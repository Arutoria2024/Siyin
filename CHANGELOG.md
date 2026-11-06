# 更新日志 · Changelog

本项目的主要变更记录。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

## [1.0.0] - 2026-11-06

首个公开版本。

### 新增
- Windows 桌面工作台：React 19 + TypeScript + Vite + WebView2，浅/深主题、水墨视觉。
- 文本 / TXT 批量合成，长文自动分段、串行队列执行。
- 实时流式试听，WAV 母版保存。
- SQLite 作品库：任务状态、标题、来源、音色快照；搜索、回放、重试、导入音频。
- 多格式导出：WAV / MP3 / FLAC / M4A / Ogg / PCM。
- GPU / CPU / 温度 / 显存 / 队列监控与负载曲线。
- 本机 HTTP 语音网关（9881）与可选局域网入口（默认 9890，API Key 鉴权）。
- 7 个 stdio MCP 工具。
- 分卷安装器（Inno Setup，约 2.9 GB，三文件同目录分发）。
- 26 项单元测试，覆盖桌面服务身份、端口冲突、局域网认证/代理/开关与独立安装配置。

### 已知限制
- 未包含语音识别、模型训练、云端托管、远程 HTTP MCP。
- 未签名安装包；需 Windows 10/11 x64 + WebView2 + Vulkan 显卡。
- 引擎 gsv.cpp 的 C++ 源码不在本仓库，仅分发预编译二进制；模型与素材授权需单独核对。
