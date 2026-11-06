# 贡献指南 · Contributing

感谢你愿意为「祀音」出一份力！在提交 Issue 或 Pull Request 之前，请花几分钟阅读本指南。

## 报告问题（Issue）

- 请先搜索是否已有相同 Issue。
- 使用 Issue 模板，写清：**系统版本、显卡/驱动、复现步骤、期望结果、实际结果、相关日志**（`app/logs/desktop.log`、`app/monitor/logs/*.log`）。
- 日志粘贴前请**自行脱敏**：删除本机路径、内网 IP、API Key、个人作品内容。
- 安全漏洞请**不要**开公开 Issue，按 [SECURITY.md](SECURITY.md) 私下报告。

## 提交代码（Pull Request）

1. Fork 本仓库并从 `main` 拉出特性分支：`feat/xxx`、`fix/xxx`、`docs/xxx`。
2. 保持改动聚焦，一个 PR 只做一件事；避免顺带格式化无关文件。
3. 代码约定：
   - 保留既有 API 路径、7 个 MCP 工具名、默认音色 `si` 的语速 `0.88` / 步数 `4`，除非任务明确要求修改。
   - 服务只管理已核对属于本项目的进程，禁止按进程名全局 stop。
   - 新增配置项优先走 `config.example.json` 模板 + `bootstrap.py`，不要把真实密钥写进代码。
4. 提交前自测：
   ```powershell
   python -m unittest discover -s app/tests -p "test_*.py"
   cd app/ui; npm run build
   ```
   `app/tests/api_smoke.py`、`mcp_smoke.py`、`release_integration.py` 会真实合成并写入作品库，按需单独运行。
5. 填写 PR 模板，说明动机、改动与验证方式。

## 代码风格

- Python 以仓库既有风格为准；前端在 `app/ui`，使用 TypeScript。
- 提交信息建议遵循 [Conventional Commits](https://www.conventionalcommits.org/)：`feat: ...` / `fix: ...` / `docs: ...` / `refactor: ...`。

## 许可

提交贡献即表示你同意以本项目的 [MIT License](LICENSE) 授权你的贡献。
