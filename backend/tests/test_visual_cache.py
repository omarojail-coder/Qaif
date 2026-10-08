import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from backend.app import create_app
from backend.evidence import GeminiUnavailable


RESULT={'summary':'Synthetic provider fixture, not a real visual analysis','image_quality':'limited',
        'findings':[{'observation':'A synthetic fixture line','category':'crack_like',
                     'interpretation':'Requires inspection','certainty':'low','box':[.1,.2,.3,.4]}],
        'limitations':['Synthetic test only; no physical diagnosis'],'next_action':'Review on site'}


class SavedVisualTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.directory=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'GEMINI_API_KEY':'unit-test-not-a-secret','GEMINI_MODEL':'gemini-3.8-flash'})
        self.env.start()
        self.app=create_app(self.directory,admin_password='private-test-password',demo_mode=True)
        self.client=TestClient(self.app); self.client.__enter__()
        self.client.post('/api/auth/login',json={'name':'admin','password':'private-test-password'})

    def tearDown(self):
        self.client.__exit__(None,None,None); self.client.close(); self.env.stop(); self.temp.cleanup()

    def upload(self,color='gray',mode='rgb'):
        mission=self.client.post('/api/missions',json={'saddle_id':'S-12','reason':'Test image review'}).json()
        self.client.post('/api/missions/'+mission['id']+'/transition',json={'status':'scheduled','assignee':'Operator','scheduled_at':'2026-10-05'})
        self.client.post('/api/missions/'+mission['id']+'/transition',json={'status':'in_progress'})
        stream=io.BytesIO(); Image.new('RGB',(200,150),color).save(stream,format='PNG')
        response=self.client.post('/api/missions/'+mission['id']+'/captures',
          files={'file':('synthetic.png',stream.getvalue(),'image/png')},data={'mode':mode,'source':'prepared_demo'})
        self.assertEqual(response.status_code,200,response.text)
        return mission,response.json()

    def analyze(self,capture,**body):
        response=self.client.post('/api/captures/'+capture['id']+'/analyze',json=body)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def prime(self,capture,**body):
        with patch('backend.app.analyze_image',return_value=RESULT) as provider:
            result=self.analyze(capture,**body)
        self.assertEqual(provider.call_count,1)
        self.assertEqual(result['execution_mode'],'live')
        self.assertEqual(result['status'],'completed')
        return result

    def test_quota_failure_replays_same_real_result_and_labels_print_report(self):
        mission,capture=self.upload(); live=self.prime(capture)
        with patch('backend.app.analyze_image',side_effect=GeminiUnavailable('HTTP 429','rate_limit')):
            replay=self.analyze(capture)
        self.assertEqual(replay['status'],'completed')
        self.assertEqual(replay['execution_mode'],'cached')
        self.assertEqual(replay['result'],live['result'])
        self.assertEqual(replay['original_analysis_id'],live['id'])
        self.assertEqual(replay['fallback_reason'],'rate_limit')
        self.assertEqual(len(self.app.state.store.all('visual_cache')),1)
        report=self.client.post('/api/missions/'+mission['id']+'/report',json={}).json()
        self.assertIn('تحليل Gemini محفوظ',report['facts']['التحليل'])
        html=self.client.get('/api/reports/'+report['id']+'/print').text
        self.assertIn('لم يُجرَ تحليل حي',html)

    def test_saved_selection_makes_no_external_call_and_survives_restart(self):
        _,capture=self.upload(); self.prime(capture)
        with patch('backend.app.analyze_image') as provider:
            saved=self.analyze(capture,strategy='saved')
        provider.assert_not_called()
        self.assertEqual(saved['execution_mode'],'cached')
        restarted=TestClient(create_app(self.directory,admin_password='ignored',demo_mode=True))
        restarted.post('/api/auth/login',json={'name':'admin','password':'private-test-password'})
        self.assertTrue(restarted.get('/api/captures/'+capture['id']+'/analysis-cache').json()['available'])
        restarted.close()

    def test_reuploaded_identical_image_matches_but_other_image_and_mode_do_not(self):
        _,capture=self.upload(); self.prime(capture)
        _,same=self.upload(); _,other=self.upload(color='blue'); _,thermal=self.upload(mode='thermal')
        with patch('backend.app.analyze_image',side_effect=TimeoutError('network')):
            self.assertEqual(self.analyze(same)['execution_mode'],'cached')
            for item in (other,thermal):
                result=self.analyze(item)
                self.assertEqual(result['status'],'failed')
                self.assertNotIn('result',result)

    def test_comparison_and_model_must_match(self):
        _,capture=self.upload(); _,old=self.upload(color='blue'); _,other_old=self.upload(color='red')
        self.prime(capture,previous_id=old['id'])
        with patch('backend.app.analyze_image',side_effect=TimeoutError('network')):
            self.assertEqual(self.analyze(capture,previous_id=old['id'])['execution_mode'],'cached')
            self.assertEqual(self.analyze(capture)['status'],'failed')
            self.assertEqual(self.analyze(capture,previous_id=other_old['id'])['status'],'failed')
            with patch.dict(os.environ,{'GEMINI_MODEL':'different-model'}):
                self.assertEqual(self.analyze(capture,previous_id=old['id'])['status'],'failed')

    def test_missing_or_corrupt_saved_result_is_not_fabricated(self):
        _,capture=self.upload()
        with patch('backend.app.analyze_image') as provider:
            self.assertEqual(self.analyze(capture,strategy='saved')['status'],'failed')
        provider.assert_not_called()
        self.prime(capture)
        saved=self.app.state.store.all('visual_cache')[0]
        saved['result']['summary']='Changed after caching'
        self.app.state.store.put('visual_cache',saved)
        result=self.analyze(capture,strategy='saved')
        self.assertEqual(result['status'],'failed'); self.assertNotIn('result',result)

    def test_invalid_provider_output_does_not_silently_replay_old_result(self):
        _,capture=self.upload(); self.prime(capture)
        with patch('backend.app.analyze_image',side_effect=ValueError('malformed response')):
            result=self.analyze(capture)
        self.assertEqual(result['status'],'failed'); self.assertNotIn('result',result)

    def test_no_fallback_in_production_even_when_saved_result_exists(self):
        _,capture=self.upload(); self.prime(capture)
        production=TestClient(create_app(self.directory,admin_password='ignored',demo_mode=False))
        production.post('/api/auth/login',json={'name':'admin','password':'private-test-password'})
        with patch('backend.app.analyze_image',side_effect=TimeoutError('network')):
            result=production.post('/api/captures/'+capture['id']+'/analyze',json={}).json()
        self.assertEqual(result['status'],'failed'); self.assertNotIn('result',result)
        self.assertEqual(production.post('/api/captures/'+capture['id']+'/analyze',json={'strategy':'saved'}).status_code,403)
        self.assertFalse(production.get('/api/captures/'+capture['id']+'/analysis-cache').json()['available'])
        production.close()

    def test_mismatched_comparison_mode_rejected(self):
        _,capture=self.upload(); _,thermal=self.upload(mode='thermal')
        response=self.client.post('/api/captures/'+capture['id']+'/analyze',json={'previous_id':thermal['id']})
        self.assertEqual(response.status_code,422)

    def test_saved_result_does_not_cross_provider_transport(self):
        _,capture=self.upload()
        self.prime(capture)
        with patch.dict(os.environ,{'QAIF_VISUAL_TRANSPORT':'gemini_direct'}):
            self.assertFalse(self.client.get('/api/captures/'+capture['id']+'/analysis-cache').json()['available'])
            result=self.analyze(capture,strategy='saved')
            self.assertEqual(result['status'],'failed')
            self.assertNotIn('result',result)

    def test_saved_analysis_keeps_antigravity_provenance_in_report(self):
        mission,capture=self.upload()
        live=self.prime(capture)
        self.assertEqual(live['execution_profile']['transport'],'antigravity')
        replay=self.analyze(capture,strategy='saved')
        self.assertEqual(replay['execution_profile'],live['execution_profile'])
        report=self.client.post('/api/missions/'+mission['id']+'/report',json={}).json()
        self.assertIn('عبر Antigravity',report['facts']['التحليل'])


if __name__=='__main__':
    unittest.main()
