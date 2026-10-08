import asyncio
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import time
import httpx
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from .store import Store, now, uid
from .seed import seed
from .pipeline_catalog import ensure_catalog
from .saddle_catalog import ensure_saddles
from .detector import CASES, assess, load_rows
from .saddle_inference import SaddleInference
from .lpg_demo import shipment_demo
from .lpg_cylinders import cylinder_catalog, cylinder_passport, journey_evidence
from .lpg_reports import customer_report
from .lpg_report_pdf import report_pdf, qr_svg
from .lpg_inspections import (KIND as LPG_INSPECTIONS, ShipmentInspectionRequest, ShipmentInspectionTransition,
    ensure_demo_inspections, create_request, transition_request, inspection_evidence)
from .evidence import MAX_BYTES, image_upload, thermal_upload, pdf_pages, report_html, VisualResult, GeminiUnavailable
from .visual_cache import request_identity, find_saved, remember_live, analysis_source_label
from .visual_provider import analyze_image, execution_profile
from .drone_flight import make_plan, start_plan, stop_plan, clock_ms

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
MISSIONS={'new':['scheduled','cancelled'],'scheduled':['in_progress','cancelled'],
          'in_progress':['review','cancelled'],'review':['completed','in_progress'], 'completed':[], 'cancelled':[]}
INSPECTIONS={'new':['assigned','cancelled'],'assigned':['visited','cancelled'],
             'visited':['result'],'result':['closed','visited'],'closed':[],'cancelled':[]}


class Login(BaseModel):
    name: str = Field(max_length=80)
    password: str = Field(max_length=256)


class MissionInput(BaseModel):
    saddle_id: str
    alert_id: str | None = None
    image_type: str = Field(default='rgb',pattern='^(rgb|thermal|both)$')
    reason: str = Field(min_length=3,max_length=2000)


class Transition(BaseModel):
    status: str
    assignee: str = Field(default='',max_length=100)
    scheduled_at: str = Field(default='',max_length=60)
    notes: str = Field(default='',max_length=4000)
    result: str = Field(default='',max_length=4000)
    ndt: str = Field(default='',max_length=4000)

    @field_validator('scheduled_at')
    @classmethod
    def valid_date(cls,value):
        if value:
            try: datetime.fromisoformat(value)
            except ValueError: raise ValueError('الموعد ليس تاريخًا صالحًا') from None
        return value


class Review(BaseModel):
    summary: str = Field(min_length=3,max_length=2000)
    observation: str = Field(min_length=3,max_length=1200)
    interpretation: str = Field(default='يلزم التحقق الميداني',max_length=1200)
    category: str = Field(pattern='^(crack_like|coating|corrosion_like|thermal|other|none)$')
    next_action: str = Field(min_length=3,max_length=1200)


class Replay(BaseModel):
    saddle_id: str='S-12'
    case: str=Field(pattern='^(ai_reference|ai_quality_control|ai_crack|ai_thermal|ai_wetness|ai_h2s|control|early_bending|early_wet_path|early_coupling|early_packet_gap|early_temperature_flatline)$')
    branch: str=Field(default='intervention',pattern='^(control|intervention)$')


class AnalysisRequest(BaseModel):
    previous_id: str | None = Field(default=None,max_length=80)
    strategy: str = Field(default='live',pattern='^(live|saved)$')


class FlightStart(BaseModel):
    restart: bool = False


def create_app(data_dir=None, admin_password=None, demo_mode=None):
    public_deployment=os.getenv('QAIF_PUBLIC_DEPLOYMENT','false').lower()=='true'
    public_base=(os.getenv('QAIF_PUBLIC_BASE_URL') or os.getenv('RENDER_EXTERNAL_URL') or '').rstrip('/')
    password=admin_password or os.getenv('QAIF_ADMIN_PASSWORD')
    if public_deployment:
        parsed=urlsplit(public_base)
        if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise RuntimeError('Set QAIF_PUBLIC_BASE_URL to the public HTTPS origin (or use RENDER_EXTERNAL_URL)')
        if not password or len(password)<12 or password=='replace-with-a-private-password':
            raise RuntimeError('Public deployment requires a private QAIF_ADMIN_PASSWORD of at least 12 characters')
        if os.getenv('QAIF_SECURE_COOKIE','false').lower()!='true':
            raise RuntimeError('Public deployment requires QAIF_SECURE_COOKIE=true')
    directory=Path(data_dir or ROOT/os.getenv('QAIF_DATA_DIR','data')).resolve()
    store=Store(directory)
    seed(store)
    ensure_catalog(store)
    ensure_saddles(store)
    saddle_ai=SaddleInference()
    if not store.all('episodes'):
        initial_rows=load_rows(ROOT/'fixtures'/'early_bending'/'control'/'observed.csv')
        initial_context=load_rows(ROOT/'fixtures'/'early_bending'/'control'/'context.csv')
        initial={'id':uid('E'),'saddle_id':'S-12','case':'control','source':'simulation','created_at':now(),
          'rows':initial_rows,'context':initial_context,'assessment':assess(initial_rows,initial_rows),
          'simulation_clock':True,'reference_scope':'matched control, research only'}
        store.put('episodes',initial,action='seed_reference')
        initial_saddle=store.get('saddles','S-12')
        initial_saddle.update(latest=initial_rows[-1],quality=initial['assessment']['quality'],episode_id=initial['id'])
        store.put('saddles',initial_saddle,action='seed_reference')
    files=directory/'files'; files.mkdir(exist_ok=True)
    demo=(os.getenv('QAIF_DEMO_MODE','true').lower()=='true') if demo_mode is None else demo_mode
    if demo: ensure_demo_inspections(store)
    if not password or password=='replace-with-a-private-password':
        password=secrets.token_urlsafe(18)
    with store.connect() as db:
        if not db.execute('SELECT name FROM users WHERE name=?',('admin',)).fetchone():
            salt=secrets.token_hex(16)
            digest=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
            db.execute('INSERT INTO users VALUES(?,?,?,?)',('admin','admin',salt,digest))
            if not public_deployment:
                (directory/'setup_credentials.txt').write_text(f'Local administrator\nUsername: admin\nPassword: {password}\nChange before public deployment.\n',encoding='utf-8')
    app=FastAPI(title='QAIF',version='0.1.0')
    app.state.store=store
    sockets=set(); attempts={}; replay_tasks={}
    for interrupted in store.all('episodes'):
        if interrupted.get('playback_status')=='running':
            interrupted['playback_status']='interrupted'
            store.put('episodes',interrupted,action='server_restart_interrupted_replay')

    def session(token):
        if not token: return None
        with store.connect() as db:
            row=db.execute('SELECT user FROM sessions WHERE token=? AND expires>?',
              (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            return json.loads(row['user']) if row else None

    def auth(request: Request):
        user=session(request.cookies.get('qaif_session'))
        if not user: raise HTTPException(401,'سجل الدخول أولًا')
        return user

    def authorize(user, roles):
        if user['role']!='admin' and user['role'] not in roles:
            raise HTTPException(403,'لا يملك دورك صلاحية هذا الإجراء')

    def get(kind, entity_id):
        value=store.get(kind,entity_id)
        if not value: raise HTTPException(404,'السجل غير موجود')
        return value

    async def broadcast(kind, entity_id):
        for socket in list(sockets):
            try: await socket.send_json({'type':'changed','kind':kind,'id':entity_id,'at':now()})
            except Exception: sockets.discard(socket)

    async def read_upload(file):
        raw=await file.read(MAX_BYTES+1)
        await file.close()
        if len(raw)>MAX_BYTES: raise HTTPException(413,'الحد الأعلى للملف 10 ميجابايت')
        return raw

    @app.middleware('http')
    async def origin_guard(request, call_next):
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if origin and origin.rstrip('/')!=str(request.base_url).rstrip('/'):
                return Response('Cross-origin mutation denied',status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        return response

    def login_response(response,user):
        token=secrets.token_urlsafe(32)
        with store.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),json.dumps(user),time.time()+8*3600))
        response.set_cookie('qaif_session',token,httponly=True,samesite='strict',max_age=8*3600,
          secure=os.getenv('QAIF_SECURE_COOKIE','false').lower()=='true')
        return user

    @app.get('/api/health')
    def health(): return {'ok':True,'app':'QAIF','version':'0.1.0','demo_mode':demo}

    def public_cylinder_summary(serial):
        if not demo: raise HTTPException(404, 'تقرير العرض غير متاح')
        try: return customer_report(serial, store.all(LPG_INSPECTIONS))
        except ValueError: raise HTTPException(404, 'لا توجد أسطوانة مسجلة بهذا الرقم التسلسلي') from None

    def cylinder_url(request, serial):
        # A configured origin keeps PDF/QR links independent of proxy Host headers.
        return (public_base or str(request.base_url).rstrip('/')) + '/cylinder/' + serial

    @app.get('/api/public/cylinders/{serial}/report')
    def public_cylinder_report(serial:str):
        return JSONResponse(public_cylinder_summary(serial), headers={'Cache-Control': 'no-store'})

    @app.get('/api/public/cylinders/{serial}/report.pdf')
    def public_cylinder_pdf(serial:str, request:Request):
        report = public_cylinder_summary(serial)
        url = cylinder_url(request, report['serial'])
        return Response(report_pdf(report, url), media_type='application/pdf',
            headers={'Content-Disposition': f'attachment; filename="Qaif-{report["serial"]}.pdf"', 'Cache-Control': 'no-store'})

    @app.get('/api/public/cylinders/{serial}/qr.svg')
    def public_cylinder_qr(serial:str, request:Request):
        # Identity validation is enough; QR does not load model evidence.
        if not demo: raise HTTPException(404, 'تقرير العرض غير متاح')
        try: canonical = cylinder_passport(serial.strip().upper())['serial']
        except ValueError: raise HTTPException(404, 'لا توجد أسطوانة مسجلة بهذا الرقم التسلسلي') from None
        url = cylinder_url(request, canonical)
        return Response(qr_svg(url), media_type='image/svg+xml')

    @app.get('/api/lpg/demo/seraj/{number}')
    def lpg_seraj_demo(number:int,user=Depends(auth)):
        if not demo: raise HTTPException(404,'عرض الشحنات التجريبي غير متاح')
        if not 1 <= number <= 21: raise HTTPException(404,'سراج الشحنة غير موجود')
        return shipment_demo(number)

    @app.get('/api/lpg/demo/cylinders')
    def lpg_cylinder_catalog(user=Depends(auth)):
        if not demo: raise HTTPException(404,'سجل الأسطوانات التجريبي غير متاح')
        return cylinder_catalog()

    @app.get('/api/lpg/demo/cylinders/{serial}')
    def lpg_cylinder_passport(serial:str,user=Depends(auth)):
        if not demo: raise HTTPException(404,'سجل الأسطوانات التجريبي غير متاح')
        try: return cylinder_passport(serial)
        except ValueError: raise HTTPException(404,'الأسطوانة غير موجودة')

    @app.get('/api/lpg/demo/cylinders/{serial}/journeys/{journey_id}')
    def lpg_cylinder_journey(serial:str,journey_id:str,until_s:float=1200,user=Depends(auth)):
        if not demo: raise HTTPException(404,'سجل الأسطوانات التجريبي غير متاح')
        if not math.isfinite(until_s) or not 0 <= until_s <= 1200:
            raise HTTPException(422,'زمن القراءات خارج نطاق الرحلة')
        try: return journey_evidence(serial,journey_id,until_s)
        except ValueError: raise HTTPException(404,'رحلة الأسطوانة غير موجودة')

    @app.get('/api/lpg/inspections')
    def shipment_inspections(user=Depends(auth)):
        if not demo: raise HTTPException(404,'مهام فحص الشحنات التجريبية غير متاحة')
        tasks=store.all(LPG_INSPECTIONS)
        return sorted(tasks,key=lambda t:(t['status'] in ('closed','cancelled'),
            {'urgent':0,'high':1,'normal':2}[t['priority']],t['created_at'],t['id']))

    @app.get('/api/lpg/inspections/{task_id}/evidence')
    def shipment_inspection_evidence(task_id:str,user=Depends(auth)):
        if not demo: raise HTTPException(404,'مهام فحص الشحنات التجريبية غير متاحة')
        return inspection_evidence(get(LPG_INSPECTIONS,task_id))

    @app.post('/api/lpg/inspections')
    async def request_shipment_inspection(body:ShipmentInspectionRequest,user=Depends(auth)):
        if not demo: raise HTTPException(404,'مهام فحص الشحنات التجريبية غير متاحة')
        authorize(user,['operator','inspector'])
        try: task=create_request(store,body,user['name'])
        except ValueError as error: raise HTTPException(409,str(error)) from None
        await broadcast(LPG_INSPECTIONS,task['id'])
        return task

    @app.post('/api/lpg/inspections/{task_id}/transition')
    async def evaluate_shipment_inspection(task_id:str,body:ShipmentInspectionTransition,user=Depends(auth)):
        if not demo: raise HTTPException(404,'مهام فحص الشحنات التجريبية غير متاحة')
        authorize(user,['inspector'])
        try: task=transition_request(store,task_id,body,user['name'])
        except KeyError: raise HTTPException(404,'مهمة فحص الشحنة غير موجودة') from None
        except ValueError as error: raise HTTPException(409,str(error)) from None
        await broadcast(LPG_INSPECTIONS,task['id'])
        return task

    @app.post('/api/auth/login')
    def login(body:Login,request:Request,response:Response):
        host=request.client.host
        recent=[t for t in attempts.get(host,[]) if time.time()-t<60]
        if len(recent)>=10: raise HTTPException(429,'حاول مجددًا بعد دقيقة')
        attempts[host]=recent+[time.time()]
        with store.connect() as db:
            row=db.execute('SELECT * FROM users WHERE name=?',(body.name,)).fetchone()
        if not row: raise HTTPException(401,'اسم المستخدم أو كلمة المرور غير صحيحة')
        digest=hashlib.scrypt(body.password.encode(),salt=bytes.fromhex(row['salt']),n=16384,r=8,p=1).hex()
        if not hmac.compare_digest(digest,row['hash']): raise HTTPException(401,'اسم المستخدم أو كلمة المرور غير صحيحة')
        attempts.pop(host,None)
        return login_response(response,{'name':body.name,'role':row['role']})

    @app.post('/api/auth/demo')
    def demo_login(request:Request,response:Response,role:str='operator'):
        if public_deployment or not demo or request.client.host not in ('127.0.0.1','::1'):
            raise HTTPException(403,'الدخول التجريبي متاح محليًا فقط')
        if role not in ('operator','drone','inspector','admin'): raise HTTPException(422,'دور غير صالح')
        return login_response(response,{'name':'عرض محلي','role':role})

    @app.get('/api/auth/me')
    def me(user=Depends(auth)): return user

    @app.post('/api/auth/logout')
    def logout(request:Request,response:Response,user=Depends(auth)):
        with store.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(request.cookies['qaif_session'].encode()).hexdigest(),))
        response.delete_cookie('qaif_session'); return {'ok':True}

    @app.post('/api/users')
    def create_user(body:dict,user=Depends(auth)):
        authorize(user,[])
        name=body.get('name',''); role=body.get('role'); new_password=body.get('password','')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{3,40}',name) or role not in ('operator','drone','inspector') or len(new_password)<12:
            raise HTTPException(422,'مطلوب اسم صحيح ودور وكلمة مرور من 12 محرفًا على الأقل')
        salt=secrets.token_hex(16)
        digest=hashlib.scrypt(new_password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
        try:
            with store.connect() as db: db.execute('INSERT INTO users VALUES(?,?,?,?)',(name,role,salt,digest))
        except Exception: raise HTTPException(409,'اسم المستخدم مستخدم') from None
        return {'name':name,'role':role}

    @app.get('/api/snapshot')
    def snapshot(user=Depends(auth)):
        kinds=['assets','saddles','pipelines','alerts','missions','captures','analyses','reports','inspections','lpg_inspections','documents','source_events','placements']
        result={k:store.all(k) for k in kinds}
        result['episodes']=[{k:v for k,v in x.items() if k not in ('rows','context','baseline','reference_rows','inference_history')} for x in store.all('episodes')]
        result['config']={'demo_mode':demo,'public_deployment':public_deployment,
          'demo_login_enabled':demo and not public_deployment,'gemini_ready':bool(os.getenv('GEMINI_API_KEY')),
          'gemini_model':os.getenv('GEMINI_MODEL','gemini-3.8-flash'),'camera_connected':False,
          'gemini_transport':execution_profile()['transport'],
          'visual_cache_fallback_enabled':bool(demo),'saved_visual_results':len(store.all('visual_cache')),
          'gemini_free_quota_verified':False, 'saddle_ai':saddle_ai.config()}
        return result

    @app.get('/api/episodes/{episode_id}')
    def episode(episode_id:str,user=Depends(auth)): return get('episodes',episode_id)

    @app.get('/api/history/{entity_id}')
    def history(entity_id:str,user=Depends(auth)): return store.history(entity_id)

    async def save_episode(saddle_id,rows,context,baseline,source,case,actor,baseline_verified=False,existing=None,fixture=None):
        if saddle_id in replay_tasks and not replay_tasks[saddle_id].done():
            raise HTTPException(409,'أوقف التشغيل المتدرج قبل استيراد تشغيل آخر')
        saddle=get('saddles',saddle_id)
        episode_id=existing['id'] if existing else uid('E')
        previous_rows=existing.get('rows',[]) if existing else []
        if previous_rows and rows[0]['timestamp_s']<=previous_rows[-1]['timestamp_s']:
            raise HTTPException(422,'زمن الدفعة الجديدة يجب أن يتبع آخر قراءة محفوظة دون تكرار')
        if existing: baseline_verified=existing.get('baseline_verified',False)
        session=saddle_ai.session(saddle_id,episode_id,previous_rows,baseline_verified,case in CASES)
        session.feed(rows)
        all_rows=previous_rows+rows
        result=session.result(all_rows,baseline)
        episode={**(existing or {}),'id':episode_id,'saddle_id':saddle_id,'case':case,'source':source,
          'created_at':existing['created_at'] if existing else now(),'last_reading_at':now(),
          'rows':all_rows,'context':(existing.get('context',[]) if existing else [])+context,
          'assessment':result,'reference_rows':baseline,'baseline_verified':baseline_verified,
          'inference_history':session.history,'fixture':fixture or (existing.get('fixture') if existing else None),
          'simulation_clock':source=='simulation','reference_scope':'matched control, research only' if baseline else None}
        store.put('episodes',episode,actor,'ingest')
        saddle.update(latest=all_rows[-1] if all_rows else None,quality=result['quality'],episode_id=episode['id'],source=source,
                      ai=result['ai'],last_reading_at=episode['last_reading_at'])
        store.put('saddles',saddle,actor,'readings')
        emitted={(a.get('basis'),a.get('category'),a.get('title')) for a in store.all('alerts') if a.get('episode_id')==episode_id}
        for finding in result['alerts']:
            if (finding.get('basis'),finding['category'],finding['title']) in emitted: continue
            store.put('alerts',{'id':uid('A'),'saddle_id':saddle_id,'episode_id':episode['id'],
              'created_at':now(),'status':'new','source':source,**finding},actor,'detected')
        await broadcast('episodes',episode['id'])
        return {k:v for k,v in episode.items() if k not in ('rows','context','reference_rows','inference_history')}

    def replay_data(body):
        if body.case.startswith('ai_'):
            directory=ROOT/'fixtures'/'saddle_ai'
            manifest=json.loads((directory/'manifest.json').read_text())
            path=directory/body.case/'observed.csv'
            if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest[body.case]['sha256']:
                raise HTTPException(500,'ملف عرض النموذج لا يطابق نسخته المثبتة')
            return load_rows(path),[],None,True,manifest[body.case]
        case='early_bending' if body.case=='control' else body.case
        branch='control' if body.case=='control' else body.branch
        directory=ROOT/'fixtures'/case
        return load_rows(directory/branch/'observed.csv'),load_rows(directory/branch/'context.csv'),load_rows(directory/'control'/'observed.csv'),False,None

    @app.post('/api/demo/replay')
    async def replay(body:Replay,user=Depends(auth)):
        authorize(user,['operator'])
        if not demo: raise HTTPException(403,'وضع المحاكاة معطل')
        rows,context,baseline,verified,fixture=replay_data(body)
        return await save_episode(body.saddle_id,rows,context,baseline,'simulation',body.case,user['name'],verified,fixture=fixture)

    @app.post('/api/demo/stream')
    async def stream_replay(body:Replay,user=Depends(auth)):
        authorize(user,['operator'])
        if not demo: raise HTTPException(403,'وضع المحاكاة معطل')
        get('saddles',body.saddle_id)
        if body.saddle_id in replay_tasks and not replay_tasks[body.saddle_id].done():
            raise HTTPException(409,'هناك تشغيل متدرج جارٍ لهذه النقطة')
        rows,context,baseline,verified,fixture=replay_data(body)
        episode_id=uid('E'); created=now()
        value={'id':episode_id,'saddle_id':body.saddle_id,'case':body.case,'source':'simulation',
          'created_at':created,'rows':[],'context':[],'reference_rows':[] if baseline else None,'simulation_clock':True,
          'baseline_verified':verified,'fixture':fixture,'playback_status':'running','progress':0,
          'reference_scope':'matched control, research only' if baseline else None}
        session=saddle_ai.session(body.saddle_id,episode_id,baseline_verified=verified,legacy=body.case in CASES)
        value['assessment']=session.result([],[] if baseline else None)
        store.put('episodes',value,user['name'],'start_playback')
        async def playback():
            emitted=set()
            try:
                for start in range(0,len(rows),12):
                    end=min(start+12,len(rows)); session.feed(rows[start:end])
                    result=session.result(rows[:end],baseline[:end] if baseline else None)
                    value.update(rows=rows[:end],context=context[:end],reference_rows=baseline[:end] if baseline else None,assessment=result,
                      inference_history=session.history,last_reading_at=now(),
                      progress=round(end/len(rows)*100),playback_status='completed' if end==len(rows) else 'running')
                    store.put('episodes',value,user['name'],'playback_progress')
                    saddle=get('saddles',body.saddle_id)
                    saddle.update(latest=rows[end-1],quality=result['quality'],episode_id=episode_id,source='simulation',
                                  ai=result['ai'],last_reading_at=value['last_reading_at'])
                    store.put('saddles',saddle,user['name'],'replay_sample')
                    for finding in result['alerts']:
                        signature=(finding.get('basis'),finding['category'],finding['title'])
                        if signature not in emitted:
                            store.put('alerts',{'id':uid('A'),'saddle_id':body.saddle_id,'episode_id':episode_id,
                              'created_at':now(),'status':'new','source':'simulation',**finding},user['name'],'detected')
                            emitted.add(signature)
                    await broadcast('episodes',episode_id)
                    if end<len(rows): await asyncio.sleep(.5)
            except asyncio.CancelledError:
                value['playback_status']='stopped'; store.put('episodes',value,user['name'],'stop_playback')
                await broadcast('episodes',episode_id)
            except Exception:
                value.update(playback_status='failed',error='تعذر إكمال التشغيل؛ آخر قراءات محفوظة')
                store.put('episodes',value,user['name'],'failed_playback')
                await broadcast('episodes',episode_id)
        replay_tasks[body.saddle_id]=asyncio.create_task(playback())
        return {'id':episode_id,'status':'running'}

    @app.post('/api/demo/stop/{saddle_id}')
    async def stop_replay(saddle_id:str,user=Depends(auth)):
        authorize(user,['operator'])
        task=replay_tasks.get(saddle_id)
        if not task or task.done(): raise HTTPException(409,'لا يوجد تشغيل جارٍ')
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        return {'ok':True}

    @app.post('/api/demo/signal')
    async def demo_signal(body:dict,user=Depends(auth)):
        authorize(user,['operator'])
        if not demo: raise HTTPException(403,'وضع المحاكاة معطل')
        saddle_id=body.get('saddle_id','S-12'); get('saddles',saddle_id)
        category=body.get('category','thermal')
        titles={'thermal':'إشارة اختبار حرارية من السرج','mechanical':'إشارة اختبار انفعال من السرج','wetness':'إشارة اختبار بلل ومراجعة الطلاء'}
        if category not in titles: raise HTTPException(422,'مسار اختبار غير صالح')
        value=store.put('alerts',{'id':uid('A'),'saddle_id':saddle_id,'episode_id':None,'category':category,
          'title':titles[category],'priority':'medium','created_at':now(),'status':'new','source':'manual_demo',
          'basis':'operator_demo_control','note':'محاكاة إشارة اختارها مشغل العرض؛ لم تستنتجها قواعد القراءات أو جهاز حقيقي.'},user['name'],'manual_demo_signal')
        await broadcast('alerts',value['id']); return value

    @app.post('/api/saddles/{saddle_id}/readings')
    async def readings(saddle_id:str,body:dict,user=Depends(auth)):
        authorize(user,['operator'])
        saddle=get('saddles',saddle_id)
        rows=body.get('rows'); context=body.get('context',[])
        if not isinstance(rows,list) or not 1<=len(rows)<=10000: raise HTTPException(422,'مطلوب 1–10000 قراءة')
        if not isinstance(context,list): raise HTTPException(422,'سياق القراءات يجب أن يكون قائمة')
        verified=body.get('baseline_verified',False)
        if not isinstance(verified,bool): raise HTTPException(422,'تأكيد التهيئة يجب أن يكون قيمة منطقية')
        required=['timestamp_s','strain_hoop_microstrain','strain_axial_microstrain','temperature_k','wetness_index']
        previous=-math.inf
        for row in rows:
            if not isinstance(row,dict) or not isinstance(row.get('packet_valid'),bool): raise HTTPException(422,'حزمة غير صالحة')
            for column in required:
                v=row.get(column)
                if v is None and column!='timestamp_s' and not row['packet_valid']: continue
                if isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v): raise HTTPException(422,'قيم غير صالحة أو غير محدودة')
            if row['timestamp_s']<=previous: raise HTTPException(422,'الزمن يجب أن يتزايد دون تكرار')
            previous=row['timestamp_s']
            if 'h2s_valid' in row and not isinstance(row['h2s_valid'],bool): raise HTTPException(422,'صلاحية قناة H₂S يجب أن تكون قيمة منطقية')
            gas=row.get('h2s_ppm')
            if gas is not None and (isinstance(gas,bool) or not isinstance(gas,(float,int)) or not math.isfinite(gas)):
                raise HTTPException(422,'قراءة H₂S يجب أن تكون رقمًا محدودًا أو فارغة')
            if row.get('h2s_valid') is True and gas is None: raise HTTPException(422,'قناة H₂S الصالحة تحتاج قراءة رقمية')
            if 'h2s_status' in row and (not isinstance(row['h2s_status'],str) or len(row['h2s_status'])>64): raise HTTPException(422,'حالة H₂S غير صالحة')
        source=body.get('source','imported')
        if source not in ('imported','device'): raise HTTPException(422,'مصدر غير صالح')
        if len(json.dumps(body,allow_nan=False))>MAX_BYTES: raise HTTPException(413,'البيانات كبيرة جدًا')
        mode=body.get('mode','append' if source=='device' else 'new')
        if mode not in ('new','append'): raise HTTPException(422,'طريقة الاستيراد غير صالحة')
        existing=None
        if mode=='append':
            explicit=body.get('episode_id')
            if explicit is not None and (not isinstance(explicit,str) or len(explicit)>80): raise HTTPException(422,'معرّف التشغيل غير صالح')
            candidate=get('episodes',explicit) if explicit else store.get('episodes',saddle.get('episode_id')) if saddle.get('episode_id') else None
            if explicit and (candidate['saddle_id']!=saddle_id or candidate['id']!=saddle.get('episode_id') or candidate['source']!=source):
                raise HTTPException(409,'الدفعة لا تتبع تشغيل هذا السرج الحالي ومصدره')
            if candidate and candidate['source']==source and candidate.get('case')=='imported': existing=candidate
            if existing and verified and not existing.get('baseline_verified',False):
                raise HTTPException(409,'لا يمكن اعتماد التهيئة بعد بدء التشغيل؛ ابدأ تشغيلًا جديدًا بتهيئة سليمة')
        return await save_episode(saddle_id,rows,context,None,source,'imported',user['name'],verified,existing)

    @app.post('/api/alerts/{alert_id}/ack')
    async def acknowledge(alert_id:str,user=Depends(auth)):
        authorize(user,['operator','inspector'])
        alert=get('alerts',alert_id)
        alert.update(status='acknowledged',ack_by=user['name'])
        store.put('alerts',alert,user['name'],'acknowledge'); await broadcast('alerts',alert_id)
        return alert

    @app.post('/api/missions')
    async def mission(body:MissionInput,user=Depends(auth)):
        authorize(user,['operator','drone'])
        saddle=get('saddles',body.saddle_id)
        if body.alert_id and get('alerts',body.alert_id)['saddle_id']!=body.saddle_id: raise HTTPException(422,'التنبيه يتبع سرجًا آخر')
        value=store.put('missions',{'id':uid('D'),'status':'new','created_at':now(),**body.model_dump(),
          'requested_by':user['name'],'assignee':'','scheduled_at':'',
          'virtual_flight':make_plan(saddle,store.all('assets'),start=True)},user['name'],'create')
        await broadcast('missions',value['id']); return value

    @app.get('/api/missions/{mission_id}/flight')
    async def flight_plan(mission_id:str,user=Depends(auth)):
        current=get('missions',mission_id)
        plan=current.get('virtual_flight') or make_plan(get('saddles',current['saddle_id']),store.all('assets'))
        return {'plan':plan,'server_now_ms':clock_ms()}

    @app.post('/api/missions/{mission_id}/flight/start')
    async def flight_start(mission_id:str,body:FlightStart,user=Depends(auth)):
        authorize(user,['operator','drone'])
        current=get('missions',mission_id)
        if current['status']=='cancelled': raise HTTPException(409,'الطلب ملغى؛ لا يمكن بدء استعراض رحلته')
        plan=current.get('virtual_flight')
        if plan and plan.get('started_ms') is not None and not body.restart:
            return {'plan':plan,'server_now_ms':clock_ms()}
        plan=plan or make_plan(get('saddles',current['saddle_id']),store.all('assets'))
        if plan is None: raise HTTPException(409,'يحتاج المسار موقع سرج ومرفق انطلاق صالحين')
        current['virtual_flight']=start_plan(plan)
        store.put('missions',current,user['name'],'start_virtual_display')
        await broadcast('missions',mission_id)
        return {'plan':current['virtual_flight'],'server_now_ms':clock_ms()}

    @app.post('/api/missions/{mission_id}/transition')
    async def mission_transition(mission_id:str,body:Transition,user=Depends(auth)):
        authorize(user,['drone','operator'])
        current=get('missions',mission_id)
        if body.status=='cancelled' and not body.notes.strip(): raise HTTPException(422,'اكتب سبب الإلغاء')
        if body.status=='scheduled' and (not body.assignee.strip() or not body.scheduled_at): raise HTTPException(422,'حدد المشغل والموعد')
        if body.status in ('review','completed') and not any(c['mission_id']==mission_id for c in store.all('captures')): raise HTTPException(409,'أرفق صورة قبل المراجعة')
        if body.status=='completed' and not any(a['mission_id']==mission_id and a['status']=='completed' for a in store.all('analyses')): raise HTTPException(409,'المهمة تحتاج نتيجة تحليل أو مراجعة بشرية')
        changes={k:v for k,v in body.model_dump().items() if k!='status' and v}
        if body.status=='cancelled' and current.get('virtual_flight'):
            changes['virtual_flight']=stop_plan(current['virtual_flight'])
        try: value=store.transition('missions',mission_id,body.status,MISSIONS,changes,user['name'])
        except ValueError as error: raise HTTPException(409,str(error)) from None
        await broadcast('missions',mission_id); return value

    @app.post('/api/missions/{mission_id}/captures')
    async def capture(mission_id:str,file:UploadFile=File(...),mode:str=Form('rgb'),captured_at:str=Form(''),
      source:str=Form('uploaded'),note:str=Form(''),user=Depends(auth)):
        authorize(user,['drone','operator'])
        mission=get('missions',mission_id)
        if mission['status'] not in ('in_progress','review'): raise HTTPException(409,'ابدأ الجولة قبل رفع الصورة')
        if mode not in ('rgb','thermal') or source not in ('uploaded','camera_export','prepared_demo'): raise HTTPException(422,'نوع الصورة أو المصدر غير صالح')
        if len(note)>2000 or len(captured_at)>80: raise HTTPException(422,'وصف طويل جدًا')
        if captured_at:
            try: datetime.fromisoformat(captured_at)
            except ValueError: raise HTTPException(422,'وقت التصوير غير صالح') from None
        capture_id=uid('C'); name=capture_id+'.jpg'
        try: metadata=image_upload(await read_upload(file),files/name)
        except ValueError as error: raise HTTPException(422,str(error)) from None
        value=store.put('captures',{'id':capture_id,'mission_id':mission_id,'saddle_id':mission['saddle_id'],
          'file':name,'mode':mode,'source':source,'note':note,'captured_at':captured_at or None,
          'uploaded_at':now(),'created_at':now(),'thermal':None,**metadata},user['name'],'upload')
        await broadcast('captures',capture_id); return value

    @app.post('/api/captures/{capture_id}/thermal')
    async def thermal(capture_id:str,file:UploadFile=File(...),units:str=Form('C'),roi:str=Form('[0,0,1,1]'),
      calibrated:bool=Form(False),user=Depends(auth)):
        authorize(user,['drone','operator'])
        capture=get('captures',capture_id)
        if capture['mode']!='thermal': raise HTTPException(422,'اختر صورة حرارية')
        try:
            region=json.loads(roi)
            if not isinstance(region,list) or len(region)!=4: raise ValueError('منطقة غير صالحة')
            capture['thermal']=thermal_upload(await read_upload(file),units,region,calibrated)
        except (ValueError,TypeError) as error: raise HTTPException(422,str(error)) from None
        store.put('captures',capture,user['name'],'import_temperature'); await broadcast('captures',capture_id)
        return capture

    def analysis_evidence(capture_id,previous_id):
        capture=get('captures',capture_id); previous=None
        if previous_id:
            old=get('captures',previous_id)
            if old['saddle_id']!=capture['saddle_id'] or old['id']==capture_id or old['mode']!=capture['mode']:
                raise HTTPException(422,'اختر صورة سابقة من النوع نفسه لنفس السرج')
            previous=files/old['file']
        return capture,previous

    @app.get('/api/captures/{capture_id}/analysis-cache')
    def saved_availability(capture_id:str,previous_id:str|None=None,user=Depends(auth)):
        capture,previous=analysis_evidence(capture_id,previous_id)
        identity=request_identity(files/capture['file'],capture['mode'],os.getenv('GEMINI_MODEL','gemini-3.8-flash'),previous,
          execution_profile=execution_profile())
        saved=find_saved(store,identity) if demo else None
        return {'available':bool(saved),'enabled':bool(demo),'original_analyzed_at':saved['analyzed_at'] if saved else None}

    @app.post('/api/captures/{capture_id}/analyze')
    async def analyze(capture_id:str,body:AnalysisRequest,user=Depends(auth)):
        authorize(user,['drone','operator','inspector'])
        if body.strategy=='saved' and not demo:
            raise HTTPException(403,'عرض التحليل المحفوظ متاح في وضع العرض التجريبي فقط')
        capture,previous=analysis_evidence(capture_id,body.previous_id)
        value={'id':uid('V'),'capture_id':capture_id,'mission_id':capture['mission_id'],
          'saddle_id':capture['saddle_id'],'previous_id':body.previous_id,'provider':'gemini',
          'model':os.getenv('GEMINI_MODEL','gemini-3.8-flash'),'created_at':now(),'status':'pending',
          'execution_mode':'live','requested_strategy':body.strategy,'execution_profile':execution_profile()}
        identity=request_identity(files/capture['file'],capture['mode'],value['model'],previous,
          execution_profile=value['execution_profile'])
        value['request_identity']=identity
        store.put('analyses',value,user['name'],'request')

        def use_saved(reason):
            saved=find_saved(store,identity) if demo else None
            if not saved: return False
            value.update(result=saved['result'],status='completed',execution_mode='cached',
              original_analysis_id=saved['source_analysis_id'],original_capture_id=saved['source_capture_id'],
              original_analyzed_at=saved['analyzed_at'],fallback_reason=reason,
              source_notice='تحليل محفوظ للصورة نفسها؛ لم يُجرَ تحليل حي لهذا الطلب')
            origin=store.get('analyses',saved['source_analysis_id'])
            if origin.get('provider_metadata'):
                value['original_provider_metadata']=origin['provider_metadata']
            return True

        try:
            if body.strategy=='saved':
                if not use_saved('operator_selected_saved'):
                    value.update(status='failed',error='لا يوجد تحليل Gemini محفوظ مطابق لهذه الصورة والمقارنة؛ حلّلها حيًا أولًا')
            else:
                value['provider_metadata']={}
                value['result']=await analyze_image(files/capture['file'],capture['mode'],os.getenv('GEMINI_API_KEY',''),value['model'],previous,
                  profile=value['execution_profile'],metadata=value['provider_metadata'])
                value['status']='completed'
        except (GeminiUnavailable,httpx.HTTPError,TimeoutError,ConnectionError) as error:
            reason=error.reason if isinstance(error,GeminiUnavailable) else 'connection_unavailable'
            message=str(error)[:1000] if isinstance(error,GeminiUnavailable) else 'تعذر الاتصال بمزود التحليل'
            value['live_error']=message
            if not use_saved(reason):
                value.update(status='failed',error=message+'؛ لا يوجد تحليل محفوظ مطابق لهذه الصورة والمقارنة')
        except Exception as error:
            value.update(status='failed',error='تعذر التحقق من استجابة التحليل؛ أعد المحاولة أو أضف مراجعة بشرية')
            value.pop('result',None)
        value=store.put('analyses',value,user['name'],value['status'])
        if value['status']=='completed' and value['execution_mode']=='live':
            remember_live(store,identity,value,user['name'])
        await broadcast('analyses',value['id'])
        return value

    @app.post('/api/captures/{capture_id}/review')
    async def review(capture_id:str,body:Review,user=Depends(auth)):
        authorize(user,['inspector','operator'])
        capture=get('captures',capture_id)
        result={'summary':body.summary,'image_quality':'limited','findings':[{'observation':body.observation,
          'interpretation':body.interpretation,'category':body.category,'certainty':'low','box':None}],
          'limitations':['مراجعة بشرية للصورة؛ لا تحدد عمق العيب أو تؤكد سلامة الأنبوب'], 'next_action':body.next_action}
        value=store.put('analyses',{'id':uid('V'),'capture_id':capture_id,'saddle_id':capture['saddle_id'],
          'mission_id':capture['mission_id'],'provider':'human','reviewer':user['name'],'created_at':now(),
          'status':'completed','result':result},user['name'],'human_review')
        await broadcast('analyses',value['id']); return value

    @app.post('/api/missions/{mission_id}/report')
    async def make_report(mission_id:str,user=Depends(auth)):
        authorize(user,['operator','drone','inspector'])
        mission=get('missions',mission_id); saddle=get('saddles',mission['saddle_id'])
        analyses=[a for a in store.all('analyses') if a['mission_id']==mission_id and a['status']=='completed']
        captures=[c for c in store.all('captures') if c['mission_id']==mission_id]
        if not analyses: raise HTTPException(409,'أضف نتيجة مراجعة قبل إنشاء التقرير')
        observations=[]; limitations=['تشخيص الشقوق والتسرب والإجهاد يحتاج تحققًا ميدانيًا.', 'بيانات السرج في العرض محاكاة ما لم يصرح المصدر خلاف ذلك.']
        for analysis in analyses:
            if analysis.get('execution_mode')=='cached':
                limitations.append(analysis_source_label(analysis))
            observations.append(analysis['result']['summary'])
            for finding in analysis['result']['findings']:
                observations.append('المشاهدة: '+finding['observation']+' · التفسير المحتمل: '+finding['interpretation'])
            limitations.extend(analysis['result']['limitations'])
        for capture in captures:
            if capture.get('thermal'):
                observations.append(f"المصفوفة المستوردة: Tmax {capture['thermal']['tmax_c']} °C، فرق عن وسيط منطقة الأنبوب {capture['thermal']['delta_c']} °C")
                limitations.append(capture['thermal']['note'])
        alert=get('alerts',mission['alert_id']) if mission.get('alert_id') else None
        episode=get('episodes',alert['episode_id']) if alert and alert.get('episode_id') else None
        sources=[{**event,'file':get('documents',event['document_id'])['file']}
                 for event in store.all('source_events') if event['saddle_id']==saddle['id']]
        value={'id':uid('R'),'mission_id':mission_id,'saddle_id':saddle['id'],'asset_name':saddle['name'],
          'created_at':now(),'status':'draft','analysis_ids':[a['id'] for a in analyses],
          'capture_ids':[c['id'] for c in captures],'episode_id':episode['id'] if episode else None,
          'facts':{'مهمة التصوير':mission_id,'سبب الطلب':mission['reason'],'مصدر التنبيه':alert['source'] if alert else 'طلب يدوي', 'مصدر صور الجولة':', '.join(c['source'] for c in captures),
            'التحليل':', '.join(analysis_source_label(a) for a in analyses),
            'مرجع القراءات':episode['id'] if episode else 'لم يُربط تنبيه قراءات بهذه المهمة',
            'حالة الاعتماد':'مسودة لمراجعة المفتش'},'observations':observations,'limitations':list(dict.fromkeys(limitations)),
          'recommendation':analyses[0]['result']['next_action'],'sources':sources}
        store.put('reports',value,user['name'],'generate_report'); await broadcast('reports',value['id']); return value

    @app.get('/api/reports/{report_id}/print',response_class=HTMLResponse)
    def print_report(report_id:str,user=Depends(auth)): return report_html(get('reports',report_id))

    @app.get('/api/reports/{report_id}/json')
    def json_report(report_id:str,user=Depends(auth)):
        report=get('reports',report_id)
        return JSONResponse(report,headers={'Content-Disposition':f'attachment; filename="{report_id}.json"'})

    @app.post('/api/inspections')
    async def inspection(body:dict,user=Depends(auth)):
        authorize(user,['operator','inspector'])
        saddle=get('saddles',body.get('saddle_id','')); reason=body.get('reason','')
        if not isinstance(reason,str) or not 3<=len(reason)<=2000: raise HTTPException(422,'اكتب الفحص المطلوب')
        report_id=body.get('report_id')
        if report_id and get('reports',report_id)['saddle_id']!=saddle['id']: raise HTTPException(422,'التقرير يتبع سرجًا آخر')
        value=store.put('inspections',{'id':uid('F'),'saddle_id':saddle['id'],'reason':reason,
          'report_id':report_id,'status':'new','created_at':now(),'requested_by':user['name']},user['name'],'create')
        await broadcast('inspections',value['id']); return value

    @app.post('/api/inspections/{inspection_id}/transition')
    async def inspection_transition(inspection_id:str,body:Transition,user=Depends(auth)):
        authorize(user,['inspector'])
        if body.status=='assigned' and not body.assignee.strip(): raise HTTPException(422,'حدد المفتش')
        if body.status=='result' and not body.result.strip(): raise HTTPException(422,'اكتب النتيجة')
        if body.status=='closed' and not body.notes.strip(): raise HTTPException(422,'اكتب قرار الإغلاق')
        if body.status=='cancelled' and not body.notes.strip(): raise HTTPException(422,'اكتب سبب الإلغاء')
        changes={k:v for k,v in body.model_dump().items() if k!='status' and v}
        try: value=store.transition('inspections',inspection_id,body.status,INSPECTIONS,changes,user['name'])
        except ValueError as error: raise HTTPException(409,str(error)) from None
        if body.status=='closed' and value.get('report_id'):
            report=get('reports',value['report_id']); report.update(status='reviewed',reviewed_by=user['name'],decision=body.notes)
            report['facts']['حالة الاعتماد']='راجعه المفتش · '+body.notes
            store.put('reports',report,user['name'],'reviewed')
        await broadcast('inspections',inspection_id); return value

    @app.post('/api/documents')
    async def document(file:UploadFile=File(...),saddle_id:str=Form(...),user=Depends(auth)):
        authorize(user,['operator','inspector']); get('saddles',saddle_id)
        raw=await read_upload(file)
        try: pages=pdf_pages(raw)
        except ValueError as error: raise HTTPException(422,str(error)) from None
        entity_id=uid('PDF'); name=entity_id+'.pdf'; (files/name).write_bytes(raw)
        value=store.put('documents',{'id':entity_id,'saddle_id':saddle_id,'name':Path(file.filename or 'report.pdf').name[:200],
          'file':name,'created_at':now(),'pages':pages,'status':'review_required',
          'extraction':'text_only','note':'لا تُضاف واقعة تلقائيًا؛ اختر النص والصفحة واعتمدها. PDF المصور يحتاج OCR.'},user['name'],'extract_pdf')
        await broadcast('documents',entity_id); return value

    @app.post('/api/documents/{document_id}/events')
    async def document_event(document_id:str,body:dict,user=Depends(auth)):
        authorize(user,['operator','inspector']); document=get('documents',document_id)
        page=next((p for p in document['pages'] if p['page']==body.get('page')),None)
        quote=body.get('quote',''); summary=body.get('summary',''); event_date=body.get('event_date','')
        event_type=body.get('event_type','inspection')
        if event_type not in ('repair','inspection','other'): raise HTTPException(422,'نوع الواقعة غير صالح')
        if not page or not isinstance(quote,str) or not 3<=len(quote)<=4000 or quote not in page['text']:
            raise HTTPException(422,'اختر اقتباسًا موجودًا حرفيًا في الصفحة')
        if not isinstance(summary,str) or not 3<=len(summary)<=2000 or len(str(event_date))>60: raise HTTPException(422,'أضف وصفًا صالحًا')
        value=store.put('source_events',{'id':uid('H'),'saddle_id':document['saddle_id'],'document_id':document_id,
          'page':body['page'],'quote':quote,'summary':summary,'event_date':event_date,'event_type':event_type,'created_at':now(),'approved_by':user['name']},user['name'],'approve_source_event')
        if event_type=='repair':
            saddle=get('saddles',document['saddle_id']); saddle['prior_repair']=True
            store.put('saddles',saddle,user['name'],'verified_repair_history')
        await broadcast('source_events',value['id']); return value

    @app.get('/api/placements')
    def recommendations(user=Depends(auth)):
        return [{'saddle_id':s['id'],'score':3*int(s['weld'])+2*int(s['wet_exposure'])+4*int(s['prior_repair']),
          'reasons':[label for yes,label in [(s['weld'],'لحام: +3'),(s['wet_exposure'],'تعرض للبلل: +2'),(s['prior_repair'],'إصلاح سابق: +4')] if yes],
          'note':'درجة أولوية معلنة؛ ليست احتمال عطل ولا مدى كشف'} for s in store.all('saddles')]

    @app.post('/api/placements')
    async def placement(body:dict,user=Depends(auth)):
        authorize(user,['operator','inspector']); get('saddles',body.get('saddle_id',''))
        decision=body.get('decision'); notes=body.get('notes','')
        if decision not in ('approved','rejected') or not isinstance(notes,str) or not 3<=len(notes)<=2000: raise HTTPException(422,'حدد القرار ومبرره')
        value=store.put('placements',{'id':uid('PL'),'saddle_id':body['saddle_id'],'decision':decision,'notes':notes,
          'created_at':now(),'reviewed_by':user['name']},user['name'],'placement_decision')
        await broadcast('placements',value['id']); return value

    @app.get('/api/files/{filename}')
    def evidence_file(filename:str,user=Depends(auth)):
        if not re.fullmatch(r'(C|PDF)-[a-f0-9]{10}\.(jpg|pdf)',filename): raise HTTPException(404,'ملف غير موجود')
        path=files/filename
        if not path.is_file(): raise HTTPException(404,'ملف غير موجود')
        return FileResponse(path)

    @app.websocket('/ws/events')
    async def events(socket:WebSocket):
        origin=socket.headers.get('origin')
        if origin and origin.split('://',1)[-1]!=socket.headers.get('host'): await socket.close(code=1008); return
        if not session(socket.cookies.get('qaif_session')): await socket.close(code=1008); return
        await socket.accept(); sockets.add(socket)
        try:
            while True:
                await asyncio.wait_for(socket.receive_text(),timeout=60)
                if not session(socket.cookies.get('qaif_session')): await socket.close(code=1008); break
                await socket.send_json({'type':'pong'})
        except (WebSocketDisconnect,asyncio.TimeoutError): pass
        finally: sockets.discard(socket)

    dist=ROOT/'frontend'/'dist'
    @app.get('/{path:path}')
    def frontend(path:str):
        if path.startswith(('api/','ws/')): raise HTTPException(404,'مسار غير موجود')
        candidate=(dist/path).resolve()
        if candidate.is_relative_to(dist.resolve()) and candidate.is_file(): return FileResponse(candidate)
        if (dist/'index.html').is_file(): return FileResponse(dist/'index.html')
        return HTMLResponse('<p>Build frontend: npm --prefix frontend run build</p>',status_code=503)

    return app


app=create_app()
