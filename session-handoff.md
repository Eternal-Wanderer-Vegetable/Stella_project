# Session Handoff

## Current Session — LinkMonitor lifecycle injection and Gravitas frontend diagnosis

用户反馈 PR #114 合入并同步到测试环境后，`_on_bot_connect` 仍出现 `Unknown parameter bot`，且 Gravitas 页面无法正常显示。当前分支 `codex/link-monitor-lifecycle-injection-fix`，基于 `origin/main@a568953`；代码提交 `15e326b`，状态记录待完成提交，PR 尚未创建。

- LinkMonitor 根因：NoneBot `Driver.on_bot_connect` / `on_bot_disconnect` 按 `BOT_HOOK_PARAMS` 解析回调；两者仍标注 `bot: Any`。已改为 `bot: Bot`，并新增通过 NoneBot `Dependent.parse` 验证 lifecycle hook 签名的回归。`@event_preprocessor` 的 `Bot` / `Event` 注解修复保留。
- Gravitas 页面：当前源代码与 `dashboard/dist` 有页面路由及 chunk；旧 `webui/dist`、`desktop/dashboard-dist` 快照缺少页面 chunk。现已执行 Vue typecheck、Vite build 和 `dashboard/sync-dist.mjs`；三个快照完全相同、各 52 个文件，JS/CSS 引用完整。生成快照在 `.gitignore` 中，不进入提交。
- API 装配：`bot.py` → `setup_gravitas` 注入 `status_api` provider → `status_api.collect_status` 注入 `webui.status_source` → `/api/v1/status` 的 `data.gravitas`。若静态资源更新后页面出现但内容 unavailable，查看 `data.gravitas`；若为 null，检查启动期 `[gravitas][boot]` 日志。外部测试环境浏览器/API 响应尚未访问。
- GitNexus：原 `.gitnexus/meta.json` 指向另一 worktree，默认 status / analyze 因 foreign storage 拒绝。已用 `/tmp/gitnexus-stella-codex-link-monitor` 外部 index 分析当前代码；两个 callback impact 为 UNKNOWN / 0 静态 caller，Driver decorator 注册点经源码确认。提交前 `detect-changes all` 为 2 files / 4 symbols、compare main 同值，LOW，无 partial/truncated。
- Verification：定向 LinkMonitor / status API 回归 35 passed；全仓 Ruff、改动 Python `py_compile` 通过；Dashboard typecheck、Vite build、静态资源同步通过。全量 Python suite 4,015 passed / 29 skipped / 3 failed（Cometa worker ACK、personal memory concurrent replay、WebUI groups mute）；三个失败在各自隔离 `STELLA_HOME` 下重跑均 1 passed，顺序/共享状态根因未确认。Vite 有 chunk-size 和 dynamic/static import warnings。未连接真实 Bot、平台或测试环境浏览器。
- Next：完成状态记录提交，推送新分支并创建 PR。部署新前端 build/sync 后重启 Bot；若 Gravitas 页仍 unavailable，收集登录后的 `/api/v1/status` 中 `data.gravitas`（不要贴凭据）及 Gravitas 启动日志。

## Previous Session — PR #113 CI repair

用户要求检查 PR [#113](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/113) 的 CI、修复失败，并将提交信息改成英文。任务已完成：分支 `codex/memory-envelope-fallback-followup` 已基于 `main@386b46f` 更新，提交标题为 `fix(memory): simplify invalid reply envelope fallback`。

- Root cause：原 CI run `39699060445` 的 `flow-manifest` 和 Python 3.10/3.11/3.12 均因 `TestDriftGate.test_committed_manifest_matches_source` 失败。语义漂移是 `cometa.claim` 与 `post.parse` 正文指纹变化、拓扑不变；PR 的 `parse_output` 文案更新使 `post.parse` 指纹变化，基线上还存在 `cometa.claim` 漂移。
- Fix：运行生成器并提交 `core/observability/flows/message-flow.982a65f5aef2.json`。`uv run --python 3.12.14 --no-project -- python scripts/generate_message_flow.py --check` 与 hosted `flow-manifest` 通过。
- Hosted verification：run `39707392594` 成功。Python 3.10 / 3.11 / 3.12 各为 4,017 passed / 29 skipped；flow-closure、Dashboard build、security、CLI、Windows native reliability、benchmark、documentation 与 lint 均通过。
- Local verification：Python 3.12.14 全量 4,014 passed / 29 skipped / 2 failed / 5 warnings。失败的 Cometa single-owner 与 WebUI OneBot config 用例各自在独立临时 `STELLA_HOME` 下单跑 1 passed；将本地全量失败保留为未确认的顺序/共享状态稳定性观察。全仓 Ruff、文档门禁（119 files / 1247 links / 577 anchors / 0 errors）、flow `--check`、JSON 和 diff checks 通过。
- Impact：`parse_output` upstream impact UNKNOWN / 0 edges；已在源码确认 `ai_gateway.py` 的动态 post-hook 注册及 runtime、回放、评估引用。文件级 impact LOW（7 个影响文件 / 3 个直接导入）。GitNexus 索引 sibling-worktree 提示和流程提取预算截断均已记录；manifest JSON 使用 Git 与 flow 门禁核验。
- Files：`memory/post_processors.py`、legacy trace fixture、generated message-flow archive、`feature_list.json`、`progress.md`、`session-handoff.md`。
- Blockers：本任务无 PR scoped CI blocker；PR 保持 open 等待 review / merge。真实平台、模型与干净 VM 验收不在本任务范围内。

## Previous Handoff — LinkMonitor dependency injection fix

用户要求修复开发环境同步提交后出现的 `link_monitor` 加载错误，并开新 PR。当前分支 `codex/link-monitor-event-injection-fix`，从 `origin/main@d136c90` 创建。原因是 NoneBot 注册 `@event_preprocessor` 时按 `Bot` / `Event` 类型做参数解析，`Any` 不受支持；源码签名已改为 `bot: Bot, event: Event`，并增加对 `Dependent.parse(..., EVENT_PCS_PARAMS)` 的回归测试。PR [#114](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/114) 已合入 `main@386b46f`；CI run `39702521767` 对 head `5df7ca5` 的结论为 success，Python 3.10/3.11/3.12 及全部其它 jobs 通过。

- Files：`extensions/link_monitor/__init__.py`、`tests/test_link_monitor.py`。
- GitNexus：索引 commit `f5e6a64` 与当前 `d136c90` tree 内容一致；目标 upstream impact `UNKNOWN / 0`，原因是 NoneBot 装饰器动态注册，已从源码确认注册点。提交前 `all` 与 `compare main` 均为 5 files / 8 symbols / 0 processes / LOW，无 partial/truncated。
- Verification：`tests/test_link_monitor.py` 12 passed；全仓 Ruff、改动文件 `py_compile`、docs（119 files / 1248 links / 577 anchors / 0 errors）、message-flow `--check`、diff check 均通过。全量 pytest 4014 passed / 29 skipped / 3 failed；失败为一个 memory-flow lifecycle 与两个 WebUI auth 用例，各自隔离重跑均通过，顺序/共享状态根因未确认。测试使用 `/tmp` 隔离 `STELLA_HOME`，未启动真实 Bot、平台或访问用户数据库。
- Next：PR #114 已合入 `main@386b46f`。全量 pytest 的三个顺序失败各自单测通过，但其共享状态/顺序根因尚未确认；当前本地全量仍按 4014 passed / 29 skipped / 3 failures 如实记录。

## Previous Session — Gravitas implementation

用户要求新建分支并执行[工程方案](docs/plans/2026-10-21-gravitas-engineering-plan.md)，阶段提交并创建 PR。GRAVITAS-IMPL G00–G09 已完成，PR [#112](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/112) 已提交且保持开放；当前分支 `codex/gravitas-implementation`，基于合并 PR #111 后的 `main@c662746`，HEAD `2bfb362`。最新 PR checks 全绿。

- Files：方案、[机器工作包清单](docs/plans/2026-10-21-gravitas-inventory.json)、[GitNexus 研究与基线证据](docs/reports/evidence/gravitas-20261021/README.md)。
- Current package：G00–G09 源码、测试、双语指南与分阶段提交均完成。CI 后续提交：`67f33a1` 为 package smoke 构建 Dashboard 资源，`4d0831c` 修正 Python 3.10 asyncio timeout 断言，`06be191` 消除 3.11 取消测试的 deadline 竞态，`2bfb362` 扩大 shared CHAT gate 回归的调度观察窗口。PR head `2bfb362` 的最终全量 CI 通过。
- Commits：G00 `709a4b4`、`82f377d`、`88de58c`、`f03eb0f`；G01 `dbcbe41`；G02 `8e87c6c`；G03a `dd8bb72`、G03b `6c625f9`、G03c `351878d`；G04a `c3d4c4d`；G04b `6458764`；G04c `8160289`、`5b87efa`；G05 `e7ee716`；G06 code `21fb77f`；G07 code `bfb1fa2`；G08 code `b78c72e`；G09 code `ddb1c53`；CI fixes `67f33a1`、`4d0831c`、`06be191`、`2bfb362`；status docs `21fe2a0`。
- Verification：G00 组合回归 78 passed；G01 定向合同/发布/flow 回归 65 passed；G03c 综合定向回归 446 passed；G04a QQ/主动/WebChat/runtime 相关定向回归 77 passed / 1 fixture warning；G04b Facade/TurnService/Planner/Capability/QQ/WebChat 相关定向回归 470 passed / 1 fixture warning；G04c runtime/capability/planner/QQ/private/WebChat/social/outbound/Cometa 回归 **517 passed / 1 fixture warning**。G05 相关定向回归 216 passed / 1 warning；全量 Python suite **3968 passed, 29 skipped, 1 warning**，使用全新 `/tmp/stella-gravitas-g05-full-20261021b`。G06 隔离回归 **97 passed / 1 existing warning**；Dashboard typecheck 通过、Vitest 7 files / **101 passed**、build 成功，localhost fake API 浏览器验收通过。G07 定向守卫 **4 passed**，全量 Python **3976 passed / 29 skipped / 1 existing warning（359.95s）**；10 seeds × 256 状态事件与 S01–S12 两轮离线回放、Standalone/OneClick staged import 均通过，same-seed digest 为 `6d35e75631c1861239cb4ac2cd8555a8e6a5058e`。Ruff、改动 Python 编译、文档门禁、flow archive `message-flow.d2b36de1444a.json`、CI YAML parse 与 diff 检查通过。详见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- G03c impacts：RoleBackend MEDIUM；`execute_model_call` CRITICAL（8 direct / 6 processes / 11 modules）；脚本探针 LOW；两个评估脚本文件 UNKNOWN/0 edges，已文本审计。`run_compact_evaluation` LOW（2 impacted/1 direct/1 flow），回放 `main` LOW（1/1）。这些 exact symbol/function impact 有编辑后补查的门禁偏差，细节见实施报告，不构成后续风险豁免。
- G08 evidence：`b78c72e` 加入 bounded dependency recovery registry、fenced passive outcomes、single-flight active probes、retry budgets/backoff 和 per-domain SQLite failure classification。涉及 endpoint/model calls、CapabilityProvider、CaptureGate、OneBot LinkMonitor、memory/social/Cometa/scheduling/knowledge/observability stores。定向回归 60 passed；最终 full suite 3,989 passed / 29 skipped / 1 existing warning（220.82s）；全仓 Ruff、改动 Python 编译、docs（119/1246/577/0 errors）、flow archive `message-flow.643390a24eac.json` 与 diff check 通过。两个中间 full run 分别遇到 WebUI replay 和 Cometa shutdown 单例失败，各单测重跑通过，之后完整全量通过；根因未确认，保留为间歇性稳定性风险。GitNexus all 13/47/31/CRITICAL；compare/main 503/1076/113/CRITICAL cumulative，扩大上限后 compare 列表仍 capped，统计和风险覆盖全部变更。具体影响、索引截断和 S13/S14 范围见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- Hosted verification：最终 PR CI run `39629392684` 在 `2bfb362` 上 Python 3.10 **4016 passed / 29 skipped / 3 warnings**、3.11 **4016 passed / 29 skipped / 4 warnings**、3.12 **4016 passed / 29 skipped / 5 warnings**；3.11 G07 S01–S12 fake evaluation 与 `release_package_layout_and_import` 均 PASS，digest `4a202051d493aaf8a67b8937e9a4003ef70f1ad7`。Dashboard run `39629392742`、Docker run `39629392600` 和 CI 内 lint/docs/security/flow/CLI/Windows native/benchmark 全部 PASS。本机 `tests/runtime/test_facade_turns.py` xdist 4-worker **13 passed**，`tests/observability/test_message_flow_runtime.py` **16 passed**；Ruff、`py_compile` 与 diff check 通过。之前 run `39628116553` 暴露的 1 秒 polling window 已由 `2bfb362` 修正，最终 CI 全绿。
- Local suite / remaining acceptance：一次完整本地回归为 **3942 passed / 22 skipped / 1 failed / 1 warning**，既有 WebUI Cometa empty-key 用例预期 400、实际 401；hosted 三版本全量已通过，但本地该异常根因未确认，不能声称本地全量绿。所有新验证使用隔离 `/tmp` `STELLA_HOME`；未启动真实模型、Bot 或平台，未读写用户数据库。真实模型/QQ/WebChat 灰度、生产跨进程恢复、clean VM、安装器与发布资产仍未验收，产品保持 **NOT READY**。
- Next：review 并合并 PR #112；之后在有授权平台账号与干净环境时完成外部验收。恢复命令：`git status --short && git log --oneline -10`。完整验证和 GitNexus 限制见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。

## Previous Session — Gravitas planning

本轮用户要求把稳态讨论完善成可落地方案，并深入使用 GitNexus。交付仅限计划、研究证据与状态；业务实施未启动。方案及文档/档案/源码指纹/证据摘要/图变更门禁已完成，结果入口为[证据 README](docs/reports/evidence/gravitas-20261021/README.md)。

- Files：[方案](docs/plans/2026-10-21-gravitas-engineering-plan.md)、[机器工作包/73 源码/50 入口/16 场景清单](docs/plans/2026-10-21-gravitas-inventory.json)、证据目录和双语历史导航。
- Evidence：基线 `2b69402`；GitNexus 1.6.12 全量重解析后关键 Function 恢复；query/context/impact、823 流程分页、源码与动态接线补证。acquire CRITICAL、Compact 和 deliver_lines HIGH。首次 partial 已重跑；PDG 无第160行语句块，不作语句级证明。
- Verification：文档、档案/DAG/指纹/证据 SHA256 与 diff 门禁通过；GitNexus all LOW、compare/main 累计 CRITICAL，临时扩大展示清单上限后完整重跑，无 partial/truncated，原始统计/风险一致。临时 STELLA_HOME；定向既有测试 83 passed/2 warnings，清理器 16 passed；三个合成探针确认调度旁路、取消计数、零水位清理问题，未实施修复。无生产库、模型、Bot 或平台连接。
- Historical status：当时 GRAVITAS-IMPL 为 planned，XPLAT-IMPL 仍为 in_progress。PR #111 合并后，本轮新建 Gravitas 分支并开始实施；XPLAT 的外部验收缺口改记 blocked，不代表验收完成。
- Historical next step：按方案 §10 从 G00 开始，先重绑 HEAD 和跑 upstream impact，再用三个子提交关闭默认 provider、waiter 回收与清理保护。当前进度见本文件上方的 Gravitas implementation。

## Inherited Cross-platform Handoff

## Current Objective

XPLAT-IMPL：执行 [GitNexus 跨平台方案](docs/plans/2026-10-20-gitnexus-cross-platform-plan.md) 的 WP00–WP11，按工作包分阶段提交。WP00–WP10 已完成；WP11 的 32 项状态矩阵、OneBot V11 事件/回投夹具和本地全量 Python 回归已通过。修复提交 `1f5c900`、`54c4d4c`、`7f35347`；PR #111 已合并，因平台 live、干净 VM 与发布验收尚缺，状态为 `blocked / NOT READY`。分支 `codex/cross-platform-implementation`，原基线 `ba582a922f4d3379b6397c4c0a8d8ef3e7c3e77d`。

## Deliverables

- [执行方案](docs/plans/2026-10-20-gitnexus-cross-platform-plan.md)：版本化合同、12工作包、依赖、迁移/回滚、测试与发布边界。
- [执行附录](docs/plans/2026-10-20-cross-platform-inventory.md)：50运行入口、32适配器和180候选文件。
- [证据索引](docs/reports/evidence/cross-platform-20261020/README.md)：原始query/context/impact、PDG、命令参数、补证、哈希。
- [WP00实施记录](docs/reports/cross-platform-implementation-20261020.md)：依赖冻结、GitNexus风险、QQ/WebChat回归与命令结果。
- [WP01实施记录](docs/reports/2026-10-21-wp01-identity-registry.md)：opaque 身份合同、隔离注册表、alias 与定向回归证据。
- [WP02实施记录](docs/reports/2026-10-21-wp02-context-message-identity.md)：projection v7、opaque message ID、turn-bound target_ref、GitNexus 风险与验证结果。
- [WP03实施记录](docs/reports/2026-10-21-wp03-storage-backend.md)：schema 21 迁移、Python/native API 4、隔离 wheel、双后端 fullchain/parity 与未关闭验收项。
- [WP04实施记录](docs/reports/2026-10-21-wp04-memory-authorization-scope.md)：schema 22、主体/连接隔离、分享撤回、KB ACL、社交作用域和定向验证证据。
- [WP05实施记录](docs/reports/2026-10-21-wp05-ingress-admission.md)：OneBot/NoneBot normalizer、共享 admission、群注册接线、WebChat 主体与定向回归/GitNexus 证据。
- [WP06实施记录](docs/reports/2026-10-21-wp06-outbound-delivery.md)：统一出站、媒体/能力合同、OneBot codec、social v5 多 ID 回执、定向回归/GitNexus 证据。
- [WP07实施记录](docs/reports/2026-10-21-wp07-background-recovery.md)：后台投递目标与跨进程任务恢复。
- [WP08实施记录](docs/reports/2026-10-21-wp08-astrbot-compat.md)：AstrBot 事件和组件兼容边界。
- [WP09实施记录](docs/reports/2026-10-21-wp09-adapter-assembly-health.md)：多适配器装配与健康状态。
- [WP10实施记录](docs/reports/2026-10-21-wp10-control-plane-delivery.md)：平台控制面、安装器与发布清单。
- [WP11认证记录](docs/reports/2026-10-21-wp11-platform-certification.md)：32 项状态、夹具、回归失败和外部验收缺口。
- [机器可读适配器矩阵](tests/platforms/adapter_matrix.json)：官方快照 32 行，未知保持显式未评估。
- `.gitnexus/lbug`：本地代码图谱；`.gitnexus/gn`：固定1.6.11启动器。工具/索引不入业务提交。

## Verification / Boundaries

WP11 定向平台/Normalizer/Outbound 测试 18 passed；后续记忆 replay/candidate 27 passed，调度 service 176 passed，WebUI manage 12 + scheduling route 1 passed，Cometa worker 6 passed。CI 同款全量 Python 最新为 **3879 passed / 29 skipped / 5 warnings**（112.76 秒），先前记录的 6 项失败均已关闭。Dashboard Vitest 100 passed、typecheck 通过、build 成功；全仓 Ruff 与 message-flow 检查通过。详见 WP11 报告。整体仍 NOT READY：OneBot V11 L0 隔离 Driver 注册通过、L1 真实事件模型到 fake 回投夹具通过、L3 夹具部分；L2 与 live 未执行。官方 32 项全部 NOT CERTIFIED；仅 OneBot V11/V12 共用发行包在本地安装，另 30 项包未安装。

GitNexus 流程抽取仍有入口/分支预算截断、回调和跨语言缺边；UNKNOWN 与零调用者均用源码引用补查，不作为低风险。全量 pytest 使用隔离 `STELLA_HOME=/tmp/stella-wp11-final-allgreen-20261021`；未迁移生产库、未启动 Bot、未连接平台或模型。没有 Windows/Linux 干净 VM、QQ 灰度、跨进程 live 恢复和 Python 3.10/3.11 独立验收。

## PR #111 CI 修复（2026-10-21）

- 首轮失败根因：test job 只安装 `requirements.txt` 与开发工具，而跨平台测试直接导入可选的 `nonebot_plugin_alconna`；它只在平台 extra 与 `requirements-platform.lock` 中定义。提交 `e622c7a` 将测试安装切换到该 lock、加入 pip 缓存键，并同步双语 CI 复现说明。
- 首次重跑暴露独立的 Cometa 测试竞态：`test_pump_delivers_submitted_ack` 在 `PENDING → SENDING` 时提前结束轮询。提交 `97a2ea9` 让测试等到 `SERVER_EMITTED` 终态。
- 最终 hosted CI run `39557774555` 全绿：Python 3.10 / 3.11 / 3.12 各 3,879 passed / 29 skipped；CLI、文档、security、flow、Windows native、benchmark、Dashboard、Docker build/push 均通过。PR [#111](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/111)。
- 本地检查：`uv pip install --dry-run --python .venv/bin/python -r requirements-platform.lock`（95 packages，无改动）；平台失败相关测试 22 passed / 1 warning；Cometa runtime assembly 3 passed；`python3 scripts/check_docs.py`（119 files / 1,234 links / 577 anchors / 0 errors）。

## Next Steps

1. 外部具备平台账户与干净环境后，按 32 行矩阵逐平台补包版本/Python/driver、fixture、live 和维护证据；单独完成多账号恢复、QQ 灰度、Python 3.10/3.11 独立运行及 Linux/Windows clean VM。
2. 补齐 OneBot L2/L3 与至少一个代表平台的真实 live 收发；按各协议事件语义评估非聊天 adapter。
3. 只有 release、平台和 VM 验收关闭后才将 XPLAT-IMPL 改为 done；GitNexus 索引预算限制仍须如实保留。

---

## Previous Handoff — historical, superseded by the current objective


## Current Objective

- EXTRACT 契约对齐（阶段2 提示词修复，计划 `docs/plans/2026-10-17-gitnexus-plan-extract-contract-prompt.md`）已全量实施并验收：分支 `feat/memory-benchmark-suite`，本会话提交 `4a45082`（提示词硬规则块+守卫测试）→ `9a74b9a`（验收证据+报告）→ `af079df`（状态）→ `723ca57`（PR CI 修复）；**已推送，PR #110 CI 13/13 全绿（run 39014161067），待用户合并**。
- 实施报告：[docs/reports/2026-10-17-extract-contract-prompt-fix.md](docs/reports/2026-10-17-extract-contract-prompt-fix.md)；证据：`docs/reports/evidence/extract-contract-20261017/`（replay-live-strata-postfix + contract-assessment-live + manifest）。

## Completed This Session

- `4a45082`：`EXTRACTION_PROMPT` 增补「契约硬规则」块（分隔线之上，`{messages}` 仍在末尾）：枚举 `evidence_contract` 可审核刻板句型与 predicate_key（含 `.en` 英形）、span 截尾/值段禁标点/canonical_value=纯值段、self_report→FACT+positive 与 explicit_preference→PREFERENCE 绑定、反例三条、非刻板句照常提取（不漏不变）、称呼规则调和（自称「我叫X」=self_report/FACT；「以后叫我X」维持 PREFERENCE 但契约暂不 accepted）。另修正两处与闸门矛盾的既有示例：正例 content 改逐字片段、结构示例契约 `sleep_pattern`/失眠 → `profile.residence`/杭州。新增 `tests/test_extraction_prompt_contract.py` 结构守卫（句型枚举/绑定措辞/块位置）。flow manifest 重生成（body_hash 漂移）。
- `9a74b9a`：真模型验收证据落盘 + 实施报告。
- `723ca57`：PR #110 首推 CI 四项失败修复（三种根因）：EXTRACT 计划文件入库（docs 链接门禁）；`digest_dir` 哈希前 CRLF→LF 归一化 + FROZEN_DIGEST 平台无关值（Windows CRLF 检出 vs CI LF 使冻结摘要分叉）；`adapt_personamem` 默认 CSV 改指 fetch 落盘嵌套布局（CI 无本机手工扁平副本）。本地全链路镜像（generator --check / 13 passed / adapt 200 + gate 98.0% 绿）后推送，CI 全绿。

## Verification Evidence

- **决定性验收（live 回放两遍独立实录，Strata qwen3.8-flash-next-iq2_xs @8081，daily-life suite）**：
  - 第一遍（计划命令，`replay-live-strata-postfix.json`）：候选 6 / 记忆 4；extraction 100%、fabrication 0%、**promotion 100%（此前 0%）**、qa 100%、delta +100。
  - 第二遍（同管线+逐候选契约盘点，`contract-assessment-live.json`）：**accepted 4（此前 0）、0 rejected**，句型全命中教学枚举（profile.residence / preference.general×2 / profile.nickname），截尾生效（「我叫小艾，以后多指教」→「我叫小艾」）。
  - 晋升以 accepted 为前置（memory_manager.py:1007 缺 accepted 拒绝晋升），promotion 100% 与 accepted 4 互为印证；关键错误 0。
- pytest：守卫+前缀缓存 14 passed；子集 `-k "prompt or consolidat or evidence_contract"` 109 passed；ruff（改动文件）、check_docs（119 文件/1195 链接）过。
- GitNexus：`impact format_extraction_prompt` 上游 CRITICAL（3 直接调用方全透传，与计划 §4 一致）；detect_changes scope=all exit 0、无 partial/truncated。

## Blockers / Inherited State

- **工作树遗留（非本会话产物，未提交）**：`memory/benchmark/_replay/daily-life/recorded/live-20261017.json`（上上会话 live 重录件）及各 untracked plans/reports/skills-lock.json/.agents/ 等照旧保留，是否提交由用户决定。
- 闸门 `memory/evidence_contract.py` 本计划零改动（ASSESSMENT_VERSION 2026-10-08.1 未 bump）。
- dev bot（用户终端直启，与 prod 同用 8080）与回放共用 8081 Strata；**bot 进程需重启才会加载新提示词**（提示词是模块常量，非热载）。

## Next Steps

1. 用户合并 PR #110（分支 18 提交全绿）；QQ 真机灰度观察阶段2 晋升（需重启 bot 加载新提示词）。
2. 开放课题（计划 §12）：称呼要求（「以后叫我X」）闸门无支持句型，扩 gate（evidence_contract 新 pattern + ASSESSMENT_VERSION bump + 提示词同步）另立计划。
3. 上会话遗留：native `fts_text` 与 Python `_tokenize` 分词分歧对齐小课题；QQ 真机检索命中观察。
4. 备忘：personamem CI gate 现 98.0%（FTS 修复后的口径），若后续调 gate 阈值需连同 `ci.yml` 一起审。
