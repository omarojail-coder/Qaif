import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.drone_flight import make_plan, display_position, great_circle, distance_km
from backend.app import create_app


class GeometryTests(unittest.TestCase):
    def test_nearest_uses_geographic_distance_and_valid_facilities(self):
        saddle={'id':'S-test','name':'Target','lon':40,'lat':60}
        assets=[{'id':'a','name':'A','type':'gas','lon':40,'lat':60.1},
                {'id':'b','name':'B','type':'refinery','lon':40.15,'lat':60},
                {'id':'c','name':'Unrelated','type':'other','lon':40,'lat':60},
                {'id':'d','name':'Bad','type':'gas','lon':float('nan'),'lat':60}]
        result=make_plan(saddle,assets)
        self.assertEqual(result['origin']['id'],'b')
        self.assertAlmostEqual(result['distance_km'],8.34,places=1)
        self.assertEqual(result['path'][0],[40.15,60])
        self.assertEqual(result['path'][-1],[40,60])
        self.assertEqual(len(result['path']),65)
        self.assertIsNone(result['started_ms'])

    def test_corrected_coordinates_preserve_edited_locations(self):
        asset={'id':'refinery-2','source':'illustrative_inventory','lon':50.14,'lat':26.65}
        self.assertEqual(display_position(asset),[50.09207,26.70243])
        self.assertEqual(display_position({**asset,'lon':50.15}),[50.15,26.65])
        self.assertEqual(display_position({**asset,'source':'device'}),[50.14,26.65])

    def test_invalid_and_zero_length_routes(self):
        a={'id':'x','name':'X','type':'gas','lon':49,'lat':25}
        self.assertIsNone(make_plan(a,[]))
        self.assertIsNone(make_plan({**a,'lon':True},[a]))
        self.assertIsNone(make_plan({**a,'lat':91},[a]))
        result=make_plan(a,[a],start=True,at_ms=1000)
        self.assertEqual(result['duration_s'],0)
        self.assertEqual(result['started_ms'],1000)
        self.assertEqual(result['path'],[[49,25],[49,25]])
        self.assertAlmostEqual(distance_km([0,0],[0,1]),111.195,places=2)

    def test_interpolated_route_stays_finite_and_monotonic(self):
        path=great_circle([39.1,24.1],[49.2,25.5])
        self.assertTrue(all(all(math.isfinite(v) for v in p) for p in path))
        distances=[distance_km(path[0],p) for p in path]
        self.assertTrue(all(a<=b for a,b in zip(distances,distances[1:])))


class FlightApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.client=TestClient(create_app(Path(self.temp.name),admin_password='flight-test-password',demo_mode=True))
        self.client.__enter__()
        self.client.post('/api/auth/login',json={'name':'admin','password':'flight-test-password'})

    def tearDown(self):
        self.client.__exit__(None,None,None); self.client.close(); self.temp.cleanup()

    def request_mission(self):
        r=self.client.post('/api/missions',json={'saddle_id':'S-8','reason':'Test virtual route','image_type':'both'})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def test_new_request_starts_and_persists_own_virtual_flight(self):
        with patch('backend.drone_flight.clock_ms',return_value=10000):
            a=self.request_mission()
        with patch('backend.drone_flight.clock_ms',return_value=20000):
            b=self.request_mission()
        self.assertEqual(a['status'],'new')
        self.assertEqual(a['virtual_flight']['started_ms'],10000)
        self.assertEqual(b['virtual_flight']['started_ms'],20000)
        self.assertEqual(a['virtual_flight']['target']['id'],'S-8')
        packet=self.client.get('/api/missions/'+a['id']+'/flight').json()
        self.assertEqual(packet['plan'],a['virtual_flight'])
        snapshot=self.client.get('/api/snapshot').json()
        self.assertEqual(snapshot['captures'],[])
        self.assertEqual(snapshot['analyses'],[])
        self.assertEqual(snapshot['reports'],[])

    def test_repeated_start_does_not_reset_and_explicit_restart_does(self):
        with patch('backend.drone_flight.clock_ms',return_value=10000):
            m=self.request_mission()
        url='/api/missions/'+m['id']+'/flight/start'
        with patch('backend.drone_flight.clock_ms',return_value=20000):
            r=self.client.post(url,json={})
        self.assertEqual(r.json()['plan']['started_ms'],10000)
        with patch('backend.drone_flight.clock_ms',return_value=30000):
            r=self.client.post(url,json={'restart':True})
        self.assertEqual(r.json()['plan']['started_ms'],30000)

    def test_cancel_stops_the_flight_and_blocks_replay(self):
        m=self.request_mission()
        with patch('backend.drone_flight.clock_ms',return_value=50000):
            r=self.client.post('/api/missions/'+m['id']+'/transition',json={'status':'cancelled','notes':'Cancelled test'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['virtual_flight']['stopped_ms'],50000)
        self.assertEqual(self.client.post('/api/missions/'+m['id']+'/flight/start',json={}).status_code,409)

    def test_legacy_read_is_non_mutating_and_start_keeps_workflow_status(self):
        store=self.client.app.state.store
        old={'id':'D-legacy','status':'review','saddle_id':'S-4','reason':'Old demo'}
        store.put('missions',old)
        before=store.get('missions','D-legacy'); history=len(store.history('D-legacy'))
        packet=self.client.get('/api/missions/D-legacy/flight').json()
        self.assertIsNone(packet['plan']['started_ms'])
        self.assertEqual(store.get('missions','D-legacy'),before)
        self.assertEqual(len(store.history('D-legacy')),history)
        self.assertEqual(self.client.post('/api/missions/D-legacy/flight/start',json={}).status_code,200)
        self.assertEqual(store.get('missions','D-legacy')['status'],'review')

    def test_viewer_cannot_start_flight_or_access_without_session(self):
        m=self.request_mission()
        self.client.post('/api/users',json={'name':'flight-inspector','role':'inspector','password':'test-inspector-pass'})
        self.client.post('/api/auth/logout',json={})
        self.assertEqual(self.client.get('/api/missions/'+m['id']+'/flight').status_code,401)
        self.client.post('/api/auth/login',json={'name':'flight-inspector','password':'test-inspector-pass'})
        self.assertEqual(self.client.get('/api/missions/'+m['id']+'/flight').status_code,200)
        self.assertEqual(self.client.post('/api/missions/'+m['id']+'/flight/start',json={}).status_code,403)


if __name__=='__main__': unittest.main()
