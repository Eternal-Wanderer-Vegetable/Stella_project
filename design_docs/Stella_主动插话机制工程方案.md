# Stella 主动插话机制工程方案

> 状态：架构设计阶段  
> 目标：在不明显增加 LLM 调用量的前提下，让 Stella 能够自然判断“什么时候应该插话”。  
> 核心原则：**先决定是否说话，再决定说什么。**

---

## 1. 背景与问题定义

目前 Stella 的语言生成能力已经能够在“已经进入话题”的情况下产生较自然的群聊语言。

当前真正的问题不是：

> “Stella 应该怎么说得更像人？”

而是：

> “Stella 什么时候应该主动说话？”

因此，本阶段暂不大幅修改 Stella System Prompt，而是建立一个独立于 LLM 的**主动参与决策层（Participation Decision Layer）**。

该机制必须解决以下问题：

1. 群友正在讨论什么？
2. Stella 与当前话题有没有关系？
3. 当前有没有适合 Stella 插话的机会？
4. 群聊是不是正处于高速消息流？
5. Stella 最近是不是已经说过很多话？
6. 这个话题是否已经结束？
7. 即使 Stella 对话题感兴趣，现在是否仍然应该保持沉默？

最终形成三个相互独立的问题：

```text
Should I speak?
    ↓
Participation Scorer

What should I know?
    ↓
Context Selector

What should I say?
    ↓
LLM
```

本方案只负责第一个问题。

---

# 2. 总体架构

```text
QQ Message
    │
    ▼
┌──────────────────────┐
│ Hard Trigger Layer   │
│ @Stella / 回复Stella │
│ 直接对话等            │
└──────────┬───────────┘
           │
           │ 非强制触发时
           ▼
┌──────────────────────┐
│ Message Buffer       │
│ 短期消息缓冲区        │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ Conversation State   │
│ 当前话题状态          │
│ 参与者/速度/活跃度等  │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ Participation Scorer │
│ 主动参与评分          │
└──────────┬───────────┘
           │
      ┌────┴────┐
      │         │
   不说话      候选参与
      │         │
      ▼         ▼
   Ignore   Context Selector
                  │
                  ▼
                 LLM
                  │
                  ▼
               Stella
```

其中：

- Hard Trigger：判断是否存在必须响应的情况。
- Message Buffer：保存近期原始消息。
- Conversation State：把原始消息转换为低成本的群聊状态。
- Participation Scorer：决定 Stella 是否应该主动插话。
- Context Selector：只在决定说话之后选择真正需要交给 LLM 的上下文。
- LLM：负责自然语言表达。

---

# 3. Hard Trigger 与主动插话必须分离

这是整个机制的第一条工程原则。

## 3.1 强制响应

以下情况不应该经过普通主动插话评分：

- 群友明确 @ Stella
- 群友直接回复 Stella
- Stella 正在参与的对话明确向她提出问题
- 系统内部要求 Stella 继续当前对话

这些属于：

```text
Forced Participation
```

直接进入：

```text
Context Selector → LLM
```

---

## 3.2 主动插话

例如：

```text
A：我刚刚打游戏遇到一个特别离谱的队友
B：咋了
A：他居然……
```

Stella 没有被 @，也没有被直接询问。

这时才进入：

```text
Passive Observation
    ↓
Participation Scoring
```

因此：

```text
Hard Trigger ≠ Participation Score
```

二者必须保持独立。

---

# 4. Message Buffer

Message Buffer 是最底层的短期观察区。

它不负责理解“意义”，只负责保存最近发生的事情。

建议每条消息保存：

```text
Message
├── timestamp
├── sender_id
├── text
├── reply_to
├── mentioned_users
├── has_image
├── has_emoji
├── message_type
└── embedding
```

其中：

- `timestamp`：用于时间连续性。
- `sender_id`：用于参与者分析。
- `text`：原始文本。
- `reply_to`：用于判断回复关系。
- `mentioned_users`：识别社交邀请。
- `message_type`：区分普通文本、图片、表情等。
- `embedding`：用于语义相关性和话题连续性判断。

Message Buffer 只保存短期数据，不承担长期记忆功能。

---

# 5. Conversation State

主动插话判断不应该每次都重新阅读大量聊天记录。

因此需要维护一个轻量的：

```text
Conversation State
```

示例：

```text
Current Topic:
    Helldivers 2 游戏体验

Topic Status:
    ACTIVE

Topic Started:
    12:31:04

Last Active:
    12:33:17

Participants:
    A, B, C

Message Velocity:
    MEDIUM

Stella Relevance:
    0.87

Stella Involved:
    FALSE
```

Conversation State 是“群聊当前状态”，不是聊天记录摘要。

---

# 6. Topic State Machine

每个话题采用简单生命周期：

```text
NEW
 ↓
ACTIVE
 ↓
COOLING
 ↓
EXPIRED
```

## 6.1 NEW

刚刚出现的新话题。

例如：

```text
A：你们有人玩新出的那个游戏吗？
```

此时建立新的 Topic。

---

## 6.2 ACTIVE

近期持续有消息围绕该话题产生。

例如：

```text
A：有人玩那个游戏吗？
B：玩过
C：我也玩了
B：你觉得怎么样
A：我觉得还行
```

Topic 保持 ACTIVE。

---

## 6.3 COOLING

消息开始减少，但尚不能确定话题已经结束。

此时 Stella 不应该主动强行把话题重新拉起来。

---

## 6.4 EXPIRED

超过一定时间没有有效延续，或者群聊已经明显转向其他话题。

EXPIRED 后：

- 不允许该 Topic 直接触发主动插话。
- 如果后来出现相关消息，应创建新的 Topic 或重新建立关联。

这样可以避免：

> “群里十分钟前聊过这个，Stella 突然现在接上一句。”

---

# 7. 参与评分模型

核心指标：

```text
Participation Score
=
Relevance
+ Opportunity
+ SocialOpportunity
+ TopicInvolvement
+ SilenceBonus
- RecentSpeechPenalty
- MessageVelocityPenalty
- RepetitionPenalty
- TopicExpiredPenalty
```

建议第一版使用 0～100 左右的最终分数。

评分不应该被理解为严格的概率，而应该理解为：

> “当前这一刻，Stella 插话是否自然？”

---

# 8. Relevance：Stella 对话题的相关性

建议分为两种：

```text
Long-Term Relevance
Current Relevance
```

## 8.1 Long-Term Relevance

来自 Stella 的长期兴趣。

例如：

- 游戏
- AI
- 编程
- Rust
- NoneBot
- Agent

这些可以长期保持较高相关性。

---

## 8.2 Current Relevance

来自 Stella 最近正在关注的事情。

例如 Stella 刚刚参与过某个游戏讨论，那么短时间内这个话题的 Current Relevance 可以提高。

---

## 8.3 Embedding

可以使用现有的：

```text
text-embedding-qwen3-embedding-0.6b
```

作为本地语义判断模型。

Embedding 的职责只是：

```text
“这个话题和 Stella 有多相关？”
```

而不是：

```text
“Stella 应不应该说话？”
```

因此：

```text
Embedding ≠ Decision Maker
```

Embedding 只提供评分依据。

---

# 9. Opportunity：插话机会

这是整个系统最重要的指标之一。

“Stella 感兴趣”并不代表“现在适合说”。

例如：

```text
A：我最近开始玩 XX
B：我也玩
C：+1
D：我也是
```

Stella 非常感兴趣。

但是：

```text
Opportunity ≈ 低
```

因为群聊已经完成了一轮快速回应。

反过来：

```text
A：有人玩这个吗？
```

则：

```text
Opportunity ≈ 高
```

因为这里存在明显的社交空位。

---

# 10. Opportunity 的主要信号

## 10.1 开放问题

例如：

```text
有人玩过这个吗？
你们觉得怎么样？
有人知道这是怎么回事吗？
```

高 Opportunity。

---

## 10.2 未完成表达

例如：

```text
A：我昨天遇到一个特别离谱的事情
B：？
A：就是……
```

高 Opportunity。

---

## 10.3 已经被充分回答

例如：

```text
A：这个怎么设置？
B：点这里
A：哦懂了
```

低 Opportunity。

---

## 10.4 高速消息流

例如短时间：

```text
A：哈哈
B：哈哈哈哈
C：笑死
D：真的
E：草
F：哈哈哈哈
```

即使 Stella 对这个话题有兴趣，也应该降低主动插话概率。

注意：

> 高消息速度应该降低评分，而不是直接禁止 Stella 发言。

因为真实的人类也会在高速聊天中突然插一句。

---

# 11. SocialOpportunity：社交机会

有些话题和 Stella 本身没有关系，但仍然非常适合插话。

例如：

```text
A：我刚刚干了一件特别蠢的事情
```

这时候 Stella 不一定关心具体主题，但存在明显的：

```text
Social Hook
```

可以自然地问：

```text
你又干嘛了
```

因此需要独立计算：

```text
SocialOpportunity
```

建议：

```text
直接邀请      +20
明显悬念      +15
强烈情绪      +10
普通陈述        0
已经充分回应   -10
```

---

# 12. TopicInvolvement：当前参与状态

人类更容易继续自己已经参与的对话。

因此：

```text
Stella Involved = TRUE
```

时，应当提高继续参与当前 Topic 的倾向。

例如：

```text
A：这个游戏挺好玩的
Stella：我也觉得
B：但是后期有点肝
```

此时 Stella 比完全没有参与过时更容易继续接话。

这是：

```text
Continuation
```

而不是：

```text
Proactive Insertion
```

工程上应该允许二者共享评分机制，但保留不同 Participation Mode。

---

# 13. SilenceBonus：沉默奖励

如果 Stella 很久没有主动参与，应该逐渐提高她再次参与的可能性。

例如：

```text
last_spoke_at = 10:00
current_time = 10:05
```

比：

```text
last_spoke_at = 10:04:30
current_time = 10:05
```

更适合主动插话。

可以设计为随时间增长、最终封顶：

```text
SilenceBonus = min(max_bonus, elapsed / growth_time)
```

但它只能作为辅助因素。

不能出现：

> “因为 Stella 很久没说话，所以无论群里聊什么都要插一句。”

---

# 14. RecentSpeechPenalty：近期发言惩罚

这是防止“机器人抢话”的核心机制。

需要维护：

```text
last_spoke_at
recent_spoke_count
recent_proactive_count
current_topic_spoke_count
```

例如：

```text
刚刚说过 → 强惩罚
连续主动发言 → 更强惩罚
当前 Topic 连续插话 → 进一步惩罚
```

特别要区分：

```text
被叫到后回答
```

和：

```text
主动插话
```

因为被 @ 后回复并不应该导致 Stella 获得“我已经主动说很多话”的同等惩罚。

---

# 15. RepetitionPenalty：重复参与惩罚

例如：

```text
Stella：这个真的好玩
A：对
Stella：我也觉得挺好玩的
B：确实
Stella：而且画面也不错
```

即使每句话单独看都合理，整体仍然非常像机器人。

因此需要记录：

```text
Stella 在当前 Topic 已经主动参与多少次
```

如果没有新的对话机会：

```text
RepetitionPenalty ↑
```

---

# 16. TopicExpiredPenalty

如果 Topic 已经进入：

```text
COOLING
```

或：

```text
EXPIRED
```

则主动参与分数应该显著下降。

尤其禁止这种行为：

```text
群聊：
A：今天吃什么
B：不知道
C：随便
（沉寂十分钟）

Stella：
我觉得火锅不错
```

这种情况从语言模型角度完全可以生成合理句子，但从群聊行为角度非常不自然。

---

# 17. 第一版评分范围

第一版不需要追求数学上的精确。

建议先使用：

| 指标 | 范围 |
|---|---:|
| Relevance | 0～30 |
| Opportunity | -20～30 |
| SocialOpportunity | 0～20 |
| TopicInvolvement | 0～20 |
| SilenceBonus | 0～10 |
| RecentSpeechPenalty | 0～60 |
| MessageVelocityPenalty | 0～30 |
| RepetitionPenalty | 0～20 |
| TopicExpiredPenalty | 0～40 |

最终：

```text
Score =
所有正向因素之和
-
所有负向因素之和
```

---

# 18. 阈值机制

建议第一版不要直接使用：

```text
Score > 50 → 说话
```

而采用多级状态：

```text
< 30
    IGNORE

30～59
    OBSERVE

60～79
    CANDIDATE

80+
    ALLOW_LLM
```

含义：

### IGNORE

当前明显不适合插话。

### OBSERVE

有一定机会，但继续观察。

### CANDIDATE

已经存在比较明确的插话机会，但可以等待下一条消息确认。

### ALLOW_LLM

认为现在值得让 LLM 生成一次回复。

---

# 19. Candidate 状态的重要性

建议不要：

```text
某一条消息 Score = 80
→ 立即调用 LLM
```

而采用：

```text
Score >= 60
    ↓
Candidate
    ↓
观察下一条消息
    ↓
机会继续存在？
    ├─ 否 → Cancel
    └─ 是 → Score 再计算
              ↓
          >= threshold
              ↓
          LLM
```

这样可以显著减少：

> “看到一句话就突然抢话”

的情况。

但对于非常明显的社交钩子，可以允许直接进入 ALLOW_LLM。

---

# 20. Participation Mode

Participation Score 只回答：

> “现在该不该说？”

还需要一个结构化字段回答：

> “为什么现在说？”

因此引入：

```text
ParticipationMode
```

第一版建议至少包含：

```text
DIRECT_MENTION
DIRECT_RELEVANCE
CONTINUE_EXISTING_CONVERSATION
TOPIC_INTEREST
SOCIAL_HOOK
```

示例：

```text
“Stella，你不是也玩这个吗？”

→ DIRECT_MENTION
```

```text
“有人知道 Rust 这个报错怎么回事吗？”

→ TOPIC_INTEREST
```

```text
“我刚刚干了一件特别蠢的事情……”

→ SOCIAL_HOOK
```

```text
Stella 刚刚参与了某个游戏讨论，
群友继续讨论该游戏。

→ CONTINUE_EXISTING_CONVERSATION
```

Participation Mode 不负责生成文本。

它只是给后面的 Context Selector 和 LLM 一个：

```text
“为什么现在轮到 Stella 说话？”
```

---

# 21. 建议的最终 Decision Object

主动参与层最终可以输出类似：

```text
ParticipationDecision

├── should_speak
├── score
├── mode
├── topic_id
├── trigger_message_id
├── confidence
└── reason_flags
```

例如：

```text
should_speak: true

score: 84

mode:
    SOCIAL_HOOK

topic_id:
    1837

trigger_message_id:
    98231

confidence:
    0.82

reason_flags:
    - strong_social_hook
    - low_recent_activity
    - moderate_message_velocity
    - topic_active
```

这个对象随后交给：

```text
Context Selector
```

---

# 22. QQ 群聊特殊处理

QQ 群聊与普通即时通讯不同，因此评分层需要特别处理以下内容。

## 22.1 @

必须优先识别：

```text
@Stella
```

这是 Hard Trigger。

---

## 22.2 回复

如果 QQ 消息明确 reply 到 Stella 的消息：

```text
reply_to == Stella message
```

应视为强相关。

---

## 22.3 图片

图片本身不一定意味着需要 Stella 发言。

默认：

```text
图片 → 观察
```

只有当：

- 图片附带文字
- 图片明显回应当前话题
- Stella 有视觉处理能力
- 群友明确询问 Stella

才提升参与度。

---

## 22.4 表情包

单独的：

```text
哈哈
[表情]
[图片]
```

一般属于低信息量消息。

可以降低：

```text
Message Value
```

但不能简单视为噪声。

例如：

```text
A：我终于把 Bug 修好了
B：[狂喜表情]
```

它仍然说明：

```text
话题已经得到回应
```

所以结构信息仍然有价值。

---

# 23. 消息速度计算

建议维护一个滑动时间窗口，例如：

```text
最近 30 秒
```

计算：

```text
messages_per_second
```

再离散化：

```text
LOW
MEDIUM
HIGH
VERY_HIGH
```

第一版无需复杂预测。

目标只是回答：

> “现在是不是大家正在疯狂抢话？”

而不是预测聊天未来走势。

---

# 24. 不要让 Embedding 决定一切

这是一个重要的工程约束。

不能设计成：

```text
Embedding 相似度高
→ Stella 说话
```

因为：

```text
“感兴趣”
```

和：

```text
“适合插话”
```

是两个完全不同的问题。

例如：

```text
A：我最近在研究 Rust
```

Stella：

```text
Relevance = 高
Opportunity = 普通
SocialOpportunity = 低
```

最终：

```text
可能继续观察
```

而：

```text
A：有人知道 Rust 这个报错怎么解决吗？
```

则：

```text
Relevance = 高
Opportunity = 高
```

最终才适合参与。

---

# 25. 完整决策流程

最终第一版流程确定为：

```text
收到 QQ 消息
       │
       ▼
消息预处理
       │
       ▼
是否 Hard Trigger？
   ┌───┴───┐
   │       │
  Yes      No
   │       │
   ▼       ▼
直接响应   更新 Message Buffer
           │
           ▼
      更新 Conversation State
           │
           ▼
      Topic 是否有效？
       ┌───┴───┐
       │       │
      No      Yes
       │       │
       ▼       ▼
     Ignore  计算 Participation Score
                   │
                   ▼
             Score < 30？
               ┌───┴───┐
              Yes      No
               │        │
               ▼        ▼
             Ignore   Observe
                         │
                         ▼
                  Score >= 60？
                    ┌────┴────┐
                   No         Yes
                    │          │
                    ▼          ▼
                 Observe    Candidate
                                │
                                ▼
                         下一消息到来
                                │
                                ▼
                         重新计算 Score
                                │
                     ┌──────────┴──────────┐
                     │                     │
                  不再适合                仍然适合
                     │                     │
                     ▼                     ▼
                   Cancel              ALLOW_LLM
                                           │
                                           ▼
                                    Context Selector
                                           │
                                           ▼
                                          LLM
```

---

# 26. LLM 调用边界

一个非常重要的原则：

> **Participation Layer 尽可能完全不调用 LLM。**

以下任务均应尽可能由规则、状态机和 embedding 完成：

- 消息速度
- 最近发言次数
- Topic 生命周期
- Topic 连续性
- Stella 与 Topic 的相关性
- 是否存在明显社交钩子
- 最近是否已经主动发言
- 是否存在回复关系
- 是否存在 @

LLM 只在：

```text
Participation Decision
=
ALLOW_LLM
```

之后调用。

这样可以让大多数群聊消息：

```text
QQ消息
→ 本地计算
→ Ignore
```

而不是：

```text
QQ消息
→ LLM
→ “我是不是应该说话？”
```

---

# 27. 与 8192 Token Context 的关系

主动插话机制本身不应该把大量聊天记录交给 LLM。

它只产生：

```text
ParticipationDecision
```

随后 Context Selector 再决定真正需要给 LLM 的内容。

因此：

```text
8192 Token
```

不应该被理解为：

> “Stella 可以读取 8192 Token 的聊天记录。”

而应该理解为：

> “Stella 的整个一次思考过程总共拥有约 8192 Token 的工作空间。”

主动参与层的设计目的之一，就是尽可能在 LLM 之外完成筛选。

---

# 28. 第一版不实现的内容

为了避免系统过早复杂化，第一版明确不做：

- 不让 LLM 给 Participation Score 打分
- 不让 LLM 总结每条消息
- 不建立复杂的人格心理状态
- 不建立复杂的情绪模拟
- 不预测群聊未来走势
- 不使用大型分类模型
- 不把所有历史消息长期保存给决策层
- 不修改 Stella System Prompt 来弥补架构问题

第一版只解决：

```text
“现在适不适合 Stella 插一句？”
```

---

# 29. 可观测性与调试

这个系统必须具备日志，否则无法调参。

建议每次主动参与判断记录：

```text
timestamp
topic_id

relevance
opportunity
social_opportunity
topic_involvement
silence_bonus

recent_speech_penalty
velocity_penalty
repetition_penalty
expired_penalty

final_score
mode

decision:
    IGNORE
    OBSERVE
    CANDIDATE
    ALLOW_LLM
```

例如：

```text
[12:33:18]
Topic: Helldivers 2
Relevance: 26
Opportunity: 21
SocialOpportunity: 10
TopicInvolvement: 0
SilenceBonus: 6

RecentSpeechPenalty: 0
VelocityPenalty: 8
RepetitionPenalty: 0
ExpiredPenalty: 0

Score: 55
Decision: OBSERVE
```

这比单纯观察：

```text
Stella 为什么没说话？
```

更容易定位问题。

---

# 30. 第一阶段验收标准

机制完成后，不以“回复质量”作为第一阶段验收指标。

重点观察：

## 情况 A：明显应该说

```text
有人明确向 Stella 发问
```

必须响应。

---

## 情况 B：明显不应该说

```text
群友高速刷屏
```

Stella 不应该频繁插话。

---

## 情况 C：存在明显社交钩子

```text
我刚刚干了一件特别离谱的事情
```

Stella 应该有机会进入 Candidate / Allow。

---

## 情况 D：Stella 感兴趣但没有插话机会

```text
群友连续讨论 Stella 感兴趣的话题
```

Stella 可以保持沉默。

这是非常重要的成功指标。

---

## 情况 E：Stella 刚刚说过

即使出现相关话题，也应该明显降低主动插话概率。

---

## 情况 F：话题已经结束

数分钟后不应该突然恢复旧话题。

---

# 31. 调参原则

第一版上线后，不建议直接凭感觉修改大量参数。

应该观察：

```text
False Positive
```

即：

> Stella 不该说却说了。

以及：

```text
False Negative
```

即：

> Stella 明明很适合说，却一直没说。

优先级：

```text
先解决 False Positive
再解决 False Negative
```

原因是：

> 一个偶尔沉默的群友很正常；一个什么都要插嘴的群友非常像机器人。

因此 Stella 的主动参与机制应该整体偏向：

```text
宁可少说，也不要抢话。
```

---

# 32. 最终架构原则

本阶段最终固定以下原则：

### 原则 1

**说话决策与语言生成完全分离。**

### 原则 2

**Relevance 不等于 Opportunity。**

### 原则 3

**主动插话必须考虑群聊整体状态，而不是只看最后一条消息。**

### 原则 4

**Conversation State 优先于完整聊天记录。**

### 原则 5

**Embedding 负责提供语义依据，不负责做最终决定。**

### 原则 6

**主动参与应该有冷却、重复惩罚和话题过期机制。**

### 原则 7

**强制响应与主动插话必须走不同路径。**

### 原则 8

**LLM 是最后一步，而不是第一步。**

### 原则 9

**宁可沉默，也不要为了“表现得像人”而强行发言。**

### 原则 10

**当前阶段不通过修改 Prompt 来解决架构问题。**

---

# 33. 后续开发顺序

建议下一阶段严格按照以下顺序继续：

```text
① Message Buffer
       ↓
② Conversation State
       ↓
③ Topic State Machine
       ↓
④ Participation Score
       ↓
⑤ Candidate / Cooldown
       ↓
⑥ Participation Mode
       ↓
⑦ Context Selector
       ↓
⑧ LLM Prompt 微调
```

其中第 ①～⑤ 项完成后，就已经可以进行第一轮真实群聊测试。

只有当：

```text
“什么时候说”
```

已经基本自然，

再处理：

```text
“说什么”
```

这样可以避免用 Prompt 去掩盖决策层的问题。
