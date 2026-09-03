# 安全政策 / Security Policy

## 支持的版本 / Supported Versions

安全修复优先针对当前 `main` 分支和最新发布版本。旧版本是否修复，取决于问题影响、修复成本和维护者判断。

Security fixes primarily target the current `main` branch and the latest release. Whether older versions are fixed depends on impact, maintenance cost, and maintainer judgment.

| 版本 / Version | 安全支持 / Supported |
| --- | --- |
| 当前 `main` / Current `main` | ✅ |
| 最新发布版 / Latest release | ✅ |
| 更早版本 / Older versions | 视情况而定 / Case by case |

## 报告漏洞 / Reporting a Vulnerability

请不要通过公开 Issue、Pull Request、讨论区或公开群消息报告安全漏洞。请优先使用仓库 GitHub 页面上的私密漏洞报告入口（Security → Report a vulnerability，若该功能已启用）。

Do not report security vulnerabilities through public Issues, Pull Requests, discussions, or public group messages. Prefer the private vulnerability reporting entry on the repository’s GitHub page (Security → Report a vulnerability, if enabled).

如果私密漏洞报告入口不可用，请加入开发者 QQ 群 `263402786`，并私信 `Eternal-Wanderer-Vegetable`，说明你希望私下报告安全问题。请不要发送真实用户数据、API 密钥或完整数据库；只提供验证问题所需的最小脱敏信息。

If private vulnerability reporting is unavailable, join the developer QQ group `263402786` and privately contact `Eternal-Wanderer-Vegetable`, stating that you want to report a security issue privately. Do not send real user data, API keys, or complete databases; provide only the minimum redacted information needed to verify the issue.

报告内容建议包括：

- 受影响的版本、提交或配置。
- 漏洞类型、影响范围和潜在后果。
- 最小复现步骤或概念验证。
- 你认为可行的缓解或修复建议。
- 是否已经向其他人披露，以及期望的联系渠道。

Include the affected version, commit, or configuration; vulnerability type, scope, and potential impact; minimal reproduction steps or proof of concept; possible mitigations; and any prior disclosure or preferred contact channel.

## 处理流程 / Response Process

维护者会尽快确认收到报告，并在完成初步评估后告知后续处理方式。确认漏洞后，维护者将根据情况修复、发布安全更新、在发布说明中致谢报告者（除非对方要求匿名），并在适当时公开漏洞摘要。

The maintainer will acknowledge receipt as soon as practical and explain the next steps after an initial assessment. Once confirmed, the maintainer may fix the issue, publish a security update, credit the reporter in release notes unless anonymity is requested, and publish a vulnerability summary when appropriate.

## 安全注意事项 / Security Notes

Stella 可以连接在线模型服务、OneBot 实现和第三方插件。请在报告中明确说明数据是否会离开本机；在线服务的请求内容取决于你的部署配置。任何公开示例都必须去除聊天内容、个人信息、密钥和其他凭据。

Stella can connect to online model services, OneBot implementations, and third-party plugins. When reporting an issue, state whether data leaves the local machine; requests to online services depend on your deployment configuration. Remove chat content, personal information, keys, and other credentials from all public examples.
