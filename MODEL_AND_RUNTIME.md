# 模型与运行时准备

本仓库只包含**源码与文档**。要让「祀音」真正运行，还需要自行准备下列模型、运行时与二进制。它们体积大、且各自有独立许可，未纳入源码仓库（`.gitignore` 已排除）。

目录约定（均相对项目根 `app/`）：

```
app/
  engine/        gsv.cpp 预编译推理后端（gsv_server.exe + ggml-*.dll）
  models/        GGUF 模型权重、音色权重、参考音频、前端数据
  python/        内嵌 Python 3.10 运行时（含第三方依赖）
  tools/ffmpeg/  FFmpeg / ffprobe 二进制
```

## 1. 推理引擎 app/engine

`gsv_server.exe` 及同目录 `ggml.dll`、`ggml-base.dll`、`ggml-cpu.dll`、`ggml-vulkan.dll`、MSVC 运行库（`msvcp140.dll`、`vcruntime140*.dll`、`concrt140.dll`）。

- 来源：gsv.cpp 项目的预编译 Windows/Vulkan 发行包。
- 1.1.0 固定上游 [KakaruHayate/gsv.cpp v0.1.2](https://github.com/KakaruHayate/gsv.cpp/releases/tag/v0.1.2)，提交与成套文件 SHA-256 见 [docs/runtime-lock.json](docs/runtime-lock.json)。必须同时更新 EXE、四个 ggml DLL、文本侧车及 frontend.py；不要混用旧 Vulkan DLL。MIT 许可及第三方声明存于 docs/licenses。
- 本仓库**不包含**引擎 C++ 源码；请在发布说明中写清上游仓库地址与版本/提交。

## 2. 模型 app/models

核心 GGUF（放在 `app/models/` 根）：

| 文件 | 说明 |
|---|---|
| `gsv-ar-q8.gguf` / `gsv-ar-*.gguf` | AR 生成模型 |
| `gsv-dit-f16all.gguf` | DiT（扩散头） |
| `gsv-cond-f16.gguf` | 条件编码 |
| `gsv-bert-f16.gguf` | BERT 特征 |
| `gsv-hubert-f16.gguf` | HuBERT 语义特征 |
| `gsv-refcode.gguf` | 参考编码 |
| `gsv-vocoder-f32.gguf` | 声码器 |
| `resampy_kaiser_best.bin` | 重采样滤波器 |

音色 `app/models/voices/si/`：

- `gsv-ar-si-*.gguf`：祀音色 AR 权重
- `ref_si.wav`：参考音频
- `manifest.json`：音色清单。仓库内 `packaging/staging/app/models/voices/*/manifest.json` 提供了 `@APP_ROOT@` 占位的脱敏模板，复制到 `app/models/voices/<voice>/` 即可；`app/desktop/bootstrap.py` 会在安装时把 `@APP_ROOT@` 替换为本机绝对路径。

前端数据 `app/models/frontend/` 与 `app/models/nltk_data/`：`bert_tokenizer`、`g2pw`（`g2pW.onnx` 约 608MB）、`nltk_data`、`fast_langdetect`。

- 常见来源：Hugging Face `KakaruHayate/GSV.CPP`（`frontend/`、模型目录）。请按上游页面的实际版本与校验和获取。

## 3. 内嵌 Python app/python

一个可移植的 Python 3.10 运行时（`python.exe` / `pythonw.exe` + `Lib` + `site-packages`）。桌面端依赖见 `app/desktop/requirements.txt`：

```
pywebview==5.4
pystray==0.19.5
psutil==7.0.0
pythonnet==3.0.5
clr-loader==0.2.7.post0
Pillow==11.1.0
```

文本前端（sidecar）依赖见 `app/frontend/frontend/requirements-zh.txt` / `requirements-multi.txt`（无需 torch）。

英文运行时应验证 `from g2p_en import G2p` 能实际导入，不能只看包是否存在。本次内嵌环境 typeguard 4.6.0 与旧 typing_extensions 文件冲突，修复为 typing_extensions 4.15.0（已锁定 wheel 校验和）；NLTK 词典与词性标注数据仍需准备。中文 G2PW 仍依赖 ONNX Runtime。

## 4. FFmpeg app/tools/ffmpeg

`ffmpeg.exe` / `ffprobe.exe`，用于 MP3/FLAC/M4A/Ogg 等导出格式。FFmpeg 以 **GPL v3** 分发，源码仓库不内置，请从官方或可信构建获取，并保留其许可证文件。

## 5. 首次启动

1. 复制 `app/services/config.example.json` 为 `app/services/config.json`（保留 `@APP_ROOT@` 与空 `token`）。
2. 启动时 `app/desktop/bootstrap.py` 会把 `@APP_ROOT@` 解析成实际路径，并为每个安装**独立生成** `gateway.token`。
3. 双击根目录 `祀音.exe`（由 `app/desktop/Launcher.cs` 经 `packaging/build.ps1` 编译），或运行 `app/desktop/launch.py`。

> 模型、参考音频、头像等素材的分发授权请单独核对；「代码开源」不等于这些素材已获再分发授权。
