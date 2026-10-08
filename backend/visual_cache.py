"""Replay only a validated real Gemini response for precisely matching evidence."""
import hashlib
import json
from pathlib import Path

from .evidence import validate_visual_result, visual_contract_hash


def result_hash(result):
    return hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def request_identity(image:Path, mode:str, model:str, previous:Path|None=None, *, execution_profile=None):
    identity={'image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'mode':mode,'model':model,
              'previous_image_sha256':hashlib.sha256(previous.read_bytes()).hexdigest() if previous else None,
              'contract_sha256':visual_contract_hash()}
    if execution_profile is not None:
        identity['execution_profile']=execution_profile
        identity['contract_sha256']=execution_profile['contract_sha256']
    return {'id':'VC-'+result_hash(identity),**identity}


def remember_live(store, identity, analysis, actor):
    if analysis.get('provider')!='gemini' or analysis.get('execution_mode')!='live' or analysis.get('status')!='completed':
        raise ValueError('Only a successful live Gemini result can populate the saved-result cache')
    if analysis.get('execution_profile')!=identity.get('execution_profile'):
        raise ValueError('Execution profile must match the saved result identity')
    result=validate_visual_result(analysis['result'])
    saved={**identity,'provider':'gemini','origin':'successful_live_analysis','result':result,
           'result_sha256':result_hash(result),'source_analysis_id':analysis['id'],
           'source_capture_id':analysis['capture_id'],'analyzed_at':analysis['created_at']}
    return store.put('visual_cache',saved,actor,'save_live_result')


def find_saved(store, identity):
    saved=store.get('visual_cache',identity['id'])
    if not saved or saved.get('origin')!='successful_live_analysis' or saved.get('provider')!='gemini':
        return None
    if any(saved.get(key)!=value for key,value in identity.items()):
        return None
    try:
        result=validate_visual_result(saved['result'])
        if result_hash(result)!=saved['result_sha256']:
            return None
        source=store.get('analyses',saved['source_analysis_id'])
        if not source or source.get('status')!='completed' or source.get('execution_mode')!='live' or source.get('provider')!='gemini':
            return None
        if source.get('request_identity')!=identity or source.get('capture_id')!=saved['source_capture_id']:
            return None
        if source.get('execution_profile')!=identity.get('execution_profile'):
            return None
        if result_hash(validate_visual_result(source['result']))!=saved['result_sha256']:
            return None
        return saved
    except (KeyError,ValueError,TypeError):
        return None


def analysis_source_label(analysis):
    if analysis.get('provider')=='human':
        return 'مراجعة بشرية'
    route=' عبر Antigravity' if analysis.get('execution_profile',{}).get('transport')=='antigravity' else ''
    if analysis.get('execution_mode')=='cached':
        return 'تحليل Gemini محفوظ'+route+' · أُجري '+analysis.get('original_analyzed_at','')+' · لم يُجرَ تحليل حي لهذا الطلب'
    return 'تحليل Gemini حي'+route+' · '+analysis.get('model','Gemini')
