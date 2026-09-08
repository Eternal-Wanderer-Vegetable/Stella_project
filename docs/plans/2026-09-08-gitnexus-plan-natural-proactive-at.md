# GitNexus Engineering Plan

> Task: 修复 Stella 主动向群友发问时缺少自然承接、在正常聊天中突兀切入的问题。
> Evidence verified at commit `88511cc9b0c71f4781db24278ee14da5af495dd2`; GitNexus index is fresh at the same commit (`2026-09-08T08:14:08.824Z`, runner provenance current).
> Evidence provenance schema 2; global dirty digest `0a9c85780067d9afcd0764f307b60891e3cee927ee11eaeb5ec7826d10fd82cd`; cited-path manifest 30 entries; exact generated plan path excluded.

## 1. Objective

[verified] 让主动 `@` 只在当前群聊存在可识别的自然承接时发送问题；无法承接时静默等待/跳过，不发送突兀问题、不消耗主动 `@` 配额，并且不回归已修复的“把上下文尾巴当成待回复内容”问题。同步让 Participation 命中后的普通插话携带真实触发消息与决策依据。

## 2. Current Behaviour

[verified] `proactive_speak_job` 先调用 `_proactive_at_user`，返回已发言后直接结束本群本轮；主动 `@` 因而绕过了 Participation Decision Layer（`stella_project/plugins/bot_main/ai_gateway.py:1395-1428`）。

[verified] `_proactive_at_user` 的顺序是 `can_speak("at")` → `pick_target` → `build_instruction` → `Pipeline.run` → 发送并 `record_at`；没有“本轮不适合问”的结果分支（`stella_project/plugins/bot_main/ai_gateway.py:1062-1170`）。

[verified] `pick_target` 的活跃条件是用户在 `PROACTIVE_AT_ACTIVE_WITHIN` 内发过任意消息，再叠加配额、用户冷却、无回应退避和候选优先级；没有当前话题、目标用户最后一句话、话题速度或可承接性判断（`memory/proactive_target.py:221-297`、`memory/proactive.py:143-155`）。

[verified] `VERIFY_PROMPT` / `COLDSTART_PROMPT` 把“现在要确认/了解一件事”设为任务，并明确写着“实在接不上，直接问也可以”；最近对话被定义为语气素材，不能否决提问（`memory/proactive_prompt.py:31-62`）。

[verified] `proactive_at` 的指令前置顺序是为避免接错话而建立的保护：`core/pipeline.py:29-74` 将指令放在上下文之前，`core/planner.py:81-99` 对该 intent 不触发 Planner。当前 `.env` 开启主动 `@`、活跃窗 300 秒、基础配额每天 2 次、用户冷却 7200 秒、冷启动话题为空，因此更可能复现 verify 候选与当前话题脱节（`.env:123-133`、`config/settings.py:706-727`）。

## 3. Relevant Architecture

[verified] 主动 `@` 与普通 Participation 是两条入口：前者由定时任务直接进入 `_proactive_at_user`，后者由 `record_group_chat` 只对 `PASSIVE` 消息调用 `ParticipationManager.observe`，命中后异步调用 `_spawn_participation_speak`（`stella_project/plugins/bot_main/ai_gateway.py:340-389`）。

[verified] 两条路径最终都可以复用 `_proactive_speak_for_group` 的群锁、ReplyGate、记忆整合、Pipeline、去重和发送流程；主动 `@` 使用 `trigger="reply", intent="proactive_at"`，普通插话使用 `trigger="proactive"`（`stella_project/plugins/bot_main/ai_gateway.py:1094-1104`、`1323-1335`）。

[verified] `ParticipationDecision` 已经持有 `topic_id`、`trigger_msg_id`、`reason_flags` 和 `breakdown`，但 `_spawn_participation_speak` 当前只把 `decision.mode` 转成固定文案（`memory/participation/decision.py:37-51`、`stella_project/plugins/bot_main/ai_gateway.py:1235-1263`）。

[inferred] 核心不是候选重复或记忆时效缺陷，而是“目标层只证明用户活跃，Prompt 又要求必须完成询问”，中间缺少自然承接闸门。

## 4. GitNexus Findings

[graph] `context(proactive_speak_job)` 显示它直接调用 `_proactive_at_user` 与 `_proactive_speak_for_group`；`trace(proactive_speak_job → _proactive_at_user)` 是单跳 `CALLS`，确认定时主动 `@` 没有经过 Participation Decision Layer。

[graph] `impact(_proactive_at_user, upstream, maxDepth=3)` 返回 `risk=LOW`、1 个直接调用者 `proactive_speak_job`、1 条受影响执行流；改动面集中在 Bot_main。

[graph] `impact(_proactive_speak_for_group, upstream, maxDepth=3)` 返回 2 个直接上游并追溯到 `record_group_chat`；公共执行器改动需覆盖定时与 Participation 两条路径。

[graph] `impact(pick_target, upstream, maxDepth=3)` 返回 `risk=MEDIUM`、7 个直接调用者，其中 6 个为现有单测、1 个为 `_proactive_at_user`；目标选择返回契约应保持兼容。

[graph] `query` 找到的 Participation 流程包含 `record_group_chat`、`observe`、`DecisionTracker` 与 `_spawn_participation_speak`；现有 benchmark 686 个评分点没有 `AT_MENTION`，不能用它证明主动 `@` 自然，只能说明 Participation 的抑制规则。

[verified] 既有实现文档明确把 `proactive_at_user` 标为“第一版独立不动、后续再统一”（`design_docs/Stella_主动插话机制实现方案.md:150-155`）；这正是本次补齐的架构断点。

## 5. Statement-Level PDG Findings

[verified] 当前 GitNexus 索引没有 PDG 层；对 `proactive_speak_job`、`_proactive_at_user`、`_proactive_speak_for_group` 的 `pdg_query(mode="controls")` 均返回 “no PDG layer”。本计划不虚构 CDG/REACHING_DEF 边。

[verified] `_proactive_at_user` 在发送前没有可表达“放弃本轮”的分支；已有去重只针对生成文本相似度，不能判断候选与当前聊天是否相关（`stella_project/plugins/bot_main/ai_gateway.py:1111-1124`）。发送后才执行 `record_at`，因此 skip 可以设计为不占配额。

[verified] `_proactive_speak_for_group` 的 `finally` 会依据 `planner_wait` 结束 ReplyGate；Participation 的 WAIT 只覆盖 `trigger="proactive"`，不能直接拿来吞掉主动 `@`（`stella_project/plugins/bot_main/ai_gateway.py:1337-1344`、`core/planner.py:191-205`）。

[inferred] 最小风险控制流是：保留现有一次 Replyer LLM 调用和 `proactive_at` 指令前置，只把“是否值得发出”作为该调用的显式二值结果；解析到内部 skip 标记时在发送层短路，并记录负向冷却。

## 6. Proposed Changes

### 6.1 建立“可跳过”的主动提问契约

[verified] 修改 `memory/proactive_prompt.py` 的 `build_instruction` 及两种 Prompt：模型先查看目标用户的最近发言/当前话题，再判断能否把候选或了解方向自然接上；有明确桥接才输出一句问题，否则只输出严格内部 skip 标记。删除“实在接不上也可以直接问”，保留不复述候选、不暴露内部记忆、不像问卷、一次只问一件事等护栏。

[verified] 修改 `stella_project/plugins/bot_main/ai_gateway.py` 的 `_proactive_at_user`：`Pipeline.run` 返回后先解析 skip；skip 时只写诊断日志并返回 `False`，不得调用发送、`record_at`、`mark_spoke`、`record_spoken` 或回应检测。正常输出仍走现有发送和记账顺序。

[verified] 保持 `ChatContext(trigger="reply", intent="proactive_at")` 与 Pipeline 指令前置顺序不变；不要把主动 `@` 改成普通 `trigger="proactive"`，也不要第一版额外增加 Planner LLM 调用。

### 6.2 防止“跳过后每分钟重复尝试”

[verified] 修改 `memory/proactive.py` / `memory/proactive_target.py`，增加进程内、带 TTL 的主动提问负向冷却，键至少包含群、目标用户和候选 ID 或冷启动话题；用户产生新消息时清理旧 skip，候选/话题变化时自然失效。

[verified] 修改 `config/settings.py`、`.env.example`、`docs/configuration.md`，增加自然度策略开关与 skip 冷却配置，并提供 `observe`/`enforce` 灰度语义。默认先 shadow 记录，正式开启 `enforce` 后才真正丢弃 skip；skip 不计每日主动 `@` 配额，也不写入 `proactive_state`。

[inferred] `pick_target` 的验证候选优先级、`last_asked_candidate_id` 排除和时效类型过滤全部保留；本次只增加“当前是否值得尝试”的结果，不重写已关闭的记忆缺陷。

### 6.3 给生成器补齐当前承接证据

[verified] 复用 `memory/pre_processors.py:108-240` 已有的短期摘要与最近原始消息尾巴；Prompt 必须把它们定义为“自然承接判断”的证据，不再只描述成语气素材。目标用户 ID、最近消息归属、当前话题新鲜度必须可区分，不能只提供无说话人标签的摘要。

[verified] 若 Participation 状态可用，扩展 `ParticipationManager.snapshot` 的群级快照为附加的当前 topic 状态、有限最近消息/速度信息，供主动 `@` 日志和 Prompt 证据使用；保持已有字段兼容，不塞入完整历史。

### 6.4 统一两条主动输出路径的 skip 与证据

[verified] 修改 `record_group_chat`、`_spawn_participation_speak`、`_proactive_speak_for_group`：把触发消息文本（截断/仅 debug）、`trigger_msg_id`、`topic_id`、`reason_flags`、`breakdown` 摘要传入普通插话指令；mode 固定文案只能作为行为方向，不能替代真实触发内容。

[verified] 让 `_proactive_speak_for_group` 识别同一内部 skip 协议；skip 时结束 ReplyGate 但不记录 Stella 主动发言、不增加 Participation 的 `proactive_speak_count`、不发送。主动 `@` 保留用户级配额/冷却，Participation 保留 topic/velocity/repetition 评分，两者只统一执行协议。

[verified] 扩展 `memory/participation/observability.py` 的日志字段，区分 `decision_allow`、`generation_skip`、`sent`、`send_failed` 与 skip 原因；默认不记录完整聊天原文。

### 6.5 测试、文档和灰度

[verified] 更新 `tests/test_proactive_prompt.py`，锁住两种模式都允许 skip、必须优先判断承接、不得保留“接不上也直接问”的反向回归；更新 `tests/test_proactive_target.py`、`tests/test_proactive_at_flow.py`，覆盖负向冷却、候选/话题变化清理、skip 不占配额。

[verified] 增加主动 `@` 执行层假 Pipeline/假 Bot 测试：无桥接不发送且不记账；有桥接发送并记账；重复 skip 不再次调用生成；发送异常不污染回应检测。更新 `tests/test_participation.py`，断言真实触发消息和 reason flags 到达生成器且 skip 不增加主动发言统计。

[verified] 保留并扩展 `tests/test_pipeline_compose.py`、`tests/test_planner.py`：`proactive_at` 仍指令前置、不被普通 Planner WAIT 吞掉；普通 `trigger="proactive"` 的 WAIT 不变。

[inferred] 在现有 Participation benchmark 外增加主动 `@` 回放样本：候选无关、候选与实现讨论相关、话题刚结束、高速刷屏、用户刚回应 Stella；指标为是否发送、是否桥接、是否重复、是否占配额。

## 7. Implementation Sequence

1. 记录当前候选数、生成数、发送数、回应数和人工抽样突兀率，不改变默认行为。
2. 加入 Prompt skip 契约与解析测试；严格标记解析失败时 fail-closed。
3. 加入带 TTL 的负向冷却和新消息清理；不新增数据库迁移。
4. 接入 `_proactive_at_user` 发送前短路，并在群锁内复核目标证据与 skip 冷却。
5. 将真实触发消息与 ParticipationDecision 元数据接入公共执行器；复用 skip/日志协议。
6. 增加配置、文档和结构化指标；先 `observe`，再对测试群启用 `enforce`。
7. 用脱敏回放和真实测试群人工抽样验收；不修改当前工作区 `.env`。

## 8. Test Strategy

- 重点：`python -m pytest tests/test_proactive_prompt.py tests/test_proactive_target.py tests/test_proactive_at_flow.py tests/test_proactive_gate.py tests/test_pipeline_compose.py tests/test_planner.py -q`
- Participation：`python -m pytest tests/test_participation.py -q`
- 全量：`python -m pytest tests -q`
- CI 形态：`pytest tests/ --cov=. --cov-branch -n auto --dist loadgroup`
- Participation 回放：`python -m tests.benchmark.participation.runner --db <脱敏数据库> --limit 5000 --no-embedding`
- 关键断言：无桥接不发送、不记账、不更新回应检测；同一 skip TTL 内不重复付费；新消息/候选变化可解除；实现讨论相关时先桥接再提问；普通 @ 回复与指令顺序不变。

## 9. Risk and Impact Analysis

[graph] `_proactive_at_user` 直接调用者只有 `proactive_speak_job`，但 `_proactive_speak_for_group` 同时被定时任务和 Participation runner 使用；公共 skip 解析/记账改变必须覆盖两条路径。

[graph] `pick_target` 风险为 MEDIUM，直接测试较多；保持 `ProactiveTarget | None` 与已有字段语义兼容。

[inferred] 过度保守会降低记忆采集；必须联合观察 skip 率、发送率、回应率、候选晋升率和人工自然度抽样。

[inferred] 本方案不增加第二次 LLM；无桥接候选仍付出一次已有 Replyer 成本，负向冷却用于避免同一候选连续付费。群锁内需复核，INFO 日志只记录元数据。

## 10. Files Expected to Change

| File | Symbols | Reason |
| ---- | ------- | ------ |
| `stella_project/plugins/bot_main/ai_gateway.py` | `_proactive_at_user`, `record_group_chat`, `_spawn_participation_speak`, `_proactive_speak_for_group` | skip 短路、触发证据、统一记账/日志 |
| `memory/proactive_prompt.py` | `build_instruction`, `build_verify_instruction`, `build_coldstart_instruction` | 可跳过的自然承接 Prompt |
| `memory/proactive_target.py` | `ProactiveTarget`, `pick_target` | 负向冷却/证据，保留选人策略 |
| `memory/proactive.py` | `ProactiveController.active_users`, `record_message` | skip 生命周期 |
| `memory/participation/__init__.py` | `ParticipationManager.snapshot` | 有限 topic/速度/最近消息快照 |
| `memory/participation/observability.py` | `log_decision` | allow/skip/sent/failed 观测 |
| `config/settings.py`, `.env.example`, `docs/configuration.md` | 配置说明 | 灰度和 TTL |
| `tests/test_proactive_prompt.py`, `tests/test_proactive_target.py`, `tests/test_proactive_at_flow.py` | 主动 @ 护栏 | skip、冷却、记账回归 |
| `tests/test_participation.py`, `tests/test_pipeline_compose.py`, `tests/test_planner.py` | 参与/管线回归 | 真实触发证据与顺序不回归 |

## 11. Reusable Implementation Context

```yaml
implementation_context:
  task_summary: "主动 @ 先判断当前聊天能否自然承接；不能承接则跳过且不占配额，同时把 Participation 的真实触发证据传给生成器。"
  acceptance_criteria:
    - "无自然桥接时不发送、不记主动 @ 配额、不更新回应检测。"
    - "同一候选/话题在 skip TTL 内不重复付费；新消息或候选变化后可重试。"
    - "实现讨论相关时先承接当前话题再提出单一轻量问题。"
    - "Participation 收到 trigger_msg_id、topic_id、reason_flags 和触发消息摘要。"
    - "proactive_at 指令前置、普通回复、硬闸门、配额/冷却和 Participation WAIT 不变。"
    - "日志可区分 selected、skip、sent、send_failed、reply/ignore。"
  evidence_provenance:
    schema_version: 2
    head_commit: "88511cc9b0c71f4781db24278ee14da5af495dd2"
    generated_plan_path: "docs/plans/2026-09-08-gitnexus-plan-natural-proactive-at.md"
    global_dirty_digest:
      algorithm: "sha256"
      canonicalization: "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records"
      value: "3f3d85703f480b60850c0c3d04efccb42607c161c4dee19512c90633b0d0dbd7"
    cited_path_manifest:
    - {path: ".env", state: untracked, object_kind: {head: absent, index: absent, worktree: absent, untracked: regular}, head_digest: absent, index_digest: absent, worktree_digest: absent, untracked_digest: "sha256:0a46e1f6a0971562f4915228c35729eb91496219350312f2e32c28f48f99ce5a"}
    - {path: ".env.example", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:18561d333d9be61c696c7d0cdcda72a20d5fdb64ced1be3b4a3725b5ca857011", index_digest: "sha256:18561d333d9be61c696c7d0cdcda72a20d5fdb64ced1be3b4a3725b5ca857011", worktree_digest: "sha256:90ee1a66a1042e0dc47bb11fc2ee2009792f48a71510c52933ae573c9b1d772f", untracked_digest: absent}
    - {path: "config/settings.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:ead69e4237c9d86e5c57b3fe509f6f9f65599435559eecf7fdf1ae66de7b8b41", index_digest: "sha256:ead69e4237c9d86e5c57b3fe509f6f9f65599435559eecf7fdf1ae66de7b8b41", worktree_digest: "sha256:96bd4424684650daed41d4c34e35f129aa0eaff2e7f9891800d25099a4dadffe", untracked_digest: absent}
    - {path: "core/context.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:68bd188e50ccedd3bf1aaed6c81b348a60e3efc968efcb3ea24dc62557398673", index_digest: "sha256:68bd188e50ccedd3bf1aaed6c81b348a60e3efc968efcb3ea24dc62557398673", worktree_digest: "sha256:af55bd32335a92fce6d79b07f7dfb7ff4600b15d6dcc6329caacf0a170e435f9", untracked_digest: absent}
    - {path: "core/pipeline.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:0dc49bedb5407e64b4100d9737bd6d4ca9c87121e511db7f48e2f309d9893e2c", index_digest: "sha256:0dc49bedb5407e64b4100d9737bd6d4ca9c87121e511db7f48e2f309d9893e2c", worktree_digest: "sha256:43fa4c21fde92262c3a89d9989976122599b57e5c6efcb7b3f2d35f86e95a7f7", untracked_digest: absent}
    - {path: "design_docs/Stella_主动插话机制实现方案.md", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:5b3aabc7308dd2599901eafee4b94a643c7b34300cf6a1c6bb0ec512a67afc2e", index_digest: "sha256:5b3aabc7308dd2599901eafee4b94a643c7b34300cf6a1c6bb0ec512a67afc2e", worktree_digest: "sha256:5b3aabc7308dd2599901eafee4b94a643c7b34300cf6a1c6bb0ec512a67afc2e", untracked_digest: absent}
    - {path: "design_docs/bug_report/bug_report_2026_8_31#1.md", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:b92faff5882154f453abaf70ff57bdf25637ba318959830ef8b0af18035ae4d0", index_digest: "sha256:b92faff5882154f453abaf70ff57bdf25637ba318959830ef8b0af18035ae4d0", worktree_digest: "sha256:bcc40eb6bb11294be0600c8e4acf82582452d549d27f2c9cb221ca50a268c6c9", untracked_digest: absent}
    - {path: "docs/architecture.md", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:2d2af7617c3d91c171d34f23a943ed71bea6e659303e79fd1d51364e2e98c401", index_digest: "sha256:2d2af7617c3d91c171d34f23a943ed71bea6e659303e79fd1d51364e2e98c401", worktree_digest: "sha256:c4089e1856d1718523f00ae6076267f0c03c18264d7bc89a81f2881ae65eec52", untracked_digest: absent}
    - {path: "docs/configuration.md", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:866f42ca531dbd4a52bfc73df2029ca3d2dd40323a44397ed7bbe1360177b38f", index_digest: "sha256:866f42ca531dbd4a52bfc73df2029ca3d2dd40323a44397ed7bbe1360177b38f", worktree_digest: "sha256:029e1a7e69d5b5caec8bd2c94f5515d61f5bd31ba2cd3a4f7008c7e6f6714539", untracked_digest: absent}
    - {path: "docs/development.md", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:b9d3e3605e8d742cb634ba47a4acad0a42bf46f9e27d151c5377f4e623cd42b7", index_digest: "sha256:b9d3e3605e8d742cb634ba47a4acad0a42bf46f9e27d151c5377f4e623cd42b7", worktree_digest: "sha256:fbaab977e0fdfa552de94bb8298a01424e150d11860fe178ceb77dc9ad0a66f9", untracked_digest: absent}
    - {path: "memory/participation/__init__.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:404265ee5abc30535576a8f24d0504bcb9e0b9ad4ee80253dc954d3a3a1be47a", index_digest: "sha256:404265ee5abc30535576a8f24d0504bcb9e0b9ad4ee80253dc954d3a3a1be47a", worktree_digest: "sha256:404265ee5abc30535576a8f24d0504bcb9e0b9ad4ee80253dc954d3a3a1be47a", untracked_digest: absent}
    - {path: "memory/participation/decision.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:faf972c40a499325e46455116b88e13f60fb84fe1d908cf268d56222b10ecfbf", index_digest: "sha256:faf972c40a499325e46455116b88e13f60fb84fe1d908cf268d56222b10ecfbf", worktree_digest: "sha256:faf972c40a499325e46455116b88e13f60fb84fe1d908cf268d56222b10ecfbf", untracked_digest: absent}
    - {path: "memory/participation/observability.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:1a20543e61f371c86cd3f958383e62a8613ac848b01e5a7e5becb14e49f350d5", index_digest: "sha256:1a20543e61f371c86cd3f958383e62a8613ac848b01e5a7e5becb14e49f350d5", worktree_digest: "sha256:1a20543e61f371c86cd3f958383e62a8613ac848b01e5a7e5becb14e49f350d5", untracked_digest: absent}
    - {path: "memory/participation/state.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:2c7a61c1b1f15a80df7d0aab0942aa26480b56cc705ec7227fb65baad25a8f34", index_digest: "sha256:2c7a61c1b1f15a80df7d0aab0942aa26480b56cc705ec7227fb65baad25a8f34", worktree_digest: "sha256:c78af896d4880ad79fef8b1a798e4e51b051262d74b288ac44d0cac13bae6dce", untracked_digest: absent}
    - {path: "memory/pre_processors.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:281331cad478029c4d0156b9498b2a4bb946cd4b7e699eef21c65ffc115bf7c5", index_digest: "sha256:281331cad478029c4d0156b9498b2a4bb946cd4b7e699eef21c65ffc115bf7c5", worktree_digest: "sha256:4b754b571639fc56dd46230aaf5f19ffc897ce3e53719bc1aeb7aa86316b02dd", untracked_digest: absent}
    - {path: "memory/proactive.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:df131e1c0c580de223e2406bdd49ae42cd9bbec5cd23b2ec9e543b6f58c3fe17", index_digest: "sha256:df131e1c0c580de223e2406bdd49ae42cd9bbec5cd23b2ec9e543b6f58c3fe17", worktree_digest: "sha256:017b8861efc2a554ffe857f0376d6e1e5248a30458e479f5ec007fbd7800fa7d", untracked_digest: absent}
    - {path: "memory/proactive_gate.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:1c79f5cd0b873f5e56ad6a9d62bb59562be4c76157f7229a0a40209b0111ba97", index_digest: "sha256:1c79f5cd0b873f5e56ad6a9d62bb59562be4c76157f7229a0a40209b0111ba97", worktree_digest: "sha256:1c79f5cd0b873f5e56ad6a9d62bb59562be4c76157f7229a0a40209b0111ba97", untracked_digest: absent}
    - {path: "memory/proactive_prompt.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:0f5f3c878c33d6a8308cb515e29970f5233a52fa92d854a1a168a6135304f22b", index_digest: "sha256:0f5f3c878c33d6a8308cb515e29970f5233a52fa92d854a1a168a6135304f22b", worktree_digest: "sha256:0f5f3c878c33d6a8308cb515e29970f5233a52fa92d854a1a168a6135304f22b", untracked_digest: absent}
    - {path: "memory/proactive_state.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:180e59d62943e893efb139d35b2107bc5975667024d9f5e085303a7b857ced8b", index_digest: "sha256:180e59d62943e893efb139d35b2107bc5975667024d9f5e085303a7b857ced8b", worktree_digest: "sha256:180e59d62943e893efb139d35b2107bc5975667024d9f5e085303a7b857ced8b", untracked_digest: absent}
    - {path: "memory/proactive_target.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:db054adb0fb542183204e8d04ae9469b177c7f62064323edb36dea8caa035ac2", index_digest: "sha256:db054adb0fb542183204e8d04ae9469b177c7f62064323edb36dea8caa035ac2", worktree_digest: "sha256:ab14fc1e6cac5afc5ae5ecd65a9de151292fae9df1ffc7d1a182e7a6bc48776b", untracked_digest: absent}
    - {path: "stella_project/plugins/bot_main/ai_gateway.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:6c905f80796512ca4b049e1bbb286a904e447adf27c95b7a2b3eebb353f2b33c", index_digest: "sha256:6c905f80796512ca4b049e1bbb286a904e447adf27c95b7a2b3eebb353f2b33c", worktree_digest: "sha256:38c602aa090b200e2b655970cb22070ed413d0abdbbc5381c05c4604363007fd", untracked_digest: absent}
    - {path: "tests/benchmark/participation/reports/20260906_194042_summary.md", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:8bfa8d409750e54549464a40d55e8df87705e443f5a010532061ad0b1fc16844", index_digest: "sha256:8bfa8d409750e54549464a40d55e8df87705e443f5a010532061ad0b1fc16844", worktree_digest: "sha256:faf5c9c101aa69614ba48abc62499505f66118587989819953092db5ec658441", untracked_digest: absent}
    - {path: "tests/benchmark/participation/runner.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:37ab739b3537048c6c9b4d645a8ba7098644ea6e8696bd49eec7fe4d94447577", index_digest: "sha256:37ab739b3537048c6c9b4d645a8ba7098644ea6e8696bd49eec7fe4d94447577", worktree_digest: "sha256:37ab739b3537048c6c9b4d645a8ba7098644ea6e8696bd49eec7fe4d94447577", untracked_digest: absent}
    - {path: "tests/test_participation.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:f095125630be57dd1aa2c90a4783c55251662a8f58d1ff3afd10a704a4083b44", index_digest: "sha256:f095125630be57dd1aa2c90a4783c55251662a8f58d1ff3afd10a704a4083b44", worktree_digest: "sha256:d2f08e008c8b1ccbb2afd4c0fe52c65c0d6a7dc40f954721c015613947a7e4bc", untracked_digest: absent}
    - {path: "tests/test_pipeline_compose.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:f12660db3f7a36dde668d2b4a359fe849c25c056556bde6b71d57f3d19bba84c", index_digest: "sha256:f12660db3f7a36dde668d2b4a359fe849c25c056556bde6b71d57f3d19bba84c", worktree_digest: "sha256:18a996300982e1f13a5cf5dd53301ae5db9039041464ea33df369d2eff6cbecd", untracked_digest: absent}
    - {path: "tests/test_planner.py", state: unstaged, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:a840745bc70e37eebf31c36cf2d56edd52600995507c003a42e5acca82f7b7db", index_digest: "sha256:a840745bc70e37eebf31c36cf2d56edd52600995507c003a42e5acca82f7b7db", worktree_digest: "sha256:4b441a3387c88e4c65fefe6eef28f700d3fb73dcd727b98a59c1dc78d11791c3", untracked_digest: absent}
    - {path: "tests/test_proactive_at_flow.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:401783b75c07092233ab0f05c9aafa182c826bf63d7ac44835ddf311e353b178", index_digest: "sha256:401783b75c07092233ab0f05c9aafa182c826bf63d7ac44835ddf311e353b178", worktree_digest: "sha256:401783b75c07092233ab0f05c9aafa182c826bf63d7ac44835ddf311e353b178", untracked_digest: absent}
    - {path: "tests/test_proactive_gate.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:8346a0882e5c232c6c4ec9f1800b535204113986531cfa0258c7cee7492fe1e9", index_digest: "sha256:8346a0882e5c232c6c4ec9f1800b535204113986531cfa0258c7cee7492fe1e9", worktree_digest: "sha256:8346a0882e5c232c6c4ec9f1800b535204113986531cfa0258c7cee7492fe1e9", untracked_digest: absent}
    - {path: "tests/test_proactive_prompt.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:3d6a853d79a62b8e1dccbef700d3b26ff1eda012497c8975c2260df3b95c5501", index_digest: "sha256:3d6a853d79a62b8e1dccbef700d3b26ff1eda012497c8975c2260df3b95c5501", worktree_digest: "sha256:3d6a853d79a62b8e1dccbef700d3b26ff1eda012497c8975c2260df3b95c5501", untracked_digest: absent}
    - {path: "tests/test_proactive_target.py", state: clean, object_kind: {head: regular, index: regular, worktree: regular, untracked: absent}, head_digest: "sha256:b5ce0df522b7243e46e61d038240308a0d75f7e5ab7ca13d790eba5891821231", index_digest: "sha256:b5ce0df522b7243e46e61d038240308a0d75f7e5ab7ca13d790eba5891821231", worktree_digest: "sha256:b5ce0df522b7243e46e61d038240308a0d75f7e5ab7ca13d790eba5891821231", untracked_digest: absent}
  primary_symbols:
    - {symbol: "proactive_speak_job", file: "stella_project/plugins/bot_main/ai_gateway.py", lines: "1395-1428", role: "定时主动 @ 入口"}
    - {symbol: "_proactive_at_user", file: "stella_project/plugins/bot_main/ai_gateway.py", lines: "1062-1170", role: "主动 @ 选人、生成、发送、记账"}
    - {symbol: "pick_target", file: "memory/proactive_target.py", lines: "221-297", role: "活跃用户/候选目标选择"}
    - {symbol: "record_group_chat", file: "stella_project/plugins/bot_main/ai_gateway.py", lines: "340-389", role: "PASSIVE 消息与 Participation 入口"}
    - {symbol: "_proactive_speak_for_group", file: "stella_project/plugins/bot_main/ai_gateway.py", lines: "1266-1392", role: "普通主动插话共用执行器"}
  related_symbols:
    - {symbol: "build_instruction", relationship: "CALLS", relevance: "主动 verify/coldstart Prompt"}
    - {symbol: "can_speak", relationship: "CALLS", relevance: "硬性主动发言闸门"}
    - {symbol: "ParticipationDecision", relationship: "PRODUCES", relevance: "已有 topic/trigger/reason 元数据"}
    - {symbol: "ParticipationManager.observe", relationship: "CALLS", relevance: "普通插话本地评分"}
    - {symbol: "Pipeline.run", relationship: "CALLS", relevance: "现有单次生成与上下文组装"}
    - {symbol: "_compose_prompt", relationship: "CALLS", relevance: "proactive_at 指令前置保护"}
  execution_path:
    - "定时任务遍历群并先调用 _proactive_at_user。"
    - "硬闸门只判断总开关、静音、睡眠、醒来缓冲、群冷却和新消息门槛。"
    - "pick_target 按活跃、配额、冷却和候选 confidence 选人，不判断承接。"
    - "Prompt 强制把候选/话题转成问题，Pipeline 以 proactive_at 指令前置生成。"
    - "当前只对生成文本去重，然后发送、record_at、启动回应检测。"
    - "Participation 当前只透传 mode 固定文案。"
  pdg_constraints:
    - {description: "当前索引无 PDG 层。", affected_statements: [], implementation_consequence: "按源码和新增测试验证控制流；需要时另行 analyze --pdg。"}
  architectural_patterns:
    - {pattern: "统一主动硬闸门", example_location: "memory/proactive_gate.py:114-152", usage_guidance: "保留硬闸门；自然承接是其后的软决策。"}
    - {pattern: "群级 asyncio.Lock", example_location: "stella_project/plugins/bot_main/ai_gateway.py:1293-1309", usage_guidance: "skip 与发送前复核遵守同一把群锁。"}
    - {pattern: "主动输出统一去重/记账", example_location: "stella_project/plugins/bot_main/ai_gateway.py:1359-1380", usage_guidance: "skip 不走 mark_spoke/record_spoken/note_stella_spoke。"}
  files_to_modify:
    - {file: "stella_project/plugins/bot_main/ai_gateway.py", symbols: ["_proactive_at_user", "record_group_chat", "_spawn_participation_speak", "_proactive_speak_for_group"], intended_change: "统一 skip、承接证据、记账和日志。"}
    - {file: "memory/proactive_prompt.py", symbols: ["build_instruction", "build_verify_instruction", "build_coldstart_instruction"], intended_change: "Prompt 先判断承接，允许严格 skip。"}
    - {file: "memory/proactive_target.py", symbols: ["ProactiveTarget", "pick_target"], intended_change: "保持选人策略，接入负向冷却/证据。"}
    - {file: "memory/proactive.py", symbols: ["ProactiveController.active_users", "ProactiveController.record_message"], intended_change: "维护短期 skip 生命周期。"}
    - {file: "memory/participation/__init__.py", symbols: ["ParticipationManager.snapshot"], intended_change: "补充有限 topic/速度/消息快照。"}
    - {file: "memory/participation/observability.py", symbols: ["log_decision"], intended_change: "区分 allow/skip/sent/failed。"}
    - {file: "config/settings.py", symbols: ["主动自然度配置段"], intended_change: "增加灰度和 TTL。"}
    - {file: ".env.example", symbols: [], intended_change: "增加部署示例。"}
    - {file: "docs/configuration.md", symbols: [], intended_change: "记录开关和灰度。"}
  tests:
    - {file: "tests/test_proactive_prompt.py", scenarios: ["verify/coldstart 允许 skip", "删除接不上仍直接问", "保留一句话与隐私护栏"]}
    - {file: "tests/test_proactive_target.py", scenarios: ["同一候选/话题 TTL 内冷却", "新消息/候选变化解除", "现有选人优先级不变"]}
    - {file: "tests/test_proactive_at_flow.py", scenarios: ["skip 不发送/不 record_at/不更新回应检测", "正常输出仍记账", "发送失败不污染成功状态"]}
    - {file: "tests/test_participation.py", scenarios: ["trigger/topic/reason 到达生成", "skip 不增加主动发言统计", "既有评分场景不回归"]}
    - {file: "tests/test_pipeline_compose.py", scenarios: ["proactive_at 指令仍前置", "普通拼接不变"]}
    - {file: "tests/test_planner.py", scenarios: ["proactive_at 不新增 Planner", "普通 proactive WAIT 仍有效"]}
  verification_commands:
    - "python -m pytest tests/test_proactive_prompt.py tests/test_proactive_target.py tests/test_proactive_at_flow.py tests/test_proactive_gate.py tests/test_pipeline_compose.py tests/test_planner.py -q"
    - "python -m pytest tests/test_participation.py -q"
    - "python -m pytest tests -q"
    - "pytest tests/ --cov=. --cov-branch -n auto --dist loadgroup"
    - "python -m tests.benchmark.participation.runner --db <脱敏数据库> --limit 5000 --no-embedding"
  risks:
    - "模型不遵守 skip 标记；解析失败必须 fail-closed。"
    - "过度保守降低记忆采集；联合 skip/发送/回应/晋升率和人工抽样评估。"
    - "无桥接候选仍付出一次已有 Replyer 成本；负向冷却避免连续付费。"
    - "群锁内复核不足会发送过期问题；发送前必须复核。"
    - "日志泄露聊天内容；INFO 级只记录结构化元数据。"
  assumptions:
    - "用户接受自然度优先、主动记忆采集减少；由灰度验证。"
    - "Participation 状态通常可用；缺证据时主动 @ 保守跳过。"
    - "负向冷却先为进程内 TTL，不新增表。"
    - "当前 .env 只作环境证据，不修改或提交。"
  open_questions:
    - "skip TTL 默认值与按群覆盖方式。"
    - "无当前 topic 时是否完全禁止冷启动；建议第一版禁止。"
    - "是否后续加入本地 embedding 预筛。"
    - "默认 enforce 的人工自然度阈值和切换时点。"
  avoid:
    - "不要把主动 @ 改成 trigger=proactive 或移除 proactive_at 指令前置。"
    - "不要把 skip 记为 record_at，也不要把未回应替代自然度 skip。"
    - "不要重写 pick_target 的 confidence、时效和 last_asked 规则。"
    - "不要用完整聊天原文扩张状态或 INFO 日志。"
    - "不要同时调 Participation 权重/阈值或修改当前 .env。"
    - "没有 PDG 层时不要声称存在 statement-level 依赖。"
```

## 12. Assumptions and Open Questions

### Assumptions

[assumed] 为了自然度，主动记忆采集允许少问一些；通过 shadow 指标和人工抽样确认。

[assumed] Participation 状态可能因重启、LRU 或开关关闭而缺失；缺证据时主动 `@` 保守跳过。

[assumed] 负向冷却先采用进程内 TTL，不新增数据库迁移；跨重启保持另立任务。

[verified] 工作区 `.env` 在 provenance 中是 `untracked`；本计划只读取、不修改、不作为交付变更。

### Open Questions

1. skip TTL 默认值及按群配置方式。
2. 冷启动无当前 topic 时是否完全禁止；建议第一版禁止。
3. 无桥接样本的单次 LLM 成本是否可接受。
4. 何种自然度、回应率和候选晋升率组合允许默认切到 `enforce`。

### Explicitly Deferred

- 不重调 Participation 权重/阈值。
- 不重复处理已经修复的候选重复、时效 TTL、回应判定和访问时间语义问题。
- 不在本次修复中把自然度结果持久化到数据库。

## 13. Definition of Done

1. 当前话题与候选无关时不发送主动问题；skip 不消耗配额、不更新回应检测、不增加主动发言统计。
2. 实现讨论相关时先桥接当前话题，再提出单一轻量问题。
3. 同一候选/话题在 skip TTL 内不重复触发生成；新消息或候选变化可解除。
4. Participation 生成输入包含真实 trigger/topic/reason 证据；无承接时可安全 skip。
5. `proactive_at` 指令前置、普通回复、硬闸门、配额/冷却、Participation WAIT 及回归测试保持通过。
6. 日志可区分 selected、skip、sent、send_failed、reply/ignore，支持人工抽样和脱敏回放。
7. 重点测试与 benchmark 通过；默认 enforce 的切换依据已记录，当前 `.env` 未被修改。
