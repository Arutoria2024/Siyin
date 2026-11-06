#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gsv-tts 轻量监控 & 控制器（无窗口，pythonw 运行）。
- 网页: http://localhost:9888
- 提供 /api/status /api/start /api/stop /api/test
- 自身不加载模型，仅在请求时查询/拉起子进程，idle 近乎零占用。
"""
import os, sys, json, time, threading, subprocess, socketserver, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYEXE = os.path.join(ROOT, 'python', 'python.exe')
PYW = os.path.join(ROOT, 'python', 'pythonw.exe')
ENGINE = os.path.join(ROOT, 'engine', 'gsv_server.exe')
SIDECAR = os.path.join(ROOT, 'frontend', 'text_sidecar.py')
GATEWAY = os.path.join(ROOT, 'services', 'gateway', 'gateway.py')
CONFIG = os.path.join(ROOT, 'services', 'config.json')
RUNDIR = os.path.join(ROOT, 'run')
LOGDIR = os.path.join(ROOT, 'monitor', 'logs')
os.makedirs(RUNDIR, exist_ok=True)
os.makedirs(LOGDIR, exist_ok=True)

PORT_ENGINE = 9880
PORT_SIDECAR = 9882
PORT_GATEWAY = 9881
MONITOR_PORT = int(os.environ.get('GSV_WORKBENCH_PORT', '9888'))

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
# NOTE: do NOT add DETACHED_PROCESS (0x00000008) here. For console programs it
# makes Windows allocate a *fresh* console instead of reusing a hidden one, and
# that fresh console is what flashed a black window on the desktop. A new
# process group plus CREATE_NO_WINDOW keeps children silent and still lets us
# signal them as a group.
FLAGS = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP

_children = {}
_lock = threading.Lock()
_starting = {'v': False}
_gpu_cache = {'t': 0.0, 'v': None}
_last_test = {'v': None}


def read_cfg():
    try:
        with open(CONFIG, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def token():
    return (read_cfg().get('gateway') or {}).get('token') or ''


def _env():
    e = dict(os.environ)
    e['GGML_VK_DISABLE_COOPMAT2'] = '1'
    e['PYTHONIOENCODING'] = 'utf-8'
    e['GSV_G2PW_MODEL'] = os.path.join(ROOT, 'models', 'frontend', 'g2pw')
    e['GSV_BERT_DIR'] = os.path.join(ROOT, 'models', 'frontend', 'bert_tokenizer')
    e['GSV_FAST_LANGDETECT'] = os.path.join(ROOT, 'models', 'frontend', 'fast_langdetect')
    e['NLTK_DATA'] = os.path.join(ROOT, 'models', 'nltk_data')
    return e


def _http_json(url, timeout=2.0, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def gpu_info():
    now = time.time()
    if now - _gpu_cache['t'] < 1.5 and _gpu_cache['v']:
        return _gpu_cache['v']
    try:
        out = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu',
             '--format=csv,noheader,nounits'],
            timeout=4, creationflags=CREATE_NO_WINDOW).decode('utf-8', 'replace').strip()
        parts = [p.strip() for p in out.split(',')]
        v = {'util_pct': int(parts[0]), 'used_mb': int(parts[1]),
             'total_mb': int(parts[2]), 'temp_c': int(parts[3])}
    except Exception:
        v = None
    _gpu_cache['t'] = now
    _gpu_cache['v'] = v
    return v


def _pid_file(name):
    return os.path.join(RUNDIR, name + '.pid')


def _save_pid(name, pid):
    try:
        with open(_pid_file(name), 'w') as f:
            f.write(str(pid))
    except Exception:
        pass


def _kill_pid(pid):
    try:
        import psutil
        p = psutil.Process(pid)
        cmd = ' '.join(p.cmdline()).lower()
        expected = (ENGINE, SIDECAR, GATEWAY)
        if not any(os.path.normcase(x).lower() in cmd for x in expected):
            return
    except Exception:
        return
    try:
        subprocess.run(['taskkill', '/PID', str(pid), '/F'],
                       creationflags=CREATE_NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
    except Exception:
        pass


def _spawn(name, args, logname):
    port = {'sidecar': PORT_SIDECAR, 'engine': PORT_ENGINE, 'gateway': PORT_GATEWAY}[name]
    try:
        import socket
        with socket.create_connection(('127.0.0.1', port), timeout=.5):
            return None
    except OSError:
        pass
    logp = os.path.join(LOGDIR, logname)
    logf = open(logp, 'ab')
    # gsv_server.exe is a *console* binary: without CREATE_NO_WINDOW it always
    # allocates a console, which is the black window the user kept seeing.
    p = subprocess.Popen(args, cwd=ROOT, env=_env(),
                         stdout=logf, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL,
                         creationflags=FLAGS, close_fds=True)
    _save_pid(name, p.pid)
    with _lock:
        _children[name] = p
    return p


def _wait(url, ok_key, timeout_s):
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            j = _http_json(url, timeout=1.5)
            if j.get(ok_key):
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def do_start():
    with _lock:
        if _starting['v']:
            return
        _starting['v'] = True
    try:
        # 1) sidecar
        _spawn('sidecar', [PYW, SIDECAR, '--host', '127.0.0.1', '--port', str(PORT_SIDECAR)], 'sidecar.log')
        _wait('http://127.0.0.1:%d/health' % PORT_SIDECAR, 'ok', 45)
        # 2) engine
        _spawn('engine', [ENGINE, '--models', 'models', '--device', 'vulkan',
                          '--port', str(PORT_ENGINE), '--sidecar', '127.0.0.1:%d' % PORT_SIDECAR,
                          '--allow-path', ROOT], 'engine.log')
        if not _wait('http://127.0.0.1:%d/health' % PORT_ENGINE, 'ok', 90):
            return
        # 3) load voice
        try:
            current = _http_json('http://127.0.0.1:%d/health' % PORT_ENGINE)
            if current.get('voice') != 'si':
                urllib.request.urlopen('http://127.0.0.1:%d/set_gpt_weights?weights_path=si' % PORT_ENGINE,
                                       timeout=240).read()
        except Exception:
            pass
        # 4) gateway
        _spawn('gateway', [PYW, GATEWAY, '--config', CONFIG], 'gateway.log')
        _wait('http://127.0.0.1:%d/v1/health' % PORT_GATEWAY, 'ok', 30)
    finally:
        _starting['v'] = False


def prepare_local_gateway():
    """Migrate this installation's legacy wildcard listener, without touching the model."""
    import psutil
    listeners = [c for c in psutil.net_connections(kind='tcp')
                 if c.status == psutil.CONN_LISTEN and c.laddr.port == PORT_GATEWAY
                 and c.laddr.ip not in ('127.0.0.1', '::1')]
    if not listeners:
        return
    gateway = _http_json('http://127.0.0.1:%d/v1/health' % PORT_GATEWAY, timeout=3)
    if gateway.get('active_requests'):
        raise RuntimeError('当前有语音请求，请完成后再应用局域网设置。')
    for listener in listeners:
        if not listener.pid:
            raise RuntimeError('无法确认旧网关进程，请先在原服务中关闭它。')
        process = psutil.Process(listener.pid)
        expected = os.path.normcase(os.path.abspath(GATEWAY))
        if not any(os.path.normcase(os.path.abspath(arg)) == expected for arg in process.cmdline()):
            raise RuntimeError('9881 被其他服务占用，请在原服务中关闭它。')
        process.terminate()
        process.wait(timeout=8)
        with _lock:
            _children.pop('gateway', None)
    _spawn('gateway', [PYW, GATEWAY, '--config', CONFIG], 'gateway.log')
    if not _wait('http://127.0.0.1:%d/v1/health' % PORT_GATEWAY, 'ok', 45):
        raise RuntimeError('网关重新加载尚未完成，请稍后再试。')


def do_stop():
    for name in ('gateway', 'engine', 'sidecar'):
        p = _children.get(name)
        if p and p.poll() is None:
            _kill_pid(p.pid)
        try:
            with open(_pid_file(name)) as f:
                pid = int(f.read().strip())
            _kill_pid(pid)
        except Exception:
            pass
        try:
            os.remove(_pid_file(name))
        except Exception:
            pass
        with _lock:
            _children.pop(name, None)
    # Last-resort sweep: match the exact engine binary path, never a bare
    # image name. `taskkill /IM gsv_server.exe` would also kill any unrelated
    # copy of the engine started elsewhere on this laptop.
    try:
        pids = _pids_by_cmdline(ENGINE)
        for pid in pids:
            _kill_pid(pid)
    except Exception:
        pass


def _pids_by_cmdline(needle):
    """PIDs whose command line contains `needle` (case-insensitive)."""
    out = []
    try:
        import subprocess as _sp
        ps = ("Get-CimInstance Win32_Process | "
              "Where-Object { $_.CommandLine -like '*%s*' -and "
              "$_.Name -ne 'powershell.exe' -and $_.Name -ne 'cmd.exe' } | "
              "ForEach-Object { $_.ProcessId }" % needle.replace("'", "''"))
        raw = _sp.check_output(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
            timeout=8, creationflags=CREATE_NO_WINDOW,
            stderr=_sp.DEVNULL).decode('utf-8', 'replace')
        for line in raw.splitlines():
            line = line.strip()
            if line.isdigit():
                out.append(int(line))
    except Exception:
        pass
    return out


def status():
    eng = None
    try:
        eng = _http_json('http://127.0.0.1:%d/health' % PORT_ENGINE, timeout=1.2)
    except Exception:
        eng = None
    gw = None
    try:
        gw = _http_json('http://127.0.0.1:%d/v1/health' % PORT_GATEWAY, timeout=1.2,
                        headers={'Authorization': 'Bearer ' + token()})
    except Exception:
        gw = None
    cfg = read_cfg()
    vname = (cfg.get('default_voice') or 'si')
    speed = ((cfg.get('voices') or {}).get(vname) or {}).get('speed_factor', 0.88)
    state = 'stopped'
    if _starting['v']:
        state = 'loading'
    elif eng and eng.get('ok'):
        state = 'running'
    elif eng is None and any(_children.values()):
        state = 'loading'
    elif eng is not None and not eng.get('ok'):
        state = 'error'
    out = {
        'state': state,
        'engine_ok': bool(eng and eng.get('ok')),
        'gateway_ok': bool(gw and gw.get('ok')),
        'gateway_reachable': bool(gw is not None),
        'voice': (eng or {}).get('voice') or vname,
        'sample_rate': ((gw or {}).get('sample_rate') or 24000),
        'speed_factor': speed,
        'queue': (gw or {}).get('active_requests') or (eng or {}).get('queue') or 0,
        'gpu': ({'util_pct': gw['gpu'].get('gpu_util_pct'), 'used_mb': gw['gpu'].get('vram_used_mb'),
                 'total_mb': gw['gpu'].get('vram_total_mb'), 'temp_c': gw['gpu'].get('gpu_temp_c')}
                if gw and gw.get('gpu') else gpu_info()),
        'stats': (gw or {}).get('stats') or {},
        'last_test': _last_test['v'],
        'uptime': (gw or {}).get('stats', {}).get('uptime_s'),
        'ts': int(time.time()),
    }
    return out


def do_test(text):
    t0 = time.time()
    body = json.dumps({'text': text, 'speed_factor': 0.88}).encode('utf-8')
    req = urllib.request.Request('http://127.0.0.1:%d/v1/tts' % PORT_GATEWAY, data=body,
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + token()})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
        audio_sec = float(r.headers.get('X-Audio-Seconds') or 0)
        first = time.time() - t0
    res = {'chars': len(text), 'audio_sec': round(audio_sec, 2),
           'bytes': len(data), 'total_ms': round((time.time() - t0) * 1000),
           'first_ms': round(first * 1000)}
    _last_test['v'] = res
    return res


PAGE = r'''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>祀 · 语音服务监控</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
background:radial-gradient(1200px 700px at 75% -10%,rgba(90,120,200,.16),transparent),
linear-gradient(160deg,#0d1117,#151b26 60%,#1b2330);color:#eaf0f7;padding:34px 16px;display:flex;justify-content:center}
.wrap{width:100%;max-width:600px}
.card{background:rgba(28,36,50,.62);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
border:1px solid rgba(255,255,255,.08);border-radius:24px;box-shadow:0 8px 40px rgba(0,0,0,.45);
padding:30px 32px;margin-bottom:18px}
h1{font-size:26px;font-weight:700;letter-spacing:.5px;margin-bottom:6px}
.sub{color:#8a94a6;font-size:13px;margin-bottom:18px}
.state{display:flex;align-items:center;gap:9px;font-size:15px;color:#93a0b4;margin-bottom:22px}
.dot{width:11px;height:11px;border-radius:50%;box-shadow:0 0 10px currentColor}
.row{margin:16px 0}
.lbl{color:#93a0b4;font-size:15px;margin-bottom:6px;display:flex;align-items:center;gap:8px}
.big{font-size:46px;font-weight:800;line-height:1.05;letter-spacing:.5px}
.cap{color:#8a94a6;font-size:14px;margin-top:5px}
.green{color:#8ee6b0}.amber{color:#f0c07a}.white{color:#eaf0f7}.red{color:#f2726f}
.btnrow{display:flex;gap:12px;margin-top:24px}
button{flex:1;padding:14px;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;
border:1.5px solid;background:transparent;transition:.15s;font-family:inherit}
#btnStart{color:#8ee6b0;border-color:rgba(142,230,176,.6)}
#btnStart:hover{background:rgba(142,230,176,.12)}
#btnStop{color:#f0b56a;border-color:rgba(240,181,106,.6)}
#btnStop:hover{background:rgba(240,181,106,.12)}
button:disabled{opacity:.4;cursor:default}
.testbox{display:flex;gap:10px;margin-top:8px}
.testbox input{flex:1;padding:11px 13px;border-radius:12px;border:1px solid rgba(255,255,255,.12);
background:rgba(10,14,20,.6);color:#eaf0f7;font-size:15px;font-family:inherit}
.testbox input:focus{outline:1px solid rgba(142,230,176,.5)}
#btnTest{padding:11px 18px;border-radius:12px;color:#9fd0ff;border:1.5px solid rgba(159,208,255,.5);flex:0 0 auto}
#btnTest:hover{background:rgba(159,208,255,.1)}
.hint{color:#6b7688;font-size:12px;margin-top:10px;line-height:1.6}
</style></head><body><div class="wrap">
<div class="card">
<h1>祀 · 语音服务</h1><div class="sub">gsv.cpp · v5turbo · 本地推理</div>
<div class="state"><span id="dot" class="dot" style="color:#6b7688;background:#6b7688"></span><span id="stateText">读取中…</span></div>
<div class="row"><div class="lbl"><span class="dot" style="color:#7fd6a4;background:#7fd6a4;width:7px;height:7px;box-shadow:none"></span>当前音色</div><div id="voice" class="big white" style="font-size:34px">—</div><div class="cap" id="sr">采样率 —</div></div>
<div class="row"><div class="lbl"><span class="dot" style="color:#7fd6a4;background:#7fd6a4;width:7px;height:7px;box-shadow:none"></span>显存占用</div><div id="vram" class="big green">—</div><div class="cap" id="gpu2">—</div></div>
<div class="row"><div class="lbl"><span class="dot" style="color:#f0b56a;background:#f0b56a;width:7px;height:7px;box-shadow:none"></span>最近一次合成</div><div id="last" class="big amber" style="font-size:34px">—</div><div class="cap" id="lastCap">尚未测试</div></div>
<div class="btnrow"><button id="btnStart" onclick="act('start')">启动服务</button><button id="btnStop" onclick="act('stop')">停止服务</button></div>
<div class="hint">启动约 60~80 秒（加载模型）。运行状态每 1.5 秒自动刷新。</div>
</div>
<div class="card">
<h1 style="font-size:20px">试听测试</h1><div class="sub">点一次会占用一次推理，用于确认服务正常</div>
<div class="testbox"><input id="ttext" value="你好，我是祀，服务运行正常。"><button id="btnTest" onclick="test1()">合成</button></div>
<div id="testOut" class="cap" style="margin-top:12px"></div>
</div>
</div><script>
const $=id=>document.getElementById(id);
const COL={running:'#7fd6a4',loading:'#f0b56a',stopped:'#6b7688',error:'#f2726f'};
const TXT={running:'运行中',loading:'加载中…',stopped:'已停止',error:'故障'};
async function refresh(){try{const r=await fetch('/api/status');const j=await r.json();
$('dot').style.background=COL[j.state]||'#6b7688';$('dot').style.color=COL[j.state]||'#6b7688';
$('stateText').textContent=TXT[j.state]||j.state;
$('voice').textContent=j.voice||'—';$('sr').textContent='采样率 '+(j.sample_rate||'—')+' Hz · 语速 '+(j.speed_factor||'—');
if(j.gpu){$('vram').textContent=j.gpu.used_mb+' / '+j.gpu.total_mb+' MB';$('gpu2').textContent='GPU '+(j.gpu.util_pct!=null?j.gpu.util_pct+'%':'—')+' · '+(j.gpu.temp_c!=null?j.gpu.temp_c+'°C':'—')+' · 队列 '+j.queue;}
if(j.last_test){$('last').textContent=j.last_test.total_ms+' ms';$('lastCap').textContent=j.last_test.chars+' 字 · '+(j.last_test.audio_sec)+' s 音频 · 首字 '+j.last_test.first_ms+' ms';}
$('btnStart').disabled=(j.state==='running'||j.state==='loading');$('btnStop').disabled=(j.state==='stopped');
}catch(e){$('stateText').textContent='无法连接监控后端';}}
async function act(what){const b=what==='start'?$('btnStart'):$('btnStop');b.disabled=true;b.textContent='请稍候…';
try{await fetch('/api/'+what,{method:'POST'});}catch(e){}setTimeout(()=>{b.textContent=what==='start'?'启动服务':'停止服务';refresh();},1200);}
async function test1(){const t=$('ttext').value.trim();if(!t)return;$('btnTest').disabled=true;$('testOut').textContent='合成中…';
try{const r=await fetch('/api/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t})});const j=await r.json();
if(j.error){$('testOut').textContent='失败：'+j.error;}else{$('testOut').textContent='✓ '+j.chars+' 字 · 音频 '+j.audio_sec+' s · 首字 '+j.first_ms+' ms · 总耗时 '+j.total_ms+' ms';}
}catch(e){$('testOut').textContent='失败：'+e;}finally{$('btnTest').disabled=false;refresh();}}
refresh();setInterval(refresh,1500);
</script></body></html>'''


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == '/':
            return self._send(200, PAGE, 'text/html; charset=utf-8')
        if p == '/api/status':
            return self._send(200, json.dumps(status(), ensure_ascii=False))
        return self._send(404, json.dumps({'error': 'not found'}))

    def do_POST(self):
        p = urlparse(self.path).path
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b''
        if p == '/api/start':
            threading.Thread(target=do_start, daemon=True).start()
            return self._send(200, json.dumps({'ok': True, 'accepted': True}))
        if p == '/api/stop':
            threading.Thread(target=do_stop, daemon=True).start()
            return self._send(200, json.dumps({'ok': True, 'accepted': True}))
        if p == '/api/test':
            try:
                body = json.loads(raw.decode('utf-8')) if raw else {}
                text = (body.get('text') or '').strip()
                if not text:
                    return self._send(400, json.dumps({'error': 'missing text'}))
                return self._send(200, json.dumps(do_test(text), ensure_ascii=False))
            except Exception as e:
                return self._send(500, json.dumps({'error': str(e)}))
        return self._send(404, json.dumps({'error': 'not found'}))


def _ensure_paths():
    """分发友好：把 config/manifest 里旧的 <PROJECT_ROOT> 绝对前缀，纠正成当前实际 ROOT。"""
    old_prefixes = ['<PROJECT_ROOT>', '<PROJECT_ROOT>']
    root_fwd = ROOT.replace('\\', '/')
    def fix(obj):
        if isinstance(obj, str):
            # 已经指向当前 ROOT 的，原样返回（幂等，避免重复加 app）
            if obj.startswith(ROOT) or obj.startswith(root_fwd):
                return obj
            for op in old_prefixes:
                if obj.startswith(op):
                    return ROOT + obj[len(op):]
        return obj
    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return fix(o)
    changed = False
    # 1) services/config.json
    try:
        with open(CONFIG, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        ncfg = walk(cfg)
        if ncfg != cfg:
            with open(CONFIG, 'w', encoding='utf-8') as f:
                json.dump(ncfg, f, ensure_ascii=False, indent=2)
            changed = True
    except Exception:
        pass
    # 2) voices/*/manifest.json
    vroot = os.path.join(ROOT, 'models', 'voices')
    try:
        for name in os.listdir(vroot):
            mp = os.path.join(vroot, name, 'manifest.json')
            if not os.path.isfile(mp):
                continue
            try:
                with open(mp, 'r', encoding='utf-8') as f:
                    man = json.load(f)
                nman = walk(man)
                if nman != man:
                    with open(mp, 'w', encoding='utf-8') as f:
                        json.dump(nman, f, ensure_ascii=False, indent=2)
                    changed = True
            except Exception:
                pass
    except Exception:
        pass
    return changed


def main():
    try:
        _ensure_paths()
    except Exception:
        pass
    url = 'http://localhost:%d' % MONITOR_PORT
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', MONITOR_PORT), H)
    except OSError:
        # 端口已被占用：说明监控已在运行，直接打开浏览器即可
        if os.environ.get('GSV_NO_BROWSER') == '1':
            raise SystemExit('Desktop workbench port is occupied; refusing browser fallback.')
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
        return

    def _open_later():
        time.sleep(0.8)
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    if os.environ.get('GSV_NO_BROWSER') != '1':
        threading.Thread(target=_open_later, daemon=True).start()
    srv.serve_forever()


if __name__ == '__main__':
    sys.path.insert(0, os.path.join(ROOT, 'desktop'))
    from bootstrap import prepare
    prepare()
    import workbench
    workbench.install(sys.modules[__name__])
    main()
