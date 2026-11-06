# -*- coding: utf-8 -*-
"""gsv-tts MCP server (stdio JSON-RPC 2.0, protocol 2024-11-05).

Zero-dependency: implements the MCP wire protocol by hand so it never needs
the `mcp` pip package (which may not be installed in the embedded python).

It is a *control plane only*: every tool calls the local gsv-tts engine
(:9880) or gateway (:9881) over HTTP. It never loads a model itself, so it
stays cheap and can be pulled up on demand by an MCP client.

Run (stdio):
    <PROJECT_ROOT>\\python\\python.exe <PROJECT_ROOT>\\services\\mcp\\mcp_server.py
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import http.client
import wave

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "gsv-tts"
SERVER_VERSION = "1.0.0"

HERE = os.path.dirname(os.path.abspath(__file__))          # ...\services\mcp
SERVICES = os.path.dirname(HERE)                           # ...\services
ROOT = os.path.dirname(SERVICES)                           # ...\gsv-tts
CONFIG_PATH = os.path.join(SERVICES, "config.json")
OUT_DIR = os.path.join(ROOT, "out")

# protocol traffic goes here; raw *binary* handles so we control the codec.
# Windows text-mode stdio defaults to the locale (GBK), which mangles UTF-8
# JSON payloads; we therefore read/write bytes and decode/encode UTF-8 by hand.
_PROTO_IN = None
_PROTO_OUT = None


def log(msg):
    try:
        sys.stderr.write("[mcp] %s\n" % msg)
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# config helpers
# ---------------------------------------------------------------------------
def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config_atomic(cfg):
    """Write config.json atomically, preserving all other fields/format."""
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, CONFIG_PATH)


def gw_token(cfg=None):
    cfg = cfg or load_config()
    return (cfg.get("gateway") or {}).get("token") or ""


def engine_base(cfg=None):
    cfg = cfg or load_config()
    eng = cfg.get("engine") or {}
    host = eng.get("host", "127.0.0.1")
    port = int(eng.get("port", 9880))
    return "http://%s:%d" % (host, port), float(eng.get("timeout", 120))


def gateway_base(cfg=None):
    cfg = cfg or load_config()
    gw = cfg.get("gateway") or {}
    # gateway binds 0.0.0.0; talk to it on loopback
    port = int(gw.get("port", 9881))
    return "http://127.0.0.1:%d" % port


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def http_json(url, method="GET", body=None, token=None, timeout=30):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            payload = {"error": raw.decode("utf-8", "replace")}
        return e.code, payload


def http_get_raw(url, timeout=10):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


# ---------------------------------------------------------------------------
# tool implementations  -> each returns a python object (will be JSON-encoded)
# ---------------------------------------------------------------------------
def tool_tts_status(args):
    cfg = load_config()
    eng_base, eng_timeout = engine_base(cfg)
    gw_base = gateway_base(cfg)
    token = gw_token(cfg)

    out = {"ok": False}
    # engine
    try:
        code, eng = http_json(eng_base + "/health", timeout=5)
        out["engine"] = eng
        out["engine_http"] = code
    except Exception as e:  # noqa: BLE001
        eng = {}
        out["engine"] = {"ok": False, "error": repr(e)}

    # gateway (adds voice list, gpu, stats, active requests)
    try:
        code, gw = http_json(gw_base + "/v1/health", token=token, timeout=10)
        out["gateway_http"] = code
        out["gateway"] = gw
    except Exception as e:  # noqa: BLE001
        gw = {}
        out["gateway"] = {"ok": False, "error": repr(e)}

    out["ok"] = bool(eng.get("ok")) and bool(gw.get("ok"))
    out["voice"] = eng.get("voice") or gw.get("voice") or cfg.get("default_voice")
    out["default_voice"] = cfg.get("default_voice")
    out["queue"] = eng.get("queue")
    out["reloading"] = eng.get("reloading")
    out["sidecar"] = eng.get("sidecar")
    out["gpu"] = gw.get("gpu")
    out["active_requests"] = gw.get("active_requests")
    out["stats"] = gw.get("stats")
    return out


def tool_tts_list_voices(args):
    cfg = load_config()
    gw_base = gateway_base(cfg)
    token = gw_token(cfg)
    voices = []
    for name, meta in (cfg.get("voices") or {}).items():
        voices.append({
            "name": name,
            "text_lang": meta.get("text_lang", "zh"),
            "prompt_lang": meta.get("prompt_lang", "zh"),
            "speed_factor": meta.get("speed_factor"),
            "sample_steps": meta.get("sample_steps"),
            "ref_audio_path": meta.get("ref_audio_path"),
            "prompt_text": meta.get("prompt_text"),
            "has_reference": bool(meta.get("ref_audio_path")),
        })
    current = None
    try:
        code, v = http_json(gw_base + "/v1/voices", token=token, timeout=10)
        current = v.get("current")
    except Exception:  # noqa: BLE001
        pass
    return {
        "current": current,
        "default": cfg.get("default_voice"),
        "tts_defaults": cfg.get("tts_defaults"),
        "audio": {
            "sample_rate": (cfg.get("audio") or {}).get("sample_rate"),
            "segment_pause_ms": (cfg.get("audio") or {}).get("segment_pause_ms"),
            "warmup_text": (cfg.get("audio") or {}).get("warmup_text"),
        },
        "voices": voices,
    }


def tool_tts_speak(args):
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError('missing required parameter "text"')
    cfg = load_config()
    gw_base = gateway_base(cfg)
    token = gw_token(cfg)
    voice = args.get("voice") or cfg.get("default_voice") or "si"
    if voice not in (cfg.get("voices") or {}):
        raise ValueError("unknown voice: %s" % voice)

    speed = args.get("speed_factor")
    if speed is None:
        speed = (cfg.get("voices", {}).get(voice, {}) or {}).get("speed_factor") or 1.0
    try:
        speed = float(speed)
    except (TypeError, ValueError):
        raise ValueError("speed_factor must be a number")

    sample_rate = 24000
    out_path = args.get("out_path")
    if not out_path:
        if not os.path.isdir(OUT_DIR):
            os.makedirs(OUT_DIR)
        out_path = os.path.join(OUT_DIR, "mcp_%s.wav" % time.strftime("%Y%m%d_%H%M%S"))

    url = ("%s/v1/text-to-speech/%s/stream?output_format=pcm&sample_rate=%d"
           % (gw_base, voice, sample_rate))
    body = json.dumps({"text": text, "speed": speed}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")

    t0 = time.perf_counter()
    first = None
    pcm = bytearray()
    u = urllib.parse.urlparse(url)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=120)
    try:
        conn.request("POST", u.path + ("?" + u.query if u.query else ""),
                     body=body,
                     headers={"Authorization": "Bearer " + token,
                              "Content-Type": "application/json"})
        resp = conn.getresponse()
        if resp.status != 200:
            err = resp.read().decode("utf-8", "replace")
            raise RuntimeError("gateway HTTP %d: %s" % (resp.status, err))
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            if first is None:
                first = time.perf_counter() - t0
            pcm.extend(chunk)
    finally:
        conn.close()

    total = time.perf_counter() - t0
    if not pcm:
        raise RuntimeError("gateway returned an empty PCM stream (0 bytes)")

    # write a proper WAV container around the raw PCM
    with wave.open(out_path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(pcm))

    duration = len(pcm) / 2.0 / sample_rate
    return {
        "ok": True,
        "path": out_path,
        "voice": voice,
        "speed_factor": speed,
        "sample_rate": sample_rate,
        "duration_s": round(duration, 3),
        "first_byte_ms": round((first or total) * 1000.0, 1) if first else None,
        "total_ms": round(total * 1000.0, 1),
        "bytes": len(pcm),
    }


def tool_tts_set_params(args):
    cfg = load_config()
    changed = {}
    voices = cfg.get("voices") or {}
    default_voice = cfg.get("default_voice")

    def coerce_num(key, val, lo, hi):
        try:
            v = float(val) if key == "speed_factor" else int(val)
        except (TypeError, ValueError):
            raise ValueError("%s must be a number" % key)
        if not (lo <= v <= hi):
            raise ValueError("%s out of range %s..%s" % (key, lo, hi))
        return v

    if "speed_factor" in args and args["speed_factor"] is not None:
        v = coerce_num("speed_factor", args["speed_factor"], 0.1, 4.0)
        cfg.setdefault("tts_defaults", {})["speed_factor"] = v
        for meta in voices.values():
            meta["speed_factor"] = v
        changed["speed_factor"] = v

    if "sample_steps" in args and args["sample_steps"] is not None:
        v = coerce_num("sample_steps", args["sample_steps"], 1, 48)
        cfg.setdefault("tts_defaults", {})["sample_steps"] = v
        for meta in voices.values():
            meta["sample_steps"] = v
        changed["sample_steps"] = v

    if "default_voice" in args and args["default_voice"] is not None:
        v = str(args["default_voice"])
        if v not in voices:
            raise ValueError("unknown voice: %s (have %s)" % (v, ", ".join(voices)))
        cfg["default_voice"] = v
        changed["default_voice"] = v

    if "segment_pause_ms" in args and args["segment_pause_ms"] is not None:
        try:
            v = int(args["segment_pause_ms"])
        except (TypeError, ValueError):
            raise ValueError("segment_pause_ms must be an integer")
        if not (0 <= v <= 5000):
            raise ValueError("segment_pause_ms out of range 0..5000")
        cfg.setdefault("audio", {})["segment_pause_ms"] = v
        changed["segment_pause_ms"] = v

    if not changed:
        raise ValueError("no recognised parameters to set "
                         "(speed_factor / sample_steps / default_voice / segment_pause_ms)")

    save_config_atomic(cfg)
    return {
        "ok": True,
        "changed": changed,
        "effective": {
            "default_voice": cfg.get("default_voice"),
            "tts_defaults": cfg.get("tts_defaults"),
            "segment_pause_ms": (cfg.get("audio") or {}).get("segment_pause_ms"),
            "voices": {n: {"speed_factor": m.get("speed_factor"),
                           "sample_steps": m.get("sample_steps")}
                       for n, m in voices.items()},
        },
    }


def tool_tts_set_reference(args):
    voice = args.get("voice")
    ref = args.get("ref_audio_path")
    prompt = args.get("prompt_text")
    if not voice or not ref or not prompt:
        raise ValueError("voice, ref_audio_path and prompt_text are all required")
    cfg = load_config()
    voices = cfg.get("voices") or {}
    if voice not in voices:
        raise ValueError("unknown voice: %s (have %s)" % (voice, ", ".join(voices)))
    voices[voice]["ref_audio_path"] = str(ref)
    voices[voice]["prompt_text"] = str(prompt)
    save_config_atomic(cfg)
    return {
        "ok": True,
        "voice": voice,
        "effective": {
            "ref_audio_path": voices[voice]["ref_audio_path"],
            "prompt_text": voices[voice]["prompt_text"],
        },
        "ref_exists": os.path.isfile(str(ref)),
    }


def tool_tts_switch_voice(args):
    name = (args.get("name") or "").strip()
    if not name:
        raise ValueError('missing required parameter "name"')
    cfg = load_config()
    eng_base, eng_timeout = engine_base(cfg)
    url = "%s/set_gpt_weights?weights_path=%s" % (eng_base, urllib.parse.quote(name, safe=""))
    t0 = time.perf_counter()
    try:
        status, raw = http_get_raw(url, timeout=300)
        try:
            result = json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001
            result = {"raw": raw.decode("utf-8", "replace")[:500]}
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("engine set_gpt_weights failed: %r" % (e,))
    return {
        "ok": status == 200,
        "requested": name,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "engine": result,
    }


def tool_tts_warmup(args):
    cfg = load_config()
    gw_base = gateway_base(cfg)
    token = gw_token(cfg)
    text = args.get("text") or (cfg.get("audio") or {}).get("warmup_text") or u"你好。"
    data = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(gw_base + "/v1/tts", data=data, method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            wav_bytes = r.read()
            xsec = r.headers.get("X-Audio-Seconds")
            code = r.status
    except urllib.error.HTTPError as e:
        raise RuntimeError("gateway /v1/tts HTTP %d: %s"
                           % (e.code, e.read().decode("utf-8", "replace")))
    elapsed = time.perf_counter() - t0
    return {
        "ok": code == 200 and len(wav_bytes) > 44,
        "text": text,
        "elapsed_s": round(elapsed, 3),
        "audio_seconds": float(xsec) if xsec else None,
        "wav_bytes": len(wav_bytes),
    }


TOOLS = {
    "tts_status": {
        "fn": tool_tts_status,
        "schema": {
            "name": "tts_status",
            "description": "Report engine + gateway health, GPU VRAM/temp, queue depth and the currently loaded voice.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    "tts_list_voices": {
        "fn": tool_tts_list_voices,
        "schema": {
            "name": "tts_list_voices",
            "description": "List configured voices with their per-voice parameters (lang, speed_factor, sample_steps, reference audio).",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    "tts_speak": {
        "fn": tool_tts_speak,
        "schema": {
            "name": "tts_speak",
            "description": "Synthesize text to a WAV file via the gateway; returns the file path, duration and time-to-first-byte.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to synthesize (<=2000 chars)."},
                    "voice": {"type": "string", "description": "Voice name; defaults to default_voice (si)."},
                    "speed_factor": {"type": "number", "description": "Speech speed; defaults to the voice's speed_factor (0.88)."},
                    "out_path": {"type": "string", "description": "Output WAV path; defaults to <PROJECT_ROOT>\\out\\mcp_<ts>.wav."},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    },
    "tts_set_params": {
        "fn": tool_tts_set_params,
        "schema": {
            "name": "tts_set_params",
            "description": "Update synthesis defaults in services\\config.json (atomic write, other fields preserved). Returns the effective values.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "speed_factor": {"type": "number", "description": "0.1..4.0"},
                    "sample_steps": {"type": "integer", "description": "1..48 (default 4)"},
                    "default_voice": {"type": "string"},
                    "segment_pause_ms": {"type": "integer", "description": "0..5000"},
                },
                "additionalProperties": False,
            },
        },
    },
    "tts_set_reference": {
        "fn": tool_tts_set_reference,
        "schema": {
            "name": "tts_set_reference",
            "description": "Set the reference audio path and prompt text for a voice in services\\config.json.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "voice": {"type": "string"},
                    "ref_audio_path": {"type": "string"},
                    "prompt_text": {"type": "string"},
                },
                "required": ["voice", "ref_audio_path", "prompt_text"],
                "additionalProperties": False,
            },
        },
    },
    "tts_switch_voice": {
        "fn": tool_tts_switch_voice,
        "schema": {
            "name": "tts_switch_voice",
            "description": "Switch the engine's loaded GPT weights (full voice) via /set_gpt_weights. Takes ~15s; do not call mid-session repeatedly.",
            "inputSchema": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Voice/weights name, e.g. si."}},
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    "tts_warmup": {
        "fn": tool_tts_warmup,
        "schema": {
            "name": "tts_warmup",
            "description": "Send one tiny synthesis to warm the reference cache; returns elapsed time.",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Defaults to audio.warmup_text or the default warmup phrase."}},
                "additionalProperties": False,
            },
        },
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC plumbing
# ---------------------------------------------------------------------------
def _content(payload, is_error=False):
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False)
    res = {"content": [{"type": "text", "text": text}]}
    if is_error:
        res["isError"] = True
    return res


def handle_request(msg):
    """Return a response dict, or None for notifications."""
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    # notifications carry no id and get no response
    if msg_id is None and method and method.startswith("notifications/"):
        return None

    def ok(result):
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def err(code, message):
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    if method == "initialize":
        return ok({
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "ping":
        return ok({})

    if method == "tools/list":
        return ok({"tools": [t["schema"] for t in TOOLS.values()]})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = TOOLS.get(name)
        if not tool:
            return err(-32602, "unknown tool: %s" % name)
        try:
            if name == 'tts_switch_voice':
                sys.path.insert(0, SERVICES)
                from gpu_guard import hold
                with hold():
                    result = tool["fn"](arguments)
            else:
                result = tool["fn"](arguments)
            return ok(_content(result, is_error=False))
        except ValueError as e:
            return ok(_content({"error": str(e)}, is_error=True))
        except Exception as e:  # noqa: BLE001
            log("tool %s failed: %r" % (name, e))
            return ok(_content({"error": "%s: %s" % (type(e).__name__, e)}, is_error=True))

    if msg_id is None:
        return None
    return err(-32601, "method not found: %s" % method)


def send(obj):
    if obj is None:
        return
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    _PROTO_OUT.write(line.encode("utf-8"))
    _PROTO_OUT.flush()


def main():
    # keep stdout exclusively for JSON-RPC; stray prints go to stderr
    global _PROTO_IN, _PROTO_OUT
    _PROTO_IN = sys.stdin.buffer
    _PROTO_OUT = sys.stdout.buffer
    # any accidental print() now lands on stderr, never in the protocol stream
    try:
        sys.stdout = sys.stderr
    except Exception:  # noqa: BLE001
        pass
    log("gsv-tts MCP server starting (protocol %s)" % PROTOCOL_VERSION)

    while True:
        raw_line = _PROTO_IN.readline()
        if not raw_line:
            break
        line = raw_line.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as e:  # noqa: BLE001
            send({"jsonrpc": "2.0", "id": None,
                  "error": {"code": -32700, "message": "parse error: %s" % e}})
            continue
        if isinstance(msg, list):                     # batch
            for m in msg:
                send(handle_request(m))
        else:
            send(handle_request(msg))
    log("stdin closed, exiting")


if __name__ == "__main__":
    main()
