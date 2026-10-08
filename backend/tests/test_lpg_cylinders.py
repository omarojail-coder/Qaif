import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.lpg_cylinders import cylinder_catalog, cylinder_passport, journey_evidence
from backend.lpg_demo import shipment_demo


class CylinderPassportTests(unittest.TestCase):
    def test_catalog_matches_saddle_grid_and_keeps_identity_between_cages(self):
        catalog = cylinder_catalog()['cylinders']
        self.assertEqual(len({c['serial'] for c in catalog}), 189)
        for number in range(1, 22):
            grid = {c['serial'] for c in shipment_demo(number)['cylinders']}
            self.assertEqual(grid, {c['serial'] for c in catalog if c['current_saddle_id'] == f'S-{number}'})
        passport = cylinder_passport('CYL-012-05')
        self.assertGreater(len({j['membership']['cage_id'] for j in passport['journeys']}), 1)
        self.assertEqual(passport['serial'], 'CYL-012-05')
        self.assertFalse(passport['persisted_operational_registry'])

    def test_memberships_do_not_overlap_and_transfers_are_continuous(self):
        for item in cylinder_catalog()['cylinders']:
            journeys = cylinder_passport(item['serial'])['journeys']
            for previous, following in zip(journeys, journeys[1:]):
                self.assertLess(datetime.fromisoformat(previous['membership']['unloaded_at']), datetime.fromisoformat(following['membership']['loaded_at']))
                self.assertEqual(previous['destination'], following['origin'])
            self.assertIsNone(journeys[-1]['membership']['unloaded_at'])
            self.assertTrue(journeys[-1]['current'])

    def test_current_evidence_does_not_expose_future_alerts(self):
        serial = 'CYL-008-03'
        journey = cylinder_passport(serial)['journeys'][-1]
        before = journey_evidence(serial, journey['id'], until_s=300)
        self.assertEqual(before['alerts'], [])
        self.assertFalse(before['signals']['lpg_anomaly']['confirmed'])
        self.assertLessEqual(max(r['timestamp_s'] for r in before['rows']), 300)
        full = journey_evidence(serial, journey['id'])
        self.assertTrue(full['signals']['lpg_anomaly']['confirmed'])
        self.assertEqual(full['expected_state'], 'review')

    def test_peaks_exclude_invalid_packets_and_pre_membership_baseline(self):
        serial = 'CYL-001-01'
        journey = cylinder_passport(serial)['journeys'][-1]
        demo = dict(shipment_demo(1))
        demo['rows'] = [dict(r) for r in demo['rows']]
        demo['rows'][23]['mount_temperature_C'] = 99999
        demo['rows'][50]['mount_temperature_C'] = 99998
        demo['rows'][50]['packet_valid'] = False
        with patch('backend.lpg_cylinders.shipment_demo', return_value=demo):
            result = journey_evidence(serial, journey['id'])
        self.assertLess(result['peaks']['temperature']['value'], 100)
        self.assertTrue(all(r['timestamp_s'] >= 120 for r in result['rows']))

    def test_unknown_is_not_reported_as_clear(self):
        serial = 'CYL-017-02'
        journey = cylinder_passport(serial)['journeys'][-1]
        result = journey_evidence(serial, journey['id'])
        self.assertEqual(result['expected_state'], 'unknown')
        self.assertTrue(result['incomplete'])
        self.assertLess(result['coverage_percent'], 90)
        self.assertEqual(result['signals']['lpg_anomaly']['latest_state'], 'unknown')

    def test_authenticated_endpoints_check_identity_and_journey_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory), admin_password='local-cylinder-test-password', demo_mode=True)
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/lpg/demo/cylinders').status_code, 401)
                client.post('/api/auth/login', json={'name': 'admin', 'password': 'local-cylinder-test-password'})
                before = client.get('/api/snapshot').json()
                self.assertEqual(client.get('/api/lpg/demo/cylinders').json()['count'], 189)
                self.assertEqual(client.get('/api/lpg/demo/cylinders/CYL-999-01').status_code, 404)
                passport = client.get('/api/lpg/demo/cylinders/CYL-001-01').json()
                journey_id = passport['journeys'][-1]['id']
                endpoint = f'/api/lpg/demo/cylinders/CYL-001-01/journeys/{journey_id}'
                self.assertEqual(client.get(endpoint + '?until_s=300').status_code, 200)
                self.assertEqual(client.get(endpoint + '?until_s=nan').status_code, 422)
                self.assertEqual(client.get(endpoint.replace('CYL-001-01', 'CYL-002-01')).status_code, 404)
                after = client.get('/api/snapshot').json()
                for kind in ('saddles', 'episodes', 'alerts', 'missions'):
                    self.assertEqual(before[kind], after[kind])


if __name__ == '__main__':
    unittest.main()
