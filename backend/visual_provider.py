"""Bounded visual review via Antigravity, with explicit execution provenance."""
import asyncio
import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path

import httpx

from .evidence import VISUAL_PROMPT, GeminiUnavailable, gemini_analyze, provider_schema, validate_visual_result, visual_contract_hash

AGENT = 'antigravity-preview-09-2026'
TOKEN_BUDGET = 12000
API = 'https://generativelanguage.googleapis.com/v1beta/interactions'
SCHEMA_INSTRUCTION = ('حلل الصورة فقط. لا تستخدم أدوات أو تصفح أو بحثًا خارجيًا. '
                      'أعد كائن JSON فقط، دون Markdown أو شرح إضافي، يطابق المخطط التالي:\n')


def prompt(mode, previous=False):
    if mode not in ('rgb', 'thermal'):
        raise ValueError('نوع الصورة غير صالح')
    text = VISUAL_PROMPT + f'نوع الصورة الحالية: {mode}.\n'
    if previous:
        text += 'الصورة الثانية هي زيارة سابقة لنفس السرج؛ اذكر حدود المقارنة.\n'
    return text + SCHEMA_INSTRUCTION + json.dumps(provider_schema(), ensure_ascii=False)


def execution_profile():
    transport = os.getenv('QAIF_VISUAL_TRANSPORT', 'antigravity')
    if transport == 'gemini_direct':
        return {'transport':transport, 'adapter_version':'gemini-direct-v1',
                'contract_sha256':visual_contract_hash()}
    if transport != 'antigravity':
        raise ValueError('إعداد مسار تحليل الصور غير صالح')
    contract = {'version':'antigravity-visual-v1', 'prompt_template':prompt('rgb', True),
                'schema':provider_schema(), 'agent':AGENT, 'max_total_tokens':TOKEN_BUDGET,
                'environment':'remote', 'tools':[], 'background':True, 'store':True,
                'validation':'local-json-and-visual-schema; final-model-output-only'}
    digest = hashlib.sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'transport':transport, 'adapter_version':contract['version'], 'agent':AGENT,
            'max_total_tokens':TOKEN_BUDGET, 'contract_sha256':digest}


def check_http(response):
    if response.status_code == 200:
        return
    code = response.status_code
    if code in (401,403,429) or code >= 500:
        reason = 'rate_limit' if code == 429 else 'provider_access' if code in (401,403) else 'provider_unavailable'
        raise GeminiUnavailable(f'تعذر التحليل عبر Antigravity (HTTP {code})', reason)
    raise ValueError(f'تعذر التحقق من طلب Antigravity (HTTP {code})')


async def antigravity_analyze(image:Path, mode:str, key:str, model:str, previous:Path|None=None,
                             *, transport=None, metadata=None, timeout_s=90, poll_interval=2):
    if not key:
        raise GeminiUnavailable('لم يُضبط مفتاح Gemini لتحليل الصور', 'missing_key')
    if not re.fullmatch(r'[a-zA-Z0-9._-]+', model):
        raise ValueError('اسم النموذج غير صالح')
    instruction = prompt(mode, previous is not None)
    inputs = [{'type':'text', 'text':instruction},
              {'type':'image', 'mime_type':'image/jpeg', 'data':base64.b64encode(image.read_bytes()).decode()}]
    if previous is not None:
        inputs += [{'type':'text', 'text':'الصورة الثانية: الزيارة السابقة'},
                   {'type':'image', 'mime_type':'image/jpeg', 'data':base64.b64encode(previous.read_bytes()).decode()}]
    payload = {'agent':AGENT, 'agent_config':{'type':'antigravity', 'model':model, 'max_total_tokens':TOKEN_BUDGET},
               'input':inputs, 'environment':'remote', 'tools':[], 'background':True, 'store':True}
    details = metadata if metadata is not None else {}
    details.update(agent=AGENT, model=model, generation_requests=1,
                   prompt_sha256=hashlib.sha256(instruction.encode()).hexdigest(),
                   schema_enforcement='prompt plus local validation', no_external_search_requested=True)
    started = time.perf_counter()
    interaction_id = None
    terminal = False
    async with httpx.AsyncClient(timeout=httpx.Timeout(25,connect=5), transport=transport,
                                 headers={'x-goog-api-key':key}) as client:
        try:
            async with asyncio.timeout(timeout_s):
                response = await client.post(API, json=payload)
                check_http(response)
                body = response.json()
                interaction_id = body.get('id')
                if not isinstance(interaction_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,512}', interaction_id):
                    raise ValueError('معرف استجابة Antigravity غير صالح')
                details['interaction_id'] = interaction_id
                while body.get('status') in ('in_progress','queued'):
                    details['status'] = body['status']
                    await asyncio.sleep(poll_interval)
                    response = await client.get(API + '/' + interaction_id)
                    check_http(response)
                    body = response.json()
                status = body.get('status')
                details['status'] = status
                terminal = status in ('completed','failed','cancelled','canceled')
                if status in ('failed','cancelled','canceled'):
                    raise GeminiUnavailable('لم يكتمل تحليل Antigravity لدى المزود', 'provider_unavailable')
                if status != 'completed':
                    raise ValueError('أعاد Antigravity حالة غير مدعومة لتحليل الصور')
                usage = body.get('usage')
                if isinstance(usage,dict):
                    details['usage'] = {name:value for name,value in usage.items()
                                        if name in ('total_tokens','total_input_tokens','total_output_tokens',
                                                    'total_cached_tokens','total_thought_tokens','total_tool_use_tokens')
                                        and isinstance(value,(int,float))}
                text = body.get('output_text')
                if not text:
                    outputs = [step for step in body.get('steps',[]) if step.get('type') == 'model_output']
                    if not outputs:
                        raise ValueError('لم تتضمن استجابة Antigravity نتيجة نهائية')
                    text = ''.join(part.get('text','') for part in outputs[-1].get('content',[])
                                   if part.get('type') == 'text')
                if not isinstance(text,str) or not text.strip():
                    raise ValueError('نتيجة Antigravity فارغة')
                cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
                return validate_visual_result(json.loads(cleaned))
        except TimeoutError:
            details['status'] = 'timed_out'
            raise GeminiUnavailable('انتهت مهلة تحليل الصورة عبر Antigravity؛ أعد المحاولة', 'provider_timeout') from None
        finally:
            details['elapsed_s'] = round(time.perf_counter() - started, 3)
            if interaction_id and not terminal:
                # Bound cleanup too; never retry the original generation request.
                try:
                    async with asyncio.timeout(3):
                        cancelled = await client.post(API + '/' + interaction_id + ':cancel')
                        details['cancellation_confirmed'] = cancelled.status_code == 200
                except (httpx.HTTPError,TimeoutError):
                    details['cancellation_confirmed'] = False


async def analyze_image(image, mode, key, model, previous=None, *, profile=None, metadata=None, transport=None):
    selected = profile or execution_profile()
    if selected['transport'] == 'antigravity':
        return await antigravity_analyze(image,mode,key,model,previous,transport=transport,metadata=metadata)
    if selected['transport'] == 'gemini_direct':
        return await gemini_analyze(image,mode,key,model,previous,transport=transport)
    raise ValueError('مسار التحليل غير صالح')
