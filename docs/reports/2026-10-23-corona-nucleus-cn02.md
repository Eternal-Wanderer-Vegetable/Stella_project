# Corona / Nucleus 实施 CN02 — 托管入口与有界生命周期

日期：2026-10-23（Asia/Shanghai） · 分支：`codex/corona-nucleus-implementation` · CN02 基线：`336dc78`

**包状态：CN02 代码包完成。CORONA-IMPL 总体仍 in progress / NOT READY。** 默认 `python bot.py` 仍走 legacy 启动；Corona supervisor、完整进程树所有权与接任由后续 CN03 实施。本阶段只启用显式 managed Nucleus。

## GitNexus 与编辑风险

CN01 HEAD `336dc78` 上的 1.6.12 / PDG 索引完成状态核对：索引绑定该提交、覆盖 1,926 个文件；源代码编辑完成后 `status` 如预期显示 5 changed / 6 added。未对脏工作区重建索引，以免覆盖提交前差异。编辑前 upstream impact 及 UNKNOWN 补查如下：

| 对象 | upstream risk / 调用者 | 决策与证据 |
| --- | --- | --- |
| `bot.py` | UNKNOWN / 0 图调用者 | 源码检查确认 Docker、shell、deploy CLI、smoke、桌面启动器及 release workflow 等字面入口；受管分支以 `runpy` 非 `__main__` 名装配，旧入口保持默认。 |
| `spawn_successor` | LOW / 2 impacted、1 direct | 在 managed 核心下拒绝自派 successor；原 service→route 链保留。 |
| `_find_uvicorn_server` | LOW / 3、1 | managed 时从 active lifecycle 取 server；legacy 路径保持。 |
| `_graceful_shutdown_body` | LOW / 3、1 | 生命周期 hook 共享 deadline；原业务关闭实现沿用。 |
| `_stop_cometa` | LOW / 3、1 | 既有 Cometa stop hook 被纳入统一剩余预算。 |
| `_start_scheduling`、`_start_cometa` | UNKNOWN / 0 图边 | 动态 `@get_driver().on_startup` 装饰器为静态图漏边；源码确认注册，受管桥将两项移至 ready 后队列，legacy decorators 不改。 |
| `cometa.runtime.stop` | UNKNOWN / 0 | 源码 `_stop_cometa()` 持有对象并调用，未改 Cometa 实现。 |

没有 HIGH / CRITICAL 风险项。图缺少动态 decorator、接收者及部分 launcher 边，UNKNOWN 的结论由源码引用审计补证，不解释为空闲代码。

## 实现

- 新建 `nucleus.bootstrap`、`nucleus.framework`、`nucleus.lifecycle` 与 `python -m nucleus` 入口。bootstrap 只从 CN01 不可变 revision 重构业务环境，校验项目/实例/代身份、回环内部监听与项目 cwd，随后解析实际 `DB_PATH`；launch capability 保留在生命周期内存，不留在环境变量中。
- `BusinessRootLock` 对规范化业务 SQLite 路径持有 POSIX `flock` / Windows `msvcrt` 文件句柄锁。锁先于 Bot/plugin 装配获取；冲突以退出码 73 拒绝，不导入业务栈。
- managed `bot.py` 跳过 Dashboard 源码构建、Corona 自登记/替换、legacy `nonebot.init` 和 successor 等副作用；`core.self_restart.spawn_successor` 在 managed 模式 fail closed。无 managed marker 时继续 legacy 启动。
- NoneBot bridge 固定要求 2.5.0，显式 `Env(_env_file=None)` / `Config(_env_file=None)`；私有 resolver、Driver registry 和 lifespan callback 访问集中于 `nucleus/framework.py`。scheduler / Cometa 继续在 legacy startup 装饰器注册，managed 时在 ready gate 后运行。
- 私有 health/drain/stop 控制路由要求 loopback 对端、Bearer capability 及代/控制器/配置 revision 身份。普通 HTTP 在 ready 前/排空后得到结构化 503；健康数据不含 token。重复 drain 不延长单一 shutdown deadline，shutdown hooks 消耗同一剩余预算；强制 watchdog 超时退出。
- 现有 memory、scheduling、Cometa 与 facade 关闭/投递业务仍保留。Nucleus 本身不启动 successor。

## 验收与验证

| 命令 / 检查 | 结果 |
| --- | --- |
| `STELLA_HOME=/tmp/stella-cn02-final-targeted .venv/bin/python -m pytest tests/nucleus -q` | **9 passed / 2.17s**；含真实 managed Nucleus OS 子进程、身份 health、配置源变更隔离、无 token 泄漏、同一 DB 第二核心拒绝及 drain/stop/退出。 |
| `STELLA_HOME=/tmp/stella-cn02-final-process .venv/bin/python -m pytest tests/nucleus/test_managed_process.py -q -s` | **1 passed / 1.49s**；真实进程退出码为 0，第二 writer 以 73 退出，第一代仍持锁运行。 |
| source-order guard + `tests/test_self_restart.py` | **7 passed / 1.27s**。 |
| 全仓 `.venv/bin/ruff check .` | 通过。 |
| `scripts/generate_message_flow.py --check` | 通过，manifest `message-flow.982a65f5aef2.json` 与源码匹配。 |
| 相关模块 `compileall` | 通过。 |
| `python3 scripts/check_docs.py` | 119 files / 1,272 local links / 577 anchors / 0 errors。 |
| `git diff --check` | 通过（报告/状态及最终暂存后还会复跑）。 |
| 全量 `STELLA_HOME=/tmp/stella-cn02-final-full-20261023 .venv/bin/python -m pytest -q` | **4037 passed / 29 skipped / 1 failed / 239.71s**。唯一失败 `tests/webui/test_webui_cometa.py::TestInputs::test_respond_with_stale_revision_conflicts` 在全量顺序中提交 API 收到 401、预期 202；完全相同用例隔离复跑 **1 passed / 0.66s**。原因未确认，不将全量标绿。 |

所有测试用独立临时 `STELLA_HOME` / pytest `tmp_path`；没有读取或改写真实用户 `.env`、生产数据库、聊天记录或凭据。未启动真实模型、QQ/WebChat、Docker 或部署服务。

进程级 ready、revision 不受 live `.env` 改写、重复业务 DB writer 拒绝、有效凭据 drain/stop 和正常退出已实证。shutdown deadline 与 watchdog 由生命周期测试覆盖；CN03 尚需落实 OS 进程树 fencing / orphan 子进程退出证明，不能从本阶段的核心锁推断为已完成。Windows 锁分支没有在 Windows 主机验收。

## 提交前 GitNexus 变更门禁

暂存后 serial 执行完成：

| 命令 | 结果 |
| --- | --- |
| `node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project --limit 1000` | 16 files / 9 symbols / 1 affected process / **MEDIUM**；变更 flow 为 `System_restart → Bot_entry`（`spawn_successor`）。未报告 partial / truncated。 |
| `node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | 146 files / 291 symbols / 58 affected processes / **CRITICAL**，累计包含 CN00、CN01 与继承计划基线。串行输出未报告 partial / truncated；终端仅省略了详细符号/flow 列表尾部。 |

All 与 compare 串行运行；CRITICAL compare 按原始值保留，不由本包定向测试豁免。

## 下一阶段

CN03：实现独立 Corona app 与唯一 supervisor、核心状态机、OS 所有权锁、进程树/后代退出确认、启动日志与崩溃退避；在核心导入失败、挂起、崩溃与外部 PID 场景验证 Corona 控制面仍可用。
