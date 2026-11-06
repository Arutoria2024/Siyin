# -*- coding: utf-8 -*-
"""Service B: LAN HTTP gateway for gsv.cpp TTS (default 0.0.0.0:9881).

Thin shell over core.py. Everything about segmentation, streaming and
resampling lives in core; this file only does HTTP, auth and rate limiting.

Endpoints
    GET  /v1/health            engine status, voice, VRAM
    GET  /v1/voices            configured voices
    POST /v1/tts/stream        chunked streaming PCM / WAV
    POST /v1/tts               whole WAV (fallback for dumb clients)

Auth: header  Authorization: Bearer <token>
      header  X-Auth-Token: <token>
      query   ?token=<token>
"""

import argparse
import json
import os
import re
import socket
import struct
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                 # <PROJECT_ROOT>\services
sys.path.insert(0, ROOT)
import core


CONFIG = {}
SYNTH = None
LOG = None
LIMITER = None
VRAM_CACHE = {'t': 0.0, 'v': None}
RETRY_AFTER_S = 2
MAX_TEXT_CHARS = 2000
CONTRACT_RE = re.compile(r'^/v1/text-to-speech/([A-Za-z0-9_.\-]+)/stream$')


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False).encode('utf-8')


def vram_info():
    now = time.time()
    if now - VRAM_CACHE['t'] < 2.0:
        return VRAM_CACHE['v']
    info = None
    try:
        import subprocess
        # CREATE_NO_WINDOW is mandatory: without it every poll spawns a console
        # window that flashes on the user's desktop. The monitor page hits
        # /v1/health every 1.5s, so this used to blink ~40 times a minute.
        out = subprocess.check_output(
            ['nvidia-smi',
             '--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu',
             '--format=csv,noheader,nounits'],
            timeout=3, stderr=subprocess.DEVNULL,
            creationflags=0x08000000)
        parts = [p.strip() for p in out.decode('utf-8', 'replace').split(',')]
        info = {'gpu': parts[0], 'vram_used_mb': int(float(parts[1])),
                'vram_total_mb': int(float(parts[2])),
                'gpu_util_pct': int(float(parts[3])),
                'gpu_temp_c': int(float(parts[4]))}
    except Exception:                                  # noqa: BLE001
        info = None
    VRAM_CACHE['t'] = now
    VRAM_CACHE['v'] = info
    return info


class RateLimiter(object):
    """Per-IP concurrent-request cap."""

    def __init__(self, limit):
        self.limit = limit
        self.lock = threading.Lock()
        self.active = {}

    def acquire(self, ip):
        with self.lock:
            n = self.active.get(ip, 0)
            if self.limit > 0 and n >= self.limit:
                return False
            self.active[ip] = n + 1
            return True

    def release(self, ip):
        with self.lock:
            n = self.active.get(ip, 0) - 1
            if n <= 0:
                self.active.pop(ip, None)
            else:
                self.active[ip] = n

    def snapshot(self):
        with self.lock:
            return dict(self.active)


def check_token(handler, query):
    expected = CONFIG.get('gateway', {}).get('token') or ''
    if not expected:
        return True                                    # auth disabled on purpose
    got = ''
    auth = handler.headers.get('Authorization') or ''
    if auth.lower().startswith('bearer '):
        got = auth[7:].strip()
    if not got:
        got = (handler.headers.get('X-Auth-Token') or '').strip()
    if not got:
        got = (query.get('token') or [''])[0].strip()
    if not got:
        return False
    import hmac
    return hmac.compare_digest(got.encode('utf-8'), expected.encode('utf-8'))


# ---------------------------------------------------------------------------
# request handler
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'gsv-tts-gateway/1.0'

    # -- plumbing ----------------------------------------------------------
    def setup(self):
        BaseHTTPRequestHandler.setup(self)
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    def log_message(self, fmt, *args):
        if LOG:
            LOG.info('%s %s', self.client_address[0], fmt % args)

    def client_ip(self):
        fwd = self.headers.get('X-Forwarded-For')
        if fwd:
            return fwd.split(',')[0].strip()
        return self.client_address[0]

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers',
                         'Authorization, X-Auth-Token, Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')

    def send_json(self, code, obj, headers=None):
        body = json_bytes(obj)
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_error_json(self, code, message, headers=None):
        self.send_json(code, {'error': message, 'code': code}, headers)

    def send_too_many(self, ip):
        """429 must carry Retry-After so clients can back off politely."""
        return self.send_error_json(
            429,
            'too many concurrent requests from %s (limit %d)'
            % (ip, LIMITER.limit),
            {'Retry-After': str(RETRY_AFTER_S)})

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    # -- routing -----------------------------------------------------------
    def do_GET(self):
        path, _, qs = self.path.partition('?')
        query = {}
        if qs:
            from urllib.parse import parse_qs
            query = parse_qs(qs)
        try:
            if path in ('/v1/health', '/health'):
                return self.handle_health()
            if path == '/':
                return self.send_json(200, {
                    'service': 'gsv-tts-gateway', 'version': '1.1',
                    'endpoints': [
                        'GET  /health',
                        'POST /v1/text-to-speech/{voice_id}/stream',
                        'GET  /v1/voices',
                        'POST /v1/tts/stream   (legacy)',
                        'POST /v1/tts          (legacy whole wav)']})
            if path in ('/v1/voices', '/voices'):
                return self.handle_voices()
            return self.send_error_json(404, 'not found: %s' % path)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        path, _, qs = self.path.partition('?')
        query = {}
        if qs:
            from urllib.parse import parse_qs
            query = parse_qs(qs)
        try:
            if not check_token(self, query):
                LOG.warning('auth rejected from %s', self.client_ip())
                return self.send_error_json(401, 'invalid or missing token')
            # ---- standard contract (mobile voice pipeline) ----------------
            m = CONTRACT_RE.match(path)
            if m:
                return self.handle_contract_stream(m.group(1), query)
            # ---- legacy endpoints, kept for existing clients ---------------
            if path == '/v1/tts/stream':
                return self.handle_stream(query)
            if path == '/v1/tts':
                return self.handle_whole(query)
            return self.send_error_json(404, 'not found: %s' % path)
        except (BrokenPipeError, ConnectionResetError):
            LOG.info('client %s disconnected mid-response', self.client_ip())

    # -- body parsing ------------------------------------------------------
    def read_request(self):
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        ctype = (self.headers.get('Content-Type') or '').lower()
        if 'application/json' in ctype or raw.strip().startswith(b'{'):
            return json.loads(raw.decode('utf-8')) if raw else {}
        # form encoded fallback
        from urllib.parse import parse_qs
        flat = {}
        for k, v in parse_qs(raw.decode('utf-8', 'replace')).items():
            flat[k] = v[0]
        return flat

    def params(self, query, body):
        """Merge query-string and body, body wins."""
        out = {}
        for k, v in query.items():
            out[k] = v[0]
        for k, v in (body or {}).items():
            out[k] = v
        return out

    @staticmethod
    def pick(params, names, default=None):
        for n in names:
            if n in params and params[n] not in (None, ''):
                return params[n]
        return default

    @staticmethod
    def default_speed(voice=None):
        """Voice-configured speed_factor, then tts_defaults, then 1.0.

        Single source of truth for "client did not send speed". Used by
        /v1/tts, /v1/tts/stream and the contract stream endpoint alike, so a
        client that omits `speed` always hears the tuned voice, never a
        hard-coded 1.0.
        """
        name = voice or CONFIG.get('default_voice') or 'si'
        meta = (CONFIG.get('voices') or {}).get(name) or {}
        val = meta.get('speed_factor')
        if val is None:
            val = (CONFIG.get('tts_defaults') or {}).get('speed_factor')
        try:
            out = float(val)
        except (TypeError, ValueError):
            return 1.0
        return out

    # -- endpoints ---------------------------------------------------------
    def handle_health(self):
        try:
            engine = core.Engine(CONFIG).health()
        except Exception as exc:                       # noqa: BLE001
            engine = {'ok': False, 'error': str(exc)}
        voice = engine.get('voice') or CONFIG.get('default_voice')
        meta = (CONFIG.get('voices') or {}).get(voice) or {}
        body = {
            # ---- contract fields -----------------------------------------
            'ok': bool(engine.get('ok')),
            'model': voice,
            'voice': voice,
            'sample_rate': int(meta.get('sample_rate')
                               or CONFIG.get('audio', {}).get('sample_rate', 24000)),
            'channels': 1,
            'format': 'pcm_s16le',
            'sample_steps': int(meta.get('sample_steps', 4)),
            'gpu': vram_info(),
            # ---- existing fields, unchanged ------------------------------
            'service': 'gsv-tts-gateway',
            'engine': engine,
            'default_voice': CONFIG.get('default_voice'),
            'voices': sorted((CONFIG.get('voices') or {}).keys()),
            'stats': SYNTH.stats.snapshot(),
            'active_requests': LIMITER.snapshot(),
            'limits': {'concurrent_per_ip':
                       CONFIG.get('gateway', {}).get('max_concurrent_per_ip', 2)},
            'time': int(time.time()),
        }
        self.send_json(200, body)

    def handle_voices(self):
        voices = []
        for name, meta in (CONFIG.get('voices') or {}).items():
            voices.append({
                'name': name,
                'text_lang': meta.get('text_lang', 'zh'),
                'prompt_lang': meta.get('prompt_lang', 'zh'),
                'sample_steps': meta.get('sample_steps', 4),
                'has_reference': bool(meta.get('ref_audio_path')),
            })
        try:
            models = core.Engine(CONFIG).models()
            current = models.get('current')
        except Exception:                              # noqa: BLE001
            current = None
        self.send_json(200, {'current': current,
                             'default': CONFIG.get('default_voice'),
                             'voices': voices})

    def _resolve(self, params):
        text = (self.pick(params, ['text', 'input']) or '')
        text = str(text).strip()
        if not text:
            raise ValueError('missing "text"')
        voice = self.pick(params, ['voice'])
        # Speed default MUST come from the voice's own config (si = 0.88), not
        # from a hard-coded 1.0. A 1.0 default made every "no speed" request
        # ~14% faster than the tuned reference, which clipped sentence-final
        # vowels ("少半个字") and sounded harsh. See docs/API.md.
        speed = self.pick(params, ['speed', 'speed_factor'], None)
        if speed is None:
            speed = self.default_speed(voice)
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            speed = self.default_speed(voice)
        sr = self.pick(params, ['sample_rate', 'sr'], None)
        sr = int(sr) if sr else int(CONFIG.get('audio', {}).get('sample_rate', 24000))
        if sr not in (24000, 48000):
            raise ValueError('sample_rate must be 24000 or 48000')
        fmt = str(self.pick(params, ['format'], 'wav')).lower()
        if fmt not in ('wav', 'pcm', 'l16'):
            raise ValueError('format must be wav or pcm')
        return text, voice, speed, sr, ('wav' if fmt == 'wav' else 'pcm')

    def _start_streaming(self, ctype):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Transfer-Encoding', 'chunked')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self._cors()
        self.end_headers()

    def _write_chunk(self, data):
        if not data:
            return
        self.wfile.write(b'%x\r\n' % len(data))
        self.wfile.write(data)
        self.wfile.write(b'\r\n')
        self.wfile.flush()

    def _end_chunked(self):
        self.wfile.write(b'0\r\n\r\n')
        self.wfile.flush()

    # =====================================================================
    #  standard contract: POST /v1/text-to-speech/<voice_id>/stream
    #  bare PCM (no WAV header), chunked, first byte as early as possible.
    # =====================================================================
    def handle_contract_stream(self, voice_id, query):
        ip = self.client_ip()
        if not LIMITER.acquire(ip):
            return self.send_too_many(ip)
        started = False
        try:
            body = self.read_request()
            if not isinstance(body, dict):
                return self.send_error_json(400, 'request body must be a JSON object')
            params = self.params(query, body)

            # -- text -------------------------------------------------------
            text = params.get('text')
            if text is None:
                text = params.get('input')
            text = str(text or '').strip()
            if not text:
                return self.send_error_json(400, 'missing required field "text"')
            if len(text) > MAX_TEXT_CHARS:
                return self.send_error_json(
                    400, 'text too long: %d chars (limit %d)'
                         % (len(text), MAX_TEXT_CHARS))

            # -- voice ------------------------------------------------------
            voices = CONFIG.get('voices') or {}
            if voice_id not in voices:
                return self.send_error_json(
                    404, 'unknown voice_id: %s (available: %s)'
                         % (voice_id, ', '.join(sorted(voices)) or 'none'))
            voice = voice_id

            # -- output_format / sample_rate --------------------------------
            fmt = str(params.get('output_format') or 'pcm').strip().lower()
            if fmt not in ('pcm', 'pcm_s16le', 's16le', 'wav'):
                return self.send_error_json(
                    400, 'output_format must be pcm or wav, got %r' % fmt)
            sr_raw = params.get('sample_rate', 24000)
            if sr_raw in (None, ''):
                sr_raw = 24000
            try:
                sr = int(sr_raw)
            except (TypeError, ValueError):
                return self.send_error_json(
                    400, 'sample_rate must be an integer (24000 or 48000)')
            if sr not in (24000, 48000):
                return self.send_error_json(
                    400, 'sample_rate must be 24000 or 48000, got %d' % sr)

            # -- optional knobs, unknown ones ignored on purpose -------------
            speed = params.get('speed', params.get('speed_factor'))
            if speed is None:
                speed = self.default_speed(voice)
            try:
                speed = float(speed)
            except (TypeError, ValueError):
                return self.send_error_json(400, 'speed must be a number')
            if not (0.1 <= speed <= 4.0):
                return self.send_error_json(400, 'speed must be within 0.1..4.0')

            steps = params.get('sample_steps')
            if steps is not None:
                try:
                    steps = int(steps)
                except (TypeError, ValueError):
                    steps = None
                if steps is not None and steps <= 0:
                    steps = None          # never let a 0-step DiT run

            # -- headers: everything the client needs to play raw PCM -------
            bare = fmt != 'wav'
            ctype = 'audio/pcm' if bare else 'audio/wav'
            t0 = time.perf_counter()
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Transfer-Encoding', 'chunked')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Accel-Buffering', 'no')
            self.send_header('X-Sample-Rate', str(sr))
            self.send_header('X-Channels', '1')
            self.send_header('X-Format', 'pcm_s16le')
            self.send_header('X-Voice', voice)
            self._cors()
            self.end_headers()
            started = True
            if not bare:
                self._write_chunk(core.wav_header(sr, data_bytes=0xFFFFFFFF))

            first = None
            nbytes = 0
            for chunk in SYNTH.stream(text, voice, speed, sr, sample_steps=steps):
                if first is None:
                    first = time.perf_counter() - t0
                nbytes += len(chunk)
                self._write_chunk(chunk)
            if nbytes == 0:
                # A silent 200 is worse than an honest failure: abort hard so
                # the client sees a truncated stream, never a fake success.
                LOG.error('contract stream produced 0 bytes for %s', ip)
                self.close_connection = True
                return
            self._end_chunked()
            LOG.info('contract stream ip=%s voice=%s chars=%d sr=%d bytes=%d '
                     'first=%.3f total=%.3f',
                     ip, voice, len(text), sr, nbytes, first or -1,
                     time.perf_counter() - t0)
        except core.TTSError as exc:
            LOG.error('contract stream failed for %s: %s', ip, exc)
            # Never write JSON into the PCM stream: just drop the connection.
            self.close_connection = True
            return
        except (BrokenPipeError, ConnectionResetError):
            LOG.info('client %s disconnected mid-contract-stream', ip)
            self.close_connection = True
        except Exception as exc:                           # noqa: BLE001
            LOG.error('contract stream error: %s\n%s', exc, traceback.format_exc())
            if not started:
                try:
                    return self.send_error_json(500, 'internal error: %s' % exc)
                except Exception:                          # noqa: BLE001
                    pass
            self.close_connection = True
        finally:
            LIMITER.release(ip)

    def handle_stream(self, query):
        ip = self.client_ip()
        if not LIMITER.acquire(ip):
            return self.send_too_many(ip)
        try:
            body = self.read_request()
            params = self.params(query, body)
            try:
                text, voice, speed, sr, fmt = self._resolve(params)
            except ValueError as exc:
                return self.send_error_json(400, str(exc))
            t0 = time.perf_counter()
            first = None
            nbytes = 0
            ctype = 'audio/wav' if fmt == 'wav' else 'audio/L16; rate=%d; channels=1' % sr
            self._start_streaming(ctype)
            if fmt == 'wav':
                self._write_chunk(core.wav_header(sr, data_bytes=0xFFFFFFFF))
            try:
                for chunk in SYNTH.stream(text, voice, speed, sr):
                    if first is None:
                        first = time.perf_counter() - t0
                    nbytes += len(chunk)
                    self._write_chunk(chunk)
            except core.TTSError as exc:
                LOG.error('synthesis failed for %s: %s', ip, exc)
                # headers are already out; the only honest signal left is to
                # stop the body. Clients see a truncated stream.
                return
            self._end_chunked()
            LOG.info('stream ip=%s chars=%d sr=%d bytes=%d first=%.3f total=%.3f',
                     ip, len(text), sr, nbytes, first or -1,
                     time.perf_counter() - t0)
        finally:
            LIMITER.release(ip)

    def handle_whole(self, query):
        ip = self.client_ip()
        if not LIMITER.acquire(ip):
            return self.send_too_many(ip)
        try:
            body = self.read_request()
            params = self.params(query, body)
            try:
                text, voice, speed, sr, _fmt = self._resolve(params)
            except ValueError as exc:
                return self.send_error_json(400, str(exc))
            t0 = time.perf_counter()
            pcm = SYNTH.synthesize(text, voice, speed, sr)
            data = core.wav_header(sr, data_bytes=len(pcm)) + pcm
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Audio-Seconds', '%.2f' % (len(pcm) / 2.0 / sr))
            self._cors()
            self.end_headers()
            self.wfile.write(data)
            LOG.info('whole ip=%s chars=%d sr=%d bytes=%d total=%.3f',
                     ip, len(text), sr, len(data), time.perf_counter() - t0)
        finally:
            LIMITER.release(ip)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def main():
    global CONFIG, SYNTH, LOG, LIMITER
    ap = argparse.ArgumentParser(description='gsv-tts LAN gateway')
    ap.add_argument('--config', default=os.path.join(ROOT, 'config.json'))
    ap.add_argument('--host', default=None)
    ap.add_argument('--port', type=int, default=None)
    args = ap.parse_args()

    CONFIG = core.load_config(args.config)
    gw = CONFIG.setdefault('gateway', {})
    host = args.host or gw.get('host', '0.0.0.0')
    port = args.port or int(gw.get('port', 9881))
    token = gw.get('token') or os.environ.get('GSV_TTS_TOKEN') or ''

    LOG = core.setup_logging(os.path.join(HERE, 'logs'), 'gateway')
    LOG.info('config=%s host=%s port=%d auth=%s',
             args.config, host, port, 'on' if token else 'OFF')

    if not token:
        LOG.warning('no token configured: gateway is OPEN to the network')

    core.check_port_free(host, port)
    engine = core.check_engine(CONFIG, wait_s=float(gw.get('engine_wait_s', 30)))
    LOG.info('engine ok: voice=%s sidecar=%s', engine.get('voice'), engine.get('sidecar'))

    SYNTH = core.Synth(CONFIG)
    LIMITER = RateLimiter(int(gw.get('max_concurrent_per_ip', 2)))

    if CONFIG.get('audio', {}).get('warmup', True):
        try:
            t0 = time.perf_counter()
            SYNTH.synthesize(CONFIG.get('audio', {}).get('warmup_text', '你好。'),
                             out_sr=24000)
            LOG.info('warmup done in %.2fs', time.perf_counter() - t0)
        except Exception as exc:                       # noqa: BLE001
            LOG.warning('warmup failed: %s', exc)

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    LOG.info('listening on http://%s:%d  (LAN: http://<this-pc-ip>:%d)', host, port, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOG.info('stopping on Ctrl-C')
    finally:
        httpd.server_close()


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception:                                  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
