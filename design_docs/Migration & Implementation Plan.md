# Stella Memory System

# Migration & Implementation Plan

---

# 1. 迁移目标

当前系统：

```text
group_messages

        ↓

short_term_memories

        ↓

long_term_memories

        ↓

Prompt

        ↓

Gemma
```

升级为：

```text
group_messages

        ↓

short_term_memories

        ↓

memory_candidates

        ↓

long_term_memories(v2)

        ↓

Memory Policy

        ↓

Memory Retrieval

        ↓

Prompt Builder

        ↓

Gemma
```

核心变化：

不是删除旧系统。

而是：

> 在现有系统外围增加新的控制层。

---

# 2. 迁移原则

---

## 原则1：数据库先扩展，不迁移数据

不要第一步修改：

```sql
DROP TABLE long_term_memories
```

这种方式。

风险：

不可恢复。

---

采用：

```
Additive Migration
```

即：

增加字段。

例如：

旧：

```
long_term_memories

id
group_id
user_id
summary
importance
last_accessed_at
```

升级：

增加：

```
memory_type

usage_tags

visibility

trigger_data

behavior_rule

confidence

status
```

旧数据：

保持。

---

# 3. 数据库迁移阶段

## Phase 0：备份

必须：

```text
stella_memory_backup.db
```

保存。

---

## Phase 1：Schema 扩展

新增：

## long_term_memories

最终结构：

```
id

group_id

user_id


summary


memory_type

usage_tags

visibility

trigger_data

behavior_rule


importance

confidence


status


created_at

updated_at

last_accessed_at
```

---

新增字段解释：

---

## status

非常重要。

枚举：

```
ACTIVE

ARCHIVED

CONFLICT

PENDING
```

---

用途：

旧记忆不直接删除。

例如：

用户：

以前喜欢A游戏。

后来：

不喜欢。

旧：

```
ARCHIVED
```

新：

```
ACTIVE
```

---

# 4. 增加 memory_candidates 表

这是最大的结构变化。

以前：

```
总结
 ↓
长期记忆
```

现在：

```
总结
 ↓
候选
 ↓
审核
 ↓
长期记忆
```

---

表：

```
memory_candidates
```

字段：

```
id

source_messages

summary

memory_type

usage_tags

visibility

trigger_data

behavior_rule


confidence

importance


created_at

status
```

status：

```
PENDING

ACCEPTED

REJECTED
```

---

# 5. Consolidator 改造路线

不要一次改完。

分三个版本。

---

# Version 1

目标：

让模型生成新格式。

现在：

输出：

```
用户喜欢游戏
```

改成：

```
{
summary:
用户喜欢合作游戏,

type:
PREFERENCE,

usage:
RECOMMEND,

confidence:
0.85
}
```

但是：

仍然写旧表。

目的：

测试模型输出质量。

---

# Version 2

加入：

```
memory_candidates
```

流程：

```
Consolidator

↓

Candidate

↓

Database
```

此时：

人工观察：

哪些 Candidate 合理。

---

# Version 3

自动审核：

增加：

Policy Validator。

例如：

模型输出：

```
summary:
用户不喜欢摸头

usage:
TOPIC_START
```

Validator:

发现：

错误。

自动修正：

```
usage:
BOUNDARY_PROTECTION

visibility:
RESTRICTED
```

---

# 6. Retrieval 迁移路线

这里是风险最高部分。

不要：

删除旧 Retriever。

采用：

双轨。

---

## Old Retriever

继续：

```
long_term_memories.summary
```

---

## New Retriever

新增：

```
Memory Policy Layer
```

---

结构：

```
             Message

                |

        +-------+-------+

        |               |

    Old Search     New Search


        |               |

        +-------+-------+

                |

          Compare Result
```

---

测试：

同一句输入：

分别生成：

A：

旧 Memory

B：

新 Memory

人工比较：

* 自然度
* 相关性
* 是否暴露信息

---

# 7. Prompt Builder 迁移

这是收益最大的地方。

现在：

类似：

```
关于用户XXX的重要记忆:

xxx
xxx
xxx
```

升级：

分区。

---

## 第一阶段

保留：

```
关于用户的重要信息
```

但是增加：

标签。

例如：

```
[Conversation Memory]

用户喜欢合作游戏。


[Behavior Constraint]

避免未经允许的边界互动。
```

---

## 第二阶段

完全切换。

---

# 8. User Profile 处理方案

你的：

```
user_profiles
```

目前应该比较危险。

原因：

很多系统容易：

把 profile 当事实。

例如：

```
性格：
温柔
幽默
感性
```

这些其实大量属于：

推断。

---

建议：

未来拆成：

```
user_profiles
```

只保存：

稳定画像。

例如：

允许：

```
语言偏好
回答长度偏好
技术水平
```

---

禁止：

```
人格判断
心理状态
价值判断
```

---

这些应该变成：

低置信 Internal Memory。

---

# 9. 测试方案

必须建立 Benchmark。

否则你无法知道升级有没有效果。

---

建立：

## Memory Test Dataset

例如：

保存：

100条真实群聊片段。

每条标记：

```
输入

正确应该调用的Memory

禁止调用的Memory

期望回复风格
```

---

案例类型：

---

## Case 1

普通聊天

测试：

不要乱调用敏感记忆。

---

## Case 2

技术问题

测试：

是否调用用户设备信息。

---

## Case 3

推荐问题

测试：

是否使用用户偏好。

---

## Case 4

主动插话

测试：

是否找到自然切入口。

---

## Case 5

冲突场景

测试：

是否启用 Behavior Guard。

---

# 10. 迁移阶段划分

## Milestone 1

数据库升级完成。

验收：

```
旧数据可读
新字段存在
```

---

## Milestone 2

Consolidator v2

验收：

可以生成：

```
Type
Usage
Visibility
```

---

## Milestone 3

Candidate Pipeline

验收：

所有新 Memory 经过 Candidate。

---

## Milestone 4

Policy Retrieval

验收：

错误记忆召回率下降。

---

## Milestone 5

完全切换。

---

# 11. 回滚方案

必须设计。

---

如果：

新 Memory 导致：

* 回复变差；
* 延迟增加；
* 人格变化。

可以：

关闭：

```
MEMORY_V2_ENABLED=False
```

回到：

旧系统。

---

# 12. 性能考虑

你的环境：

```
RTX5080
64GB RAM
Gemma 27B
```

模型不是瓶颈。

瓶颈会是：

## SQLite查询

解决：

索引。

重点：

```
group_id

user_id

memory_type

visibility

status
```

---

## Embedding

不要每次生成。

保存：

```
memory_embedding
```

---

## Retrieval Cache

缓存：

```
(group_id, topic)
```



