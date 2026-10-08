import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.lpg_inspections import ensure_demo_inspections


class ShipmentInspectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.directory.name), admin_password='local-inspection-test-password', demo_mode=True)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.client.post('/api/auth/login', json={'name': 'admin', 'password': 'local-inspection-test-password'})

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def request(self, number=1, cutoff=300):
        return self.client.post('/api/lpg/inspections', json={'number': number, 'reason': 'فحص توضيحي لتثبيت السراج', 'evidence_until_s': cutoff})

    def transition(self, task_id, **body):
        return self.client.post(f'/api/lpg/inspections/{task_id}/transition', json=body)

    def test_seed_tasks_are_shipment_only_and_idempotent(self):
        before = self.client.get('/api/snapshot').json()
        tasks = self.client.get('/api/lpg/inspections').json()
        self.assertEqual({t['number'] for t in tasks}, {2, 6, 8, 14, 17, 20})
        self.assertTrue(all(t['trip_id'] == f"TRIP-{t['number']:03d}" for t in tasks))
        ensure_demo_inspections(self.app.state.store)
        after = self.client.get('/api/snapshot').json()
        self.assertEqual(before['lpg_inspections'], after['lpg_inspections'])
        self.assertEqual(before['inspections'], after['inspections'])

    def test_create_duplicate_guard_and_full_assessment_persists(self):
        before = self.client.get('/api/snapshot').json()
        response = self.request()
        self.assertEqual(response.status_code, 200)
        task_id = response.json()['id']
        self.assertEqual(self.request().status_code, 409)
        self.assertEqual(self.transition(task_id, status='closed', decision='قرار قبل التقييم').status_code, 409)
        self.assertEqual(self.transition(task_id, status='in_progress', assignee='مفتش الاختبار').status_code, 200)
        self.assertEqual(self.transition(task_id, status='review', condition='normal', findings='لا ملاحظة ظاهرة', recommendation='متابعة لاحقة').status_code, 409)
        evaluated = self.transition(task_id, status='review', condition='maintenance', findings='تثبيت القفص يحتاج إعادة ضبط', recommendation='إعادة ضبط التثبيت ومراجعته', mount_check='loose')
        self.assertEqual(evaluated.status_code, 200)
        self.assertEqual(evaluated.json()['condition'], 'maintenance')
        closed = self.transition(task_id, status='closed', decision='إغلاق المهمة مع الإحالة إلى الصيانة')
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.json()['condition'], 'maintenance')
        self.assertEqual([h['status'] for h in closed.json()['history']], ['new', 'in_progress', 'review', 'closed'])
        self.assertEqual(self.transition(task_id, status='review', condition='isolate').status_code, 409)
        after = self.client.get('/api/snapshot').json()
        for kind in ('saddles', 'episodes', 'alerts', 'inspections', 'missions'):
            self.assertEqual(before[kind], after[kind])
        restarted = create_app(Path(self.directory.name), admin_password='local-inspection-test-password', demo_mode=True)
        saved = restarted.state.store.get('lpg_inspections', task_id)
        self.assertEqual(saved['status'], 'closed')
        self.assertEqual(saved['assessment']['findings'], 'تثبيت القفص يحتاج إعادة ضبط')
        self.assertGreaterEqual(len(restarted.state.store.history(task_id)), 4)

    def test_evidence_is_frozen_at_request_cutoff_and_missing_is_unknown(self):
        self.assertEqual(self.transition('LPG-F-008', status='cancelled', decision='إلغاء المثال لاختبار لقطة أبكر').status_code, 200)
        request = self.request(8, 300).json()
        evidence = self.client.get(f"/api/lpg/inspections/{request['id']}/evidence").json()
        self.assertEqual(evidence['alerts'], [])
        self.assertEqual(evidence['window']['end_s'], 300)
        self.assertFalse(evidence['signals']['lpg_anomaly']['confirmed'])
        missing = self.client.get('/api/lpg/inspections/LPG-F-006/evidence').json()
        self.assertEqual(missing['expected_state'], 'unknown')
        self.assertTrue(missing['incomplete'])
        self.assertNotIn('serial', missing)

    def test_normal_evaluation_requires_documented_checks(self):
        task_id = self.request(3).json()['id']
        self.transition(task_id, status='in_progress', assignee='مفتش الاختبار')
        result = self.transition(task_id, status='review', condition='normal', findings='لم يسجل الفحص ملاحظة', recommendation='المتابعة في الرحلة التالية', gas_check='no_indication', mount_check='normal', latch_check='normal')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['assessment']['source'], 'manual_demo_assessment')

    def test_operator_can_request_but_cannot_evaluate(self):
        self.client.post('/api/users', json={'name': 'testoperator', 'role': 'operator', 'password': 'local-operator-test-password'})
        self.client.post('/api/auth/login', json={'name': 'testoperator', 'password': 'local-operator-test-password'})
        task_id = self.request(4).json()['id']
        self.assertEqual(self.transition(task_id, status='in_progress', assignee='مفتش الاختبار').status_code, 403)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/lpg/inspections').status_code, 401)

    def test_invalid_shipment_ids_and_missing_decisions_are_rejected(self):
        self.assertEqual(self.request(99).status_code, 422)
        self.assertEqual(self.client.get('/api/lpg/inspections/pipe-record/evidence').status_code, 404)
        self.assertEqual(self.transition('LPG-F-002', status='cancelled', decision='').status_code, 409)
        self.assertEqual(self.transition('LPG-F-002', status='cancelled', decision='لا حاجة إلى هذا المثال').status_code, 200)


if __name__ == '__main__':
    unittest.main()
