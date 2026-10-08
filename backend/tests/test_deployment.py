"""Public hosting safeguards and the same LPG flows used by the web demo."""
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.app import create_app


class PublicDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.env = patch.dict(os.environ, {
            'QAIF_PUBLIC_DEPLOYMENT': 'true',
            'QAIF_SECURE_COOKIE': 'true',
            'QAIF_PUBLIC_BASE_URL': 'https://qaif.example.test',
            'QAIF_ADMIN_PASSWORD': 'deployment-test-password-only',
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def test_rejects_incomplete_public_configuration(self):
        cases = [('QAIF_ADMIN_PASSWORD', 'short'),
                 ('QAIF_ADMIN_PASSWORD', 'replace-with-a-private-password'),
                 ('QAIF_SECURE_COOKIE', 'false'),
                 ('QAIF_PUBLIC_BASE_URL', 'http://qaif.example.test'),
                 ('QAIF_PUBLIC_BASE_URL', 'https://qaif.example.test/path'),
                 ('QAIF_PUBLIC_BASE_URL', 'https://user:password@qaif.example.test')]
        for key, value in cases:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                with self.assertRaises(RuntimeError):
                    create_app(self.root / 'rejected', demo_mode=True)
        self.assertFalse((self.root / 'rejected').exists())

    def test_authenticated_lpg_demo_without_quick_admin_access(self):
        app = create_app(self.root, demo_mode=True)
        self.assertFalse((self.root / 'setup_credentials.txt').exists())
        # Even a loopback peer/proxy must not get the quick administrator login.
        with TestClient(app, base_url='https://qaif.example.test', client=('127.0.0.1', 1234)) as client:
            self.assertEqual(client.post('/api/auth/demo?role=admin').status_code, 403)
            self.assertEqual(client.get('/api/lpg/demo/cylinders').status_code, 401)
            response = client.post('/api/auth/login', json={
                'name': 'admin', 'password': 'deployment-test-password-only'},
                headers={'Origin': 'https://qaif.example.test'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('Secure', response.headers['set-cookie'])
            self.assertIn('HttpOnly', response.headers['set-cookie'])
            self.assertEqual(client.get('/api/lpg/demo/seraj/20').status_code, 200)
            self.assertEqual(len(client.get('/api/lpg/demo/cylinders').json()['cylinders']), 189)
            self.assertEqual(client.get('/api/lpg/inspections').status_code, 200)
            config = client.get('/api/snapshot').json()['config']
            self.assertTrue(config['demo_mode'])
            self.assertTrue(config['public_deployment'])
            self.assertFalse(config['demo_login_enabled'])
            self.assertEqual(client.post('/api/auth/logout', headers={
                'Origin': 'https://unrelated.example.test'}).status_code, 403)
            with client.websocket_connect('wss://qaif.example.test/ws/events', headers={
                'Origin': 'https://qaif.example.test',
                'Cookie': 'qaif_session=' + client.cookies.get('qaif_session')}) as socket:
                socket.send_text('ping')
                self.assertEqual(socket.receive_json()['type'], 'pong')

    def test_pdf_and_qr_use_public_url_behind_proxy(self):
        app = create_app(self.root, demo_mode=True)
        with TestClient(app, base_url='http://internal-proxy') as client:
            response = client.get('/api/public/cylinders/CYL-020-01/report.pdf')
            self.assertEqual(response.status_code, 200)
            reader = PdfReader(BytesIO(response.content))
            links = [str(a.get_object()) for a in reader.pages[0]['/Annots']]
            self.assertIn('https://qaif.example.test/cylinder/CYL-020-01', '\n'.join(links))
            self.assertNotIn('internal-proxy', '\n'.join(links))
            self.assertEqual(client.get('/api/public/cylinders/CYL-020-01/qr.svg').status_code, 200)

    def test_render_supplies_canonical_url(self):
        with patch.dict(os.environ, {'QAIF_PUBLIC_BASE_URL': '',
                                     'RENDER_EXTERNAL_URL': 'https://qaif-demo.onrender.com'}):
            app = create_app(self.root, demo_mode=True)
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/health').status_code, 200)


if __name__ == '__main__':
    unittest.main()
