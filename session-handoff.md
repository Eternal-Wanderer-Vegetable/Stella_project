# Session Handoff

## Current Session — Gravitas implementation

用户要求新建分支并执行[工程方案](docs/plans/2026-10-21-gravitas-engineering-plan.md)，阶段提交，完成后创建 PR。当前分支 `codex/gravitas-implementation` 基于合并 PR #111 后的 `main@c662746`；本轮范围登记为 GRAVITAS-IMPL G00–G09，严格一次推进一个工作包。

- Files：方案、[机器工作包清单](docs/plans/2026-10-21-gravitas-inventory.json)、[GitNexus 研究与基线证据](docs/reports/evidence/gravitas-20261021/README.md)。
- Current package：G00–G05 均已按工作包提交；下一步 G06 控制面与流程可见性。
- Commits：G00 `709a4b4`、`82f377d`、`88de58c`、`f03eb0f`；G01 `dbcbe41`；G02 `8e87c6c`；G03a `dd8bb72`、G03b `6c625f9`、G03c `351878d`；G04a `c3d4c4d`；G04b `6458764`；G04c `8160289`、`5b87efa`；G05 `e7ee716`。
- Verification：G00 组合回归 78 passed；G01 定向合同/发布/flow 回归 65 passed；G03c 综合定向回归 446 passed；G04a QQ/主动/WebChat/runtime 相关定向回归 77 passed / 1 fixture warning；G04b Facade/TurnService/Planner/Capability/QQ/WebChat 相关定向回归 470 passed / 1 fixture warning；G04c runtime/capability/planner/QQ/private/WebChat/social/outbound/Cometa 回归 **517 passed / 1 fixture warning**。G05 相关定向回归 216 passed / 1 warning；全量 Python suite **3968 passed, 29 skipped, 1 warning**，使用全新 `/tmp/stella-gravitas-g05-full-20261021b`。Ruff、改动 Python 编译、文档门禁（119 files / 1,241 links / 577 anchors / 0 errors）、flow archive `message-flow.b72338474a6c.json`（141 nodes / 139 resolved / 9,536 closures / 14,275 reachable symbols）及 `--check` 均通过。GitNexus G05 all 13/44/3/MEDIUM，compare main 469/867/75/CRITICAL cumulative，无 partial/truncated。G01 Python 3.10/3.11/3.12 import 与 Standalone/OneClick 包内导入记录仍有效。
- G03c impacts：RoleBackend MEDIUM；`execute_model_call` CRITICAL（8 direct / 6 processes / 11 modules）；脚本探针 LOW；两个评估脚本文件 UNKNOWN/0 edges，已文本审计。`run_compact_evaluation` LOW（2 impacted/1 direct/1 flow），回放 `main` LOW（1/1）。这些 exact symbol/function impact 有编辑后补查的门禁偏差，细节见实施报告，不构成后续风险豁免。
- Data / blockers：全部 G05 Python 测试使用隔离 `/tmp/stella-gravitas-*` 路径；未启动真实模型或平台，未读写用户数据库。全量第一次尝试暴露流程归档漂移、模拟发布树缺少 gravitas 包及复用临时 STELLA_HOME 导致的 WebUI 401，修正/隔离后完整重跑通过。G05 enforce 仍由 controller 的 coverage refusal 禁用；aged backend 还需要未来可靠完整性事实。G04c 在途 non-cooperative send 保留为进程内 quarantine，最多 16 个活动 callback；进程重启后的平台结果仍为 unknown，未做跨进程验证。真实模型、QQ/WebChat 灰度、跨进程 live、干净 VM 与发布验收缺失，整体保持 NOT READY。
- Next：执行 G06 status API/source、Dashboard、deploy status、flow catalog/inventory 与脱敏权限；当前代码提交为 `e7ee716`。恢复命令：`git status --short && git log --oneline -10`。G05 实现与证据见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。

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
