import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path

import httpx
from PIL import Image

from backend.evidence import GeminiUnavailable
from backend.visual_provider import AGENT, antigravity_analyze

RESULT={'summary':'Synthetic contract fixture; not a diagnosis', 'image_quality':'limited',
        'findings':[{'observation':'Fixture region','category':'thermal','interpretation':'Uncertain',
                     'certainty':'low','box':[.1,.2,.3,.4]}],
        'limitations':['Test fixture only'],'next_action':'Review'}


class AntigravityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.image=Path(self.temp.name)/'image.jpg'
        Image.new('RGB',(50,50)).save(self.image)

    def tearDown(self):
        self.temp.cleanup()

    async def test_polls_thermal_comparison_and_returns_validated_result(self):
        requests=[]
        def handler(request):
            requests.append(request)
            if request.method=='POST':
                return httpx.Response(200,json={'id':'test-interaction','status':'in_progress'})
            return httpx.Response(200,json={'id':'test-interaction','status':'completed',
                'steps':[{'type':'model_output','content':[{'type':'text','text':json.dumps(RESULT)}]}],
                'usage':{'total_tokens':100,'total_tool_use_tokens':0}})
        metadata={}
        result=await antigravity_analyze(self.image,'thermal','unit-test-key','gemini-3.8-flash',self.image,
            transport=httpx.MockTransport(handler),metadata=metadata,poll_interval=0)
        self.assertEqual(result,RESULT)
        self.assertEqual([r.method for r in requests],['POST','GET'])
        self.assertEqual(requests[0].headers['x-goog-api-key'],'unit-test-key')
        self.assertNotIn('unit-test-key',str(requests[0].url))
        payload=json.loads(requests[0].content)
        self.assertEqual(payload['agent'],AGENT)
        self.assertEqual(payload['agent_config']['model'],'gemini-3.8-flash')
        self.assertEqual(payload['agent_config']['max_total_tokens'],12000)
        self.assertTrue(payload['background'] and payload['store'])
        self.assertEqual(payload['tools'],[])
        self.assertEqual(len([p for p in payload['input'] if p['type']=='image']),2)
        self.assertIn('thermal',payload['input'][0]['text'])
        self.assertIn('الزيارة السابقة',payload['input'][2]['text'])
        self.assertEqual(metadata['interaction_id'],'test-interaction')
        self.assertEqual(metadata['usage']['total_tokens'],100)

    async def test_out_of_range_box_or_unstructured_output_is_rejected(self):
        invalid={**RESULT,'findings':[{**RESULT['findings'][0],'box':[0,0,2,1]}]}
        for output in (json.dumps(invalid),'I cannot produce JSON'):
            with self.subTest(output=output):
                def handler(request):
                    return httpx.Response(200,json={'id':'test','status':'completed','output_text':output})
                with self.assertRaises(ValueError):
                    await antigravity_analyze(self.image,'rgb','test','gemini-3.8-flash',
                        transport=httpx.MockTransport(handler),poll_interval=0)

    async def test_rate_limit_is_not_retried_and_key_is_not_exposed(self):
        requests=[]
        def handler(request):
            requests.append(request)
            return httpx.Response(429,json={'error':{'message':'unit-test-key provider message'}})
        with self.assertRaises(GeminiUnavailable) as error:
            await antigravity_analyze(self.image,'rgb','unit-test-key','gemini-3.8-flash',transport=httpx.MockTransport(handler))
        self.assertEqual(error.exception.reason,'rate_limit')
        self.assertNotIn('unit-test-key',str(error.exception))
        self.assertEqual(len(requests),1)

    async def test_timeout_cancels_running_interaction_without_regeneration(self):
        requests=[]
        async def handler(request):
            requests.append(request)
            if str(request.url).endswith(':cancel'):
                return httpx.Response(200,json={'status':'cancelled'})
            if request.method=='POST':
                return httpx.Response(200,json={'id':'test-timeout','status':'in_progress'})
            await asyncio.sleep(.1)
            return httpx.Response(200,json={'id':'test-timeout','status':'in_progress'})
        metadata={}
        with self.assertRaises(GeminiUnavailable) as error:
            await antigravity_analyze(self.image,'rgb','test','gemini-3.8-flash',
                transport=httpx.MockTransport(handler),metadata=metadata,poll_interval=0,timeout_s=.02)
        self.assertEqual(error.exception.reason,'provider_timeout')
        self.assertTrue(metadata['cancellation_confirmed'])
        self.assertEqual(sum(r.method=='POST' and not str(r.url).endswith(':cancel') for r in requests),1)
        self.assertTrue(str(requests[-1].url).endswith(':cancel'))

    async def test_poll_failure_cancels_pending_request(self):
        requests=[]
        def handler(request):
            requests.append(request)
            if str(request.url).endswith(':cancel'):
                return httpx.Response(200,json={'status':'cancelled'})
            if request.method=='POST':
                return httpx.Response(200,json={'id':'test','status':'in_progress'})
            return httpx.Response(503)
        with self.assertRaises(GeminiUnavailable):
            await antigravity_analyze(self.image,'rgb','test','gemini-3.8-flash',
                transport=httpx.MockTransport(handler),poll_interval=0)
        self.assertEqual(len(requests),3)
        self.assertTrue(str(requests[-1].url).endswith(':cancel'))

    async def test_unknown_action_is_cancelled_without_executing_tools(self):
        requests=[]
        def handler(request):
            requests.append(request)
            if str(request.url).endswith(':cancel'):
                return httpx.Response(200,json={'status':'cancelled'})
            return httpx.Response(200,json={'id':'test','status':'requires_action','steps':[{'type':'function_call'}]})
        with self.assertRaises(ValueError):
            await antigravity_analyze(self.image,'rgb','test','gemini-3.8-flash',transport=httpx.MockTransport(handler))
        self.assertEqual(len(requests),2)
        self.assertTrue(str(requests[-1].url).endswith(':cancel'))

    async def test_terminal_failure_is_not_fabricated(self):
        with self.assertRaises(GeminiUnavailable):
            await antigravity_analyze(self.image,'rgb','test','gemini-3.8-flash',
                transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'id':'test','status':'failed'})))


if __name__=='__main__':
    unittest.main()
