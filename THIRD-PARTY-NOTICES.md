# 第三方组件与素材归属

本仓库自有代码以根目录 [LICENSE](LICENSE)（MIT）发布。下列第三方组件与素材由各自权利人授权，**不适用**本仓库的 MIT 条款；分发或再发布前请逐项核对上游许可与素材授权。

## 代码 / 依赖

| 组件 | 位置 | 许可 | 来源 |
|---|---|---|---|
| GPT-SoVITS 文本前端（G2P） | `app/frontend/frontend/GPT_SoVITS/text/` | MIT | RVC-Boss / GPT-SoVITS（上游 `text/` 的逐字副本，含 g2pw、zh_normalization、LangSegmenter、ja_userdic 等） |
| pywebview | 运行时依赖 | BSD-3-Clause | r0x0r/pywebview |
| pystray | 运行时依赖 | LGPL-3.0 | moses-palmer/pystray |
| psutil | 运行时依赖 | BSD-3-Clause | giampaolo/psutil |
| pythonnet / clr-loader | 运行时依赖 | MIT | pythonnet |
| Pillow | 运行时依赖 | HPND (PIL) | python-pillow |
| React / ReactDOM / Vite / TypeScript / lucide-react | `app/ui/` 前端依赖 | MIT / ISC / Apache-2.0（见各自包） | 各上游项目 |
| FFmpeg（ffmpeg.exe / ffprobe.exe） | `app/tools/ffmpeg/`（**未随源码提供**） | GPL v3 | ffmpeg.org |

## 模型与运行时（未随源码提供）

| 项目 | 说明 | 许可/来源 |
|---|---|---|
| gsv.cpp 推理引擎（`gsv_server.exe` 及 ggml DLL） | 预编译二进制，无对应 C++ 源码随本仓库提供 | 见上游 gsv.cpp 项目 |
| GGUF 模型权重（AR / DiT / Cond / BERT / HuBERT / RefCode / Vocoder） | `app/models/*.gguf` | 见 Hugging Face `KakaruHayate/GSV.CPP` 等上游模型页；训练数据与权重许可需单独核对 |
| G2PW / BERT tokenizer / NLTK 数据 | `app/models/frontend/`、`app/models/nltk_data/` | 各自上游（G2PW、bert-base-chinese、NLTK） |
| 内嵌 Python 3.10 运行时 | `app/python/` | PSF License |

## 图像 / 音频素材

| 素材 | 位置 | 说明 |
|---|---|---|
| 角色头像 | `app/ui/public/assets/character.jpg` | 参考人物图，来源与再分发授权需**单独确认** |
| 应用图标源图 | `appico.png`、`app/monitor/*.ico` | 由上述素材派生 |
| 背景图 / 水墨山水 | `app/ui/public/assets/{banner,ink,ink-landscape-*.jpg,png}` | 程序生成或项目自制，按项目许可 |
| 参考音频 | `app/models/voices/si/ref_si.wav`（**未随源码提供**） | 音色参考音频，来源与授权需单独确认 |

> 说明：本文件仅做归属登记，不代表上述第三方素材已获得面向公众的再分发授权。「代码开源」不能被解读为「全部模型、人物图片、参考音频与捆绑组件均已许可清理」。正式公开发布前，请按每一项的实际授权状态决定是否随包分发。
