# 安全策略 · Security Policy

## 报告漏洞

如果你发现了安全漏洞，**请不要公开提交 Issue**。请通过以下方式私下联系维护者：

- 发送邮件至项目维护者（可在 GitHub 个人主页找到联系方式），或
- 使用 GitHub 的 [私密漏洞报告](https://docs.github.com/zh/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/about-reporting-a-security-vulnerability)（仓库 Security 选项卡 → Report a vulnerability）。

请在报告中说明：影响范围、复现步骤、可能的影响与建议修复方式。我们会尽快确认并回复。

## 安全设计要点

- 所有内部服务默认仅监听回环地址（127.0.0.1）。
- HTTP 网关使用 Bearer / `X-Auth-Token` 令牌，常量时间比较；按 IP 限制并发。
- 局域网入口需 API Key 登录，会话使用 HttpOnly + SameSite=Strict Cookie；网络开关与密钥读取仅限本机。
- 每台安装由 `bootstrap.py` 独立生成 `gateway.token`，不随源码或安装模板分发。

## 支持范围

当前维护 1.0.x 系列。报告时请注明版本与操作系统/显卡环境。
