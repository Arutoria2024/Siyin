import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
from lan_access import LanAccess, settings

Connection = http.client.HTTPConnection


class Workbench(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype='application/json'):
        body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        self._send(200, 'workbench')
    def do_POST(self):
        self._send(200 if self.allowed() else 403, '{}')
    def log_message(self, *args):
        pass


class LanAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'services').mkdir()
        self.config = {'gateway': {'token': 'test-private-key', 'host': '127.0.0.1'},
                       'network': {'lan_enabled': False, 'lan_port': 9890}, 'preserve': 123}
        self.write_config()
        self.access = LanAccess(self.root, Workbench, 'workbench-session')
        self.access.firewall_status = lambda force=False: {'state': 'unknown', 'message': 'test'}
        self.access.start(0)
        self.port = self.access.server.server_port

    def write_config(self):
        (self.root / 'services/config.json').write_text(json.dumps(self.config))

    def tearDown(self):
        self.access.stop()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = Connection('127.0.0.1', self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def login(self):
        code, headers, _ = self.request('POST', '/login', urlencode({'key': 'test-private-key'}))
        self.assertEqual(code, 303)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';')[0]

    def test_login_required_and_bad_key(self):
        code, headers, _ = self.request('GET', '/')
        self.assertEqual((code, headers['Location']), (303, '/login'))
        self.assertEqual(self.request('POST', '/login', urlencode({'key': 'wrong'}))[0], 401)

    def test_authenticated_workbench_and_sensitive_controls_local_only(self):
        cookie = self.login()
        headers = {'Cookie': cookie, 'X-Workbench-Token': 'workbench-session'}
        self.assertEqual(self.request('GET', '/', headers=headers)[2], b'workbench')
        for path in ('network', 'network-firewall', 'network-key'):
            self.assertEqual(self.request('POST', '/api/workbench/' + path, '{}', headers)[0], 403)

    def test_ui_requires_session_token_and_same_origin(self):
        cookie = self.login()
        self.assertEqual(self.request('POST', '/api/workbench/submit', '{}', {'Cookie': cookie})[0], 403)
        headers = {'Cookie': cookie, 'X-Workbench-Token': 'workbench-session', 'Origin': 'http://other-host'}
        self.assertEqual(self.request('POST', '/api/workbench/submit', '{}', headers)[0], 403)
        headers['Origin'] = 'http://127.0.0.1:' + str(self.port)
        self.assertEqual(self.request('POST', '/api/workbench/submit', '{}', headers)[0], 200)

    def test_api_key_required_even_for_health(self):
        self.assertEqual(self.request('GET', '/v1/health')[0], 401)
        self.assertEqual(self.request('POST', '/v1/tts', '{}', {'Authorization': 'Bearer wrong'})[0], 401)

    def test_session_tampering_and_key_rotation(self):
        session = self.access.session()
        self.assertTrue(self.access.valid_session(session))
        self.assertFalse(self.access.valid_session(session + 'x'))
        self.config['gateway']['token'] = 'rotated-key'
        self.write_config()
        self.assertFalse(self.access.valid_session(session))

    def test_switch_closes_listener_and_invalidates_sessions(self):
        session = self.access.session()
        self.access.configure(False, 9890)
        self.assertIsNone(self.access.server)
        self.assertFalse(self.access.valid_session(session))
        self.assertEqual(self.access.config()['preserve'], 123)
        with self.assertRaises(OSError):
            socket.create_connection(('127.0.0.1', self.port), timeout=.2)

    def test_stream_proxy_preserves_pcm_and_headers(self):
        class Gateway(Workbench):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(200)
                self.send_header('Content-Type', 'audio/pcm')
                self.send_header('X-Sample-Rate', '24000')
                self.send_header('Content-Length', '4')
                self.end_headers()
                self.wfile.write(b'\x00\x01\x02\x03')
            def do_OPTIONS(self):
                self.send_response(204)
                self.end_headers()
        gateway = ThreadingHTTPServer(('127.0.0.1', 0), Gateway)
        worker = threading.Thread(target=gateway.serve_forever, daemon=True)
        worker.start()
        try:
            def factory(host, port, **kwargs):
                return Connection(host, gateway.server_port if port == 9881 else port, **kwargs)
            with patch('lan_access.http.client.HTTPConnection', side_effect=factory):
                code, headers, body = self.request('POST', '/v1/text-to-speech/si/stream', '{}',
                                                   {'Authorization': 'Bearer test-private-key'})
                self.assertEqual((code, body), (200, b'\x00\x01\x02\x03'))
                self.assertEqual(headers['X-Sample-Rate'], '24000')
                self.assertEqual(self.request('OPTIONS', '/v1/tts')[0], 204)
        finally:
            gateway.shutdown(); gateway.server_close(); worker.join()

    def test_port_validation_and_local_default(self):
        self.assertEqual(settings({}), (False, 9890))
        for port in (9881, 9888, 80, 65536, True, '9890'):
            with self.assertRaises(ValueError):
                settings({'network': {'lan_enabled': True, 'lan_port': port}})


if __name__ == '__main__':
    unittest.main()
