# CI

中文 | [English](ci.en.md) · [文档总览](../README.md)

`.github/workflows/ci.yml`，当前 job：

| Job | 内容 |
|---|---|
| `lint` | `ruff check .`（Python 3.11） |
| `security` | `pip-audit -r requirements.txt`（阻塞；仅三个上游约束导致的 cryptography ID 按下文精确豁免）+ `bandit`（非阻塞，报告上传为 artifact） |
| `test` | 3.10 / 3.11 / 3.12 三版本矩阵，从 `requirements-platform.lock` 安装基础与可选平台桥接依赖，再运行 `pytest tests/ --cov=. --cov-branch -n auto`，覆盖率报告上传为 artifact |
| `cli` | Rust CLI（`cli/`）：`cargo fmt --check` + `clippy -- -D warnings` + `cargo test`，另对帮助文本做子命令清单冒烟（doctor/init/start/stop/restart/status/logs/upgrade/migrate/plugin/capabilities/manifest/compose），防止重构悄悄丢命令 |
| `windows-native` | windows-latest 上跑 `pytest tests/windows`——进程树、升级与安装可靠性的原生矩阵（哨兵/PID/激活记录等都依赖真实 Windows 语义） |
| `documentation` | 标准库链接/锚点、双语配对、迁移映射、状态检查与六个正反例合同测试 |
| `flow-manifest` | 源码锚点与消息流程生成物漂移门禁 |
| `flow-closure` | GitNexus 索引、inventory 与独立发现入口对账 |
| `notify` | 仅 PR：汇总状态并评论（依赖 test/lint/security/cli/flow-manifest/flow-closure/documentation） |

`test` 依赖 `lint` 与 `security` 通过；`fail-fast: false` 保证某个版本失败时其余继续。同一分支的旧工作流会被自动取消。

**本地复现 CI 环境**：

```bash
pip install -r requirements-platform.lock -r requirements-dev.txt pytest pytest-asyncio pytest-cov pytest-xdist pytest-timeout
ruff check .
pytest tests/ --cov=. --cov-branch -n auto --dist loadgroup
```

`requirements-platform.lock` 包含 `requirements.txt` 的基础依赖（包括目录中 29 条可选记录对应的 28 个适配器发行包）及 `requirements-platform.in` 声明的可选 Uninfo。黑盒语音要求 Python 3.11+，因此 Python 3.10 矩阵会按 marker 跳过该包。OneBot v11 出站 codec 需要的 Alconna 也在基础依赖中。

`pip-audit` 是阻塞的，未列入精确豁免的漏洞会让 CI 失败。当前 NoneBot QQ 适配器仍将 `cryptography` 限制在 `<49`；该适配器使用 Ed25519，没有调用以下公告影响的 PKCS#7 解密或 `cryptography` X.509 验证 API，因此 CI 只豁免三个精确 ID：`PYSEC-2026-3552`、`PYSEC-2026-3553`、`PYSEC-2026-3554`。这不是对已安装 `cryptography` 无漏洞的声明；当 QQ 适配器放宽版本上限并可解析到修复版本后，应删除豁免并恢复完整审计。Mail 适配器因其 `aiosmtplib~=3.0` 约束无法安装 `PYSEC-2026-3805` 的修复版 5.1.2，已在目录和运行时策略中屏蔽，并从基础依赖移除。不要用 `|| true` 关闭其余漏洞检查。

**只有 3.10 红、且是全量 collect error 时，先怀疑传递依赖**。`requirements.txt` 里的直接依赖基本都是下限约束（`>=`），传递依赖则完全不钉——任何上游发一个只支持 3.11+ 的新版本，`test (3.10)` 就会全红，而 3.11/3.12 与开发机全绿。2026-09-01 的实例：`pygtrie` 2.6.0 在模块顶层用了 `typing.Self`（3.11 才有），`import nonebot` 直接抛 `AttributeError: module 'typing' has no attribute 'Self'`，622 个用例全部 error。这类故障的排查方式是**只看 `==== ERRORS ====` 段的第一条 traceback**（几万行日志里全是同一条的复制），修法是在 `requirements.txt` 里显式钉住那个传递依赖并写清原因。

Dashboard test/build 独立定义于 `.github/workflows/dashboard_ci.yml`。Agent 初始化模式与附加门禁见 [验证规则](../agent/verification.md)。
