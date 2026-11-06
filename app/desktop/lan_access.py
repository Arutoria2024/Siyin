"""Optional authenticated LAN entry for the existing workbench and TTS gateway."""
import base64
import hashlib
import hmac
import html
import http.client
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlsplit


def ipv4_addresses():
    import psutil
    result = []
    stats = psutil.net_if_stats()
    for name, addresses in psutil.net_if_addrs().items():
        if name in stats and not stats[name].isup:
            continue
        for item in addresses:
            try:
                address = ipaddress.ip_address(item.address)
            except ValueError:
                continue
            if address.version == 4 and not address.is_loopback and not address.is_link_local and not address.is_unspecified:
                result.append({'interface': name, 'address': str(address)})
    return sorted(result, key=lambda row: (not ipaddress.ip_address(row['address']).is_private, row['interface']))


def settings(config):
    value = config.get('network') or {}
    enabled = value.get('lan_enabled', False)
    port = value.get('lan_port', 9890)
    if not isinstance(enabled, bool):
        raise ValueError('局域网开关必须为布尔值')
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535 or port in (9880, 9881, 9882, 9888, 9898):
        raise ValueError('局域网端口须为 1024～65535，且不能占用本机服务端口')
    return enabled, port


def _ps(code, timeout=20):
    encoded = base64.b64encode(code.encode('utf-16le')).decode()
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, timeout=timeout, creationflags=0x08000000)
    output = result.stdout.decode('utf-8-sig', 'replace').strip()
    if result.returncode:
        raise RuntimeError('Windows 防火墙操作未完成；可能缺少管理员权限或取消了授权。')
    return output


class LanAccess:
    def __init__(self, root, handler, token, prepare_gateway=None):
        self.root = Path(root).resolve()
        self.handler = handler
        self.token = token
        self.prepare_gateway = prepare_gateway
        self.secret = secrets.token_bytes(32)
        self.server = None
        self.thread = None
        self.lock = threading.RLock()
        self.error = ''
        self.rule = 'SiYin-LAN-' + hashlib.sha256(str(self.root).lower().encode()).hexdigest()[:12]
        self.firewall_cache = (0, {'state': 'unknown', 'message': '尚未检查'})
        self.firewall_reading = False
        self.failures = {}

    def config(self):
        return json.loads((self.root / 'services/config.json').read_text(encoding='utf-8'))

    def key(self):
        return str(self.config().get('gateway', {}).get('token') or '')

    def valid_key(self, value):
        expected = self.key()
        return bool(expected) and hmac.compare_digest(str(value).encode(), expected.encode())

    def session(self):
        payload = f'{int(time.time()) + 28800}.{secrets.token_hex(16)}'
        signature = hmac.new(self.secret, (payload + self.key()).encode(), hashlib.sha256).hexdigest()
        return payload + '.' + signature

    def valid_session(self, value):
        try:
            expiry, nonce, signature = value.split('.')
            if int(expiry) < time.time() or int(expiry) > time.time() + 28860:
                return False
            expected = hmac.new(self.secret, (expiry + '.' + nonce + self.key()).encode(), hashlib.sha256).hexdigest()
            return bool(self.key()) and hmac.compare_digest(signature, expected)
        except (ValueError, AttributeError):
            return False

    def firewall_status(self, force=False):
        if not force and time.monotonic() - self.firewall_cache[0] < 30:
            return self.firewall_cache[1]
        if not force:
            if not self.firewall_reading:
                self.firewall_reading = True
                def read_later():
                    try:
                        self.firewall_status(force=True)
                    finally:
                        self.firewall_reading = False
                threading.Thread(target=read_later, daemon=True).start()
            return self.firewall_cache[1]
        try:
            code = "$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
            code += f"$r=Get-NetFirewallRule -Name '{self.rule}' -ErrorAction SilentlyContinue;"
            code += "if($r){$p=$r|Get-NetFirewallPortFilter;$a=$r|Get-NetFirewallAddressFilter;"
            code += "@{exists=$true;enabled=($r.Enabled -eq 'True');action=[string]$r.Action;port=[string]$p.LocalPort;scope=@($a.RemoteAddress)}|ConvertTo-Json -Compress}else{'{\"exists\":false}'}"
            info = json.loads(_ps(code))
            _, port = settings(self.config())
            active = (info.get('enabled') and info.get('action') == 'Allow' and
                      info.get('port') == str(port) and info.get('scope') == ['LocalSubnet'])
            info.update(state='allowed' if active else 'disabled' if info.get('exists') else 'missing',
                        message='已允许本地子网访问' if active else '尚未放行当前端口')
        except Exception:
            info = {'state': 'unknown', 'message': '无法读取防火墙状态，请检查 Windows 权限'}
        self.firewall_cache = (time.monotonic(), info)
        return info

    def firewall_apply(self, enabled):
        _, port = settings(self.config())
        program = str(self.root / 'python/pythonw.exe').replace("'", "''")
        name = self.rule
        code = "$ErrorActionPreference='Stop';"
        if enabled:
            code += f"$r=Get-NetFirewallRule -Name '{name}' -ErrorAction SilentlyContinue;"
            code += f"if($r){{$r|Remove-NetFirewallRule}};New-NetFirewallRule -Name '{name}' -DisplayName '祀音 - 局域网工作台与 API' -Direction Inbound -Action Allow -Enabled True -Protocol TCP -LocalPort {port} -RemoteAddress LocalSubnet -Profile Any -Program '{program}'|Out-Null"
        else:
            code += f"Get-NetFirewallRule -Name '{name}' -ErrorAction SilentlyContinue|Set-NetFirewallRule -Enabled False"
        encoded = base64.b64encode(code.encode('utf-16le')).decode()
        outer = "$ErrorActionPreference='Stop';try{"
        outer += "$p=Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList "
        outer += f"@('-NoProfile','-NonInteractive','-EncodedCommand','{encoded}');exit $p.ExitCode}}catch{{exit 1223}}"
        _ps(outer, timeout=120)
        return self.firewall_status(force=True)

    def status(self, firewall=False):
        enabled, port = settings(self.config())
        addresses = ipv4_addresses()
        return {'local_enabled': True, 'local_api': 'http://127.0.0.1:9881',
                'local_workbench': None, 'enabled': enabled, 'port': port,
                'listening': self.server is not None, 'addresses': addresses,
                'urls': [f'http://{item["address"]}:{port}' for item in addresses],
                'api_key_set': bool(self.key()), 'error': self.error,
                'firewall': self.firewall_status(force=firewall)}

    def start(self, port):
        if not self.key():
            raise ValueError('请先配置 API Key，才能开启局域网访问')
        server = ThreadingHTTPServer(('0.0.0.0', port), self.lan_handler())
        server.daemon_threads = True
        self.server = server
        self.thread = threading.Thread(target=server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        server, self.server = self.server, None
        if server:
            # shutdown closes the listener; authenticated in-flight UI sessions
            # are also invalidated, and PCM streams check the switch per chunk.
            server.shutdown()
            server.server_close()
            self.thread.join(timeout=3)
        self.secret = secrets.token_bytes(32)

    def configure(self, enabled, port):
        settings({'network': {'lan_enabled': enabled, 'lan_port': port}})
        with self.lock:
            if self.prepare_gateway:
                self.prepare_gateway()
            old_enabled, old_port = settings(self.config())
            if self.server and (not enabled or self.server.server_port != port):
                self.stop()
            try:
                if enabled and not self.server:
                    self.start(port)
                config = self.config()
                config['network'] = {'lan_enabled': enabled, 'lan_port': port}
                config['gateway']['host'] = '127.0.0.1'
                target = self.root / 'services/config.json'
                temp = target.with_suffix('.network.tmp')
                temp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                os.replace(temp, target)
                self.error = ''
            except Exception:
                self.stop()
                if old_enabled:
                    self.start(old_port)
                raise
        return self.status()

    def restore(self):
        try:
            if self.prepare_gateway:
                self.prepare_gateway()
            enabled, port = settings(self.config())
            if enabled:
                self.start(port)
        except Exception as exc:
            self.error = str(exc)

    def lan_handler(self):
        owner = self
        class Handler(self.handler):
            protocol_version = 'HTTP/1.1'
            is_lan = True
            def log_message(self, *args):
                pass
            def local_host(self):
                return True  # LAN requests pass the authentication gate below.
            def same_origin(self):
                origin = self.headers.get('Origin')
                return not origin or urlsplit(origin).netloc == self.headers.get('Host')
            def logged_in(self):
                try:
                    cookie = SimpleCookie(self.headers.get('Cookie', ''))
                    return owner.valid_session(cookie['siyin_session'].value)
                except (KeyError, ValueError):
                    return False
            def allowed(self):
                return self.logged_in() and self.same_origin() and self.headers.get('X-Workbench-Token') == owner.token
            def redirect(self, path, cookie=None):
                self.send_response(303)
                self.send_header('Location', path)
                self.send_header('Content-Length', '0')
                self.send_header('Cache-Control', 'no-store')
                if cookie:
                    self.send_header('Set-Cookie', cookie)
                self.end_headers()
            def login_page(self, failed=False):
                message = 'API Key 不正确，请重新输入。' if failed else '请输入服务电脑上的 API Key，以访问语音工作台。'
                page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>祀音 · 局域网访问</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f3ec;color:#242c29;font:15px "Segoe UI","Microsoft YaHei",sans-serif}form{box-sizing:border-box;width:min(420px,90vw);padding:36px;background:#ffffffc9;border:1px solid #dce4da;border-radius:24px;box-shadow:0 20px 70px #242c2910}h1{font-family:serif;font-size:30px;font-weight:500}p{color:#6d7d73;line-height:1.8}input,button{box-sizing:border-box;width:100%;padding:13px;border-radius:10px;font:inherit}input{border:1px solid #a9bba8;background:#fff}button{margin-top:18px;border:0;background:#46786b;color:white;cursor:pointer}small{display:block;margin-top:20px;color:#6d7d73}</style><form method="post" action="/login"><h1>祀音</h1><p>' + html.escape(message) + '</p><input name="key" type="password" autocomplete="current-password" aria-label="API Key" placeholder="API Key" required><button>进入工作台</button><small>同一局域网 · 数据保存在服务电脑</small></form></html>'
                return self._send(401 if failed else 200, page, 'text/html; charset=utf-8')
            def api_path(self):
                path = urlsplit(self.path).path
                return path.startswith('/v1/') or path in ('/health', '/voices')
            def proxy_api(self):
                auth = self.headers.get('Authorization', '')
                key = auth[7:].strip() if auth.lower().startswith('bearer ') else self.headers.get('X-Auth-Token', '')
                if not key:
                    key = parse_qs(urlsplit(self.path).query).get('token', [''])[0]
                if self.command != 'OPTIONS' and not owner.valid_key(key):
                    self.close_connection = True
                    self.send_response(401)
                    self.send_header('Access-Control-Allow-Origin', '*')
                    body = b'{"error":"invalid or missing token","code":401}'
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers(); self.wfile.write(body); return
                conn = http.client.HTTPConnection('127.0.0.1', 9881, timeout=300)
                started = False
                try:
                    size = int(self.headers.get('Content-Length', 0))
                    if size < 0 or size > 2000000 or self.headers.get('Transfer-Encoding'):
                        return self._send(400, '{"error":"invalid request body"}')
                    body = self.rfile.read(size) if size else None
                    headers = {'Authorization': 'Bearer ' + key, 'X-Forwarded-For': self.client_address[0]}
                    for name in ('Content-Type', 'Origin', 'Access-Control-Request-Headers', 'Access-Control-Request-Method'):
                        if self.headers.get(name): headers[name] = self.headers[name]
                    conn.request(self.command, self.path, body=body, headers=headers)
                    response = conn.getresponse()
                    self.send_response(response.status)
                    for name, value in response.getheaders():
                        if name.lower() not in ('transfer-encoding', 'connection', 'content-length', 'server', 'date'):
                            self.send_header(name, value)
                    if response.status not in (204, 304):
                        self.send_header('Transfer-Encoding', 'chunked')
                    self.send_header('Access-Control-Expose-Headers', 'X-Sample-Rate, X-Channels, X-Format, X-Voice, Retry-After, X-Audio-Seconds')
                    self.end_headers(); started = True
                    if response.status in (204, 304): return
                    while owner.server is not None:
                        data = response.read1(16384)
                        if not data: break
                        self.wfile.write(b'%x\r\n' % len(data) + data + b'\r\n'); self.wfile.flush()
                    if owner.server is None:
                        self.close_connection = True
                    else:
                        self.wfile.write(b'0\r\n\r\n'); self.wfile.flush()
                except (OSError, ValueError, http.client.HTTPException):
                    if not started: self._send(502, '{"error":"local gateway unavailable"}')
                    self.close_connection = True
                finally:
                    conn.close()
            def do_OPTIONS(self):
                if self.api_path(): return self.proxy_api()
                return self._send(405, '{}')
            def do_GET(self):
                path = urlsplit(self.path).path
                if self.api_path(): return self.proxy_api()
                if path == '/login': return self.login_page()
                if not self.logged_in(): return self.redirect('/login')
                if path == '/api/workbench/instance': return self._send(404, '{}')
                return super().do_GET()
            def do_POST(self):
                path = urlsplit(self.path).path
                if self.api_path(): return self.proxy_api()
                if not self.same_origin(): return self._send(403, '{}')
                if path == '/login':
                    ip = self.client_address[0]
                    count, last = owner.failures.get(ip, (0, 0))
                    if count >= 10 and time.time() - last < 60:
                        return self._send(429, '{"error":"请稍后再试"}')
                    size = int(self.headers.get('Content-Length', 0))
                    if size <= 0 or size > 4096: return self.login_page(True)
                    key = parse_qs(self.rfile.read(size).decode('utf-8', 'replace')).get('key', [''])[0]
                    if not owner.valid_key(key):
                        if len(owner.failures) > 256: owner.failures.clear()
                        owner.failures[ip] = ((count + 1) if time.time() - last < 60 else 1, time.time())
                        return self.login_page(True)
                    owner.failures.pop(ip, None)
                    return self.redirect('/', 'siyin_session=' + owner.session() + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800')
                if not self.logged_in(): return self._send(401, '{"error":"请先使用 API Key 登录"}')
                if path in ('/api/workbench/network', '/api/workbench/network-firewall', '/api/workbench/network-key'):
                    return self._send(403, '{"error":"网络开关与密钥管理请在服务电脑上操作"}')
                return super().do_POST()
        return Handler
