# GitNexus Engineering Plan — Stella 多人对话身份与归属修复

> Task：修复 A 对话后 B 中途加入被认成 A，以及他人纠正后身份继续漂移的问题。
> 状态：待实施；深入版，13 节，impact_depth=3，freshness=strict。本文只产生计划，不代表修复已上线。
> Evidence verified at commit `038e419da0c60ada84ae91dee7f11a5ece12aec0`；分支 `feat/qq-private-personal-memory`；Docker GitNexus `Stella_project` 本次已通过 `analyze --index-only --pdg` 刷新。
> Evidence provenance schema 2；global dirty digest `586a758c0893f04a4f4dd4792f05eae5a55ab30047dadcb2631f7a1a8dd03a04`；cited-path manifest 34 项；仅排除本计划的规范路径。完整快照见 §11。
> 证据标签：`[verified]` 当前源码或已核实运行证据；`[graph]` 图/PDG 输出；`[inferred]` 工程判断与拟议设计；`[assumed]` 待执行阶段验证的假设。

## 1. Objective

[inferred] 让 Stella 在群聊中始终区分消息作者、被回复者、被提及者、记忆所属人和机器人自身。即便名字相似、没有引用、第三人参与纠正、上下文被裁剪或异步摘要尚未完成，也不能仅凭话题连续性把这些身份合并。

交付目标：

- 当前发言者只由平台事件确定；任何别名、自然语言或 LLM 输出均不能改写其稳定 ID。
- 当前用户的个人线索与其他成员的公开背景都有明确归属；缺失归属的数据不能作为当前用户身份依据。
- 明确的本人自我介绍及时生效；第三人纠正有来源和目标，不能把纠正者当成被纠正的人。
- reply/@、BOT_SELF 回复对象、逻辑回复分段完整进入历史、摘要和回放。
- 保持现有群 SPACE、PERSON/audience 隔离、私聊和 WebChat 路径、RuntimeFacade/TurnService、SQLite 与 Python/Rust 后端约定，以及本地模型 8K 预算和现有 LLM 调用限额。

## 2. Current Behaviour

[verified] 调查报告 `docs/reports/2026-10-04-multi-user-identity-confusion-investigation.md` 已形成一条可复核的失败链：2026-10-03 22:28:58，B 说“阿呆是我”，trace 982 的当前用户 ID 正确，却选入 A 的三条 Allets 记忆。数据库中的 `user_id` 仍属于 A，`owner_type=SPACE`；错误发生在检索适用性、渲染和上下文使用环节。后续 A 的纠正没有恢复稳定归属，另一次回复甚至把 Allets 当成机器人自己的名字。

[verified] 当前链路为：平台监听记录 `group_messages` → `ChatContext` → `build_context` / `build_user_context` → `retrieve_memories`（可经 embedding）→ `build_v2_prompt_context` → `TurnService._compose_prompt` / `prepare_turn` → `fit_prompt_to_window` → 生成 → 确认发送后 `_record_bot_lines` → 后台 session compact。

[verified] 五个关键缺口：

| 缺口 | 当前源码锚点 | 工程后果 |
| --- | --- | --- |
| 群 `peer_id` 是群号，却被用于用户 scope | `memory/pre_processors.py:545-605`；`core/planner.py:289-324` | PERSON 候选按错主体取；不能仅修复主回复而遗漏 Planner |
| SPACE 可见候选不等于当前用户个人事实 | `memory/retrieval_v2.py:136-197,507-684`；`memory/ownership.py:174` | 群共享背景可能属于其他成员，不能因为可见就成为“你”的身份 |
| 记忆有 user_id，但正文渲染丢失 | `memory/prompt_builder.py:160-183` | “希望被叫 Allets”不再说明是谁的偏好 |
| 主历史缺 reply/@，BOT_SELF 只有“我:” | `memory/pre_processors.py:278-361`；`ai_gateway.py:690-803,806`、`2537-2560` | 对谁说的话被后来者继承；多气泡缺逻辑归组 |
| 纠正未进入可信身份状态，头部又可能被裁掉 | `memory/addressing_intent.py:218-283`；`core/context_budget.py:49-101` | “阿呆是我”等会 prefilter_miss；超预算时稳定身份区被尾部裁剪丢弃 |

[verified] 现有 tail 已按消息行数、时间和间隔选取；本计划进一步定义逻辑单元和归属，不把现有实现描述成“只取某人的三句话”。现有 `_merge_similar` 会检查 `user_id`，不能把症状误判为数据库把不同用户的记忆直接合并。

## 3. Relevant Architecture

[verified] `RuntimeFacade` 当前在进程内直接调用 pipeline/TurnService，并有会话锁和 epoch 取消检查（`core/runtime/facade.py:231-281`）。`ChatContext` 有显式 JSON 投影白名单，版本为 3（`core/context.py:201-251`）；投影是兼容边界，不能据此声称主回复链路已经跨进程。

[verified] schema 当前为 15。已有 `conversation_registry`、`memory_evidence`、`personal_profile_facts`、`memory_scope_versions`，v15 保持存量记忆 SPACE 语义（`memory/schema.py:570-715`；`memory/migrations.py:739-810`）。迁移执行器按版本事务提交，失败回滚；已有行数守恒与 FTS 校验。

[verified] `retrieve_memories_emb` 最终进入同一个 `retrieve_memories`，正常和异常回退均携带 `access_scope`（`memory/retrieval_v2.py:687-751`）。本计划修正调用方传入的主体，在 Python 侧增加归属呈现；保持现有 native 检索 ABI，不新增另一套数据库或检索引擎。

[verified] `set_preference` 按 space+user 写现有称呼偏好；`handle_addressing` 对修改他人有权限约束。会话内本人别名声明与跨空间身份、称呼命令是不同事实，不应绕过现有权限自动改写其他人的偏好。

[inferred] 采用一条权威链：平台 envelope → SQLite 消息及关系 → 有来源的身份声明 → 结构化 history/memory → 预算器 → LLM。姓名仅是附属属性。自由文本摘要和模型输出只能提供内容，不能产生权威的用户 ID、收件人或身份更名。

## 4. GitNexus Findings

[graph] 本次 runner `.gitnexus/run.cjs` 与索引的 analyzer identity 已核对；执行一次 `docker exec stella-gitnexus node .gitnexus/run.cjs analyze --index-only --pdg`，同 HEAD 完成。context、clusters、processes 均已读取；clusters/processes 为工具默认有界摘要，不能作为全仓完整拓扑。

| 查询（repo 均为 Stella_project） | 结果摘录 | 本计划如何处理 |
| --- | --- | --- |
| impact `build_conversation_section` upstream depth3 | `HIGH; impacted=13; direct=2` | 保留 prompt builder 旧位置参数；兼容现有预算测试 |
| impact `_build_user_context_v2` upstream depth3 | `HIGH; impacted=4; direct=1` | `build_user_context` 及 capability/proactive 路径一起验收 |
| impact `record_message`，收敛到 `Function:memory/pre_processors.py:record_message` | `CRITICAL; impacted=25; direct=5; epistemic=lower-bound` | 五个图直接调用者全部覆盖；另用源码检查图漏掉的动态/接收器调用 |
| impact `build_context` upstream depth3 | `HIGH; impacted=22; direct=17` | tail、cache、short-term、full-workflow 测试一起更新 |
| impact `fit_prompt_to_window` upstream depth3 | `CRITICAL; impacted=34; direct=6` | 不全局替换原字符串裁剪；结构化预算走新入口，旧回放/Planner 兼容 |
| impact `ChatContext` upstream depth3 | `CRITICAL; impacted=50; direct imports=30` | 新字段有默认值；投影 v4；全体直接依赖详见 §9/§11 |

[graph] `record_message` 报告有 3 个接收器类型无法确定的调用点被索引丢弃。最初仅按名字调用 impact 有歧义而返回 UNKNOWN，后按文件/uid 收敛；UNKNOWN 没有被当作低风险。`retrieve_memories_emb` 在图中按名字未找到，随后用文字定位实际定义于 `memory/retrieval_v2.py:687` 并读源码；未凭图空结果推断不存在。

[verified] 对 `record_message(` 的源码核对同时发现 `memory/proactive.py` 的同名控制器方法；它不等于历史持久化函数。WebChat 有用户与 BOT_SELF 两处实际写入，须一起保持会话键与归属语义。`build_context` 由注册 hook 动态触发，图的直接业务调用者为空不表示它未使用。

## 5. Statement-Level PDG Findings

以下只采用本次完成的 3 个有界切片；不补造异步竞态的 PDG 边。

1. **scope 绑定**：[graph] `pdg_query(mode=flows,target=_build_user_context_v2,variable=access_scope,limit=25)` 返回 4 项。空 scope 和按会话构建 scope 的定义均到达 embedding 与普通检索分支。[verified] 源码确认触发条件为非 proactive 且有 conversation_kind，两个调用点都传相同 scope。**约束**：修复在共同定义处，Planner 同样调用可信主体 helper；不能只修其中一个检索分支。
2. **裁剪控制**：[graph] `pdg_query(mode=controls,target=_fit_prompt,limit=35)` 返回 7 项，覆盖预算内直接返回、存在当前输入 marker 的分支、无 marker 的尾部回退。[verified] 源码按原字符串 `【现在 ` 拆分，只保留 context 尾部。**约束**：结构化路径不能再靠用户可伪造 marker 定位身份块；旧 generic 函数仍保留原分支供非聊天消费者。
3. **记忆归属数据丢失**：[graph] `pdg_query(mode=flows,target=build_conversation_section,variable=content,limit=25)` 返回 2 项，content 到正文模板和 token 计算。[verified] line175 的模板仅使用 content，没有 user_id。**约束**：先生成带归属的完整条目，再算 token；不能预算时算无标签正文、之后再补标签导致超额。

[verified] `compact_once` 在 await backend.generate 后会 `skip_range` 或 `apply_summary`，当前没有携带身份 revision/reset generation 的提交校验（`memory/session_compact.py:225-257`）。同群 in-flight 防重只保护并发 compact，不足以证明 reset 或身份纠正后旧摘要不能提交。此竞态结论由状态代码得出，不称为 PDG 已证明。

## 6. Proposed Changes

### 6.1 P0：检索主体与记忆归属

[inferred] 在 `memory/ownership.py` 新增一个**拟新增**纯 helper `scope_for_chat_context`，统一从可信 `ChatContext` 决定权限主体：普通群聊/私聊用 `ctx.user_id`；`proactive_at` 用经过现有触发链验证的目标 uid；无明确目标的群主动发言为“无当前个人主体”，保留 SPACE 背景，不使用群号或 user_id=0 构造某个 PERSON。不要改动现有 owner/audience 授权 SQL 的含义。

[inferred] `memory/pre_processors.py:_build_user_context_v2` 与 `core/planner.py:RestrictedPlanner._query_memory` 都改用该 helper。保持 `retrieve_memories` / `retrieve_memories_emb` 签名与 native API，验证 embedding fallback 和 Python/Rust 各自既有 scope 约束。

[inferred] `memory/prompt_builder.py:build_conversation_section` 增加 keyword-only 的当前主体参数，默认 None 保留旧调用兼容。每条记忆生成不可裁断的头部：

```text
当前用户的记忆 [subject=用户(202)]：希望被称呼为阿呆
其他成员的公开背景 [subject=用户(101)]：希望被称呼为Allets
群共享事实 [subject=群/无个人主体]：正在讨论部署问题
归属未确认 [source=legacy]：原始事实正文；不可用作当前用户身份依据
```

[inferred] `user_id` 在旧 SPACE 记忆中首先解释为“记录归属用户”，不能无条件升级成经过认证的事实主语。如果正文说的是第三人而证据没有结构化 subject，标签仍保留记录归属并加“事实主语未确认”；当前身份判断只使用 §6.3 的可信声明/现有显式偏好，不能让含糊长记忆覆盖它。不从含 ID 的自由文本反向解析归属。

[inferred] 应用性分区只决定呈现，不扩大权限、不把 SPACE 强制缩成当前 uid。先恢复标签并保留既有排序；首版不全局重写 ranking/top-k。当前人物没有可用记忆时允许说不知道；当前身份 capsule 来自独立可信状态，避免 A 的高分记忆挤占 B 后又伪造 B 身份。Planner 的记忆压缩与最终主回复采用同样归属约定。

### 6.2 P1：消息 envelope、schema16 与历史关系

[inferred] 给 `ChatContext` 增加带默认值的字段，拟议消息 DTO 为 `MessageIdentityEnvelope`；实现可用 dataclass，但投影仅传有界 JSON primitive：`sender_display_name`、`reply_to_msg_id`、`reply_target_user_id`、`mentioned_user_ids`、`logical_message_id`、`part_index`、`origin_msg_id`、`reply_recipient_user_id`、`relation_version`、`recorded_row_id`。沿用现有 conversation_key/bot_id/user_id/source_kind/turn_id；display name 是展示数据，不能作稳定身份键。字段规格：uid 使用当前项目 uid 类型；平台 message ID 在持久化边界统一成字符串；part_index 非负；mention 去重最多 32 个；display name 规范化最多 64 字符，移除控制字符/提示标记。

[inferred] `core/context.py` 投影版本 3→4；新增白名单字段可序列化、有默认空值；v3 旧输入缺字段时使用未知关系。`raw_event` / bot 仍不过投影。任何来源不明的投影不能仅凭传入 uid 获得权限，权限主体继续由既有可信入口确定。

[inferred] schema 15→16，对 `group_messages` 做**加列**迁移：conversation_key、bot_id、sender_display_name、reply_to_msg_id、reply_target_user_id、mentioned_user_ids_json、logical_message_id、part_index、origin_msg_id、reply_recipient_user_id、turn_id、relation_version。文本/可选 ID 默认 NULL，mentions 默认 `[]`，part_index/relation_version 默认 0。索引 `(group_id,msg_id)` 为非唯一，关系查找须同时约束 canonical conversation/bot；新增 `(conversation_key,logical_message_id,part_index)` 非唯一索引用于归组。旧 row id、时间、content、source_kind、memory owner、FTS 内容和行数均不改。旧 msg_id=0 或无法绑定 canonical key 的行保留 unknown，不根据相邻文本补 reply 对象。

[inferred] `memory/schema.py` 同步新库建表和兼容补列；`memory/migrations.py` 注册拟新增 `migrate_v16`，在现有 per-version 事务里加列/索引/§6.3 新表，失败不推进版本。兼容旧库 fixture 时历史查询按列可用性降级，不能以每轮捕获任意异常掩盖真实 SQLite 错误。迁移先在数据库副本 dry-run，随后验证幂等、行数守恒、旧私聊 storage ID、FTS 和索引。

[inferred] `ai_gateway.py:record_group_chat` 在 `record_message` 前把平台 event 的 reply/@ 解析写入 ctx；提取无条件执行，不依赖 SOCIAL_ENABLED。现有 `_extract_message_relations` 的解析逻辑作为来源，社会学习可以消费同一份 envelope，但不能成为主历史关系的唯一持久化位置。reply target 只能由同 canonical conversation+bot 的原始消息解析；找不到或多条冲突则 unknown，禁止猜最近发言者。仅 @ 可以表达提及，不自动等价“我就是被@的人”。

[inferred] `record_message` 在同一 SQLite 短事务写正文和 envelope，返回 ctx 带 recorded_row_id；不跨网络/LLM await 持有事务。重复事件沿用现有去重行为，本计划不新增会误删不同气泡的唯一约束。

[inferred] `_record_bot_lines` 保留原位置参数，新参数只 keyword-only，接收可信 origin ctx 与确认成功的 receipts。每个确认气泡有自身 platform message ID；同一次回复共享 logical_message_id/turn_id、递增 part_index、相同 origin_msg_id 和 reply_recipient_user_id。历史作者仍为 BOT_SELF；回复对象不是作者。receipt 无 message ID 时仍可记录已确认的逻辑关系，msg_id 缺失保持未知。failed/unknown 不写“已送达” BOT_SELF、不重发 unknown。普通群聊回复、私聊、命令回复、proactive_at、无目标 proactive 和 WebChat 分别指定合法 origin 或明确 unknown。

[inferred] `build_context` / `_fetch_recent_tail` 读取关系列，生成结构化逻辑单元，再呈现：`机器人 → 用户(101) [回复 msg=…]`、`用户(202) [reply_to=…; mentions=…]`。保留时间顺序、间隔提示和原有年龄边界；一个机器人 turn 的多气泡作为同一逻辑单元。连续后缀选取最多 12 个逻辑单元，并设置 48 行扫描上限及 token 上限，防止极多气泡膨胀。输入文本按字段转义，正文不能伪造结构头。异常或缺元数据用“对象未知”，不能退成最近一人。

### 6.3 P1：有来源的本人声明与纠错

[inferred] 新建拟新增模块 `memory/conversation_identity.py`。职责限定为会话内身份线索解析、来源校验、持久化、冲突和版本管理；不建设跨群身份图，不把此表当 PERSON 授权来源。

[inferred] schema16 新建 `conversation_identity_claims`：id、conversation_key、bot_id、subject_user_id、author_user_id、claim_kind、alias、source_row_id、status、supersedes_id、created_at；索引 `(conversation_key,subject_user_id,status)`。新建 `conversation_identity_versions`：conversation_key 主键、revision 单调整数。允许多条有来源 claim，active/inactive/conflicted 状态明确；source_row_id 指向该会话已入库原消息，更新版本与 claim 状态同一事务。存储仅当前会话别名，不跨 PRIVATE_DIRECT/群公开呈现。历史正文被正常清理后，仍保留必要的声明证据快照（原作者、原消息 ID、声明原文的有界摘要）或使 claim 降为不可验证，不能留下虚假的外键证明。

[inferred] 先实现不增加 LLM 调用的有界规则：整条非引用文本的“我是X”“X是我”“我才是X”“以后叫我X”“那我改名叫X”可生成本人 alias claim，subject 只能为平台 sender。名字最多32字符并复用现有规范化要求。引号/转述/第三人称/多个自称/超长内容判 ambiguous；“我是管理员/机器人”等角色权限表达不产生身份或权限。别名碰撞不会合并 uid。规则只覆盖已知失败形式，不能声称能解析任意中文纠正。

[inferred] 第三人“他才是A”“A不是他”作为 correction evidence：只有 reply 指向某条原消息、明确@稳定uid、或显式唯一且已验证的别名目标时，才能形成目标明确的否定/冲突线索；第三人不能创建他人的 confirmed_self，也不能把说话者改成该目标。目标不唯一就只作带来源的普通对话，不写身份映射；需要称呼时使用稳定 ID 或中性称呼。第三人的纠正可使争议线索 conflicted，但不会改写平台映射或现有显式称呼偏好。

[inferred] 必须区分 reply 消息的作者与纠正所指的人：引用 BOT_SELF 时，直接被引用的作者是机器人；可通过该泡保存的 origin/recipient 找到“此前被机器人叫错的人”作为纠正候选。只在同一会话的可信链与明确文本一致时形成目标线索；多收件人、丢失origin或只有邻接关系则 unknown。否定“B不是Allets”本身不等于确认“A就是Allets”。

[inferred] 本人最新明确更名只 supersede 本人旧 alias claim；新旧多个别名若没有“改名/纠正”语义可并存，不自动删除历史别名。称呼命令仍通过现有 `classify_addressing`/`handle_addressing` 权限链写 preference。fresh self alias 与旧显式称呼冲突时分开呈现“本人此轮自称X / 曾要求称呼Y”，身份回答可使用确认的 X，正常称呼暂用中性表述，不静默改 preference。需要持久改变称呼时由本人现有命令确认。

[inferred] hook 顺序：入库得到 source_row_id → 校验并更新 claim/revision → 构建当前用户 capsule → cache/history/prompt；群监听与主 matcher 不能重复确认同一 source_row_id。private/WebChat 在各自已记录消息的入口执行同一纯解析/服务，不复制业务规则。

[inferred] 每轮 capsule 从平台 ID、该会话已验证 alias、当前显式 preference、已解析 reply target 和冲突状态生成。**身份陈述的使用优先级**：平台 stable ID > 源消息校验的本人声明 > 显式偏好（仅“怎么称呼”）> 带归属记忆 > 自由摘要；第三人或模型说法不晋升为本人声明。准确的“我是谁”规则回复，仅在整条匹配身份问句且有足够本人事实时返回；复合问题继续 LLM。没有证据时明确“不确定名字”，不借用 A 的名字。

### 6.4 P1/P2：结构化预算与摘要一致性

[inferred] 在 `core/context_budget.py` 拟新增 `fit_conversation_parts` 与 `ConversationPromptParts`；保留 `fit_prompt_to_window` 旧默认行为及其字符串返回契约。`TurnService._compose_prompt`/`prepare_turn` 采用 parts 路径，Planner `_ask` 继续 generic 路径，但其 memory 文本已经有归属。旧 `build_v2_prompt_context` 位置调用保留，新增 parts 信息走可选 keyword 或 ctx 字段。

[inferred] parts 划分为：可信身份 capsule、当前输入 envelope+正文、带归属行为约束、history 逻辑单元、profile/记忆、knowledge/tool/skill/social。优先保留 capsule+当前 envelope；当前正文太长时只裁正文并标注，不切开作者/对象字段。按项目现有 system/output/tool reserve 先计算可用预算，禁止额外固定 8K 常数覆盖真实 endpoint window。建议 capsule 初始目标≤256估算token，不用机械截断 ID 满足这个软限额。

[inferred] 预算不足的处理顺序：可选 social/低优先证据 → 低相关带归属记忆 → 旧 history 的完整逻辑单元 → 当前正文。行为约束按已有安全/功能优先级保留。最后重算带所有标签的总 token；protected minimum 已超过预算时走现有 DIRECT 的简短“输入过长，请简化”结果，不调用超额 LLM，不默默删掉身份。用户正文中 `【现在 ` 等 marker 只是数据，不影响块定位。

[inferred] history 只选连续后缀且按逻辑单元边界，避免排序后把回复挪给另一位成员。若单个机器人逻辑单元过大，保留整个单元的作者/回复对象头和有界各段摘要，明确标记内容裁剪，不能把部分气泡变成另一个独立 turn。`tail_start_id` 是实际保留后缀第一行 id，compact 上界始终排除它；仅原始完整前缀可推进 summary watermark。budget 阶段减少 tail 后可以保守保留 preprocessor 的较早 tail_start_id，使 compact 范围更小；禁止把未处理的中间消息跳过。

[inferred] `SessionState` 增加 reset generation；身份 revision 使用持久化会话版本。cache key 加 format_version、关系历史 version、identity_revision、generation；现有 history maxid/stcUpdated/summaryVersion/mode/policy 继续保留。纠正/更名成功立即 bump revision，清该会话 identity/context cache；budget/cache/replay 共同读取同一冻结快照，不依赖 TTL 最终刷新。

[inferred] `compact_once` 在 await 前捕获 generation、identity_revision、summarized_up_to、tail_start_id；await 后在提交 summary 或 skip_range 前比较。任一不匹配即丢弃结果，不推进位置，下一轮重试。reset 与 apply/skip 的 CAS 在同一 session 状态锁/同步临界区；无 SQLite 事务跨 await。现有 `_in_flight` 防重保留。

[inferred] compact 输入保留 uid、机器人收件人、原 reply 引用；自由摘要只保存话题与互动，不承担身份权威。身份 capsule 每轮重新生成；旧 short_term/active/session summary 没有归属结构时标记 legacy_unverified，不能转成确认身份事实。不要求本次把全部摘要改成新的 JSON 引擎。

### 6.5 P2：可观测性、回放和发布边界

[inferred] `TurnService.prepare_turn` 在现有 trace 中添加版本化的结构化 budget snapshot：budget_format_version=2、parts/原始长度与摘要、current_sender_id、reply_target、identity_revision、selected row范围/逻辑单元、每条注入记忆的 subject/归属状态、dropped parts 与最终估算。常规日志只写 ID、版本、原因和统计；详细原文仍受既有 detailed trace 开关/留存约束，不默认为所有用户新增全文日志。

[inferred] `core/observability/replay.py:replay_budget_decision` 按版本选择 v1 generic 或 v2 parts，使用冻结快照而非当前数据库查别名；相同 snapshot 应得到相同 sender/recipient/保留单元与预算结果。旧记录继续离线可回放，不能以重新保存旧 snapshot 的方式“升级”证据。

[inferred] 首次发布用影子离线比对和少量明确测试会话确认，再扩大到普通群聊。采用分阶段发布提交而非新增多组长期配置开关。出现串人可回退应用提交；schema16 为 additive，回退应用保留新列/表，禁止直接对生产库做降版本删列。真实滚动回退在副本验证，新旧双进程不得共享可写会话数据库。

## 7. Implementation Sequence

所有步骤开始前按 AGENTS.md 对实际待改符号重新 impact；HIGH/CRITICAL 明示影响面。每个实施提交前 detect_changes(scope=all)，partial/truncated 必须解决，UNKNOWN 补源码/测试。以下是待实施步骤，均未完成。

| 步骤 | 优先级/依赖 | 可直接执行的工作 | 退出条件 | 估算投入* |
| --- | --- | --- | --- | --- |
| M0 冻结失败与契约 | P0，无依赖 | 将报告 A/B/C/R 场景转换成合成 uid、固定时间、SPACE/PERSON 混合测试数据库；明确 old behavior 断言和新期望；记录当前 scope、prompt、tail、模型参数 | 离线重现 B 收到 A 无归属偏好、纠正 prefilter_miss、长输入裁身份三个失败；不读写生产库 | 0.5–1日 |
| M1 最小止错 | P0，M0 | 共用 scope helper；主回复/Planner 两处主体纠正；记忆归属标签与未知降级；不改变 native ABI/owner SQL | 普通/embedding fallback/Planner scope 正确；A 记忆不能被当 B 身份；SPACE 背景仍可见、PRIVATE_ONLY 不泄漏；旧接口兼容 | 1–2日 |
| M2 关系合同与迁移 | P1，M1 | schema16、ChatContext v4、trusted event关系、记录事务、confirmed BOT_SELF收件人/气泡归组；私聊/WebChat/主动路径接入或明确unknown | 新旧DB/投影均可运行；social关闭关系仍在；失败/unknown没有已送达BOT_SELF；跨群重复messageid不串目标 | 2–3日 |
| M3 身份状态与纠正 | P1，M2 | claim服务、source验证、本人规则、第三人冲突规则、版本事务、hook顺序、即时capsule与cache刷新；整条身份问句可走已有DIRECT | 每条claim有证据；A/B同名不合并；C不能覆写A/B；改名下一轮可见；不改别人preference | 1.5–2.5日 |
| M4 预算/摘要一致性 | P1/P2，M2+M3 | parts预算、逻辑tail、generation/revision CAS、legacy摘要降级、v2trace/replay | 8K/极小预算保持归属头；no-marker旧路径兼容；纠正/reset期间compact旧结果不能提交；v1/v2回放一致 | 2–3日 |
| M5 回归与小范围发布 | P2，M1–M4 | 运行§8矩阵；最终一次更新必要golden/预算baseline；冻结真实本地模型验证；副本迁移/回退/性能；发布验收记录 | §13全部通过；模型验证独立于FakeBackend；失败则记录并停在相应阶段，不宣称全修复 | 1–2日 |

* [assumed] 单名熟悉项目的工程师、测试环境可用情况下约 8–13.5 工程日，包含联调但不包含等待真实群试用的时间。估算用于排期，不作为验收证据。M1 可独立交付，但只完成主体和归属修复，不能据此宣布 reply/纠正/裁剪全部问题已解决。

## 8. Test Strategy

[verified] 现有测试落点已定位：prompt builder 的旧位置参数/称呼区、budget 的 marker、tail 的时间顺序/summary、session compact 的失败与空结果、cache、migration 的dry-run/回滚/幂等、private ingress、proactive_at、facade与trace replay。调查阶段的既有测试通过仅是基线，不验证本计划的新行为。

拟新增 `tests/test_multi_user_identity.py`、`tests/test_message_relations.py`、`tests/test_conversation_identity.py`、`tests/test_structured_conversation_budget.py`，测试名由实施者按以下输入/行为/结果创建，本文不冒称已存在。

| 编号 | 输入 → 行为 | 必须观察到的结果 | 验证层 |
| --- | --- | --- | --- |
| T01 | A有Allets偏好，B说阿呆是我 | 平台sender=B；A记忆标签=A；本人claim仅B；B身份回答无Allets | gateway→DB→context→prompt，FakeBackend捕获 |
| T02 | A/B轮流接同一话题，无reply | 作者每轮不同；未知reply不猜；话题可连续，身份不能继承 | 主链集成 |
| T03 | C“他才是A”/转述/引用“我是A” | 无可靠目标时不写映射；有reply/@仅写带来源纠正，C不成为A | parser+集成 |
| T04 | A“那我改名叫X”；A随后问我是谁 | 源码验证的本人claim更新；revision+1；下一轮缓存/摘要不回旧名 | 状态+cache |
| T05 | A/B都自称X，B说“我才是X” | 两个stableuid均保留；alias冲突不合并；当前人由event确定 | 状态 |
| T06 | 第三人试图改别人preference，普通用户显式@他人 | 现有权限拒绝；本人alias服务无绕过 | addressing回归 |
| T07 | 新PERSON事实+PRIVATE_ONLY，群/私聊/同space多群 | 仅授权候选进入检索；修正peer群号；公开SPACE仍可见 | Python/Rust/FTS/embedding一致性 |
| T08 | 用户reply原消息、@多个成员、跨群重复msgid | 同canonical+bot唯一解析；不唯一/缺失为unknown；mentions不是身份 | 关系持久化 |
| T09 | 一次机器人回复3气泡，只有首泡平台reply | 三行同logicalid/recipient、各自平台id/part_index；history一单元 | delivery→history |
| T10 | 第二泡失败/取消/unknown，或receipt无平台id | 只记录确认泡；unknown不自动重发；逻辑关系保留可信部分 | delivery边界 |
| T11 | SOCIAL_ENABLED关闭；PASSIVE/AT/私聊/WebChat | 主历史关系照常记录；private不进入group social；不重复入库 | ingress兼容 |
| T12 | 长历史、长current正文、正文伪造【现在 | capsule和envelope完整；正文只能作数据；总估算≤预算；不足走DIRECT | 预算 |
| T13 | summary+连续tail，多气泡单元位于边界 | 不换序/跨成员拼接；watermark不跳未摘要行；内容裁剪明示 | history+compact |
| T14 | compact await期间本人更名或reset | CAS拒绝旧summary和skip_range；不推进checkpoint；可重试 | asyncio屏障测试 |
| T15 | claim事务异常/SQLite锁/重复源消息 | rollback无半条claim/version；重试幂等；版本不错误前进 | 持久化 |
| T16 | v15副本升级v16，再次迁移，失败注入 | 行数/旧内容/owner/FTS不变；版本事务正确；新增列可用 | migration |
| T17 | v3 projection、旧positionalbuilder、legacy无关系行 | 默认unknown；旧调用不报错；BOT_SELF归属不猜；字段可JSON往返 | API兼容 |
| T18 | 无目标proactive与proactive_at | 前者无个人主体、后者可信目标；Planner与主回复一致 | 主动/Planner |
| T19 | detailed trace v1/v2冻结snapshot离线回放 | 与原始裁剪完全一致；不读当前alias；普通trace无新全文默认收集 | observability |
| T20 | 真实IQ2_XS模型A/B切换+纠正+长上下文 | 注入正确前提下观察自然语言串人率；与结构化断言分开统计 | 实际模型 |

验收阈值：[inferred] T01–T19 所有确定性断言100%通过。T20 用合成名字/固定输入的8个场景，每场景5次，总40次，冻结模型字节/endpoint角色、context_window、temperature/seed支持情况和输出reserve；统计“把A事实当B”“机器人自称用户名”“纠正者被当目标”三类，目标为0/40，且不能以统一不回答规避（至少36/40正确完成原问题）。不支持seed时记录实际采样条件。40次仅是发布门槛，不证明所有开放群聊零错误；如不达标，返回对应场景修改prompt或身份规则，不增加主链每轮第二次身份LLM调用。真实群试用另行记录，不假称已完成。

验证命令（实施时在已具备项目依赖的 Python 环境执行；新增文件须先存在）：

```powershell
python -m pytest tests/test_prompt_builder_v2.py tests/test_context_budget.py tests/test_context_tail.py tests/test_bot_self_source.py tests/test_session_compact.py tests/test_session_context_cache.py tests/test_turn_trace_replay.py tests/test_migrations.py tests/test_personal_memory_scope.py tests/test_private_chat_ingress.py tests/test_proactive_at_flow.py tests/runtime/test_facade_turns.py -q
python -m pytest tests/test_multi_user_identity.py tests/test_message_relations.py tests/test_conversation_identity.py tests/test_structured_conversation_budget.py -q
python -m pytest tests/runtime tests/capability tests/cometa tests/knowledge tests/observability tests/webui tests/scheduling tests/test_planner.py tests/test_pipeline_compose.py tests/test_ai_gateway_deterministic_reply.py tests/test_jargon_service.py tests/test_short_term_attribution.py tests/test_full_workflow.py tests/test_retrieval_v2_and_schema.py tests/test_retrieval_cache_topic.py tests/test_addressing.py tests/test_addressing_intent.py tests/test_addressing_handler.py -q
python -m pytest tests/ -v --cov=. --cov-branch --cov-report=xml -n auto --dist loadgroup --timeout=120 --timeout-method=thread
docker exec stella-gitnexus node .gitnexus/run.cjs detect-changes --scope all --repo /repo
```

[verified] pytest/asyncio/pythonpath 配置见 `pyproject.toml`；完整 suite 选项来自 `.github/workflows/ci.yml:90-107`，需要 pytest-cov/xdist/timeout。Python/Rust parity 要运行项目已有双后端测试配置并记录实际加载的 native API版本；不能拿旧 `.pyd.api1.bak` 冒充当前后端。没有 native 环境时此项标记未验证，不能宣布兼容完成。本次规划不执行新功能测试、真实发信或生产迁移。

## 9. Risk and Impact Analysis

[graph] **CRITICAL**：ChatContext、record_message、fit_prompt_to_window；**HIGH**：build_context、_build_user_context_v2、build_conversation_section。前置风险告知已完成；工程风险不因 riskSharedAxes 较低而豁免。

直接依赖逐项处理：

- `build_conversation_section`：`build_v2_prompt_context` 接入归属参数；`test_tech_mode_has_larger_conversation_budget` 按含标签token重新验收，预算baseline仅在M5最终更新。
- `_build_user_context_v2`：唯一直接调用者 `build_user_context` 不变；其 capability注册与 proactive_at 下游在M1/T18检验。
- 其余4个分析目标的全部 d=1 条目见下表，来自已保存的完整 impact 结果。方法相同的测试依赖可保持源码不变，但必须运行。未解析动态调用通过源码入口核对，不当成低风险。

| 分析目标 | d=1 文件 | 完整 d=1 符号 | 处置 |
| --- | --- | --- | --- |
| build_context | `tests/test_context_tail.py` | `_run`、`test_bot_question_precedes_user_reply`、`test_bot_self_rendered_as_wo`、`test_fresh_summary_keeps_original_label`、`test_gap_marker_inserted_within_window`、`test_no_gap_marker_when_continuous`、`test_no_tail_falls_back_to_exchanges`、`test_session_summary_precedes_tail`、`test_stale_messages_excluded_from_tail`、`test_stale_summary_relabeled`、`test_summary_and_tail_coexist`、`test_tail_in_time_order`、`test_timestamp_unparseable_not_filtered` | M5运行；需要新断言时更新，兼容默认接口 |
| build_context | `tests/test_full_workflow.py` | `test_full_workflow_summary_feeds_next_reply` | M5运行；需要新断言时更新，兼容默认接口 |
| build_context | `tests/test_session_context_cache.py` | `_build` | M5运行；需要新断言时更新，兼容默认接口 |
| build_context | `tests/test_short_term_attribution.py` | `test_build_context_falls_back_when_column_missing`、`test_write_and_read_short_term_keeps_attribution` | M5运行；需要新断言时更新，兼容默认接口 |
| fit_prompt_to_window | `core/observability/replay.py` | `replay_budget_decision` | M1–M4按契约接入或保持默认；M5兼容验证 |
| fit_prompt_to_window | `tests/test_context_budget.py` | `test_long_prompt_keeps_current_input_marker`、`test_short_prompt_is_unchanged` | M5运行；需要新断言时更新，兼容默认接口 |
| fit_prompt_to_window | `core/planner.py` | `_ask` | M1–M4按契约接入或保持默认；M5兼容验证 |
| fit_prompt_to_window | `core/runtime/turn_service.py` | `prepare_turn` | M1–M4按契约接入或保持默认；M5兼容验证 |
| fit_prompt_to_window | `tests/test_turn_trace_replay.py` | `test_offline_replay_matches_frozen_snapshot` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `capability/delegation.py` | `delegation.py` | M1–M4按契约接入或保持默认；M5兼容验证 |
| ChatContext | `capability/hooks.py` | `hooks.py` | M1–M4按契约接入或保持默认；M5兼容验证 |
| ChatContext | `core/planner.py` | `planner.py` | M1–M4按契约接入或保持默认；M5兼容验证 |
| ChatContext | `core/runtime/facade.py` | `facade.py` | M1–M4按契约接入或保持默认；M5兼容验证 |
| ChatContext | `core/runtime/turn_service.py` | `turn_service.py` | M1–M4按契约接入或保持默认；M5兼容验证 |
| ChatContext | `memory/post_processors.py` | `post_processors.py` | M1–M4按契约接入或保持默认；M5兼容验证 |
| ChatContext | `memory/pre_processors.py` | `pre_processors.py` | M1–M4按契约接入或保持默认；M5兼容验证 |
| ChatContext | `stella_project/plugins/bot_main/ai_gateway.py` | `ai_gateway.py` | M1–M4按契约接入或保持默认；M5兼容验证 |
| ChatContext | `tests/capability/test_capability_hooks.py` | `test_capability_hooks.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/capability/test_delegation.py` | `test_delegation.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/cometa/test_gateway_wiring.py` | `test_gateway_wiring.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/knowledge/test_isolation.py` | `test_isolation.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/observability/test_message_flow_runtime.py` | `test_message_flow_runtime.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/runtime/legacy_harness.py` | `legacy_harness.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/runtime/runtime_harness.py` | `runtime_harness.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/runtime/test_facade_turns.py` | `test_facade_turns.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/runtime/test_turn_service.py` | `test_turn_service.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_ai_gateway_deterministic_reply.py` | `test_ai_gateway_deterministic_reply.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_bot_self_source.py` | `test_bot_self_source.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_context_tail.py` | `test_context_tail.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_full_workflow.py` | `test_full_workflow.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_jargon_service.py` | `test_jargon_service.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_personal_memory_scope.py` | `test_personal_memory_scope.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_pipeline_compose.py` | `test_pipeline_compose.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_planner.py` | `test_planner.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_private_chat_ingress.py` | `test_private_chat_ingress.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_proactive_at_flow.py` | `test_proactive_at_flow.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_session_context_cache.py` | `test_session_context_cache.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `tests/test_short_term_attribution.py` | `test_short_term_attribution.py` | M5运行；需要新断言时更新，兼容默认接口 |
| ChatContext | `webui/chat_ingress.py` | `chat_ingress.py` | M1–M4按契约接入或保持默认；M5兼容验证 |
| record_message | `stella_project/plugins/bot_main/ai_gateway.py` | `_record_bot_lines`、`handle_private_chat`、`record_group_chat` | M1–M4按契约接入或保持默认；M5兼容验证 |
| record_message | `tests/test_bot_self_source.py` | `test_record_message_persists_bot_self` | M5运行；需要新断言时更新，兼容默认接口 |
| record_message | `webui/chat_ingress.py` | `run_turn` | M1–M4按契约接入或保持默认；M5兼容验证 |

[inferred] 九个 ChatContext 生产直接导入者中，planner/pre_processors/turn_service/gateway接入新字段；facade、capability hooks/delegation、post_processors、WebChat保持默认构造/JSON兼容，只有需要填入可信关系的入口才改。30个导入项全部在§11清单中；不要求为“导入了类型”做无关重构。

| 风险 | 防范与发布约束 |
| --- | --- |
| 限制SPACE到当前人会损伤群知识 | 不改visibility；presentation明确第三方归属，身份capsule独立 |
| 新字段被用户文本/别名伪造 | 元数据仅从event/可信ctx/source行；转义正文；稳定uid不从文本重建 |
| 旧memory.user_id只是记录归属，正文实际讲别人 | 区分记录归属与事实主语；非本人证据不得覆盖身份状态 |
| 称呼与别名冲突 | 分开表/语义；中性称呼；不绕过原addressing权限 |
| async compact/caches重新带回旧错名 | revision+generation+watermark CAS；提交与skip均检查；同轮冻结snapshot |
| schema16阻断升级/旧应用回退 | additive、事务、副本dry-run；保留列/表回退；禁止生产降schema |
| relation解析增加IO/锁时间 | 复用本地索引查原消息；无逐条nickname网络请求；短事务，无await |
| 8K标签成本让知识消失 | 标签计入预算；capsule≤256软目标；明确优先级，监控不同parts占用 |
| graph漏边 | record_message lower-bound；动态hook、WebChat BOT_SELF等已源码补查；实施前impact重验 |
| 高质量输入仍有模型串人 | 真模型40场采样验收；确定性身份问句可DIRECT；不把fake测试当模型准确率 |

[inferred] 性能门槛：同设备/同fixture记录M0与M5的preprocess+compose+budget p50/p95（不含LLM）；目标p95增加≤20ms且额外数据库查找有界。超标先合并查询/利用revision缓存，不能删归属头换速度。无新增正常回复LLM调用、网络nickname lookup或后台第二引擎。

## 10. Files Expected to Change

所有“新增”文件/符号均为设计名称，不表示仓库已存在；现有符号的证据范围见 §2–6。

| 文件 | 现有/拟新增落点 | 原因 |
| --- | --- | --- |
| `memory/ownership.py` | 拟新增scope_for_chat_context；现有scope语义保持 | 当前主体共用 |
| `memory/pre_processors.py` | record_message、build_context、_build_user_context_v2、_fetch_recent_tail | metadata入库、身份顺序、tail/cache |
| `core/planner.py` | RestrictedPlanner._query_memory | 同步修scope与归属 |
| `memory/prompt_builder.py` | build_conversation_section、build_v2_prompt_context | subject标签/parts兼容 |
| `core/context.py` | ChatContext/投影白名单 | 可选关系字段与v4 |
| `memory/schema.py` | SCHEMA_VERSION、建表/补列路径 | 新库与schema16 |
| `memory/migrations.py` | MIGRATIONS；拟新增migrate_v16 | 加列、身份表、事务版本 |
| `memory/conversation_identity.py`（新增） | 有界解析/校验/claim/revision/capsule | 身份纠正与可信来源 |
| `stella_project/plugins/bot_main/ai_gateway.py` | record_group_chat、handle_chat、handle_private_chat、_record_bot_lines；现有reply/@解析 | trusted envelope/confirmed delivery |
| `webui/chat_ingress.py` | 源码已确认的record_message调用处 | 同一关系/claim契约，缺平台关系明确unknown |
| `memory/session_context.py` | SessionState与summary/reset提交路径 | generation/CAS |
| `memory/session_compact.py` | compact_once及输入渲染 | 身份版本校验、带对象摘要 |
| `core/context_budget.py` | 拟新增fit_conversation_parts/ConversationPromptParts | 保护身份/输入，旧generic保留 |
| `core/runtime/turn_service.py` | _compose_prompt、prepare_turn | 接入parts和版本化trace |
| `core/observability/replay.py` | replay_budget_decision | v1/v2冻结回放 |
| 现有测试文件 | §8及§11清单 | 兼容、迁移、cache/compact、权限 |
| 4个新增测试文件 | §8明确路径 | A/B/C失败与新合同 |

[inferred] 首版预期不改 `memory/retrieval_v2.py`/native ABI、全局ranking、addressing权限、delivery重试机制、PERSON backfill或长期配置。若执行中发现某后端丢弃必需user_id，不静默扩大范围：停在parity验收、附实测证据修订计划和impact后再动对应后端。

## 11. Reusable Implementation Context

以下 JSON 供执行者直接消费；证据manifest是 helper 的schema2原样输出，不手工重算。所有 source anchor 以该 HEAD 和工作树快照为准；执行前检查漂移，发生变化只重验受影响范围。

```json
{
  "implementation_context": {
    "task_summary": "Repair Stella group-chat participant confusion through trusted message envelope, attributed memories, source-bound local identity claims, protected budget and summary CAS. Plan only.",
    "acceptance_criteria": [
      "Stable sender never derived from text",
      "All injected memory items attributed or unknown",
      "All deterministic T01-T19 pass",
      "Python/native access scope parity",
      "8K identities protected; no extra normal LLM call",
      "40 real-model samples zero identity conflation, at least36 tasks completed",
      "Additive v16 and rollback verified",
      "Compact stale apply and skip blocked",
      "Every impact direct dependent accounted"
    ],
    "evidence_provenance": {
      "schema_version": 2,
      "head_commit": "038e419da0c60ada84ae91dee7f11a5ece12aec0",
      "generated_plan_path": "docs/plans/2026-10-04-gitnexus-plan-multi-user-identity-repair.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "586a758c0893f04a4f4dd4792f05eae5a55ab30047dadcb2631f7a1a8dd03a04"
      },
      "cited_path_manifest": [
        {
          "path": ".github/workflows/ci.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:fdd5a82926831dc902d6d5986fc862275c49dcb8ae986af5948ca2e18eac0ea5",
          "index_digest": "sha256:fdd5a82926831dc902d6d5986fc862275c49dcb8ae986af5948ca2e18eac0ea5",
          "worktree_digest": "sha256:63de89a47ac1b55e5a0fd35b20c8724d8a8082ddf212f26f2726e9b78f624e81",
          "untracked_digest": "absent"
        },
        {
          "path": "core/context.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:8ff33be933f5b4220ff4983ced15d81be451530586a6042667f82b53071e1094",
          "index_digest": "sha256:8ff33be933f5b4220ff4983ced15d81be451530586a6042667f82b53071e1094",
          "worktree_digest": "sha256:990ff9db9b7afe0d3f46d12fae6901ba815f84964dcbbd170bcef1ec2d20017c",
          "untracked_digest": "absent"
        },
        {
          "path": "core/context_budget.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c251a2d207c10db899aff227938fa98ff09a8f9aeb9edc3c6be97dedb364b849",
          "index_digest": "sha256:c251a2d207c10db899aff227938fa98ff09a8f9aeb9edc3c6be97dedb364b849",
          "worktree_digest": "sha256:204f15d48a7feec840f8408cbaff62291898df775f51e11f7e79c295a7cf9989",
          "untracked_digest": "absent"
        },
        {
          "path": "core/observability/replay.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4e137712058ca9886662a86a586e2bce0a4eed7da27067a318b2fcaef20fb6d5",
          "index_digest": "sha256:4e137712058ca9886662a86a586e2bce0a4eed7da27067a318b2fcaef20fb6d5",
          "worktree_digest": "sha256:acaec43b1c3604fd9de6cb2c58f43db7483f8150772c5c9db5f12798eee49553",
          "untracked_digest": "absent"
        },
        {
          "path": "core/planner.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:166c4ca5b5fd136a98080ee8ab1734a7539a3f3fc9c88c0572dd01e9d94355cc",
          "index_digest": "sha256:166c4ca5b5fd136a98080ee8ab1734a7539a3f3fc9c88c0572dd01e9d94355cc",
          "worktree_digest": "sha256:0758c630415f5d6e207b0b7e3199d1866422e4026bff980dd6dcac062727ec58",
          "untracked_digest": "absent"
        },
        {
          "path": "core/runtime/facade.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:cb6f072ffc6749a176995b7947c666da4711ca3c6cd0e27478f0acad18073f2c",
          "index_digest": "sha256:cb6f072ffc6749a176995b7947c666da4711ca3c6cd0e27478f0acad18073f2c",
          "worktree_digest": "sha256:ae1b4544ba93aab006b29cc9e6013d792c135bcd71893725adb3034eb7dc7443",
          "untracked_digest": "absent"
        },
        {
          "path": "core/runtime/turn_service.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:5ff67a869d004e7a21aba6fc8f0ce2925a6f39098f4bee8f68fe515f8feef800",
          "index_digest": "sha256:5ff67a869d004e7a21aba6fc8f0ce2925a6f39098f4bee8f68fe515f8feef800",
          "worktree_digest": "sha256:7f1e8a53963909d4419b925b848032107af0af36a03b20dc39b997ed05ebadd0",
          "untracked_digest": "absent"
        },
        {
          "path": "core/social/delivery.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:ff023f32956b9400e2a92bfb84c506105a2f299a8a7337827bfda4e8e29373f5",
          "index_digest": "sha256:ff023f32956b9400e2a92bfb84c506105a2f299a8a7337827bfda4e8e29373f5",
          "worktree_digest": "sha256:ff023f32956b9400e2a92bfb84c506105a2f299a8a7337827bfda4e8e29373f5",
          "untracked_digest": "absent"
        },
        {
          "path": "docs/reports/2026-10-04-multi-user-identity-confusion-investigation.md",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "regular"
          },
          "state": "untracked",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "sha256:b3df90c8946027d4522ac3ad0adcd47a77d629b71769e3c87b40a5bccc3b16af"
        },
        {
          "path": "memory/addressing.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:fd6c815e56f76cde9ccd1c95b945ef3e0b323d32a369aba99ce67f751b3708e7",
          "index_digest": "sha256:fd6c815e56f76cde9ccd1c95b945ef3e0b323d32a369aba99ce67f751b3708e7",
          "worktree_digest": "sha256:938ad73adf5d510a8eea117de0af1b92d4388c3bfe2972ca93a0e448caa6e206",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/addressing_intent.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e3f7b7abdec1a4039a16a249f5f267209e53247d2d3b05104cc4aa0daf0f9f21",
          "index_digest": "sha256:e3f7b7abdec1a4039a16a249f5f267209e53247d2d3b05104cc4aa0daf0f9f21",
          "worktree_digest": "sha256:fa591905f82d729cbc25fdb3a2c60dbcc5ae0b208f22d2d343f10816f6db8d9b",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/migrations.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9cc52b00c59922013e049134b557ee7efa35181dde5f4382670faebbf9206e32",
          "index_digest": "sha256:9cc52b00c59922013e049134b557ee7efa35181dde5f4382670faebbf9206e32",
          "worktree_digest": "sha256:339aaac3c4284146bcaa2f872a656aeec0aab3629bff4c8d78cb82fd322b8731",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/ownership.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f657a389cec594cf1f04c1e663f843a0a7fd452d95e33019d5b0fd75eaeab875",
          "index_digest": "sha256:f657a389cec594cf1f04c1e663f843a0a7fd452d95e33019d5b0fd75eaeab875",
          "worktree_digest": "sha256:00ac2c4e237e0220d44328d1bc8f2e7ce8cfbb519122f607e87ef76e3ec73b99",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/pre_processors.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f20bd2a5a8f4d0b3e3925c8d84c6a93dd11642c5d37a6f1cb5d3f4808a5e7f24",
          "index_digest": "sha256:f20bd2a5a8f4d0b3e3925c8d84c6a93dd11642c5d37a6f1cb5d3f4808a5e7f24",
          "worktree_digest": "sha256:48101c08db2e4b8dc7206a2cae10df8f5e5a2e807e279ac8ac4168957ab05846",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/prompt_builder.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:8fa01f5467f657f5d6cdd3824b8da9850cef954a8c7ab3c52c9c577bc8671c87",
          "index_digest": "sha256:8fa01f5467f657f5d6cdd3824b8da9850cef954a8c7ab3c52c9c577bc8671c87",
          "worktree_digest": "sha256:3c8a6eb9d7afcb89f4ebf3d4516b4bba308bb66f67cebe0544bf9b80b0c25048",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/retrieval_v2.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b1a6e6488d2069c5897f24cd4bebf2b1d101af2b96ae0075da0c2666456a37ce",
          "index_digest": "sha256:b1a6e6488d2069c5897f24cd4bebf2b1d101af2b96ae0075da0c2666456a37ce",
          "worktree_digest": "sha256:b29659adbdc516c9f4796bdd9ce20fb874f8c4aa5ae3498d87de7c8383703bd6",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/schema.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:14bfcd5a17f04c69fce2227017ee29a4d78ad460009f449f8654c68b57025b14",
          "index_digest": "sha256:14bfcd5a17f04c69fce2227017ee29a4d78ad460009f449f8654c68b57025b14",
          "worktree_digest": "sha256:58bdf8e922a17f52001e1a70a7a57bdbf3ae793e2d9d2bcd6bf9e1f16adb831a",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/session_compact.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:089ce27c0c6b9b027dfbdd992384d7b02efe99f979c9ba11761a5e3d3ce94f29",
          "index_digest": "sha256:089ce27c0c6b9b027dfbdd992384d7b02efe99f979c9ba11761a5e3d3ce94f29",
          "worktree_digest": "sha256:089ce27c0c6b9b027dfbdd992384d7b02efe99f979c9ba11761a5e3d3ce94f29",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/session_context.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4508dcb1c8dfcc893fd2297198bdf65c0fad3a0300d4035f50e7182bb7d6ec46",
          "index_digest": "sha256:4508dcb1c8dfcc893fd2297198bdf65c0fad3a0300d4035f50e7182bb7d6ec46",
          "worktree_digest": "sha256:4508dcb1c8dfcc893fd2297198bdf65c0fad3a0300d4035f50e7182bb7d6ec46",
          "untracked_digest": "absent"
        },
        {
          "path": "pyproject.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:39d4bc0f2aee0342e36c4bbfaf4b90d265cba2a43325cacadccb4c8d26262d0b",
          "index_digest": "sha256:39d4bc0f2aee0342e36c4bbfaf4b90d265cba2a43325cacadccb4c8d26262d0b",
          "worktree_digest": "sha256:f905626257d35ed923dafb6bf67f8afb6408f14e51f93f5d7c0e7b89938bc0cf",
          "untracked_digest": "absent"
        },
        {
          "path": "stella_project/plugins/bot_main/ai_gateway.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c39c7c5eb51c06683350a80e1239e4ddcba19e1f03f8133e1c3b128335b24190",
          "index_digest": "sha256:c39c7c5eb51c06683350a80e1239e4ddcba19e1f03f8133e1c3b128335b24190",
          "worktree_digest": "sha256:3a5ada14d058dd5766d588e50efa665daf72a8e4e2ee5e52d1756add510b90c6",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/runtime/test_facade_turns.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c86622a9e008ef0464cdbebc365e20bc86da7307be4bf4f22d91286f611b9858",
          "index_digest": "sha256:c86622a9e008ef0464cdbebc365e20bc86da7307be4bf4f22d91286f611b9858",
          "worktree_digest": "sha256:aa2510922ef3dab02fe46edd82521a27790f9bb061d0bc32551c8a685f1f90f9",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_bot_self_source.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a30cc8dfd3c598b37e1acc81c09f87ec9969feb642da0439a3c273c2a271f879",
          "index_digest": "sha256:a30cc8dfd3c598b37e1acc81c09f87ec9969feb642da0439a3c273c2a271f879",
          "worktree_digest": "sha256:8fd792bab6f30fa9d471ebde781f78e4a189a495587ee390d6998b2ca4059b62",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_context_budget.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f08fb39fd69c88097129a570e05ee47d65e2676e20fb112b467345a3003ec812",
          "index_digest": "sha256:f08fb39fd69c88097129a570e05ee47d65e2676e20fb112b467345a3003ec812",
          "worktree_digest": "sha256:6abf9270f3f345802746e25876368dbe52b547975901a5e0f8a7cd1f123ed686",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_context_tail.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:109fb86644013e6554cbf00996af716e7d4e7706e4ba72b7e3c250486e4aa009",
          "index_digest": "sha256:109fb86644013e6554cbf00996af716e7d4e7706e4ba72b7e3c250486e4aa009",
          "worktree_digest": "sha256:109fb86644013e6554cbf00996af716e7d4e7706e4ba72b7e3c250486e4aa009",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_migrations.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4d0c25148e75d241dfa5d19e0441a70615d6bed66ac10b8d593b462c0c32f8bd",
          "index_digest": "sha256:4d0c25148e75d241dfa5d19e0441a70615d6bed66ac10b8d593b462c0c32f8bd",
          "worktree_digest": "sha256:4d0c25148e75d241dfa5d19e0441a70615d6bed66ac10b8d593b462c0c32f8bd",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_personal_memory_scope.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a5012ec78c750f9bfe74cdf09976f1727db1de4865a60347f3300f77c3535989",
          "index_digest": "sha256:a5012ec78c750f9bfe74cdf09976f1727db1de4865a60347f3300f77c3535989",
          "worktree_digest": "sha256:1908de7adfb46a309273808a6d0ae17071645c592d72698381f1672f05284aa7",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_private_chat_ingress.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9df40c234588acaf45b4dde9dadf15d232eb040716e87d84dce71b97a4816e20",
          "index_digest": "sha256:9df40c234588acaf45b4dde9dadf15d232eb040716e87d84dce71b97a4816e20",
          "worktree_digest": "sha256:bea22676d45d595c197dc2ed514f26680d6d8601ddaaf00f0a59ae4bbc3e0959",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_proactive_at_flow.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:03b89e9ebda866c007dffd963961e7644c03688b013174c823d8b2eba568d128",
          "index_digest": "sha256:03b89e9ebda866c007dffd963961e7644c03688b013174c823d8b2eba568d128",
          "worktree_digest": "sha256:c21964239984e9432f970fb0255b3e4c3de25117dd4c839a8243194a5d6ae8f7",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_prompt_builder_v2.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c75bb869b8d205835821bd67ccd57d2ffb573b3affcd3773adde0f04e292e6f1",
          "index_digest": "sha256:c75bb869b8d205835821bd67ccd57d2ffb573b3affcd3773adde0f04e292e6f1",
          "worktree_digest": "sha256:4ad7e1cd105e4e1e0f30b1be49621bb8f2ed8ff197a34f885c3dd983d1ab8410",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_session_compact.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e06e882faf89c06ddc76b8e7cf66539719453b1c158dc422048430947b015bd2",
          "index_digest": "sha256:e06e882faf89c06ddc76b8e7cf66539719453b1c158dc422048430947b015bd2",
          "worktree_digest": "sha256:e06e882faf89c06ddc76b8e7cf66539719453b1c158dc422048430947b015bd2",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_session_context_cache.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:fb0daed74e7326fffaa745b5cacfe558b4bb5b853ce135798fe3e276df40b63a",
          "index_digest": "sha256:fb0daed74e7326fffaa745b5cacfe558b4bb5b853ce135798fe3e276df40b63a",
          "worktree_digest": "sha256:fb0daed74e7326fffaa745b5cacfe558b4bb5b853ce135798fe3e276df40b63a",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_turn_trace_replay.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:38b916e1bb4e5f962ed52ec1296ef39033f465124778c321ce34166bb230cbb4",
          "index_digest": "sha256:38b916e1bb4e5f962ed52ec1296ef39033f465124778c321ce34166bb230cbb4",
          "worktree_digest": "sha256:2f1ebf343806588f8ad2512461bebf6f4ecbf6513cde02ee52eefe964bad3d3f",
          "untracked_digest": "absent"
        },
        {
          "path": "webui/chat_ingress.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:934183552e1c7fd4a80cdd74063a46117523135f8f1b4bbeb4df5b57a63ee44b",
          "index_digest": "sha256:934183552e1c7fd4a80cdd74063a46117523135f8f1b4bbeb4df5b57a63ee44b",
          "worktree_digest": "sha256:4bfacf2270bfec70d58d9741b326680e78b207d73d361d66a73725e70c74d87b",
          "untracked_digest": "absent"
        }
      ]
    },
    "primary_symbols": [
      {
        "symbol": "record_message",
        "file": "memory/pre_processors.py",
        "lines": "55-108",
        "role": "Trusted persistence and source row id",
        "source_verified": true
      },
      {
        "symbol": "build_context",
        "file": "memory/pre_processors.py",
        "lines": "111-246",
        "role": "History/session cache and summary boundary",
        "source_verified": true
      },
      {
        "symbol": "_build_user_context_v2",
        "file": "memory/pre_processors.py",
        "lines": "545-605",
        "role": "Correct scope before both retrieval branches",
        "source_verified": true
      },
      {
        "symbol": "build_conversation_section",
        "file": "memory/prompt_builder.py",
        "lines": "160-183",
        "role": "Ownership rendering before token accounting",
        "source_verified": true
      },
      {
        "symbol": "fit_prompt_to_window",
        "file": "core/context_budget.py",
        "lines": "49-101",
        "role": "Critical generic budget compatibility; new parts route",
        "source_verified": true
      }
    ],
    "related_symbols": [
      {
        "symbol": "ChatContext",
        "relationship": "IMPORTS x30",
        "relevance": "Projection/default constructor compatibility"
      },
      {
        "symbol": "RestrictedPlanner._query_memory",
        "relationship": "retrieval caller",
        "relevance": "Same peer/sender bug"
      },
      {
        "symbol": "retrieve_memories",
        "relationship": "CALLS",
        "relevance": "Scope/ranking unchanged; attribution preserved"
      },
      {
        "symbol": "retrieve_memories_emb",
        "relationship": "CALLS",
        "relevance": "Source located687-751; both fallback paths preserve scope"
      },
      {
        "symbol": "TurnService._compose_prompt",
        "relationship": "CALLS",
        "relevance": "Structure current input and context"
      },
      {
        "symbol": "TurnService.prepare_turn",
        "relationship": "CALLS",
        "relevance": "Budget, limits, trace"
      },
      {
        "symbol": "_record_bot_lines",
        "relationship": "CALLS record_message",
        "relevance": "Confirmed delivery; logical bubble group"
      },
      {
        "symbol": "record_group_chat",
        "relationship": "CALLS record_message",
        "relevance": "Passive listener before matcher"
      },
      {
        "symbol": "handle_chat",
        "relationship": "event ingress",
        "relevance": "Trust platform sender; lock generation"
      },
      {
        "symbol": "handle_private_chat",
        "relationship": "CALLS record_message",
        "relevance": "Canonical private storage; one record"
      },
      {
        "symbol": "classify_addressing",
        "relationship": "semantic classifier",
        "relevance": "Existing prefilter/permissions remain"
      },
      {
        "symbol": "set_preference",
        "relationship": "SQLite transaction",
        "relevance": "Explicit address separate from local alias"
      },
      {
        "symbol": "SessionState",
        "relationship": "summary/cache state",
        "relevance": "Generation CAS and watermark"
      },
      {
        "symbol": "compact_once",
        "relationship": "async summarization",
        "relevance": "Apply and skip checks after await"
      },
      {
        "symbol": "MIGRATIONS",
        "relationship": "version registry",
        "relevance": "Additive schema16"
      },
      {
        "symbol": "_migrate",
        "relationship": "schema compat",
        "relevance": "Fresh DB vs legacy columns"
      },
      {
        "symbol": "replay_budget_decision",
        "relationship": "CALLS fit_prompt_to_window",
        "relevance": "Backward-compatible replay"
      },
      {
        "symbol": "_fetch_recent_tail",
        "relationship": "CALLS",
        "relevance": "Logical contiguous suffix"
      },
      {
        "symbol": "_load_preferred_address",
        "relationship": "pre-context",
        "relevance": "Current target only"
      },
      {
        "symbol": "scope_for_conversation",
        "relationship": "authorization",
        "relevance": "Existing owner/audience scope rules"
      }
    ],
    "execution_path": [
      "Trusted platform event -> canonical context + relations",
      "record_message short transaction -> source_row_id",
      "Idempotent self claim/correction -> persisted identity revision",
      "Correct access scope -> existing ordinary/embedding/native retrieval",
      "Attributed memory + logical tail + trusted identity capsule",
      "Conversation parts budget -> existing TurnService/gate/generation",
      "Confirmed receipts only -> BOT_SELF author+recipient+logical turn",
      "Async compact guarded by generation,identity revision,watermark",
      "Versioned trace frozen snapshot -> offline v1/v2 replay"
    ],
    "pdg_constraints": [
      {
        "description": "access_scope shared def flows into both retrieval branches; pdg flows4 items",
        "affected_statements": [
          "memory/pre_processors.py:560",
          "memory/pre_processors.py:566",
          "memory/pre_processors.py:576",
          "memory/pre_processors.py:586"
        ],
        "implementation_consequence": "Correct sender scope at common definition and Planner; preserve proactive no-target semantics"
      },
      {
        "description": "_fit_prompt controls7 items, marker branch and generic no-marker tail fallback",
        "affected_statements": [
          "core/context_budget.py:50",
          "core/context_budget.py:54",
          "core/context_budget.py:55",
          "core/context_budget.py:66",
          "core/context_budget.py:69"
        ],
        "implementation_consequence": "Keep generic interface; introduce typed protected parts, no text-marker role inference"
      },
      {
        "description": "content flows2 items into unlabelled item and token estimate",
        "affected_statements": [
          "memory/prompt_builder.py:172",
          "memory/prompt_builder.py:175"
        ],
        "implementation_consequence": "Attach provenance labels before token estimate and selection"
      }
    ],
    "architectural_patterns": [
      {
        "pattern": "RuntimeFacade/TurnService existing in-process runtime",
        "example_location": "core/runtime/facade.py:231-281",
        "usage_guidance": "Extend existing pipeline and epoch cancellation; no new engine"
      },
      {
        "pattern": "SPACE/PERSON/audience authorization",
        "example_location": "memory/ownership.py:174",
        "usage_guidance": "Visibility before applicability; no public/private widening"
      },
      {
        "pattern": "Per-version SQLite migration",
        "example_location": "memory/migrations.py:830",
        "usage_guidance": "Schema16 additive transaction; no LLM await in transaction"
      },
      {
        "pattern": "Explicit ChatContext JSON whitelist",
        "example_location": "core/context.py:201-251",
        "usage_guidance": "Version4 optional primitive fields; platform handles excluded"
      },
      {
        "pattern": "Confirmed delivery receipts",
        "example_location": "core/social/delivery.py:61-150",
        "usage_guidance": "Bind BOT_SELF only confirmed bubbles; unknown no auto retry"
      }
    ],
    "files_to_modify": [
      {
        "file": "memory/ownership.py",
        "symbols": [
          "scope_for_chat_context (new)"
        ],
        "intended_change": "Trusted current subject, retain owner/audience visibility"
      },
      {
        "file": "memory/pre_processors.py",
        "symbols": [
          "record_message",
          "build_context",
          "_build_user_context_v2",
          "_fetch_recent_tail"
        ],
        "intended_change": "Persist envelope, identity ordering, structured tail and revision cache"
      },
      {
        "file": "core/planner.py",
        "symbols": [
          "RestrictedPlanner._query_memory"
        ],
        "intended_change": "Shared trusted scope helper and attributed memory"
      },
      {
        "file": "memory/prompt_builder.py",
        "symbols": [
          "build_conversation_section",
          "build_v2_prompt_context"
        ],
        "intended_change": "Subject labels and optional parts contract"
      },
      {
        "file": "core/context.py",
        "symbols": [
          "ChatContext"
        ],
        "intended_change": "Defaulted envelope fields, projection version4"
      },
      {
        "file": "memory/schema.py",
        "symbols": [
          "SCHEMA_VERSION"
        ],
        "intended_change": "Additive schema16 new DB/compat columns"
      },
      {
        "file": "memory/migrations.py",
        "symbols": [
          "MIGRATIONS",
          "migrate_v16 (new)"
        ],
        "intended_change": "Transactional schema16 registry and verification"
      },
      {
        "file": "memory/conversation_identity.py",
        "symbols": [
          "claim parsing/source validation/revision/capsule (new)"
        ],
        "intended_change": "Conversation-local identity facts, no ACL elevation"
      },
      {
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "symbols": [
          "record_group_chat",
          "handle_chat",
          "handle_private_chat",
          "_record_bot_lines"
        ],
        "intended_change": "Trusted reply/mention inputs and confirmed BOT_SELF recipients"
      },
      {
        "file": "webui/chat_ingress.py",
        "symbols": [
          "record_message call sites"
        ],
        "intended_change": "Shared contract for web user and BOT_SELF"
      },
      {
        "file": "memory/session_context.py",
        "symbols": [
          "SessionState"
        ],
        "intended_change": "Reset generation and CAS summary application"
      },
      {
        "file": "memory/session_compact.py",
        "symbols": [
          "compact_once"
        ],
        "intended_change": "Freeze revision/generation across await, recipient labels"
      },
      {
        "file": "core/context_budget.py",
        "symbols": [
          "fit_conversation_parts (new)",
          "ConversationPromptParts (new)"
        ],
        "intended_change": "Structured protected parts, preserve generic API"
      },
      {
        "file": "core/runtime/turn_service.py",
        "symbols": [
          "_compose_prompt",
          "prepare_turn"
        ],
        "intended_change": "Parts path and versioned budget trace"
      },
      {
        "file": "core/observability/replay.py",
        "symbols": [
          "replay_budget_decision"
        ],
        "intended_change": "v1 generic/v2 parts replay from frozen snapshot"
      }
    ],
    "tests": [
      {
        "file": "tests/test_multi_user_identity.py",
        "status": "new",
        "scenarios": [
          "T01,T02 gateway->context captures correct sender and labels",
          "T03 correction author differs from target",
          "T07 scope backend parity",
          "T18 targetless/targeted proactive"
        ]
      },
      {
        "file": "tests/test_message_relations.py",
        "status": "new",
        "scenarios": [
          "T08 reply resolution canonical/bot uniqueness",
          "T09 multi-bubble one logical turn",
          "T10 failed/unknown/no platform id",
          "T11 social-off and ingress"
        ]
      },
      {
        "file": "tests/test_conversation_identity.py",
        "status": "new",
        "scenarios": [
          "T04 rename/cache revision",
          "T05 alias collision distinct uid",
          "T06 no bypass addressing permissions",
          "T15 source-row/idempotent transaction failure"
        ]
      },
      {
        "file": "tests/test_structured_conversation_budget.py",
        "status": "new",
        "scenarios": [
          "T12 token boundary/marker spoof/extreme current input",
          "T13 contiguous logical suffix/summary boundary"
        ]
      },
      {
        "file": "tests/test_prompt_builder_v2.py",
        "status": "existing",
        "scenarios": [
          "Subject and unknown labels; keyword-only compatibility; label token cost"
        ]
      },
      {
        "file": "tests/test_context_budget.py",
        "status": "existing",
        "scenarios": [
          "Generic function unchanged; existing current marker tests"
        ]
      },
      {
        "file": "tests/test_context_tail.py",
        "status": "existing",
        "scenarios": [
          "Time order/gaps/age; recipient and logical unit bounds"
        ]
      },
      {
        "file": "tests/test_session_compact.py",
        "status": "existing",
        "scenarios": [
          "T14 async barrier revision/reset aborts both apply and skip",
          "Failure retry preserves watermark"
        ]
      },
      {
        "file": "tests/test_session_context_cache.py",
        "status": "existing",
        "scenarios": [
          "Identity revision and generation cache invalidation"
        ]
      },
      {
        "file": "tests/test_migrations.py",
        "status": "existing",
        "scenarios": [
          "T16 additive v16/dry-run/idempotent/per-version rollback"
        ]
      },
      {
        "file": "tests/test_personal_memory_scope.py",
        "status": "existing",
        "scenarios": [
          "T07 space/person/private-only across retrieval backends"
        ]
      },
      {
        "file": "tests/test_private_chat_ingress.py",
        "status": "existing",
        "scenarios": [
          "T11/T17 private canonical ownership; one input write"
        ]
      },
      {
        "file": "tests/test_proactive_at_flow.py",
        "status": "existing",
        "scenarios": [
          "T18 trusted target vs no target"
        ]
      },
      {
        "file": "tests/test_bot_self_source.py",
        "status": "existing",
        "scenarios": [
          "T09/T10 author remains BOT_SELF, recipient separate"
        ]
      },
      {
        "file": "tests/test_turn_trace_replay.py",
        "status": "existing",
        "scenarios": [
          "T19 frozen v1/v2 snapshot replay"
        ]
      },
      {
        "file": "tests/runtime/test_facade_turns.py",
        "status": "existing",
        "scenarios": [
          "T17 v3 defaults/v4 projection; epoch reset compatibility"
        ]
      }
    ],
    "verification_commands": [
      "python -m pytest tests/test_prompt_builder_v2.py tests/test_context_budget.py tests/test_context_tail.py tests/test_bot_self_source.py tests/test_session_compact.py tests/test_session_context_cache.py tests/test_turn_trace_replay.py tests/test_migrations.py tests/test_personal_memory_scope.py tests/test_private_chat_ingress.py tests/test_proactive_at_flow.py tests/runtime/test_facade_turns.py -q",
      "python -m pytest tests/test_multi_user_identity.py tests/test_message_relations.py tests/test_conversation_identity.py tests/test_structured_conversation_budget.py -q",
      "python -m pytest tests/runtime tests/capability tests/cometa tests/knowledge tests/observability tests/webui tests/scheduling tests/test_planner.py tests/test_pipeline_compose.py tests/test_ai_gateway_deterministic_reply.py tests/test_jargon_service.py tests/test_short_term_attribution.py tests/test_full_workflow.py tests/test_retrieval_v2_and_schema.py tests/test_retrieval_cache_topic.py tests/test_addressing.py tests/test_addressing_intent.py tests/test_addressing_handler.py -q",
      "python -m pytest tests/ -v --cov=. --cov-branch --cov-report=xml -n auto --dist loadgroup --timeout=120 --timeout-method=thread",
      "docker exec stella-gitnexus node .gitnexus/run.cjs detect-changes --scope all --repo /repo"
    ],
    "risks": [
      "CRITICAL ChatContext/record_message/generic budget; HIGH history/scope/render",
      "record_message graph lower-bound unresolved receiver calls",
      "memory.user_id may be recording owner rather than semantic subject",
      "Claims need valid source and no ACL elevation",
      "Async summary can reintroduce stale identity if CAS incomplete",
      "Native backend parity must be measured",
      "Actual model may conflate despite structurally correct input"
    ],
    "assumptions": [
      "M2 verify platform reply ID/receipt type against sanitized real events; missing/ambiguous -> unknown",
      "M1 load actual native API and test scope plus returned user_id; backup API1 module is not evidence",
      "M2 validate v3/v4 projection and all imports; no new cross-process engine",
      "M0 freeze actual endpoint window, reserves and model bytes; historical process has no source commit binding",
      "8-13.5 engineering days and extra preprocess p95<=20ms are targets; calibrate at M0"
    ],
    "open_questions": [
      "M0 whether preference conflict needs future UI; initial neutral address + existing command",
      "M2 adapter receipt platform IDs stable? missing uses logicalID",
      "Cross-group aliases/general third-party NLP/global ranking/backfill/full JSON summary explicitly deferred"
    ],
    "avoid": [
      "Do not repeat full repository discovery",
      "Do not implement during planning",
      "Do not treat UNKNOWN/empty graph as safe",
      "Do not infer sender/recipient from nickname/topic/adjacency",
      "Do not change SPACE visibility or PRIVATE_ONLY authorization",
      "Do not use group peer_id as person",
      "Do not trust LLM-generated source/owner IDs",
      "Do not automatically change other users address preference",
      "Do not hold SQLite transaction across await",
      "Do not record failed/unknown delivery as confirmed BOT_SELF or resend unknown",
      "Do not add a normal-chat identity LLM call or a second engine",
      "Do not rewrite historical memory owners or aliases without evidence",
      "Do not change native ABI/global ranking in initial fix",
      "Do not regenerate baselines per step; once at M5",
      "Do not claim fake-backend tests demonstrate real-model accuracy"
    ],
    "direct_dependents": {
      "build_context": {
        "risk": "HIGH",
        "impacted": 22,
        "direct": [
          {
            "symbol": "_run",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_bot_question_precedes_user_reply",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_bot_self_rendered_as_wo",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_fresh_summary_keeps_original_label",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_gap_marker_inserted_within_window",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_no_gap_marker_when_continuous",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_no_tail_falls_back_to_exchanges",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_session_summary_precedes_tail",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_stale_messages_excluded_from_tail",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_stale_summary_relabeled",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_summary_and_tail_coexist",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_tail_in_time_order",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_timestamp_unparseable_not_filtered",
            "file": "tests/test_context_tail.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_full_workflow_summary_feeds_next_reply",
            "file": "tests/test_full_workflow.py",
            "relation": "CALLS"
          },
          {
            "symbol": "_build",
            "file": "tests/test_session_context_cache.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_build_context_falls_back_when_column_missing",
            "file": "tests/test_short_term_attribution.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_write_and_read_short_term_keeps_attribution",
            "file": "tests/test_short_term_attribution.py",
            "relation": "CALLS"
          }
        ],
        "epistemic": "exact"
      },
      "fit_prompt_to_window": {
        "risk": "CRITICAL",
        "impacted": 34,
        "direct": [
          {
            "symbol": "replay_budget_decision",
            "file": "core/observability/replay.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_long_prompt_keeps_current_input_marker",
            "file": "tests/test_context_budget.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_short_prompt_is_unchanged",
            "file": "tests/test_context_budget.py",
            "relation": "CALLS"
          },
          {
            "symbol": "_ask",
            "file": "core/planner.py",
            "relation": "CALLS"
          },
          {
            "symbol": "prepare_turn",
            "file": "core/runtime/turn_service.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_offline_replay_matches_frozen_snapshot",
            "file": "tests/test_turn_trace_replay.py",
            "relation": "CALLS"
          }
        ],
        "epistemic": "exact"
      },
      "ChatContext": {
        "risk": "CRITICAL",
        "impacted": 50,
        "direct": [
          {
            "symbol": "delegation.py",
            "file": "capability/delegation.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "hooks.py",
            "file": "capability/hooks.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "planner.py",
            "file": "core/planner.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "facade.py",
            "file": "core/runtime/facade.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "turn_service.py",
            "file": "core/runtime/turn_service.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "post_processors.py",
            "file": "memory/post_processors.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "pre_processors.py",
            "file": "memory/pre_processors.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "ai_gateway.py",
            "file": "stella_project/plugins/bot_main/ai_gateway.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_capability_hooks.py",
            "file": "tests/capability/test_capability_hooks.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_delegation.py",
            "file": "tests/capability/test_delegation.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_gateway_wiring.py",
            "file": "tests/cometa/test_gateway_wiring.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_isolation.py",
            "file": "tests/knowledge/test_isolation.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_message_flow_runtime.py",
            "file": "tests/observability/test_message_flow_runtime.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "legacy_harness.py",
            "file": "tests/runtime/legacy_harness.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "runtime_harness.py",
            "file": "tests/runtime/runtime_harness.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_facade_turns.py",
            "file": "tests/runtime/test_facade_turns.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_turn_service.py",
            "file": "tests/runtime/test_turn_service.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_ai_gateway_deterministic_reply.py",
            "file": "tests/test_ai_gateway_deterministic_reply.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_bot_self_source.py",
            "file": "tests/test_bot_self_source.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_context_tail.py",
            "file": "tests/test_context_tail.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_full_workflow.py",
            "file": "tests/test_full_workflow.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_jargon_service.py",
            "file": "tests/test_jargon_service.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_personal_memory_scope.py",
            "file": "tests/test_personal_memory_scope.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_pipeline_compose.py",
            "file": "tests/test_pipeline_compose.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_planner.py",
            "file": "tests/test_planner.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_private_chat_ingress.py",
            "file": "tests/test_private_chat_ingress.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_proactive_at_flow.py",
            "file": "tests/test_proactive_at_flow.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_session_context_cache.py",
            "file": "tests/test_session_context_cache.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "test_short_term_attribution.py",
            "file": "tests/test_short_term_attribution.py",
            "relation": "IMPORTS"
          },
          {
            "symbol": "chat_ingress.py",
            "file": "webui/chat_ingress.py",
            "relation": "IMPORTS"
          }
        ],
        "epistemic": "exact"
      },
      "record_message": {
        "risk": "CRITICAL",
        "impacted": 25,
        "direct": [
          {
            "symbol": "_record_bot_lines",
            "file": "stella_project/plugins/bot_main/ai_gateway.py",
            "relation": "CALLS"
          },
          {
            "symbol": "handle_private_chat",
            "file": "stella_project/plugins/bot_main/ai_gateway.py",
            "relation": "CALLS"
          },
          {
            "symbol": "record_group_chat",
            "file": "stella_project/plugins/bot_main/ai_gateway.py",
            "relation": "CALLS"
          },
          {
            "symbol": "test_record_message_persists_bot_self",
            "file": "tests/test_bot_self_source.py",
            "relation": "CALLS"
          },
          {
            "symbol": "run_turn",
            "file": "webui/chat_ingress.py",
            "relation": "CALLS"
          }
        ],
        "epistemic": "lower-bound",
        "boundaries": [
          "3 call sites invoking `record_message` were dropped at index time because the receiver's type could not be established (e.g. an unresolved constructor, factory or chained expression). Those callers are absent from this result — actual impact may be higher."
        ]
      }
    },
    "index_refresh": {
      "command": "docker exec stella-gitnexus node .gitnexus/run.cjs analyze --index-only --pdg",
      "outcome": "completed same HEAD; runner/index analyzer provenance matched",
      "limits": [
        "clusters/processes bounded resource summaries",
        "record_message three unresolved receiver callsites",
        "retrieve_memories_emb name context missed; source687-751 verified"
      ]
    },
    "seed_report": "docs/reports/2026-10-04-multi-user-identity-confusion-investigation.md",
    "phases": [
      "M0 fixtures/contract",
      "M1 scope/labels",
      "M2 envelope/schema/receipts",
      "M3 claims/cache",
      "M4 budget/compact CAS/replay",
      "M5 full regression/local-model/rollout"
    ],
    "plan_status": "unimplemented"
  }
}
```

## 12. Assumptions and Open Questions

- [assumed] 平台 reply message ID 能与现有 `group_messages.msg_id` 匹配：执行M2用真实脱敏event/receipt验证类型、reply segment缺失和跨bot重复；不匹配时仅unknown，不猜目标。
- [assumed] 当前Python/Rust API都能保留检索结果的user_id与scope：执行M1/T07验证实际加载后端和返回字段；已有API1备份不算证据。native路径没有跑通就保留未验证项。
- [assumed] 投影v4消费端允许新增白名单字段：执行M2检验旧v3构造/回放和各导入者；当前facade为in-process，不为本任务构建进程桥。
- [assumed] 8K endpoint/runtime reserve与调查中的模型配置可冻结：M0记录真实角色/window和模型摘要，M5同条件测试。历史进程日志未绑定commit，不能证明当时运行的每行等同当前HEAD。
- [assumed] 8–13.5工程日与≤20ms p95为排期/性能目标，需M0测量校准，不是已得结果。
- 待M0确认：已有“本人显式称呼”是否需要在UI呈现冲突提醒。首版采用中性称呼+原命令确认，无需等待新UI才能实施。
- 待M2确认：BOT_SELF每泡receipt ID在不同适配器是否稳定可用；缺ID使用logicalid，不以可选能力阻塞主修复。
- 明确延后：跨群别名统一、一般性第三人实体解析、旧memory的自动个人化backfill、全局ranking重写、全部摘要JSON化、任意复杂中文纠错语义模型。上述均不是本次修复的完成条件。
- 图限制：resources默认截断摘要、record_message receiver漏边、retrieve_memories_emb未被名称context命中，均已来源核实；不能把graph计数当全仓绝对上限。

## 13. Definition of Done

- [ ] M0可复现调查中的三类机制，fixture仅使用合成身份；没有生产数据库改写。
- [ ] 主回复、Planner、embedding正常/回退使用正确可信主体，Python/Rust scope parity通过；SPACE/PERSON/audience边界没有变宽。
- [ ] 每条注入记忆具有归属或unknown标签；当前身份不由他人记忆/旧自由摘要决定。
- [ ] social关闭也记录reply/@；BOT_SELF确认气泡保存真实作者、收件人和逻辑分段；failed/unknown没有虚假已送达记录。
- [ ] 自我介绍、改名、第三人纠正、同名/引用和称呼权限按T01–T06验收，当前uid从未由文本改写；cache立即更新。
- [ ] schema16副本迁移/回滚失败注入/幂等/行数与FTS检查通过；旧数据不自动发明关系或身份。
- [ ] 结构化预算完整保留身份和当前envelope，所有标签计入估算；超小预算有明确DIRECT行为；旧generic接口仍兼容。
- [ ] reset/纠正期间compact apply和skip均通过generation/revision CAS；watermark不跳消息；旧摘要仅作非权威内容。
- [ ] v3/v4投影、私聊/WebChat/主动/命令/Cometa与动态hook相关回归通过，30个ChatContext直接依赖均覆盖。
- [ ] T01–T19确定性测试100%通过；本地模型T20达到0/40串人和≥36/40任务完成，记录采样条件及未覆盖范围。
- [ ] 无新增正常回复LLM调用；性能门槛达标或有测量支持的修订；最终baseline仅刷新一次。
- [ ] 最终detect_changes无partial/truncated，UNKNOWN有补证；小范围发布与可回退验收记录齐全，才把计划状态改为完成。
