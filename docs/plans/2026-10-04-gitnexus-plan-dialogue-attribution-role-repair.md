# GitNexus Engineering Plan — 多人群聊发言与事件归属修复

> Task: 修复群 263402786 在 2026-10-04 QQ 时间 19:09:22 起的多人对话复现，并建立可验证的发言/动作/事实状态验收。
> 深度：deep / full；状态：方案完成，尚未实施。
> Evidence verified at commit 6a6f311e94ccd5058ec1f305f374de613f2e7c86；分支 feat/dashboard-flow-completeness-repair。
> GitNexus: 本轮 analyze --index-only --pdg 刷新成功，indexed/current commit 相同；发布本计划前 status 为 up-to-date。CLI 1.6.11，Node 22.23.2，/repo=E:\stella\stella_project，容器 stella-gitnexus。
> Publication re-anchor: 工作区整体dirty摘要发生变化，HEAD与25个cited-path条目未变；按Deepen模式重新核验runner/status、刷新文档索引（121.1s）、逐一重查11个impact与3个PDG，风险及直接依赖一致。业务代码和执行状态仍未实施。
> Evidence provenance schema 2；global dirty digest 9c6156bebb3d681552fea707c604d5289ad4344438bf2276541acb38aadd9df6；cited-path manifest 25 个排序条目；仅排除本计划确切路径。
> 证据标记：[verified] 当前源码/配置/已执行探针；[graph] 图结果；[inferred] 有证据支持但未做模型因果对照；[assumed] 待实施时确认。

## 1. Objective

让 Stella 在共享群上下文中可靠区分：当前说话者、每条历史发言的作者、Bot 的回复对象、话语中的动作主体/受体，以及“已发生”与“条件/未来/否定/转述”。完成指标见 §13；不会以“提示词已增加”“单测通过”代替真实模型验收。

边界：沿用现有 ChatContext、TurnService、schema16、SQLite、单次正常回复模型调用与 8K 预算；不把群历史分割成彼此隔离的私聊，不增加每轮身份判别模型调用，不自动修改人格/下载模型/改量化。本计划没有修改业务代码、测试、配置或生产数据，没有生成真实 QQ 消息。

## 2. Current Behaviour

[verified] 真实复现记录见 docs/reports/2026-10-04-multi-user-identity-recurrence-190922.md:45。memory_traces 1182 当前 sender=1035720144；历史正确记录 Bot→176403822“下次再乱摸我手给你冻上”，实际模型却说“176403822还说要冻我手”，thought 同时将条件威胁变成“已经冻过手”。该轮 1227/6340 tokens，无裁剪，3 气泡确认送达。

[verified] 实时历史已经具有作者/收件人，但首泡“我（回复给 用户(A)）”、后续“我（同一条回复，第3/3条）”依赖跨行继承。_fetch_recent_tail 以逻辑单元选择、最后逐气泡输出；最终预算又逐物理行裁剪（memory/pre_processors.py:579；core/context_budget.py:260），所以“逻辑单元被选择”不等于“最终始终完整保留”。

[verified] OpenAI-compatible 后端把整段背景和当前输入装进一个 user message，前面只有 system message（core/llm/lm_studio.py:110）；LLMBackend 接口是 generate(prompt: str, system_prompt: str)。不存在由后端原生 user/assistant roles 自动恢复群参与者身份的机制。

## 3. Relevant Architecture

现有链路：

```text
OneBot 原始事件 → 适配器 _check_reply/_check_at_me
→ record_group_chat / handle_chat / handle_private_chat
→ _extract_message_relations → ChatContext 身份信封
→ record_message / resolve_reply_target
→ build_context → _fetch_recent_tail
→ build_v2_named_sections → TurnService.prepare_turn
→ fit_conversation_parts → 后端 generate（单个 user prompt）
→ 确认发送回执 → _record_bot_lines → 下一轮历史
                          ↘ fetch_pending_messages → build_compact_prompt
                             → COMPACT 模型 → guarded apply/skip → 较早摘要
```

[verified] 最新原文、会话压缩摘要和整合器话题摘要共存（pre_processors.py:340–355）；摘要不应替代原文的作者证据。会话压缩摘要是 session_context 的进程内状态，不是本次需要新增的数据库表（session_context.py:52–101）。

[verified] 预算 v2 保护 identity/当前输入，先删 evidence、memories、profile，后删历史行；冻结 parts_input 供离线预算回放（turn_service.py:535）。本方案优先改变输入投影，保留预算算法与后端签名，避免扩大到 provider/工具/Cometa/Planner 的契约迁移。

## 4. GitNexus Findings

本轮读了 context/clusters/processes 资源；功能区涉及 Bot_main、Memory、Runtime、Llm、Observability、Tests。资源列表是有界摘要，process 缺项不代表没有执行链。概念 query 导航到 prepare_turn、_record_bot_lines、record_message、fetch_pending_messages、build_compact_prompt；随后用 context/impact 和源码核对。

所有 impact 使用 upstream、repo=Stella_project、depth=3；风险采用包含测试的完整结果，不用 riskSharedAxes 降级：

| symbol / 文件 | 图风险 | d=1 直接数 | 改动边界 |
| --- | --- | --- | --- |
| _extract_message_relations / ai_gateway.py | HIGH | 3 | 群主动、群被动、私聊入口 |
| _record_bot_lines / ai_gateway.py | CRITICAL | 13 | 所有 Bot 历史写入调用者；只改 message ID 解析 |
| resolve_reply_target / pre_processors.py | HIGH | 5 | 带 scope 的引用作者解析 |
| _bot_bubble_recipient / conversation_identity.py | HIGH | 1 | 纠正目标解析 |
| resolve_correction_target / conversation_identity.py | HIGH | 3 | 身份纠正及两个测试 |
| _query_tail_rows_with_relations / pre_processors.py | LOW | 1 | 扩展投影列 |
| _render_tail_line / pre_processors.py | LOW | 1 | 行格式兼容包装 |
| _fetch_recent_tail / pre_processors.py | MEDIUM | 7 | 实时上下文与尾巴测试 |
| build_v2_named_sections / prompt_builder.py | HIGH | 3 | 主回复、兼容 prompt builder、compose 测试 |
| fetch_pending_messages / session_compact.py | CRITICAL | 5 | 压缩执行、区间/计数测试 |
| build_compact_prompt / session_compact.py | CRITICAL | 7 | 压缩模板和缓存/防编造测试 |

可审计结果摘录：impact(_record_bot_lines, include-tests) 返回 impactedCount=20/direct=13/risk=CRITICAL；impact(_fetch_recent_tail) 返回 29/direct=7/risk=MEDIUM；context(build_v2_named_sections) 返回 TurnService.prepare_turn 与 build_v2_prompt_context。部分符号没有 process 列表；没有将 0 process 当成影响为零。

完整 d=1 覆盖与测试分组见 §9。HIGH/CRITICAL 已在交互中提示，实施时须在每个符号编辑前重新 impact，不能把本次规划结果当作长期豁免。

## 5. Statement-Level PDG Findings

1. [graph] impact(mode=pdg, _fetch_recent_tail, line=583) 的 12 个有界相关语句包含 limit<=0、关系查询/旧库回退、selected、is_grouped、idx>0。切片 truncatedBy=depth，risk=UNKNOWN；只能作为局部导航。 [verified] 当前源码分支在 idx>0 时绕过 _render_tail_line，因此后续气泡没有收件人标签。
2. [graph] impact(mode=pdg, _extract_message_relations, line=944) 只返回 1 个语句，risk=UNKNOWN；跨适配器动态属性流程不由该切片证明。 [verified] 生产 conda stella 的 OneBot adapter 2.4.6 源码先 deepcopy 成 original_message，再将 reply 段删出 message 并设置 event.reply；Stella helper 仅取 event.get_message()，所以原始关系消失。
3. [graph] impact(mode=pdg, _record_bot_lines, line=2824) affectedStatements 为空，risk=UNKNOWN；这不是安全结论。 [verified] 当前持久化表达式 int(platform_id) if platform_id.isdigit() else 0 将合法负数消息 ID 变成 0。AST 源函数探针独立证明了这一点。

只记录上述真实返回，没有重建或声称存在未返回的 CDG/REACHING_DEF 边。调用图完整风险判断与源码/实际探针共同约束改动。

## 6. Proposed Changes

### 6.1 P0：先修可确定的数据损失

**A. 原始引用提取 — ai_gateway.py:_extract_message_relations**

[verified] 当前只扫描 get_message()（939–958），真实原文含 reply 的输入落库为空；生产适配器清洗过程与隔离探针一致。

拟改：优先扫描适配器保存的 original_message；不存在时使用 event.reply 的可信 message_id 补足引用；最后才用处理后的消息段兼容测试桩/其他事件形状。收集候选后确定唯一引用，冲突、多义/非法值保持 unknown；不得从用户正文解析 CQ/QQ 号来猜人。@ 去重，并继续排除 Bot/@all。函数返回形状保持 tuple[str|None, tuple[str,...]]；三种入口仍共用同一 helper。event.reply 中的作者不能绕过现有 canonical conversation+bot 校验成为身份主体。

**B. 有符号消息 ID — ai_gateway.py:_record_bot_lines、pre_processors.py:resolve_reply_target、conversation_identity.py:_bot_bubble_recipient**

[verified] 所述三个位置拒绝负数。真实平台回执 -558868042 在 group_messages 中成了 msg_id=0，正数 381231377 保留下来。

拟改：统一接受平台 integer 或规范十进制文本的非零有符号 ID，拒绝 bool、浮点、空串、字母、0；支持负数不是放宽 user_id/bot_id 校验。可在拟新增纯投影模块放一个 message-ID parser，实际符号名由实现确定。_record_bot_lines 仍只记 acknowledged，failed/unknown 不记；不将 message_sent 回调当作另一个重复写库来源。旧无 origin/receipt 路径继续可用，不猜平台 ID。

**C. 引用 Bot 时的纠正目标 — conversation_identity.py:resolve_correction_target / _bot_bubble_recipient**

[verified] 当前已解析 reply_target_user_id=Bot 时会抢先把 Bot 当纠正目标，绕过 Bot 气泡收件人；_bot_bubble_recipient SQL 没使用传入 conversation_key。隔离探针返回了 Bot 与跨 key 的收件人，而不是 intended recipient/unknown。

拟改：保留“唯一非 Bot @ 优先”；引用普通用户仍取原作者；引用 Bot 时按同 conversation+bot 的确认 BOT_SELF 气泡收件人定位候选，且不把 Bot 自己写为用户别名主体；数据缺失、重复、跨 key 均 unknown。不改变自称/第三人证据等级，不新增一般自然语言实体识别。旧库缺 canonical 列时采取保守降级，不以 group_key 独自推断跨 Bot 归属。

### 6.2 P1：共享的明确作者投影，避免代词/标签跨行继承

拟新增 **memory/conversation_projection.py**（当前路径不存在；这是计划创建的纯模块，不是已实现能力）。职责仅为有符号 message ID 解析与已经可信的消息行投影/序列化；不含 DB、模型、会话队列或语义实体抽取。

为每个记录保留：作者稳定 ID、作者角色 user/BOT_SELF、收件人或 unknown、引用 ID/作者或 unknown、被提及用户、logical_message_id、已确认 part_index、源输入 ID，以及原始正文。语义事件不要用正则抽成“已发生”事实，body 只表示“某人曾说这些话”。

推荐默认呈现为**每个逻辑回复一个物理行**，内容为 JSON 转义的气泡数组；例子只是拟定格式：

```text
记录R2 [作者=Stella/Bot(1694717255); 回复给=用户(176403822); 原输入=383945296]:
  气泡=[{"part":0,"text":"谁是小孩啦"},{"part":1,"text":"明明是你自己刚睡醒脑子不清醒"},{"part":2,"text":"下次再乱摸我手给你冻上"}]
```

以上为文档换行示意，实际该记录必须为一个物理行，正文内换行变成 JSON 的转义序列；不得把气泡正文直接插成伪造的“用户/系统”标签。Bot(稳定ID) 是发言作者，回复给用户A是收件人；正文里的“我”才指作者、“你”只在原上下文中指收件人，不能自动绑定到当前用户C。不输出内部 QQ/记录标签到正常聊天台词，除非用户明确问身份信息。

修改 pre_processors.py：
- _query_tail_rows_with_relations 追加投影所需 msg_id/origin_msg_id/bot_id/conversation_key 列，保留现有 part_index 并保持原索引列含义；旧库 missing-column 回退仍能读。
- _fetch_recent_tail 连续合组时核对 logical ID、作者/来源及收件人一致性；冲突记录独立呈现/关系 unknown，不能合成一个“人”。
- 多气泡一次输出一个自足行；单条用户消息正文也安全转义。保留实际 part_index，不为过滤/失败气泡虚构前后文或总段数。
- 尾巴限额计算采用最终渲染文本的成本，包含作者/ID/引用/转义开销，继续受 48 行扫描、逻辑单元数与 token 上限控制。
- 返回 (text, tail_start_id) 形状与原始行起点语义不变；旧信封缺 recipient 时明确 unknown，不猜最近说话者。

[verified] 预算最终按 newline 删除，因此新投影中的每个逻辑回复行会整体保留/整体移除。保留 core/context_budget.py 的预算 v2 算法，仍需集成测试验证极大单元导致 over_protected/历史让位时行为；不改算法、不更换 v1/v2 分派。在实际实现若选择多物理行块，则本方案的“小范围”前提失效：必须增加结构化 history units 和 budget v3/replay 兼容，不能继续宣称旧按行预算安全。

新投影有显式版本常量与版本前缀，部署以新进程启用，从而不复用旧进程的已组装缓存。暂不引入运行中开关/全局 schema bump；冻结回放始终消费当时的 parts_input 字符串。

### 6.3 P1：受预算保护的角色与事实状态规则

修改 prompt_builder.py:build_v2_named_sections 的 identity 稳定区（已有保护，不改变段落顺序），增加短而明确的固定约束：
- 你是 Stella；历史作者写 Stella/BOT_SELF 的话是你自己说的，收件人不是作者。
- 当前只回复当前 sender；其他成员的台词与被谈论者不自动继承给当前人。
- 历史是发言记录，不是事实证明；你曾威胁、假设、玩笑、否认，不意味着相应事件实际发生。
- 提及过去事件前必须能从记录支持作者、对象与发生状态；不确定时不复述、不补造；可以自然回应当前“摸摸”，不必串起其他人的旧剧情。

规则不硬编码“冻手”，不靠单词匹配制造状态事实；不要求每轮额外输出复杂身份 JSON。无需增加每轮第二次 LLM 调用。人格台词风格保留，事实/角色限制优先于接梗。

### 6.4 P2：压缩输入与实时历史使用同一角色约定

[verified] session_compact.py:123 当前只 SELECT id,user_id,content,source_kind，139 格式为“我:”；压缩丢失收件人是潜在重复源，不是这次无裁剪复现的已证明原因。

修改 fetch_pending_messages，读可用关系列并使用相同纯投影。保留 low_id < id < high_id、旧 limit 的原始行计数、max_id 最后扫描行以及 empty-content 前进契约；不得因合组改变返回 count 为逻辑单元数。批次切在逻辑消息中间时每段仍带完整作者/收件人，不额外越界读取/推进位置。

build_compact_prompt/COMPACT_PROMPT 保留自然语言简短输出、固定前缀缓存、原防编造原则。要求以第三人作者名/ID描述“Stella对A说了……”，保留 if/下次/没有/只是转述等状态；禁止把 Bot 引文提升为用户自我声明。已有摘要的合并同样遵守这一点；这仍是模型规则，不是数学保证，必须接受真实压缩后再回复的端到端验收。

不改变 compact_once 的 acquire/gate、异步调用、CAS、guard、apply/skip/watermark；不将 SQLite 事务跨 LLM await。已有易失摘要不会通过修改 prompt 自动纠正：灰度部署以新进程清空易失状态，或走已有受保护的指定会话 reset；不清理长期记忆、不改写原始历史、不做生产全库 backfill。

### 6.5 P3：模型输出验收与有条件升级

拟新增 scripts/evaluate_dialogue_attribution.py（当前不存在），离线读取冻结案例，在不连 QQ、不写生产库的条件下调用指定模型。记录原始 wire messages、输入格式版本、模型标识/模型文件指纹（能取到才记录）、实际解码参数、context/max tokens、seed 支持情况、完整输出与人工复核标注。

不把规则匹配器的“未找到关键词”当作语义正确；关键错误分类是 speaker swap、recipient carry-over、agent/patient reversal、hypothetical-as-fact、quoted-denial-as-assertion，以及 Bot 与用户姓名混合。主评估由明确场景 oracle+人工语义复核，自动匹配仅辅助筛选。

原生 user/assistant 消息数组作为**有条件的后续实验**：只有推荐投影+规则在冻结模型仍不达标时，才单独规划后端中性 structured messages 契约、兼容层、预算/replay 与各 provider 的角色限制。不得直接拆 user prompt 成 role=assistant 历史来静默改变其他消费者；更换/重新量化模型同样须对照测试、保持资源和下载授权边界。

## 7. Implementation Sequence

| 阶段 | 工作 | 依赖/退出条件 |
| --- | --- | --- |
| M0 | 将真实记录复制为隔离冻结夹具（A/B/C 稳定映射、含原系统提示）；新增会失败的负数 ID、适配器清洗后事件和 role/state oracle | baseline能够再现机制/原模型错误；禁止仅存20条文本而缺原prompt/采样条件 |
| M1 | 修原始 reply/@ 提取与三处 signed message ID；修 Bot引用纠正分支与 canonical 查询 | 端到端 原始事件→库→引用解析，对正负 ID 一致；unknown/cross-scope保守 |
| M2 | 增纯投影模块；尾巴一条逻辑回复一个物理行，算完整渲染成本 | 保留 DB 行/逻辑 ID/part_index/水位；插话、多泡、转义、旧库通过 |
| M3 | protected identity 添加角色/状态规则；v1/v2预算及frozenparts保持原接口 | 8K预算内，无新增正常模型调用，现有预算回放通过 |
| M4 | 压缩输入同投影，模板保留作者与条件/否定/转述 | 测试 interval/count、CAS reset/identity revision、旧库降级；summary→reply不串人 |
| M5 | 消融对照、80次验收、一次性更新必要golden/manifest、完整门禁 | 达到§13；未通过时回改投影/规则，或开启独立升级实验 |
| M6 | 一个群灰度：双号/第三人真实复演，确认平台输出和DB关系；再扩大 | 不自动重启生产、不发测试QQ；实施时与操作者协调真实窗口 |

每个阶段新增/修改 symbol 前重新 GitNexus impact，HIGH/CRITICAL 先报告；每次提交前 detect-changes --scope all，partial/truncated 不能当净通过。此次仅方案，不做 M0–M6 改动。

## 8. Test Strategy

### 已执行基线与真实函数探针

[verified] 本轮四个相关套件 **87 passed，55 个既有依赖弃用 warning**（Python3.14；没有调用真实模型）。基线通过仍没有覆盖下面的真实缺陷。

已执行隔离探针采用当前源码 AST 函数体，外部传输/持久化为桩或临时 SQLite；这是函数机制验证，不是完整机器人集成测试：
- acknowledged platform_message_id=-558868042 → 实际 _record_bot_lines 构造 msg_id=0。
- original_message 包含 reply、event.reply 有 ID、get_message 只有处理后正文 → 实际 extractor 返回 (None,())。
- 同会话有负数和正数原消息 → resolver 对负数返回 unknown，对正数返回 Bot。
- Bot泡收件人=2002：negative引用 unknown；positive引用且 reply_target=Bot 返回Bot；仅改 conversation_key 仍取到2002。
均未访问生产库、未发送消息。这些需在 M0 转为正规的回归测试，不能把 AST 探针当成修复后验收。

### 确定性场景矩阵

| 场景 | 输入→动作→期望 | 现有/拟新增测试 |
| --- | --- | --- |
| G1 | 真实 GroupMessageEvent 经适配器清洗，original有reply/at → 三种入口提取 → 非Bot提及/引用不丢 | test_message_relations；test_private_chat_ingress集成 |
| G2 | event.reply与original冲突/不可用 → 提取 → 唯一可信或unknown；正文CQ不能改主体 | test_message_relations |
| G3 | 正数/负数/整数/空/0/bool/float/非法ID → 回执落库和引用查找 → 正负一致，其他unknown | test_message_relations；test_conversation_identity |
| G4 | 不同Bot/会话同msgID、旧列缺失、重复目标 → resolve → 不跨scope猜人 | test_message_relations；test_conversation_identity |
| G5 | 回复Bot“他才是X”，reply作者已解析Bot，泡收件人A → 纠正 → A候选，Bot/C不继承A | test_conversation_identity |
| G6 | A→B→A→C，多泡含failed/unknown及缺首泡 → 投影 → 正确作者/对象、原part_index、仅确认内容 | test_message_relations；新test_conversation_projection |
| G7 | 正文换行/引号/伪造作者头/内含我和你 → 单物理行序列化 → 正文不会创建额外记录 | 新test_conversation_projection |
| G8 | 历史单元成本含长ID/headers/JSON → 选择与最终budget → 全记录保留或全删，无孤立第3泡 | test_structured_conversation_budget；test_context_tail |
| G9 | low/high/limit切多泡、空消息 → compact fetch → 保留原扫描max/count，不跨界/跳水位 | test_session_compact |
| G10 | 真实压缩输入→预设摘要+接续prompt → 对象不丢；并发reset/identity修订 → 旧结果不提交 | test_session_compact |
| G11 | 同summary新版旧版、私聊、群级主动user_id0、无origin历史 → 投影 → 不制造默认某个人 | test_message_relations；私聊/主动回归 |
| G12 | 带新投影v2parts与旧v1/v2frozenparts → replay → 各自原字节/预算可重放 | test_structured_conversation_budget |

M0增加的函数名由实现确定，表中已有测试文件确实存在；新增路径明确标为拟新增。遗留“BOT_SELF必须为我:”及“第N/M条”字符串断言需按新的明确作者语义更新，保留归属/水位断言，而不是为了绿色保留含糊格式。

### 真实模型采样与消融

先冻结同一个模型/端点/解码参数与输入字节，分三组：
- V0：原始真实 prompt，仅作为对照。
- V1：M1关系修复+M2明确投影，无新状态规则。
- V2：V1+M3规则；再分别运行 M4压缩后接续条件。

原复现每个变体先跑10次，比较四类错误而不挑一次成功输出；获选版本再做**原T20八类场景+新增八类状态/角色场景，各5次=80次**。原场景包括切人/同名/纠正/长背景；新增包括本次Bot用户角色反转、主体受体反转、条件未来、否定、第三人转述、多人相同动作、多泡预算裁剪、压缩后接续。统计关键归属/状态错误0/80、原任务完成≥72/80。0/80只代表样本门槛，不是所有中文群聊的绝对保证。

当前生产配置文件声明 chat温度0.7、compact0.3、context8192、reserve1000、安全200（只读取允许键）；不据此宣称19:11实际wire参数全已冻结。用运行时真实解析值记录，不先把温度调低掩盖输入问题。model换型/量化对比在输入修复仍失败时单独实验。

### 验证命令

已执行：
```powershell
python -m pytest tests/test_message_relations.py tests/test_conversation_identity.py tests/test_structured_conversation_budget.py tests/test_session_compact.py -q
```

实施后：
```powershell
python -m pytest tests/test_message_relations.py tests/test_conversation_identity.py tests/test_structured_conversation_budget.py tests/test_session_compact.py tests/test_context_tail.py tests/test_prompt_cache_prefix.py -q
python -m pytest tests/ -q -n auto --dist loadgroup
python -m ruff check .
docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project
```

CI命令与依赖安装见 .github/workflows/ci.yml:90；本机若未装pytest-timeout不加--timeout。拟新增投影套件加入定向命令，新评估脚本在创建并验证CLI后才给出运行命令，不伪造当前已有脚本。

## 9. Risk and Impact Analysis

### d=1 全量责任覆盖

| 被改函数 | 全部直接依赖 | 保持/验收责任 |
| --- | --- | --- |
| _extract_message_relations | handle_chat；handle_private_chat；record_group_chat | 返回形状稳定；群/私聊/被动同规则；SOCIAL开关不影响提取 |
| _record_bot_lines | _announce_sleep_transition；_finish_addressing；_proactive_at_user；_proactive_speak_impl；handle_capability_query；handle_chat；handle_private_chat；handle_reload；handle_scheduling；handle_toggle；test_failed_segment_not_recorded_trusted_part_kept；test_legacy_call_without_origin_still_records；test_multi_bubble_reply_shares_logical_unit | 只修ID解析；旧无origin路径、群主动无个人target、确认/失败/unknown语义不变；覆盖主动、命令回复、私聊 |
| resolve_reply_target | handle_chat；handle_private_chat；record_group_chat；test_reply_resolves_to_original_author_same_conversation；test_reply_unknown_when_message_missing_or_cross_conversation | signed ID与scope，保守unknown |
| _bot_bubble_recipient | resolve_correction_target | canonical+bot，不推断正文人物 |
| resolve_correction_target | process_message_identity；test_reply_to_bot_bubble_recipient_is_candidate；test_resolve_correction_target_priority | @优先、Bot泡收件人、声明证据等级 |
| _query_tail_rows_with_relations；_render_tail_line | 两者直接依赖均为_fetch_recent_tail | append列不误移索引；旧库fallback |
| _fetch_recent_tail | build_context；test_tail_start_id_returned；test_tail_start_id_skips_filtered_messages；test_tail_legacy_db_without_relation_columns；test_tail_renders_relations_and_logical_grouping；test_tail_unit_cap_keeps_recent_suffix；test_tail_unknown_reply_target_rendered_as_unknown | API/起点/时间窗口/unknown；更新格式语义测试 |
| build_v2_named_sections | build_v2_prompt_context；TurnService.prepare_turn；test_no_truncation_matches_legacy_compose | stable beforedynamic；两组装路径共享规则；正常调用数量与预算 |
| fetch_pending_messages | compact_once；test_fetch_excludes_both_ends；test_fetch_limit_advances_incrementally；test_fetch_renders_bot_self_as_wo；test_fetch_skips_empty_content | 原始行limit/count/max水位，更新角色格式 |
| build_compact_prompt | compact_once；test_prompt_cache_prefix._assert_fixed_part_cacheable；test_prompt_contains_anti_fabrication_clauses；test_prompt_has_no_leftover_placeholder；test_prompt_merges_existing_summary；test_prompt_omits_block_without_existing；test_prompt_preserves_own_speech_clause | 前缀可缓存、原防编造、新角色规则；不改CAS |

图对动态入口/跨语言/文档仍有覆盖限制；上表是解析到的直接依赖，不是所有调用的数学全集。源码/运行探针确认的重要入口一并纳入。

### 兼容与性能

- **schema/后端**：不做schema17、不改个人记忆scope/Rust检索合同，使用现有v16列。signed platform message ID 与 user_id严格分开；旧msg_id0无法可靠恢复，保持unknown，不自动回填。
- **角色处理**：修了引用作者后不能让Bot成为人类声明主体；Bot泡收件人只作为现有有源证据的纠正候选，不能把每次引用都理解为用户身份纠正。
- **成本**：增加元数据会增加prompt tokens。按完整渲染长度控制尾巴，不通过增大context/删除identity解决；在冻结夹具测总prompt、消息保留数量和preprocess p95（门槛≤+20ms），不得凭代码声称性能已通过。
- **缓存/回放**：部署新进程清空易失上下文与摘要；不以旧摘要作新事实。旧frozenparts不再查库、不重渲染，budget v2算法保持，格式版本单独于预算版本。若改预算算法必须另立v3，不覆写v2结果。
- **并发/水位**：保留短事务、COMPACT gate与CAS；renderer纯计算，不引入网络、锁或第二消息引擎。
- **生成语义**：以上数据修复是可确定的；“模型不反转角色”的结果只能通过采样支持。新规则/格式可能降低接梗流畅度，任务完成率与人工复核同列发布门槛。
- **范围**：强制断言8K；排除直接搬运历史为原生assistant角色、全摘要JSON化、全局memory backfill、追加在线学习/逐轮语义审查。
- **灰度回退**：schema16不变可回退应用；原始带符号ID是正确数据，应保留。rollback仍须单写入进程。回退旧代码会重新遇到本缺陷，不能称为功能已修复。

## 10. Files Expected to Change

| 文件 | 现有符号或拟新增内容 | 原因 |
| --- | --- | --- |
| stella_project/plugins/bot_main/ai_gateway.py | _extract_message_relations、_record_bot_lines | 原始关系/signed回执 |
| memory/pre_processors.py | resolve_reply_target、_query_tail_rows_with_relations、_render_tail_line、_fetch_recent_tail | signed引用/完整角色投影 |
| memory/conversation_identity.py | _bot_bubble_recipient、resolve_correction_target | Bot泡收件人和canonical校验 |
| memory/prompt_builder.py | build_v2_named_sections | 保护区简短角色/事实状态规则 |
| memory/session_compact.py | fetch_pending_messages、build_compact_prompt/COMPACT_PROMPT | 同投影+同规则，水位不变 |
| memory/conversation_projection.py | 拟新增纯数据投影与message-ID parser，符号待实现 | 两条历史路径共用语义 |
| tests/test_message_relations.py、tests/test_conversation_identity.py | 适配器事件/负数/纠正集成 | 补真实形状测试 |
| tests/test_context_tail.py、tests/test_structured_conversation_budget.py | 完整逻辑行/预算/旧回放 | 防对象头被裁掉 |
| tests/test_session_compact.py、tests/test_prompt_cache_prefix.py | 关系/watermark/template | 摘要高风险门禁 |
| tests/test_conversation_projection.py | 拟新增 | 作者/对象/转义/不合并冲突单元 |
| scripts/evaluate_dialogue_attribution.py | 拟新增模型采样工具；冻结fixture路径在M0创建时记录 | 真实语义验收 |

core/context_budget.py、core/llm/base.py、core/llm/lm_studio.py、TurnService/replay 为已核对的兼容边界，首轮不需改动。私聊既有测试通过既有入口补用例；若实现要修改入口/上下文额外符号，先 impact 并补责任表。

## 11. Reusable Implementation Context

下列机器可读pack包括规范helper生成的完整provenance；新文件为planned/absent，不能当已有API调用。

```json
{
  "implementation_context": {
    "task_summary": "Fix multi-user author/recipient and factual-state recurrence confirmed in QQ group 263402786 at platform time 2026-10-04 19:09:22; plan only, no implementation.",
    "acceptance_criteria": [
      "Original relations survive adapter sanitization; positive and negative platform IDs behave identically, invalid or cross-scope references remain unknown.",
      "BOT_SELF author, recipient and current sender remain distinct; quoted Bot bubble correction resolves only a confirmed same-scope human recipient.",
      "Each logical reply is a single escaped physical line so budget v2 removes whole records; retain 8192 context.",
      "Compaction preserves author/recipient and conditional/negative/quoted status without changing raw-row count, scan watermark or CAS.",
      "Actual model: zero critical attribution/state errors in 80 samples and task completion at least 72/80, followed by coordinated real QQ acceptance."
    ],
    "evidence_provenance": {
      "schema_version": 2,
      "head_commit": "6a6f311e94ccd5058ec1f305f374de613f2e7c86",
      "generated_plan_path": "docs/plans/2026-10-04-gitnexus-plan-dialogue-attribution-role-repair.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "9c6156bebb3d681552fea707c604d5289ad4344438bf2276541acb38aadd9df6"
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
          "path": "StellaData/.env",
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
          "untracked_digest": "sha256:30a5893e456ec75cb8eef5d65d1e498916907b192f48825639a3bebd602de98c"
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
          "head_digest": "sha256:a353c4d7c772bcf1ce45df24b552ac5fa81288650472698bb89a3fae4e2a6797",
          "index_digest": "sha256:a353c4d7c772bcf1ce45df24b552ac5fa81288650472698bb89a3fae4e2a6797",
          "worktree_digest": "sha256:a353c4d7c772bcf1ce45df24b552ac5fa81288650472698bb89a3fae4e2a6797",
          "untracked_digest": "absent"
        },
        {
          "path": "core/llm/base.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c99f95ddf62b440027360792c3c2a6d4c7506f1acfc38198be7396ae36b6a2a8",
          "index_digest": "sha256:c99f95ddf62b440027360792c3c2a6d4c7506f1acfc38198be7396ae36b6a2a8",
          "worktree_digest": "sha256:c99f95ddf62b440027360792c3c2a6d4c7506f1acfc38198be7396ae36b6a2a8",
          "untracked_digest": "absent"
        },
        {
          "path": "core/llm/lm_studio.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e6525af6e3d15662ef441647276a2a1d51cb05851f83f3fe407b44d51fc85b1d",
          "index_digest": "sha256:e6525af6e3d15662ef441647276a2a1d51cb05851f83f3fe407b44d51fc85b1d",
          "worktree_digest": "sha256:06ea8a4408b0cbb11cd40c7f22deedc618eab11d1527b27a1bdadbd4476190bb",
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
          "head_digest": "sha256:f7fdaa92ff3565e92c04384b4797d5bb5af9acbdb91f28bac7b3ad0df3758631",
          "index_digest": "sha256:f7fdaa92ff3565e92c04384b4797d5bb5af9acbdb91f28bac7b3ad0df3758631",
          "worktree_digest": "sha256:2cd29626210ab3df7da4771a30494ba155805715e60208dea7d179d93267df1a",
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
          "path": "docs/reports/2026-10-04-multi-user-identity-recurrence-190922.md",
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
          "untracked_digest": "sha256:86697347c0978e47f50cdb34d6593c246d546e575abf1b96ca5a96bf9f6ba197"
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
          "head_digest": "sha256:4fb350938f53675bc5df51427201d643c9f66d2e1bbe97f8969133433c478385",
          "index_digest": "sha256:4fb350938f53675bc5df51427201d643c9f66d2e1bbe97f8969133433c478385",
          "worktree_digest": "sha256:4fb350938f53675bc5df51427201d643c9f66d2e1bbe97f8969133433c478385",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/conversation_projection.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
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
          "head_digest": "sha256:97f1a5baf4e4479e746ab565a4a0ff0e641bcca0b940453ddaaf357155c27652",
          "index_digest": "sha256:97f1a5baf4e4479e746ab565a4a0ff0e641bcca0b940453ddaaf357155c27652",
          "worktree_digest": "sha256:97f1a5baf4e4479e746ab565a4a0ff0e641bcca0b940453ddaaf357155c27652",
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
          "head_digest": "sha256:b457018ec5c000ed520428704e9258603b5076e306b784ff1bc425cc52477930",
          "index_digest": "sha256:b457018ec5c000ed520428704e9258603b5076e306b784ff1bc425cc52477930",
          "worktree_digest": "sha256:9f75d1468b44af7c907fa170349fa5c31ad9e4ea9d28b4ff86292f6883f421bf",
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
          "head_digest": "sha256:64ee9bd9ba96c456fb33fb23b18acb2c61d5988b90a429748192cd885b1a0a6d",
          "index_digest": "sha256:64ee9bd9ba96c456fb33fb23b18acb2c61d5988b90a429748192cd885b1a0a6d",
          "worktree_digest": "sha256:64ee9bd9ba96c456fb33fb23b18acb2c61d5988b90a429748192cd885b1a0a6d",
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
          "path": "scripts/evaluate_dialogue_attribution.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
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
          "head_digest": "sha256:b361ebfb9cdd2b30a11f50d375632e629467a7a666f23a8b2f6090623f9bbdde",
          "index_digest": "sha256:b361ebfb9cdd2b30a11f50d375632e629467a7a666f23a8b2f6090623f9bbdde",
          "worktree_digest": "sha256:b361ebfb9cdd2b30a11f50d375632e629467a7a666f23a8b2f6090623f9bbdde",
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
          "head_digest": "sha256:4abd8c5cb6c5e4fb3062c3c6957a20487ff77ce3a06e555c0d8fd0df76ad8989",
          "index_digest": "sha256:4abd8c5cb6c5e4fb3062c3c6957a20487ff77ce3a06e555c0d8fd0df76ad8989",
          "worktree_digest": "sha256:4abd8c5cb6c5e4fb3062c3c6957a20487ff77ce3a06e555c0d8fd0df76ad8989",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_conversation_projection.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_message_relations.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:5e0b6ffbebbd189d27a0a71a2757763158a06dea72cfc71484ba1b45ffcae545",
          "index_digest": "sha256:5e0b6ffbebbd189d27a0a71a2757763158a06dea72cfc71484ba1b45ffcae545",
          "worktree_digest": "sha256:5e0b6ffbebbd189d27a0a71a2757763158a06dea72cfc71484ba1b45ffcae545",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_prompt_cache_prefix.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:47edc19ce14a0a7ba11f9ad95149e8c025f43e89cd5d2b93a426587c9432d029",
          "index_digest": "sha256:47edc19ce14a0a7ba11f9ad95149e8c025f43e89cd5d2b93a426587c9432d029",
          "worktree_digest": "sha256:47edc19ce14a0a7ba11f9ad95149e8c025f43e89cd5d2b93a426587c9432d029",
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
          "head_digest": "sha256:5d24a50f74983105da4d6d93c02dbeecffff8d6054c121a770497dbeeab64605",
          "index_digest": "sha256:5d24a50f74983105da4d6d93c02dbeecffff8d6054c121a770497dbeeab64605",
          "worktree_digest": "sha256:5d24a50f74983105da4d6d93c02dbeecffff8d6054c121a770497dbeeab64605",
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
        }
      ]
    },
    "primary_symbols": [
      {
        "symbol": "_extract_message_relations",
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "lines": "939-958",
        "role": "Reads processed event only; prefer preserved original_message and trusted event.reply."
      },
      {
        "symbol": "_record_bot_lines",
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "lines": "2753-2839",
        "role": "Confirmed receipt persistence; signed ID rejected at 2824; CRITICAL impact."
      },
      {
        "symbol": "resolve_reply_target",
        "file": "memory/pre_processors.py",
        "lines": "191-228",
        "role": "Signed ID parsing with canonical conversation and bot scope."
      },
      {
        "symbol": "_fetch_recent_tail",
        "file": "memory/pre_processors.py",
        "lines": "463-589",
        "role": "Logical grouping and full-rendered token cost; current continuation loses recipient."
      },
      {
        "symbol": "fetch_pending_messages",
        "file": "memory/session_compact.py",
        "lines": "109-141",
        "role": "Compaction input loses relations; preserve raw-row boundaries/count/watermark; CRITICAL impact."
      }
    ],
    "related_symbols": [
      {
        "symbol": "_bot_bubble_recipient",
        "file": "memory/conversation_identity.py",
        "lines": "325-346",
        "role": "Signed references and omitted canonical conversation SQL guard."
      },
      {
        "symbol": "resolve_correction_target",
        "file": "memory/conversation_identity.py",
        "lines": "287-322",
        "role": "Resolved author Bot currently masks recipient fallback."
      },
      {
        "symbol": "_query_tail_rows_with_relations",
        "file": "memory/pre_processors.py",
        "lines": "410-430",
        "role": "Append fields without shifting the existing 11-column indexes."
      },
      {
        "symbol": "_render_tail_line",
        "file": "memory/pre_processors.py",
        "lines": "442-460",
        "role": "Replace implicit self label with explicit trusted authorship."
      },
      {
        "symbol": "build_v2_named_sections",
        "file": "memory/prompt_builder.py",
        "lines": "251-308",
        "role": "Protected stable identity and factuality rules; HIGH impact."
      },
      {
        "symbol": "build_compact_prompt",
        "file": "memory/session_compact.py",
        "lines": "84-93",
        "role": "Keep natural-language summary and stable cache prefix; CRITICAL impact."
      },
      {
        "symbol": "compact_once",
        "file": "memory/session_compact.py",
        "lines": "185-275",
        "role": "Existing guarded async compaction, unchanged."
      },
      {
        "symbol": "fit_conversation_parts",
        "file": "core/context_budget.py",
        "lines": "173-316",
        "role": "Existing budget v2 removes history by physical newline; unchanged."
      },
      {
        "symbol": "TurnService.prepare_turn",
        "file": "core/runtime/turn_service.py",
        "lines": "350-554",
        "role": "Freeze parts_input then fit; existing string interface unchanged."
      },
      {
        "symbol": "_base_payload",
        "file": "core/llm/lm_studio.py",
        "lines": "110-129",
        "role": "Single user string; native multi-message API migration deferred."
      }
    ],
    "execution_path": [
      "Original OneBot envelope -> adapter reply/mention sanitization -> group/private/passive ingress.",
      "Preserved relation extraction -> ChatContext -> scoped record and reply resolution.",
      "build_context -> logical history projection -> protected named sections -> prepare_turn -> existing budget -> single model generation.",
      "Acknowledged delivery receipt -> signed platform ID persistence -> subsequent scoped references.",
      "Older raw rows -> shared projection -> compact prompt -> model -> guarded apply/skip -> later context."
    ],
    "pdg_constraints": [
      {
        "description": "_fetch_recent_tail line 583 upstream slice: 12 statements, depth-truncated, risk UNKNOWN.",
        "affected_statements": [
          "idx > 0 continuation branch",
          "is_grouped guard",
          "selected/group selection"
        ],
        "implementation_consequence": "Source confirms recipient omission; use one physical record per logical unit and test final budget. Do not claim complete PDG coverage."
      },
      {
        "description": "_extract_message_relations line 944: one statement, UNKNOWN; dynamic adapter boundary absent.",
        "affected_statements": [
          "list(event.get_message())"
        ],
        "implementation_consequence": "Use verified production adapter 2.4.6 behavior and real sanitized event test."
      },
      {
        "description": "_record_bot_lines line 2824: empty PDG affectedStatements, UNKNOWN.",
        "affected_statements": [],
        "implementation_consequence": "Source and isolated AST probe demonstrate .isdigit rejection; empty slice is not permission or proof of safety."
      }
    ],
    "architectural_patterns": [
      "Reuse RuntimeFacade/TurnService, ChatContext, SQLite/schema16 and asynchronous compaction.",
      "Pure planned conversation_projection module has no DB/network/session engine; canonical identity is supplied by trusted envelope.",
      "Signed platform IDs are separate from unsigned user/bot identity validation.",
      "One physical escaped transcript record per logical reply preserves existing line-based budget/replay contract.",
      "Stable prompt instructions before dynamic data preserve cache prefix; existing compaction gate/CAS stays unchanged."
    ],
    "files_to_modify": [
      {
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "symbols": [
          "_extract_message_relations",
          "_record_bot_lines"
        ],
        "intended_change": "Preserve original relations and signed acknowledged IDs; do not change delivery trust or duplicate callback ingestion."
      },
      {
        "file": "memory/pre_processors.py",
        "symbols": [
          "resolve_reply_target",
          "_query_tail_rows_with_relations",
          "_render_tail_line",
          "_fetch_recent_tail"
        ],
        "intended_change": "Scoped signed lookup, explicit author/recipient projection and full rendered cost."
      },
      {
        "file": "memory/conversation_identity.py",
        "symbols": [
          "_bot_bubble_recipient",
          "resolve_correction_target"
        ],
        "intended_change": "Canonical guarded signed lookup and correct Bot-author branch."
      },
      {
        "file": "memory/prompt_builder.py",
        "symbols": [
          "build_v2_named_sections"
        ],
        "intended_change": "Protected concise author/recipient/current-sender and factual-state rules."
      },
      {
        "file": "memory/session_compact.py",
        "symbols": [
          "fetch_pending_messages",
          "build_compact_prompt",
          "COMPACT_PROMPT"
        ],
        "intended_change": "Shared role projection and factuality rules; preserve raw row watermarks and guarded lifecycle."
      },
      {
        "file": "memory/conversation_projection.py",
        "symbols": [],
        "intended_change": "PLANNED/ABSENT: pure platform-ID parser and typed escaped transcript projection; final symbol names decided during implementation."
      },
      {
        "file": "scripts/evaluate_dialogue_attribution.py",
        "symbols": [],
        "intended_change": "PLANNED/ABSENT: isolated actual-model evaluation with wire inputs, runtime parameters, output capture and human semantic review."
      },
      {
        "file": "tests/test_conversation_projection.py",
        "symbols": [],
        "intended_change": "PLANNED/ABSENT: typed-envelope, escaping, grouping conflict, recipient unknown and physical-line tests."
      }
    ],
    "tests": [
      {
        "file": "tests/test_message_relations.py",
        "scenarios": [
          "Production adapter sanitized event retains original reply and non-Bot mentions.",
          "Signed IDs through acknowledged delivery and lookup; legacy origin-less path.",
          "Failed/unknown segments excluded; private, passive and proactive callers covered."
        ]
      },
      {
        "file": "tests/test_conversation_identity.py",
        "scenarios": [
          "Reply to Bot with resolved author Bot -> confirmed recipient candidate.",
          "Cross-conversation/bot and duplicate/invalid references -> unknown.",
          "Unique non-Bot @ priority and human correction evidence preserved."
        ]
      },
      {
        "file": "tests/test_context_tail.py",
        "scenarios": [
          "Full logical single-line replies, actual part indexes and origin IDs.",
          "Legacy schema fallback, unknown recipient, original tail_start_id.",
          "Render cost includes labels, IDs and escaping."
        ]
      },
      {
        "file": "tests/test_structured_conversation_budget.py",
        "scenarios": [
          "History record retained or dropped atomically under 8K budget.",
          "Protected identity and current input remain.",
          "Old v1/v2 frozen strings replay without DB re-render."
        ]
      },
      {
        "file": "tests/test_session_compact.py",
        "scenarios": [
          "Original low/high exclusion, raw-row limit/count/max with empty rows.",
          "Batch-split logical replies self-contained without out-of-bound reads.",
          "Author/recipient/state contract plus reset/identity revision prevents stale application."
        ]
      },
      {
        "file": "tests/test_prompt_cache_prefix.py",
        "scenarios": [
          "Stable instructions before dynamic body, existing anti-fabrication and own-speech constraints retained."
        ]
      },
      {
        "file": "tests/test_conversation_projection.py",
        "scenarios": [
          "PLANNED: body newline/quote/header injection safely escaped.",
          "PLANNED: inconsistent metadata not silently merged; no inferred counts/recipient."
        ]
      }
    ],
    "verification_commands": [
      "BASELINE EXECUTED: python -m pytest tests/test_message_relations.py tests/test_conversation_identity.py tests/test_structured_conversation_budget.py tests/test_session_compact.py -q -> 87 passed, 55 existing warnings.",
      "IMPLEMENTATION: python -m pytest tests/test_message_relations.py tests/test_conversation_identity.py tests/test_structured_conversation_budget.py tests/test_session_compact.py tests/test_context_tail.py tests/test_prompt_cache_prefix.py -q; add planned projection suite after creating it.",
      "IMPLEMENTATION: python -m pytest tests/ -q -n auto --dist loadgroup",
      "IMPLEMENTATION: python -m ruff check .",
      "BEFORE EACH SYMBOL EDIT: Docker GitNexus upstream impact depth 3; report HIGH/CRITICAL and resolve UNKNOWN with source/runtime evidence.",
      "BEFORE EACH COMMIT: docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project; partial/truncated is unresolved."
    ],
    "risks": [
      "Receipt recording and compaction fetch/template are CRITICAL; use separate gated phases.",
      "Model attribution improvement remains inferred until actual V0/V1/V2 comparison and 80-sample semantic evaluation.",
      "More explicit metadata uses tokens; count full rendering and measure preprocess p95 delta <=20 ms.",
      "Old msg_id=0 cannot be recovered from current records; preserve unknown rather than guessed backfill.",
      "Native structured roles or multiline budget units would invalidate narrow compatibility scope and require replanning.",
      "No complete graph claim: dynamic dispatch and PDG depth limits remain."
    ],
    "assumptions": [
      "Reverify installed OneBot adapter 2.4.6 and original_message semantics at implementation time.",
      "Freeze runtime wire parameters, not presumed historical .env values; record unavailable seed/hash honestly.",
      "Single physical escaped record keeps budget v2 algorithm unchanged; use existing new-process lifecycle to clear ephemeral summaries/cache.",
      "Model evaluations are isolated from QQ and production storage."
    ],
    "open_questions": [
      "Can V2 satisfy actual model semantic gates at current production parameters? Not yet measured.",
      "If V2 fails, independently test provider-neutral structured messages or model/quantization alternatives.",
      "M0 must capture complete actual prompt/system/decoding context, not merely the twenty visible messages.",
      "M6 real QQ multi-user window requires operator coordination during implementation; not executed by this planning task."
    ],
    "avoid": [
      "No second identity LLM per normal turn.",
      "No per-user isolated group history or parallel runtime engine.",
      "No schema17, long-term memory purge, production DB backfill or invented state/event parser.",
      "No automatic model download, quantization swap, bot restart or QQ test messages.",
      "Do not treat baseline unit tests or isolated AST probes as proof of model repair.",
      "Do not modify budget v2/replay/backend string contract silently."
    ]
  }
}
```

## 12. Assumptions and Open Questions

- [assumed] 部署时仍为该OneBot adapter版本及original_message/deepcopy语义；实施者复核生产conda包版本，并以真实清洗后事件测试，不只传人工ChatContext。
- [assumed] frozen评估能获得实际模型参数与固定端点；缺少seed或模型文件hash时如实记录“不支持/不可取得”，不虚称完全可复现。当前.env声明不是过去wire记录。
- [inferred] 明确作者/完整逻辑行与角色/状态规则能降低本模型错误，但尚未对V1/V2调用真实模型；M5失败就不能发布“已解决”。
- [verified] 新投影/评估/测试模块路径当前不存在；本轮只写计划。模型oracle需人工复核，不能用假后端通过来证明真实语义能力。
- [verified] 旧msg_id0和过滤掉的一字泡缺少完整平台证据；不新增message_sent反向写入、不自动生产补全。将“零平台ID历史引用恢复”作为明确deferred数据修复项。
- [inferred] 当前修复的identity纠正适配存在Bot分支优先级问题；计划修改仅覆盖既有明确引用纠正，不扩展复杂汉语第三人实体解析。
- [assumed] 新renderer使用一个物理行可维持budget v2；若实施时改成多行/原生roles/结构化event JSON，必须route-back重写接口、预算与回放方案。
- [verified] 全量历史排序、群多Bot历史隔离、长期记忆事实审核、social/consolidation整个所有prompt不是本轮重构范围；本轮仅修声明来源边界和实时/会话压缩投影。
- 原生roles与换模型/量化作为仅在M5失败后启用的后续实验；不提前安装、更换端点或增加每轮身份模型调用。

## 13. Definition of Done

1. 原始引用和mentions在适配器清洗后仍保留；signed message ID在回执→库→引用/纠正链路一致；0/非法/跨scope仍unknown。
2. 当前sender/历史author/recipient互不改写；Bot引用纠正落到可信候选，不给Bot或纠正者错误授名。
3. 多气泡历史逻辑单元在预算后无孤立后续泡；正文伪造标签不改变可信信封；元数据在成本计算内，context8192边界保持。
4. 压缩前后作者/对象可追溯；条件/否定/转述不升级事件；max/count/空消息/CAS回归全部通过。
5. 实际模型80次矩阵speaker/recipient/action/state关键错误0/80，原任务完成≥72/80；真实原复现包含在矩阵，人工复核结果留档。未达标不可宣称修好。
6. 定向与全量测试、ruff、manifest（若需一次性再生）和commit前GitNexus门禁通过；0 partial/truncated图变更检查。
7. preprocess p95增量≤20ms（按固定夹具实测），无每轮额外身份LLM，用户正常回复不泄露内部记录ID。
8. 一个群真实双号/第三人灰度经过操作者协调并留下平台输出/DB关系证据，确认无新串人后再扩展。离线结果不替代真实灰度。

本轮交付为分析与可执行方案；已执行的是87项基线和隔离机制探针，以上修复、模型采样和灰度均未执行。


