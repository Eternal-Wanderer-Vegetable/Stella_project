# Session Progress Log

## Current State

**Last Updated:** 2026-10-22 (Asia/Shanghai)
**Active Feature:** LINK-MONITOR-DI follow-up: fix the remaining `bot: Any` annotations on NoneBot Bot lifecycle hooks.
**Inherited Feature:** PR #114 was merged at `main@386b46f`; PR #113 CI repair is complete at `main@a568953`. XPLAT-IMPL external acceptance gaps remain tracked separately.
**Scope:** Investigate the second LinkMonitor injection failure and Gravitas page visibility after test environment synchronization. Fix the lifecycle hook annotations; verify the local static assets and API wiring.

**What's Done:** Code commit `15e326b` on `codex/link-monitor-lifecycle-injection-fix`, based on `origin/main@a568953`; focused regression passed (35 tests), full Ruff passed, and Dashboard build/static sync passed. Full Python suite: 4,015 passed / 29 skipped / 3 failed; each failing test passed alone with isolated `STELLA_HOME` (Cometa worker ACK, memory concurrency, WebUI group mute). Local generated snapshots now include Gravitas and match exactly. External test environment still needs deployment and a live page/API recheck.

**Files:** `extensions/link_monitor/__init__.py`, `tests/test_link_monitor.py`, `feature_list.json`, `progress.md`, and `session-handoff.md`. Build snapshots under `dashboard/dist`, `webui/dist`, and `desktop/dashboard-dist` are ignored generated files.

**What's Next:** Push the follow-up branch and open a new PR. After deployment, restart the Bot; if Gravitas shows unavailable, inspect authenticated `/api/v1/status` `data.gravitas` and the `[gravitas][boot]` log.

## 2026-10-22 — LinkMonitor lifecycle hooks and Gravitas frontend diagnosis

- LinkMonitor 原因：NoneBot `Driver.on_bot_connect` / `on_bot_disconnect` 会按 `BOT_HOOK_PARAMS` 调用 `Dependent.parse`；两个回调仍将 `bot` 标为 `Any`，因此在事件预处理器修复后暴露同一类 `Unknown parameter bot`。改为 `nonebot.adapters.Bot`，新增两种 lifecycle hook 的依赖解析回归。代码提交 `15e326b`。
- Gravitas UI 原因（本地部署快照）：`dashboard/dist` 已含 Gravitas 路由 chunk，而 `webui/dist` 与 `desktop/dashboard-dist` 是旧快照且无该 chunk。Vue typecheck、Vite build 和 `dashboard/sync-dist.mjs` 已成功；三处生成物各 52 个文件、树哈希相同，静态引用检查无缺失。前端源码与编译未发现断链。
- Gravitas 数据链：`bot.py` 调用 `setup_gravitas` 注入状态 provider，再将 `status_api.collect_status` 注入 WebUI；`/api/v1/status` 应返回 `data.gravitas`。若页面路由已出现但显示 unavailable，应检查响应中的 `data.gravitas`；值为 null 时检查启动日志 `[gravitas][boot]`。没有连接外部测试浏览器，未确认远端响应。
- GitNexus：原 `.gitnexus/meta.json` 属于另一 worktree；默认 `status` / `analyze` 因 foreign storage 拒绝；用外部临时 storage 对当前工作区建索引。两个 lifecycle handler upstream impact 为 `UNKNOWN / 0`（动态 Driver decorator），源码确认注册点和 `BOT_HOOK_PARAMS` 解析。提交前 all 与 compare/main 均为 2 files / 4 symbols / 0 processes / LOW，无 partial/truncated。
- Verification：`STELLA_HOME=/tmp/stella-debug-20261022 .venv/bin/pytest tests/test_link_monitor.py tests/test_status_api.py -q`：35 passed；全仓 Ruff、改动文件 `py_compile` 通过。Dashboard typecheck / build / sync 通过；Vite 有 chunk-size 与动态/静态双导入 warning。隔离 `STELLA_HOME=/tmp/stella-link-monitor-followup-full-20261022` 的全量 Python suite 为 4015 passed / 29 skipped / 3 failed（252.61s）；Cometa `test_subprocess_ack_pauses_claim_then_allows_fake_task_once`、memory `test_concurrent_replay_bounded_by_unique_constraint`、WebUI `test_groups_mute` 分别在独立 `/tmp/stella-link-followup-{cometa,memory,webui}-20261022` 下单测 1 passed。共享状态/顺序根因未确认，故本地全量仍记录为失败。
- Next：推送新分支并创建 follow-up PR；将 `pnpm --dir dashboard build && pnpm --dir dashboard sync:webui` 运行结果部署到测试环境后重启 Bot。若页面仍 unavailable，读取登录后的 `/api/v1/status` `data.gravitas` 与 Gravitas 启动日志继续定位。

## 2026-10-22 — PR #113 CI repair

- CI diagnosis：run `39699060445` 的 Python job 均只失败于 `TestDriftGate.test_committed_manifest_matches_source`；semantic diff 为 `cometa.claim`、`post.parse` 正文变化而拓扑未变。PR 的 `parse_output` 文案改动触发 `post.parse` 指纹更新，基线另有 `cometa.claim` 漂移。
- GitNexus：编辑前 `parse_output` upstream impact UNKNOWN/0 边；源码确认 `ai_gateway.py` 动态注册 post hook，并有 runtime、回放、评估引用。文件级 LOW，7 个影响文件 / 3 个直接 import。rebase 后 `detect-changes all` 为 3 files / 6 symbols，`compare main` 为 6 / 8，均 0 affected processes / LOW；CLI 提示 sibling-worktree 索引落后 2 commits，需保留 freshness 限制。全流程提取有预算截断（2,917 入口候选、816 callees、22 深度截断、44 walk 截断）；JSON/archive 由 Git 与 flow 门禁核验。
- Fix：`scripts/generate_message_flow.py` 生成 `core/observability/flows/message-flow.982a65f5aef2.json`；`--check` 通过。
- Local verification：Python 3.12.14 全量回归 4,014 passed / 29 skipped / 2 failed / 5 warnings（165.25s）；Cometa `test_second_worker_rejected` 和 WebUI OneBot config 测试各自在独立临时 `STELLA_HOME` 下复跑为 1 passed。全仓 Ruff、文档门禁（119 files / 1247 links / 577 anchors / 0 errors）、flow `--check`、JSON 与 diff 检查通过。全量并行失败仍如实保留。
- Hosted verification：run `39707392594` on rebased code completed successfully. Python 3.10 / 3.11 / 3.12 each reported 4,017 passed / 29 skipped; flow-manifest, flow-closure, Dashboard build, security, CLI, Windows native reliability, benchmark, docs and lint all passed. PR checks show the updated branch is mergeable.
- Commit：英文标题 `fix(memory): simplify invalid reply envelope fallback`；PR 已基于 `main@386b46f` 更新。
- Remaining local observation：full suite reported 4,014 passed / 29 skipped / 2 failed; both failures passed when isolated with separate temporary `STELLA_HOME` roots. Keep the local full-run instability visible; no PR-scoped CI failure remains.
- Next：本任务完成；PR [#113](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/113) 等待 review/merge。无新任务时不继续扩展范围。

## 2026-10-22 — LinkMonitor dependency injection fix

- Branch/base：`codex/link-monitor-event-injection-fix` from `origin/main@d136c90`。
- Root cause：NoneBot 在 `event_preprocessor` 装饰时解析函数参数；`BotParam` / `EventParam` 不接受 `typing.Any`，所以当前日志先报未知参数 `bot`，若只改 `bot`，后续 `event` 也会失败。现改用 `nonebot.adapters.Bot` 与 `Event`。
- Regression：新增测试直接调用 `Dependent.parse(..., allow_types=EVENT_PCS_PARAMS)`。既有 fixture 将 `event_preprocessor` 替换成 identity，因此原测试会跳过启动期解析合同。
- GitNexus：index at `f5e6a64`，当前 `origin/main@d136c90` 与索引 commit 的 tree diff 为空；`_refresh_on_any_event` upstream impact 为 UNKNOWN / 0 静态调用者，源码审计确认动态 `@event_preprocessor` 注册。提交前 `all` / `compare main` 均为 5 files / 8 symbols / 0 processes / LOW，无 partial/truncated。
- Verification：定向 `tests/test_link_monitor.py` 12 passed；改动文件 Ruff、`py_compile`、全仓 Ruff、`check_docs.py`（119 files / 1248 links / 577 anchors / 0 errors）、message-flow `--check` 与 `git diff --check` 通过。全量 pytest 为 4014 passed / 29 skipped / 3 failures；三个失败分别是 MemoryConsolidator lifecycle、WebUI chat auth、WebUI Cometa auth，各自用独立 `STELLA_HOME` 单测重跑均 1 passed。失败与本次模块无关，完整顺序相互作用未确认。
- PR：[#114](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/114)，测试 head `5df7ca5`；CI run `39702521767` conclusion `success`，并已于 `386b46f` 合入 `main`。Python 3.10/3.11/3.12、security、docs、CLI、flow、GitNexus、Windows native、benchmark jobs 均通过。

## 2026-10-21 — Gravitas implementation

- Branch/base：`codex/gravitas-implementation` from `origin/main@c662746`，该基线包含已合并的 PR #111。
- Scope：G00–G09；G00–G09 均已按阶段提交，PR [#112](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/112) 已提交并保持开放。G07 code 为 `bfb1fa2`，G08 code 为 `b78c72e`，G09 code 为 `ddb1c53`；CI follow-up 为 `67f33a1`、`4d0831c`、`06be191`、`2bfb362`。
- Commits：G00 `709a4b4`（默认 provider gate）、`82f377d`（flow manifest）、`88de58c`（waiter cancellation）、`f03eb0f`（清理水位）；G01 `dbcbe41`；G02 `8e87c6c`；G03a `dd8bb72`、G03b `6c625f9`、G03c `351878d`；G04a `c3d4c4d`；G04b `6458764`（域内期限传播）；G04c `8160289`（最终发送围栏）、`5b87efa`（非合作发送隔离）；G05 `e7ee716`；G06 code `21fb77f`；G07 code `bfb1fa2`；G08 code `b78c72e`。
- G00 evidence：隔离组合回归 78 passed；Ruff 和 message-flow check 通过。缺失、NULL、零、负数、非法文本与越界 checkpoint 的清理负例均已落入正式测试。
- G01 evidence：定向合同、发布布局与 flow 回归 65 passed；Ruff、flow check、文档门禁通过（119 files / 1237 links / 577 anchors / 0 errors）。Python 3.10/3.11/3.12 导入通过；Standalone Python zip 与 OneClick Python staging 均含可导入 gravitas 包及配置样例。
- G03 evidence：G03a 有界公平票据队列；G03b 将生产模型调用迁入共享 executor；G03c 完成实际端点资源交接、adaptive request 新票据、每业务调用最多 3 次真实请求和脚本路径审计。当前综合回归 446 passed；变更文件 Ruff、Python 编译、flow 清单生成/检查通过。命令和影响证据见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- G04a evidence：可信 QQ 群/私聊、proactive 与 WebChat 入口在可阻塞预处理前创建总 Deadline；`ChatContext` 运行时传递且不进入 projection；Facade 保留旧生成 deadline 并叠加总剩余时间，默认 provider 与 TurnService 收到同一 deadline。定向回归 77 passed / 1 fixture warning；全仓 Ruff、编译、文档、flow manifest 和 diff 检查通过。提交前 GitNexus all 15 files/39 symbols/24 processes/CRITICAL，compare main 451/774/67/CRITICAL（累计）。详见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- G04b evidence：独立 `DeadlineExceeded` 控制信号贯穿 WebChat/Facade 锁、prepare（Planner/Router/工具 fanout）、模型队列/生成和所有 finalize 路径；旧生成 cap 仍保留超时兜底，total deadline 到期不会转成 provider fallback。QQ 群聊/私聊/proactive 静默结束。定向回归 470 passed / 1 warning；全仓 Ruff、py_compile、文档门禁和 flow manifest 检查通过。最终 manifest 为 `message-flow.c36cccb0c356.json`。GitNexus 1.6.11 all 11/33/34/CRITICAL，compare main 454/785/70/CRITICAL（累计）；一次 partial all 已重跑，图覆盖限制与完整结果见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- G04c evidence：`deliver_lines` 在各段间隔和 callback/物理分片前受同一总 Deadline 约束。未开始就过期的段不发送；已开始后超时或取消则记 `unknown`、停止后续段；不合作 callback 留作隔离任务，同会话后续发送被围栏，活动 callback 总数上限 16。QQ 普通群/私聊、Cometa ACK、主动 @/群聊六个发送入口传递 ctx deadline。WebChat HTTP 路由与 `run_turn` 共用 120 秒 deadline，覆盖输出采集和 SSE complete 帧前检查。综合回归 517 passed / 1 existing NoneBot fixture warning；全仓 Ruff、py_compile、文档门禁（119 files / 1,241 links / 577 anchors / 0 errors）和 flow 检查通过。最终归档 `message-flow.c00e93615f8b.json`（141 nodes / 139 source-resolved / 9,489 closure sites / 14,108 reachable symbols）。GitNexus 当前索引更新至 `8160289`；发送代码提交前 all 10 files / 40 symbols / 15 processes / HIGH，compare main 464 / 840 / 72 / CRITICAL cumulative（当时 scope=all 也含未提交的 G04c 状态更新）。代码提交 `8160289`、`5b87efa`；真实模型、QQ/WebChat live、跨进程恢复、clean VM 与发布验收未完成，整体保持 NOT READY。详见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- G05 evidence：提交 `e7ee716` 完成压力滞回、单个恢复 token、防惊群、按 backlog 行数/年龄拒采、无正文缺口账本，以及 consolidation/Compact/proactive 准入检查；配置阈值为离线夹具起点，enforce 仍因覆盖门禁保持 shadow。定向组合回归 216 passed / 1 现有 NoneBot warning；全量 Python 回归在新隔离 `STELLA_HOME` 下 3968 passed / 29 skipped / 1 现有 pytest warning（355s）。全仓 Ruff、改动 Python 编译、文档门禁（119 files / 1,241 links / 577 anchors / 0 errors）、flow `--check` 与 diff 检查通过；归档 `message-flow.b72338474a6c.json`（141 nodes / 139 source-resolved / 9,536 closure sites / 14,275 reachable symbols）。GitNexus all 13 files / 44 symbols / 3 processes / MEDIUM；compare main 469 / 867 / 75 / CRITICAL cumulative，无 partial/truncated。首次全量测试发现的 flow drift、合成包树缺 `gravitas/`、共享临时根造成 WebUI 401 均已修复/隔离后重跑通过。详见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- G06 evidence：代码提交 `21fb77f` 提供缓存只读状态 API、脱敏 fact/age/criteria/version/ack、deploy/CLI/Dashboard 展示和 flow catalog/inventory 节点；不会触发 tick、probe 或改变 shadow/enforce 决策。隔离 Python 回归 97 passed / 1 现有 pytest warning；Dashboard typecheck 通过、7 files / 101 tests passed、build 成功；localhost fake API 浏览器验收通过。全仓 Ruff、改动 Python 编译与 flow check 通过，归档 `message-flow.d2b36de1444a.json`（144 nodes / 142 source-resolved / 9,637 closure sites / 14,346 reachable symbols）。代码门禁 GitNexus all 16/40/2/MEDIUM；compare main 484/938/69/CRITICAL cumulative；状态记录门禁 all 4/7/0/LOW、compare main 489/982/78/CRITICAL cumulative，均无 partial/truncated。`check_docs.py` 119 files / 1,244 links / 577 anchors / 0 errors。pnpm wrapper 依赖预检因 ERR_PNPM_IGNORED_BUILDS 阻断，直接运行已安装 typecheck/test/build 入口成功；没有改 build approvals。未连接真实模型/Bot/平台；无生产数据库、clean VM 或发布验收。详见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- G07 evidence：`bfb1fa2` 增加 S01–S12 场景 runner、10 个连续固定 seed×256 步 off/shadow 状态轨迹、重复语义 digest 和 Standalone/OneClick staged import；CI 在 Python 3.11 运行并上传离线报告。定向守卫 4 passed；全量 Python suite **3976 passed / 29 skipped / 1 existing warning（359.95s）**。离线评测所有 S01–S12、seed trace、包 import、same-seed digest 均 PASS，digest `6d35e75631c1861239cb4ac2cd8555a8e6a5058e`；live/clean VM 明确 SKIPPED。Ruff、py_compile、flow、docs、YAML parse 与 diff 检查通过。详见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- G08 evidence：代码提交 `b78c72e` 增加进程内 endpoint/provider/connection/storage recovery registry、代际围栏、single-flight probe lease 与双层预算；接入模型调用、CapabilityProvider、CaptureGate、OneBot LinkMonitor 和六个 SQLite 域。授权/配置类错误终止重试，SQLite contention 不误报 corruption，存储只由显式维护成功恢复。定向隔离回归 60 passed；最终全量 **3989 passed / 29 skipped / 1 existing warning（220.82s）**。全仓 Ruff、改动文件 py_compile、flow、文档门禁（119 files / 1246 links / 577 anchors / 0 errors）和 diff 检查通过，归档 `message-flow.643390a24eac.json`。中间全量运行曾有两个独立失败，单例重跑通过，第四次全量通过；原因未确认，作为间歇性稳定性风险保留。GitNexus all 13/47/31/CRITICAL；compare/main 503/1076/113/CRITICAL cumulative，compare 清单仍 capped、统计与风险覆盖完整。S13/S14 为本地隔离软件回归；无真实模型、Bot、平台、用户数据库、跨进程 worker、clean VM 或发布验收。详见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- G09 evidence：代码提交 `ddb1c53` 实现原子策略文件/ACK、worker 身份与配置绑定、TTL/replay/墙钟围栏、只暂停新 claim、默认关闭的授权自动重启与有限预算；含真实 OS 子进程暂停 claim、硬杀后 owner lease 到期并由新身份 worker 接任的回归。G09→WebUI Cometa 同进程定向序列 56 passed。一次本地全量 pytest 为 **3942 passed / 22 skipped / 1 failed / 1 warning（226.97s）**：既有 WebUI Cometa empty-key 用例预期 400、实际 401；不将本地结果记作通过。全仓 Ruff、py_compile、文档门禁（119/1248/577/0）、flow 与 diff 检查通过。生产模型/平台、跨进程 live、clean VM、安装器与发布验收未执行，整体产品仍 NOT READY。
- Hosted CI follow-up：Python 3.10 曾因测试捕获异常类型不兼容失败，`4d0831c` 修正为 `asyncio.TimeoutError`；Python 3.11 曾暴露取消用例的 200ms 总期限竞态，`06be191` 改成 provider 启动事件同步；run `39628116553` 再暴露 shared CHAT gate 用例的 1 秒轮询窗口竞争，`2bfb362` 改为事件同步首个 provider、最多观察 10 秒并显露提前失败的原异常。本机 xdist 4 workers 下 `tests/runtime/test_facade_turns.py` **13 passed**。最终 run `39629392684` 在 `2bfb362` 上 Python 3.10 **4,016 passed / 29 skipped / 3 warnings**、3.11 **4,016 passed / 29 skipped / 4 warnings**、3.12 **4,016 passed / 29 skipped / 5 warnings**；3.11 G07 S01–S12、package layout/import 均 PASS。Dashboard `39629392742`、Docker `39629392600` 和所有其他 CI job 通过。PR #112 留待 review/merge。
- GitNexus：编辑前索引已刷新于 G06 状态提交 `d3499a8`；G03c 具体影响包含 `execute_model_call` CRITICAL（8 直接调用者、6 流程、11 模块），RoleBackend MEDIUM，探针函数 LOW；两个评估脚本文件 UNKNOWN/0 边并已按源码补证。G07 新 runner symbols 与 `.github/workflows/ci.yml` 为 UNKNOWN/未索引，`rg` 确认调用仅在新增守卫测试/runner 和 Python 3.11 CI 步骤；提交前 all 4 files、无索引 symbol overlap（不视为 clean/LOW）；compare main 493/984/78/CRITICAL 累计，均无 partial/truncated。完整证据见实施报告。
- Deviation：`execute_model_call` 的 exact impact（CRITICAL），以及两个评估脚本函数的 exact impact（LOW）均在首次编辑后才补跑。已扩大源码审计、补充透明录制包装和回归并向用户说明；不能把后续覆盖或低 File 风险当作事前豁免。
- Blockers：G07 离线验收无未解决代码阻塞；enforce 仍被覆盖门禁拒绝。真实模型、QQ/WebChat 灰度、Cometa 跨进程 live、干净 VM、实际 installer 和发布验收尚未完成，不能由本地回归或包布局 smoke 替代。
- Next：review 并合并 PR #112；之后在有授权平台账号与干净环境时补真实模型/QQ/WebChat 灰度、生产跨进程恢复、clean VM、安装器与发布验收。整体保持 NOT READY。
- Files：G08 主模块 `gravitas/dependency_recovery.py`、定向测试 `tests/gravitas/test_g08_dependency_recovery.py` 与 flow archive；G07 runner `scripts/run_gravitas_evaluation.py`、场景矩阵 `tests/gravitas/fixtures/v1/suite.json`、Python CI `.github/workflows/ci.yml`；证据见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。

## 2026-10-21 — Gravitas engineering planning

- Files：[工程方案](docs/plans/2026-10-21-gravitas-engineering-plan.md)、[机器清单](docs/plans/2026-10-21-gravitas-inventory.json)、[证据](docs/reports/evidence/gravitas-20261021/README.md)。V1 G00–G07 闭合资源压力/期限/取消/记忆边界；V2 G08/G09 处理依赖和 Cometa 跨进程恢复。
- Evidence：GitNexus 1.6.12 索引 Function 身份异常后，单 worker / 无 embedding 全量重解析修复；八类 query、十六组 context/upstream impact、823 流程分页与 50 声明入口补证。候选源码 73 文件/41 调用点；10 工作包/10 不变量/16 场景。acquire CRITICAL，Compact/deliver_lines HIGH；UNKNOWN 保留源码接线补证。
- Baseline：隔离定向 83 passed/2 warnings；清理器既有测试 16 passed。三个合成探针确认默认 Facade 绕过调度、取消 waiter 计数滞留、checkpoint=0 清理删除未整合行，尚未修复。原始用户库、Bot、模型和平台未访问。
- Blockers：方案不受 live 缺口阻塞；业务实现、生产阈值、模型/QQ/WebChat/VM/发布仍 NOT READY。原 XPLAT-IMPL 状态与验收缺口保持，不开启第二个 in_progress 实施任务。
- Gates：check_docs 与档案验证器、指纹/证据 SHA256、diff 检查通过；GitNexus all LOW，compare/main 累计 CRITICAL。compare 的固定 1000-symbol 展示上限经临时只扩展示清单的 harness 完整重跑，原始统计/风险一致且无 partial/truncated。最终记录见证据目录。
- Next：方案已完成，仅在后续实施任务执行 G00；先重新绑定目标 HEAD 和 upstream impact，再把三项探针转成正式回归并修复。不得直接启用 enforce。

## 2026-10-20 — GitNexus / Cross-platform planning

- 基线索引：1,249文件、95,747节点、236,981关系、829推断流程；启用PDG，保留流程预算、动态调用和跨语言缺边限制。
- 独立入口核验：50声明入口/9流程族，34注册扫描结果，双向差集为空。
- 工程方案：12依赖工作包；32适配器分母；180候选文件；包含身份、权限、迁移、双后端、投递恢复、插件、控制面、部署与验收。
- 本轮只交付计划与工具/文档；平台fixture/live、迁移、业务测试与发布均未执行。后续应从WP00开始，不能把计划完成当实施完成。
- 文档/清单一致性、源代码零修改与影响检查已通过；索引状态和最终刷新记录见本地 `.gitnexus/verification/`，持久证据见报告目录。`detect_changes`仅覆盖3个已跟踪状态文件，新文档/证据另行完整验证。

## 2026-10-20 — Cross-platform implementation (WP00)

- 已从 `ba582a9` 建立 `codex/cross-platform-implementation`；规划阶段已有的计划、证据与状态修改保留在本分支。
- 数据边界：本机 `STELLA_HOME` 未设置；回归夹具把库与空间配置放进 pytest 临时目录。未启动 Bot、未读取或迁移用户库。
- 冻结候选组合：NoneBot 2.5.0、Alconna 0.62.1、Uninfo 0.11.2；官方包元数据声明均支持 Python >=3.10，`uv pip compile` 对 3.10/3.11/3.12 解析通过，三个版本运行时 import smoke 通过。
- 基线：会话身份/注册表/用户隔离 79 passed；QQ/WebChat 入口/上下文 32 passed；采集门/入站限制 31 passed；文档门禁 119 files / 1199 links / 577 anchors / 0 errors。
- WP00 完成：平台桥接依赖设为显式可选 extra，并生成跨 Python 的锁；现有回归向量作为 QQ/WebChat 冻结基线。锁定依赖解析与 3.10/3.11/3.12 导入烟测通过；定向回归 142 passed；文档/JSON/diff 检查通过。下一步 WP01。
- 影响基线已按 UID 精确核对：`conversation_key` CRITICAL（14 impacted、6 direct、4 flows、5 modules）；`ConversationRef.conversation_key` UNKNOWN/0 edges；`get_or_register_group` UNKNOWN/0 callers，源码引用仅定义与测试；`scope_for_chat_context` HIGH/5 impacted；`record_message` CRITICAL/18 lower-bound，3 个未解析接收者。

## 2026-10-21 — Cross-platform implementation (WP01)

- GitNexus 1.6.11 刷新绑定 `edb8a3d`，status up-to-date、content current、覆盖 1,394 个文件（96,237 nodes / 237,994 edges / 1,012 clusters / 829 flows）。流程入口/分支截断、32 候选上限和跨语言属性缺边仍按计划限制处理。
- 影响证据：旧 `lookup` 为 CRITICAL（10 impacted / 4 direct / 4 flows）；registry schema helper HIGH（22 / 3）；负数分配器 HIGH（7 / 3）；旧 `conversation_key` 函数 CRITICAL（14 / 6 / 4 flows / 5 modules），同名属性 UNKNOWN。文本核查发现维护工具直接读旧表，故 V2 使用独立表；`register_conversation_v2` 尚无生产调用者，留待后续入口包接线。
- 完成 transport identity/key codecs 与 `conversation_registry_v2`、可歧义 alias 映射；V2 / V1 负数存储号在事务中统一扫描，旧 QQ/WebChat 读写 API 和表布局保持独立。未扩展 QQ-only 的整数空间配置；generic 会话默认 `transport:<canonical_key>` 独占空间，避免隐式共享。
- 环境边界：`STELLA_HOME` 未设置；pytest 使用临时数据库和空间配置；未启动 Bot、未访问或迁移生产库。
- 验收：身份/注册表及 QQ/WebChat 相关测试 **160 passed**，message-flow 合同测试 **14 passed**；改动 Python Ruff 通过；文档门禁 119 文件 / 1204 链接 / 577 锚点 / 0 errors；message-flow 清单已重生成，拓扑未变，`--check` 通过。暂存后 GitNexus `scope=all` 为 13 个文件 / 83 symbols / low；compare main 为 156 文件 / 111 symbols / low，无 partial/truncated。
- 阶段提交：`ea79171`（`feat(transport): add V2 identity registry (WP01)`）。下一阶段 WP02。
- 细节与命令见[WP01实施记录](docs/reports/2026-10-21-wp01-identity-registry.md)。

## 2026-10-21 — Cross-platform implementation (WP02)

- 实现提交 `8ab18ce`：ChatContext projection v7（安全读取 v6）、conversation projection v2、opaque message IDs 与旧 QQ INTEGER codec 分离；reply envelope schema 2 使用绑定 turn / identity revision / generation epoch 的 `target_ref`。
- GitNexus 编辑前：`parse_platform_message_id` CRITICAL/22 impacted/7 flows；reply envelope 两解析锚点 HIGH；`_extract_reply_candidate` HIGH/4 impacted/3 flows；UNKNOWN 的 reset/parser hook 已文本审计。提交前 scope all 31 files/121 symbols/21 processes/critical；compare main 187 files/232 symbols/21 processes/critical，完整重跑无 partial/truncated。
- 定向回归 310 passed；Ruff、`generate_message_flow.py --check` 与暂存 diff check 通过。全量 Python：3782 passed/29 skipped/4 failed，失败项为 Cometa stale lease、两项 WebUI Cometa 401、WebUI chat history TypeError；详见 WP02 报告，保留 NOT READY。
- `STELLA_HOME` 未设置，pytest 临时隔离；未启动 Bot、未读写生产库。无 live 模型/平台、QQ 灰度或 clean VM 验收。
- 下一阶段 WP03：刷新索引并先查 schema 20→21、migrations、Python/native backend 与 API 4 wheel 合同的 upstream impact；仅用临时旧库副本验证迁移。

## 2026-10-21 — Cross-platform implementation (WP03)

- 实现提交 `ec5cf65`：schema 21 新增 `platform_message_id` 与 `subject_key`；迁移仅从旧非零 INTEGER `msg_id` 保守复制平台回执，不猜历史主体；Python/native 检索合同升至 API 4 / schema 21，外部用户 ID 作为字符串传入。
- 修正 flow manifest 检查，使其在所有不可变归档中查找当前源码匹配项；fullchain 验证改为走生产 evidence 写入路径，并检查双方晋升、冲突观察、提交事实和 trace integrity。
- 定向 pytest 77 passed / 1 skipped；Rust 25 passed；隔离 release wheel 报告 API 4 / schema 21，fullchain PASS；embedding benchmark 101/101 质量与 parity 通过。Rule benchmark 两后端一致但共享一个既有 expected-ranking mismatch（100/101）。
- Ruff、文档门禁（119 files / 1206 links / 577 anchors / 0 errors）、flow manifest 与 diff 检查通过。全量 pytest 因 `tests/cometa/test_worker.py::TestSingleOwner::test_second_worker_rejected` 451.87 秒无进展而中止（876 passed / 7 skipped）；单测 30 秒重现，集成门禁 NOT READY。WP02 已报告的其他全量失败也未关闭。
- `STELLA_HOME` 未设置；仅使用临时 SQLite 和隔离 wheel；未启动 Bot、访问生产库或运行真实模型/平台。
- 阶段实现提交 `ec5cf65`；具体命令、GitNexus 风险、限制及下一步见 [WP03 实施记录](docs/reports/2026-10-21-wp03-storage-backend.md)。下一阶段 WP04。

## 2026-10-21 — Cross-platform implementation (WP04)

- GitNexus 编辑前 upstream impact 覆盖 owner scope、evidence source、retrieval、sharing、addressing、social schema/store、knowledge ACL/schema、proactive target 与 memory manager。原始风险含 `knowledge.acl.resolve_role` CRITICAL（23 impacted / 3 direct / 7 KB flows）、`ensure_social_schema` CRITICAL（47 / 2）；ownership/retrieval/evidence/sharing/addressing 等多个 HIGH。UNKNOWN 的 `ConversationScope.from_context` 用 `rg` 补查，确认生产调用来自 `core/social/context_builder.py`；类级影响 MEDIUM（21 / 11）。
- 实施提交 `eabec23`：PERSON owner、检索与证据核验以 `connection_id + subject_key` 隔离；旧 evidence 版本仍可验证；分享 grant/revoke、地址偏好、社交学习与 KB owner/grant ACL 增加显式身份域。memory/native schema 21→22，social schema 4，KB schema 2；旧 sharing 授权行迁移时复制保留，历史 connection 为空不猜映射。重新生成最终 message-flow archive。
- 回归：记忆/权限组 135 passed；knowledge 与 social 学习/迁移组 203 passed；retrieval/proactive 补充组 45 passed（测试组有重叠，不汇总相加）；Python native selector/promotion/benchmark 29 passed / 1 skipped；Rust cargo 25 passed。Ruff、文档 119 files / 1209 links / 577 anchors / 0 errors、flow check、`git diff --check`、cargo fmt 通过；隔离 native wheel 报告 API 4 / schema 22。
- GitNexus 提交前摘要：scope all 49 files / 215 symbols / 48 processes / CRITICAL；compare main 241 files / 496 symbols / 71 processes / CRITICAL（包含 WP00–WP03）。CLI 显示的名字列表有省略，摘要统计保留；图谱刷新至 `eabec23` 后继续维护状态文档。
- 状态文档提交前复查：GitNexus all/compare 均运行成功，原始风险为 CRITICAL；索引把文档章节关联到大量流程，原始风险照录。新报告/JSON 状态文件用 diff、文档链接与 JSON 解析门禁补证。
- `STELLA_HOME` 未设置；只使用临时测试数据，未读取/迁移生产库，未启动 Bot、真实模型或平台。全量 Python 与 live/发布认证尚未完成，整体 NOT READY；下一阶段 WP05。

## 2026-10-21 — Cross-platform implementation (WP05)

- 实现提交 `28b296c`：新增 `NormalizedEvent` / `UnsupportedEvent`、OneBot v11 与通用 NoneBot normalizer、共享 `AdmissionPolicy`；外部身份和消息 ID 原样字符串化，通用身份按连接域隔离，未知 session 保留 opaque。WebChat 固定管理员 ID 作为身份，用户名只作显示名。
- QQ 群/私聊与 WebChat 上下文携带 BotRef/UserRef/SceneRef；群被动采集与 @ 对话都接入 `get_or_register_group`，使用注册表返回的 storage ID/空间。采集门关闭时被动入口先返回，注册表与内容行均不写。插件入口保留纯消息段唤醒，AstrBot 工具事件构造显式跳过非 OneBot adapter。
- GitNexus 1.6.11 编辑前文件级影响：`ai_gateway.py` HIGH/196 impacted、WebChat ingress CRITICAL/522 impacted；vision LOW/5、capability hook LOW/6。入口 matcher 方法的 UNKNOWN/0 通过 decorator 注册和源码补证；registry 群登记方法原先仅测试调用，本阶段已接入。源码索引基于 `3075d62`，新 normalizer 文件在该索引生成后创建。
- 回归：Normalizer/vision/群私聊/WebChat/capture gate/AstrBot/registry/context/message-flow 相关测试 214 passed；改动 Python Ruff 通过。message-flow 初检发现函数体变化后生成 `message-flow.3631d3d0ca29.json`，后续 `--check` 通过。
- GitNexus 提交前：scope all 14 files/26 symbols/16 processes/CRITICAL；compare main 重跑后 254 files/484 symbols/76 processes/CRITICAL（包含 WP00–WP05）。首次 compare 的 process query 被中断并标 PARTIAL，重跑得到非 PARTIAL 完整摘要；CLI 名称列表仍按固定摘要折叠。
- 状态/报告提交门禁：GitNexus all 5 files/14 symbols/0 processes/LOW；compare 首轮 PARTIAL 后重跑为 255 files/486 symbols/76 processes/CRITICAL。文档检查 119 files / 1213 links / 577 anchors / 0 errors，feature JSON 与 message-flow 检查通过。
- `STELLA_HOME` 未设置；入口测试 DB、群空间和 WebChat home 使用 pytest 临时隔离数据。未读取/迁移用户库，未启动 Bot、真实模型或平台；未运行全量 Python suite，WP02/WP03 历史全量缺陷仍未关闭。线程/频道 adapter、QQ 灰度、clean VM 和发布认证仍待后续阶段，整体 NOT READY；下一阶段 WP06。

## 2026-10-21 — Cross-platform implementation (WP06)

- 实现提交 `d2270d1`：新增 transport-neutral outbound/media/capability contracts、显式 Bot/target 解析、OneBot v11 UniMessage codec、能力降级、长文本拆分及逐物理发送段结果；群/私聊、Cometa ack、主动发送和能力清单统一走 outbound service。
- DeliveryResult 保留 opaque ID 列表和 accepted/partial/failed/unknown 等状态；unknown 不自动重投。social schema 4→5 增加 `platform_message_ids_json`，迁移只包裹旧 primary ID；effects、查询和引用归因消费 ID 列表。
- 编辑前 GitNexus：`deliver_lines` HIGH (10/6/3)、`record_delivery` CRITICAL (12/3/4)、`seal_delivery_plan` CRITICAL (14/3/5)；封存签名/摘要未改。`find_delivery_by_platform_id` UNKNOWN/0，经 `rg` 确认有测试调用。边界见 WP06 报告。
- 定向回归 138 passed / 1 warning；改动 Python Ruff、message-flow check 与 diff check 通过。归档 `message-flow.72cc70e6e149.json` 为 141 nodes / 139 source-resolved / 8,952 closure sites / 11,689 reachable symbols。
- GitNexus 提交前 scope all 21 files/54 symbols/7 processes/HIGH；compare main 264 files/589 symbols/76 processes/CRITICAL，包含 WP00–WP05。状态文档 scope all 7 files/14 symbols/0 processes/LOW；compare main 265 files/591 symbols/76 processes/CRITICAL。
- `STELLA_HOME` 未设置；只用临时测试数据。未运行全量 Python、真实 QQ/其他平台、clean VM 或发布验收；历史全量缺口仍未关闭，整体 NOT READY。下一阶段 WP07。

## 2026-10-21 — Cross-platform implementation (WP07)

- 实现提交 `7bea280`：后台通知和调度任务现在持久化版本化 `DeliveryTarget`、`BotRef`、主体及作用域；投递前要求精确匹配当前 Bot/连接/adapter/platform/self_id，不从模型文本或默认 Bot 推断。Proactive timer 在无 Bot 或多 Bot 歧义时跳过，主动路径以注册表会话键读取/写入上下文。
- Scheduling SQL schema 1→2：新增目标、主体和 scope；仅当旧 Bot 与群 ID 可验证为数字且绑定无歧义时转换旧任务，其他旧任务保持不可发送；旧 quota 行保留在 legacy scope。Cometa Origin JSON 2→3，校验目标与 BotRef 一致；CAS、租约和 unknown 不重投语义保留。
- 编辑前 GitNexus upstream impact 与源码补查见 WP07 报告；高风险 Origin 调用链未扩大其 schema 兼容边界。提交前 GitNexus 1.6.11 scope all：31 files / 162 symbols / 36 flows / CRITICAL；compare main：287 files / 908 symbols / 102 flows / CRITICAL；均未标 partial/truncated。累计 compare 风险包含 WP00–WP07。
- 定向回归：调度/主动与上下文组合 401 passed；Cometa 目录忽略 worker 用例 194 passed / 7 skipped；身份和出站 67 passed。`tests/cometa/test_worker.py` 在全目录命令中运行超过 8 分钟无进展后被中断（此前已记录该用例 30 秒隔离重现挂起），因此全目录/全量 pytest 没有通过声明。改动 Python Ruff、`git diff --check` 与重生成后的 message-flow manifest 检查通过。
- `STELLA_HOME` 未设置；pytest 使用临时隔离数据，未读写生产库或运行真实 Bot/模型/平台。live、发布、clean VM 及 Cometa worker 挂起缺口保留，整体 NOT READY。下一阶段 WP08。

## 2026-10-21 — Cross-platform implementation (WP08)

- 实现提交 `8e3466e`：AstrBot 分发与 capability 工具入口都验证 OneBot v11 Bot；其他 adapter 不进入 QQ API 插件路径。通用 `type/data` 与文本链转换加入兼容层；发送仍明确走 OneBot codec。
- `PlatformAdapterTypeFilter` 按 platform/adapter 名称匹配，不把唯一配置实例 ID 当类型。`Context.send_message` 限定 OneBot 群/私聊，并仅在 Bot 注册表中存在唯一 OneBot 实例时投递；多 OneBot 时 fail closed。
- 编辑前 `build_event` upstream impact 为 HIGH（5 impacted / 2 direct，命中 `handle_plugin` 流程）；其他关键事件、分发、转换与 Context 目标 LOW。filter 图为 UNKNOWN/0 静态调用，已由 pipeline 动态 `.filter()` 调用与装饰器注册源码补证。提交前 GitNexus 1.6.11 all：14 files / 60 symbols / 5 processes / MEDIUM；compare main：300 files / 971 symbols / 107 processes / CRITICAL。固定 `.gitnexus/gn` 启动器通过；仓库 `run.cjs` 指向 1.6.12 且与本地图存储版本不兼容。
- 定向回归 373 passed；Ruff、`check_docs.py`（119 files / 1,223 links / 577 anchors / 0 errors）、message-flow 检查与 `git diff --check` 通过。新增 `message-flow.9b80952673b2.json`（141 nodes / 139 source-resolved / 8,973 closure sites / 11,899 reachable symbols）。
- `STELLA_HOME` 未设置；测试使用临时/fixture 数据，未读写生产库或运行 Bot、真实模型和平台。插件底层 API 仿真不在范围内；QQ 灰度、其他平台 live、发布、clean VM 与全量 Python 验收缺口保留，整体 NOT READY。下一阶段 WP09。

## 2026-10-21 — Cross-platform implementation (WP09)

- 实现提交 `9f75ded`：新增 `STELLA_ADAPTER_MODULES` 与 `adapter_loader`，NoneBot CLI 不再静态预注册适配器；Bot 在 Driver 初始化后、插件加载前按配置顺序注册。默认仍启用 OneBot V11；第三方包需手工安装，缺包、坏模块或 Driver 不兼容时清晰失败。
- `link_monitor` 现按 adapter type + Bot self ID 隔离连接、心跳、探活和告警。只有 OneBot V11 使用 `get_status()`；状态接口增加 `applicable`、opaque `bots` / `connections`，其他平台连接可见而健康为 unknown。`status_api` 保持原样透传结构。
- 编辑前 GitNexus：`link_status` LOW（4 impacted / 2 direct / 2 processes）；status aggregator LOW；装饰器入口 UNKNOWN/0 已按 NoneBot/APScheduler 注册源码和扩展 loader 补证。提交前 all 为 13 files / 59 symbols / 4 processes / MEDIUM；compare main 为 314 files / 1,018 symbols / 106 processes / CRITICAL（累计 WP00–WP09）。一次 compare partial 后串行重跑；最终汇总覆盖全部变更，明细展示有上限。
- 定向回归 73 passed；全仓 Ruff 通过；文档 119 files / 1,224 links / 577 anchors / 0 errors；message-flow `9b80952673b2` 检查通过；真实 NoneBot Driver 的默认注册 smoke 仅初始化 Driver、不运行 Bot，结果为 `OneBot V11`。全量 Python 未跑；WP07 Cometa worker 挂起、真实平台、QQ 灰度、clean VM 与发布验收仍 NOT READY。
- 测试设 `STELLA_HOME=/tmp/stella-wp09-20261021`；未读取或修改本机生产 `.env`、数据库或配置。下一阶段 WP10。
- 细节见[WP09 实施记录](docs/reports/2026-10-21-wp09-adapter-assembly-health.md)。

## 2026-10-21 — Cross-platform implementation (WP10)

- 实现提交 `a20c3a1`：平台页可配置适配器模块列表并展示配置值、生效值和进程覆盖；保留 OneBot 多正向 WS 地址与 token 不回显；平台配置写入受鉴权、审计和 restart_required 契约保护。Doctor 仅在 OneBot V11 未启用时跳过其五项 NapCat 检查；安装器状态页不再把 `applicable=false` 误报为协议端未连接。路由优先于 SPA 的原实现由既有挂载回归锁定。
- 包装器问题在实现提交后复核发现；follow-up `b0cb052` 让 standalone 和 OneClick installer resource staging 都从最终发布树生成 `.stella-manifest.json`。这修正了 allowlist 将隐式元数据漏出包的问题。
- 编辑前 GitNexus：`deploy.probe._probe_onebot` HIGH（10 impacted / 2 direct / 3 processes）；`check_onebot_mode` UNKNOWN/0 通过 `_ALL_CHECKS` 源码注册补证；`platformcfg.onebot` 与 `platformcfg.update` LOW。安装器内嵌 JS 文件影响 UNKNOWN/0，`rg` 确认消费者为本文件 `renderStatus` / `copyDiag`；状态 API 合同已由测试覆盖。包修复前刷新图绑定 `a20c3a1`：`build_standalone` LOW（5 / 2 direct）、`stage_installer_resources` MEDIUM（15 / 12 direct）、`write_manifest` LOW（2）。
- GitNexus 阶段门禁：实现批次 all 16 files / 47 symbols / 8 processes / HIGH；包 follow-up all 2 files / 4 symbols / 0 processes / LOW。against-main 比较为 WP00–WP10 累计 333 files / 1,122 symbols / 106 processes / CRITICAL，重跑后无 partial；符号列表明确 capped。图已刷新并绑定 `b0cb052`；WP11 开始前会检查状态提交后的索引新鲜度。图分析记录仍包括 20 个大文件跳过、动态/跨语言属性边缺失、entry-point ranking/trace budget/branching 截断。
- 状态证据提交前：文档门禁 119 files / 1,228 links / 577 anchors / 0 errors，JSON 与 staged diff 检查通过；GitNexus 状态 scope all 为 4 files / 11 symbols / LOW，compare main 为 334 files / 1,128 symbols / 106 processes / CRITICAL（累计；符号列表 capped）。
- 回归：一组 Deploy/运行时/状态/WebUI 定向回归 **253 passed**；`test_platform_adapters.py` 后续更新后 **4 passed**；产品包测试 **18 passed**。全仓 Ruff 通过；文档门禁 119 files / 1,225 links / 577 anchors / 0 errors；message-flow `9b80952673b2` 检查通过。
- Dashboard 使用 Codex bundled Node 执行 `vue-tsc --noEmit` 通过、Vitest **100 passed**、Vite production build 通过；产物有 dynamic-import 和 >500 KB chunk 警告。`run.html` 内嵌脚本 `node --check` 通过。pnpm wrapper 因本机 pnpm 11 把旧 `onlyBuiltDependencies` 配置视为 ignored build scripts 而失败；未批准额外脚本，使用已安装包的直接 Node 门禁完成验证，安装意外写入的 workspace 审批提示已还原。
- 发布验证：standalone Python zip 已由 builder 生成并通过 `check_release_archive.py`；Standalone staging 与 OneClick resource staging 均通过 `check_release_layout.py`，其中含新 manifest、adapter loader、webui/dist 和 desktop/dashboard-dist。`pyproject.toml` 仍不静态预注册 adapter，OneBot 默认依赖仍在 `requirements.txt`。
- 隔离：测试/构建使用 `STELLA_HOME=/tmp/stella-wp10-20261021` 与临时发布目录；本阶段未运行 Bot、读取生产库、连接模型或平台。非 OneBot live、全量 Python、QQ 灰度、clean VM 和真实 Release 仍 NOT READY。下一步 WP11。
- 细节见[WP10 实施记录](docs/reports/2026-10-21-wp10-control-plane-delivery.md)。

## 2026-10-21 — Cross-platform implementation (WP11)

- 新增 `tests/platforms/adapter_matrix.json`：固定官方快照 32 项分母，逐项保留包版本/Python 范围、driver、组件、场景、权限、窗口、限流、维护状态和 L0–L3 local/fixture/live 状态。隔离 `.venv` 只观察到 OneBot V11/V12 共用发行包 `nonebot-adapter-onebot 2.4.6`（Requires-Python `>=3.9,<4.0`）；其余 30 个适配器包未安装。未知字段不推断，32 项均未认证。
- 新增 `tests/platforms/test_adapter_matrix.py`：逐行对照冻结 inventory，并以真实 OneBot `GroupMessageEvent` 构造入站事件，验证同一 Bot/群目标经 fake `UniMessage` transport 回投。定向平台/Normalizer/Outbound 回归 **18 passed**。
- 初始全量运行 3873 passed / 29 skipped / 6 failed；后续修复记忆 evidence source key、WebUI scheduling 的显式 Bot 目标，并修复 Cometa worker 关闭时的注册重试和相关测试隔离。CI xdist 全量复跑现为 **3879 passed / 29 skipped / 5 warnings**（112.76 秒），6 项初始失败均已关闭。记忆定向 27 passed、调度 service 176 passed、WebUI manage 12 + route 1 passed、worker 6 passed。
- Dashboard direct Vitest 100 passed、`vue-tsc --noEmit` 通过、Vite build 成功（既有导入/大 chunk 警告）；全仓 Ruff 和 message-flow 检查通过。三个修复阶段提交为 `1f5c900`、`54c4d4c`、`7f35347`。本地 Python 回归不替代真实平台、QQ 灰度和发布验收。
- GitNexus 1.6.11 刷新绑定 `22ce1d0`；提交前 all 为 5 tracked files / 15 symbols / LOW。compare main 首轮 partial 后串行重跑完整：336 files / 1,140 symbols / 106 processes / CRITICAL，无 partial/truncated（符号列表 capped）。
- 真实平台/QQ灰度、L2完整链、L3完整能力、多账号 live 恢复、Python 3.10/3.11 独立运行与 Linux/Windows clean VM 未执行；32 项平台仍均未认证。
- PR #111 CI 修复分两阶段提交：`e622c7a` 让三版本测试 job 安装包含基础与可选 Alconna/Uninfo 平台桥接依赖的 `requirements-platform.lock`，并同步缓存键和中英文 CI 指南；`97a2ea9` 修正 Cometa ack 测试把瞬态 `SENDING` 误当完成态的轮询竞态。
- 本地验证：平台锁 dry-run 检查 95 个包、无需更改；平台失败相关测试 22 passed / 1 warning；Cometa runtime assembly 3 passed；文档检查 119 files / 1,234 links / 577 anchors / 0 errors。最终 PR CI run `39557774555` 全绿：Python 3.10/3.11/3.12 各 3,879 passed / 29 skipped，其他 CI、Dashboard 和 Docker build/push jobs 全部通过。

## What's Done

- 回复协议修复（fix/reply-envelope-multicurrent，自 a4aa233 切出）：诊断与修复详情见 [修复报告](docs/reports/2026-10-16-reply-envelope-multicurrent-fallback-fix.md)。`core/dialogue_attribution.py` 两处改动；`tests/test_dialogue_attribution_repair.py` 新增 4 例并改 2 处旧断言；P2 oracle 按 952007e 流程修订 7 个夹具并在 manifest 记录 `current_slot_prompt_revision`。
- 验收：定向 pytest 59+37+187 passed；引用受影响模块的全部测试文件通过；ruff 通过；`python scripts/check_docs.py` 通过（119 文件/1191 链接）。GitNexus 本机注册表损坏不可用，影响面以 rg 兜底清点并记录于报告 §3。
- 未做：真实 QQ 灰度观测（需重启 bot 进程加载新解析器与提示词）；嵌套 `<reply>` 畸形态仍走澄清兜底（提示词已明示禁止，发生率待观察）。
- CI 补录：PR #109 首推两失败（flow-manifest 漂移 + TestDriftGate，同根因=改插桩源码未重生成 manifest），已重生成（6757c542d9db→3eb7f47d8f7f，语义 diff 为空）并推送；CI 全量 3728 项无其他回归。

- CI-106：PR #106 的 flow-closure 在 `npx -y gitnexus@1.6.11 analyze --index-only` 崩溃（`malloc(): unaligned tcache chunk detected`），后续 inventory 门禁因前序失败被跳过。
- 修复候选已在本地工作树：CI analyzer 加 `--workers 1`，新静态测试锁定命令与两个独立 inventory/reconciliation 步骤。Pinned npm analyzer 单 worker 在容器中成功；41 个 flow 定向测试通过；两条 CI 等价检查通过；跟踪 Python Ruff、docs 检查通过；`git diff --check` 通过。
- GitNexus scope=all：最终为 5 文件/12 符号/low；与 PR base `origin/main@f4d6247` 比较 18 文件/35 符号/low，无 partial/truncated。后者包含既有 6.2.0 变更、本地 release 状态记录和本修复。
- 修复提交 `c22dcecdde227564cecd6a7290f246ae43ba3efa` 已推送至 PR #106；hosted CI run 38357443346 全部检查通过，flow-closure analyzer、runtime inventory 与 discovered-entry reconciliation 均成功。Docker Publish run 38357443338 也成功。
- 本修复只增加 GitNexus `--workers 1` 和对应 workflow contract test；`v6.2.0` tag 未移动，仍指向已发布 commit `6c62fdc`。原有未跟踪用户资料未修改、未暂存。

- RELEASE-620：线上 main@f4d6247 已包含本地 topic 的所有工作；从该提交创建 `codex/release-6.2.0`。
- 已将 pyproject、CLI/桌面 Cargo 元数据和 lock、Tauri 配置同步至 6.2.0；更新双语 README、合同说明、迁移模板与发布说明。
- 发布 notes 明确 schema 18→19、Rust API 2→3、旧 evidence 的 `legacy_unverified` 迁移、native wheel 兼容要求及 QQ/Rust/VM 验收边界。
- 本地门禁：pytest 3669 passed/17 skipped；跟踪 Python Ruff 通过；Dashboard 100 tests/typecheck/build 通过；CLI fmt/clippy/20 tests 与 desktop cargo check 通过；文档、message-flow、版本一致性通过。
- 全仓 Ruff 仍被原有未跟踪 `docs/reports/evidence/dialogue-attribution-20261008/guard_probe.py` 的 I001 阻挡；未修改该用户文件。GitNexus scope=all：16 文件、33 符号、low，无 partial/truncated；upstream 版本读取路径曾报 HIGH，直接调用与打包消费者已检查。
- 已推送 `v6.2.0`，Release 于 2026-10-13 正式发布：https://github.com/Eternal-Wanderer-Vegetable/Stella_project/releases/tag/v6.2.0（14 项资产）。GitHub Actions run 38332591325 全部 jobs 成功，含四种 OneClick 安装验收、manifest/SHA-256 和发布后回读。
- 发布页注明安装器按维护者授权的 `STELLA_ALLOW_UNSIGNED=1` 例外未签名；clean-VM/GUI 首启与真实 QQ 灰度仍未完成，不能由 hosted 安装验收替代。

- 58 份双语正文按主题归类；架构和开发长文拆分；28 个原路径和 577 个原章节锚点保留。
- AGENTS 为 45 行任务入口，CLAUDE 引用共同规则；专题标明来源和复审条件。
- 当前源码合同与发布快照区分，补齐 CI 与数据目录优先级说明。
- 建立任务状态、Windows/Git Bash 初始化、文档 CI 门禁；根状态文件排除出发布包。

## Verification Evidence

- `python scripts/check_docs.py`：通过；路径、双语、迁移锚点和状态检查无错误。
- 独立 unittest 6/6；新增 Python 文件 Ruff 通过；`git diff --check` 通过。
- 246 个迁移前历史文件 SHA256 完全一致，原章节锚点集合无缺失。
- PowerShell/Git Bash docs 模式通过；非法模式退出码 1/2，空仓库文档检查退出码 1。
- GitNexus scope=all：120 文件/859 符号，low；用独立 index 纳入本轮 83 个新增文件，真实 index 未改。
- harness-creator：28/100 → 100/100，仅结构评分。详见 [整理报告](docs/reports/2026-10-10-documentation-restructure.md)。

## Files

- AGENTS/CLAUDE、README、docs 分类正文/兼容入口/映射、Agent 专题、根状态三文件。
- scripts/check_docs.py、tests/documentation、init.ps1/init.sh、CI 和 release 排除项。

## Blockers / Risks

- 本次文档验收已完成。模型、QQ、native parity、VM/GUI 与实际 Agent 会话效果仍需各自证据，不在本次结论中关闭。
- 保留原有未跟踪技能、日志、计划、报告、证据及 native 备份，不纳入本轮提交。用户已审核文档重整并授权提交上传，最终提交与远端状态以 Git 记录为准。

## What's Next

1. CI-106 已完成并通过 PR #106 hosted checks；修复提交为 `c22dcecdde227564cecd6a7290f246ae43ba3efa`。
2. RELEASE-620 已完成；版本提交 `6c62fdc3f7ae010896f7f308e37f356eb3c20581`，tag 与稳定 Release 已发布。
2. RELEASE-620 已完成；版本提交 `6c62fdc3f7ae010896f7f308e37f356eb3c20581`，tag 与稳定 Release 已发布。
3. 真实 QQ 灰度、clean-VM/GUI 首启和未签名安装提示仍按各自流程验收；不得将 GitHub-hosted 安装验收扩大为这些结论。

## PR #105 CI Repair — 2026-10-10

- CI-001 done；scope：闭包预算、生成清单、回归与在线 CI。
- 基线 f8b2dce；本地复现两项合同失败：manifest 漂移、四个 ingress 截断。
- record_group_chat 实际闭包 257 个辅助符号，旧上限 256；显式 cap=512 完整展开。
- 修复：默认 cap 256 → 512，保留小预算截断与零核心截断门禁；按仓库惯例替换随包清单。
- 验证：40 项专项通过；全量 Python 3669 passed / 17 skipped（Windows Python 3.14、隔离 STELLA_HOME）；623 个已跟踪 Python 文件 Ruff 通过；清单漂移、文档门禁通过。
- 修复提交：3b31931，已推送 PR #105；[主 CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38043343651) 全部 11 项通过，[Dashboard CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38043343680) 通过。
- 提交前 GitNexus：6 文件、11 符号、low，无 partial/truncated；提交后索引刷新到修复提交并保留 PDG。
- CI-001 验收完成。完成记录的后续提交与 CI 以 Git／PR 最新状态为准；新任务由用户授权。

### Final-head Dashboard follow-up

- 2906569 的 Dashboard CI 暴露既有大数据功能用例超时（5.17s > 默认 5s）；原修复提交的主 CI 与 Dashboard 全部通过记录仍有效。
- 保留 100 页／100000 事件、全部水位断言、性能专项预算；仅该功能用例超时设为 15s。
- c7751f6 已修复该超时；本地 Dashboard 100 项测试、类型检查、生产构建通过。
- [主 CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38044052769) 全部 11 项通过，[Dashboard CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38044052792) 通过；CI-001 done，无活动任务。
- 完成记录提交的最终 SHA／检查结果以 Git 和 PR 最新状态为准。

## AI-Gated Memory Capture — 2026-10-16

- 分支 `feat/ai-gated-memory-capture`（基于 `codex/release-6.2.0` @ `c22dcec`），6 提交：`3db81e7`（M1+M2 门模块+探针+测试）、`8bc6404`（M3 writer 拒绝契约）、`574250c`（M4+M5 三入口+BOT_SELF 门控+闭门钩子+e2e）、`0ab17fb`（M6 状态快照+.env.example）、`427825c`（M7 双语文档）、`502ef7d`（M8 实施报告）。
- 语义：`CONSOLIDATION` 角色被有界探针（真实生成路径最小 ping、不要求 /v1/models、含降级链）证实可用前，QQ 群/私聊/WebChat 的记忆采集 fail-closed；关门期消息不落库不排队不回放，恢复后从下一条新消息开始。`backend_for` 零改动；无 schema 迁移；无旁路开关。
- 验证：全量 `pytest tests -q` **3707 passed / 17 skipped**；ruff（git ls-files 口径）全过；`check_docs` 0 errors；`generate_message_flow --check` 过（manifest 仅 body hash 变化，新入口 `bot_main.start_capture_gate` 已入 inventory）。
- 基线例外：`ruff check .`（含未跟踪文件）报前会话遗留 `docs/reports/evidence/dialogue-attribution-20261008/guard_probe.py` I001（未改动）；GitNexus CLI 本机 registry 损坏，调用方清点用文本检索兜底（record_message 5 处生产调用、_record_bot_lines 13 处，全部覆盖）。
- NOT READY：真实模型探针冒烟、QQ 真机灰度、clean-VM 验收。详见 [实施报告](docs/reports/2026-10-16-ai-gated-memory-capture-implementation.md)。

### What's Next（AI-Gated Memory Capture）

1. 用户验收合并；合并前可在真实端点做一次探针冒烟（开/关门 + 冷加载观察）。
2. QQ 灰度观测：关门期消息不落库、`/stella/status` 的 `memory_capture` 段就绪状态。
3. 存量积压检查/排空是独立运维决策，未在本特性范围内。

## Memory Benchmark 评测体系 — 2026-10-16/17

- 分支 `feat/memory-benchmark-suite`（基于 origin/main @ `4029877`，PR #109 合并点），9 提交：`933864d`（M0 报告契约+基线对比+排除泛化）、`2b36ed9`（M1 维度扩容+生成器）、`23c00f3`（**parity harness 保真修复**）、`0938c5d`（M2 四模式矩阵）、`b744eec`（M3 PersonaMem）、`157b140`（M4 写路径回放）、`d744d46`（M5 成本计量）、`fdcdb88`（M6 canonical tie-break+parity 门禁）、`a8b317e`（双语文档+冻结基线+manifest）。
- **Parity 闭环**：21/24（API2 时代旧数字作废）→ 101/101。根因两个：① harness 把 `semantic_scores=None` 折叠成 `{}`，Python 侧跑「embedding 权重+零语义分」而 Rust 侧跑 rule-only——双实现一直在跑不同打分语义；② recommend_001 为 0.939 同分平手，native 早有 canonical tie-break（score desc → id asc）而 Python 稳定排序保留新鲜度序，policy.py 补齐后全数据集硬差异清零，**无需 allowed_diffs**。
- **四模式矩阵实证**（`memory/retrieval_v2.py` 与 `config/settings.py` 零改动）：① FTS 候选路径对自然中文查询**恒 0 命中**（`_segment_text` 整串+滑窗全为 MATCH token，FTS5 隐式 AND 语义不可能满足；101 例 0 行，检索总是回退新鲜度路径）——生产侧课题，已记账进报告 `retrieval_path`；② embedding/hybrid 只评 fixture 覆盖用例（查询向量在场判定），未覆盖显式 skip——现有 fixture 只覆盖旧 22 例中文文本，重建需 embedding 服务（当前 1234/8081 不可达，NOT READY）。
- 数据集：手写 53 + 生成 48 = **101 例**；新维度 temporal/conflict-supersede/scope-privacy/abstain/lineage 全部一次判别力测试锁死；`cross_scope_leak_rate` 与 `forbidden_activation_rate` 双硬零（结构化跨空间泄漏判定不依赖标注自觉）。
- 门禁：冻结基线 `memory/benchmark/_fixtures/baselines/2026-10-16.json` 逐指标零容差（`test_baseline_gate_per_metric_zero_tolerance`）；parity 全数据集门禁（`test_parity_gate_full_dataset`，native 缺席显式 skip）；PersonaMem CI job `memory-benchmark-public`（固定 seed 200 例 4.4s accuracy 100%，下载失败显式红不静默绿）；回放门禁（extraction/promotion/qa 100%、fabrication 0%、memory_delta +100）。
- 验证：全量 `pytest tests -q` **3750 passed / 17 skipped**；ruff（git ls-files 口径）全过；`check_docs` 0 errors；`generate_message_flow --check` 过（manifest 随 policy.py tie-break 重生成 d950c0561bfc）。证据：docs/reports/evidence/memory-benchmark-20261016/（含 manifest.json，parity/模式矩阵/回放/PersonaMem 报告）。
- NOT READY：live 回放真实模型验证（需 CONSOLIDATION 端点，离线跑 `--live --record` 一次并存证）；英文 embedding fixture 重建（需 embedding 服务）；QQ 真机灰度与本特性无直接耦合。
- 陷阱存档：assess_candidate 要求候选带 `source_message_ids` + `verification_contract`（exact_support_span 逐字等于候选内容且为消息原文子串，statement_kind 只认 self_report/explicit_preference 刻板句式）；回放预置消息必须显式写 conversation_key（空串会让快照与证据列 legacy 回填值不一致、晋升 verify 断链）；argparse 收 Path 对象会被当序列展开；`_ensure_common_tables` 不建 group_messages（用 pre_processors._GROUP_MESSAGES_V16_DDL）；批次大小必须与录制件批次对齐。

### What's Next（Memory Benchmark）

1. live 回放真实模型验证一次（`python scripts/eval_memory_replay.py --live --record memory/benchmark/_replay/daily-life/recorded/live.json`）并存证。
2. embedding 服务可用时重建 fixture（`scripts/build_embedding_fixture.py`），覆盖 101 例后 embedding/hybrid 模式全量可评。
3. FTS 恒 0 命中是生产检索的真实缺陷候选（RAG 特性疑似死代码），建议另立课题核查 `_query_fts` 的 MATCH 语义与生产收益。
4. PersonaMem 中文对照集与全量 5000 行离线跑为显式延后项（计划 §12）。

### 真模型验收（第一次）— 2026-10-17

- 生产双模型：**Strata 8081 = qwen3.8-flash-next-iq2_xs**（CONSOLIDATION 角色经 `LLM_ROLE_CONSOLIDATION_ENDPOINT=MEMORY` 槽）+ **LM Studio 1234 = text-embedding-qwen3-embedding-0.6b**。排查发现本机系统代理（7890）劫持 127.0.0.1 请求（502 假象），脚本一律 `NO_PROXY=127.0.0.1,localhost`。
- **embedding fixture 重建**：259 向量覆盖 101/101 用例（此前仅旧 22 例）；真实向量下四模式矩阵 parity 全 101/101，硬零全模式保持，embedding/hybrid 提升为 101/101 全绿（重生成后）。
- **基准抓到并修复一个用例创作缺陷**：M1 temporal/supersede 用例只偏移 `last_accessed_at` 列而排序读 `last_confirmed_at` 列——recency 判别未生效，rule 模式靠 conf/imp 差侥幸通过；真实 embedding 下新旧事实 sem 差（+0.030）抵掉 conf/imp 差（+0.035），7 例旧值激活踩硬零。修复=补 `last_confirmed_at_offset_minutes`（15 个文件），修复后 embedding 101/101。基线随之重生成（变更原因入档）。
- **live 回放真模型打通**（`--live --record`，3 批整合生成成功，录制件 `recorded/live-20261017.json`）：extraction 100%、fabrication 0%（第二轮）；**promotion/qa = 0% 的根因是生产配置现状**——`LLM_ROLE_EXTRACT_ENDPOINT=CHAT` 而 online 槽 base_url 为空，阶段2 契约提取回退阶段1，候选 verification=unknown 全部 OBSERVING 不晋升。这是配置决策（启用完整晋升链路需给 CHAT/MEMORY 槽配端点），非链路缺陷；已如实写入双语文档。
- 两轮 live 候选数 7→4、改写句式（「希望被称为小艾」被判 fabrication）第二轮消失——真模型非确定性实录，反证 recorded 确定性回放的价值。

### 两课题根因检查 — 2026-10-17（续）

**课题①「记忆晋升端点」——用户记忆正确，配置早已就绪；昨天结论勘误。**
- `.env` 自 2026-10-09 起三槽（CHAT/MEMORY/VISION）全部指向 Strata 8081（qwen3.8-flash-next-iq2_xs），`LLM_ROLE_EXTRACT_ENDPOINT=CHAT` → EXTRACT 与 CONSOLIDATION **一模型两职配置正常、阶段2 真实启用**（live 日志 🎯 ×3 批实证）。昨天写进文档的「EXTRACT 无可用端点→回退阶段1」是**错误结论**：告警来自评测 runner 硬编码 `_extract_backend=None`，非配置问题；runner 已改为真实装配，双语文档已勘误。
- **真实瓶颈（live 实证，4 候选契约全 unknown，0 accepted）**：qwen3.8-flash 阶段2 契约输出与窄合同三类错配——① span 带尾巴（「我叫小艾，以后多指教」整段作 content/exact_support_span，刻板句式 `_PREFERENCE_PATTERN`/`_SELF_REPORT_PATTERNS` fullmatch 失败；value 段不允许逗号）；② statement_kind/type 错配（称呼自述标 PREFERENCE，self_report 要求 FACT）；③ 部分契约形状不符早期 unassessed。accepted 是 Gate1 全部晋升路径的前置 → **当前模型下普通记忆实际不会晋升**（recorded 件手造合格契约 100% 晋升反证链路本身通）。低风险修复方向：extraction_prompt 强调「最小刻板句、无标点尾巴、self_report 必须 FACT」并给反例。

**课题②「FTS 恒 0 命中」——原初设计缺陷（a6431e4，2026-08-08 RAG 引入即如此），非回归。**
- 根因链：`_segment_text` 的 `re.findall(r"\w+", normalized)` 在 Unicode 语义下把**整段连续中文（即整条查询串）当一个 token**；FTS5 MATCH 空格连接 = 隐式 AND；文档索引只含文档自身整串 token → 查询整串 token 永不命中 → AND 恒假。逐 token 实证：「有什么游戏推荐吗」14 个 token 文档缺 13 个，唯一命中的只有「游戏」；只有 ≤4 字且恰为文档滑窗片段的查询才能命中（「游戏」AND=2 正常）。生产句子查询恒 0。
- 影响面：`retrieval_v2._fetch_candidates`（生产检索主路，RAG_ENABLED 默认 true）与 `retriever._query_rag_results`（RAG 主路径）两条 FTS 路径全部失效 → BM25 相关性从未生效，检索总是回退新鲜度排序，且每次检索白付一次 FTS 查询。
- 修复实证（内存 FTS5 模拟）：仅修分词（`\w+` 排除 CJK，滑窗保留）AND 仍 0（13 个滑窗 token 全要命中——**AND 对滑窗分词本质不可用**）；分词修复 + MATCH 改 OR 可真实召回（bm25 排序），但 OR 的 bm25 在短文档上区分度有限（-0.0 平坦），实施时需配 bm25 调权或最小长度过滤。native 检索不实现 FTS → parity 无影响。建议立小课题实施（retriever.py + retrieval_v2.py 两处 MATCH 构造 + 分词函数，附四模式矩阵回归）。

### FTS 中文检索修复实施 — 2026-10-17（续二）

- 计划 `2026-10-17-gitnexus-plan-fts-chinese-or-retrieval.md` 全量实施，5 提交于 `feat/memory-benchmark-suite`：`80da1b0`（分词 `_tokenize` 去 `\w+` 整段 CJK token + `_match_expression` OR 表达式 + 两查询点切换 + 11 例新测）、`d042c04`（migrate_v20 重灌存量索引 + SCHEMA_VERSION 20 + native 合同同步升 20 + .pyd 重编译 + 基准 native 标记改打 MEMORY_SCHEMA_VERSION）、`a180636`+`d6d20e1` 内含两次 flow manifest 重生成、`d6d20e1`（FTS 命中不窄化候选池并集语义三处同源 + 基准 FTS 空间暗伤修复）、`88eadeb`（实施报告 + 证据）。
- **计划偏差四项（全部有实证记录于报告 §1）**：① migrate_v17 编号过时（v17-v19 已存在）→ v20；② 「native 不实现 FTS」不成立——`load_fts_candidates` 直绑原始查询串同样恒 0 行，已改 OR 表达式并连带合同升 20（native 门禁按库 schema_meta 严格相等放行，不升会让 native 拒读新库）；③ 「Selection 兜底」不足——OR 后 forbidden 硬零 0→9.1%，根因是 FTS 池窄化，改为「FTS 命中不窄化候选池」（bm25 头 + 新鲜度头部并集，Python 双路径 + native 三处同源）；④ 基准 `_populate_fts_index` 空间默认空串 vs memories 行默认 group_id 的暗伤（AND 恒假时代被掩盖）。
- **验收**：fts 模式基准 100/101（唯一失败=基线记录的既有 rank-casual-001）、forbidden 0.0%、`retrieval_path` 65 行/101 查询（修复前恒 0）；四模式矩阵逐位对齐 2026-10-16 旧矩阵，rule/embedding parity 101/101；冻结基线零容差通过；bm25 默认列权经 rank 裁决保留。全量 pytest **3763 passed / 17 skipped**；cargo test 22/22；ruff/check_docs/flow-manifest 门禁过；detect_changes scope=all：代码符号零重叠（唯一非符号差异=上一会话遗留的 live-20261017.json 重录件，未随本批提交）。
- 本机 `_native.pyd` 已重编译到合同 20（gitignore 产物）；**发布注意事项**：release wheel 须重编，升级过渡期旧 .pyd 遇 schema 20 库会拒绝并回退 python（auto 模式）。
- NOT READY：QQ 真机灰度（随下次启动迁移自动重灌存量索引，观察检索命中即可）；native `fts_text` 与 Python `_tokenize` 的 ≤4 字段/`{2,8}` 分块既有分歧留后续小课题（报告 §6）。

### EXTRACT 契约对齐实施 — 2026-10-17（续三）

- 计划 `2026-10-17-gitnexus-plan-extract-contract-prompt.md` 全量实施，2 提交于 `feat/memory-benchmark-suite`：`4a45082`（EXTRACTION_PROMPT 增补契约硬规则块：枚举 evidence_contract 可审核句型与 predicate_key 含 .en 英形、span 截尾/值段禁标点、self_report→FACT+positive 与 explicit_preference→PREFERENCE 绑定、反例三条、非刻板句照常提取声明、称呼规则调和；并修正正例 content 逐字与结构示例契约 sleep_pattern→profile.residence 两处与闸门矛盾的示例；新增 tests/test_extraction_prompt_contract.py 结构守卫；flow manifest 重生成）、`9a74b9a`（真模型验收证据+实施报告）。
- **决定性验收（Strata qwen3.8-flash-next-iq2_xs @8081，daily-life suite live 回放两遍独立实录）**：第一遍标准报告候选 6/记忆 4，extraction 100%、fabrication 0%、**promotion 100%（此前 0%）**、qa 100%、delta +100；第二遍逐候选契约盘点 **4 条 accepted（此前 0）、0 rejected**，句型全部命中教学枚举（profile.residence / preference.general×2 / profile.nickname），截尾生效（「我叫小艾，以后多指教」→「我叫小艾」）。晋升以 accepted 为前置（memory_manager.py:1007），两证据互为印证。
- 门禁：守卫+前缀缓存 14 passed；子集 `-k "prompt or consolidat or evidence_contract"` 109 passed；ruff/check_docs 过；detect_changes scope=all exit 0 无 partial/truncated（唯一跟踪脏文件仍是上会话遗留 live-20261017.json 重录件，未随本批提交）。
- 闸门零改动（ASSESSMENT_VERSION 2026-10-08.1 未 bump）；GitNexus impact `format_extraction_prompt` 上游 CRITICAL（3 直接调用方全透传，与计划 §4 一致）。
- 遗留（计划 §12 开放项）：称呼要求（「以后叫我X」）闸门无支持句型、契约不会 accepted，扩 gate 另立课题；真模型非确定性下两遍候选 6/6、accepted 4/4，修复效果稳定复现。

### PR #110 CI 修复 — 2026-10-17（续四）

- 分支首推触发 PR #110 全量 CI，四项失败三种根因，全部修复（`723ca57`）：
  ① documentation：progress.md 链接的 EXTRACT 计划文件未入库（本地存在 untracked 件所以本地门禁过）→ 计划文件入库；
  ② test×3（同一例 `test_frozen_generated_dir_matches`）：`digest_dir` 直接哈希原始字节，Windows 检出 CRLF vs CI LF 使冻结摘要平台相关（本地 62e3b22b / CI 15252fbf）→ 哈希前 CRLF→LF 归一化，FROZEN_DIGEST 同步为平台无关值；
  ③ memory-benchmark-public：`adapt_personamem` 默认 CSV 是扁平路径而 `fetch_personamem` 落盘嵌套 `benchmark/text/`（扁平件是本机历史手工副本）→ 默认改指 fetch 落盘布局。
- 本地全链路镜像验证后推送：generator --check / 两测试文件 13 passed / adapt 200 + benchmark gate（**98.0%、forbidden 0**，门禁绿；较上次记录 100% 低 2 点是同分支 FTS 检索语义修复所致）。
- 推送后 run 39014161067 **13/13 全绿**（含 test 3.10/3.11/3.12、memory-benchmark-public、documentation）。
