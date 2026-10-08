"""Verify a running container or HTTPS deployment without printing secrets."""
import json
import os
import sys
import time
from http.cookies import SimpleCookie
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8765').rstrip('/')
    cookie = None

    def call(path, body=None, expected=200):
        headers = {}
        if cookie:
            headers['Cookie'] = cookie
        if body is not None:
            headers.update({'Content-Type': 'application/json', 'Origin': base})
        request = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                assert response.status == expected, f'{path}: unexpected status'
                return response.read(), response.headers
        except HTTPError as error:
            assert error.code == expected, f'{path}: status {error.code}, expected {expected}'
            return b'', error.headers

    for attempt in range(30):
        try:
            health = json.loads(call('/api/health')[0])
            assert health['ok'] and health['demo_mode']
            break
        except (URLError, ConnectionError, AssertionError):
            # Docker can forward the socket before Uvicorn finishes startup.
            if attempt == 29:
                raise RuntimeError('Service did not become healthy') from None
            time.sleep(1)
    assert b'<html' in call('/')[0]
    assert b'<html' in call('/cylinder/CYL-020-01')[0]
    report = json.loads(call('/api/public/cylinders/CYL-020-01/report')[0])
    assert report['serial'] == 'CYL-020-01'
    assert call('/api/public/cylinders/CYL-020-01/report.pdf')[0].startswith(b'%PDF')
    assert b'<svg' in call('/api/public/cylinders/CYL-020-01/qr.svg')[0]
    call('/api/lpg/demo/cylinders', expected=401)
    call('/api/auth/demo?role=admin', {}, expected=403)
    password = os.getenv('QAIF_SMOKE_PASSWORD') or os.getenv('QAIF_ADMIN_PASSWORD')
    if not password:
        raise RuntimeError('Set QAIF_SMOKE_PASSWORD to test protected pages')
    _, headers = call('/api/auth/login', {'name': 'admin', 'password': password})
    session = SimpleCookie()
    session.load(headers['Set-Cookie'])
    assert session['qaif_session']['secure']
    cookie = 'qaif_session=' + session['qaif_session'].value
    # Explicit header also verifies a Secure-cookie API through local Docker HTTP.
    assert json.loads(call('/api/auth/me')[0])['role'] == 'admin'
    assert len(json.loads(call('/api/lpg/demo/cylinders')[0])['cylinders']) == 189
    for path in ['/api/lpg/demo/seraj/20', '/api/lpg/demo/cylinders/CYL-020-01',
                 '/api/lpg/inspections', '/api/snapshot']:
        json.loads(call(path)[0])
    print('PASS: frontend, public reports/PDF/QR, protected LPG pages, and cloud login safeguards')


if __name__ == '__main__':
    main()
