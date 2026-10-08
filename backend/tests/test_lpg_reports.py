import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.app import create_app
from backend.lpg_reports import customer_report
from backend.lpg_reports import places
from backend.lpg_report_locations import located_observations
from backend.lpg_cylinders import cylinder_passport
from urllib.parse import parse_qs, urlsplit


class CustomerReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.app = create_app(Path(cls.directory.name), admin_password='customer-report-test-only', demo_mode=True)
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.directory.cleanup()

    def test_barcode_lookup_is_public_but_operator_records_are_private(self):
        response = self.client.get('/api/public/cylinders/cyl-008-01/report')
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report['serial'], 'CYL-008-01')
        self.assertEqual(len(report['journeys']), 6)
        self.assertEqual(report['journeys'][-1]['destination']['city'], 'الجبيل')
        self.assertIsNone(report['journeys'][-1]['arrived_at'])
        self.assertEqual(report['transport']['reading_until_s'], 650)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.client.get('/api/snapshot').status_code, 401)
        self.assertEqual(self.client.get('/api/lpg/demo/cylinders/CYL-008-01').status_code, 401)
        # Recursively protect operator names/notes and raw model or measurement data.
        forbidden = {'assignee', 'requested_by', 'by', 'actor', 'findings', 'recommendation', 'decision', 'history', 'signals', 'rows', 'truck', 'membership', 'max_score'}
        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for child in value.values(): inspect(child)
            elif isinstance(value, list):
                for child in value: inspect(child)
        inspect(report)

    def test_unknown_serial_does_not_silently_show_a_different_cylinder(self):
        for serial in ('CYL-999-01', 'CYL-001-10', 'unknown'):
            for suffix in ('report', 'report.pdf', 'qr.svg'):
                self.assertEqual(self.client.get(f'/api/public/cylinders/{serial}/{suffix}').status_code, 404)

    def test_region_history_is_continuous_and_readings_exclude_future_events(self):
        report = customer_report('CYL-001-01')
        self.assertEqual(report['transport']['reading_until_s'], 240)
        self.assertEqual(report['status']['code'], 'clear')
        self.assertEqual(report['journeys'][-1]['observations'], [])
        for previous, next_journey in zip(report['journeys'], report['journeys'][1:]):
            self.assertEqual(previous['destination'], next_journey['origin'])
        incomplete = customer_report('CYL-006-01')
        self.assertEqual(incomplete['status']['code'], 'unknown')
        self.assertTrue(any('غير مكتملة' in note for note in incomplete['transport']['notes']))

    def test_inspection_outcome_is_kept_after_closing_and_reinspection_does_not_release(self):
        tasks = self.app.state.store.all('lpg_inspections')
        isolated = customer_report('CYL-020-01', tasks)
        self.assertEqual(isolated['status']['code'], 'isolate')
        task = next(t for t in tasks if t['number'] == 20)
        self.assertEqual(customer_report('CYL-020-01', [{**task, 'status': 'closed'}])['status']['code'], 'isolate')
        normal = next(t for t in tasks if t['number'] == 14)
        self.assertEqual(customer_report('CYL-014-01', [normal])['status']['code'], 'reviewed')
        self.assertEqual(customer_report('CYL-014-01', [{**normal, 'status': 'in_progress'}])['status']['code'], 'pending')
        self.assertNotEqual(customer_report('CYL-020-01', [{**task, 'status': 'cancelled'}])['status']['code'], 'isolate')

    def test_pdf_and_qr_export_are_real_public_files(self):
        response = self.client.get('/api/public/cylinders/CYL-020-01/report.pdf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'application/pdf')
        self.assertIn('Qaif-CYL-020-01.pdf', response.headers['content-disposition'])
        reader = PdfReader(BytesIO(response.content))
        self.assertGreaterEqual(len(reader.pages), 2)
        content = reader.pages[0].extract_text()
        self.assertIn('CYL-020-01', content)
        self.assertIn('2026-09-10', content)
        self.assertIn('2026-10-08', content)
        self.assertIn('http://testserver/cylinder/CYL-020-01', str(reader.pages[0]['/Annots'][0].get_object()))
        svg = self.client.get('/api/public/cylinders/CYL-020-01/qr.svg')
        self.assertEqual(svg.status_code, 200)
        self.assertIn('image/svg+xml', svg.headers['content-type'])
        self.assertEqual(ElementTree.fromstring(svg.content).tag, '{http://www.w3.org/2000/svg}svg')

    def test_observations_keep_event_time_and_exclude_future_current_readings(self):
        report = customer_report('CYL-008-01')
        current = report['journeys'][-1]
        self.assertTrue(current['observations'])
        for event in current['observations']:
            self.assertGreaterEqual(event['reading_elapsed_s'], 120)
            self.assertLessEqual(event['reading_elapsed_s'], report['transport']['reading_until_s'])
            self.assertLessEqual(event['recorded_at'], report['transport']['reading_at'])
            location = event['location']
            self.assertEqual(location['source'], 'estimated_display_route')
            self.assertTrue(location['nearest_city'])
            self.assertGreaterEqual(location['distance_km'], 0)
            query = parse_qs(urlsplit(location['maps_url']).query)['query'][0]
            self.assertEqual(query, f"{location['latitude']:.4f},{location['longitude']:.4f}")

    def test_historical_return_uses_the_correct_route_not_the_replay_cage(self):
        report = customer_report('CYL-020-01')
        outward, returned = report['journeys'][:2]
        self.assertEqual(returned['route']['path'], list(reversed(outward['route']['path'])))
        for journey in report['journeys']:
            self.assertEqual(journey['route']['path'][0], journey['origin']['position'])
            self.assertEqual(journey['route']['path'][-1], journey['destination']['position'])
        self.assertEqual(report['journeys'][-1]['route']['path'], places()[20]['path'])

    def test_no_readings_does_not_invent_observation_coordinates(self):
        journey = cylinder_passport('CYL-020-01')['journeys'][-1]
        _, events = located_observations(journey, {'rows': [], 'alerts': [], 'incomplete': True}, places())
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]['reading_elapsed_s'])
        self.assertIsNone(events[0]['recorded_at'])
        self.assertIsNone(events[0]['location'])

    def test_pdf_contains_all_located_events_and_clickable_map_links(self):
        report = self.client.get('/api/public/cylinders/CYL-020-01/report').json()
        reader = PdfReader(BytesIO(self.client.get('/api/public/cylinders/CYL-020-01/report.pdf').content))
        content = '\n'.join(page.extract_text() for page in reader.pages)
        links = [str(annotation.get_object().get('/A', {}).get('/URI', ''))
                 for page in reader.pages for annotation in page.get('/Annots', [])]
        for journey in report['journeys']:
            for event in journey['observations']:
                location = event['location']
                if location:
                    self.assertIn(f"N {location['latitude']:.4f}", content)
                    self.assertIn(f"E {location['longitude']:.4f}", content)
                    self.assertIn(location['maps_url'], links)
                if event['recorded_at']:
                    self.assertIn(event['recorded_at'][:19].replace('T', ' '), content)

    def test_public_reports_are_disabled_with_display_mode_off(self):
        app = create_app(Path(self.directory.name) / 'no-demo', admin_password='public-gate-test-only', demo_mode=False)
        with TestClient(app) as client:
            for suffix in ('report', 'report.pdf', 'qr.svg'):
                self.assertEqual(client.get(f'/api/public/cylinders/CYL-001-01/{suffix}').status_code, 404)


if __name__ == '__main__':
    unittest.main()
