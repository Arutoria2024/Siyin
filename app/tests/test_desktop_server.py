import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'desktop'))
import desktop_server


class DesktopServerTests(unittest.TestCase):
    def check_server(self, info, html):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(info).encode() if self.path.endswith('/instance') else html.encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            return desktop_server.probe(server.server_port, Path(__file__).parent)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def info(self, root=None):
        return {'application': 'siyin-workbench', 'protocol': 1,
                'root': str(root or Path(__file__).parent)}

    def test_accepts_only_own_workbench(self):
        ready = self.check_server(self.info(), '<meta name="session-token" content="test-session">')
        self.assertEqual(ready['token'], 'test-session')

    def test_rejects_legacy_server(self):
        self.assertIsNone(self.check_server({'ok': True}, '<title>Server monitor</title>'))

    def test_rejects_other_installation(self):
        self.assertIsNone(self.check_server(self.info(Path(__file__).parent / 'other'),
                                           '<meta name="session-token" content="test-session">'))

    def test_rejects_unbuilt_or_uninjected_page(self):
        self.assertIsNone(self.check_server(self.info(), '<meta name="session-token" content="__SESSION_TOKEN__">'))

    def test_reuses_verified_workbench_without_launch(self):
        with patch.object(desktop_server, 'probe', return_value={'base_url': 'http://127.0.0.1:9888', 'token': 'test'}), \
             patch.object(desktop_server.subprocess, 'Popen') as spawn:
            ready = desktop_server.ensure(Path(__file__).parent)
            self.assertEqual(ready['token'], 'test')
            spawn.assert_not_called()

    def test_occupied_legacy_port_uses_isolated_workbench(self):
        ready = {'base_url': 'http://127.0.0.1:9898', 'token': 'test'}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(desktop_server, 'probe', side_effect=[None, None, ready]), \
             patch.object(desktop_server, 'free_port', side_effect=[None, 9898]), \
             patch.object(desktop_server.subprocess, 'Popen') as spawn:
            spawn.return_value.poll.return_value = None
            self.assertEqual(desktop_server.ensure(folder), ready)
            self.assertEqual(spawn.call_args.kwargs['env']['GSV_WORKBENCH_PORT'], '9898')
            self.assertEqual(spawn.call_args.kwargs['env']['GSV_NO_BROWSER'], '1')
            self.assertEqual(json.loads((Path(folder) / 'run/desktop-server.json').read_text())['port'], 9898)


if __name__ == '__main__':
    unittest.main()
