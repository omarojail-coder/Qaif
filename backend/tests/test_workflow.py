import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from reportlab.pdfgen import canvas

from backend.app import create_app, ROOT
from backend.detector import assess, load_rows


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name)
        self.client=TestClient(create_app(self.directory,admin_password='test-only-private-password',demo_mode=True))
        self.client.__enter__()
        self.assertEqual(self.client.post('/api/auth/login',json={'name':'admin','password':'test-only-private-password'}).status_code,200)

    def tearDown(self):
        self.client.__exit__(None,None,None); self.client.close(); self.temp.cleanup()

    def post(self,path,body,status=200):
        result=self.client.post('/api'+path,json=body)
        self.assertEqual(result.status_code,status,result.text)
        return result.json()

    def image(self):
        data=io.BytesIO(); Image.new('RGB',(200,150),'gray').save(data,format='PNG'); return data.getvalue()

    def mission(self):
        mission=self.post('/missions',{'saddle_id':'S-12','image_type':'rgb','reason':'Visual inspection request'})
        self.post('/missions/'+mission['id']+'/transition',{'status':'scheduled','assignee':'Drone operator','scheduled_at':'2026-10-05T10:00:00+03:00'})
        self.post('/missions/'+mission['id']+'/transition',{'status':'in_progress'})
        result=self.client.post('/api/missions/'+mission['id']+'/captures',files={'file':('photo.png',self.image(),'image/png')},data={'mode':'rgb','source':'prepared_demo'})
        self.assertEqual(result.status_code,200,result.text)
        return mission,result.json()

    def test_complete_workflow_and_restart(self):
        replay=self.post('/demo/replay',{'case':'early_bending','saddle_id':'S-12'})
        self.assertTrue(any(a['category']=='mechanical' for a in replay['assessment']['alerts']))
        mission,capture=self.mission()
        self.post('/missions/'+mission['id']+'/transition',{'status':'completed'},409)
        review=self.post('/captures/'+capture['id']+'/review',{'summary':'Surface feature observed',
          'observation':'A line is visible; test fixture image only','interpretation':'Cannot diagnose from this fixture',
          'category':'other','next_action':'Inspector to verify on site'})
        self.assertEqual(review['provider'],'human')
        self.post('/missions/'+mission['id']+'/transition',{'status':'review'})
        self.post('/missions/'+mission['id']+'/transition',{'status':'completed'})
        report=self.post('/missions/'+mission['id']+'/report',{})
        self.assertEqual(report['status'],'draft')
        html=self.client.get('/api/reports/'+report['id']+'/print')
        self.assertEqual(html.status_code,200); self.assertIn('window.print()',html.text)
        inspection=self.post('/inspections',{'saddle_id':'S-12','reason':'Verify surface feature','report_id':report['id']})
        for status,fields in [('assigned',{'assignee':'Inspector'}),('visited',{}),('result',{'result':'Visual review completed','ndt':'No NDT measurement taken'}),('closed',{'notes':'Follow-up required; no safety certification'})]:
            self.post('/inspections/'+inspection['id']+'/transition',{'status':status,**fields})
        self.post('/inspections/'+inspection['id']+'/transition',{'status':'visited'},409)
        client=TestClient(create_app(self.directory,admin_password='irrelevant',demo_mode=False))
        client.post('/api/auth/login',json={'name':'admin','password':'test-only-private-password'})
        snapshot=client.get('/api/snapshot').json()
        self.assertEqual(snapshot['inspections'][0]['status'],'closed')
        self.assertEqual(snapshot['reports'][0]['status'],'reviewed')
        self.assertTrue(client.get('/api/files/'+capture['file']).content.startswith(b'\xff\xd8'))
        self.assertGreaterEqual(len(client.get('/api/history/'+inspection['id']).json()),5)
        client.close()

    def test_rules_and_negative_controls(self):
        expected={'early_bending':{'mechanical'},'early_wet_path':{'wetness'},'early_coupling':{'sensor_fault'},
          'early_packet_gap':{'sensor_fault'},'early_temperature_flatline':{'sensor_fault'}}
        for case,categories in expected.items():
            a=load_rows(ROOT/'fixtures'/case/'intervention'/'observed.csv')
            b=load_rows(ROOT/'fixtures'/case/'control'/'observed.csv')
            self.assertEqual(assess(b,b)['alerts'],[],case)
            self.assertEqual({x['category'] for x in assess(a,b)['alerts']},categories,case)

    def test_permissions_and_sessions(self):
        self.post('/users',{'name':'inspector_1','role':'inspector','password':'private-inspector-password'})
        self.post('/auth/logout',{})
        self.assertEqual(self.client.get('/api/snapshot').status_code,401)
        self.assertEqual(self.client.get('/api/files/C-0123456789.jpg').status_code,401)
        self.post('/auth/login',{'name':'inspector_1','password':'private-inspector-password'})
        self.post('/demo/replay',{'case':'control'},403)
        self.post('/missions',{'saddle_id':'S-12','reason':'not allowed'},403)
        self.client.post('/api/auth/logout',json={})
        self.post('/auth/demo?role=admin',{},403)

    def test_invalid_upload_and_mission_transition(self):
        mission=self.post('/missions',{'saddle_id':'S-12','reason':'Test invalid upload'})
        self.post('/missions/'+mission['id']+'/transition',{'status':'in_progress'},409)
        result=self.client.post('/api/missions/'+mission['id']+'/captures',files={'file':('fake.jpg',b'<script>alert(1)</script>','image/jpeg')})
        self.assertEqual(result.status_code,409)
        self.post('/missions/'+mission['id']+'/transition',{'status':'scheduled','assignee':'Operator','scheduled_at':'2026-10-05'})
        self.post('/missions/'+mission['id']+'/transition',{'status':'in_progress'})
        result=self.client.post('/api/missions/'+mission['id']+'/captures',files={'file':('fake.jpg',b'<script>alert(1)</script>','image/jpeg')})
        self.assertEqual(result.status_code,422)
        result=self.client.post('/api/missions/'+mission['id']+'/captures',files={'file':('large.jpg',b'x'*(10*1024*1024+1),'image/jpeg')})
        self.assertEqual(result.status_code,413)
        self.assertEqual(self.client.get('/api/files/..%2Fqaif.sqlite3').status_code,404)

    def test_provider_failure_is_persisted_and_retry_possible(self):
        mission,capture=self.mission()
        with patch.dict(os.environ,{'GEMINI_API_KEY':''}):
            result=self.post('/captures/'+capture['id']+'/analyze',{})
        self.assertEqual(result['status'],'failed'); self.assertNotIn('result',result)
        self.assertEqual(self.client.get('/api/snapshot').json()['analyses'][0]['status'],'failed')
        with patch('backend.app.analyze_image',side_effect=TimeoutError('network')):
            retry=self.post('/captures/'+capture['id']+'/analyze',{})
        self.assertEqual(retry['status'],'failed')
        self.post('/missions/'+mission['id']+'/report',{},409)

    def test_thermal_matrix_and_non_numeric_rejection(self):
        mission=self.post('/missions',{'saddle_id':'S-12','image_type':'thermal','reason':'Thermal review'})
        self.post('/missions/'+mission['id']+'/transition',{'status':'scheduled','assignee':'Operator','scheduled_at':'2026-10-05'})
        self.post('/missions/'+mission['id']+'/transition',{'status':'in_progress'})
        capture=self.client.post('/api/missions/'+mission['id']+'/captures',files={'file':('thermal.png',self.image(),'image/png')},data={'mode':'thermal'}).json()
        self.assertIsNone(capture['thermal'])
        array=np.full((20,30),25.0); array[5,7]=55
        stream=io.BytesIO(); np.save(stream,array)
        result=self.client.post('/api/captures/'+capture['id']+'/thermal',files={'file':('temperature.npy',stream.getvalue())},data={'roi':'[0,0,1,1]','units':'C'})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['thermal']['tmax_c'],55)
        self.assertEqual(result.json()['thermal']['delta_c'],30)
        stream=io.BytesIO(); np.save(stream,np.array([['unsafe']],dtype=object))
        result=self.client.post('/api/captures/'+capture['id']+'/thermal',files={'file':('bad.npy',stream.getvalue())})
        self.assertEqual(result.status_code,422)
        stream=io.BytesIO(); np.save(stream,np.full((4,4),float('nan')))
        self.assertEqual(self.client.post('/api/captures/'+capture['id']+'/thermal',files={'file':('bad.npy',stream.getvalue())}).status_code,422)

    def test_pdf_source_attribution_and_print_escaping(self):
        stream=io.BytesIO(); c=canvas.Canvas(stream); c.drawString(50,750,'Coating repaired on 2026-01-02'); c.save()
        result=self.client.post('/api/documents',files={'file':('prior.pdf',stream.getvalue(),'application/pdf')},data={'saddle_id':'S-12'})
        self.assertEqual(result.status_code,200,result.text)
        document=result.json()
        self.post('/documents/'+document['id']+'/events',{'page':1,'quote':'Invented quote','summary':'bad source'},422)
        event=self.post('/documents/'+document['id']+'/events',{'page':1,'quote':'Coating repaired','summary':'Coating repair','event_date':'2026-01-02','event_type':'repair'})
        self.assertEqual(event['page'],1)
        self.assertEqual(event['document_id'],document['id'])
        self.assertEqual(next(r for r in self.client.get('/api/placements').json() if r['saddle_id']=='S-12')['score'],9)

    def test_stream_updates_and_stop_preserve_partial_readings(self):
        with self.client.websocket_connect('/ws/events') as socket:
            running=self.post('/demo/stream',{'case':'early_bending','saddle_id':'S-12'})
            self.assertEqual(socket.receive_json()['type'],'changed')
            self.post('/demo/replay',{'case':'control','saddle_id':'S-12'},409)
            self.post('/demo/stop/S-12',{})
            episode=self.client.get('/api/episodes/'+running['id']).json()
            self.assertEqual(episode['playback_status'],'stopped')
            self.assertGreater(len(episode['rows']),0)
            self.assertLess(len(episode['rows']),433)

    def test_demo_signal_is_not_an_inference_and_is_disabled_in_production(self):
        signal=self.post('/demo/signal',{'saddle_id':'S-12','category':'thermal'})
        self.assertEqual(signal['source'],'manual_demo')
        self.assertEqual(signal['basis'],'operator_demo_control')
        self.assertIsNone(signal['episode_id'])
        client=TestClient(create_app(self.directory,admin_password='ignored',demo_mode=False))
        client.post('/api/auth/login',json={'name':'admin','password':'test-only-private-password'})
        self.assertEqual(client.post('/api/demo/signal',json={'category':'thermal'}).status_code,403)
        client.close()

    def test_invalid_dates_rejected(self):
        mission=self.post('/missions',{'saddle_id':'S-12','reason':'Schedule date test'})
        self.post('/missions/'+mission['id']+'/transition',{'status':'scheduled','assignee':'Operator','scheduled_at':'not-a-date'},422)

    def test_live_import_requires_valid_chronology_and_no_invented_detection(self):
        row={'timestamp_s':0,'strain_hoop_microstrain':300,'strain_axial_microstrain':70,'temperature_k':298,'wetness_index':.1,'packet_valid':True}
        self.post('/saddles/S-12/readings',{'rows':[row,row]},422)
        result=self.post('/saddles/S-12/readings',{'rows':[row,{**row,'timestamp_s':1,'strain_axial_microstrain':1000}]})
        self.assertFalse(result['assessment']['reference_available'])
        self.assertEqual(result['assessment']['alerts'],[])
        self.assertEqual(result['source'],'imported')

    def test_csrf_guard(self):
        self.assertEqual(self.client.post('/api/demo/replay',json={'case':'control'},headers={'origin':'https://evil.example'}).status_code,403)


if __name__=='__main__': unittest.main()
