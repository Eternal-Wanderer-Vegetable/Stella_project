# Session Progress Log

## Current State

**Last Updated:** 2026-10-17 (Asia/Shanghai)
**Active Feature:** EXTRACT 契约对齐（阶段2 提示词修复）已在 `feat/memory-benchmark-suite` 落地并验收通过（4a45082 提示词+守卫、9a74b9a 证据报告，另含状态提交）；真模型 live 回放 accepted 0→4、promotion 0%→100%。分支累计待用户审阅合并（未推送）。
**Scope:** 计划 [2026-10-17-gitnexus-plan-extract-contract-prompt.md](docs/plans/2026-10-17-gitnexus-plan-extract-contract-prompt.md) 全量实施：仅改 `EXTRACTION_PROMPT`（契约硬规则块+示例契约修正），闸门 `evidence_contract.py` 零改动。详情见 [实施报告](docs/reports/2026-10-17-extract-contract-prompt-fix.md)。

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
