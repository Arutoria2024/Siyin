<div align="center">

<img alt="Siyin Logo" src="assets/logo.png" width="200" />

# Siyin · 祀音

**A local-first Windows text-to-speech workbench**, built on top of the [gsv.cpp](https://github.com/) / GPT-SoVITS v5turbo inference backend. It provides text & TXT synthesis, live streaming preview, a task queue, an audio library, multi-format export, performance monitoring, an HTTP API and an MCP server.

[![Release](https://img.shields.io/github/v/release/Arutoria2024/Siyin?color=6f4e37&label=Release)](https://github.com/Arutoria2024/Siyin/releases)
[![License](https://img.shields.io/github/license/Arutoria2024/Siyin?color=2f6f4f&label=License)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows)](https://www.microsoft.com/windows)

</div>

> 中文说明请见 [README.md](README.md)。

## What it is

This release is a **character-specific voice edition**: a fine-tuned voice of **"Shi" (祀)** from *Arknights: Endfield*, built for **fast speech synthesis of that character**. A general-purpose edition is still in development.

- **All-in-one, install and use** — engine, text frontend, models and voice are bundled. **No training, no fine-tuning, no voice cloning**, and no reference audio to prepare.
- **Very fast** — **RTF ≈ 0.2** measured on an RTX 2060 6GB (about 0.2 s of compute per 1 s of audio; 0.2–0.26 depending on text), i.e. roughly 4–5× faster than real time.
- **Low load** — ~2.7–2.9 GB VRAM; models stay resident after the first load.
- **Broad GPU support** — ggml **Vulkan** backend: NVIDIA / AMD / Intel, discrete or integrated.

## GPU support

| Tier | Models | Status |
|---|---|---|
| ✅ Tested | NVIDIA GeForce RTX 2060 6GB | stable; VRAM ~2.7–2.9 GB, **RTF ≈ 0.2** |
| 🟢 Recommended | NVIDIA RTX 20 / 30 / 40, GTX 16 series (≥4GB) | Vulkan backend, expected to work; not individually tested |
| 🟢 Recommended | AMD Radeon RX 6000 / 7000 | same as above |
| 🟡 Try | Intel Arc A/B, Vulkan-capable iGPU | may be slower with shared memory |
| 🔴 Not recommended | GPUs without Vulkan / CPU-only | works but ~14.6× slower |

## Features

- 🎙️ Text / TXT batch synthesis with automatic long-text segmentation.
- 🔊 Live streaming preview (listen while generating); WAV master output.
- 📚 SQLite-backed task & audio library: search, replay, retry, import.
- 🎚️ Export to WAV / MP3 / FLAC / M4A / Ogg / PCM (via FFmpeg).
- 📈 GPU / CPU / temperature / VRAM / queue monitoring.
- 🌐 Local HTTP gateway (9881) + optional authenticated LAN entry (default 9890).
- 🤖 7 stdio MCP tools for AI agents.
- 🖥️ Modern desktop UI (React 19 + TS + Vite + WebView2).
- 🔒 Local-first: loopback-only by default, per-install secret key.

## Download

Grab the latest installer from [**Releases**](https://github.com/Arutoria2024/Siyin/releases). The installer consists of three files (`*.exe` + two `*.bin` volumes, ~2.9 GB total) — put them in the same folder and run the exe.

Requires Windows 10/11 x64, WebView2 Runtime, a Vulkan-capable GPU (≥ 6GB VRAM recommended).

## Build from source

This repository contains source only; models, Python/FFmpeg/engine binaries are not included. See [MODEL_AND_RUNTIME.md](MODEL_AND_RUNTIME.md).

```powershell
cd app/ui && npm ci && npm run build
./packaging/build.ps1
```

## Docs

- [Model & runtime setup](MODEL_AND_RUNTIME.md)
- [Ops & source release](docs/运维与源码发布.md)
- [API](docs/接入规范/API.md) · [MCP](docs/接入规范/MCP.md)
- [Third-party notices](THIRD-PARTY-NOTICES.md)

## License

Own code is released under the [MIT License](LICENSE). Third-party code, models and assets keep their own licenses.
