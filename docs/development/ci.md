# CI

中文 | [English](ci.en.md) · [文档总览](../README.md)

`.github/workflows/ci.yml`，当前 job：

| Job | 内容 |
|---|---|
| `lint` | `ruff check .`（Python 3.11） |
| `security` | `pip-audit -r requirements.txt`（阻塞）+ `bandit`（非阻塞，报告上传为 artifact） |
| `test` | 3.10 / 3.11 / 3.12 三版本矩阵，`pytest tests/ --cov=. --cov-branch -n auto`，覆盖率报告上传为 artifact |
| `cli` | Rust CLI（`cli/`）：`cargo fmt --check` + `clippy -- -D warnings` + `cargo test`，另对帮助文本做子命令清单冒烟（doctor/init/start/stop/restart/status/logs/upgrade/migrate/plugin/capabilities/manifest/compose），防止重构悄悄丢命令 |
| `windows-native` | windows-latest 上跑 `pytest tests/windows`——进程树、升级与安装可靠性的原生矩阵（哨兵/PID/激活记录等都依赖真实 Windows 语义） |
| `documentation` | 标准库链接/锚点、双语配对、迁移映射、状态检查与六个正反例合同测试 |
| `flow-manifest` | 源码锚点与消息流程生成物漂移门禁 |
| `flow-closure` | GitNexus 索引、inventory 与独立发现入口对账 |
| `notify` | 仅 PR：汇总状态并评论（依赖 test/lint/security/cli/flow-manifest/flow-closure/documentation） |

`test` 依赖 `lint` 与 `security` 通过；`fail-fast: false` 保证某个版本失败时其余继续。同一分支的旧工作流会被自动取消。

**本地复现 CI 环境**：

```bash
pip install -r requirements.txt -r requirements-dev.txt pytest pytest-cov pytest-xdist
ruff check .
pytest tests/ --cov=. --cov-branch -n auto --dist loadgroup
```

`pip-audit` 是阻塞的，某个上游依赖爆出 CVE 时 CI 会红。若判断为不可立即修复的上游问题，可临时在该步骤加 `|| true`，但应记录原因。

**只有 3.10 红、且是全量 collect error 时，先怀疑传递依赖**。`requirements.txt` 里的直接依赖基本都是下限约束（`>=`），传递依赖则完全不钉——任何上游发一个只支持 3.11+ 的新版本，`test (3.10)` 就会全红，而 3.11/3.12 与开发机全绿。2026-09-01 的实例：`pygtrie` 2.6.0 在模块顶层用了 `typing.Self`（3.11 才有），`import nonebot` 直接抛 `AttributeError: module 'typing' has no attribute 'Self'`，622 个用例全部 error。这类故障的排查方式是**只看 `==== ERRORS ====` 段的第一条 traceback**（几万行日志里全是同一条的复制），修法是在 `requirements.txt` 里显式钉住那个传递依赖并写清原因。

Dashboard test/build 独立定义于 `.github/workflows/dashboard_ci.yml`。Agent 初始化模式与附加门禁见 [验证规则](../agent/verification.md)。
