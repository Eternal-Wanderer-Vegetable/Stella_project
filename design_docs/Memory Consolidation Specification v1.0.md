
# Stella Memory System

# Memory Consolidation Specification

版本：

```text
Document: MCS-001

Version: 1.0 Draft

Status: Design
```

---

# 1. 设计目标

Memory Consolidation 的目标不是：

> 总结聊天记录。

而是：

> 从大量短期互动中提取对未来 Stella 行为有价值的信息。

因此：

## 原始聊天

```text
group_messages
```

↓

## 短期上下文

```text
short_term_memories
```

↓

## Memory Candidate

↓

## Policy 审核

↓

## Long Term Memory

---

# 2. 核心原则

---

# Principle 1

## 不记录对话，记录状态变化

错误：

聊天：

```
A:
我今天吃火锅了
```

生成：

```
用户今天吃火锅
```

这没有长期价值。

---

正确：

连续观察：

```
A:
我每周都去吃火锅

A:
火锅是我最喜欢的东西
```

生成：

```
用户喜欢火锅类食物
```

---

所以：

Memory 不是 Event Log。

---

# Principle 2

## 单次表达 ≠ 长期事实

例如：

用户：

> 今天突然想吃炸鸡。

不能：

```
PREFERENCE:
用户喜欢炸鸡
```

原因：

这是一次性状态。

---

应该：

```
EVENT:
用户某日想吃炸鸡
```

或者：

不保存。

---

# Principle 3

## 长期记忆必须具有未来价值

判断：

如果未来 Stella 不知道它，会不会明显变差？

如果：

不会。

删除。

---

# 3. Consolidation Pipeline

整体流程：

```text
             group_messages

                    |

                    v

          Context Window Builder

                    |

                    v

          Candidate Extraction

                    |

                    v

          Candidate Validation

                    |

                    v

          Policy Classification

                    |

                    v

          Conflict Resolution

                    |

                    v

          Long Term Memory
```

---

# 4. 第一阶段：Context Window Builder

目的：

提供给 Consolidator 的不是全部聊天。

而是：

> 最近一段有意义的上下文。

输入：

例如：

最近：

```
500条消息
```

不推荐。

---

应该：

根据：

## 时间

例如：

最近24小时。

## 话题

例如：

同一个 Topic。

## 用户

例如：

涉及某用户的重要互动。

---

输出：

```text
Conversation Segment
```

例如：

```
用户A:
我最近又开始玩Helldivers2

用户B:
你不是一直喜欢合作游戏吗

用户A:
对，单机玩久了没意思
```

---

# 5. 第二阶段：Candidate Extraction

这是 LLM 的主要工作。

但是输出不能直接是 Memory。

必须先产生：

## Memory Candidate

---

Candidate 格式：

```json
{
"content":

"用户喜欢合作类游戏",

"type":

"PREFERENCE",

"usage":

[
"RECOMMEND",
"TOPIC_START"
],

"confidence":

0.85
}
```

---

注意：

Candidate 不是最终 Memory。

---

# 6. Candidate 必须回答五个问题

Consolidator Prompt 中应该要求：

---

## Q1

这是否是稳定信息？

如果：

只是一次事件：

拒绝。

---

## Q2

它属于什么 Memory Type？

必须选择：

```
FACT
PREFERENCE
EVENT
PLAN
RELATION
STYLE
GROUP_CONTEXT
```

---

## Q3

为什么未来有价值？

例如：

错误：

```
用户今天吃了苹果
```

未来价值：

低。

正确：

```
用户长期喜欢水果
```

未来价值：

高。

---

## Q4

它应该如何被使用？

生成：

Usage Tag。

---

## Q5

它是否需要限制访问？

生成：

Visibility。

---

# 7. Candidate 分类规则

---

# FACT

生成条件：

稳定事实。

例如：

```
用户使用RTX5080
用户是工程专业学生
```

要求：

置信度：

> 0.9

---

# PREFERENCE

生成条件：

用户明确表达喜欢/讨厌。

例如：

```
我特别喜欢FPS游戏
```

或者：

多次行为证明。

---

# EVENT

生成条件：

重要事件。

例如：

```
完成毕业设计
参加比赛
```

生命周期较短。

---

# PLAN

生成条件：

未来计划。

例如：

```
准备升级电脑
准备训练模型
```

需要：

定期衰减。

---

# RELATION

生成条件：

人与人之间稳定互动。

要求：

高置信。

禁止：

一次玩笑生成关系。

例如：

错误：

```
A说摸摸B

↓

A喜欢B
```

---

# STYLE

生成条件：

交流方式。

例如：

```
用户喜欢直接回答
```

---

# GROUP_CONTEXT

生成条件：

群体共同状态。

例如：

```
最近群里一直讨论某游戏
```

---

# 8. Candidate → Long Term Memory

这里需要一个 Gate。

不是所有 Candidate 都进入数据库。

---

建议：

## Gate 1：Confidence

规则：

```
confidence >=0.85

允许进入
```

---

```
0.6-0.85

进入观察区
```

---

```
<0.6

丢弃
```

---

# Gate 2：Importance

计算：

```
Importance =
Future Usefulness
+
Stability
+
Personal Impact
```

---

例如：

用户生日：

高。

用户今天吃什么：

低。

---

# Gate 3：Policy Validation

检查：

Usage 是否合理。

例如：

模型生成：

```
用户不喜欢摸头

Usage:
TOPIC_START
```

拒绝。

修正：

```
Usage:
BOUNDARY_PROTECTION

Visibility:
RESTRICTED
```

---

# 9. Conflict Resolution

这是长期记忆非常重要的一部分。

因为人会变化。

---

例：

旧：

```
用户喜欢A游戏
```

新：

```
用户最近不玩A游戏了
```

不能：

两个都保留。

---

需要：

Memory Relation：

```text
UPDATE
REPLACE
CONFLICT
```

---

## UPDATE

增强旧记忆。

例如：

```
用户喜欢FPS

↓

用户喜欢合作FPS
```

---

## REPLACE

替代。

例如：

```
喜欢A

↓

不喜欢A
```

---

## CONFLICT

无法判断。

进入：

```
uncertain_memory
```

---

# 10. Memory Decay

长期记忆也会过期。

---

建议：

不同 Type 不同生命周期。

| Type          | 衰减 |
| ------------- | -- |
| FACT          | 极慢 |
| STYLE         | 慢  |
| PREFERENCE    | 中  |
| RELATION      | 中  |
| EVENT         | 快  |
| PLAN          | 快  |
| GROUP_CONTEXT | 很快 |

---

例如：

GROUP_CONTEXT：

```
最近大家玩某游戏
```

一个月后无意义。

---

# 11. Consolidator 输出规范

最终要求：

不能输出：

```json
[
"用户喜欢游戏"
]
```

---

必须：

```json
[
{
"summary":
"用户喜欢合作类射击游戏",

"type":
"PREFERENCE",

"usage_tags":
[
"RECOMMEND",
"TOPIC_START"
],

"visibility":
"OPEN",

"trigger":
[
"GAME",
"FPS"
],

"behavior_rule":
"可以自然推荐相关游戏",

"confidence":
0.92,

"importance":
0.75
}
]
```

---

# 12. Consolidator 不应该做什么

非常重要。

## 禁止1：

不要总结人格。

错误：

```
用户是一个温柔的人
```

原因：

人格推断风险高。

---

正确：

```
用户经常主动帮助群友
```

---

## 禁止2：

不要保存隐私推断。

错误：

```
用户可能有心理问题
```

---

## 禁止3：

不要保存一次性玩笑。

错误：

```
用户喜欢摸头
```

来源：

一次玩笑。

---

# 13. 与现有数据库对应

你的现有：

```
long_term_memories
```

升级后：

承担：

```
Validated Memory
```

新增建议：

增加中间表：

```
memory_candidates
```

流程：

```
short_term

↓

memory_candidates

↓

long_term
```

不要：

```
short_term

↓

long_term
```

---

# 14. 推荐实施顺序

## Phase 1

修改 consolidator 输出。

目标：

让它生成：

```
Type
Usage
Visibility
```

---

## Phase 2

增加 Candidate 表。

不要直接写 long_term。

---

## Phase 3

增加 Validation。

---

## Phase 4

增加 Conflict Resolution。

---

## Phase 5

增加 Memory Decay。

---

# 15. 本阶段完成标准

完成后：

Stella 应该具备：

✅ 不会把聊天日志当记忆
✅ 不会把一次玩笑变成人格
✅ 能区分事实、偏好、关系、边界
✅ 新旧记忆可以更新
✅ 长期记忆不会无限膨胀


