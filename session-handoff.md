# Session Handoff

## Current Objective

XPLAT-IMPL：执行 [GitNexus 跨平台方案](docs/plans/2026-10-20-gitnexus-cross-platform-plan.md) 的 WP00–WP11，按工作包分阶段提交。WP00–WP03 已完成，下一阶段 WP04；当前分支 `codex/cross-platform-implementation`，基线 `ba582a922f4d3379b6397c4c0a8d8ef3e7c3e77d`，最新实现提交 `ec5cf65`。

## Deliverables

- [执行方案](docs/plans/2026-10-20-gitnexus-cross-platform-plan.md)：版本化合同、12工作包、依赖、迁移/回滚、测试与发布边界。
- [执行附录](docs/plans/2026-10-20-cross-platform-inventory.md)：50运行入口、32适配器和180候选文件。
- [证据索引](docs/reports/evidence/cross-platform-20261020/README.md)：原始query/context/impact、PDG、命令参数、补证、哈希。
- [WP00实施记录](docs/reports/cross-platform-implementation-20261020.md)：依赖冻结、GitNexus风险、QQ/WebChat回归与命令结果。
- [WP01实施记录](docs/reports/2026-10-21-wp01-identity-registry.md)：opaque 身份合同、隔离注册表、alias 与定向回归证据。
- [WP02实施记录](docs/reports/2026-10-21-wp02-context-message-identity.md)：projection v7、opaque message ID、turn-bound target_ref、GitNexus 风险与验证结果。
- [WP03实施记录](docs/reports/2026-10-21-wp03-storage-backend.md)：schema 21 迁移、Python/native API 4、隔离 wheel、双后端 fullchain/parity 与未关闭验收项。
- `.gitnexus/lbug`：本地代码图谱；`.gitnexus/gn`：固定1.6.11启动器。工具/索引不入业务提交。

## Verification / Boundaries

基线 main@ba582a922f4d3379b6397c4c0a8d8ef3e7c3e77d；WP00 基线回归 142 passed；WP01 定向回归 160 passed、message-flow 合同 14 passed；WP02 定向回归 310 passed；WP03 定向回归 77 passed / 1 skipped、Rust 25 passed、隔离 native wheel fullchain 和 embedding parity 通过。WP03 全量 pytest 在 876 passed / 7 skipped 后因 Cometa worker 测试 451.87 秒无进展而中止，单测 30 秒复现；WP02 报告中的其他全量失败仍未关闭，集成门禁 NOT READY。WP03 实现提交 `ec5cf65`；预提交 GitNexus scope all 17 files/58 symbols/10 flows/HIGH，compare main 202 files/296 symbols/28 flows/CRITICAL，索引预算限制见 WP03 报告。编辑前影响与源码补查见各阶段报告。

GitNexus 流程抽取仍有入口/分支预算截断、回调和跨语言缺边；UNKNOWN 与零调用者均用源码引用补查，不作为低风险。WP01 中 V2 注册 API 无生产调用点，待后续入口包接线。WP03 已将 opaque 平台回执和规范主体分别持久化，历史 subject 仍为空未知而不猜测。平台注册快照 SHA-256 不变；平台收发 fixture/live 尚未执行。未迁移生产库、未启动 Bot；`STELLA_HOME` 未设置，测试使用临时隔离数据。

## Next Steps

1. WP03 实现提交 `ec5cf65` 已完成；本次计划、progress、feature_list、handoff 和报告的状态文档待提交。
2. 下一阶段 WP04：刷新当前 GitNexus 状态；对 `memory/ownership.py`、`memory/evidence_contract.py`、`memory/retrieval_v2.py`、`memory/personal_sharing.py`、`memory/addressing.py`、`memory/social_*`、`knowledge/{acl,domain,store,schema}.py` 和 `capability/providers/knowledge.py` 运行 upstream impact，再按权限与数据边界实施。
3. 按 WP04 验收同裸 ID 隔离、私聊到群/频道零泄漏、旧 evidence 兼容、分享撤回、KB ACL 和主动目标校验；提交前运行 docs、模块回归与 GitNexus all/compare 门禁。
4. 平台 live、QQ 灰度、Windows native wheel 与 clean VM 仍分别验收；GitNexus 图的流程/候选预算限制、partial/truncated 重跑和源码补证要求持续适用。

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
