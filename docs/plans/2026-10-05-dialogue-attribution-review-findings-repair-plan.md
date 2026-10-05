# Stella 归属复发修复——复核发现整改计划

> 日期：2026-10-05，Asia/Shanghai。
> 输入：[复核报告](../reports/2026-10-05-dialogue-attribution-plan-execution-review.md)（判定 NOT READY，F1—F13）。
> 基线：分支 feat/dialogue-attribution-role-repair @ f752538（CI 10 job 全绿，但功能判定 NOT READY）。
> 状态：**仅计划。本文所有"拟"字接口为拟实施；不打开任何开关、不动生产库、不发 QQ。**

## 1. 目标与边界

将复核报告 13 项发现全部整改为可验证的修复：先修确定性缺陷，再接通运行链，最后重建验收。整改完成前，三个开关（`PERSONAL_MEMORY_SHARE_ENABLED`、`PROACTIVE_VERIFICATION_CONTRACT_MODE`、`REPLY_ATTRIBUTION_GUARD_MODE`）保持默认关闭；不得以"打开开关"作为任何阶段的验证手段。

不在本计划范围：更换模型、部署 Laya、重建身份引擎、Dashboard/Cometa 扩展。模型重放、native 构建与 QQ 灰度由用户执行，本计划负责把脚本、清单与判据准备好。

## 2. 发现 → 阶段映射

| 发现 | 一句话 | 阶段 |
| --- | --- | --- |
| F2 | Nox 复合纠正原句被整句否定 guard 拒绝 | P1 |
| F10 | 私聊 idle 收尾仍传负 group_id，短尾不沉淀 | P1 |
| F3 | 共享复制 SQL 引用 candidates 不存在的列 | P3 |
| F4 | 共享授权无本人/Bot/来源绑定，跨用户串扰 | P3 |
| F5 | 撤回 bump `user:{uid}`，规范键是 `person:{platform}:{bot_id}:{uid}` | P3 |
| F13 | regrant 返回成功但副本仍 DEPRECATED、来源不更新 | P3 |
| F11 | 主动合同 digest 是 TODO、桥接比较对象错误 | P4 |
| F12 | reply_plan 解析器是占位、引用丢作者、correction_ack 不检查 | P4 |
| F1 | R3/R5/R6 零业务接线，开关无消费者 | P5 |
| F6 | 数据修复按全局 fact_key 去重，会杀合法双受众副本 | P6 |
| F7 | 孤儿判断用身份 revision 表当会话注册表 | P6 |
| F8 | 撤回把 audience 写回 status，无 CAS/列级审计 | P6 |
| F9 | wrong_space 查询形状与真实 09:00 污染行不匹配 | P6 |
| R0/R8 缺口 | 场景 oracle、生产条件模型重放、native parity、灰度 | P0 / P8 |

阶段顺序对复核报告 §5 返工顺序做了一处依赖驱动的调整：**接线（P5）放在合同模块修好（P3/P4）之后**——先把有缺陷的 helper 接上线只会把缺陷送进发送链。P1/P2 独立可并行，P6 与 P5 无依赖可并行。

## 3. P0 冻结场景与独立 oracle（先行，无业务改动）

对应原计划 R0 与复核 §3「缺执行证据」。

1. 把四个现场（09:00:46 / 13:19:51 / 13:22—13:31 / 14:09:19）固化为可重放夹具：输入消息序列、来源 row、期望判定（正确归属/正确作者/拒发）。存 `tests/fixtures/dialogue_attribution/`。
2. 为每类现场写**独立于实现**的判定函数（oracle）：给定最终发送文本与来源集合，按作者/对象/极性输出 pass/fail。oracle 不 import 被测模块，供 P7/P8 复用。
3. 记录生产参数基线：persona 完整字节与 hash、endpoint/model、temperature、max_tokens、预算配置（缺值显式记 unknown，不填默认）。

出口：夹具 + oracle + 基线清单入库存档，全部只读。

## 4. P1 身份复合纠正（F2）

文件：`memory/conversation_identity.py`。

现状（已核实）：`parse_self_alias` 在 :117 对**整句**检查 `_NEGATION_COND_MARKS`，含「不是」即返回 None——「我是Nox，不是红中没摸鱼」「我叫Nox，不叫红中」全被丢弃；`process_message_identity`（:629）因此不登记。关系句「我是她姐」「我是你教父了」不在 `_ROLE_TERMS` 拦截范围内，仍会落库。

拟实施：

1. 新增结构化解析 `parse_self_claim_structured(text) -> SelfClaim | None`（dataclass：`alias`、`supersedes`、`excluded_aliases: list[str]`、`parser_version`）：
   - 问句/引号/超长仍整句拒绝（沿用 :113/:109）；
   - 否定标记**不再整句拒绝**，改为分句后逐句分类：主句=首个自称模式命中；其余分句归类为 ①名字排除（「不是X」「不叫X」，X 进 `excluded_aliases`）②活动/状态否认（含「没」「在」等非名字结构，忽略）③其他（整句 ambiguous → None）；
   - `_SELF_PATTERNS` 主句命中后，新名字仍过现有 normalize/角色词/长度检查。
2. 关系描述拦截：`_ROLE_TERMS` 增补亲属词（姐/哥/弟/妹/爸/妈/叔/姨/教父/教母/干爹/干妈等）；别名含人称代词（你/我/他/她/它/谁）一律拒绝——「她姐」「你教父了」由此挡下。
3. `process_message_identity` 改走结构化结果：同一事务内登记声明（带 `parser_version`）、按 `excluded_aliases` 与 `supersedes` 失活旧别名、推进 identity revision（现有 compact CAS 不变）。
4. 旧 `parse_self_alias` 保留为 tuple 包装（内部调结构化版），现有调用方与测试不破。

验收反例（全部入 `tests/test_conversation_identity.py`）：

- 「我是Nox，不是红中没摸鱼」→ 登记Nox；「红中」「没摸鱼」均不落别名；下一轮 capsule 读到Nox；
- 「我叫Nox，不叫红中」→ 登记Nox 且**旧红中 self_alias 失活**（若存在）、revision+1；
- 「我是她姐」「我是你教父了」「我是管理员」→ 零写入；
- 「我是谁」「这是Lumi不是我」「如果我是Nox」→ 零写入（既有负例不回退）。

## 5. P2 私聊 idle 收尾（F10）

文件：`stella_project/plugins/bot_main/ai_gateway.py`（`session_idle_check_job`，:3953）、`memory/consolidator.py`、`memory/conversation_registry.py`。

现状（已核实）：idle 对 `idle_session_groups()` 的每个 key 调 `end_session(group_id)` 后 `maybe_consolidate(group_id)`（:3963）；私聊 key 为负存储 ID，被 `maybe_consolidate` :2010 的负群号 guard 拒绝——compact 状态已清、整合没跑。定时排空 `drain_registered_sessions` 有批次门（`_batch_size(False)`≈30），backlog=5 的短尾永远轮不到。

拟实施：

1. `conversation_registry` 增 `lookup_by_storage_session_id(conn, storage_id) -> ConversationRef | None`（表已有该列索引，`ref_from_row` 现成）。
2. idle 改为：每个 idle key 先查注册表——命中 → `maybe_consolidate(conversation_ref=ref)`；正群号且未注册 → 旧 `maybe_consolidate(group_id)` 路径；负 key 未命中 → 记原因跳过，绝不伪造 ref。
3. `_pending_groups` 去重键本来就是 `storage_session_id`，即时/idle 两触发天然互斥；补并发测试确认无双消费、无 checkpoint 倒退。
4. 定时排空保持批次门（进行中会话不凑整批）；**已 idle 结束的短尾由第 2 步兜底**——测试：backlog=5 + idle 到期 → 恰好整合一次。

出口：即时/idle/定时三触发在私聊上全部落到同一 `ref.memory_space`；失败与取消不推进 checkpoint（沿用现有合同）。

## 6. P3 共享授权重写（F3/F4/F5/F13）

文件：`memory/personal_sharing.py`（重写）、`memory/schema.py` + `memory/migrations.py`（v18）、`memory_rust/backend.py` + `memory_rust/native/src/schema.rs`（版本常量同步）。

现状（已核实）：复制 SQL 引用 candidates 不存在的 `confirmation_count`/`last_confirmed_at`（:257/:261；memories 表 :414 有这两列，**仅 candidates 路径必炸**）；复制/撤回只按 `fact_key + audience` 匹配不绑 owner（:216-222/:249/:275/:329-345）；版本键是 `user:{uid}`（:185/:349）而检索读 `person:{platform}:{bot_id}:{uid}`（retrieval_v2.py:598-609，ownership.py:52）；regrant 只翻授权状态，existing 检查忽略 status（:216-225），副本不复活、来源不更新；`detect_sharing_intent` 的「在群里」关键词使「我在群里玩游戏」「他说可以在群里分享这件事」误报 true。

拟实施：

1. **schema v18**（幂等 additive）：`personal_memory_sharing` 加列 `owner_key`、`subject_key`、`platform`；新表 `personal_memory_sharing_copies(grant_id, table_name, record_id, prior_status, created_at, PRIMARY KEY(grant_id, table_name, record_id))` 作为副本台账。Python/Rust `MEMORY_SCHEMA_VERSION` 同升，`test_migrations.py` 链终点断言同步（v17 曾漏，前车之鉴）。
2. **owner/source 绑定**：授权主键语义改为 `(owner_key, subject_key, fact_key)`，`owner_key = person_owner_key(platform, bot_id, user_id)`。grant 前服务端核验：source row 存在于 `group_messages`、作者==user、会话匹配、非 Bot——失败返回 `source_unverified`。
3. **fact 定位与 pending**：按 owner_key+fact_key 找 PRIVATE_ONLY 原件（memories/candidates）；找到 → active 并复制；没找到 → `status=pending` 落库，等整合写入后同事务提升（提升挂接点在 P5）。多事实歧义 → pending + 澄清话术，不猜。
4. **复制 SQL 按真实 DDL**：candidates 用实际列（`evidence`、`source_message_ids`、`occurrence_count`、`first_seen_at`、`source_kinds`、`verification_contract_json`…）；副本写 `owner_type=PERSON + owner_key + compat namespace`（`person_compat_space`）、`audience='USER_SHARED'`；每条副本记入台账；同事务写 `memory_evidence` 与 `sharing_audit_log`。
5. **撤回按台账**：只失活本 grant 台账内的 record_id（不再按 fact_key 全表 UPDATE），保护其他 grant 与合法 PRIVATE_ONLY 原件；**bump 规范键** `person_owner_key`（strict=True，事务内，失败整体回滚）。
6. **regrant（F13）**：更新 grant 的 source 字段为新授权消息；按台账把本 grant 副本恢复到 `prior_status`（台账在撤回时记录）；不复活其他 grant、不恢复非法历史。
7. **意图检测收紧（F4）**：改为「分享范围词（在群里/群里也/群里）**与**分享动词（记得/记住/能说/提一嘴/也能用）共现 + 第一人称主语」；引号/转述（他说/她说/听说）、否定、问句先拒；纯话题句（我在群里玩游戏）不得命中。词表有界并配正反例单测。

验收反例（临时库 = **正式 v18 全 DDL** + memories + candidates + FTS + evidence；全部入新增 `tests/test_personal_memory_sharing.py`）：

- 复制不再抛 `no column named confirmation_count`，副本字段完整；
- 用户 123 授权同键事实 → 仅 123 的 USER_SHARED 行出现；456 零变化（跨用户隔离）；跨 Bot 同人同理；
- 「他说可以在群里分享这件事」「我在群里玩游戏」→ 不授权；
- grant → 真实 `retrieve_memories`（规范 owner、默认阈值）命中 → revoke 提交 → **暖缓存立即 miss**（同进程）+ 新进程 miss（版本落库）+ FTS/embedding/native 同步不可见；
- grant → revoke → regrant 全程：副本复活、来源更新为新消息、其他 grant 副本未动；
- pending → 整合写入 → 同事务 active+复制；重复消息重放幂等。

## 7. P4 合同 helper 补全（F11/F12）

文件：`memory/proactive_contract.py`、`core/dialogue_attribution.py`。

现状（已核实）：`validate_contract_consistency` 的 digest 校验是 TODO（:96-98）；`validate_bridge_event` 拿 `bridge.target_user_id != contract.fact_object_id` 比较（:154）——Nox 主体的真实承接被拒、第三人对象的伪造桥接放行；`parse_reply_plan` 恒返回 `not_implemented`（:106）；`validate_evidence_references` 只查 ID 存在+预算；`render_evidence` 把人类原话「我开发 Stella」渲染成 Bot 裸台词；`apply_guard_decision` 只对 `current_response` 做风险检查，`correction_ack` 任意内容原样放行（:480-497）。

拟实施：

1. `VerificationContract` 增 `selected_target_user_id` 字段；`validate_contract_consistency` 落地：重算候选内容 digest（与 consolidator 同一归一化）比对、候选 status 仍在册、`source_row_ids` 逐条在 `group_messages` 存在且作者/会话匹配合同——任一漂移返回具体 reason。
2. `validate_bridge_event` 改为：`bridge.target_user_id == contract.selected_target_user_id`；`recent_message_ids` 必须是服务端构建的「该目标在该会话近期消息」集合的子集，digest 服务端重算——编造 ID/摘要拒绝。
3. `parse_reply_plan` 实现 versioned 协议解析（`<reply_plan>` + 槽位），未知标签/多 `current_response`/截断 → `(None, reason)`；解析不了就走兜底路径，enforce 下不原样放行。
4. `validate_evidence_references` 增强：`quote_references` 只能引 `evidence_type=message`，`verified_fact_references` 只能引 `is_verified=True` 的 `verified_fact`；引用会话必须等于当前会话或在合法受众内；普通 message 冒充 verified_fact 拒绝。
5. `render_evidence` 带作者边界：消息引用渲染为服务端模板「{作者可信展示名}说过：{原文}」；事实引用按服务端模板填角色槽。模型供给的 author/正文一律不进渲染。
6. `correction_ack` 改为服务端受限模板：模型只给是否承认的标志，承认文本由当前可信纠正证据生成（对象不明就承认弄错对象，不编名）；风险词检查覆盖全部自由文本槽。补现场风险词：「刚才是谁说」「说我脏手」「装失忆」等（词法只是可测防线，语义保证仍靠解析+服务端渲染，边界照原计划 §6.6 表述）。

验收反例：空证据 + correction_ack「对，是你刚才说我脏手，又装失忆了」→ enforce 下 reject/fallback；「我开发 Stella」的人类原话引用渲染后保留作者边界；同 ID 改写内容的候选、空来源候选、Nox 主体桥接、第三人伪造桥接全部拒绝；合法 variant 仍可选发（不能全靠 skip 过关）。

## 8. P5 运行链接线（F1，最大项）

文件：`core/context.py`、`core/runtime/turn_service.py`、`memory/pre_processors.py`、`memory/prompt_builder.py`、`memory/post_processors.py`、`stella_project/plugins/bot_main/ai_gateway.py`、`memory/consolidator.py`、`core/observability/flow_catalog.py`。

现状（已核实）：三个开关零消费者（settings.py:1532-1546）；posthook 仅 parse_output=100/bad_phrase=80/split_lines=60/log_thought=40（ai_gateway.py:656-659）；`finalize_turn` 只做 trace+hooks（turn_service.py:601）；主动入口直接 `build_instruction(target)` 当 ctx.message、ctx.lines 拼接直发（ai_gateway.py:3183/:3248）；ChatContext 投影仍是 schema 4。

拟实施（开关全 off 时每条路径必须 no-op，老行为逐字节不变）：

1. **ChatContext 投影 4→5**：新增 `retrieval_query: str`、`verification_contract/attribution_evidence/attribution_decision: dict|None`、`reply_disposition: str|None`；round-trip 用例 + 旧投影缺字段按 unknown/feature-off 处理；native bridge 契约检查过一遍。
2. **typed retrieval_query**：主动验证场景由合同主题+目标近期真实对话生成查询文本，`_build_user_context_v2` 优先消费 ctx.retrieval_query；不再拿整段指令模板当查询（embedding/Python/Rust/detect_mode/topic cache 同一输入）。
3. **R6 guard 进核心**：证据表（服务端从可信近期消息+受众内已验证事实+当前纠正构建，≤16 单元/512 token，`fit_conversation_parts` 原子裁剪，引用 ID 集合==实际保留集合）在 prepare 侧挂 ctx；`finalize_turn` 在 parse_output 之后、bad_phrase 之前执行 guard（等价 priority=90，实现放 TurnService 使 legacy Pipeline 与 native facade 共用）；guard 拒绝写入 `reply_disposition`，`split_lines` 的「......？」默认值不得覆盖 suppressed/fallback 处置；raw_output 与 prompt 照旧留痕，决定/原因/最终 digest 另记。
4. **R5 主动合同接线**：`pick_target` 后服务端建合同（候选+来源 digest、variants、selected_target）→ ctx；模型输出只允许 skip 或选 variant_id+bridge_id；发送前重验（P4 的两函数）；只发送校验通过的填充问题；`record_at` 只对确实送达的同一候选问题记账，skip/拒绝/失败原因单独落 flow，不冒充确认。
5. **R3 业务入口**：私聊消息入口（身份处理之后）按 `PERSONAL_MEMORY_SHARE_ENABLED` 跑意图检测 → 建/续 grant（含 source 绑定）；consolidator 写 PERSON/PRIVATE_ONLY 事实的同一事务内提升匹配的 pending grant（P3 第 3 步的挂接点）；私聊显式撤回话术 → 撤回路径。
6. **回执与观测**：`flow_catalog` 增 attribution/sharing/contract 节点，全部 skip/拒绝/失败/送达有终态；**代码定稿后 manifest regenerate 一次**（门禁拦的是正常漂移）。

出口（legacy 与 native 双链验证）：模拟错误 raw_output 不进最终发送/已送达历史/表达学习；合法输出可发送；14:09 错误开发者问题与 13:19 错称呼在发送前被拦；开关 off 时全部行为与 f752538 一致（回归断言）。

## 9. P6 数据修复工具重写（F6/F7/F8/F9）

文件：`tools/data_repair.py`（重写）。

现状（已核实）：duplicate 仅 `GROUP BY fact_key`（:153-159）不排空 key、无稳定保留序；orphan 用 `conversation_identity_versions` 当会话注册表（:196-199）；wrong_space 查 `owner_type='PERSON' AND audience='SPACE'`（:91-97）而真实 09:00 行是 `SPACE / space:space_4 / CURRENT_SPACE` 形状；apply 无 CAS（:309-320）、audit.old_value 存的是 audience、revoke 把 old_value 写进 status 列（:398-409）——(DEPRECATED,SPACE) 修成 (SPACE,SPACE)。

拟实施（对齐原计划 §6.7 三类显式操作）：

1. **来源驱动检测**：
   - `private_owner_repair`：owner_type=SPACE 的行，其 `memory_evidence`/`source_conversation_key` 经 `conversation_registry` 解析为 kind=private 且 person 主体可定 → 候选；manifest 带整行旧值 digest。真实 09:00 形状必须命中（用正式 DDL 插旧形状探针验收）。
   - `duplicate`：仅在 `(owner_type, owner_key, subject_key, audience, fact_key)` 组内且 `fact_key != ''` 才比对；保留=最早 `created_at`、平局取最小 id（稳定序）；PRIVATE_ONLY+USER_SHARED 双受众副本是**合法形状**永不标记；空 key 一律列 unknown 不自动处理。
   - `orphan`：以 conversation_registry 为会话真相——`source_conversation_key` 不在注册表**且**证据 source row 确实不存在 → 列入「来源缺失」复核清单（显式确认后才可操作，不默认失活）；「已注册、有来源、无身份声明」是正常会话，永不判孤儿。
2. **apply 带 CAS**：逐条重验当前内容 digest + 旧 status/audience/owner 与 manifest 一致，不符跳过并报告（不信任 preview 旧结论）；审计记录**列级** old/new 与 digest；新副本、`memory_evidence`、规范 scope bump 同事务。
3. **revoke 列级还原**：从审计恢复**全部被改列**（status+audience+owner…），不是把单值塞回 status；前置 CAS=当前 digest==apply 后 digest，保护期间用户的新变化；含 `private_owner_repair` 的批次撤回需显式确认（明知会恢复公开错误行）。
4. **可召回验证**：apply 后 FTS 查询、embedding selector、暖/冷 `retrieve_memories` 均不可再见失活行；scope 版本入键换桶生效。
5. 不迁移整个 space_4；不改 `group_messages` 会话身份；不倒退 checkpoint。

出口：preview 三类在正式 DDL 临时库全对（含上述反例）；apply→revoke round-trip 逐列还原；stale manifest 被拒；生产库上**只跑 preview**，apply 由用户按 P8 清单执行。

## 10. P7 集成反例矩阵（贯穿，收口在 P5/P6 后）

原则（复核 §4 的教训）：所有测试用**正式 DDL** 临时库（含 FTS/evidence/台账表），走**真实入口**（真实 `retrieve_memories` 暖缓存、真实 `TurnService.prepare/finalize`、真实 apply/revoke 而非 dry_run），断言用 P0 oracle。

| 新增/重写测试 | 必须覆盖 |
| --- | --- |
| `tests/test_dialogue_attribution_repair.py`（重写现有 25 例） | 正式 schema、真实 round-trip、P6 全部反例 |
| `tests/test_personal_memory_sharing.py`（新） | P3 权限矩阵：隔离/pending/暖缓存撤回/regrant |
| `tests/test_reply_attribution_guard_integration.py`（新） | 同一错误 raw_output 经 legacy+native 双链被拦；DIRECT/SILENT/取消/超时；correction_ack 攻击样本 |
| `tests/test_proactive_contract_flow.py`（新） | 候选改写/伪造桥接/正确主体桥接/跨会话/缺源 → 拒发；合法 variant 送达后记账一次 |
| `tests/test_conversation_identity.py` / `tests/test_migrations.py`（扩充） | P1 反例集；v18 迁移链与降级 |
| `tests/runtime/test_turn_service.py` 等（回归） | 开关 off 行为不变断言 |

复核 §4 已绿的 179 项定向测试保持全绿；追加 `python -m ruff check .`（全仓）与 `python scripts/generate_message_flow.py --check`（P5 冻结后）。

编辑事故防范（本分支两次前科）：每次编辑后 `python -m compileall` 被改文件 + ruff；diff 里出现 U+201C/U+201D（`_QUOTE_MARKS` 数据位除外）即停；ruff F821 出现即查孤儿函数体。

## 11. P8 验收与发布门（脚本就绪，用户执行）

对齐原计划 §8 与复核 §3 R8 出口，全部达标前不得宣称修复完成：

1. **模型重放**：扩展 `scripts/evaluate_dialogue_attribution.py` 走生产 prepare 链+guard（非仅新提示词采样）；生产 persona/参数基线下最终条件 ≥260 样本（四现场×30 + 原 16 类×5 + 新 12 边缘×5）；判据：0 关键错归 / 0 越权共享 / 0 不相关记账，原 80 任务 ≥72，可回答场景 ≥90%；同时报告原始错误率/阻断率/漏过率。
2. **native parity**：cargo test → maturin 构建 v18 wheel → 明确选 native 的 parity 测试（含新台账表只读兼容）；降级必须显式记录原因，skip 不算通过。
3. **生产数据修复**：备份（SQLite API 含 WAL）→ 用户审查 preview → 按序 apply：先 `private_owner_repair`，再 `identity_claim_recheck`，最后经核验的 `share_grant_apply`；每批留 batch_id 可撤回。
4. **QQ 灰度**：≥48h、200 有效轮次、20 个有来源可承接的主动机会；关键错归/越权召回/错误记账/旧错误副本复活任一发生即停。
5. **文档更正**：实施总结 [2026-10-05-dialogue-attribution-implementation-summary.md](../reports/2026-10-05-dialogue-attribution-implementation-summary.md) 的「All phases R0-R8 completed」按本计划完成情况重写（"25 个测试"与"30+"、接线未完成等不实表述一并修正），或以新总结替代并标注旧文作废。

## 12. 工程守则（每个提交）

- 每个待编辑符号先跑 impact（Docker：`docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs impact <symbol> --direction upstream --depth 3 --repo Stella_project`；本机 CLI registry 损坏，文本核查兜底时须补全量文字核对）；HIGH/CRITICAL 先列调用面。
- 每次提交前 `detect-changes --scope all`；partial/truncated 不算清洁。
- 已知 HIGH 面：`maybe_consolidate`（P2/P5）、`parse_self_alias`（P1）、`_write_memory_candidates`（P3 挂接/P5）、`finalize_turn`（P5）。
- 提交节奏：P1、P2、P3、P4、P5、P6 各自独立成提交（可并行推进的保持小步），每步树可运行、开关 off 行为不变。
