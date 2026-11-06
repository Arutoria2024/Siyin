"""Select only this installation's workbench; never adopt an arbitrary HTTP server."""
import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(port, root):
    base = f'http://127.0.0.1:{int(port)}'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(base + '/api/workbench/instance', timeout=1) as response:
            info = json.load(response)
        if not isinstance(info, dict) or info.get('application') != 'siyin-workbench' or info.get('protocol') != 1:
            return None
        if os.path.normcase(str(Path(info.get('root', '')).resolve())) != os.path.normcase(str(Path(root).resolve())):
            return None
        with opener.open(base, timeout=2) as response:
            html = response.read(65536).decode('utf-8')
        token = re.search(r'name="session-token" content="([^"]+)"', html)
        if not token or token[1] == '__SESSION_TOKEN__':
            return None
        return {'base_url': base, 'token': token[1]}
    except (OSError, ValueError, TypeError):
        return None


def free_port(port=0):
    try:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', port))
            return sock.getsockname()[1]
    except OSError:
        return None


def ensure(root):
    root = Path(root).resolve()
    state = root / 'run' / 'desktop-server.json'
    ports = [9888, 9898]
    try:
        cached = int(json.loads(state.read_text(encoding='utf-8'))['port'])
        if 1 <= cached <= 65535:
            ports.insert(0, cached)
    except (OSError, ValueError, TypeError, KeyError):
        pass
    ports = list(dict.fromkeys(ports))
    for port in ports:
        ready = probe(port, root)
        if ready:
            return ready
    for candidate in ports + [0, 0]:
        port = free_port(candidate)
        if port is None:
            continue
        env = dict(os.environ, GSV_NO_BROWSER='1', GSV_WORKBENCH_PORT=str(port))
        child = subprocess.Popen(
            [str(root / 'python/pythonw.exe'), str(root / 'monitor/monitor.py')],
            cwd=root, env=env, creationflags=0x08000000)
        deadline = time.monotonic() + 40
        while child.poll() is None and time.monotonic() < deadline:
            ready = probe(port, root)
            if ready:
                state.parent.mkdir(parents=True, exist_ok=True)
                temp = state.with_suffix('.tmp')
                temp.write_text(json.dumps({'port': port}), encoding='utf-8')
                os.replace(temp, state)
                return ready
            time.sleep(.25)
        # This is a newly spawned monitor, never an existing server/model process.
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
    raise RuntimeError('无法启动本机桌面工作台，请检查 app/logs/desktop.log。')
