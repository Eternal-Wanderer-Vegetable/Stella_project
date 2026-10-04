# 多人群聊身份混淆排查

日期：2026-10-04（Asia/Shanghai）。状态：排查完成，未实施修复。

## 结论

找到与实测描述一致的真实实例，并通过 `memory_traces.final_ids` 与记忆表关联确认：**回复 B 时注入了 A 的三条称呼记忆；数据库仍正确标注 A 的 user_id，但 prompt 渲染省略了归属。**

多人共用历史本身符合群聊需求；问题在于当前用户、被谈论的人、Bot 回复对象、记忆主体没有在送给模型的上下文里完整保留。第三人纠正后仍走普通文本对话，原错误回复与多个称呼版本继续占据背景，因此会出现持续串人和身份漂移。

另发现确定性的独立错误：群聊的个人记忆 scope 用 `ctx.peer_id`（群号）构造，应该代表当前用户的个人分支实际指向群号。它会漏掉当前用户的 USER_SHARED 个人记忆；不能单独解释 A/B 交换。

## 调查基线与边界

- 工作区：`E:\stella\stella_project`；分支：`feat/qq-private-personal-memory`；HEAD：`038e419da0c60ada84ae91dee7f11a5ece12aec0`。
- 使用 Docker 容器 `stella-gitnexus`，`/repo` 挂载当前工作区，CLI 1.6.11。先 `list` 绑定仓库；后续查询显式使用 `--repo Stella_project`。
- 原索引为旧分支 `0600226`。最终以 `analyze --index-only --pdg` 刷新，保留原 PDG 模式；status 确认 indexed/current commit 均为 `038e419`，927 个覆盖文件匹配，up-to-date。
- 执行概念 query、符号 context、调用 trace，再用源码和真实日志交叉核查。索引存在入口/深度/分支预算截断及动态调用缺边，未将空调用者或缺失执行流视为不存在。
- 实际证据来自 `StellaData/logs/stella_thought_logs.md` 和以 `mode=ro` 打开的 `StellaData/memory/agent_memory.db`。数据库时间是 UTC，下文已转换为 Asia/Shanghai。日志记录模型为 `qwen3.8-flash-next-iq2_xs`。
- 历史日志没有提交号，不能证明测试进程加载了当前 HEAD 的每一处代码；日志里的输入/输出与数据库归属是直接证据，当前源码与离线探针则独立证实组装机制。
- 没有修改业务代码、配置、生产数据库，没有发送 QQ 消息、调用生成模型或启动/停止机器人。只新增本报告并刷新 GitNexus 索引。探针使用进程内数据库及临时 STELLA_HOME。

## 实际实例：B 被叫成 A

为减少无关个人信息，以下只列身份问题相关的两位成员：

| 标记 | 平台 user_id | 记录中的称呼 |
|---|---|---|
| A | `2873089182` | Allets / allest；此前使用 STellA |
| B | `3883589893` | 阿呆 |

2026-10-03 22:28:58，B 输入“阿呆是我”。日志第 52625 行开始的完整 prompt：

```text
当前与你对话的用户 QQ 号：3883589893。
对话摘要: 用户2873089182改名Allets
...
用户(3883589893): 阿呆是我

可参考的聊天背景：
- 希望被称呼为 Allets（此前曾要求称呼为 STellA，但随后主动更改为 Allets）
- 偏好被称呼为 Allets
- 希望被称呼为STellA（注意大小写格式），或者改名为Allets

【现在 用户(3883589893) 对你说】阿呆是我
```

实际回复同时说“阿呆是你呀”与“Allets大人”。模型接收到了正确的当前 QQ 号，仍被没有归属的称呼背景误导。

数据库 `memory_traces.id=982`，UTC 时间 `2026-10-03 14:28:58`，目标 user_id 为 B。其 final_ids 关联结果：

| final memory id | memories.user_id | 内容 |
|---|---|---|
| `55c2ce467c34407fb5e4c70c3ab3f81f` | A | 希望被称呼为 Allets，之前为 STellA |
| `067ff4768acc40e1bf3deeefe1565a82` | A | 偏好被称呼为 Allets |
| `3354cf7dcd324dba8ec004f98b662827` | A | 希望被称呼为 STellA，或者改名为 Allets |

这三条都是 `owner_type=SPACE, owner_key=space:space_1`。**此实例的数据库记忆主体没有串写；串人发生在召回与渲染之后。**

22:29:32，A 纠正“我才是allest”；22:34:58，A 的 prompt 却同时含“Allets”和 B 的“阿呆”偏好，Stella 又说“不过叫我Allets嘛”。身份混淆已经扩大到用户与 Bot 自身。

## 原因与证据等级

### 1. 同空间其他成员记忆进入当前回复，渲染又丢掉主体：已确认，首要原因

路径由图查询确认：

```text
build_user_context → _build_user_context_v2
  → retrieve_memories → _fetch_candidates
prepare_turn → build_v2_prompt_context → build_conversation_section
```

- `memory/retrieval_v2.py:162`：有 scope 时使用 owner 谓词；只有无 scope 的另一分支才追加 `m.user_id = 当前用户`。
- `memory/ownership.py:174` 的 `owner_scope_sql`：SPACE 分支允许当前空间的记忆，不限主体；PERSON 分支另外按 owner、subject、audience 限制。授权可见性与“这条事实属于谁”是不同问题。
- `memory/retrieval_v2.py:89`：返回 dict 仍保留 `user_id`，因此这里尚未丢失归属。
- `memory/prompt_builder.py:175`：聊天素材只渲染 `- {content}`，省略 `user_id`。诸如“希望被称呼为 Allets”于是看起来像当前用户的偏好。
- `memory/prompt_builder.py:251` 虽有“只有明确写着当前用户才归 TA”的提示，下面偏好文本却没有标识是谁；模型必须自行猜测。真实记录已证明提示不能消除这一矛盾。

只允许当前用户记忆的旧行为在有 scope 后扩大成空间背景召回，渲染仍沿用省略主体的形式；组合后直接产生此次缺陷。允许参考他人公开记忆可以保留，但必须保留主体并区分当前用户事实与第三方背景。

### 2. Bot 历史回复不标对象，引用关系没有接入主 prompt：已确认，重要放大因素

- `ai_gateway.py:928`：当前 ctx.user_id 直接取事件 sender，未从聊天文本猜人。
- `ai_gateway.py:917`：当前 message 使用 plaintext。事件本身仍在 raw_event 中；这不等于引用/@关系被渲染进模型输入。
- `memory/pre_processors.py:371`：尾巴只查 id、user_id、content、source_kind、timestamp。
- `memory/pre_processors.py:345`：历史用户消息渲染为 `用户(uid): ...`，Bot 发言渲染为 `我: ...`，没有“回复给谁/引用哪条消息”。
- `ai_gateway.py:2537`：每个 Bot 气泡单独落库，msg_id 为 0；该短期表没有保留当前回复的目标用户、源消息或发送回执 ID。
- `ai_gateway.py:748` 已提取引用/@，在开启 social delivery 时写入规范化旁表，并供参与评分使用。主聊天的尾巴查询没有消费这些关系；不能说全项目没有关系数据。

对应真实记录：21:43:17 Stella 对成员 R 说“红中叔呀 / 笨蛋骑士”；21:44:46 另一成员 C 问“我是谁”，Stella 把最近的“笨蛋骑士”套给 C（日志第 50357、50453 行）。21:37:48，A 转述“红中是让你自己想叫啥就叫啥”，Stella 回“以后就叫你红中哥”，把转述者与被谈论的人混为一人（第 49860 行）。

### 3. 纠正没有形成明确身份更新，旧称呼与错误回复继续参与下一轮：已确认存在，因果放大有日志支持

- 昵称/称呼在显式偏好表、自由文本长期记忆、摘要、短期 Bot 台词中同时出现。
- 只读快照中 A 的显式 `user_address_preferences` 仍是 9 月 26 日保存的“Stella”；长期记忆已记录 Allets。B 的阿呆偏好也存在长期记忆中。这些不是统一的身份/别名记录。
- `memory/addressing_intent.py:226` 的预筛选在语义分类前执行。隔离探针中，“那我改名叫Allets”“阿呆是我”“我才是allest”均为 `prefilter_miss`，不会调用显式称呼配置路径；“以后叫我Allets”才匹配 SET_SELF_ADDRESS。
- 改名、自我介绍与身份纠正不必全部当作称呼配置命令；但当前缺少独立的、按真实主体处理这些事实并处理冲突的路径。
- 错误回复作为 BOT_SELF 被真实落库，并继续出现在尾巴与压缩摘要中。保留“Bot 说过什么”合理，但它不能自动升级为用户身份事实。

日志第 52196 行中第三人询问“这对吗”，Stella 又说“你才是那个红中”；第 53071 行中多人的纠正已进入背景，Stella 仍自称 Allets。纠正被当作普通接话，未可靠重建身份关系。

### 4. 群号误作当前用户的个人 scope：确定性代码错误，独立于上面的无归属召回

- `ai_gateway.py:937`：group 会话的 `peer_id` 是群号；当前 sender 在 `ctx.user_id`。
- `memory/pre_processors.py:566` 和 `core/planner.py:311`：均向 `scope_for_conversation` 传 `ctx.peer_id or ctx.user_id`。
- 群 peer_id 非空，因此个人 owner 变成 `person:qq:<bot>:<群号>`，subject 变成 `qq:<群号>`。

作用：当前用户的 USER_SHARED 个人事实无法正常进入这个分支，而 SPACE 记忆仍可能进入。私聊 peer_id 本来等于当前用户，不能用私聊通过来证明群路径正确。修复时需按 conversation kind 与真实 sender 区分会话地址和用户主体。

### 5. 尾巴容量与最终裁剪会丢身份线索：已复现机制，本次关键实例并非由裁掉当前 ID 导致

- 默认 `RECENT_TAIL_LIMIT=12`（config/settings.py:347），按数据库行计数；三气泡回复占三行。只要多人频繁插话或多段输出，就更容易把先前的人名/身份声明挤出原文窗口。
- `core/context_budget.py:49`：超预算时保存当前输入，背景只取尾部，不把身份/称呼区当成受保护段。
- `memory/prompt_builder.py:251`：身份/称呼在背景头部，正好容易被兜底裁剪删除。
- 压缩摘要是自然语言、默认目标约 200 中文字（300 tokens / 1.5）；模板要求保留谁说过什么，但没有结构化参与者/回复目标验证。

关键错误轮次保留了当前 QQ 号，故不能将它诊断成“只有上下文不足”。裁剪与摘要是额外风险，需要独立覆盖。

### 6. 模型与人格提示对不确定身份的处理：有输出表现，尚未做模型对照

真实输出反复用“嘴瓢”“别纠结”解释错误，或继续猜称呼。默认人格文本强调嘴硬、接梗和熟人聊天；它可能让身份纠正退化成玩笑互动。完整历史被拼为一个 user message，而不是有结构化主体与回复关系的消息序列（core/llm/lm_studio.py:118）。

没有比较其他模型、量化或采样设置，不能断言 IQ2_XS 是根因，亦不能宣称换模型即可修好。现有实例先暴露了明确的检索/归属问题。

## 隔离验证

用当前真实函数、合成 A=2001 / B=2002 / 群=7777 / Bot=10000 验证；不调用 LLM。

| 探针 | 结果 |
|---|---|
| `_fetch_candidates` 无 scope，当前 B | 只返回 B 的 SPACE 记忆 |
| 同函数，正确 group scope | 返回 A/B 的 SPACE 记忆与 B 的 USER_SHARED PERSON 记忆 |
| 同函数，当前群入口生成的 scope | 返回 A/B 的 SPACE 记忆，漏掉 B 的 PERSON 记忆 |
| `build_conversation_section` | 同时输出“希望被称呼为 Allets”和“希望被称呼为 阿呆”，没有任何 user_id |
| `_build_user_context_v2`，替换检索为捕获参数的桩 | requested user=2002，但 person_owner=`person:qq:10000:7777`，subject=`qq:7777` |
| 超预算的真实 compose/fit 组合 | 当前输入标签保留，头部当前身份与称呼偏好均被裁掉 |
| 12 行原始尾巴 | 11 个 Bot 气泡 + B 新消息使 A 身份声明掉出原文窗口 |
| 称呼分类预筛选 | 三种自我介绍/纠正句均 prefilter_miss；明确“以后叫我Allets”可匹配 |

现有测试：

```text
python -m pytest tests/test_context_tail.py tests/test_prompt_builder_v2.py \
  tests/test_context_budget.py tests/test_personal_memory_scope.py tests/test_addressing.py -q
49 passed, 1 warning
```

这些测试验证各模块的既有约束，未覆盖“群入口生成 scope → 召回他人称呼 → 渲染丢主体 → 多人纠正”的完整链。个人 scope 测试直接传入正确用户，不会发现入口把 peer_id 当 user_id。

## 建议的后续修复顺序（尚未实施）

1. **P0：修复群 scope 主体参数；保留注入记忆的 user_id。** 将当前用户事实与他人公开背景显式分区，给第三方称呼标明主体。退出条件：B 的 USER_SHARED 可以命中；A 的称呼只能作为 A 的背景出现，不能变成 B 的称呼。
2. **P0：补齐对话关系。** 当前输入保留 sender、引用消息与被提及对象；Bot 历史保留回复目标和源消息。退出条件：C 纠正 A/B 时，C 不会继承被纠正者的身份。
3. **P1：明确身份事实、称呼偏好与纠正的关系。** 自我介绍、改名、第三人转述、Bot 猜测使用不同证据权限；冲突时询问明确主体，错误 Bot 台词不能覆盖真实主体事实。保留正常群聊共享，不能仅靠按用户分割全部群历史回避问题。
4. **P1：保护身份与关系信息的预算，按完整逻辑消息保留最近对话。** 将身份段纳入保护区，裁背景时按消息/主体完整边界裁，摘要保留可验证的参与者和归属。
5. 在上述输入修正后，再用同一冻结案例比较模型/量化/采样设置；不要把模型更换当成已验证修复。

验收至少覆盖：A 连续说话→B 插话；C 为 A 纠正；用户与 Bot 同名；两个成员同昵称；引用 A 的旧消息；A 三气泡回复后 B 发短句；超预算；摘要存在；同空间其他成员称呼记忆可见；私聊及跨空间个人记忆回归。
