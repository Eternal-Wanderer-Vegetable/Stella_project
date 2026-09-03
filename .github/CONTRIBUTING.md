# 贡献指南 / Contributing Guide

感谢你愿意为 Stella 贡献代码、文档、测试、问题反馈或设计建议。中文是本指南的主要语言；英文版本紧随其后。

Thank you for contributing code, documentation, tests, issue reports, or design ideas to Stella. Chinese is the primary language of this guide; the English version follows each section.

## 先看这些文档 / Read These First

- [开发指南（中文）](../docs/development.md) / [Development Guide (English)](../docs/development.en.md)
- [架构说明（中文）](../docs/architecture.md) / [Architecture (English)](../docs/architecture.en.md)
- [插件接入规范（中文）](../docs/plugin-spec.md) / [Plugin Specification (English)](../docs/plugin-spec.en.md)
- [LICENSE](../LICENSE)

开发指南包含环境准备、测试、CI、代码约定、发布流程和 PR 前检查项。涉及记忆、提示词、数据归属、监听器优先级或成本控制的改动，请先阅读相关设计记录。

The Development Guide covers setup, tests, CI, code conventions, release procedures, and the pre-PR checklist. For changes involving memory, prompts, data ownership, listener priority, or cost control, read the relevant design records first.

## 报告问题 / Report an Issue

提交前请搜索已有 Issue，确认问题尚未被报告。请使用 Issue 模板，并提供：

- Stella 版本、操作系统和 Python 版本。
- 可复现步骤、实际结果和预期结果。
- 相关日志或最小复现示例。
- 脱敏后的配置和数据；不要上传 `.env`、API 密钥、聊天记录、数据库或完整运行日志。

Before opening an issue, search existing issues to avoid duplicates. Use an issue template and include your version, operating system, Python version, reproduction steps, actual and expected results, and relevant logs or a minimal reproduction. Redact sensitive data; never upload `.env` files, API keys, chat transcripts, databases, or complete runtime logs.

安全漏洞请阅读 [安全政策 / Security Policy](SECURITY.md)，不要在公开 Issue 中披露。

For security vulnerabilities, read the [Security Policy](SECURITY.md) instead of disclosing them in a public issue.

## 开发环境 / Development Setup

```bash
git clone https://github.com/Eternal-Wanderer-Vegetable/Stella_project.git
cd Stella_project
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

项目要求 Python `>=3.10, <4.0`。开发期间请将真实用户数据放在被忽略的 `StellaData/` 或其他本地数据目录中，不要写入仓库。

The project requires Python `>=3.10, <4.0`. Keep real user data in the ignored `StellaData/` directory or another local data directory; do not add it to the repository.

## 提交前检查 / Before Submitting

```bash
python -m pytest tests -q
ruff check .
```

两条命令都应通过。若改动涉及提示词、数据库 schema、配置、发布布局或 GUI 数据契约，请按开发指南执行额外检查，并在 PR 描述中说明结果。

Both commands should pass. For changes involving prompts, database schema, configuration, release layout, or GUI data contracts, run the additional checks in the Development Guide and report the results in the PR description.

## Pull Request 要求 / Pull Request Requirements

- 每个 PR 聚焦一个主题，标题简洁并说明实质变化。
- 代码、测试和文档应同步更新；新增行为应有回归测试。
- 不要提交凭据、用户数据、运行日志、构建产物或无关格式化改动。
- 描述变更动机、实现方式、测试结果和已知限制。
- 如果 PR 仍在讨论阶段，请标记为 Draft。
- 维护者可能要求补充测试、拆分范围或调整实现。

- Keep each PR focused on one topic with a concise title describing the substantive change.
- Update code, tests, and documentation together; add regression tests for new behavior.
- Do not commit credentials, user data, runtime logs, build artifacts, or unrelated formatting changes.
- Describe the motivation, implementation, test results, and known limitations.
- Mark the PR as Draft while it is still under discussion.
- Maintainers may request more tests, a narrower scope, or implementation changes.

## 提交信息 / Commit Messages

提交信息可以使用中文或英文，应简要说明实际变化。避免使用 `fix bug`、`update` 等无法表达内容的描述。

Commit messages may be written in Chinese or English and should briefly describe the actual change. Avoid uninformative messages such as `fix bug` or `update`.

## 许可 / License

提交到本项目的内容应允许在项目 [AGPL v3.0](../LICENSE) 许可及其中适用的附加条款下发布。提交 PR 即表示你有权提交这些内容。

Contributions must be distributable under the project’s [AGPL v3.0](../LICENSE) license and applicable additional terms. By opening a PR, you confirm that you have the right to submit the contribution.
