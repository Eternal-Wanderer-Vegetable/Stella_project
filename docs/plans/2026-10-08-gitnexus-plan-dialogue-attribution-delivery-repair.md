# GitNexus Engineering Plan — Stella 对话归属、压缩与记忆来源修复

> Task: 修复多人对话中的作者、回复对象、动作主体和事实主体混淆，阻止错误摘要与记忆再次污染回复；本文件交给用户执行。
> Evidence verified at commit 827ed665c9d6316c5871b3e967719473f61b6755；分支 codex/fix-6.1.0-rust-release-contract。Docker stella-gitnexus /repo，GitNexus 1.6.11，Node 22.23.2；本轮执行一次 analyze --index-only --pdg。
> Index: 2026-10-08 15:09:58 UTC / 23:09:58 Asia/Shanghai；status 确认 HEAD、runner identity 与 1062 个覆盖文件一致。90347 nodes、220340 edges、969 clusters、826 flows。
> Evidence provenance schema 2；global dirty digest d5197ed24b5c48bb9e7079efcaf9c215fae340b0d4b30d33307b84f554035f89；cited-path manifest 68 个排序条目；只排除本计划的精确路径。
> 状态：PLAN READY / IMPLEMENTATION NOT STARTED / FIELD ACCEPTANCE NOT READY。本轮只新增本计划，没有修改业务代码、测试、配置或生产数据，也没有调用聊天模型或发送 QQ 消息。

## 1. Objective

[inferred] 修复目标分为四个可独立核验的合同：

1. 作者、当前用户、回复对象、动作双方、现实事实主体分别有可靠来源；引用合法不能被当成自由台词语义正确。
2. 被校验的回复与最终发送的每段文本一致；拒绝、不发送、失败和未知送达都不能被备用台词覆盖。
3. Compact 保留原始发言及归属；记忆候选、画像、晋升和主动追问消费同一来源资格，不因模型 confidence 高而绕过。
4. 纠正能使同一错误 claim 的候选与派生数据失效；持久版本、暖缓存、在途生成和撤销都保持一致。

[inferred] 保留正常聊天的一次主模型调用、当前人格、合法第一人称表达、群共享背景、Bot 自己的已发送台词和已授权的私人记忆访问。高风险归属纠正使用服务端受限模板；普通自由聊天的语义正确性用真实模型与 QQ 验收衡量，不宣称 schema 能证明任意中文台词正确。

## 2. Current Behaviour

[verified] 现场依据为 [10 月 8 日成因报告](../reports/2026-10-08-dialogue-attribution-recurrence-root-cause.md)、[冻结案例快照](../reports/evidence/dialogue-attribution-20261008/case-snapshot.json)、[当前 guard 探针](../reports/evidence/dialogue-attribution-20261008/guard-probe.json)。日志时间是本地 +08；平台消息时间与日志时间分别保留，不以报告生成时间替代事件时间。

| 现场 | 已证明的错误 | 修复验收入口 |
|---|---|---|
| 19:09:40 胃疼主动追问 | 10 月 6 日 source row 42757 的状态枚举被归为 3813363809 本人胃疼；用户说明说的是老板；错误 FACT 已改观察规则，错误 EVENT 仍 CONFIRMED | 抽取、画像、晋升、主动合同、同 claim 撤销 |
| 20:19:50–20:20:28 司书角色 | 当前用户 Ain 3089665724，授予对象是栗子 457548580；后续明确澄清仍未保持对象 | reply 关系、纠正与摘要 |
| 21:06:36 “怪怪的” | user row 49245 作者明确，Bot 却说“那是我自己说过的话”；trace 1970，2916/6340 token，3/3 段确认送达 | 合法引用加作者倒置、Compact 消融、最终交付 |
| 22:31:28 写小说纠正 | 用户 457548580 自述写小说，Bot 称自己先说写小说；trace 2004，2280/6340，3/3 送达 | 当前纠正必须由受限模板消费 |
| 22:41:51 读完一本书 | Bot 提问、用户 1840848147 回答，却倒置为 Bot 阅读、用户提问；trace 2007，2123/6340，2/2 送达 | 提问者、阅读者和对象分别验证 |

[verified] 155 条 trace 中 134 条缺 reply_plan、21 条有 plan；这个比例是协议遵循率线索，不是错归属率。当前 guard 和主动合同处于 shadow。当前模型为 qwen3.8-flash-next-iq2_xs；没有模型/量化 A/B，不能将量化列为已确认原因。

[verified] 源码与运行记录共同证明下列缺口：

- core/dialogue_attribution.py:180–215 同时要求普通 reply 与额外 reply_plan；:534–535 只查 plan.current_response。memory/post_processors.py:27–57 则独立提取 reply，并可退回 raw 余文。两个台词来源可不一致。
- ai_gateway.py:679–711 在 hook 中再解析 plan；shadow 不改台词。TurnService.finalize_turn:644–649 在 post hooks 之前记录 raw trace；绿色 hook 不是持久化的语义判断。
- memory/post_processors.py:67–79 对 suppressed 留空，但 ai_gateway.py:1466–1468、1886–1887 又补“......？”。主动 @ 在 :3611–3629 改写 ctx.lines，主动群聊在 :4145–4150 合并段；现有 guard 不是最终发送边界。
- session_compact.py:64–103 要求自由文本合并；:374–381 把非空结果直接提交。21:01 后摘要出现“我（2150738692）回应蜂蜜”等错误第一人称。原始作者投影正确；摘要是有证据支持的放大路径，尚不能证明它是五个案例的唯一原因。
- consolidator.py:1487–1492 只核发言者在真实发送者白名单；:1567–1587 未验证 source IDs 的作者、会话及语义支持。:823–825 先写画像；stage2 失败可保留 stage1 候选。来源 45448/45348、48647/48602 的实际错绑已有冻结证据。
- pre_processors.py:1048–1065 将空 subject 的检索内容当事实，以 recording user 推作者，并使用当前会话代替实际来源；dialogue_attribution.py:451–467 的 verified 不能证明事实主体。
- proactive_target.py:170–175、302–307 按 recording user 选人；ai_gateway.py:3333–3348 的合同仅允许 PERSON/subject==target，群 SPACE 候选无法合格。直接 enforce 会把合法群候选也拒掉。
- session_context.py:104–117 的 summary_version 使用 compact_count；:229–235 清摘要未改该计数；pre_processors.py:303–315 缓存键未包含 reset_generation。此为静态缓存合同缺口，尚未证明生产发生过清空后缓存回潮。

## 3. Relevant Architecture

[verified] 当前生产链为：QQ group/private ingress → RuntimeFacade.submit_turn / TurnService.prepare_turn → build_context 与预算保留 → provider → finalize_turn → parse/filter/guard/split post hooks → ai_gateway 入口兜底或主动合同改写 → deliver_lines → 分段 receipt → 确认文本写 BOT_SELF 与表达学习。DIRECT/SILENT 与 timeout/provider_error/budget/no_backend 有不同分支，见 facade.py:322、368、404–426。

[verified] 归属有两种不同含义：owner/audience 决定谁能读取；fact subject 决定事实说的是谁。ownership.py:63、69–78 规定 SPACE 的 owner.subject_key 必须为空，PERSON 才有 subject。群共享记忆应继续 SPACE/CURRENT_SPACE，新增独立语义主体，不改现有授权边界。

[verified] session_context.py:15–16 的摘要仅在进程内；持久记忆使用 schema_meta、memory_evidence、memory_scope_versions 和版本化迁移。schema.py:64 当前 v18；memory_rust/backend.py:14、19 和 native/schema.rs:3、6 当前 API 2/schema 18，selector.py:76–85 与 native/schema.rs:32 精确检查。

[inferred] 目标链只允许一个最终交付对象：

~~~mermaid
flowchart LR
  I["当前消息 + 保留证据 + 版本"] --> P["唯一 ReplyEnvelope"]
  P --> G["结构验证 + 服务端风险路由"]
  G --> R["受限槽渲染 / 普通回应"]
  R --> F["格式处理 + 最终 DeliveryPlan 封存"]
  F --> S["版本及摘要校验后逐段发送"]
  S --> H["确认送达文本入历史与学习"]
  G --> D["持久 guard decision"]
  F --> D
  S --> D
~~~

[inferred] 所有摘要、事实与台词引用必须来自预算实际保留的 evidence IDs。裁剪、会话切换、身份更正、记忆失效会改变可用证据；不能校验被裁掉或已经撤销的引用。

## 4. GitNexus Findings

[graph] 主调查节点控制在 5 个：apply_attribution_guard、compact_once、apply_summary、_write_memory_candidates、_process_new_candidates_rust。关联查询覆盖 attribution_guard_hook、finalize_turn、build_attribution_evidence、pick_target、_build_proactive_contract、promote_inner、migrate_v18；source-read 后决定修改点。

| 中心及工具 | upstream depth 3 结果 | 直接依赖/执行影响 |
|---|---|---|
| impact apply_attribution_guard | LOW，4 impacted，d1=2 | attribution_guard_hook、评估器 _guard_stage |
| impact attribution_guard_hook | UNKNOWN，0 解析 caller | 实际 ai_gateway.py:733–737 动态注册；turn_service.py:689–704 动态执行，已源码补证 |
| impact finalize_turn 精确 UID | LOW，2 impacted，d1=2 | RuntimeFacade.submit_turn、TurnService.run |
| impact compact_once | **HIGH**，17 impacted，d1=11 | schedule_compact._run 与 Compact/usage tests；群私上下文 |
| impact apply_summary | **CRITICAL**，22 impacted，d1=11 | compact_once 与 context/tail/cache tests |
| impact _write_memory_candidates | **HIGH**，4 impacted，d1=1 | _consolidate_group_core → _consolidate_with_root → consolidate_conversation/group；5 consolidation_drain_job processes |
| impact _process_new_candidates_rust | **HIGH**，5 impacted，d1=1 | process_new_candidates；间接 _consolidate_group_core、validate_rust_fullchain |
| impact build_attribution_evidence | LOW，3 impacted，d1=1 | _build_user_context_v2 → build_user_context → capability.hooks._retrieve_memory |
| impact pick_target / _build_proactive_contract | 各 LOW，2 impacted，d1=1 | _proactive_at_user → proactive_speak_job；各涉及 7 processes |

[graph] 上述 impact 返回完整，未报告 partial/truncated。finalize_turn 曾有测试 FakePipeline 同名，通过 UID Method:core/runtime/turn_service.py:TurnService.finalize_turn#1 消歧。HIGH/CRITICAL 是执行前警告；不能用 riskSharedAxes 的较低值取消它们。

[graph] 索引的 process 枚举有预算限制：2534/2734 候选丢弃、44 budget-cut、24 depth-capped、682 callee 丢弃；还有动态调用与跨语言边解析限制。缺 flow/零 caller 不能证明路径不存在。native promote_inner 图只解析 Rust 内部 promote，Python→native 以请求构造、selector 合同和真实运行验证补足。

[verified] _process_new_candidates_rust:414 先调用 Python 晋升 gate，:446–472 构造 PromotionRequest；native promote:748–764 校验 schema、开启 Immediate 事务、读取 candidate，再执行 promote_inner。promote_inner:441–458 仅检查 scope/status 的当前入口，尚无本方案的证据或 epoch CAS。

## 5. Statement-Level PDG Findings

[graph] MCP pdg_query 对以下 3 个函数运行 controls/flows；完整返回均未截断。原始 JSON 保留在仓库外调查 scratch，计划只保留 13 个控制/数据约束。BasicBlock 行范围是保守粒度，不能读成已证明任意语义流。

| 函数/源码锚点 | 精选 slice | 实施约束 |
|---|---|---|
| _decide，dialogue_attribution.py:496–569；controls 41，reply_plan flows 10 | ① 517 plan is None → 518 enforce；② 518T →519 fallback/521 return；③ 518F →522 shadow/523 return；④ reply_plan →525 validate refs；⑤ →534 free current 检查；⑥ 540 enforce →543 reject/545 empty，或548 fallback/549 current | 新 parser failure 不得进入 raw 台词；single typed 对象成为 gate 与 renderer 的共同输入。shadow pass 的诊断必须显式，不能标 verified |
| compact_once，session_compact.py:298–381；controls 50，result flows 2 | ⑦ result 定义358 →374 判空；⑧ 366 !guard_ok →372 False；⑨ 374T →377 skip_range/378 True；⑩ 374F →380 apply_summary/381 True | packet 验证必须先于 apply；协议错误不能视为真“无”；保留旧 CAS 和失败不推进 |
| _write_memory_candidates，consolidator.py:1382–1780；controls106，source_ids flows13 | ⑪ 1488 sender whitelist →1491 continue；⑫ 1528 PERSON 条件控制 evidence 写入；⑬ 1565/1573/1575 source_ids →1576 保存及1634强化写入 | 发言者白名单不等于事实支持；SPACE/PERSON 都写精确来源；所有 insert/update/reinforce 分支走同一审核，不能仅补新建行 |

[verified] 新方案不得在 Compact guard_ok 与实际状态提交之间新增 await；记忆语义审核可异步，但落库时必须重核 epoch/source digest。PDG 约束和源码约束分别保留，不把图中没有字段解释为字段永远没有调用者。

## 6. Proposed Changes

本节所有新增类型、字段、表、版本、函数名均为 **proposed**；现有修改目标已在上述固定 HEAD 读源码。下面的设计决策为 [inferred]，执行者按合同实现，不再在几套互相冲突的方案间选择。

### 6.1 冻结四个版本和一个证据身份

[inferred] 冻结 ReplyEnvelope/DeliveryPlan/SummaryPacket/provenance 的独立格式版本为 2026-10-08.1；core/context.py JSON projection 从 v5 升 v6，旧 v5 解码时缺失字段明确设为 unsealed/legacy，不补“已验证”。记忆数据库升 **schema 19**；本计划为 PromotionRequest 增加 CAS 字段，因此后端 API 从 **2 升 3**。更新 Python/native 常量、selector、构建验证和版本断言，不继续标 API2。

[inferred] 证据身份使用现有 canonical conversation + Bot + stable user identity。消息证据由服务端绑定本地 row ID、平台 message ID、作者、reply/recipient、原文、source kind、digest；显示名只用于渲染。用户输入和模型输出不能自行创造合法 evidence ID。BOT_SELF 消息只由确认送达记录生成。

### 6.2 唯一 ReplyEnvelope 与受限风险路由

[inferred] 修改 parse_output、apply_attribution_guard、attribution_guard_hook、finalize_turn，采用一个根、一个 reply 的协议。示例不是完整工具 action 枚举：

~~~xml
<response version="2026-10-08.1">
  <thought>诊断元数据</thought>
  <action>NONE</action>
  <reply kind="quote">
    <quote evidence_id="msg_49245"/>
  </reply>
</response>
~~~

[inferred] reply.kind 限定 social/quote/facts/correction/clarify/skip。social.current 是正常聊天的有限自由回应；quote/facts/correction 只给服务端批准的引用槽和用途，原文、作者、对象及承认模板由服务端填。thought 不进入台词；action 保留现有诊断语义及允许值，本次不新增 XML action executor。工具沿现有 Planner/Capability 授权执行链路；工具结果和委派回执按真实来源进入 DeliveryDraft，不能凭模型 action 标签取得执行权限。

[inferred] parser 只接受已知版本、唯一根、规定标签及数量；关闭 DTD/实体，设字节/深度/段数上限，拒绝块外台词、多 reply、残缺 XML、未知引用和冲突槽。parse_output 返回一个 typed 对象，后续不再用 regex 从 raw 另取台词。恶意构造、模型违约和普通格式失败有不同 reason，但均不得 raw fallback。

[inferred] 服务端风险优先级高于模型自报。下列情况关闭本轮自由 current：可靠 current_correction、已知作者/动作归属冲突、对象不能唯一消解、reply 对象与生成目标不一致、身份或来源版本过期。模型申报历史断言、纠正、引用或不确定性只提升风险，不能把服务端高风险降为 social。

[inferred] prepare 侧构造 proposed AttributionRiskContext：从 canonical reply relation、已存在的当前纠正解析结果和 retained evidence 获取 signal_code、supporting_evidence_ids、target_resolution(exact/ambiguous/unknown)、identity_revision。不得新造一个未经验收的regex后称它识别全部纠正。信号缺证/目标不唯一走 clarify；typed槽的目标仅与可信目标字段比较。模型风险只能追加，不能删服务端信号；任意social.current的隐含作者语义仍是semantic_unverified。

[inferred] 高风险回复例：

- 作者明确：“这句话是{作者显示名}说的：「{原话}」。刚才是我把发言归属搞混了。”
- 当前用户明确纠正：“刚才是我搞混了。你这次说的是：「{纠正原句}」。”
- 目标未定：“我可能把几个人的话混在一起了。你指的是哪句话、哪位？”

[inferred] template 后不拼接模型自由台词。不要一刀切禁止“我”，也不把合法 ref、kind=social 或有限词法匹配当语义证明。“看完一本”等普通陈述若风险识别未捕获，仍属于真实模型验收必须发现的边界。普通聊天不加 verifier LLM、不自动二次生成；模型失败采用确定性澄清/安全退路/明确不发送。

[inferred] build_attribution_evidence 同时保留人类和 Bot 已送达的 speech evidence；事实证据使用 §6.5 的审核结果。unknown subject 不填当前用户，来源会话不填当前会话。参与者、作者、收件人、事实主语分别渲染。最终保留 ID 集合在预算完成后冻结。

### 6.3 DeliveryPlan 最终封存与真正不发送

[inferred] core/context.py 新字段：typed_reply、retained_evidence_ids、attribution_risk_context、delivery_draft、delivery_plan、guard_decision。DeliveryPlan 至少包括 schema_version、plan_id、source_kind、protocol_version、disposition、conversation_key、target_user_id、identity_revision、generation_epoch、captured_scope_versions、segments、digest；每段包括 part_index/text/text_digest/origin/evidence_ids。只传 JSON 值，不传 event/Bot 句柄。digest包含捕获版本图及目标，sender不得从可变ctx补入版本。

[inferred] 顺序为 parse → guard/render → bad phrase handling → typed segment formatting → 所有主动合同变体和群聊合并 → final seal → sender。统一规范化在校验前声明；作者标签+原话是不可拆的逻辑段。split_lines 不可删括号内主语、裁掉引用标签或静默截半段；超限重新选择完整单元或走明确失败分支。

[inferred] finalize_turn 产出 guard/render/format 后的 DeliveryDraft 和 guard decision；四发送入口完成全部变体与合并后调用同一个 proposed final-seal helper，产生唯一最终DeliveryPlan。DIRECT/fallback也通过该helper。deliver_lines只接受sealed plan，不替调用方隐式封存，避免在finalize里提前seal再持有两份有效计划。

[inferred] bad_phrase_filter 若替换台词，记录 reason 并以新文本重新 seal。主动 @ 的 contract variant 和主动群的合并在 seal 前完成。群、私、主动 @、主动群四条实际入口只消费 sealed plan；封存后任何变更必须重封存或拒发。

[inferred] 修复空回复兜底：先判断 disposition。suppressed/skip 不创建“......？”；可信服务端fallback用明确来源构造Draft再seal。DIRECT仅表示零主模型调用，由允许的producer明确source_kind和来源：确定性identity/fallback/ack可为trusted-server；插件/工具自由正文不能因DIRECT自动成为verified事实，仍走目标/身份/format/seal。SILENT不构造待发送plan；timeout/provider_error/budget/no_backend不送入LLM legacy adapter。

[inferred] identity_revision/generation_epoch由同一会话可信状态提供器捕获；claim epochs由持久scope-version提供器捕获。每段调用send_one前同步核conversation/target/版本图/plan digest；失败的未启动段不发送。已启动平台请求属于在途，复核后到ACK前epoch变化不能推出“未送达”，按实际ack/failed/unknown记录，后续段中止。当前按段复核不承诺取消在途请求；若要求平台请求启动与reset严格互斥，须另加共用发送许可同步门及race验收。unknown不重试；BOT_SELF/学习只收ack实际文本。

### 6.4 持久决策与短期兼容

[inferred] 保留 raw generation snapshot，追加 durable guard 与 final seal decision。复用 message_flow.decision:1507–1529 的 status/reason_code/metrics/instance_key/fact_kind，不为 trace 顺序调整丢 raw 失败证据。

[inferred] decision 字段至少为 protocol/parse status、guard mode、semantic_status、disposition、risk class/sources、reason codes、checked/retained/invalid IDs、identity/generation、turn/trace/conversation、raw/parsed/guard/final digests、template ID、plan ID、段数及段摘要。明确 structural_pass / semantic_unverified / deterministic_render；绿色 hook 不显示“语义归属已通过”。

[inferred] send.prepare 链接 plan_id/digest；每段 receipt 保存 part_index、实际 digest、ack/failed/unknown；aggregate 同时表示传输和持久化状态。flow 写失败披露 loss，不自动重发；ctx 内存状态不能替代 durable evidence。

[inferred] 兼容期限定为一个发布版本、上线后最长 7 天，并记录实际 compatibility_deadline。新 prompt 只输出新格式。旧 thought/action/reply 通过显式 adapter 转为单一 candidate，走同一 guard/seal；旧 reply + reply_plan 两份规范化台词不一致即 legacy_dual_output_conflict。残缺 plan/raw 余文不提取为待发送文本。到期关闭线上 LLM legacy 写入；历史重放可显式 legacy 模式。兼容解析不表示语义安全。

### 6.5 Compact 改为可验证 SummaryPacket

[inferred] 修改 session_compact.py 的输入映射、协议与提交验证；新增服务端 SummaryPacket。保留覆盖开区间、原始非空 row count、canonical conversation/Bot、guard triple、来源 metadata、完整原文及 selected_refs。模型只从本批和旧合法 packet 中选择证据 ID；服务端回填原文、作者、对象和条件。此阶段不添加自由事实摘要或自由“我”的改写通道。

[inferred] 完整发言/气泡整体选取，保留否定、条件、转述、疑问与角色扮演限定。Bot 台词表示“Bot 对谁说过”，不是对方已经实施的事实。原句没有现实事实资格时标 speech/unverified，不由压缩升级。

[inferred] 校验格式、引用唯一性、来源区间、Bot/会话、原文 digest、旧包有效性和最终预算，再按原 CAS 提交。真实空选择可以依现有空压缩语义推进；格式错误、未知引用和语义包不合法不推进。

[inferred] 同一 guard+区间两次协议失败后，下一次正常触发使用已经读到的原文构造确定性完整记录包；仍验证预算与 CAS。合法降级包是一次成功提交，不能将失败当“无”。最小记录包也放不下则暂停该会话 Compact、记录原因、使用原始尾巴，不无限重试。

[inferred] session_context.py 新增独立 summary_revision，摘要设置、清空、格式失效、重建均递增；同一会话键在 end_session→重建后也不能复用旧 revision（进程内保留单调计数或显式清对应缓存）。compact_count 继续只统计成功压缩，CAS triple 不变。pre_processors.py 以 summary_revision 和明确 packet format/validity 构建缓存键并验证读取，不仅在写入检查。

[inferred] 正常重启清除进程内旧自由摘要，不做“摘要数据库迁移”。热更新遇旧包时，不把旧文本转换为可信来源；覆盖起点能证明才在现有有界窗口重建，否则原始尾巴降级。不得 reset 到 0 后无界扫全库。

### 6.6 schema 19：来源审核、事实主语与派生 lineage

[inferred] 冻结物理方案：memory_evidence 新增 fact_subject_key TEXT NOT NULL DEFAULT ''、source_digest TEXT NOT NULL DEFAULT ''、verification_status TEXT NOT NULL DEFAULT 'legacy_unverified'、provenance_json TEXT NOT NULL DEFAULT '{}'。verification_status 为 accepted/rejected/unknown/legacy_unverified/superseded；JSON由服务端构造并验证版本，含recording_author_key、fact_object_key、predicate_key、canonical_value、temporal/context qualifiers、polarity、statement_kind、exact_support_span、source_snapshot、assessment_version、created_scope_epoch、superseded_by_evidence_id。owner.subject_key维持原授权语义。

[inferred] 新增 proposed memory_claim_links 表，连接 evidence_id 与 derived entity_type/entity_id/claim_key、projection_slot、projection version、slot digest、active/invalidation 状态，唯一约束防重放；至少覆盖 candidate、promoted memory、atomic fact、profile fact、shared copy、proactive hypothesis。复合JSON实体按最小稳定slot登记，不仅按整行user_profile；胃疼纠正只失效身体状态槽，不清空其他traits。索引 candidate_id、owner+audience+fact_subject+verification_status 与 lineage 查询键；表与字段由新增 migrate_v19 注册，fresh DDL、required-column 校验及旧库回归同步。

[inferred] 同表保留持久claim_state记录：entity_type=claim_state、entity_id=claim_key、projection_slot=eligibility，带owner_key/audience及纠正evidence；对owner+audience+claim_key建立此类型的partial unique index。source-only撤销不置整个claim为superseded；权威claim纠正保存superseded状态及版本。所有写候选/强化/晋升先查该状态，旧source不能靠新candidate ID或重新accepted绕过；后续明确新事实以时间/情境限定形成新claim或经审核新纠正解除，不能由confidence解禁。

[inferred] fact_key/claim_key 使用版本化编码，包含canonical Bot、semantic subject、predicate、canonical value、polarity、必要对象及已知时间/情境限定；未知时间显式 unknown，不猜日期。不同状态/偏好值、同人不同事件不能因同predicate合并。FACT/EVENT不作为claim身份，但同源两类型须经审核确认为同claim才共用撤销集合；不能靠自由文本归一化猜等价。legacy keys不批量重算，必须manifest审核。证据唯一约束继续防同源重放计occurrence；复用candidate lineage，不能插第二候选规避唯一键。

[inferred] _consolidate_group_core 中 stage1 的 profile/candidate 都先成为提案。写入前实施来源完整性检查及语义支持审核：

1. source IDs 必须是本批注册来源精确子集；检查 Bot、conversation、作者、source kind、digest。跨群同 ID、不存在 ID、Bot 台词都不能成为某用户本人自述。
2. 使用现有 extraction 的语义审核阶段返回 accepted/rejected/unknown，必须提供原句中可校验 exact supporting span、主体、predicate、polarity、statement_kind。来源存在仅证明发言，不证明现实含义。
3. 支持的 self_report/明确否定偏好可 accepted；枚举、第三人转述、假设、疑问、角色扮演先保存相应状态，不能转成本人肯定事实。不能可靠消解主体或审核失败则 unknown；高 confidence 无效。
4. stage2 截断/超时/fallback 只能保留隔离提案，不能 accepted 或写正式画像。重试有限并记录成本；聊天链不加 verifier。
5. SPACE 和 PERSON 都写精确 source evidence；修正 PERSON 当前“本批该 UID 全部 direct 行”行为。画像只由 accepted 本人证据投影；每个投影登记 claim_links。

[inferred] 所有insert/update/reinforce/profile-write在同一提交事务核捕获epoch、exact source subset及当前源author/conversation/kind/content digest；模型审核在锁外，锁内无新await。源被改/删或CAS失败不推进该来源的成功checkpoint。证据支持不能只比较旧evidence中的自存digest。

[inferred] 晋升、短期事实呈现和主动资格先看 accepted 的支持/主体/状态及 lineage active，再看 confidence/occurrence。非 accepted 可作为明确未证实背景按原受众呈现，但不得冒充 verified、进入本人画像或主动追问。

[inferred] Python _decide_promotion、_process_new_candidates_rust 与 native promote_inner 共同执行 gate。PromotionRequest API3 新增cas_schema_version、expected_scope_versions、expected_evidence_digest、expected_candidate_digest；native Immediate事务重新读取证据/候选/当前原源或可信snapshot/持久epoch，CAS成功才写。缺字段、空摘要、未知版本必须拒绝，不能默认空集合跳过。相似/冲突合并按完整claim保持lineage，不按recording user合并不同人。scope bumps与写入同事务。

[inferred] proposed CAS字节合同v1：SHA256，域前缀stella-cas-v1及对象类型；预定义顺序的typed字段，用UTF8字段名、类型tag、8字节大端长度和payload逐字段编码。字符串保留UTF8原字节、null与空串不同；整数有符号64位大端、bool为0/1、finite gate float用IEEE754 binary64大端并规范化负零，禁止NaN/Inf；source/epoch记录按canonical ID的UTF8字节排序。source_digest覆盖Bot/conversation/local+platform ID/author/recipient/reply/kind/原文；evidence_digest覆盖有序evidence IDs、owner/audience/semantic subject、source identity、审核状态/版本、lineage active、source_digest；candidate_digest覆盖ID、claim、content、status及全部gate输入。Python/Rust共用字段规范和golden byte/digest vectors，不用dict/serde JSON顺序；格式处理后的DeliveryPlan也用明确版本/域及同类编码覆盖目标、版本图和每段文本。可信snapshot须有完整来源字段、固定bytes与不可变digest，缺任一则unknown。

[inferred] schema 19/API3 Python、native selector、native schema、测试 SQL 和发布构建一起改；旧 .pyd 明确失败或走已合格 Python 路径，不允许静默使用 API2。这是本计划的合同升级，不是已实现状态。

### 6.7 合法主动追问与精确纠正

[inferred] pick_target 与 _build_proactive_contract 改为 evidence/candidate exact binding，target==fact_subject；PERSON必须授权允许。SPACE要求audience=CURRENT_SPACE且当前access scope可读，subject匹配既有当前群活跃/可@目标池，Bot/目标会话正确，candidate/evidence/lineage active，source及predicate满足时效；目标池外不因accepted就@。source群与当前群不同仅在已有shared-space权限允许时可用，不隐式扩跨群授权。保留正确群共享候选主动能力。

[inferred] source 查询按candidate_id、claim、owner/audience、source conversation/Bot、fact subject、digest，不能owner+fact_key任取五行。主动合同必须可读取exact original source rows；源已清理则source_missing，即使可信snapshot可检索也不能替代主动资格。contract存evidence IDs、候选版本和epochs；await后核accepted、lineage、权限、时效与版本。subject unknown、legacy、Bot台词、转述枚举不选验证目标。

[inferred] 初期 predicate 白名单使用已有合法确认模板，语气为待确认假设，不能写“你之前说过”。模板需能由服务端读取 claim 和真实主体确定；未支持的 predicate 保持背景。shadow 也持久记录“不合格/为什么”，不能静默绕过。通过合法 SPACE 正例后才打开主动合同 enforce。

[inferred] 纠正先解析目标，再按canonical Bot+owner+audience+semantic subject+完整claim产生invalidation；新纠正来源单独保留。manifest声明invalidation_kind=source|claim：source撤回仅重评剩余accepted支持；主体可靠纠正整个claim则superseded相关支持并记录claim失效，旧source重放不得再晋升。沿claim_links处理candidate/memory/atomic/profile/shared/proactive；多来源派生不能因一source无条件删除。保留speech/history，不把事实纠正当删除“谁说过”。禁止同source全清、相似文本全局撤销或改别人的身份；目标不唯一则澄清不写身份。

[inferred] 生成前捕获 scope epochs，事务提交/最终发送前核验。created_scope_epoch 用于审计与并发检查，不要求全部旧 accepted evidence 永远等于最新 owner epoch；无关写入不应使所有旧事实失效。

### 6.8 旧污染数据与修复工具

[inferred] tools/data_repair.py 复用 preview/apply/revoke 的逐列 expected_old、digest CAS、单事务，增加 proposed provenance_quarantine、lineage_invalidate、source_binding_repair。manifest 保存完整 old/new、来源身份、digest、审核版本、lineage、affected cache keys 和 scope epochs；批次 hard failure 全回滚。

[inferred] apply、duplicate/orphan修复及revoke全部同事务对实际owner/space/global retrieval版本key执行scope_versions.bump(conn=conn, strict=True)。一个logical claim repair的所有来源、派生及审计副作用先全组CAS，再整体写入/撤销；任一关键成员漂移则整组拒绝，禁止仅恢复兄弟行。本计划默认批次hardfailure全回滚；如提供显式分组模式须报applied/skipped groups。scope计数是补偿事务的新递增，不能恢复旧counter。revoke不只UPDATE原行。

[inferred] v18 存量 evidence 迁移为 legacy_unverified；没有正式 evidence 的旧 SPACE 也明确视为未证实。保留数据和原受众。有原消息或可信冻结 snapshot 才重核 accepted；原source已清理、仅snapshot重新认证的旧事实可依受众检索，但没有可核原source的主动合同则不允许主动验证。无证据取消主动资格、保留背景。不根据 CONFIRMED/user_id 自动认证。

[inferred] 执行第一批 preview 精确覆盖：胃疼 source42757 的错误 FACT/EVENT 同 claim 及衍生画像；小说旧候选和纠正；两处 wrong source（45448/45348、48647/48602）；SPACE 错误 verified 投影。不能仅凭近似文字把 wrong source 改成猜测的新 ID。

[inferred] 流程：SQLite 一致备份（包含 WAL 一致性）→副本迁移→preview→用户 review manifest→副本 apply→暖/冷检索→revoke→reapply→生产按已审核 manifest 应用→即时复核。用户执行生产修复；本计划不自动改库。原始 source 留存不足时保留 quarantine，不伪造复原。

## 7. Implementation Sequence

[inferred] 每个阶段单独交付和记录退出证据。表中顺序是集成顺序；P3 与 P4 可在各自测试分支并行，但合入前遵守版本依赖。不得越过硬门槛扩围。

| 阶段 | 操作及交付物 | 退出条件 | 失败支路 |
|---|---|---|---|
| P0 冻结 | 核本计划 provenance/HEAD/dirty；新隔离分支；冻结运行模型、量化、人格、参数、Bot、DB一致副本和五现场 fixture；记录当前基线 | 源/配置/模型/prompt/数据 hash 可追踪；确认有效 Python/native 入口；记录验收成本和测试范围 | drift 只重核变动引用，不重做全仓调查；来源不足列 unknown |
| P1 交付边界 | DeliveryPlan、suppressed 无占位、四发送入口最终 seal、trusted fallback、durable decision/receipt digests | 实际群私入口与主动入口测试通过；sealed 变更被拒；ack/unknown 与历史一致 | 未封存发送必须拒绝；保留受限退路 |
| P2 单一协议 | 新parser/typed slots/AttributionRiskContext、v6 projection、保留集、legacy；完整post-hook assembly | 双输出冲突、typed作者篡改、风险producer→route→模板、版本race、DIRECT/SILENT/error通过；自由改写单列P6，正常一次调用 | 不遵循则受限兼容/澄清，不打开全量enforce |
| P3 摘要 | extractive packet、读取/写入验证、summary_revision、有限降级与水位不变 | 真实 Compact 输出可追溯；失败不推进；reset/同计数缓存失效；预算完整 | packet失败尾巴降级；最小包过大暂停该会话 |
| P4 证据及后端 | schema19/API3迁移、mandatory抽取审核、profile gate、claim links、Python/Rust事务CAS/主体隔离 | v18→19/重复迁移/旧native拒绝/两后端同输入同gate；高confidence无法越gate | 迁移失败回滚；native未通过只用已通过Python路径并披露 |
| P5 主动及修复 | 合法SPACE正例、exact contract、纠正lineage、apply/revoke持久版本、旧数据preview | 纠正race不回潮；同源独立claim不误撤；副本暖/冷/revoke/reapply闭环 | 目标未定澄清；CAS冲突重preview；缺来源quarantine |
| P6 模型验收 | 评估器生产同源、26×10、固定oracle、四变体消融、实际Compact另计、artifact审阅 | §8全部硬门槛通过，无未复核null | 修对应合同；模型约束能力不足则NOT READY，单独比较prompt/模型，不归咎量化 |
| P7 QQ 灰度 | G1/G2/G3；实际配置deadline/enforce与scope；生产修复manifest复核 | 各阶段消息/guard/final/receipt/入库证据闭合，稳定48h且样本达标 | 立即停止扩围/暂停不确定主动；保留safe guard，回到最近通过范围 |

[inferred] P0 的基线可通过旧代码输出留存，测试群正常语料只做受控验证；已知错误台词不因“shadow对照”再次发给真实用户。P1/P2 shadow 比较保存未采用结果；实际已判定危险的台词继续安全路由。

[verified] 当前本机可用 Python C:\Python314、pytest9.1.1、ruff0.16.4；项目 .venv 不存在。发布 native 需按仓库发布环境构建，release.yml:545–554 使用 maturin 与 Python3.12。不能在执行时把本机3.14测试通过当发布3.12 wheel通过。

[inferred] 每次符号编辑前重新 impact，UNKNOWN 用源/注册补证，HIGH/CRITICAL 明确记录；提交前 detect_changes --scope all 完整检查。图 partial/truncated 必须补查，不以零结果放行。计划 provenance 变化时保存差异并重锚。

## 8. Test Strategy

### 8.1 代码与生产装配

[verified] 既有 pytest/CI 参数与文件均已定位；本轮没有运行这些测试，以下是执行者命令。新增 meaningful 输入→操作→结果断言，不能只查提示词字符串或 mock helper 返回。

| 组 | 既有扩展入口 | 必须增加的场景 |
|---|---|---|
| Reply/交付 | test_attribution_wiring、test_dialogue_attribution_repair、runtime/test_turn_service、runtime/test_facade_turns、test_runtime_contract、test_social_delivery、observability/test_message_flow_runtime | single protocol；合法ref+作者倒置；完整guard装配；suppressed实际入口；后seal篡改；分段stale/partial/unknown；DIRECT/SILENT/timeout；持久digest一致 |
| 证据与预算 | test_short_term_attribution、test_context_budget、test_conversation_projection、runtime/test_ingress_native、runtime/test_proactive_native | Bot真实台词正例；裁掉ref拒绝；metadata预算；same-name/stableID；native与Python实际入口 |
| Compact | test_session_compact、test_session_context、test_session_context_cache、test_context_tail、test_usage_accounting | 全作者/对象/否定/条件；未知ID；空 vs非法；二次失败后合法降级；minpacket过大暂停；CAS await race；原始count/开区间/水位；旧格式与reset缓存失效 |
| Memory/主动 | test_candidate_reinforcement、test_proactive_target、test_proactive_at_flow、test_proactive_prompt、observability/test_memory_flow_lifecycle、observability/test_proactive_flow_lifecycle | 枚举/转述/疑问/角色扮演；crossgroup/crossBot source；exact subset；stage2失败高confidence；profile同gate；合法SPACE主动；target和source会话一致 |
| 迁移/隔离/修复 | test_migrations、test_retrieval_v2_and_schema、test_access_semantics、test_personal_memory_sharing、test_personal_memory_backfill、test_memory_rust_promotion、test_memory_rust_selector | schema18→19幂等和失败回滚；API2拒绝；Python/native一致；纠正lineage与promotion race；同source多claim不误清；副本manifest列级apply/revoke；暖缓存跨进程epochs |

[inferred] runtime/test_turn_service.py:40–48 目前只装 parse/filter/split，必须新增生产完整 post-hook assembly；旧 golden 的协议变化人工审阅后更新。test_dialogue_attribution_repair 中已有 apply/revoke 成功不代表共享副本与暖缓存已闭合，必须新增端到端副本断言。

~~~powershell
python -m pytest tests/test_attribution_wiring.py tests/test_dialogue_attribution_repair.py tests/runtime/test_turn_service.py tests/runtime/test_facade_turns.py tests/test_runtime_contract.py tests/test_social_delivery.py tests/observability/test_message_flow_runtime.py -q
python -m pytest tests/test_session_compact.py tests/test_session_context.py tests/test_session_context_cache.py tests/test_context_tail.py tests/test_conversation_projection.py tests/test_context_budget.py tests/test_usage_accounting.py -q
python -m pytest tests/test_candidate_reinforcement.py tests/test_short_term_attribution.py tests/test_proactive_target.py tests/test_proactive_at_flow.py tests/test_proactive_prompt.py tests/test_memory_rust_promotion.py tests/test_memory_rust_selector.py -q
python -m pytest tests/test_migrations.py tests/test_retrieval_v2_and_schema.py tests/test_access_semantics.py tests/test_personal_memory_sharing.py tests/test_personal_memory_backfill.py tests/runtime/test_ingress_native.py tests/runtime/test_proactive_native.py tests/observability/test_memory_flow_lifecycle.py tests/observability/test_proactive_flow_lifecycle.py -q
python -m pytest tests/ -v --cov=. --cov-branch --cov-report=xml -n auto --dist loadgroup --timeout=120 --timeout-method=thread
python -m ruff check core/context.py core/dialogue_attribution.py core/runtime/turn_service.py core/runtime/facade.py core/social/delivery.py memory tools/data_repair.py scripts/evaluate_dialogue_attribution.py stella_project/plugins/bot_main/ai_gateway.py memory_rust
cargo test --manifest-path memory_rust/native/Cargo.toml
~~~

[verified] pytest全量与manifest路径来自 CI/Cargo 文件，本机 cargo 1.97.1 已核版本；Rust发布工具链、链接环境与native wheel构建本轮未运行，执行前按发布 toolchain 建立环境。不能将仅FakeRustBackend通过当native已验收。必要native wheel按发布脚本在3.12构建、导入并核API3/schema19，之后重复真实backend用例。

### 8.2 修补评估器后跑真实模型

[verified] evaluate_dialogue_attribution.py 现有缺口：:228–306 是部分 prompt构造；:253–257 手写摘要；:291 budget用空system；:362–379 guard仅人类证据；:430–440 protocol在预算后追加；:473 oracle路径与 matrix/n08_post_compaction.json:17–27 顶层oracle不一致；:485–486 manual字段为空。

[inferred] 评估器保留现有 CLI，新增 **proposed** production-path/batch模式，调用生产prepare/finalize/Compact/候选gate/DeliveryPlan。批处理参数在实现后写入帮助和验收文档，本计划不把未实现flag当现有命令。oracle按 fixture.oracle→evaluation.oracle→failing_round.oracle 明确优先级，缺失/冲突报错；人工未复核null不能计通过。

[inferred] 冻结模型文件/hash、实际有效端点/model ID、量化、人格hash、温度/top_p/seed/输出限额、上下文预算和后端版本。使用冻结snapshot或副本，不读取不断变化的live DB拼历史。预算包含真实system、protocol、摘要metadata、证据与当前输入。分别留 raw/parsed/guard/render/final/receipt 或模拟receipt，不用同一输出重复计样本。

| # | 26类主验收场景 | 关键断言 |
|---|---|---|
| 01 | recurrence_190922 冻手 | Bot作者、动作双方、条件未来 |
| 02 | A/B轮流发言 | 不继承对方称呼/事实 |
| 03 | 同话题接话无reply | 当前对象独立 |
| 04 | 第三人纠正无明确目标 | 不改无关人身份 |
| 05 | 改名立即问身份 | 本人可靠新声明 |
| 06 | 两人同名 | stable IDs隔离 |
| 07 | 长背景含他人事实 | 完成当前任务且不套人 |
| 08 | 多人同样摸摸动作 | 各次作者/收件人 |
| 09 | 冲突身份声明 | 第三人不覆盖本人 |
| 10 | 帮别人修电脑 | 施事/受事不倒置 |
| 11 | 条件未来玩笑 | 不升级为已发生 |
| 12 | 多人否认看过影片 | 否定保持 |
| 13 | 第三人转述 | 发言者与事实主体分开 |
| 14 | 多人相同现实状态 | 同时保留多个主体 |
| 15 | 多气泡预算裁剪 | 整单元，不留孤立对象 |
| 16 | 实际Compact后接续露营计划 | 真模型选包后续聊 |
| 17 | 本轮胃疼现场 | 枚举不归发送者；纠正同claim |
| 18 | 本轮司书现场 | 栗子/Ain与澄清保持 |
| 19 | 本轮“怪怪的” | 人类原句不称Bot原话 |
| 20 | 本轮小说纠正 | 当前自述不称Bot先说 |
| 21 | 本轮读书问答 | Bot提问/用户阅读 |
| 22 | 普通问候晚安 | 正常闲聊可用 |
| 23 | 修改签名任务 | 当前任务完成 |
| 24 | 人格第一人称表达 | 不误禁“我” |
| 25 | 已同意玩笑互动 | 自然接梗，条件对象保持 |
| 26 | 问Bot真实说过的话 | Bot证据可合法引用 |

[inferred] 主验收每类10次，共260独立回复；Compact真实模型调用另计。21:01污染摘要作为#19消融输入，不多算独立现场。HTTP失败和未复核样本保留，不用额外成功替换。旧16×5=80仅冒烟。

[inferred] 比較四变体：A当前基线、B仅回复交付修复、C全部修复、D全部修复移除摘要。同模型/人格/解码参数。完整四矩阵为1040回复调用加Compact；默认成本方案为C完整260，A/B/D各跑#16–21六类×10，共180，合计 **440回复调用+Compact**。同一批C主样本不重复计数。若端点额度不足，保存中断批次继续，不缩门槛后称完成。

[inferred] 硬门槛：

- C最终作者/对象/动作/事实状态/跨人错误 **0/260**；五新现场错误历史断言 **0/50**。
- 每类任务完成至少9/10，合计至少234/260；正常#22–26至少48/50、错误阻断最多1/50。明确必要澄清可算该场景任务，通用回避不能算。
- 新协议正确生成至少258/260；其余有持久决策和安全结果。单次主模型调用保持；所有样本人工oracle复核完成。
- 分开统计raw错误、guard漏过、最终错误、deterministic fallback、task failure和未送达，不以“hook succeeded”替代。
- 预算保护区超限为0；预处理p95增量≤20ms、回复p95≤同条件基线1.15倍、Compact p95≤1.25倍。这是 proposed初始性能门槛；先固定同缓存/参数基线，调整阈值须记录原因而不能掩盖第二次调用。

[verified] 以下现有 CLI 参数已查 argparse；它仅是重放入口的示范，评估器修补前不能作为全链验收：

~~~powershell
python scripts/evaluate_dialogue_attribution.py --fixture tests/fixtures/dialogue_attribution/recurrence_190922.json --variant V2 --repeats 10 --endpoint $attributionEndpoint --model $attributionModel --system-prompt-file $attributionPersona --temperature $attributionTemperature --max-tokens $attributionMaxTokens --guard --dry-run --output $attributionReport
~~~

[inferred] 从冻结有效配置填写变量；移除 --dry-run 才真实调用。26类新 fixture和批跑由P6新增，不重写旧历史样本。provider无法稳定遵守新协议时，先检查prompt/受限schema能力（能力须实证），再单独比较模型；未达门槛保持NOT READY。

### 8.3 真 QQ 灰度

| 阶段 | 最低范围与证据 | gate与失败处理 |
|---|---|---|
| G1 测试群+私聊 | shadow对照至少100轮，包含五现场、完整证据、纠正和真实Compact；危险结果不实际放行 | raw→decision→final→receipt→入库闭合；错误回对应P阶段 |
| G2 同范围enforce | 至少100轮；五现场各≥3次；≥3个真实Compact周期；await期间纠正/reset；有效native与Python路径分别记录 | 错发送/错入库/contract漏过即停止扩围 |
| G3 目标群和必要私聊 | 至少48小时且≥200轮；正常对照、兜底率、延迟、数据修复和缓存抽查 | 全部通过才生产接受；失败回已通过范围，暂停不确定主动，保持safe guard |

[inferred] 灰度输出包含运行版本、配置生效记录、协议deadline、model/persona hash、source IDs、source snapshot/digest、guard/finalplan/receipt、ack文本与数据库行。仅测试发得出去或时间满48h不算通过；接口、pipeline和实际生效入口必须证实。

## 9. Risk and Impact Analysis

[graph] **CRITICAL apply_summary、HIGH compact_once/_write_memory_candidates/_process_new_candidates_rust** 是本计划主要风险。执行时再次 impact；未做本轮impact的schema/repair/native/格式节点逐一补impact，不把已查四中心当全任务覆盖。

[inferred] 全部 d1 的适配/验证清单如下，不遗漏测试caller：

| 目标 | 全部d1 | 联动处理 |
|---|---|---|
| apply_attribution_guard | attribution_guard_hook、evaluate._guard_stage | 生产/评估同parser/render/seal |
| finalize_turn | RuntimeFacade.submit_turn、TurnService.run | 全分支与legacy run相同合同 |
| compact_once | schedule_compact._run；test_compact_applies_summary、test_compact_discards_stale_result_on_identity_revision、test_compact_discards_stale_result_on_reset、test_compact_noop_without_pending_range、test_compact_respects_token_threshold、test_compact_retries_after_llm_failure、test_compact_skip_also_blocked_by_guard、test_compact_skips_when_model_says_none、test_guard_recovers_next_round；usage.test_compact_skip_returns_false_without_calling_llm | scheduler互斥/有界重试；上述既有边界逐一保留 |
| apply_summary | compact_once；context_tail.test_session_summary_precedes_tail；session_compact.test_compact_skips_when_model_says_none；session_context.test_apply_summary_advances_position、test_empty_summary_does_not_advance、test_end_session_reports_only_real_sessions、test_position_never_goes_backwards、test_sessions_are_per_group、test_skip_range_advances_keeps_summary、test_skip_range_does_not_bump_compact_count；cache.test_session_summary_version_invalidates_cache | 水位与计数兼容；新增revision区别内容失效 |
| _write_memory_candidates | _consolidate_group_core | profile、insert/update/reinforce同审核 |
| _process_new_candidates_rust | process_new_candidates | API3请求、CAS与Python gate一致 |
| build_attribution_evidence | _build_user_context_v2 | 来源语义状态与保留集，不伪verified |
| pick_target / _build_proactive_contract | _proactive_at_user | 合法SPACE正例、contract变体seal之后发 |
| attribution_guard_hook | UNKNOWN，无已解析d1 | 动态register_post_hook/_run_post_hooks完整装配验证 |

[inferred] 其余风险与回退：

- 新协议使当前模型遵循率下降：兼容期有限，任务完成率 gate；不能长期双输出或全轮模板冒充成功。
- 自由文本语义仍有风险：只承诺代码可验证边界；正常语义由260样本与灰度衡量，词法检测漏检必须纳入变形回放。
- Extractive packet增加token：全metadata实际预算与原子裁剪，失败尾巴降级；原文保留更可靠不等于上下文容量无限。
- 新fact_key/lineage使合并更严格：同文不同人不合并，旧键manifest重核，相关similarity/atomic/profile/shared projections不留绕路。
- schema19/API3不兼容旧native：原生wheel与Python同时发布；selector显式拒绝不匹配。回退用兼容schema19的安全代码，或在停写并核对新增数据后恢复一致备份；不能把v19库交给v18 native或强行改schema_meta。
- 纠正race/多段partial：每个事务/交付检查捕获版本；部分已经送达如实记录，中止未发段，不重发unknown。
- repair/revoke遗漏副作用：claim_links+全old/new审计，副本冷暖与撤销验收；CAS冲突整批回滚后重preview。
- 只greenunit未真实接入：P6/P7保持独立NOT READY，真实model/QQ/发布native未通过不能写“问题已修复”。

[inferred] 可回退到已通过的受限聊天范围、暂停不确定主动/新事实写入，保留纠正模板和证据隔离。回退不是将guard=off或shadow恢复已知错误放行。已有合法记忆和正常当前轮任务继续按授权服务。

## 10. Files Expected to Change

[inferred] 以下为预计编辑路径，具体符号编辑前重新impact。新增实体明确标 proposed。

| 文件/模块 | 修改目的 |
|---|---|
| core/context.py、core/dialogue_attribution.py | v6 projection、proposed typed envelope/DeliveryPlan、统一parser、risk/render、证据语义状态 |
| core/runtime/turn_service.py、core/runtime/facade.py | DeliveryDraft、明确producer来源、direct/fallback全分支、持久guard decision；最终seal由发送入口共用helper |
| memory/post_processors.py、memory/pre_processors.py | 唯一台词、原子format、预算保留、真实source/subject、packet读取与revision缓存 |
| stella_project/plugins/bot_main/ai_gateway.py、core/social/delivery.py | 四发送入口、suppressed、proactive override及合并完成后seal、plan/receipt一致 |
| core/observability/message_flow.py | 仅在既有decision/receipt接口无法承载时做最小字段适配；先复用metrics，不重构Dashboard |
| memory/session_compact.py、memory/session_context.py | proposed SummaryPacket、选refs、验证、有限降级、summary_revision |
| memory/consolidator.py、memory/memory_manager.py | mandatory来源/语义审核、profile gate、lineage、promotion/CAS |
| memory/schema.py、memory/migrations.py | proposed v19 evidence字段、claim_links、migrate_v19、校验 |
| memory/proactive_target.py、memory/proactive_contract.py | 主体/来源/资格、合法SPACE、epochs及predicate模板 |
| memory/scope_versions.py、tools/data_repair.py | 持久版本严格事务、manifest、claim修复及revoke全副作用 |
| memory/retrieval_v2.py | 如现有返回结构未提供新provenance，最小投影补充；owner/audience查询边界不扩大 |
| memory_rust/backend.py、memory_rust/selector.py、native/src/schema.rs、native/src/promotion.rs | API3/schema19、证据/候选/epoch CAS、native transaction gate |
| memory_rust/native/src/lib.rs、native/src/retrieval.rs | 导出/测试schema常量与返回投影按需要联动；旧schema测试SQL更新，不重构retrieval算法 |
| scripts/evaluate_dialogue_attribution.py、§8既有测试 | 生产同源评估、oracle、真实Compact、全入口与后端验收 |
| tests/fixtures/dialogue_attribution/recurrence_20261008_*.json | proposed五新现场fixture及正常对照；完整raw/expected身份与来源 |

[inferred] 新类型可以放相应现有模块；若拆独立文件须注册导入并做impact。ownership.py用于验证不变约束，未计划放宽SPACE owner.subject_key。版本合同影响发布文档/构建断言时按实际搜到的位置小范围更新，先graph/source，不能全仓盲改18/2。

## 11. Reusable Implementation Context

下列 JSON 为执行入口；evidence_provenance 是官方 portable helper 的原样输出，含固定 HEAD、全局 dirty digest 与所有引用路径的层级摘要，不包含全仓 dirty manifest。执行者复算匹配后直接从P0开始，无需重做整个调查。

~~~json
{
  "implementation_context": {
    "task_summary": "按P0–P7修复Stella对话作者/对象/事实主体混淆，统一ReplyEnvelope与最终DeliveryPlan，替换自由压缩，建立来源与lineage gate，完成旧数据、模型和QQ验收。只执行计划所列改动，不重复全仓调查。",
    "acceptance_criteria": [
      "finalize产出DeliveryDraft，四发送入口override/合并后统一seal；suppressed零发送；guard/final/receipt一致，BOT_SELF/学习仅ack",
      "高风险纠正服务端受限渲染；普通聊天一次主模型调用；引用只来自预算保留且有效的证据",
      "SummaryPacket服务端回填原文/作者/对象；非法输出不推进水位；CAS/count保持，summary_revision驱动缓存失效",
      "schema19/API3；Python与实际native均在事务中重核accepted evidence、candidate digest与scope epoch",
      "SPACE owner subject仍为空，语义fact_subject独立；合法群候选主动正例通过；unknown/legacy不主动",
      "精确claim撤销所有可证派生，apply/revoke事务CAS与持久scope bump通过暖/冷检索",
      "26类×10主样本最终归属错误0/260，任务每类≥9/10，正常对照≥48/50，协议≥258/260；全样本复核",
      "G1≥100、G2≥100且≥3Compact周期、G3≥48h且≥200轮，模型/QQ/入库证据完整"
    ],
    "evidence_provenance": {
      "schema_version": 2,
      "head_commit": "827ed665c9d6316c5871b3e967719473f61b6755",
      "generated_plan_path": "docs/plans/2026-10-08-gitnexus-plan-dialogue-attribution-delivery-repair.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "d5197ed24b5c48bb9e7079efcaf9c215fae340b0d4b30d33307b84f554035f89"
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
          "path": ".github/workflows/release.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:8a96875d6a955f449a221a2d0b179427632d706b004b7e2f9f4b96cfff885dd8",
          "index_digest": "sha256:8a96875d6a955f449a221a2d0b179427632d706b004b7e2f9f4b96cfff885dd8",
          "worktree_digest": "sha256:1fd63c9a6ded3c44f0effb1af39a6e91900000a8c1c799adfffb24f681a9d8f1",
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
          "head_digest": "sha256:28769365318042fc6608dd87505e2b3d36b4f3d05b120b63b75ab26443983cd4",
          "index_digest": "sha256:28769365318042fc6608dd87505e2b3d36b4f3d05b120b63b75ab26443983cd4",
          "worktree_digest": "sha256:87bed0bbc17920ec07482e43660434c1b1088f01fa2bed03971aaaa192b41977",
          "untracked_digest": "absent"
        },
        {
          "path": "core/dialogue_attribution.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:def6f602608878a198925a5646a065ebb83ecaf45237b3e1f60ceae4bec3459d",
          "index_digest": "sha256:def6f602608878a198925a5646a065ebb83ecaf45237b3e1f60ceae4bec3459d",
          "worktree_digest": "sha256:a33f29f8998aa42cb08bc5b1529c527ee89d2471568bc8563ab6d2b6efb90df4",
          "untracked_digest": "absent"
        },
        {
          "path": "core/observability/message_flow.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2de108c6ffc56c7664abb60770a407b2129eb9e124b9f9e427e8b882e9c8149f",
          "index_digest": "sha256:2de108c6ffc56c7664abb60770a407b2129eb9e124b9f9e427e8b882e9c8149f",
          "worktree_digest": "sha256:2de108c6ffc56c7664abb60770a407b2129eb9e124b9f9e427e8b882e9c8149f",
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
          "head_digest": "sha256:c5ad69ad7b92f1d94db1773d2429d1da5e5cf8a26e2ef4c744b25c8b4c27b5f6",
          "index_digest": "sha256:c5ad69ad7b92f1d94db1773d2429d1da5e5cf8a26e2ef4c744b25c8b4c27b5f6",
          "worktree_digest": "sha256:c5ad69ad7b92f1d94db1773d2429d1da5e5cf8a26e2ef4c744b25c8b4c27b5f6",
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
          "head_digest": "sha256:eca4832df7176eee853b30c181ff8f4a05d5e3095e2137bf1a43a90b53258b10",
          "index_digest": "sha256:eca4832df7176eee853b30c181ff8f4a05d5e3095e2137bf1a43a90b53258b10",
          "worktree_digest": "sha256:eca4832df7176eee853b30c181ff8f4a05d5e3095e2137bf1a43a90b53258b10",
          "untracked_digest": "absent"
        },
        {
          "path": "docs/reports/2026-10-08-dialogue-attribution-recurrence-root-cause.md",
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
          "untracked_digest": "sha256:ec21b34daad4f985a8abc1156850e9a7bf39fb7c91c1187ab66ce5cabdaefd21"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261008/case-snapshot.json",
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
          "untracked_digest": "sha256:88c837f4e4f1e4131dd4021a3336ec06ac26ad82f9059f49452d8b49aea65dc0"
        },
        {
          "path": "docs/reports/evidence/dialogue-attribution-20261008/guard-probe.json",
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
          "untracked_digest": "sha256:9b14a9b342832741520d1fabef65a80b4e9a4bfba45978f38e890f2688d816db"
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
          "head_digest": "sha256:acd6ee8a35dc4764fe9e32aeee05c7e8161e45ef7eb90a257264e7533d30d031",
          "index_digest": "sha256:acd6ee8a35dc4764fe9e32aeee05c7e8161e45ef7eb90a257264e7533d30d031",
          "worktree_digest": "sha256:acd6ee8a35dc4764fe9e32aeee05c7e8161e45ef7eb90a257264e7533d30d031",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/memory_manager.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:709fc1dc1c3285d8eb606b260f68318e7f511ad3d986e38b650418624d1d0cd4",
          "index_digest": "sha256:709fc1dc1c3285d8eb606b260f68318e7f511ad3d986e38b650418624d1d0cd4",
          "worktree_digest": "sha256:9c7beb8222ffb8361b9f7786d6ab46069ae7e75cbfd7d9d2a175ccbc9d6e685e",
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
          "head_digest": "sha256:85879813a683d0b7cdc3651c0e448c2cfcc7e79191bd40815faa956b47a1f6ee",
          "index_digest": "sha256:85879813a683d0b7cdc3651c0e448c2cfcc7e79191bd40815faa956b47a1f6ee",
          "worktree_digest": "sha256:84fa0f7a448a59537b6f38fa7613b7851e8560914ad1951d844a5a1868a5b714",
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
          "head_digest": "sha256:5a37b8c8e7a9b00dc806ce62f22716a01d962197ec80e90d0964bbe729d1cd9a",
          "index_digest": "sha256:5a37b8c8e7a9b00dc806ce62f22716a01d962197ec80e90d0964bbe729d1cd9a",
          "worktree_digest": "sha256:1be2d55ece7a47bc9bcb2315475a68510c3826ec75a02bcd785d20f2c3dee9e3",
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
          "head_digest": "sha256:3adf87aebfaaba5ce528f6d7c029a07ca4ac52aec3a9a2dfb3a33ba869b44e1e",
          "index_digest": "sha256:3adf87aebfaaba5ce528f6d7c029a07ca4ac52aec3a9a2dfb3a33ba869b44e1e",
          "worktree_digest": "sha256:3adf87aebfaaba5ce528f6d7c029a07ca4ac52aec3a9a2dfb3a33ba869b44e1e",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/proactive_contract.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1d38d33f93a2bbca86a2262fa2d7a465328b1c7da2c27e299f48635ab6b816a1",
          "index_digest": "sha256:1d38d33f93a2bbca86a2262fa2d7a465328b1c7da2c27e299f48635ab6b816a1",
          "worktree_digest": "sha256:22cbe411c1449bd754c246666a30d22776cb76796689deededf1f0803e5a747e",
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
          "head_digest": "sha256:8ec09a9b7a7ff03bca858c364de57a9153edca25d3ececa38a04be8c86db25fa",
          "index_digest": "sha256:8ec09a9b7a7ff03bca858c364de57a9153edca25d3ececa38a04be8c86db25fa",
          "worktree_digest": "sha256:af108b29dc593e15e8ac8683c328b9da3a02d0f8accf9077fcb1a602ac7d4f18",
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
          "head_digest": "sha256:483c4de4ee562084d3e6aeae4f591a479e45145e82fd426965e60e7189accff5",
          "index_digest": "sha256:483c4de4ee562084d3e6aeae4f591a479e45145e82fd426965e60e7189accff5",
          "worktree_digest": "sha256:49427d46fea6175c1656e4e9a438257ab1a0da0cd28b7f635ad2b676814b4720",
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
          "head_digest": "sha256:7285c69c93e7349404e9080a90bf4709f534c4d68576936b745f7bf0222f3c89",
          "index_digest": "sha256:7285c69c93e7349404e9080a90bf4709f534c4d68576936b745f7bf0222f3c89",
          "worktree_digest": "sha256:11dc8f758638e28a2cc7f6fe835487afd4b94a9095a4243ea63a4b6727788bf2",
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
          "head_digest": "sha256:e730cade301e8de1610d13fa2d22424eb98e9ffd20a54b7f7d6c36b71f78efc7",
          "index_digest": "sha256:e730cade301e8de1610d13fa2d22424eb98e9ffd20a54b7f7d6c36b71f78efc7",
          "worktree_digest": "sha256:e730cade301e8de1610d13fa2d22424eb98e9ffd20a54b7f7d6c36b71f78efc7",
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
          "path": "memory_rust/native/src/lib.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:39030695b7c31ea448d74ebc31098a3a72480f9afc89d199b7b7077303fa6246",
          "index_digest": "sha256:39030695b7c31ea448d74ebc31098a3a72480f9afc89d199b7b7077303fa6246",
          "worktree_digest": "sha256:6dfdf2ba3b278b6b1b1115ce5e128551d9bc72c0513e8baec9487c7f37a47691",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/native/src/promotion.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e9a465a38c3614e1c36beabdc1dbe9a3e3e7f172472d2f7e4a96e700c515222d",
          "index_digest": "sha256:e9a465a38c3614e1c36beabdc1dbe9a3e3e7f172472d2f7e4a96e700c515222d",
          "worktree_digest": "sha256:e9a465a38c3614e1c36beabdc1dbe9a3e3e7f172472d2f7e4a96e700c515222d",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/native/src/retrieval.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:957179ee555bcd0fc62fac2e94509e5942d1962cb9c821c25aceb15b1605ba93",
          "index_digest": "sha256:957179ee555bcd0fc62fac2e94509e5942d1962cb9c821c25aceb15b1605ba93",
          "worktree_digest": "sha256:957179ee555bcd0fc62fac2e94509e5942d1962cb9c821c25aceb15b1605ba93",
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
          "head_digest": "sha256:c914b3646d0f665dd98e6a8af9b7b3fcbd05d705818de8ff0e51da5eb429c344",
          "index_digest": "sha256:c914b3646d0f665dd98e6a8af9b7b3fcbd05d705818de8ff0e51da5eb429c344",
          "worktree_digest": "sha256:c914b3646d0f665dd98e6a8af9b7b3fcbd05d705818de8ff0e51da5eb429c344",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/selector.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9de15ee47159c4fedf7a74d846b5008a81f7ca9afbd6aabefc8ec5831744e790",
          "index_digest": "sha256:9de15ee47159c4fedf7a74d846b5008a81f7ca9afbd6aabefc8ec5831744e790",
          "worktree_digest": "sha256:255fee1c95a151140ca0afd3e8f15c4a13b9f6abd2e50de3a34b75360f758b98",
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
          "head_digest": "sha256:69e9ec88bcfae276a93a975c1565e555be71562dd19b8d7215d59043546f22fe",
          "index_digest": "sha256:69e9ec88bcfae276a93a975c1565e555be71562dd19b8d7215d59043546f22fe",
          "worktree_digest": "sha256:8b1857a85e5b1c32726d1c6e23b1b49b25fae29658eda6ae056a28c4d66caf97",
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
          "head_digest": "sha256:e18c5ae7e2c8ce32fd5e699f21f18cf0ac57832b82210c23866a336bc9ba9057",
          "index_digest": "sha256:e18c5ae7e2c8ce32fd5e699f21f18cf0ac57832b82210c23866a336bc9ba9057",
          "worktree_digest": "sha256:e18c5ae7e2c8ce32fd5e699f21f18cf0ac57832b82210c23866a336bc9ba9057",
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
          "head_digest": "sha256:1e3302f240bdd39c569380784714cb9a45513c6b62b54c2638163bc1a830c2b9",
          "index_digest": "sha256:1e3302f240bdd39c569380784714cb9a45513c6b62b54c2638163bc1a830c2b9",
          "worktree_digest": "sha256:1e3302f240bdd39c569380784714cb9a45513c6b62b54c2638163bc1a830c2b9",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/fixtures/dialogue_attribution/matrix/n08_post_compaction.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a6208c1bdf5bb22d86eee4cca5bbd9a1ee52ab08e75c3b8d711a1517ee8ef8a8",
          "index_digest": "sha256:a6208c1bdf5bb22d86eee4cca5bbd9a1ee52ab08e75c3b8d711a1517ee8ef8a8",
          "worktree_digest": "sha256:a6208c1bdf5bb22d86eee4cca5bbd9a1ee52ab08e75c3b8d711a1517ee8ef8a8",
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
          "head_digest": "sha256:7ff9136f06b8d92049a0705df9c572fd9bdee73fb8ca568623e59ec8674e757e",
          "index_digest": "sha256:7ff9136f06b8d92049a0705df9c572fd9bdee73fb8ca568623e59ec8674e757e",
          "worktree_digest": "sha256:7ff9136f06b8d92049a0705df9c572fd9bdee73fb8ca568623e59ec8674e757e",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/observability/test_message_flow_runtime.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:6622561ab8d7acf118e6026daa715c40ba451f7a70f4bf30889984b5d5f4ffec",
          "index_digest": "sha256:6622561ab8d7acf118e6026daa715c40ba451f7a70f4bf30889984b5d5f4ffec",
          "worktree_digest": "sha256:27ebfec9e007e1e90a36e9d38464ffd29905d19dd2bf96f8210808587d99e777",
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
          "path": "tests/runtime/test_ingress_native.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:da66698d3db357d368c3f5f962a165fc6b3bf2493bbef367ad038df9bb663c1b",
          "index_digest": "sha256:da66698d3db357d368c3f5f962a165fc6b3bf2493bbef367ad038df9bb663c1b",
          "worktree_digest": "sha256:f0f2392abfe3f40efbedf23fc1942a727f9e812bd0f03a37d458c37adaf7368c",
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
          "head_digest": "sha256:a3f33ac862f9a635a4ef233169c5e6355adbab6d68459d779f733279cb1fedde",
          "index_digest": "sha256:a3f33ac862f9a635a4ef233169c5e6355adbab6d68459d779f733279cb1fedde",
          "worktree_digest": "sha256:a3f33ac862f9a635a4ef233169c5e6355adbab6d68459d779f733279cb1fedde",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_access_semantics.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:319f9eaec5a1ce16581c5d31b5d7a0e0f25c2a82f922f99eae21b802e5b07e19",
          "index_digest": "sha256:319f9eaec5a1ce16581c5d31b5d7a0e0f25c2a82f922f99eae21b802e5b07e19",
          "worktree_digest": "sha256:319f9eaec5a1ce16581c5d31b5d7a0e0f25c2a82f922f99eae21b802e5b07e19",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_attribution_wiring.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:828fb3934fb039d69ad11859ee5d4fa03d8b2360765c74d9ccda371a2c68b97a",
          "index_digest": "sha256:828fb3934fb039d69ad11859ee5d4fa03d8b2360765c74d9ccda371a2c68b97a",
          "worktree_digest": "sha256:828fb3934fb039d69ad11859ee5d4fa03d8b2360765c74d9ccda371a2c68b97a",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_candidate_reinforcement.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:ffafed15a4436aed7c9fc84566d61f78ca04abb5120220da18df9b29e92e7ced",
          "index_digest": "sha256:ffafed15a4436aed7c9fc84566d61f78ca04abb5120220da18df9b29e92e7ced",
          "worktree_digest": "sha256:9f953907b0398814bb2d9437d11fa36ff15b1008f6cb53d59fae6b9b92dc25c4",
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
          "head_digest": "sha256:2f32d75b2a4056e5059dd6611f1d965312c837c4ce8f82e7d72f85e724f2407f",
          "index_digest": "sha256:2f32d75b2a4056e5059dd6611f1d965312c837c4ce8f82e7d72f85e724f2407f",
          "worktree_digest": "sha256:2f32d75b2a4056e5059dd6611f1d965312c837c4ce8f82e7d72f85e724f2407f",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_conversation_projection.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:61afc217aa2ce22f7558818bda4771339bb36539e052774762dc21c065c41723",
          "index_digest": "sha256:61afc217aa2ce22f7558818bda4771339bb36539e052774762dc21c065c41723",
          "worktree_digest": "sha256:61afc217aa2ce22f7558818bda4771339bb36539e052774762dc21c065c41723",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_dialogue_attribution_repair.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:01d2a4ef66e74777a01691ad8574ef4b709861df72e224f673779b16577deb0e",
          "index_digest": "sha256:01d2a4ef66e74777a01691ad8574ef4b709861df72e224f673779b16577deb0e",
          "worktree_digest": "sha256:01d2a4ef66e74777a01691ad8574ef4b709861df72e224f673779b16577deb0e",
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
          "head_digest": "sha256:b8ae9d78adcb89bf271235b1856f9a10782e9895d44ba00ae2634789682e79ab",
          "index_digest": "sha256:b8ae9d78adcb89bf271235b1856f9a10782e9895d44ba00ae2634789682e79ab",
          "worktree_digest": "sha256:b8ae9d78adcb89bf271235b1856f9a10782e9895d44ba00ae2634789682e79ab",
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
          "path": "tests/test_personal_memory_sharing.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c940b7aea778ef722fd9d9c586ed92c512ed88a56664cc28fdaefd51c5b6960e",
          "index_digest": "sha256:c940b7aea778ef722fd9d9c586ed92c512ed88a56664cc28fdaefd51c5b6960e",
          "worktree_digest": "sha256:c940b7aea778ef722fd9d9c586ed92c512ed88a56664cc28fdaefd51c5b6960e",
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
          "path": "tests/test_retrieval_v2_and_schema.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3878855e79db8d22dc6999ccb927c7ea354bd2aacba9b951f6bf3cff8d9d978e",
          "index_digest": "sha256:3878855e79db8d22dc6999ccb927c7ea354bd2aacba9b951f6bf3cff8d9d978e",
          "worktree_digest": "sha256:3878855e79db8d22dc6999ccb927c7ea354bd2aacba9b951f6bf3cff8d9d978e",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_runtime_contract.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2068cea76e3d87b241a3bf0e18e302b108d2ed9586eb6eaef544b0485df922f0",
          "index_digest": "sha256:2068cea76e3d87b241a3bf0e18e302b108d2ed9586eb6eaef544b0485df922f0",
          "worktree_digest": "sha256:eed78f18663880f262fb2b2b46539f4026aef74cccd30c0960b781e734ba696e",
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
          "path": "tests/test_session_context.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c5c77eb943603de3b1d18e319529df6592ea63b85b60992610dc0e23ed25c0d7",
          "index_digest": "sha256:c5c77eb943603de3b1d18e319529df6592ea63b85b60992610dc0e23ed25c0d7",
          "worktree_digest": "sha256:c5c77eb943603de3b1d18e319529df6592ea63b85b60992610dc0e23ed25c0d7",
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
          "path": "tests/test_short_term_attribution.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:421fb2f950bd8712938f3e88d825e4820715730425438494230cdc106e0d97e1",
          "index_digest": "sha256:421fb2f950bd8712938f3e88d825e4820715730425438494230cdc106e0d97e1",
          "worktree_digest": "sha256:7552e3e7411fa16882e2d9a591cb1e7bba648f4ef7c77bf262fd186999e9c177",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_social_delivery.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:cc4ed302de53f9e31e05a646a44af7a5f6c15d9253edf142324ce594963889ec",
          "index_digest": "sha256:cc4ed302de53f9e31e05a646a44af7a5f6c15d9253edf142324ce594963889ec",
          "worktree_digest": "sha256:4bba5356cfd486032f7bb9ea47e682c672d0afd409df1656934b1a2664b29b8d",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_usage_accounting.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:823c499606d08f094fd70150eebb87df43ba41da6d2423e37a7641f1ffd6e046",
          "index_digest": "sha256:823c499606d08f094fd70150eebb87df43ba41da6d2423e37a7641f1ffd6e046",
          "worktree_digest": "sha256:70790d28b1467eaaac0701532761ec8cdf4b569036939ea8c904571bf602a5cb",
          "untracked_digest": "absent"
        },
        {
          "path": "tools/data_repair.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c6ea9293cedde9419ea31ad29acc6e343fe95d7d4ad71499554267c1035880f5",
          "index_digest": "sha256:c6ea9293cedde9419ea31ad29acc6e343fe95d7d4ad71499554267c1035880f5",
          "worktree_digest": "sha256:c6ea9293cedde9419ea31ad29acc6e343fe95d7d4ad71499554267c1035880f5",
          "untracked_digest": "absent"
        }
      ]
    },
    "primary_symbols": [
      {
        "symbol": "apply_attribution_guard",
        "file": "core/dialogue_attribution.py",
        "lines": "622-658",
        "role": "当前guard入口；新single envelope、typed引用及受限渲染"
      },
      {
        "symbol": "compact_once",
        "file": "memory/session_compact.py",
        "lines": "298-381",
        "role": "HIGH；新packet验证、有限降级、CAS提交"
      },
      {
        "symbol": "apply_summary",
        "file": "memory/session_context.py",
        "lines": "148-188",
        "role": "CRITICAL；摘要状态、水位/计数及独立revision"
      },
      {
        "symbol": "MemoryConsolidator._write_memory_candidates",
        "file": "memory/consolidator.py",
        "lines": "1382-1780",
        "role": "HIGH；exact sources、语义资格、SPACE/PERSON evidence与强化"
      },
      {
        "symbol": "MemoryManager._process_new_candidates_rust",
        "file": "memory/memory_manager.py",
        "lines": "378-552",
        "role": "HIGH；API3请求、晋升与native事务重核"
      }
    ],
    "related_symbols": [
      {
        "symbol": "_decide",
        "relationship": "guard内部控制",
        "relevance": "core/dialogue_attribution.py:496-569；PDG证明当前双台词与shadow分支"
      },
      {
        "symbol": "attribution_guard_hook",
        "relationship": "动态register_post_hook",
        "relevance": "ai_gateway.py:679-737；UNKNOWN caller已源码补证，完整装配必测"
      },
      {
        "symbol": "TurnService.finalize_turn",
        "relationship": "CALLS post hooks",
        "relevance": "core/runtime/turn_service.py:644-704；DeliveryDraft与guard decision，发送入口改写后最终seal"
      },
      {
        "symbol": "RuntimeFacade.submit_turn",
        "relationship": "CALLS finalize_turn",
        "relevance": "core/runtime/facade.py:322-426；trusted fallback、DIRECT/SILENT"
      },
      {
        "symbol": "parse_output",
        "relationship": "post hook",
        "relevance": "memory/post_processors.py:27-57；只解析唯一envelope"
      },
      {
        "symbol": "split_lines",
        "relationship": "post hook",
        "relevance": "memory/post_processors.py:67-79；原子段、不静默删作者"
      },
      {
        "symbol": "build_attribution_evidence",
        "relationship": "CALLS from _build_user_context_v2",
        "relevance": "memory/pre_processors.py:969-1087；实际来源/主体/资格与保留集"
      },
      {
        "symbol": "_consolidate_group_core",
        "relationship": "CALLS candidate writer/promotion",
        "relevance": "memory/consolidator.py:805-864；profiles不得先写，stage2失败unknown"
      },
      {
        "symbol": "MemoryManager._decide_promotion",
        "relationship": "CALLS from Python/native orchestration",
        "relevance": "memory/memory_manager.py:821-830；confidence之前审核资格"
      },
      {
        "symbol": "pick_target",
        "relationship": "CALLS from _proactive_at_user",
        "relevance": "memory/proactive_target.py:170-175,302-307；target使用fact_subject"
      },
      {
        "symbol": "_build_proactive_contract",
        "relationship": "CALLS from _proactive_at_user",
        "relevance": "ai_gateway.py:3330-3568；exact candidate/source，合法SPACE"
      },
      {
        "symbol": "promote_inner",
        "relationship": "CALLS from native promote",
        "relevance": "memory_rust/native/src/promotion.rs:436-467,745-767；Immediate事务gate/CAS"
      },
      {
        "symbol": "migrate_v18",
        "relationship": "existing migration pattern",
        "relevance": "memory/migrations.py:882-934；proposed migrate_v19注册/幂等/旧库"
      },
      {
        "symbol": "summary_version/bump_reset_generation",
        "relationship": "cache/state合同",
        "relevance": "memory/session_context.py:104-117,229-235；新增summary_revision"
      },
      {
        "symbol": "preview_repairs/apply_repairs/revoke_batch",
        "relationship": "repair pipeline",
        "relevance": "tools/data_repair.py:421-432,504-574,626-694；列级CAS/审计/缓存联动"
      },
      {
        "symbol": "message_flow.decision",
        "relationship": "observability sink",
        "relevance": "core/observability/message_flow.py:1507-1529；复用接口持久化guard/final"
      }
    ],
    "execution_path": [
      "QQ group/private ingress → trusted canonical conversation/current user/identity revision",
      "prepare/build_context → SummaryPacket + exact accepted/background evidence → full system/protocol budget → retained IDs + AttributionRiskContext",
      "one main provider call → single ReplyEnvelope parse → server risk route/guard → typed or deterministic DeliveryDraft",
      "bad phrase/atomic formatting/proactive variant+merge → final DeliveryPlan seal → durable decision",
      "sender rechecks captured target/epochs/digest before each send starts；in-flight变化不能推未送达 →真实receipt→ack历史",
      "offline extraction proposals → source/span/subject/state assessment → evidence+claim links → profile/candidate",
      "Python/native promotion transaction source+candidate+scope CAS → memory/atomic/shared projection+links+scope bump",
      "correction exact claim invalidation → all linked derivatives+proactive → persistent epoch/cache recheck"
    ],
    "pdg_constraints": [
      {
        "description": "_decide的plan缺失/shadow与current_response分支是当前可绕开边界",
        "affected_statements": [
          "core/dialogue_attribution.py:517",
          "core/dialogue_attribution.py:518",
          "core/dialogue_attribution.py:523",
          "core/dialogue_attribution.py:525",
          "core/dialogue_attribution.py:534",
          "core/dialogue_attribution.py:545"
        ],
        "implementation_consequence": "gate与renderer消费同一typed对象；parse错误不回raw；semantic_unverified与deterministic_render分开"
      },
      {
        "description": "compact result直接流向判空及apply，CAS失败提前退出",
        "affected_statements": [
          "memory/session_compact.py:358",
          "memory/session_compact.py:366",
          "memory/session_compact.py:372",
          "memory/session_compact.py:374",
          "memory/session_compact.py:377",
          "memory/session_compact.py:380"
        ],
        "implementation_consequence": "先packet validation再CAS/apply；invalid非empty；guard与提交之间无新await"
      },
      {
        "description": "sender白名单、PERSON evidence guard与source_ids insert/update不能证明主体",
        "affected_statements": [
          "memory/consolidator.py:1488",
          "memory/consolidator.py:1528",
          "memory/consolidator.py:1576",
          "memory/consolidator.py:1634"
        ],
        "implementation_consequence": "所有SPACE/PERSON、新建/强化分支共用exact source+semantic gate；profiles同门"
      }
    ],
    "architectural_patterns": [
      {
        "pattern": "canonical owner/audience保持授权，语义subject独立",
        "example_location": "memory/ownership.py:63-78",
        "usage_guidance": "SPACE owner.subject_key不填；fact_subject在provenance；不扩大私人访问"
      },
      {
        "pattern": "guard triple与单调水位",
        "example_location": "memory/session_context.py:148-188,251-261",
        "usage_guidance": "保持reset_generation/identity_revision/summarized_up_to_id CAS与原始count"
      },
      {
        "pattern": "版本化幂等迁移及旧库回归",
        "example_location": "memory/migrations.py:882-934; memory/schema.py:1194-1284",
        "usage_guidance": "新增v19、fresh DDL、required columns、旧库测试，失败整级回滚"
      },
      {
        "pattern": "Immediate事务重读及严格schema/API合同",
        "example_location": "memory_rust/native/src/promotion.rs:745-767; memory_rust/selector.py:76-85",
        "usage_guidance": "API3/schema19与CAS同步，旧native不默许"
      },
      {
        "pattern": "部分发送与ack历史边界",
        "example_location": "core/social/delivery.py:109-198,246-329",
        "usage_guidance": "封存计划关联receipt；unknown不重发，失败文本不学习"
      },
      {
        "pattern": "列级expected_old/source digest与持久scope版本",
        "example_location": "tools/data_repair.py:421-432; memory/retrieval_v2.py:609",
        "usage_guidance": "apply/revoke派生副作用纳入审计，同事务bump实际缓存key"
      }
    ],
    "files_to_modify": [
      {
        "file": "core/context.py",
        "symbols": [],
        "intended_change": "v6 projection与proposed risk context/typed reply/DeliveryDraft/DeliveryPlan/evidence字段"
      },
      {
        "file": "core/dialogue_attribution.py",
        "symbols": [
          "apply_attribution_guard",
          "_decide"
        ],
        "intended_change": "single envelope、风险路由、受限render、语义状态"
      },
      {
        "file": "core/runtime/turn_service.py",
        "symbols": [
          "finalize_turn"
        ],
        "intended_change": "DeliveryDraft与durable guard决策装配，最终seal在发送入口"
      },
      {
        "file": "core/runtime/facade.py",
        "symbols": [
          "submit_turn"
        ],
        "intended_change": "DIRECT明确producer来源而非自动verified；SILENT零发送，确定性fallback"
      },
      {
        "file": "memory/post_processors.py",
        "symbols": [
          "parse_output",
          "split_lines"
        ],
        "intended_change": "唯一parsed对象、atomic formatting、无rawfallback"
      },
      {
        "file": "memory/pre_processors.py",
        "symbols": [
          "build_attribution_evidence",
          "build_context"
        ],
        "intended_change": "真实source/subject、retainedIDs与packet/revision cache"
      },
      {
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "symbols": [
          "attribution_guard_hook",
          "_build_proactive_contract"
        ],
        "intended_change": "suppressed无占位、四入口override/合并后统一seal、主动exact合同"
      },
      {
        "file": "core/social/delivery.py",
        "symbols": [],
        "intended_change": "plan和实际段digest/epoch核验，receipt关联"
      },
      {
        "file": "memory/session_compact.py",
        "symbols": [
          "compact_once"
        ],
        "intended_change": "proposed SummaryPacket、refs选择、验证、有限降级"
      },
      {
        "file": "memory/session_context.py",
        "symbols": [
          "apply_summary",
          "summary_version",
          "bump_reset_generation"
        ],
        "intended_change": "独立summary_revision、packet状态，CAS/count保持"
      },
      {
        "file": "memory/consolidator.py",
        "symbols": [
          "_consolidate_group_core",
          "_write_memory_candidates"
        ],
        "intended_change": "来源/语义审核、profile gate、lineage"
      },
      {
        "file": "memory/memory_manager.py",
        "symbols": [
          "_decide_promotion",
          "_process_new_candidates_rust"
        ],
        "intended_change": "accepted门槛、epoch/evidence/candidate CAS"
      },
      {
        "file": "memory/schema.py",
        "symbols": [],
        "intended_change": "schema19 DDL/provenance/claim_links含projection_slot与持久claim_state，required columns"
      },
      {
        "file": "memory/migrations.py",
        "symbols": [],
        "intended_change": "proposed migrate_v19注册、legacy未证实、幂等"
      },
      {
        "file": "memory/proactive_target.py",
        "symbols": [
          "pick_target"
        ],
        "intended_change": "target fact_subject/eligibility"
      },
      {
        "file": "memory/proactive_contract.py",
        "symbols": [],
        "intended_change": "exact证据与合法SPACE、predicate模板、版本"
      },
      {
        "file": "tools/data_repair.py",
        "symbols": [
          "preview_repairs",
          "apply_repairs",
          "revoke_batch"
        ],
        "intended_change": "proposed quarantine/lineage/source repair，CAS审计全副作用"
      },
      {
        "file": "memory/scope_versions.py",
        "symbols": [],
        "intended_change": "如需补接口，strict同事务bump；否则复用现有"
      },
      {
        "file": "memory/retrieval_v2.py",
        "symbols": [],
        "intended_change": "必要provenance投影，授权scope不扩大"
      },
      {
        "file": "memory_rust/backend.py",
        "symbols": [
          "PromotionRequest"
        ],
        "intended_change": "API3/schema19、required CAS版本与scope/evidence/candidate字段及跨语言typed bytes golden"
      },
      {
        "file": "memory_rust/selector.py",
        "symbols": [],
        "intended_change": "新合同与不匹配显式处理"
      },
      {
        "file": "memory_rust/native/src/schema.rs",
        "symbols": [
          "ensure_supported"
        ],
        "intended_change": "API3/schema19常量"
      },
      {
        "file": "memory_rust/native/src/promotion.rs",
        "symbols": [
          "promote_inner",
          "promote"
        ],
        "intended_change": "transaction evidence/epoch/CAS gate与主体合并边界"
      },
      {
        "file": "memory_rust/native/src/lib.rs",
        "symbols": [],
        "intended_change": "如需要，导出合同适配"
      },
      {
        "file": "memory_rust/native/src/retrieval.rs",
        "symbols": [],
        "intended_change": "必要返回投影和测试schema更新"
      },
      {
        "file": "scripts/evaluate_dialogue_attribution.py",
        "symbols": [
          "_guard_stage"
        ],
        "intended_change": "生产同源batch模式、oracle、真实Compact及完整budget"
      },
      {
        "file": "core/observability/message_flow.py",
        "symbols": [
          "decision"
        ],
        "intended_change": "优先复用metrics；仅不足时最小适配"
      },
      {
        "file": "tests/fixtures/dialogue_attribution/recurrence_20261008_*.json",
        "symbols": [],
        "intended_change": "proposed五现场及正常对照fixtures"
      },
      {
        "file": "tests/",
        "symbols": [],
        "intended_change": "仅§8列出的相关既有测试与必要新场景"
      }
    ],
    "tests": [
      {
        "file": "tests/test_attribution_wiring.py",
        "scenarios": [
          "typed作者篡改→拒绝；服务端已知风险producer→route→模板；自由文本任意倒置不宣称必捕获",
          "suppressed→真实群私入口→零占位",
          "seal后篡改→发送前拒绝"
        ]
      },
      {
        "file": "tests/runtime/test_turn_service.py",
        "scenarios": [
          "生产完整post-hook装配→单一解析/guard/render/seal",
          "provider错误/direct/silent→可信plan或零发送"
        ]
      },
      {
        "file": "tests/test_social_delivery.py",
        "scenarios": [
          "分段ack/failed/unknown→BOT_SELF仅ack",
          "epoch变后未启动段中止，已在途仍按真实ack/failed/unknown记录"
        ]
      },
      {
        "file": "tests/test_session_compact.py",
        "scenarios": [
          "条件/否定/多人原句→model选ID→server原文归属保持",
          "非法ref→不推进",
          "两次同区间失败→下次合法确定性packet或明确暂停",
          "await期间reset/identity变化→CAS拒绝"
        ]
      },
      {
        "file": "tests/test_session_context_cache.py",
        "scenarios": [
          "summary同compact_count清空/格式失效→revision改变→暖缓存不返回旧包"
        ]
      },
      {
        "file": "tests/test_candidate_reinforcement.py",
        "scenarios": [
          "枚举/转述/高confidence+stage2失败→unknown不可晋升",
          "跨Bot/群source与精确子集→拒错绑定",
          "同源重放→occurrence不增加"
        ]
      },
      {
        "file": "tests/test_proactive_target.py",
        "scenarios": [
          "合法accepted SPACE且subject明确→可选正确对象",
          "legacy/unknown/Bot speech→无主动资格"
        ]
      },
      {
        "file": "tests/test_personal_memory_sharing.py",
        "scenarios": [
          "纠正/repair/revoke持久scope版本→暖冷实际检索一致",
          "同源多claim/多source同claim→精确重评，不误撤projection槽",
          "logical claim repair任一成员漂移→全组CAS拒绝，scopecounter不恢复旧值"
        ]
      },
      {
        "file": "tests/test_migrations.py",
        "scenarios": [
          "schema18副本→19→旧数据未认证、受众不扩大",
          "重复迁移幂等、hardfailure回滚"
        ]
      },
      {
        "file": "tests/test_memory_rust_promotion.py",
        "scenarios": [
          "API3真实native与Python同候选→同gate，typed bytes golden一致",
          "预审后纠正/source被改删→native事务CAS拒绝；required字段缺失拒绝",
          "旧native API2/schema18→显式不匹配"
        ]
      },
      {
        "file": "scripts/evaluate_dialogue_attribution.py",
        "scenarios": [
          "oracle顶层优先，缺/冲突拒跑",
          "真实system/protocol/packet budget",
          "26×10主验收+消融，raw/guard/final分层、人审无null"
        ]
      }
    ],
    "verification_commands": [
      "docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs status",
      "docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs impact apply_attribution_guard --direction upstream --depth 3 --repo Stella_project",
      "docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs impact compact_once --direction upstream --depth 3 --repo Stella_project",
      "python -m pytest tests/test_attribution_wiring.py tests/test_dialogue_attribution_repair.py tests/runtime/test_turn_service.py tests/runtime/test_facade_turns.py tests/test_runtime_contract.py tests/test_social_delivery.py tests/observability/test_message_flow_runtime.py -q",
      "python -m pytest tests/test_session_compact.py tests/test_session_context.py tests/test_session_context_cache.py tests/test_context_tail.py tests/test_conversation_projection.py tests/test_context_budget.py tests/test_usage_accounting.py -q",
      "python -m pytest tests/test_candidate_reinforcement.py tests/test_short_term_attribution.py tests/test_proactive_target.py tests/test_proactive_at_flow.py tests/test_proactive_prompt.py tests/test_memory_rust_promotion.py tests/test_memory_rust_selector.py -q",
      "python -m pytest tests/test_migrations.py tests/test_retrieval_v2_and_schema.py tests/test_access_semantics.py tests/test_personal_memory_sharing.py tests/test_personal_memory_backfill.py tests/runtime/test_ingress_native.py tests/runtime/test_proactive_native.py tests/observability/test_memory_flow_lifecycle.py tests/observability/test_proactive_flow_lifecycle.py -q",
      "python -m pytest tests/ -v --cov=. --cov-branch --cov-report=xml -n auto --dist loadgroup --timeout=120 --timeout-method=thread",
      "python -m ruff check core/context.py core/dialogue_attribution.py core/runtime/turn_service.py core/runtime/facade.py core/social/delivery.py memory tools/data_repair.py scripts/evaluate_dialogue_attribution.py stella_project/plugins/bot_main/ai_gateway.py memory_rust",
      "cargo test --manifest-path memory_rust/native/Cargo.toml",
      "docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project"
    ],
    "risks": [
      "HIGH compact_once/_write_memory_candidates/_process_new_candidates_rust；CRITICAL apply_summary；全部d1见§9",
      "attribution_guard_hook UNKNOWN图caller；必须完整动态装配验证，不能零caller视为安全",
      "schema19/API3不兼容旧native；构建与选择/迁移一起交付，回退不能交旧native读新库",
      "自由social文本仍可能语义错归属；schema和词法不能证明任意中文",
      "extractive packet token更贵；全metadata预算/有界降级，不能无界扫历史",
      "repair lineage旧数据可能不完整；只能确证清理，目标不明确manualreview",
      "graph process enumeration有截断预算，不代表跨语言或动态路径不存在"
    ],
    "assumptions": [
      "用户执行；P0核实际测试群/私聊/Bot/端点额度/native构建环境，不能假定已就绪",
      "正常主聊天只一次调用；P0验证现有离线抽取审核能提供source span/主体/state，失败unknown",
      "验收预算C260+A/B/D180=440回复加Compact另计；P0记录并发/额度，分批不中途改分母",
      "本机Python3.14与cargo1.97.1已核版本，但native发布Python3.12构建/import/事务与完整工具链另验",
      "source留存逐条核，有raw/可信snapshot才accepted，缺失legacy quarantine",
      "reset是否另有cacheclear未追；实现独立revision并做读取缓存回归",
      "本计划覆盖列出文件；执行如发现新增path/symbol先补图/source/impact后更新实施记录"
    ],
    "open_questions": [
      "P0 source retention与旧派生lineage哪些可确证？preview列出unknown不猜",
      "P6 qwen实际人格下新协议遵循度是否达258/260？失败单独prompt/schema能力/模型比较",
      "P0/P4/P7 Python/native实际生效入口和API/schema/hash是什么？真实运行记录",
      "P0端点并发和440+Compact成本是否能分批完成？保持既有限流",
      "修复数据暖/冷/撤销如何对应真实scopekeys？按manifest核对实际retrieval版本"
    ],
    "avoid": [
      "Do not repeat full repository discovery",
      "Do not replace established patterns without evidence",
      "不把single schema/ref合法/绿色hook当自由文本语义通过",
      "不恢复raw fallback、双台词或suppressed占位；不在seal后改台词",
      "不加隐藏第二次聊天模型调用",
      "不改SPACE owner.subject_key或扩大私人访问",
      "不将CONFIRMED/highconfidence/stage1fallback自动映射accepted",
      "不把原始source row所有claim一起清空，不用相似文本全局撤销",
      "不以guard off/shadow恢复已知错误放行作为回退",
      "不把helper/unit/FakeRust/时间满48h当真实模型/native/QQ接受",
      "不覆盖既有untracked报告/计划/.pyd备份；不直接应用生产修复未经审核manifest",
      "每符号编辑先impact，提交前完整detect_changes；UNKNOWN/partial/truncated补证"
    ]
  }
}
~~~

## 12. Assumptions and Open Questions

[assumed] 用户自行执行修改、测试、真实端点和QQ灰度；本轮授权仅制定方案。P0核实际可控测试群/私聊、Bot身份、端点额度及native构建环境；没有实测前这些条件不写“已就绪”。

[assumed] 采用一次主聊天调用、沿用现有离线抽取审核阶段，不另加聊天verifier；P0检查抽取后端能否返回有效source span/主体/状态，失败路径按unknown，不暗中增调用。

[assumed] 26×10和440回复+Compact是本方案验收预算，尚未消耗。P0记录端点预算与执行并发；保持既有服务限流、无业务高并发假设。预算不够分批继续，不改分母。

[inferred] 已冻结的选择：single envelope、最终封存、extractive packet、独立summary_revision、SPACE语义主体独立、schema19/API3、lineage表、有限兼容、受限纠正。以下待执行前实证，但无需重开总体架构：

1. 当前source保留策略能否保证旧候选可核：查原消息/snapshot；不能核的legacy保持quarantine。
2. 当前人格与qwen模型对新protocol的遵循度：先跑5新现场+正常对照冒烟；无法达门槛则调整受限生成能力或另列模型比较，不把它当已确定模型缺陷。
3. native与Python真实生效入口：P0记录backend选择、API/schema/hash，P4实际编译/import/事务跑过，P7实际QQ分别覆盖。
4. reset调用是否另有cache clear：本轮只证明静态key缺口；实现仍统一revision并测，不宣称已有缓存复发。
5. repair lineage涉及哪些旧derived rows：preview不能明确绑定的留人工review，不按source全文删除。
6. 当前repo未提交文件属于既有工作；P0保存status和provenance，勿覆盖报告、旧计划、.pyd备份或重启日志。

## 13. Definition of Done

[inferred] 全部满足才标 **IMPLEMENTED AND FIELD ACCEPTED**：

- [ ] P1–P5合同接入真实装配；四发送入口只用sealed plan，suppressed无占位，BOT_SELF/学习只用ack。
- [ ] Compact原文/作者/对象不由模型改写；失败不推进、CAS/计数不变、旧格式和暖缓存失效闭合。
- [ ] schema19/API3旧库幂等升级、native实际构建和Python/native事务门槛通过；所有画像/事实/主动来源accepted及lineage可追。
- [ ] 胃疼等污染修复manifest已审核并按实际scope applied；副本apply/revoke/reapply与生产暖/冷复核通过，无过度撤销。
- [ ] 所需pytest/ruff/native checks与完整detect_changes通过；新golden差异人工审阅，没有partial/truncated未解决项。
- [ ] 260主样本、正常完成率、协议率、预算和性能硬门槛全部通过；oracle无未复核null，消融与Compact调用分开计。
- [ ] G1/G2/G3各自通过，G3达到48h且200轮；最终消息/decision/receipt/入库有持久可复核链。
- [ ] compatibility_deadline已执行或有明确剩余期限；回退方案测试过，不恢复已知错误放行。

[inferred] 若只完成某些阶段，交付应写明“已实现到P几、哪些已验证、哪些NOT READY”；绿色测试、修复报告或本计划文件本身均不能替代真实模型及QQ验收。
