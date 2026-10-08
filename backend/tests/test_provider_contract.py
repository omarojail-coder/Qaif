import io
import json
import tempfile
import unittest
from pathlib import Path

import httpx
from PIL import Image
from backend.evidence import gemini_analyze, provider_schema, report_html


class ProviderContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_request_and_valid_structured_response(self):
        result={'summary':'Surface review','image_quality':'limited','findings':[{'observation':'A line',
          'category':'crack_like','interpretation':'Could be coating feature','certainty':'low','box':[.1,.2,.3,.4]}],
          'limitations':['No depth inference'],'next_action':'Inspect on site'}
        requests=[]
        def handler(request):
            requests.append(request)
            return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':json.dumps(result)}]}}]})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.jpg'; Image.new('RGB',(50,50)).save(path)
            answer=await gemini_analyze(path,'rgb','unit-test-key','gemini-3.8-flash',path,httpx.MockTransport(handler))
        self.assertEqual(answer,result)
        self.assertNotIn('unit-test-key',str(requests[0].url))
        self.assertEqual(requests[0].headers['x-goog-api-key'],'unit-test-key')
        payload=json.loads(requests[0].content)
        self.assertEqual(len([p for p in payload['contents'][0]['parts'] if 'inlineData' in p]),2)
        self.assertNotIn('pattern',json.dumps(payload['generationConfig']['responseJsonSchema']))

    async def test_out_of_range_result_rejected(self):
        result={'summary':'Test','image_quality':'limited','findings':[{'observation':'Line','category':'other',
          'interpretation':'Uncertain','certainty':'low','box':[0,0,2,1]}],'limitations':['Test'],'next_action':'Review'}
        def handler(request): return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':json.dumps(result)}]}}]})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.jpg'; Image.new('RGB',(50,50)).save(path)
            with self.assertRaises(ValueError): await gemini_analyze(path,'rgb','test','model',transport=httpx.MockTransport(handler))

    async def test_provider_error_has_no_fabricated_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.jpg'; Image.new('RGB',(50,50)).save(path)
            with self.assertRaisesRegex(ValueError,'HTTP 429'):
                await gemini_analyze(path,'rgb','test','model',transport=httpx.MockTransport(lambda request:httpx.Response(429)))

    def test_print_report_escapes_untrusted_content(self):
        report={'id':'R-test','asset_name':'<script>bad</script>','created_at':'test','facts':{'Fact':'<img src=x>'},
          'observations':['<script>alert(1)</script>'],'limitations':['Test'],'recommendation':'Review','sources':[]}
        rendered=report_html(report)
        self.assertNotIn('<script>',rendered)
        self.assertIn('&lt;script&gt;',rendered)


if __name__=='__main__': unittest.main()
