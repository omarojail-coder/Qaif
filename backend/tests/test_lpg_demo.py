import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.lpg_demo import shipment_demo


class ShipmentDemoTests(unittest.TestCase):
    def test_reference_has_no_model_alerts(self):
        data = shipment_demo(1)
        self.assertEqual(data['alerts'], [])
        self.assertTrue(all(s['state'] == 'absent' for s in data['inference_history'][-1]['signals'].values()))

    def test_gas_alert_is_confirmed_by_actual_model_history(self):
        data = shipment_demo(8)
        alert = next(a for a in data['alerts'] if a['signal'] == 'lpg_anomaly')
        index = int(alert['timestamp_s'] / 5)
        for result in data['inference_history'][index - 2:index + 1]:
            self.assertGreaterEqual(result['signals']['lpg_anomaly']['score'], .5)
        self.assertTrue(data['inference_history'][index]['signals']['lpg_anomaly']['alarm'])
        self.assertFalse(data['lpg_model_trained'])

    def test_missing_readings_suspend_inference(self):
        data = shipment_demo(17)
        self.assertFalse(data['rows'][-1]['packet_valid'])
        self.assertTrue(all(s['state'] == 'unknown' and s['score'] is None for s in data['inference_history'][-1]['signals'].values()))

    def test_cylinders_and_cadence(self):
        data = shipment_demo(2)
        self.assertEqual([row['timestamp_s'] for row in data['rows']], [i * 5 for i in range(241)])
        self.assertEqual(len(data['inference_history']), len(data['rows']))
        serials = {c['serial'] for c in data['cylinders']}
        self.assertEqual(len(serials), 9)
        self.assertTrue(serials.isdisjoint(c['serial'] for c in shipment_demo(1)['cylinders']))

    def test_endpoint_is_authenticated_and_preserves_pipe_records(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory), admin_password='local-lpg-test-password', demo_mode=True)
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/lpg/demo/seraj/2').status_code, 401)
                client.post('/api/auth/login', json={'name': 'admin', 'password': 'local-lpg-test-password'})
                before = client.get('/api/snapshot').json()
                self.assertEqual(client.get('/api/lpg/demo/seraj/22').status_code, 404)
                result = client.get('/api/lpg/demo/seraj/2')
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()['trip_id'], 'TRIP-002')
                after = client.get('/api/snapshot').json()
                for kind in ('saddles', 'episodes', 'alerts', 'missions'):
                    self.assertEqual(before[kind], after[kind])


if __name__ == '__main__':
    unittest.main()
