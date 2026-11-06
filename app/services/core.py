# -*- coding: utf-8 -*-
"""Shared TTS core for every gsv.cpp access shell.

One implementation of:
    text -> segments -> streaming /tts requests -> WAV/PCM parse
         -> optional resample (48k -> 24k) -> PCM chunks out

Shells (gateway / local_http / tcp / pipe / mcp) only move bytes around;
they must not re-implement segmentation or streaming.

Engine facts (measured on <PROJECT_ROOT>, RTX 2060):
  * POST /tts with stream=true -> chunked audio/wav, 44-byte header first,
    then s16le / 48k / mono PCM.
  * sample_steps MUST be explicit on the streaming path, else the DiT fails
    and the body is empty even though the status is 200.
  * text_split_method=cut0 disables engine-side splitting so our own
    segmentation decides the boundaries.
"""

import collections
import http.client
import json
import math
import os
import re
import struct
import threading
import time

SRC_RATE = 48000
SRC_CHANNELS = 1
SRC_BITS = 16

try:
    import numpy as np
except ImportError:                                  # pragma: no cover
    np = None

SENT_END = set(u'\u3002\uff01\uff1f\uff1b!?;\n')
SOFT = set(u'\uff0c,\u3001 ')


# ---------------------------------------------------------------------------
# segmentation (parameters fixed by the project tuning manual)
# ---------------------------------------------------------------------------
class Segmenter(object):
    def __init__(self, first_min=20, first_max=40, chunk_min=36, chunk_max=48,
                 tail_slack=8):
        self.first_min = first_min
        self.first_max = first_max
        self.chunk_min = chunk_min
        self.chunk_max = chunk_max
        self.tail_slack = tail_slack

    def _find_cut(self, text, min_len, max_len):
        cut = 0
        for i, ch in enumerate(text[:max_len]):
            if ch in SENT_END and (i + 1) >= min_len:
                cut = i + 1
        if cut:
            return cut
        for i in range(min(max_len, len(text)) - 1, min_len - 2, -1):
            if i < len(text) and text[i] in SOFT:
                return i + 1
        return max_len if len(text) >= max_len else 0

    def split(self, text):
        text = (text or u'').strip()
        if not text:
            return []
        parts = []
        rest = text
        first = True
        while rest:
            min_len = self.first_min if first else self.chunk_min
            max_len = self.first_max if first else self.chunk_max
            if len(rest) <= max_len + self.tail_slack:
                parts.append(rest)
                break
            if len(rest) < min_len:
                parts.append(rest)
                break
            cut = self._find_cut(rest, min_len, max_len)
            if cut and cut<len(rest) and rest[cut-1].isascii() and rest[cut-1].isalnum() and rest[cut].isascii() and rest[cut].isalnum():
                # Do not bisect English words when the ordinary punctuation
                # splitter reaches its character cap.
                boundary=list(re.finditer(r'\s+|(?<=[\u3400-\u9fff])(?=[A-Za-z])',rest[:cut]))
                if boundary and boundary[-1].end()>0:cut=boundary[-1].end()
            if not cut:
                parts.append(rest)
                break
            parts.append(rest[:cut])
            rest = rest[cut:]
            first = False
        return [p for p in (x.strip() for x in parts) if p]


# ---------------------------------------------------------------------------
# WAV header
# ---------------------------------------------------------------------------
def parse_wav_header(buf):
    """Return (channels, rate, bits, data_offset)."""
    if len(buf) < 12 or buf[0:4] != b'RIFF' or buf[8:12] != b'WAVE':
        raise ValueError('not a RIFF/WAVE payload: %r' % buf[:12])
    pos = 12
    channels = rate = bits = None
    while pos + 8 <= len(buf):
        cid = buf[pos:pos + 4]
        size = struct.unpack('<I', buf[pos + 4:pos + 8])[0]
        if cid == b'fmt ':
            body = buf[pos + 8:pos + 8 + 16]
            if len(body) < 16:
                raise ValueError('short fmt chunk')
            _fmt, channels, rate = struct.unpack('<HHI', body[0:8])
            bits = struct.unpack('<H', body[14:16])[0]
        elif cid == b'data':
            if channels is None:
                raise ValueError('data chunk before fmt chunk')
            return channels, rate, bits, pos + 8
        pos += 8 + size
    raise ValueError('no data chunk in header')


def wav_header(sample_rate, channels=1, bits=16, data_bytes=0):
    byte_rate = sample_rate * channels * bits // 8
    block = channels * bits // 8
    return (b'RIFF' + struct.pack('<I', (36 + data_bytes) & 0xFFFFFFFF) + b'WAVE'
            + b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, sample_rate,
                                    byte_rate, block, bits)
            + b'data' + struct.pack('<I', data_bytes & 0xFFFFFFFF))


STREAM_WAV_HEADER = wav_header(SRC_RATE, data_bytes=0xFFFFFFFF)


# ---------------------------------------------------------------------------
# resampler (phase kept across arbitrary packet boundaries)
# ---------------------------------------------------------------------------
class Resampler(object):
    def __init__(self, src_rate=SRC_RATE, out_rate=24000):
        self.ratio = float(src_rate) / float(out_rate)
        self.pos = 0.0
        self.frames = 0
        self.prev = 0.0

    def convert(self, samples, final=False):
        if np is None:
            raise RuntimeError('numpy is required by core.Resampler')
        samples = np.asarray(samples, dtype=np.float64)
        if samples.size == 0:
            return np.zeros(0, dtype=np.float64)
        if self.frames:
            data = np.empty(samples.size + 1, dtype=np.float64)
            data[0] = self.prev
            data[1:] = samples
            base = self.frames - 1
        else:
            data = samples
            base = 0
        last = base + data.size - 1
        limit = last + 1 if final else last
        if self.pos >= limit:
            self.frames += samples.size
            self.prev = float(samples[-1])
            return np.zeros(0, dtype=np.float64)
        count = int(math.floor((limit - self.pos) / self.ratio)) + 1
        positions = self.pos + self.ratio * np.arange(count, dtype=np.float64)
        positions = positions[positions < limit]
        if positions.size == 0:
            self.frames += samples.size
            self.prev = float(samples[-1])
            return np.zeros(0, dtype=np.float64)
        rel = positions - base
        k = np.floor(rel).astype(np.int64)
        frac = rel - k
        np.clip(k, 0, data.size - 1, out=k)
        k1 = np.clip(k + 1, 0, data.size - 1)
        out = data[k] * (1.0 - frac) + data[k1] * frac
        self.pos = float(positions[-1]) + self.ratio
        self.frames += samples.size
        self.prev = float(samples[-1])
        return out


def _to_s16(frames):
    if np is None:
        raise RuntimeError('numpy is required by core')
    if frames.size == 0:
        return b''
    v = np.clip(frames * 32768.0, -32768.0, 32767.0).astype('<i2')
    return v.tobytes()


# ---------------------------------------------------------------------------
# engine client
# ---------------------------------------------------------------------------
class TTSError(Exception):
    pass

TEXT_LANGUAGES = ('zh', 'en', 'auto', 'auto_yue', 'ja', 'ko', 'yue', 'all_zh', 'all_ja', 'all_ko', 'all_yue')

def text_language(value):
    if value is not None and value not in TEXT_LANGUAGES:
        raise ValueError('unsupported text_lang')
    return value


class Engine(object):
    def __init__(self, cfg):
        eng = cfg.get('engine', {})
        self.host = eng.get('host', '127.0.0.1')
        self.port = int(eng.get('port', 9880))
        self.timeout = float(eng.get('timeout', 120))
        self.seed = int(cfg.get('seed', 20261014))
        self.default_voice = cfg.get('default_voice', 'si')
        self.voices = cfg.get('voices', {})
        self.cfg = cfg

    # -- voice metadata ----------------------------------------------------
    def voice_params(self, voice=None):
        name = voice or self.default_voice
        meta = dict(self.voices.get(name) or {})
        if not meta:
            raise TTSError('unknown voice: %s' % name)
        if not meta.get('ref_audio_path'):
            base = self.voices.get(self.default_voice) or {}
            meta['ref_audio_path'] = base.get('ref_audio_path')
            meta.setdefault('prompt_text', base.get('prompt_text'))
        if not meta.get('ref_audio_path') or not meta.get('prompt_text'):
            raise TTSError('voice %s has no reference audio configured' % name)
        return name, meta

    def payload(self, text, voice=None, speed=1.0, stream=True, sample_steps=None, text_lang=None):
        name, meta = self.voice_params(voice)
        switch_ok = bool(self.cfg.get('engine', {}).get('allow_voice_switch', False))
        # sample_steps must never be 0: a 0-step DiT answers HTTP 200 with an
        # empty body, which looks like a silent success. Clamp to >= 1, default 4.
        steps = sample_steps if sample_steps is not None else meta.get('sample_steps', 4)
        try:
            steps = int(steps)
        except (TypeError, ValueError):
            steps = 4
        if steps <= 0:
            steps = 4
        body = {
            'text': text,
            'text_lang': text_language(text_lang) or meta.get('text_lang', 'zh'),
            'ref_audio_path': meta['ref_audio_path'],
            'prompt_text': meta['prompt_text'],
            'prompt_lang': meta.get('prompt_lang', 'zh'),
            'stream': bool(stream),
            'sample_steps': steps,
            'text_split_method': 'cut0',
            'seed': self.seed,
            # Preserve pre-upgrade attention behavior until optional approximations
            # have been auditioned for the installed voice.
            'dit_window': int(self.cfg.get('engine',{}).get('dit_window',0)),
            'dit_cfg_off_t': float(self.cfg.get('engine',{}).get('dit_cfg_off_t',0)),
        }
        try:
            sf = float(speed)
        except (TypeError, ValueError):
            sf = 1.0
        if abs(sf - 1.0) > 1e-6:
            body['speed_factor'] = max(0.1, min(4.0, sf))
        # Sending "voice" makes the engine reload weights (~40s on this box)
        # whenever it differs from the loaded one, so it stays opt-in.
        if switch_ok and name != self.default_voice:
            body['voice'] = name
        return body

    # -- streaming request -------------------------------------------------
    def iter_pcm(self, text, voice=None, speed=1.0, sample_steps=None, text_lang=None):
        """Yield raw 48k/16bit/mono PCM bytes for one segment."""
        body = json.dumps(self.payload(text, voice, speed, True, sample_steps, text_lang))
        conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            conn.request('POST', '/tts', body, {'content-type': 'application/json'})
            resp = conn.getresponse()
            if resp.status != 200:
                raise TTSError('engine HTTP %d: %s' % (resp.status, resp.read()[:200]))
            header = b''
            offset = None
            while len(header) < 4096:
                d = resp.read1(4096)
                if not d:
                    raise TTSError('engine returned no WAV data chunk')
                header += d
                try:
                    ch, rate, bits, offset = parse_wav_header(header)
                except ValueError:
                    continue
                if ch != SRC_CHANNELS or rate != SRC_RATE or bits != SRC_BITS:
                    raise TTSError('unexpected engine format: %d Hz / %d ch / %d bit'
                                   % (rate, ch, bits))
                break
            if offset is None:
                raise TTSError('engine WAV header never completed')
            carry = header[offset:] if len(header) > offset else b''
            while True:
                if carry:
                    d = carry
                    carry = b''
                else:
                    d = resp.read1(4096)
                if not d:
                    break
                yield d
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def health(self):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            conn.request('GET', '/health')
            resp = conn.getresponse()
            raw = resp.read()
            return json.loads(raw.decode('utf-8'))
        finally:
            conn.close()

    def models(self):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            conn.request('GET', '/models')
            resp = conn.getresponse()
            return json.loads(resp.read().decode('utf-8'))
        finally:
            conn.close()

    def reload_voice(self, voice=None):
        name = voice or self.default_voice
        conn = http.client.HTTPConnection(self.host, self.port, timeout=300)
        try:
            conn.request('GET', '/set_gpt_weights?weights_path=%s' % name)
            resp = conn.getresponse()
            raw = resp.read()
            return json.loads(raw.decode('utf-8')) if raw else {}
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# runtime statistics (shared by every shell, surfaced by /v1/health)
# ---------------------------------------------------------------------------
class Stats(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.requests = 0
        self.segments = 0
        self.runaway = 0
        self.errors = 0
        self.started = time.time()
        self.recent = collections.deque(maxlen=50)

    def bump(self, **kw):
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, getattr(self, k, 0) + v)

    def snapshot(self):
        with self.lock:
            return {
                'requests': self.requests,
                'segments': self.segments,
                'runaway_segments': self.runaway,
                'errors': self.errors,
                'uptime_s': round(time.time() - self.started, 1),
                'recent': list(self.recent),
            }


# ---------------------------------------------------------------------------
# streaming synthesizer
# ---------------------------------------------------------------------------
class _Job(object):
    def __init__(self, index, text, final, cap_bytes):
        self.index = index
        self.text = text
        self.final = final
        self.cap = cap_bytes
        self.cond = threading.Condition()
        self.buf = collections.deque()
        self.queued = 0
        self.done = False
        self.error = None
        self.runaway = False
        self.t0 = None
        self.ttfb = None
        self.ttfp = None
        self.end = None
        self.pcm_bytes = 0
        self.audio_s = 0.0

    def push(self, data):
        if not data:
            return
        with self.cond:
            while self.queued >= self.cap and not self.done:
                self.cond.wait(0.1)
            if self.done:
                return
            self.buf.append(data)
            self.queued += len(data)
            self.cond.notify_all()

    def take(self):
        """Return next chunk, or None when the segment is exhausted."""
        with self.cond:
            while not self.buf and not self.done:
                self.cond.wait(0.1)
            if self.buf:
                data = self.buf.popleft()
                self.queued -= len(data)
                self.cond.notify_all()
                return data
            return None


class Synth(object):
    """text -> ordered PCM chunk stream (real streaming, 2 requests in flight)."""

    def __init__(self, cfg):
        self.cfg = cfg
        seg = cfg.get('segment', {})
        self.segmenter = Segmenter(
            first_min=int(seg.get('first_min', 20)),
            first_max=int(seg.get('first_max', 40)),
            chunk_min=int(seg.get('chunk_min', 36)),
            chunk_max=int(seg.get('chunk_max', 48)),
            tail_slack=int(seg.get('tail_slack', 8)))
        audio = cfg.get('audio', {})
        self.out_sr = int(audio.get('sample_rate', 24000))
        self.pause_ms = int(audio.get('segment_pause_ms', 0))
        self.lead_trim_ms = int(audio.get('lead_trim_ms', 250))
        self.fade_ms = int(audio.get('fade_ms', 20))
        self.seam_fade_ms = int(audio.get('seam_fade_ms', 6))
        self.max_inflight = int(audio.get('max_inflight', 2))
        self.max_queued_bytes = int(audio.get('max_queued_bytes', 48000 * 2 * 6))
        self.chars_per_sec = float(audio.get('chars_per_sec', 5.0))
        self.engine = Engine(cfg)
        self.stats = Stats()

    # -- helpers -----------------------------------------------------------
    def _silence(self, ms, sr):
        n = int(sr * ms / 1000) * 2
        return b'\x00' * n

    def _expected_s(self, text):
        return max(0.6, len(text) / self.chars_per_sec)

    # -- one segment -------------------------------------------------------
    def _run_job(self, job, voice, speed, out_sr, sem, sample_steps=None):
        job.t0 = time.perf_counter()
        resampler = None if out_sr == SRC_RATE else Resampler(SRC_RATE, out_sr)
        fade_in = int(out_sr * self.fade_ms / 1000)
        fade_out = int(out_sr * self.fade_ms / 1000)
        seam = int(out_sr * self.seam_fade_ms / 1000)
        lead_cap = int(out_sr * self.lead_trim_ms / 1000)
        lead_win = max(1, int(out_sr / 100))
        lead_buf = []
        lead_frames = 0
        lead_done = self.lead_trim_ms <= 0
        faded = 0
        carry = b''
        frames_total = 0

        def emit(frames, final=False):
            nonlocal faded, frames_total
            if frames.size == 0:
                return
            n_fade = fade_in if job.index == 0 else seam
            if faded < n_fade:
                take = min(n_fade - faded, frames.size)
                ramp = 0.5 * (1.0 - np.cos(np.pi * (np.arange(take) + faded) / float(n_fade)))
                frames = frames.copy()
                frames[:take] *= ramp
                faded += take
            if final and fade_out:
                take = min(fade_out, frames.size)
                ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(take) / float(take)))
                frames = frames.copy()
                frames[-take:] *= ramp
            frames_total += frames.size
            job.audio_s = frames_total / float(out_sr)
            job.push(_to_s16(frames))

        def flush_lead():
            nonlocal lead_done, lead_buf, lead_frames
            if lead_done:
                return
            buf = np.concatenate(lead_buf) if lead_buf else np.zeros(0)
            lead_buf = []
            lead_frames = 0
            lead_done = True
            emit(buf)

        def feed(frames, final=False):
            nonlocal lead_buf, lead_frames, lead_done
            if frames.size == 0:
                if final:
                    flush_lead()
                return
            if not lead_done:
                lead_buf.append(frames)
                lead_frames += frames.size
                buf = np.concatenate(lead_buf)
                onset = None
                i = 0
                limit = min(buf.size, lead_cap)
                while i + lead_win <= limit:
                    win = buf[i:i + lead_win]
                    rms = float(np.sqrt(np.mean(win * win)))
                    if rms >= 0.02:
                        onset = i
                        break
                    i += lead_win
                if onset is not None:
                    lead_buf = []
                    lead_frames = 0
                    lead_done = True
                    emit(buf[onset:], final)
                    return
                if buf.size >= lead_cap:
                    lead_buf = []
                    lead_frames = 0
                    lead_done = True
                    emit(buf, final)
                    return
                if final:
                    flush_lead()
                return
            emit(frames, final)

        try:
            for raw in self.engine.iter_pcm(job.text, voice, speed, sample_steps, getattr(job,'text_lang',None)):
                if job.ttfb is None:
                    job.ttfb = time.perf_counter()
                if carry:
                    raw = carry + raw
                    carry = b''
                even = len(raw) & ~1
                if even < len(raw):
                    carry = raw[even:]
                if not even:
                    continue
                job.pcm_bytes += even
                samples = np.frombuffer(raw[:even], dtype='<i2').astype(np.float64) / 32768.0
                if job.ttfp is None:
                    job.ttfp = time.perf_counter()
                out = samples if resampler is None else resampler.convert(samples)
                feed(out)
            if carry:
                raise TTSError('odd trailing byte from engine')
            if not job.pcm_bytes:
                raise TTSError('engine returned no audio for this segment; check text language and sidecar dependencies')
            feed(np.zeros(0), final=True)
            job.end = time.perf_counter()
            exp = self._expected_s(job.text)
            if job.audio_s > exp * 2.0 + 1.5:
                self.stats.bump(runaway=1)
                job.error = None
                job.runaway = True
        except Exception as exc:                       # noqa: BLE001
            job.error = '%s: %s' % (type(exc).__name__, exc)
            self.stats.bump(errors=1)
        finally:
            with job.cond:
                job.done = True
                job.cond.notify_all()
            sem.release()

    # -- public API --------------------------------------------------------
    def stream(self, *args, **kwargs):
        from gpu_guard import hold
        queued = time.perf_counter()
        with hold():
            start = time.perf_counter();first = None;size = 0;state = 'completed'
            stream = self._stream_serialized(*args, **kwargs)
            try:
                for chunk in stream:
                    if first is None:first = time.perf_counter()
                    size += len(chunk)
                    yield chunk
            except GeneratorExit:
                state = 'cancelled'
                raise
            except Exception:
                state = 'failed'
                raise
            finally:
                stream.close()
                rate = kwargs.get('out_sr') or (args[3] if len(args)>3 else None) or self.out_sr
                seconds = size / (rate * 2.0)
                elapsed = time.perf_counter()-start
                with self.stats.lock:
                    self.stats.recent.append({'state':state,'queue_ms':round((start-queued)*1000),'first_ms':round((first-start)*1000) if first else None,'total_ms':round(elapsed*1000),'audio_s':round(seconds,3),'rtf':round(elapsed/seconds,3) if seconds else None,'time':time.time()})

    def _stream_serialized(self, text, voice=None, speed=1.0, out_sr=None, pause_ms=None,
               sample_steps=None, text_lang=None):
        """Yield PCM (s16le, mono) chunks in order, as soon as they exist."""
        sr = int(out_sr or self.out_sr)
        segs = self.segmenter.split(text)
        if not segs:
            return
        self.stats.bump(requests=1, segments=len(segs))
        pause = self.pause_ms if pause_ms is None else int(pause_ms)
        jobs = [_Job(i, s, i == len(segs) - 1, self.max_queued_bytes)
                for i, s in enumerate(segs)]
        for job in jobs:job.text_lang=text_language(text_lang)
        sem = threading.Semaphore(self.max_inflight)
        threads = []
        cancelled = threading.Event()
        def schedule():
            for job in jobs:
                sem.acquire()
                if cancelled.is_set():
                    sem.release()
                    break
                t = threading.Thread(target=self._run_job,
                                     args=(job, voice, speed, sr, sem, sample_steps),
                                     daemon=True)
                threads.append(t)
                t.start()
        scheduler = threading.Thread(target=schedule, daemon=True)
        scheduler.start()
        try:
            for job in jobs:
                while True:
                    chunk = job.take()
                    if chunk is None:
                        break
                    yield chunk
                if job.error:
                    raise TTSError(job.error)
                if pause and not job.final:
                    yield self._silence(pause, sr)
        finally:
            cancelled.set()
            for job in jobs:
                with job.cond:
                    job.done = True
                    job.buf.clear()
                    job.queued = 0
                    job.cond.notify_all()
            scheduler.join()
            for t in threads:
                t.join()

    def synthesize(self, text, voice=None, speed=1.0, out_sr=None, pause_ms=None,
                   sample_steps=None, text_lang=None, postprocess=None):
        """Whole utterance as one PCM blob."""
        pcm = b''.join(self.stream(text, voice, speed, out_sr, pause_ms, sample_steps, text_lang))
        from postprocess import polish_pcm
        return polish_pcm(pcm, int(out_sr or self.out_sr), self.cfg, voice or self.engine.default_voice, postprocess)[0]


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# shell helpers (used by every transport shell, kept here so none of them
# grows its own copy)
# ---------------------------------------------------------------------------
def setup_logging(logdir, name):
    """Log to <logdir>/<name>-YYYYMMDD.log and to stderr."""
    import logging
    import logging.handlers
    if not os.path.isdir(logdir):
        os.makedirs(logdir)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    fh = logging.handlers.TimedRotatingFileHandler(
        os.path.join(logdir, '%s.log' % name), when='midnight',
        backupCount=14, encoding='utf-8')
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def check_port_free(host, port):
    """Raise SystemExit with a clear message when the port is already taken."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
    except OSError as exc:
        raise SystemExit(
            '[fatal] %s:%d is already in use (%s).\n'
            '        Stop the process that owns it, or change the port in '
            'services/config.json.' % (host, port, exc))
    finally:
        s.close()


def check_engine(cfg, wait_s=0.0):
    """Verify the engine answers /health; optionally wait for it."""
    eng = Engine(cfg)
    deadline = time.time() + wait_s
    last = None
    while True:
        try:
            h = eng.health()
            if h.get('ok'):
                return h
            last = h
        except Exception as exc:                       # noqa: BLE001
            last = exc
        if time.time() >= deadline:
            raise SystemExit(
                '[fatal] gsv engine at %s:%d is not healthy: %s\n'
                '        Start it first: <PROJECT_ROOT>\\start.bat'
                % (eng.host, eng.port, last))
        time.sleep(1.0)
