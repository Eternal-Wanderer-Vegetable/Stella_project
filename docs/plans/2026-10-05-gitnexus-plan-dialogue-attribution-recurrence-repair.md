# Stella 对话归属复发修复执行计划

> 日期：2026-10-05，Asia/Shanghai。深度：完整执行计划（用户已选择）。
> 状态：**仅计划，交由用户执行；没有实施业务修改、迁移生产数据、调用模型验收或发送 QQ 消息。**
> 证据：工作树基于 HEAD `6b35b6ba85752ddef66c50e2f56d045f6a5bb908`；实际字节以 §11 的 schema-2 provenance 为准。
> GitNexus：Docker `stella-gitnexus`，`/repo`，显式 repo=`Stella_project`，CLI 1.6.11；PDG 已建立。本轮 status 为 0 changed / 20 added / 0 deleted，新增项都是调查报告与证据。索引不覆盖新增材料；业务符号图与当前源码 HEAD 一致。已有刷新耗时 537.6 秒，本轮避免仅为诊断材料再运行该刷新，以源码核对补足；执行时若业务路径变化，必须刷新后重新 impact。
> 完整工作区 dirty digest：b92b6e29caba6b85442428bea338ea9937ebf70e5988f0071ed56faa660a495a；引用路径 78 项。只排除本计划的规范路径。

## 1. 目标与执行边界

将两份调查报告中的四个现场落实为可验证的修复，同时保留群共享上下文、私聊隔离、现有 RuntimeFacade/TurnService、SQLite、异步整合和压缩、正常回复一次模型调用的约束。

验收行为：

- 09:00：私聊中确认并明确要求群内记住的本人事实，进入正确 PERSON 归属与已授权共享受众；同 Bot、同用户在群内提问时能使用，其他人的私聊事实不可见。
- 13:19：Nox 对第三人的称呼不能成为 Nox 自己的名字；“我是Nox，不是红中没摸鱼”应更新本人身份，否定尾句不能成为别名。
- 13:22—13:31：不能把“用户肘其他人”说成“用户肘 Bot”，也不能把 Bot 的“脏手别摸”翻成用户说 Bot 脏手；收到明确纠正后，后续轮次不能维护原错误前提。
- 14:09：主动验证必须仍针对选定候选与目标，不得把另一个人的“开发 Stella”背景变成对当前人的确认问题；无法证实主语/承接时跳过，不消耗候选验证状态。
- 数据修复可预览、可审计、可重复执行、有撤回路径；通过测试、生产条件模型采样和真实 QQ 灰度后才允许宣称修复。

本计划新增的接口、文件、开关和 schema 均为**拟实施**；文中现有行为使用证据标签，设计决策使用 [inferred]。不重做昨日已实施的消息关系/有符号 ID/多气泡投影，也不在本任务更换模型、部署 Laya 或另建身份引擎。

## 2. 当前行为与四个现场

调查输入：

1. `docs/reports/2026-10-05-dialogue-target-recurrence-090046-140919.md`。
2. `docs/reports/2026-10-05-dialogue-target-recheck-131951-132820.md`。
3. `docs/reports/evidence/dialogue-attribution-20261005/` 中的原始 prompt/output、来源消息和 trace；两份 manifest 可核对 SHA-256。

[verified] 时间分三层：用户定位的是本机日志/生成完成时间；memory_traces.ts 与 group_messages.timestamp 为 UTC；QQ message_sent.time 是另一时钟。09:00 首泡平台时间为 09:00:19；13:19 为 13:19:23；“脏手别摸”为平台 13:29:02、本机 13:29:30。第二处按用户确认台词定位并扩展到 13:31，不能机械把 13:28:20 当精确平台时刻。

| 场景 | memory trace | 输入/数据证据 | 失败位置 |
| --- | --- | --- | --- |
| 09:00:46 | 1310 | 私聊 CP 关系已保存，但错误归入 SPACE/space_4；群聊 scope 在 space_1 | 即时整合丢失 ConversationRef；无显式 USER_SHARED 写入 |
| 13:19:51 | 1383/1384 | 当前目标=Nox；候选对象=3644282359“红中”；纠正原文包含逗号 | 生成移换事实对象；身份规则整句拒绝纠正 |
| 13:22—13:31 | 1386—1390 | 摘要保留肘其他人的对象；1390 近期历史明确作者=Bot | 生成侧受体/作者倒置，后续维护错误叙述 |
| 14:09:19 | 1395 | 目标=176403822；“开发 Stella”的背景记录者=3089665724 | 任务模板污染检索模式、跨人取材、发送前缺候选一致性门控 |

[verified] 这些现场的关键轮次均无预算裁剪，当前用户和实际发送对象正确。1390 为 1674/6340、送达 3/3。日志中 message_sent 的长度截断不能解释成模型上下文裁剪。

[verified] 13:19 候选与 14:09 候选的较早来源消息有已清理情况；调查证明“模型接收的候选内容及归属”，没有证明较早候选抽取本身真实无误。实施必须把来源缺失当 unknown，不能根据旧内容重造证据。

## 3. 相关架构与约束

现有执行链：

```text
平台消息 → 可信 ChatContext/ConversationRef → 原消息入库 → 身份声明
        → TurnService.prepare_turn → 记忆访问 scope/检索/预算
        → generate_reply → finalize_turn → 后置解析/分泡
        → 网关交付回执 → BOT_SELF 记录/学习/压缩/主动配额

整合触发 → maybe_consolidate → 后台去重/任务集合
         → consolidate_group 或 consolidate_conversation
         → 同 storage_session_id 的锁 → 候选与证据写入 → checkpoint

主动验证 → pick_target → ProactiveTarget → build_instruction
         → 上述同一运行时 → 空/skip/重复过滤 → deliver_lines
         → acknowledged-only 学习/记录 → record_at(candidate_id)
```

[verified] `core/pipeline.py:45` 只是 TurnService 兼容门面；核心阶段在 `core/runtime/turn_service.py`。新增生成约束接入同一阶段服务，避免网关与原生运行时各有一份逻辑。

[verified] `memory/consolidator.py:611` 已有 consolidate_conversation；`:966` 的 drain_conversation 和 `:984` 的注册会话排空携带完整 ref。即时入口 `:1955` 仍只接收整数，`:1943` 调 consolidate_group；私聊调用在 `ai_gateway.py:1643`。

[verified] PERSON 的现有访问合同是 group=当前 SPACE + 当前用户 USER_SHARED，private=隔离 SPACE + 本人 PRIVATE_ONLY/USER_SHARED，见 `memory/ownership.py:169`。**写共享授权与改私聊整合入口是两件事**；修正空间不会自动完成共享。

[verified] 后置钩子优先级为 parse_output=100、bad_phrase_filter=80、split_lines=60、log_thought=40，见 `ai_gateway.py:656`。finalize_turn 先记录原始 memory trace 再执行钩子，见 `turn_service.py:601`。约束必须在最终分泡与交付之前落实，另记录最终决策，不能覆盖原始模型证据。

[verified] ChatContext JSON 投影是白名单，schema 当前为 4；新增运行时数据需同步字段投影及 round-trip 测试。记忆库 schema 当前 16，Python backend 与 Rust native 精确匹配整库版本，见 `memory_rust/backend.py:19`、`memory_rust/native/src/schema.rs:6`。

[inferred] 采用一次生成、确定性服务端约束、按来源引用的方案。人格维持活泼风格，但不得覆盖平台身份、本人纠正或已验证事实。不能由模型自己声明“校验通过”作为放行依据。

## 4. GitNexus 发现与影响范围

本轮从已完成调查播种，图用于补充实施影响；每个查询回答一个规划问题。已读取 context、clusters、processes 资源：关键模块为 Memory、Bot_main、Runtime、Observability；资源展示有 top-N 限制，空 process 不表示路径不存在。

| 问题/调用 | 关键结果 | 实施处理 |
| --- | --- | --- |
| impact(maybe_consolidate, upstream, depth=3, include-tests) | [graph] risk=HIGH；10 impacted；d1=4；3 affected entry processes | 全部四个入口必须兼容及测试，见 §9 |
| impact(parse_self_alias, upstream, depth=3, include-tests) | [graph] risk=HIGH；8 impacted；d1=2 | 保留旧接口包装；扩大正例时同时加强问句/否定反例 |
| impact(_write_memory_candidates, upstream, depth=3, include-tests) | [graph] risk=HIGH；20 impacted；d1=14 | 维持强化、来源白名单、Bot 排除和事务合同 |
| impact(_proactive_at_user, upstream, depth=3) | [graph] risk=LOW；d1=proactive_speak_job | 门控失败返回 False，保持与主动插话互斥 |
| context(finalize_turn, file=core/runtime/turn_service.py) | [graph] 调用方为 RuntimeFacade.submit_turn 与 TurnService.run | 两条调用面都必须执行同一生成约束 |
| impact(finalize_turn, uid=Method:core/runtime/turn_service.py:TurnService.finalize_turn#1, upstream, depth=3) | [graph] risk=LOW；23 impacted；d1=2；完整结果已解歧 | 覆盖 native facade、legacy Pipeline、取消/超时/直回 |
| context(preview, file=tools/backfill_personal_memory.py) | [graph] 预览经 _verdict_entry；有 apply/revoke 与相关测试 | 复用审计模式，不能直接套用仅允许 group 的旧判据 |
| context(_retrieve_with_optional_backend) | [graph] 检索参数进入 Python/Rust 分支；detect_mode 取 query | 在进入两种 backend 前分离任务与检索文本 |

[verified] 上述影响点已按当前源码核对。三个 HIGH 是实际改动风险提示；riskSharedAxes 较低不豁免。finalize_turn 的首次未解歧结果为 UNKNOWN，已按 UID 重查，不以 UNKNOWN 作为安全结论。

业务索引 HEAD 与当前一致；新增未索引调查材料以文件及哈希引用。执行前按 §11 重新取 provenance，并对每个实际待改符号重跑 impact；本轮结果不是未来修改的长期通行证。

## 5. 语句级 PDG 约束

1. **私聊 ref 的传递。** [graph] pdg_query(flows, target=_consolidate_with_flow, variable=group_id, limit=100) 共 2 条：参数在 `consolidator.py:1932` 用于 trace scope，在 `:1943` 进入 consolidate_group。[verified] 源码同样如此。增加 ref 不能只改业务调用而保留错误 scope；去重键、因果 trace、锁与 checkpoint 必须指向同一会话。

2. **身份复合句拒绝。** [graph] pdg_query(controls, target=parse_self_alias, limit=100) 共 27 条；`conversation_identity.py:112` 的分句符检查 true→`:114` continue；`:120` 零命中→return None。[verified] 这是 Nox 纠正丢弃的控制点。新解析路径必须先识别肯定本人姓名，再处理否定/活动尾句；不能简单删除分句符防线。

3. **主动发送与记账。** [graph] pdg_query(controls, target=_proactive_at_user, limit=200) 共 104 条，已取完整边集并只保留相关切片：`ai_gateway.py:3223` 控制空输出、`:3230` 控制 skip、`:3248` 控制拼接为空、`:3282` 控制已送达段为空；`:3293` 后才进入送达记账。[verified] 来源/问题一致性校验必须在 `:3270` 附近的 deliver_lines 之前；配额及 candidate_id 只能绑定最终获准且已送达的同一问题。

PDG 是函数内基本块关系，不能据其证明模型语义或跨函数事务正确。没有把手工源码推理标成 PDG 边。finalize_turn 的顺序由当前源码确认，未虚构该处的 PDG 结果。

## 6. 拟实施改动

### 6.1 合同、schema 与兼容策略

[inferred] 首个实施提交定义三个小合同，分别接入现有服务：

- **候选验证合同**：candidate_id、记录作者、事实主体、对象、predicate、极性/发生状态、source_conversation_key、source_row_ids、候选内容 digest、验证版本。记录作者不自动等于事实主体；关系的 actor/object 独立。
- **共享授权合同**：Bot/用户/事实 key、发起授权的真实消息行、来源会话、受众、授权/撤回状态、版本。模型输出不能授予 USER_SHARED。
- **回复引用合同**：服务端生成的证据 ID、作者、对象、原文/可验证状态、当前会话、身份 revision、有效生成 epoch；最终放行/拒绝原因和最终文本 digest。

新增文件建议：`memory/proactive_contract.py`、`memory/personal_sharing.py`、`core/dialogue_attribution.py`。它们是现有链路的合同与服务，不另建运行时。

拟增加：candidate 的 verification_contract_json、身份声明的 parser_version，以及 sharing authorization/audit 的有界表。默认空/unknown；不得从历史自由文本自动回填“可靠主语”。先增加 schema._migrate 的幂等建表/加列，再注册下一空闲版本迁移（当前应为 v17），成功后才推进 schema_meta。

同一提交同步 Python/Rust 的 MEMORY_SCHEMA_VERSION；RetrievalRequest 查询/受众合同保持当前 API v2，若实施实际修改 backend 请求语义，则必须同时提升 API 并修改 native，禁止只升级 Python。旧 native 不匹配时明确退到 Python并记录原因，不以“Rust 测试跳过”宣布 native 合格。

ChatContext 增加 typed retrieval_query、verification_contract、attribution_evidence、attribution_decision 等 JSON 安全字段，投影 schema 拟由 4→5；旧投影缺字段按 feature-off/unknown 处理，不能放宽权限。任何跨进程接收端需通过现有 projection round-trip 用例及实际 bridge 契约检查。

### 6.2 统一会话整合入口

文件：`memory/consolidator.py` 与 `ai_gateway.py`；现有 symbols：maybe_consolidate、_consolidate_with_flow、consolidate_group、consolidate_conversation、drain_registered_sessions、session_idle_check_job。

- 给后台触发增加完整 ConversationRef 入参；内部固定 ref 快照，经 consolidate_conversation 执行。保留 maybe_consolidate(group_id) 的正群号兼容包装。
- 私聊即时触发必须传 ref；私聊/已注册会话的 idle 收尾按可信会话键 lookup 后传 ref。真实未注册群可走旧正群号路径。
- consolidate_group 对 <=0 的“群号”在任何 resolve_space/写库/checkpoint 之前拒绝；绝不自行用 -uid 构造私聊 ref。ref 与 storage_session_id/registry 不一致时拒绝并记原因。
- 注册/legacy 排空统一同 storage_session_id 的锁与同一 pending key，避免两个入口并发消费同一批。保留任务集合、完成回调清理、取消与异常清理。
- scope、parent_trace relation、锁、消息查询、checkpoint 的身份一致；不能只改私聊那一行调用。
- 失败/截断不推进 checkpoint；保留当前对不可解析批次的处理政策，不扩大本任务改动范围。新增“错误空间”的拒绝绝不能推进位置。
- 不倒退生产 checkpoint 来“补回记忆”；已消费的历史数据由 §6.7 独立迁移恢复。

完成标准：即时/空闲/定时/重复触发均写入同 ref.memory_space，并保持普通群整合原行为。

### 6.3 本人事实的显式共享与召回

文件：新增 personal_sharing.py；接入已入库消息处理、_write_memory_candidates、现有 memory_evidence/ownership/scope_versions。

- 默认私聊为 PRIVATE_ONLY；只接受平台 sender 本人的肯定分享要求，例如“以后在群里也记得我们CP的关系”。否定、撤回、引用、他人转述、模型的同意台词均不是授权。
- 授权必须绑定具体事实：通过明确事实表述或唯一的近期、同用户私聊事实定位；多个可能事实时暂不共享，自然澄清“你想让我在群里记住哪件事？”。
- 授权与事实抽取异步解耦：先记录真实 source_row_id 的 pending grant；事实尚未整合不能误报已经完成共享。整合写入后同一事务绑定 fact_key、证据与 PERSON/USER_SHARED 副本；消息重放及重试幂等。
- 不将整段私聊、所有 profile、其他成员的关系或药物信息整体公开。允许候选包含“该用户与 Bot 的关系”，不授权另一个人的 PERSON 私聊资料。
- 本版 USER_SHARED 沿用已存在的“同 Bot、同本人跨群聊天可见”语义。明确只限某个群的请求不能提升成全局 USER_SHARED：先保持 PRIVATE_ONLY，提示限定分享尚未完成；细粒度群授权不混入本次 schema/查询合同。
- 授权、复制、memory_evidence、审计、scope version 在同一短事务，无模型/网络 await。撤回只撤销该授权生成的共享行；保留合法 PRIVATE_ONLY 原件。撤回提交后版本推进失败必须整体失败，不能默默继续使用旧缓存。
- [verified] scope_versions.bump 当前会吞 SQLite 错误（`memory/scope_versions.py:62`）。共享/撤回事务须用严格版本推进并验证成功，不直接把该宽松 helper 当授权一致性保证；其他普通记忆调用保持兼容。
- 对“私聊记忆/我们的关系”等明确查询，加入受 scope 约束的本人已授权事实优先通道，预留有界预算；若多条关系互相矛盾则呈现未知/待确认，不以旧 SPACE 排名结果覆写已确认个人事实。
- 同时记录召回各阶段排除原因：可见性、事实状态、pool、排序、预算、cache。调查未确认旧群 SPACE 关系被哪一步排除，先用冻结输入和临时库测量，不能盲目调大所有召回上限。

完成标准：同 Bot 同人可读取已授权事实，未授权/其他人/其他 Bot 不可读取；共享成功与缓存可见一致，撤回即不可见。

### 6.4 可靠身份纠正与旧错误声明清理

文件：`memory/conversation_identity.py`；symbols：parse_self_alias、process_message_identity、record_self_alias_claim、subject_alias。新增有界结构化解析结果，旧 parse_self_alias 可保留 tuple 包装。

- 支持“我是A，不是B”“我叫A，不叫B”“以后叫我A”等本人肯定更正。Nox 原句先获得肯定 A=Nox；“不是红中没摸鱼”不是新名字，活动否定不写别名。
- 问句“我是谁/我是你教父了吗”、否定“这是Lumi不是我”、关系描述“我是她姐”、转述/引号/多重矛盾/权限角色/过长名字不进入可靠本人姓名。无法判定按 unknown；不引入第二个身份模型调用。
- 更正只作用于本会话、平台 sender；旧 self_alias 失活、新声明与 parser_version、revision 同一事务提交。纯“不是B”可撤销本人 B 声明，不能推导另一个人是 B。
- 明确更名语义 supersede；普通自我介绍的并存行为保留兼容，subject_alias 只读取经新规则核验的可用声明；冲突时回到稳定 ID/当前平台昵称，不选择最高 id 就当可靠名字。
- 源 row 必须存在于同会话且作者是本人；第三人纠正继续走现有唯一目标解析，不能把被引用 Bot 作者当成人类目标。
- revision 变化触发现有 compact CAS；await 前生成的旧 capsule/摘要不能在更正后提交。
- 用 §6.7 的预览工具重新核验旧声明，“谁”“你教父了吗”“这是Lumi不”“她姐”等按原文和新规则处理；不能全库删除，也不能把晚于现场的声明当作早期错误原因。

完成标准：第 5 条纠正写入后下一轮 capsule 为 Nox；问句/否定不产生姓名；别名不会跨会话或合并用户 ID。

### 6.5 主动验证：把任务、主题和最终问题分开

文件：ProactiveTarget/build_instruction 所在模块、_proactive_at_user、_build_user_context_v2；新增 proactive_contract.py。

**选择的实现：服务器准备可验证问题，模型只决定自然承接/受限选项；不让模型自由改写事实主体。**

1. pick_target 后读取 candidate 及真实来源，建立候选验证合同。来源已清理、主体不明、极性未知、内容 digest 已变、身份冲突时 skip，并按稳定 candidate key 退避，避免重复空耗。
2. legacy 候选不能把 user_id 当事实主体。只对源消息能够证明的有界谓词建立合同：本人称呼/称呼偏好、明确 actor→object 的称呼关系、已确认本人属性/与 Bot 的关系。无法解析的自由事实暂不主动验证，保留候选等待新的直接证据。
3. 若 Nox→第三人 B“红中”的 source 缺失，跳过；source 完整时可生成“你平时会叫{B的可靠展示名}红中吗？”，不能以“红中”称呼 Nox。昵称空/冲突时不硬点名，不在产品台词输出内部 QQ 号。
4. 服务端生成有限 question_variants 与 choice_id；事实槽由合同填充。模型一次生成只允许 skip 或选择一个 variant，并附当前目标近期事件的 bridge_id。任意自由问题、借他人背景、无法核对的桥接事件一律拒绝；没有合格模板的候选不发送。
5. ctx.message 保留任务语义；retrieval_query 来自候选主题及目标近期实际对话，不含整个指令模板。embedding、Python、Rust、detect_mode、topic cache 都使用这个主题输入；删除 RTX5080 例子仅作减噪，不能成为唯一修复。
6. 主动验证背景不再复用一整组不相关 shared memories。仅加入该合同需要、scope 允许的本人/明确第三人关系证据；行为约束照常保留。普通群聊仍保留共享 SPACE 上下文。
7. 发送前重新校验 candidate_id/digest、target UID、choice、bridge evidence、identity revision/取消状态；没有自由文本重写槽。待发问题必须与合同对应。
8. 继续 acknowledged-only 交付；record_at 的配额只绑定确实发出的同一候选问题。skip、拒绝、失败、未知送达均不得记录该候选为已验证；拒绝原因与尝试退避可单独记录，不能冒充确认次数。

完成标准：GPU 示例不能改变 mode/query；14:09 的错误开发者问题和13:19 的错称呼都在发送之前阻止。正确且可承接的模板仍能发出，不能靠全部 skip 通过验收。

### 6.6 普通生成：来源约束、纠正优先与发送前保护

文件：新增 dialogue_attribution.py；TurnService.prepare_turn/finalize_turn、ChatContext、prompt_builder、post_processors 接入。

- 从可信近期消息、已验证个人事实和当前本人纠正构建小证据表，包含作者、对象、原话及来源。摘要和旧 Bot 的推断台词只按“说过的话”呈现，不能成为“事件已发生”的证据。
- 保留投影 v1 的作者/收件人规则，增加稳定的“纠正优先、风格不改事实”政策；不改写用户人格文件，不把“傲娇”本身认定为根因。
- 拟在原 thought/action 协议之外增加 versioned reply_plan：
  - current_response：回应当前输入的自由口语，不承载未经核实的过去事实；
  - quote_reference：只提供服务端证据 ID，历史原话及说话者由服务端按原文渲染；
  - verified_fact_reference：只能选择服务端已经核验的事实模板与角色槽；
  - correction_ack：使用当前可信纠正生成简短承认；对象不明时承认弄错对象，不编造对象名。
- 模型给出的 author/object/“verified=true”不构成证据。历史引用必须在本轮预算保留、同会话或合法受众的证据集中，且作者/对象/极性/状态核对一致；摘要没有 source ID 时只可作低可信话题提示。
- 服务端引用按来源精确渲染，不能把正确 metadata 与任意错误 paraphrase 拼接；自由 current_response 中出现明显过去事实、指责用户装失忆/甩锅、引用已否定动作等风险表达时，需要合格来源或拒绝该段。
- **边界：有限词法/结构规则无法证明任意中文自由文本完全无角色错误。** 这部分只作为可测量的防线；不能声称加 metadata 或正则即获语义保证。生产采样出现任何漏过的关键倒置，阻止灰度晋级；先收紧对应自由槽为受限模板，仍无法达标则保持 shadow/关闭该能力，另行评估模型方案。
- 原始 raw_output 与 prompt 保留；决定、拒绝原因、最终文本 digest 另记。检查插在 parse_output 之后、bad phrase/split_lines之前（拟 priority=90），并在最终生成内容改变后再复核。guard 拒绝不能被 split_lines 的“......？”默认值绕过；建立明确 reply_disposition，网关和运行时共同遵守。
- 普通回复校验失败时优先去掉无证据历史复述、保留合格当前回应；若剩余无合格段，仅使用不声称过去事实的简短兜底。主动验证失败始终 skip，不用普通兜底去 @ 用户。
- 正常路径只调用一次 CHAT 模型；无额外自动重问。DIRECT/SILENT 不强行执行生成协议；工具/Planner阶段及现有总调用上限不改变。显式直接身份回复也做可信源检查，不能将普通输出检查绕过成跨人引用。
- 有界证据表建议最多16单元/512估算 token，必须纳入现有 fit_conversation_parts；证据/引用单元原子裁剪。最终允许引用的 ID 集合要与实际保留输入一致，不能引用已被预算移除的记录。
- 用户纠正后的新轮次优先当前原文，旧 Bot 的“你肘我”不能压过“我想肘的是Kirito”；这是意图纠正，不自动把“实际肘过Kirito”存成事实。原消息用于审计不删除，但错误推断不可成为引用事实来源。

完成标准：错误 raw output 可保留于日志，但不得进入最终发送/已送达 Bot 历史/表达学习；正常当前话题回应、合法历史引用及人格自然度仍通过 §8。

### 6.7 已污染数据的可审计修复

新增工具建议 `tools/repair_dialogue_attribution.py`，复用现有迁移/回填工具的“preview→apply(batch_id)→revoke”模式；**不直接复用 _verdict_entry**，它在 `backfill_personal_memory.py:168` 只允许 group 来源，并默认保留原 SPACE，不能直接处理错误私聊 SPACE 行。

三种显式操作：

1. private_owner_repair：registry + 源 row + Bot/本人 + 原行 digest 全部匹配后，将错误 SPACE 记忆/候选复制到正确 PERSON/PRIVATE_ONLY；提交新证据及审计后将错误公开 SPACE 行失活，不能让旧副本继续参与群召回。
2. share_grant_apply：另行验证真实本人分享源消息及具体事实，再生成 USER_SHARED。纠正 owner 不是分享授权；不得用 Bot 的同意作为授权。
3. identity_claim_recheck：按新解析器与源消息重检旧声明，变更状态/revision并审计；支持真实 Nox 纠正的幂等补登记。来源缺失/歧义项只列出，不自动定名。

manifest 要带 memory/candidate/claim ID、预期旧内容 digest、来源 row、规范会话、Bot/本人、授权 row、操作类型和新旧状态；apply 重新核对，不能信任 preview 的旧结论。单批次短事务，唯一键防重复，失败回滚，审计与 scope/revision 同时提交。

不迁移整个 space_4；不改变 group_messages 的会话身份；不靠“负数意味着某人”猜 user_id；不倒退 checkpoint/伪造确认次数。清理源旧行的 FTS/status、embedding及缓存版本，验证 Python/Rust/FTS/embedding均不再召回失活错误副本。

撤回共享副本保留正确的 PRIVATE_ONLY；撤回身份变更以原审计为条件，避免覆写随后用户的新纠正。不能把错误公开 SPACE 状态作为默认回滚目标。整库备份恢复只在受控停机恢复中使用，并重新执行归属防线。

### 6.8 开关与观测

拟新增独立开关（config/settings.py，用现有 _env_choice/_env_bool 模式）：

| 开关 | 默认 | 阶段 |
| --- | --- | --- |
| PERSONAL_MEMORY_SHARE_ENABLED | false | 临时库验收后开启指定 Bot/用户 |
| PROACTIVE_VERIFICATION_CONTRACT_MODE | off | off → shadow → enforce |
| REPLY_ATTRIBUTION_GUARD_MODE | off | off → shadow → enforce |

注册 ref 和负群号拒绝是数据正确性修复，不靠关开关恢复错误路由。shadow 只能在严格隔离重放或尚未进入线上修复承诺的观测中使用；实际开放主动验证时先关闭旧自由提问通道，避免影子“看见错误却照发”。

记录：canonical conversation、current user、candidate/evidence ID、source availability、query digest/mode、author/object验证状态、identity/scope revision、guard mode、拒绝原因、原输出/最终输出 digest、receipt及候选记账。沿用现有 trace/flow机制，新增节点须更新 flow_catalog/spec与测试，不另建追踪数据库。敏感私聊正文保留原本地日志政策，普通 flow 仅记 ID/digest。

## 7. 分阶段执行顺序

| 阶段 | 工作与依赖 | 阶段出口 |
| --- | --- | --- |
| R0 | 读取此计划的安全 receipt；重新取 HEAD/provenance；核对两份调查 manifest；备份测试用数据库；冻结四个真实夹具和更早肘人链；建立 persona/生产参数基线 | 有失败判据；oracle 与模型输入分离；无生产写入 |
| R1 | 定义 §6.1 合同、feature-off 行为、schema下一版本、Python/Rust版本与ctx投影；只加结构，不自动迁历史 | 迁移幂等/失败回滚/旧字段默认值与后端退化测试通过 |
| R2 | 修注册会话即时/idle/排空入口与负群号防线；所有 d1 调用兼容 | 私聊三触发路径一致，无重复强化/错误checkpoint |
| R3 | 实现事实级共享授权、pending绑定、撤回、版本与明确关系查询召回；依赖R1/R2 | 授权矩阵、并发重放与撤回缓存测试通过 |
| R4 | 修身份复合纠正、问句/否定/关系反例、事务revision与compact CAS | Nox原句落库并下一轮生效；误识别反例零写入 |
| R5 | 主动验证合同/主题query/模板选择/桥接校验/发送与记账；依赖R1/R4 | 错误问题拒发；可承接的受支持候选可正常发出 |
| R6 | 普通回复证据表、单次生成reply_plan、服务端渲染、最终guard及fallback；依赖R1/R4 | 模拟错误raw_output不进入发送/学习；各运行时一致 |
| R7 | 开发数据修复preview/apply/revoke；在生产库副本检查再跑一次 | 迁移清单可审查，旧错误副本不可召回，撤回不破坏私聊原件 |
| R8 | 完成静态/单元/集成、生产模型采样、分组灰度、真实QQ；最后一次统一更新受影响goldens/flow基线 | §13全通过后，由用户按清单切生产与应用审查后的迁移 |

每阶段开始前对实际编辑的符号运行 impact；HIGH/CRITICAL先列调用面和回归集合。每阶段结束保持树可运行，开关尚未打开时旧功能兼容；需提交时执行 detect_changes(scope=all)，partial/truncated不是清洁检查。不要重复刷新golden掩盖行为变化，最终R8按确认的行为统一更新一次。

### 发布与回滚顺序

1. 使用 SQLite 备份API生成一致快照；记录 schema/应用/native版本及源manifest。不要在运行时只复制.db而漏WAL。
2. 发布兼容schema与归属/身份修复，保持主动与生成guard关闭；完成副本迁移验收。
3. 对指定群/账号开启合同enforce与生成guard；实际原候选来源缺失应skip。已确认的共享仅开启指定本人，不全库泛化。
4. 审查preview后，用户应用归属修复，再独立应用可证明的sharing grants。
5. 灰度至少48小时且达到§8样本量；不足延长。关键错归、越权召回、错误记账或旧错误副本复活任一发生即停止晋级。
6. 回滚首先关闭主动发送/共享新增，保持正确ref与隔离防线；普通guard若影响可用性，退到当前回应受限兜底。不能回到会发已确认错归内容的自由通道。数据按batch撤回合规副本，native/应用版本配套恢复。

## 8. 测试与验收策略

### 8.1 确定性测试（临时库 + 假模型 + 假交付）

[verified] tests/conftest.py 默认关闭 MEMORY_V2_ENABLED。因此新端到端测试必须显式开启V2，并隔离STELLA_HOME、DB、spaces、model与QQ副作用；只跑旧v1默认用例不能算验证生产路径。

| 现有测试文件/新增建议 | 必测输入 → 预期 |
| --- | --- |
| test_private_chat_ingress.py、test_consolidator_core.py；新增 test_consolidation_conversation_trigger.py | 私聊ref三触发路径、legacy正群、负群拒绝、即时+定时竞争、取消及失败→归属/位置/计数正确 |
| test_personal_memory_scope.py、test_personal_memory_concurrency.py；新增 test_personal_memory_sharing.py | 本人肯定分享/否定/引用/第三人/多事实/重复消息/撤回→仅合法共享，PERSON/SCOPE/FTS/embedding一致 |
| test_conversation_identity.py、test_multi_user_identity.py | Nox完整原句、我是谁、这是Lumi不是我、关系描述、重名、第三人无目标、旧版本→正确声明或unknown |
| test_session_compact.py、test_session_context_cache.py | 生成期间身份纠正/reset→旧compact不提交；错误Bot台词不能晋升事实 |
| test_proactive_prompt.py、test_proactive_target.py、test_proactive_at_flow.py | RTX示例改变不影响mode；第三人称呼/开发背景/缺源/候选更新/无桥接→拒发；合法variant→送达后记账一次 |
| test_structured_conversation_budget.py、test_prompt_builder_v2.py、test_context_budget.py | 证据与历史原子裁剪；引用被丢证据→拒绝；保留规则/当前纠正与工具结果 |
| tests/runtime/test_turn_service.py、test_facade_turns.py、test_proactive_native.py；新增 test_reply_attribution_guard.py | 同错误raw output经legacy/native均被拦；DIRECT/SILENT、超时、取消、metadata不一致、malformed计划不泄露标签 |
| test_personal_memory_backfill.py、test_migrations.py；新增 test_dialogue_attribution_repair.py | preview只读、stale digest拒绝、部分失败回滚、幂等、来源缺失不迁、撤回保护随后新数据 |
| test_memory_rust_selector.py、test_memory_rust_promotion.py、test_retrieval_v2_and_schema.py | schema mismatch降级显式；正确native读新库，查询/受众/失活过滤与Python一致 |
| observability/test_proactive_flow_lifecycle.py、test_memory_flow_lifecycle.py | 每个skip/拒绝/失败/送达有终态；业务回滚不留下已确认履历 |

新增文件路径是实施建议，当前不存在；避免把计划里的测试名当成已通过结果。必须保留语义检查的反例：正确metadata+反转自由文本不能仅因metadata正确而通过。

### 8.2 模型重放（无QQ发送、无生产写库）

[verified] scripts/evaluate_dialogue_attribution.py 支持 --system-prompt-file、--max-tokens、--dry-run。但其 build_prompt 重构输入，不能直接覆盖新增pipeline/授权/主动选择流程。实施时扩展为读取真实冻结prompt或通过生产prepare路径组装，并执行新增后处理/guard；不要只给新提示词采样。

固定条件：使用实际group persona完整字节与hash、运行时endpoint/model、temperature、max_tokens、预算、协议版本和可取得的模型指纹。缺失值明确记录；不要默认512 max_tokens、默认无persona或修改温度来“验收通过”。不打印API key。

- 基线：四个现场各10次（40次），只使用出错之前的输入；persona on/off消融另各10次用于解释，不作为交付条件。基线未复现仍保留冻结错误output作为guard反例。
- 修复后：四类真实现场各30次（120次），包含13:22/13:25/13:31多轮前后关系；另保留原16类×5次（80次）并添加12类边缘×5次（60次），共至少260次最终条件验收。
- 12类新增边缘：复合身份纠正；问句误姓名；否定误姓名；关系描述；缺源第三人候选；候选更新竞态；桥接事件属他人；sharing肯定/否定；撤回暖缓存；跨Bot同人；错误metadata/自由文本；guard malformed/预算裁剪。
- 每样本保存实际wire prompt、system hash、raw output、最终output、预算、候选/证据/授权和决定；人工/独立规则按作者、对象、极性、状态、任务完成分别审查。关键词筛查仅辅助，不将它当语义oracle。
- 不把历史错误回复预先塞进“首轮待测输入”；连续纠错场景只纳入该轮真实之前已发生的Bot错误，并单独测清洁历史与污染历史。
- 一次正常CHAT生成、预处理+guard p95增量目标≤20ms（本地不含模型/IO）；总token预算不超当前窗口，生产响应时延p95增量目标≤10%。超过则调小证据/缓存，不关闭归属校验掩盖成本。

门槛：最终发送内容**0关键错归、0越权共享、0不相关候选记账**；原80场景任务完成≥72/80；新增可回答场景完成率≥90%。缺源/无承接skip是正确动作，单独统计，不能把所有主动任务都skip而宣称正常任务完成。0/N只表明这组样本通过，不能宣称未来绝对零错误。

若原始模型仍会出错但guard全部阻断，报告“原始错误率/阻断率/漏过率/兜底率”，不能只报最终0。最终漏过关键错误→该版本不发布enforce，收紧输出槽后重跑受影响样本与关键矩阵。

### 8.3 真实QQ灰度

由用户安排参与账号与测试群，执行四个现场的真实消息序列，含作者交替、回复负号气泡、Nox纠正、私聊事实分享→群问→撤回、主动第三人候选、肘人纠正→摸摸→追问记忆。

至少48小时、200个涉及多人/历史/纠正的有效轮次、20个**有来源且可承接**的主动验证机会；流量不足延长。分别核对最终台词、实际@、receipt、BOT_SELF源/收件人、memory owner/audience、候选记账和缓存撤回。不能用Dashboard页面可见或离线矩阵代替现场验收。

### 8.4 已核实可用的命令与实施后命令

在项目根目录（现有pytest及评估help已验证；下列测试执行属于后续实施）：

```powershell
python -m pytest tests/test_private_chat_ingress.py tests/test_consolidator_core.py tests/test_conversation_identity.py tests/test_multi_user_identity.py tests/test_personal_memory_scope.py tests/test_personal_memory_concurrency.py -q
python -m pytest tests/test_proactive_prompt.py tests/test_proactive_target.py tests/test_proactive_at_flow.py tests/runtime/test_turn_service.py tests/runtime/test_facade_turns.py tests/runtime/test_proactive_native.py -q
python -m pytest tests/test_session_compact.py tests/test_structured_conversation_budget.py tests/test_prompt_builder_v2.py tests/test_migrations.py tests/test_memory_rust_selector.py tests/test_memory_rust_promotion.py -q
python -m pytest tests/ -q
```

新增文件完成后追加到定向测试集合；CI依赖安装/ruff/pytest-xdist遵循 .github/workflows/ci.yml 与 requirements-dev.txt。Ruff若本地未安装，使用CI配置环境，不在计划阶段安装。

现有脚本的纯渲染示例（本次未运行该命令，也不调用模型）：

```powershell
python scripts/evaluate_dialogue_attribution.py --fixture tests/fixtures/dialogue_attribution/recurrence_190922.json --variant V2 --system-prompt-file StellaData/system_prompts/space_1.md --max-tokens 2000 --dry-run
```

真实采样传入当时实际endpoint/model与完整参数，输出到新验收目录；新增四现场夹具/生产链重放支持完成后才使用。不得把旧脚本dry-run当新guard验收。

native项目已有 memory_rust/native/Cargo.toml 与 pyproject.toml（maturin）；版本更新后在该目录执行cargo test，按maturin配置构建wheel，再运行明确选择native的parity测试。本轮未证明本机已装Rust/maturin，缺工具应标记native未验收并由用户准备，不声称skip等于通过。

GitNexus命令沿用Docker：

```powershell
docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs impact maybe_consolidate --direction upstream --depth 3 --repo Stella_project
docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project
```

以上仅代表调用形态；实际所有待编辑符号需分别impact，索引若业务源码变化先刷新 --index-only --pdg。

## 9. 风险与全部直接依赖的处理

| 风险/直接依赖 | 处理 |
| --- | --- |
| HIGH maybe_consolidate：d1=_proactive_speak_impl、handle_chat、handle_private_chat、session_idle_check_job | 正群号兼容、私聊ref、idle lookup、后台去重与四入口集成测试；群门控不能遗漏 |
| HIGH parse_self_alias：d1=process_message_identity、test_self_alias_patterns_bounded | 保留接口包装，新增结构结果经同hook；正例/反例同时验收 |
| HIGH _write_memory_candidates：d1业务=_consolidate_group_core | 写入与证据/共享/版本短事务；禁止网络await；checkpoint与异常原合同保持 |
| 该writer d1 tests（共13项） | test_write_memory_candidates_drops_bot_self_candidate；test_confidence_capped_at_one；test_first_seen_at_not_refreshed_on_reoccurrence；test_reoccurrence_eventually_promotes_end_to_end；test_same_content_different_users_stay_separate；test_same_fact_accumulates_instead_of_duplicating；test_similar_wording_counts_as_same_fact；test_source_kinds_accumulate_across_observations；test_stale_observing_candidate_rejected；test_unrelated_facts_stay_separate；test_write_memory_candidates_whitelist；test_memory_promotion_deadlock._write_one；test_memory_candidates_drop_unknown_sender。保留各断言，新增PERSON重放不强化反例 |
| _proactive_at_user d1=proactive_speak_job | skip/拒绝保持返回False与主动插话互斥；配额只在已送达问题上计数 |
| finalize_turn d1=RuntimeFacade.submit_turn、TurnService.run | 两路径同guard；DIRECT/SILENT零生成；取消/超时及最终posthooks不能漏检查 |
| 新结构协议与persona抵触 | versioned协议、malformed降级、persona完整重放；旧格式只feature-off兼容，enforce不默默退自由输出 |
| 移除其他群背景造成失语/全skip | 只限主动验证任务输入；普通群历史保留；支持候选完成率与有效机会分母独立统计 |
| PERSON复制仍保留错误SPACE副本 | 归属修复提交后旧错误行失活；SQL/FTS/embedding/native和暖缓存同时检查 |
| 共享授权与缓存版本不同步 | 同事务严格版本写入；撤回失败整体回滚；权限变更不依赖TTL |
| native版本不一致 | 同步schema常量、重新构建；回退显式，native验收单列 |
| 新身份声称覆盖权限/跨用户 | stable UID最高；正文不能变换主体或权限；会话边界、引用否定反例 |
| 模型自由文本仍可能绕过结构标签 | 不认自报metadata正确；受限引用模板、风险段拦截及生产漏过率门槛；未知能力不宣称保证 |

单元测试/graph无法证明模型内部因果；尚未确认量化和persona是根因。代码安全性、采样表现、实际QQ行为三项验收独立记录。

## 10. 预计变更文件

| 文件 | 现有符号/位置或拟新增职责 | 目的 |
| --- | --- | --- |
| core/context.py | ChatContext与JSON投影 | 分离主题、传合同/证据/决定 |
| core/runtime/turn_service.py | prepare_turn/finalize_turn及现有组装路径 | 统一政策、预算与最后guard |
| core/dialogue_attribution.py（新增） | 证据合同、解析、服务端渲染、决定 | 约束作者/对象与历史引用 |
| memory/post_processors.py | parse_output、split_lines | 协议解析、拒绝不被兜底绕过 |
| memory/prompt_builder.py | build_v2_named_sections | 受保护规则及有界来源证据 |
| memory/pre_processors.py | _build_user_context_v2 | query分离、主动定向证据、授权关系召回 |
| memory/consolidator.py | maybe_consolidate/_consolidate_with_flow/候选写入 | 注册会话与授权/来源合同 |
| stella_project/plugins/bot_main/ai_gateway.py | 私聊/idle/主动入口、posthook注册 | 接线、发送前复核及记账 |
| memory/conversation_identity.py | 解析、声明、读取 | 复合纠正与误声明阻断 |
| memory/proactive_target.py、proactive_prompt.py | ProactiveTarget/build_instruction | typed候选/受限选项 |
| memory/proactive_contract.py（新增） | 来源/候选/模板/桥接 | 问题不可自由换主体 |
| memory/personal_sharing.py（新增） | grant、绑定、撤回 | 事实级授权 |
| memory/schema.py、migrations.py | additive结构与下一版本 | 幂等、审计 |
| memory/scope_versions.py、cache_keys.py | 严格权限版本/策略版本 | 权限变更缓存同步 |
| memory_rust/backend.py、memory_rust/native/src/schema.rs | schema版本常量 | native精确兼容；若API变动同步backend/native读写面 |
| core/observability/flow_catalog.py及受影响spec | 拟新增guard/share节点 | 观测终态、已知spec合同；编辑前另做impact |
| config/settings.py及相应环境文档 | 拟新增三开关 | 可控开启 |
| tools/repair_dialogue_attribution.py（新增） | preview/apply/revoke | 生产数据修复 |
| scripts/evaluate_dialogue_attribution.py、测试/夹具 | §8 | 生产输入及最终回复验收 |
| memory/session_compact.py/session_context.py（条件变更） | 仅在新证据/身份版本未覆盖现有CAS时 | 不为已正确摘要重写整套压缩 |

不直接编辑 StellaData/.env、persona、生产.db。流程目录仅改新增功能所需的节点，Dashboard/Laya/Cometa扩展不在本计划。

## 11. 可复用实施上下文

下面JSON是执行上下文；provenance由技能原始helper生成，未重实现digest。执行器必须使用read-plan的descriptor receipt读取本计划，校验同一generated_plan_path。全局digest因后续日志追加而变化时，核对引用代码/证据，重新snapshot；不能仅因runtime日志变化推翻已核验业务结论，也不能复用旧global digest。

```json
{
  "implementation_context": {
    "task_summary": "仅执行经用户交接的 Stella 四现场对话归属修复：注册私聊整合、本人分享、身份纠正、主动候选合同和普通回复来源约束。本文件交付时所有新接口/迁移/测试仍为计划。",
    "acceptance_criteria": [
      "09:00 私聊本人事实正确归属，明确授权后群内可用；撤回及跨用户/Bot隔离通过",
      "13:19 Nox复合纠正生效，第三人称呼不能成为本人名字",
      "13:22—13:31 动作对象与Bot原话作者不倒置；纠正优先",
      "14:09 仅发送与选定候选/目标/桥接一致的问题；拒发不确认候选",
      "确定性矩阵、生产persona及参数下至少260次最终样本：0关键错归/越权共享/不相关记账，原80任务完成≥72，新增可回答场景≥90%",
      "真实QQ至少48小时、200有效轮次、20合法主动机会；Python/native实际parity通过；数据修复预览/应用/撤回均审计"
    ],
    "evidence_provenance": {
      "schema_version": 2,
      "head_commit": "6b35b6ba85752ddef66c50e2f56d045f6a5bb908",
      "generated_plan_path": "docs/plans/2026-10-05-gitnexus-plan-dialogue-attribution-recurrence-repair.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "b92b6e29caba6b85442428bea338ea9937ebf70e5988f0071ed56faa660a495a"
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
          "head_digest": "sha256:8b93b0e30864a4e4e1f871cdf7dac49431949b73cf2c871c96f63e376e0a4fa3",
          "index_digest": "sha256:8b93b0e30864a4e4e1f871cdf7dac49431949b73cf2c871c96f63e376e0a4fa3",
          "worktree_digest": "sha256:8b93b0e30864a4e4e1f871cdf7dac49431949b73cf2c871c96f63e376e0a4fa3",
          "untracked_digest": "absent"
        },
        {
          "path": "AGENTS.md",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
          "index_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
          "worktree_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
          "untracked_digest": "absent"
        },
        {
          "path": "StellaData/system_prompts/space_1.md",
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
          "untracked_digest": "sha256:24b96058e4fb8ac88c362b3f65743fd0906388b4b0b1cf34e2d29402fa7bee5f"
        },
        {
          "path": "config/settings.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f5988688a1c41fdefd0be96e396c7d3cf66aee42970d2c5b9221139d1d6ad266",
          "index_digest": "sha256:f5988688a1c41fdefd0be96e396c7d3cf66aee42970d2c5b9221139d1d6ad266",
          "worktree_digest": "sha256:33c47148ef6487d72a832c48621775189bb109f03384a7cbb2633594565b1d90",
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
          "head_digest": "sha256:c8c268431396ef9f353371240affdb8f44fcb31907ebe714419c5aa23b9be6c1",
          "index_digest": "sha256:c8c268431396ef9f353371240affdb8f44fcb31907ebe714419c5aa23b9be6c1",
          "worktree_digest": "sha256:b7593964ad1cfef64b1a37b706ad8bebbb239d9608cd75982007109ceb3c3596",
          "untracked_digest": "absent"
        },
        {
          "path": "core/observability/flow_catalog.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a5a5e45e6babfc2c0fe4a4a24bed5acd2321cdbd48d782da3eaae97e1dcc0ff3",
          "index_digest": "sha256:a5a5e45e6babfc2c0fe4a4a24bed5acd2321cdbd48d782da3eaae97e1dcc0ff3",
          "worktree_digest": "sha256:a5a5e45e6babfc2c0fe4a4a24bed5acd2321cdbd48d782da3eaae97e1dcc0ff3",
          "untracked_digest": "absent"
        },
        {
          "path": "core/pipeline.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:222ef09dfbc08ace4f69534d961766b19a3182583b30e373eea58ede4ebc7ad7",
          "index_digest": "sha256:222ef09dfbc08ace4f69534d961766b19a3182583b30e373eea58ede4ebc7ad7",
          "worktree_digest": "sha256:8a10f1ed57c9d10763f972882db25122efaa5e5f22170095ac265392129164ec",
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
          "head_digest": "sha256:f07b6e16f56689dffa41f508e5c0e0fe4c95df2a8c101c0d704c9413df205f85",
          "index_digest": "sha256:f07b6e16f56689dffa41f508e5c0e0fe4c95df2a8c101c0d704c9413df205f85",
          "worktree_digest": "sha256:f07b6e16f56689dffa41f508e5c0e0fe4c95df2a8c101c0d704c9413df205f85",
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
          "head_digest": "sha256:b31b103d7f0106875ba26b9101e370dd06f8d1ac16a97f86b8156d03fdd53367",
          "index_digest": "sha256:b31b103d7f0106875ba26b9101e370dd06f8d1ac16a97f86b8156d03fdd53367",
          "worktree_digest": "sha256:b31b103d7f0106875ba26b9101e370dd06f8d1ac16a97f86b8156d03fdd53367",
          "untracked_digest": "absent"
        },
        {
          "path": "docs/reports/2026-10-04-dialogue-attribution-model-acceptance.md",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f5447ed82d742d95ad8e01bc26f222ec0773aeffd40f410f02f5a4bc4d698031",
          "index_digest": "sha256:f5447ed82d742d95ad8e01bc26f222ec0773aeffd40f410f02f5a4bc4d698031",
          "worktree_digest": "sha256:f5447ed82d742d95ad8e01bc26f222ec0773aeffd40f410f02f5a4bc4d698031",
          "untracked_digest": "absent"
        },
        {
          "path": "docs/reports/2026-10-05-dialogue-target-recheck-131951-132820.md",
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
          "untracked_digest": "sha256:be342af529f3ef94dd40a457b467281edcb014dcc00ada94d84127f358898901"
        },
        {
          "path": "docs/reports/2026-10-05-dialogue-target-recurrence-090046-140919.md",
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
          "untracked_digest": "sha256:cd9d55f65791fd457b09a598a6d9c30c547b41988f3729949c2b8e05fba9ae82"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/case-090046.json",
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
          "untracked_digest": "sha256:50f4d15400cf9ae97edf8d5ee2452b04abd25940cf2dfce65038f2fb7ba5c229"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/case-140919.json",
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
          "untracked_digest": "sha256:415d7dd33c8462ba044ee9f26d128283575631a0e4d6eb494e10c2c875274c5b"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/cross-case-evidence.json",
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
          "untracked_digest": "sha256:26af40bcd6c53f39c94fde7a11c178177b3c8b1d45443594280b23d66e8d7e50"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/gitnexus-build-user-context.txt",
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
          "untracked_digest": "sha256:45ee0c210a6e414f2274239da6afcd3733bdb00447b35c665cc8fbd07f471e67"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/gitnexus-consolidate-group.txt",
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
          "untracked_digest": "sha256:33453d250639e05b2b83ff0ab9f6d894fe309661a9cbbdac0294a9acb89044dd"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/gitnexus-maybe-consolidate.txt",
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
          "untracked_digest": "sha256:fff308e9186ba7ba3d59dcc5cc752c1a8741a5d4b790fefe29d0ee10a8184406"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/gitnexus-proactive-at.txt",
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
          "untracked_digest": "sha256:395654d3085acab0d984d7d2a0c7cac39f8de2cbef2f4d49d41fdb185a4c6454"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/manifest.json",
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
          "untracked_digest": "sha256:05b6dd2a7443975a31e5cec5ea92600d4c261f77dcd18426a1f0b584d12f0b5f"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/recheck-cross-case.json",
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
          "untracked_digest": "sha256:9189f55c90bd9c0d64b95db0fa32a3c599d50ace5d1cfc951159f7b63e13b6e9"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/recheck-manifest.json",
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
          "untracked_digest": "sha256:a3f8eb3bc3a9cc0be2a380fc54d41657d24922f9ca8f0d030ff7053d911e7467"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/recheck-memory-trace-1381.json",
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
          "untracked_digest": "sha256:2c8e10c46fc471b345e764487b2e5be2258198074260c690bbabeb46ec134e5c"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/recheck-memory-trace-1383.json",
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
          "untracked_digest": "sha256:6adf88b1454a995ed32797b4f7bd9dbac5400d8d4c54cb52d14bb259d0468c97"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/recheck-memory-trace-1384.json",
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
          "untracked_digest": "sha256:c06351b46f3ebbd925f654594724c6b3071f57f18687a3954720724deca829aa"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/recheck-memory-trace-1386.json",
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
          "untracked_digest": "sha256:90b21460a951a3d011a6362f01822741d8c860eba6281c87cd6e91d5af80fcb4"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/recheck-memory-trace-1387.json",
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
          "untracked_digest": "sha256:31700d1718acac3cfc3ec79eeb08f73b86b082737f37a39beb94eec04a0b7ee9"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/recheck-memory-trace-1388.json",
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
          "untracked_digest": "sha256:fb31f8cddd32a273edce671a4878b584fbcd46b1f6c96f86025fbb5f1e83871a"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/recheck-memory-trace-1389.json",
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
          "untracked_digest": "sha256:00eb8ac7a68d2791e4ce5c1ddcd1b81e1acdc4d39ad66ff457b443df762097e7"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261005/recheck-memory-trace-1390.json",
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
          "untracked_digest": "sha256:f21c57953ee44578f837fa5bce85af418d1e88bf8775d791e577bd0ac4d06293"
        },
        {
          "path": "memory/cache_keys.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:69f0a6e4ef409b8f93b52cb51761776c3337e19052e8413f6d811d5d9433b051",
          "index_digest": "sha256:69f0a6e4ef409b8f93b52cb51761776c3337e19052e8413f6d811d5d9433b051",
          "worktree_digest": "sha256:ed290c2450647a86aaa3d1f7cf623daded913b5f058da3585acfbc64e842188a",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/consolidator.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e4b64c416beb9b7fd1b385cc81ed6b347f6454495f87b2eec91dd675697cf0cb",
          "index_digest": "sha256:e4b64c416beb9b7fd1b385cc81ed6b347f6454495f87b2eec91dd675697cf0cb",
          "worktree_digest": "sha256:aa004732273ae5abca12c9f2393cd4d0637eb4c50750da67ff7c0eac222bb90c",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/conversation_identity.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:dd5ac95e7565dd1fa3b845c11d41aa34263ccb6ce94f4d47344c18fe101a690e",
          "index_digest": "sha256:dd5ac95e7565dd1fa3b845c11d41aa34263ccb6ce94f4d47344c18fe101a690e",
          "worktree_digest": "sha256:dd5ac95e7565dd1fa3b845c11d41aa34263ccb6ce94f4d47344c18fe101a690e",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/conversation_registry.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c1c5ae67f7e36ddad84f5e1835caa985af1259110285c19ef59a53ea45d4f688",
          "index_digest": "sha256:c1c5ae67f7e36ddad84f5e1835caa985af1259110285c19ef59a53ea45d4f688",
          "worktree_digest": "sha256:c1c5ae67f7e36ddad84f5e1835caa985af1259110285c19ef59a53ea45d4f688",
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
          "head_digest": "sha256:17ba03890fc016be663b682a4d76898a78cc327ab6148d0635f04a3208c74e66",
          "index_digest": "sha256:17ba03890fc016be663b682a4d76898a78cc327ab6148d0635f04a3208c74e66",
          "worktree_digest": "sha256:27affdd553b1c7e85ae32b77e43112f66415b33308469d6f6ba57b4d28e7b8ad",
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
          "head_digest": "sha256:ee9a14280b62023f0d35808386e27deb5317f9864a341feaf0d820107796c347",
          "index_digest": "sha256:ee9a14280b62023f0d35808386e27deb5317f9864a341feaf0d820107796c347",
          "worktree_digest": "sha256:5d1656176ad23cf129945ce080d68500ab20f44f9e58d1664a29862a718ee541",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/post_processors.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c725f8e42911a8bfcf4a951d4e29dd7f283c0644e6511f57e65b26d87d560d33",
          "index_digest": "sha256:c725f8e42911a8bfcf4a951d4e29dd7f283c0644e6511f57e65b26d87d560d33",
          "worktree_digest": "sha256:47f77377864959e6e1d4dc75ee8d50f1f96e3c3927f4ec0ff9d6381610a5650d",
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
          "head_digest": "sha256:5220e3df5178e2f203adbabb1c60fb515804ada8d0f9488ab0ceabf5119f1fc2",
          "index_digest": "sha256:5220e3df5178e2f203adbabb1c60fb515804ada8d0f9488ab0ceabf5119f1fc2",
          "worktree_digest": "sha256:5220e3df5178e2f203adbabb1c60fb515804ada8d0f9488ab0ceabf5119f1fc2",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/proactive_prompt.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:874b7d3468fae146df4ffa9297703e925befea0875726c36da110be30e061c52",
          "index_digest": "sha256:874b7d3468fae146df4ffa9297703e925befea0875726c36da110be30e061c52",
          "worktree_digest": "sha256:2537e9e72517180d0dfea0d689cd17649c5d7b41a88a0a27cf9e9b7d997d0f65",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/proactive_target.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:ad5292295efa1564795c581a97ee16ce733375a7750895ec9c06e5121ecd053f",
          "index_digest": "sha256:ad5292295efa1564795c581a97ee16ce733375a7750895ec9c06e5121ecd053f",
          "worktree_digest": "sha256:51306dc28e0d1772c2e234515cc21b8395883bd431e787cbddb3714a06ba045d",
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
          "head_digest": "sha256:df67ce2d5ab2e926019099566200c7a92594a25424015af9a5c45ff2bc6f79ad",
          "index_digest": "sha256:df67ce2d5ab2e926019099566200c7a92594a25424015af9a5c45ff2bc6f79ad",
          "worktree_digest": "sha256:27def31def9fe4dcf3d13a5e7fc6e01b9dd722975bfa75b21231dc6d2ad588c7",
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
          "head_digest": "sha256:c149c7844d7fbe2fbfdbb032a69432300db36021d9cfec78be3f8ba4d1c8eecc",
          "index_digest": "sha256:c149c7844d7fbe2fbfdbb032a69432300db36021d9cfec78be3f8ba4d1c8eecc",
          "worktree_digest": "sha256:c53b1e2a7f1d21816303a8858266bfaea6190279bc5e3bb6bf152670920b76f0",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/scope_versions.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4af52696429817e5a41317f63a98bb762b73c493777bd1c6a8127668760d9c75",
          "index_digest": "sha256:4af52696429817e5a41317f63a98bb762b73c493777bd1c6a8127668760d9c75",
          "worktree_digest": "sha256:426f6714ce85261b614991da6b0094a72c9a449ba4447b81019ef9bc25b2957d",
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
          "head_digest": "sha256:a365526068d5fdf23e6424e1da1444acb4cb69fdeeff979b2cc64ac4987718fa",
          "index_digest": "sha256:a365526068d5fdf23e6424e1da1444acb4cb69fdeeff979b2cc64ac4987718fa",
          "worktree_digest": "sha256:a365526068d5fdf23e6424e1da1444acb4cb69fdeeff979b2cc64ac4987718fa",
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
          "head_digest": "sha256:10fc8c6d112e7586bea79b64b599aa2d08164434f42b4eac5fbcda769d85e872",
          "index_digest": "sha256:10fc8c6d112e7586bea79b64b599aa2d08164434f42b4eac5fbcda769d85e872",
          "worktree_digest": "sha256:10fc8c6d112e7586bea79b64b599aa2d08164434f42b4eac5fbcda769d85e872",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/backend.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:07a828ee4f9243c947a949cda7fb986af4a6605f58eeeeaea230c5e9da82a264",
          "index_digest": "sha256:07a828ee4f9243c947a949cda7fb986af4a6605f58eeeeaea230c5e9da82a264",
          "worktree_digest": "sha256:07a828ee4f9243c947a949cda7fb986af4a6605f58eeeeaea230c5e9da82a264",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/native/Cargo.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e7bfbb381cfa15304e4b46187922031f0eb339266091e619f78dc4e22ed08703",
          "index_digest": "sha256:e7bfbb381cfa15304e4b46187922031f0eb339266091e619f78dc4e22ed08703",
          "worktree_digest": "sha256:0d9f3b3075db37aecf804f84d7eef0d8cc64360dede8f1af1e2dd2d1346a00b0",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/native/pyproject.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a7bd8449c7c6c97472bb6cbf871299ae8d5743e69a8fbd2563a141d9bf4df9c6",
          "index_digest": "sha256:a7bd8449c7c6c97472bb6cbf871299ae8d5743e69a8fbd2563a141d9bf4df9c6",
          "worktree_digest": "sha256:82812b99560534f15f62e593d500b995f50197a3648c095ea13d39506df72b4b",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/native/src/schema.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:adeb6fbb2f5deb7550dc6f4b1ddc26b0b51c624185ee58dded33a3ce981cdf99",
          "index_digest": "sha256:adeb6fbb2f5deb7550dc6f4b1ddc26b0b51c624185ee58dded33a3ce981cdf99",
          "worktree_digest": "sha256:adeb6fbb2f5deb7550dc6f4b1ddc26b0b51c624185ee58dded33a3ce981cdf99",
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
          "path": "requirements-dev.txt",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9e84af5f5e54f236fea657ab951f6e8dd513881a138f636936026c105878b298",
          "index_digest": "sha256:9e84af5f5e54f236fea657ab951f6e8dd513881a138f636936026c105878b298",
          "worktree_digest": "sha256:343fe3cde2ece5e2d2a23b7240528b734890ba365e623ce62a6ce7ecf310dc7e",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/evaluate_dialogue_attribution.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:64a3ad0ab7a46c81f9b9a60ed5e801725d87d94a328c9581a40454a2e3074d3f",
          "index_digest": "sha256:64a3ad0ab7a46c81f9b9a60ed5e801725d87d94a328c9581a40454a2e3074d3f",
          "worktree_digest": "sha256:64a3ad0ab7a46c81f9b9a60ed5e801725d87d94a328c9581a40454a2e3074d3f",
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
          "head_digest": "sha256:5fa1eafe8c7acdac22dee52a9212acd11f2d4b283d96cb45e07e40efd61616ca",
          "index_digest": "sha256:5fa1eafe8c7acdac22dee52a9212acd11f2d4b283d96cb45e07e40efd61616ca",
          "worktree_digest": "sha256:5fa1eafe8c7acdac22dee52a9212acd11f2d4b283d96cb45e07e40efd61616ca",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/conftest.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e20d97e3ef0051d0165b00f4b683616527b35ac992549e7c672f61a8e14323eb",
          "index_digest": "sha256:e20d97e3ef0051d0165b00f4b683616527b35ac992549e7c672f61a8e14323eb",
          "worktree_digest": "sha256:2c95f7957354c00456481799de8e030782187d424bfa308ce96bc79b0be975d2",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/fixtures/dialogue_attribution/recurrence_190922.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:05a1a95bd333ab1807e1f936fea5d43181f3a4256b6e830099ba26229e05d154",
          "index_digest": "sha256:05a1a95bd333ab1807e1f936fea5d43181f3a4256b6e830099ba26229e05d154",
          "worktree_digest": "sha256:05a1a95bd333ab1807e1f936fea5d43181f3a4256b6e830099ba26229e05d154",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/observability/test_memory_flow_lifecycle.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4b781834ab8b63167970426d228c7010a5a71f5471450f8c26f77f8ce7f2dc4c",
          "index_digest": "sha256:4b781834ab8b63167970426d228c7010a5a71f5471450f8c26f77f8ce7f2dc4c",
          "worktree_digest": "sha256:4b781834ab8b63167970426d228c7010a5a71f5471450f8c26f77f8ce7f2dc4c",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/observability/test_proactive_flow_lifecycle.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:ce041a075d07f40eee0e5d7bccfefe32e081abbc727ef6d1b329f00420f35acf",
          "index_digest": "sha256:ce041a075d07f40eee0e5d7bccfefe32e081abbc727ef6d1b329f00420f35acf",
          "worktree_digest": "sha256:ce041a075d07f40eee0e5d7bccfefe32e081abbc727ef6d1b329f00420f35acf",
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
          "path": "tests/runtime/test_proactive_native.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d3d8426acf67d7810c10e02b483f36b348c8f54370cbe7b26f6a153afd474c0d",
          "index_digest": "sha256:d3d8426acf67d7810c10e02b483f36b348c8f54370cbe7b26f6a153afd474c0d",
          "worktree_digest": "sha256:274dcf6743c01e00ec136dea230fa47339bb3fef6c439e4323dbc5c94c3f461e",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/runtime/test_turn_service.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b877fff9cb0a7c3c9121724dd16114a58e1a6a13cf7af60d2d75692d0f88a5c0",
          "index_digest": "sha256:b877fff9cb0a7c3c9121724dd16114a58e1a6a13cf7af60d2d75692d0f88a5c0",
          "worktree_digest": "sha256:b877fff9cb0a7c3c9121724dd16114a58e1a6a13cf7af60d2d75692d0f88a5c0",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_consolidator_core.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:6cb81d634be365cb5de3ab614b3117a75416cfa3f3102d0ab3fae0c5e7af2b75",
          "index_digest": "sha256:6cb81d634be365cb5de3ab614b3117a75416cfa3f3102d0ab3fae0c5e7af2b75",
          "worktree_digest": "sha256:61f1f5ea2364a48cac0351fccfe7dad3372b8f9fe8594c2d0a5b2ef4b79edc74",
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
          "path": "tests/test_conversation_identity.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f166a1d3c372e42060e27595c70bb5d4ffc7869545d3cfacc1b49405b6a88516",
          "index_digest": "sha256:f166a1d3c372e42060e27595c70bb5d4ffc7869545d3cfacc1b49405b6a88516",
          "worktree_digest": "sha256:f166a1d3c372e42060e27595c70bb5d4ffc7869545d3cfacc1b49405b6a88516",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_memory_rust_promotion.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9d4202785baeebcb029856bc541110eea8fd71490d00b9615f39784b172de4ff",
          "index_digest": "sha256:9d4202785baeebcb029856bc541110eea8fd71490d00b9615f39784b172de4ff",
          "worktree_digest": "sha256:38b041bc5f48b796dc5791d3c32994a4e2682c7a4afffa47159851f803d55c76",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_memory_rust_selector.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a558a5eeba893e1c8766d561c9b178b6ca41d2b4852ce9c543cfe3f62c2b6611",
          "index_digest": "sha256:a558a5eeba893e1c8766d561c9b178b6ca41d2b4852ce9c543cfe3f62c2b6611",
          "worktree_digest": "sha256:fd062f808dc4f22ec15861b86a445db85b29b552d3ff58b8490f7428cb417d05",
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
          "head_digest": "sha256:664e9fe0a60a02998c4d9a79dc0c1a311860fb7a10100a11597030f37f738365",
          "index_digest": "sha256:664e9fe0a60a02998c4d9a79dc0c1a311860fb7a10100a11597030f37f738365",
          "worktree_digest": "sha256:664e9fe0a60a02998c4d9a79dc0c1a311860fb7a10100a11597030f37f738365",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_multi_user_identity.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:13389e8b7127c059a74e1616e2d386192c1ec3a1989570c1ca34129d022b0d0c",
          "index_digest": "sha256:13389e8b7127c059a74e1616e2d386192c1ec3a1989570c1ca34129d022b0d0c",
          "worktree_digest": "sha256:13389e8b7127c059a74e1616e2d386192c1ec3a1989570c1ca34129d022b0d0c",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_personal_memory_backfill.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d1f355e0cd5823da32d477f0bb81cf9f8ad8ba68672ae3a1a2d33eb1edea446b",
          "index_digest": "sha256:d1f355e0cd5823da32d477f0bb81cf9f8ad8ba68672ae3a1a2d33eb1edea446b",
          "worktree_digest": "sha256:991b17d716beda8db8495a675a67fe845d92f8b2ab25cbac116111ec32bcde7b",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_personal_memory_concurrency.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2f0d0648d3a8971a642e11bb640827af9056291444ce2eaea3243ae76c85818b",
          "index_digest": "sha256:2f0d0648d3a8971a642e11bb640827af9056291444ce2eaea3243ae76c85818b",
          "worktree_digest": "sha256:300ce7c8fc6b36a30c5142b8840ce92e4beefd10392725a49bd69144890cac69",
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
          "head_digest": "sha256:9fc646705fa89ee11c08208d5206b3d5a54c4de7fdde33821b7995ab8d65c7bf",
          "index_digest": "sha256:9fc646705fa89ee11c08208d5206b3d5a54c4de7fdde33821b7995ab8d65c7bf",
          "worktree_digest": "sha256:9fc646705fa89ee11c08208d5206b3d5a54c4de7fdde33821b7995ab8d65c7bf",
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
          "path": "tests/test_proactive_prompt.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:760a6801fbb44a10964510ec97d69e4e9009f530be26c4885e29071dfd6925fc",
          "index_digest": "sha256:760a6801fbb44a10964510ec97d69e4e9009f530be26c4885e29071dfd6925fc",
          "worktree_digest": "sha256:3a2e17b5c30a91e62f594434c819dabb9f4d8926c669af2a2b864fce733de6b2",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_proactive_target.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b3046bf0dc133f90aa4fe65001f4cff0514640da7b276f4bea42d034042052d4",
          "index_digest": "sha256:b3046bf0dc133f90aa4fe65001f4cff0514640da7b276f4bea42d034042052d4",
          "worktree_digest": "sha256:81ecb43fa10a49409247dbd802295a8c0376df763eb9d5089cd11ead0c31e46d",
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
          "head_digest": "sha256:be7d7f9ac0619fab2aaa8bcc4ca5cb0131f1fc1f172e44ab30899469e5d09da3",
          "index_digest": "sha256:be7d7f9ac0619fab2aaa8bcc4ca5cb0131f1fc1f172e44ab30899469e5d09da3",
          "worktree_digest": "sha256:be7d7f9ac0619fab2aaa8bcc4ca5cb0131f1fc1f172e44ab30899469e5d09da3",
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
          "path": "tests/test_structured_conversation_budget.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:73b364670c6d684dadd393d426dbe25890cb95d8e14c514b2bb5c1db664c3b58",
          "index_digest": "sha256:73b364670c6d684dadd393d426dbe25890cb95d8e14c514b2bb5c1db664c3b58",
          "worktree_digest": "sha256:73b364670c6d684dadd393d426dbe25890cb95d8e14c514b2bb5c1db664c3b58",
          "untracked_digest": "absent"
        },
        {
          "path": "tools/backfill_personal_memory.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2a081693b779e89a896484bcbc1e7185bbca6330085de5ab35f1d40bf310db68",
          "index_digest": "sha256:2a081693b779e89a896484bcbc1e7185bbca6330085de5ab35f1d40bf310db68",
          "worktree_digest": "sha256:1005bb310ebed2956399adb483a43893449d8a1dc0130a12221e18b53e29d0e5",
          "untracked_digest": "absent"
        }
      ]
    },
    "primary_symbols": [
      {
        "symbol": "maybe_consolidate",
        "file": "memory/consolidator.py",
        "lines": "1955-1981",
        "role": "HIGH风险：以注册ConversationRef替换负存储ID群整合入口"
      },
      {
        "symbol": "_proactive_at_user",
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "lines": "3102-3346",
        "role": "LOW图风险：候选合同、typed query、发送前复核与ack记账"
      },
      {
        "symbol": "parse_self_alias",
        "file": "memory/conversation_identity.py",
        "lines": "87-129",
        "role": "HIGH风险：有限语法承认复合本人纠正并拒绝问句/否定/关系描述"
      },
      {
        "symbol": "finalize_turn",
        "file": "core/runtime/turn_service.py",
        "lines": "601-606",
        "role": "LOW图风险但跨运行路径：生成后guard及最终处置，不绕过DIRECT/SILENT"
      },
      {
        "symbol": "_write_memory_candidates",
        "file": "memory/consolidator.py",
        "lines": "1382-1515",
        "role": "HIGH风险：PERSON/受众/源证据/候选合同与授权写入"
      }
    ],
    "related_symbols": [
      {
        "symbol": "handle_private_chat",
        "relationship": "CALLS maybe_consolidate",
        "relevance": "即时私聊触发使用注册ref"
      },
      {
        "symbol": "session_idle_check_job",
        "relationship": "CALLS maybe_consolidate",
        "relevance": "空闲整合不从负数猜会话"
      },
      {
        "symbol": "handle_chat",
        "relationship": "CALLS maybe_consolidate",
        "relevance": "保留正群兼容与群整合"
      },
      {
        "symbol": "_proactive_speak_impl",
        "relationship": "CALLS maybe_consolidate",
        "relevance": "保留主动整合正确归属"
      },
      {
        "symbol": "_consolidate_with_flow",
        "relationship": "CALLS consolidate_group",
        "relevance": "trace的会话必须与实际整合ref一致"
      },
      {
        "symbol": "_consolidate_group_core",
        "relationship": "CALLS _write_memory_candidates",
        "relevance": "锁/checkpoint/候选持久化一致"
      },
      {
        "symbol": "process_message_identity",
        "relationship": "CALLS parse_self_alias",
        "relevance": "声明transaction和identity revision"
      },
      {
        "symbol": "proactive_speak_job",
        "relationship": "CALLS _proactive_at_user",
        "relevance": "skip终态与配额"
      },
      {
        "symbol": "_retrieve_with_optional_backend",
        "relationship": "CALLS detect_mode/normalize_mode",
        "relevance": "从typed retrieval_query取主题，保持Python/native一致"
      },
      {
        "symbol": "_build_user_context_v2",
        "relationship": "retrieval/context",
        "relevance": "候选证据隔离及授权关系优先召回"
      },
      {
        "symbol": "RuntimeFacade.submit_turn",
        "relationship": "CALLS TurnService.finalize_turn",
        "relevance": "统一运行时入口"
      },
      {
        "symbol": "TurnService.run",
        "relationship": "CALLS finalize_turn",
        "relevance": "legacy与native协议/guard一致"
      },
      {
        "symbol": "_run_post_hooks",
        "relationship": "post-processing",
        "relevance": "parse后guard优先级90；最终内容改变再校验"
      },
      {
        "symbol": "parse_output",
        "relationship": "post hook",
        "relevance": "先解析，不将模型metadata视作证据"
      },
      {
        "symbol": "split_lines",
        "relationship": "post hook",
        "relevance": "拒绝不被默认气泡绕过"
      },
      {
        "symbol": "_verdict_entry",
        "relationship": "backfill pattern only",
        "relevance": "现有工具仅允许group来源，不能直接修复private SPACE"
      },
      {
        "symbol": "build_v2_named_sections",
        "relationship": "prompt/budget",
        "relevance": "保护身份规则与有界证据"
      },
      {
        "symbol": "bump_scope_versions",
        "relationship": "authorization cache pattern",
        "relevance": "现有错误吞掉行为不能用于严格权限事务"
      }
    ],
    "execution_path": [
      "接手先用read-plan receipt读取规范计划，核对HEAD、引用manifest/global snapshot；业务变更重读和刷新图",
      "R0冻结真实wire prompt、时钟、生产persona和失败输出，定位09:00关系召回排除阶段",
      "R1 additive schema与Python/native版本、ChatContext投影和合同",
      "R2 注册ref接入私聊即时/定时/idle，锁/checkpoint与trace同会话",
      "R3 本人明确事实分享→pending/source绑定→PERSON USER_SHARED；撤回与严格scope版本事务",
      "R4 有界身份语法与旧声明审计/revision",
      "R5 真实来源→候选合同→服务端问题variant→模型choice/bridge→发送前复核→ack记账",
      "R6 可信来源表→生产prepare→一次CHAT→parse→guard→后处理→最终复核→发送/学习处置",
      "R7 副本preview/apply/revoke，通过后用户控制生产修复",
      "R8 确定性/native、生产条件模型矩阵、真实QQ灰度，达标后enforce"
    ],
    "pdg_constraints": [
      {
        "description": "parse_self_alias 的逗号/子句分隔与多匹配分支",
        "affected_statements": [
          "memory/conversation_identity.py:112",
          "memory/conversation_identity.py:114",
          "memory/conversation_identity.py:120"
        ],
        "implementation_consequence": "不简单放开逗号；肯定自称+独立否定尾句以有限语法拆开，问句/关系描述不能晋升身份"
      },
      {
        "description": "主动空目标/过滤/空输出/无送达控制分支；完整104条controls结果已核验",
        "affected_statements": [
          "stella_project/plugins/bot_main/ai_gateway.py:3223",
          "stella_project/plugins/bot_main/ai_gateway.py:3230",
          "stella_project/plugins/bot_main/ai_gateway.py:3248",
          "stella_project/plugins/bot_main/ai_gateway.py:3282",
          "stella_project/plugins/bot_main/ai_gateway.py:3293"
        ],
        "implementation_consequence": "guard拒绝纳入skip，只有同一候选问题已确认送达才记账，不由普通split兜底恢复发送"
      },
      {
        "description": "_consolidate_with_flow 中group_id同时流向trace和consolidate_group",
        "affected_statements": [
          "memory/consolidator.py:1925",
          "memory/consolidator.py:1932",
          "memory/consolidator.py:1943"
        ],
        "implementation_consequence": "迁移为同一注册ref规范身份贯穿trace/锁/checkpoint/整合，禁止仅改存储路由留下错误可观测键"
      }
    ],
    "architectural_patterns": [
      {
        "pattern": "RuntimeFacade/TurnService 单一准备与完成链",
        "example_location": "core/runtime/turn_service.py:finalize_turn",
        "usage_guidance": "新增guard接入现有post hooks及最终处置，不新增并行生成引擎"
      },
      {
        "pattern": "ConversationRef注册与规范scope",
        "example_location": "memory/consolidator.py:consolidate_conversation",
        "usage_guidance": "负storage_id用于存储寻址，不能用于群resolve_space"
      },
      {
        "pattern": "PERSON PRIVATE_ONLY/USER_SHARED",
        "example_location": "memory/ownership.py",
        "usage_guidance": "所有自动私聊写入保持PRIVATE_ONLY；分享必须有本人消息及事实级授权"
      },
      {
        "pattern": "短事务、证据唯一键、版本与回填审计",
        "example_location": "memory/schema.py; tools/backfill_personal_memory.py",
        "usage_guidance": "复用模式，不能直接复用仅group入口或默认保留错误SPACE"
      },
      {
        "pattern": "CAS压缩与epoch/revision",
        "example_location": "memory/session_compact.py:355",
        "usage_guidance": "纠正/取消后旧压缩不得提交；只在现有guard不覆盖时条件修改"
      },
      {
        "pattern": "精确schema native兼容",
        "example_location": "memory_rust/backend.py; memory_rust/native/src/schema.rs",
        "usage_guidance": "同步Python/Rust版本并实际重建/parity；不能把native skip视作通过"
      }
    ],
    "files_to_modify": [
      {
        "file": "core/context.py",
        "symbols": [
          "ChatContext"
        ],
        "intended_change": "typed query、合同、证据与处置；投影版本推进"
      },
      {
        "file": "core/runtime/turn_service.py",
        "symbols": [
          "prepare_turn",
          "finalize_turn",
          "_run_post_hooks"
        ],
        "intended_change": "统一预算、guard、终态和DIRECT/SILENT边界"
      },
      {
        "file": "core/dialogue_attribution.py",
        "symbols": [],
        "intended_change": "新增：来源合同、reply_plan校验、服务端渲染"
      },
      {
        "file": "memory/post_processors.py",
        "symbols": [
          "parse_output",
          "split_lines"
        ],
        "intended_change": "输出协议与拒绝不可绕过"
      },
      {
        "file": "memory/prompt_builder.py",
        "symbols": [
          "build_v2_named_sections"
        ],
        "intended_change": "保护规则及有界证据表"
      },
      {
        "file": "memory/pre_processors.py",
        "symbols": [
          "_build_user_context_v2",
          "_retrieve_with_optional_backend"
        ],
        "intended_change": "typed query、主动定向来源、授权关系召回"
      },
      {
        "file": "memory/consolidator.py",
        "symbols": [
          "maybe_consolidate",
          "_consolidate_with_flow",
          "_write_memory_candidates"
        ],
        "intended_change": "注册ref、来源和分享绑定"
      },
      {
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "symbols": [
          "handle_private_chat",
          "session_idle_check_job",
          "_proactive_at_user"
        ],
        "intended_change": "接线、发送前复核及ack记账"
      },
      {
        "file": "memory/conversation_identity.py",
        "symbols": [
          "parse_self_alias",
          "process_message_identity"
        ],
        "intended_change": "有界复合身份纠正、revision与审计"
      },
      {
        "file": "memory/proactive_target.py",
        "symbols": [
          "ProactiveTarget"
        ],
        "intended_change": "候选合同字段"
      },
      {
        "file": "memory/proactive_prompt.py",
        "symbols": [
          "build_instruction"
        ],
        "intended_change": "受限choice/bridge指令"
      },
      {
        "file": "memory/proactive_contract.py",
        "symbols": [],
        "intended_change": "新增：源证据→合同/服务端question variants"
      },
      {
        "file": "memory/personal_sharing.py",
        "symbols": [],
        "intended_change": "新增：事实级grant/pending/撤回"
      },
      {
        "file": "memory/schema.py",
        "symbols": [],
        "intended_change": "授权/审计及合同字段"
      },
      {
        "file": "memory/migrations.py",
        "symbols": [],
        "intended_change": "下一空闲schema版本additive幂等迁移"
      },
      {
        "file": "memory/scope_versions.py",
        "symbols": [],
        "intended_change": "严格授权版本更新；不吞权限失败"
      },
      {
        "file": "memory/cache_keys.py",
        "symbols": [],
        "intended_change": "协议/受众撤回缓存一致"
      },
      {
        "file": "memory_rust/backend.py",
        "symbols": [],
        "intended_change": "schema兼容；API若改变同步"
      },
      {
        "file": "memory_rust/native/src/schema.rs",
        "symbols": [],
        "intended_change": "schema常量及必要新表兼容"
      },
      {
        "file": "config/settings.py",
        "symbols": [],
        "intended_change": "三个独立开关"
      },
      {
        "file": "core/observability/flow_catalog.py",
        "symbols": [],
        "intended_change": "新节点及受影响spec；编辑前另impact"
      },
      {
        "file": "tools/repair_dialogue_attribution.py",
        "symbols": [],
        "intended_change": "新增：preview/apply/revoke带source/digest/CAS"
      },
      {
        "file": "scripts/evaluate_dialogue_attribution.py",
        "symbols": [
          "build_prompt"
        ],
        "intended_change": "生产prepare/冻结wire及最终guard重放"
      },
      {
        "file": "memory/session_compact.py",
        "symbols": [],
        "intended_change": "条件修改：新证据/身份version若现有CAS未覆盖"
      },
      {
        "file": "memory/session_context.py",
        "symbols": [],
        "intended_change": "条件修改：证据/纠正失效与缓存"
      }
    ],
    "tests": [
      {
        "file": "tests/test_consolidation_conversation_trigger.py",
        "scenarios": [
          "新增：即时/idle/定时private ref及正群兼容→正确scope/checkpoint；负群拒绝；并发/取消"
        ]
      },
      {
        "file": "tests/test_personal_memory_sharing.py",
        "scenarios": [
          "新增：本人肯定分享/否定/引用/第三人/多事实→正确受众；pending幂等；暖缓存撤回；跨Bot/用户隔离；Python/native parity"
        ]
      },
      {
        "file": "tests/test_conversation_identity.py",
        "scenarios": [
          "我是Nox，不是红中没摸鱼→Nox；我是谁/这是Lumi不是我/她姐→unknown；随后轮次identity revision更新"
        ]
      },
      {
        "file": "tests/test_proactive_at_flow.py",
        "scenarios": [
          "Nox称第三人红中、他人开发背景、缺源、候选变化、无bridge→skip且不确认；合法variant交付→一次记账"
        ]
      },
      {
        "file": "tests/test_reply_attribution_guard.py",
        "scenarios": [
          "新增：Bot脏手原话/用户肘他人→反转raw输出被拦；正确metadata+错误自由文本不能通过；parse/malformed/取消/超时/预算/DIRECT/SILENT；实际legacy/native一致"
        ]
      },
      {
        "file": "tests/test_dialogue_attribution_repair.py",
        "scenarios": [
          "新增：preview只读；stale digest拒绝；失败回滚；重复应用幂等；未知来源不迁；撤回不覆盖后来纠正；旧SPACE不可召回"
        ]
      },
      {
        "file": "tests/test_memory_rust_selector.py",
        "scenarios": [
          "schema mismatch显式降级；新schema实际native构建、可用与隔离"
        ]
      },
      {
        "file": "tests/test_memory_rust_promotion.py",
        "scenarios": [
          "新字段/受众/失活行过滤与Python一致"
        ]
      },
      {
        "file": "tests/observability/test_proactive_flow_lifecycle.py",
        "scenarios": [
          "skip/拒绝/失败/交付均有终态；不能写已确认履历"
        ]
      },
      {
        "file": "scripts/evaluate_dialogue_attribution.py",
        "scenarios": [
          "扩展：四现场120+旧80+边缘60≥260；完整生产persona/参数/wire；最终台词语义oracle与完成率；真实QQ另验"
        ]
      }
    ],
    "verification_commands": [
      "python -m pytest --version",
      "python scripts/evaluate_dialogue_attribution.py --help",
      "python -m pytest tests/test_private_chat_ingress.py tests/test_consolidator_core.py tests/test_conversation_identity.py tests/test_multi_user_identity.py tests/test_personal_memory_scope.py tests/test_personal_memory_concurrency.py -q",
      "python -m pytest tests/test_proactive_prompt.py tests/test_proactive_target.py tests/test_proactive_at_flow.py tests/runtime/test_turn_service.py tests/runtime/test_facade_turns.py tests/runtime/test_proactive_native.py -q",
      "python -m pytest tests/ -q",
      "docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs impact maybe_consolidate --direction upstream --depth 3 --repo Stella_project",
      "docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project"
    ],
    "risks": [
      "HIGH: maybe_consolidate、parse_self_alias、_write_memory_candidates；按§9回归所有d1业务调用和测试",
      "LOW图风险不等于生成链低业务风险；动态hook/跨语言需要源码与真实重放",
      "任意自由自然语言的角色语义不能完全静态证明，关键漏过即停止晋级并收紧槽",
      "旧来源清理导致unknown；不得补造来源或批量分享",
      "授权scope版本必须与行变更同事务且失败关闭；原helper吞错须使用严格路径",
      "升级schema必须native重构建和实际parity；缺工具保持未验收",
      "数据修复不可把错误公开SPACE恢复作为默认rollback；不能一次搬整个space_4"
    ],
    "assumptions": [
      "接手HEAD/引用字节可能改变：read-plan receipt+snapshot核对；业务漂移先重读/刷新图",
      "schema17与ctx投影5是假定下一空闲版本：检查当前迁移/投影注册表后再分配",
      "协议在当前CHAT后端是否可靠：完整persona+生产参数测malformed、完成率和最终漏过",
      "09:00旧SPACE关系未召回具体阶段未证实：R0测scope池/排行/缓存排除原因再针对性改",
      "源消息可用性需apply/发送时再核验：缺源unknown",
      "本机Rust/maturin依赖未验证：用户准备后真正构建，不能跳过并称通过",
      "USER_SHARED继续既有跨群语义；明确限群授权保持私有并澄清，不能静默扩大"
    ],
    "open_questions": [
      "R0确定09:00已存在群关系未入prompt的具体阶段",
      "无法可靠解析/已丢来源候选需要多少新本人证据；先skip不阻塞安全修复",
      "生产重放中自由current_response是否仍漏过关键归属；若漏过需要收紧哪些槽",
      "限单群事实分享权限合同延期，不纳入本版广域USER_SHARED"
    ],
    "avoid": [
      "不要重复整个仓库发现；以报告/manifest/本pack为起点，漂移范围重核",
      "不要把本计划、新测试或旧80样本当成已修复证据",
      "不要重做已正确的BOT_SELF、有符号消息ID和v1投影",
      "不要用负storage_id推断群/本人身份；禁止私聊进入resolve_space",
      "不要将条件/否定/问句/引用/第三人称呼转成本人事实",
      "不要用Bot承诺替代本人分享授权；不要自动把全部private设USER_SHARED",
      "不要让模型metadata证明事实；不要自由改写主动问题主体或用他人bridge",
      "不要让guard拒绝被split_lines兜底恢复成主动@发送",
      "不要新增第二模型判定/并行身份引擎或扩大Dashboard/Laya/Cometa范围",
      "不要迁移整个space_4、倒退checkpoint或伪造候选确认",
      "每个实际符号编辑前impact；HIGH/CRITICAL需预先报告；UNKNOWN必须源码补证；提交前detect_changes完整",
      "交付当前计划后停止；业务实施和生产操作由用户执行"
    ],
    "verification_notes": [
      {
        "command": "python -m pytest --version",
        "status": "本轮已运行，pytest 9.1.1；仅工具可用性"
      },
      {
        "command": "python scripts/evaluate_dialogue_attribution.py --help",
        "status": "本轮已运行；已核实fixture/variant/system-prompt-file/max-tokens/dry-run"
      },
      {
        "command": "python -m pytest tests/test_private_chat_ingress.py tests/test_consolidator_core.py tests/test_conversation_identity.py tests/test_multi_user_identity.py tests/test_personal_memory_scope.py tests/test_personal_memory_concurrency.py -q",
        "status": "现有路径已核实；实施后运行，本轮未执行"
      },
      {
        "command": "python -m pytest tests/test_proactive_prompt.py tests/test_proactive_target.py tests/test_proactive_at_flow.py tests/runtime/test_turn_service.py tests/runtime/test_facade_turns.py tests/runtime/test_proactive_native.py -q",
        "status": "现有路径已核实；实施后运行"
      },
      {
        "command": "python -m pytest tests/ -q",
        "status": "现有CI/test入口；实施后运行"
      },
      {
        "command": "docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs impact maybe_consolidate --direction upstream --depth 3 --repo Stella_project",
        "status": "已运行同形态impact；每一实际编辑符号重新执行"
      },
      {
        "command": "docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project",
        "status": "现有CLI接口；提交前执行，partial/truncated不算通过"
      }
    ]
  }
}
```

## 12. 假设、未决项与延期范围

- [assumed] 开始执行时仍基于上述业务HEAD，或者已有可解释后续修改。检查read-plan receipt、git HEAD及cited manifest；有引用内容变动先重读该范围，不能只替换commit pin。
- [assumed] schema下一空闲版本为17、ctx投影下一版本为5；实现前检查注册表/接收端，冲突顺延，不覆盖他人迁移。
- [assumed] 新功能通过单模型输出协议在现有CHAT后端可用；用完整persona和生产参数测malformed/完成率。不能假定此协议天然可靠。
- [verified] 原来的80样本未携带生产persona，旧V0样例10次也未复现；本计划要求新260次与实际QQ门槛，不以旧通过结果抵扣。
- [inferred] 已授权本人关系优先召回会改善09:00；旧SPACE关系当时未入prompt的具体排序阶段尚未证实。R0/R3必须先复现排除原因，不能凭猜测改所有检索权重。
- source row已清理的候选/记忆：保持unknown，不主动验证或自动分享。需要新的本人证据，或者由用户提供可审计的原始来源；不能用模型生成补来源。
- USER_SHARED本版继续既有跨群语义；限单群授权待独立合同/后端权限设计，当前明确限群请求保持私有并澄清，不能扩大受众。
- schema升级必须native重构建；本轮只确认工程文件/版本合同，未确认本机编译依赖齐备。
- 自由自然语言语义无法由有限静态规则完全证明；若最终漏过率未达门槛，R6/R8不得晋级。后续模型/量化/原生role数组方案需另做有同等输入的对照，不能夹在此次修复里未经证据直接替换。
- 延期：通用身份知识图、任意事件抽取、Laya第二判定器、模型替换、Dashboard整体重构、跨Bot共享、自动恢复缺失来源、细粒度群授权。
- 本计划不包含生产迁移实际授权与测试账号协调的执行动作；这些由接手用户按计划控制，规划阶段没有运行。

## 13. 完成定义

以下全部满足，才能标记“修复完成”：

- [ ] 四个冻结现场及更早肘人链均有独立oracle、实际输入与原始失败输出，时间口径准确。
- [ ] 私聊即时/idle/定时全部走注册ref，负存储ID不能触发resolve_space或错误checkpoint推进。
- [ ] 显式事实共享、pending绑定、幂等、撤回、跨用户/Bot隔离、暖缓存与backend一致性均通过。
- [ ] Nox完整纠正下一轮生效；“我是谁”“这是Lumi不是我”等不形成可靠姓名，旧误声明经审计处理。
- [ ] 主动验证只发送与当前合同一致的服务端问题，缺源/无桥接拒发，合法机会可发送，拒发不消耗候选确认状态。
- [ ] Bot作者/动作对象倒置不能进入最终发送；原始输出、guard决定、最终台词可分别追踪；legacy/native、取消/超时/预算边界都覆盖。
- [ ] 数据修复preview/apply/revoke已在副本验证，旧错误SPACE副本不可召回；生产实际应用有批次审计与完整备份。
- [ ] Python/Rust schema契约和实际native parity合格；失败退化原因明确，skip不冒充通过。
- [ ] 最终生产条件≥260采样达到§8安全与任务门槛，报告原始错误/阻断/漏过/兜底；性能预算达标。
- [ ] 真实QQ灰度达到时长与有效机会分母，未出现关键归属/授权/记账错误；不足则延长。
- [ ] 最终goldens/spec基线只按确认行为统一更新；提交前detect_changes无partial/truncated，测试和未决限制如实记录。

**当前完成的只有调查与本执行计划；所有R0—R8实施/验收勾选仍为空，由用户接手执行。**
