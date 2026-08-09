
# Stella Memory System

# Memory Schema Specification

版本：

```
Document: MMS-001
Version: 1.0 Draft
Status: Design
```

---

# 1. 设计目标

本规范定义 Stella 长期记忆的数据结构。

目标：

1. 支持长期人格连续性；
2. 支持上下文相关检索；
3. 支持聊天素材与行为约束分离；
4. 支持未来替换存储方案。

---

# 2. Memory 基础模型

一条 Memory 的逻辑结构：

```
Memory
│
├── Identity
│
├── Content
│
├── Classification
│
├── Usage
│
├── Permission
│
├── Trigger
│
├── Behavior
│
└── Metadata
```

对应：

```
(
id,

content,

type,

usage_tags,

visibility,

trigger,

behavior,

confidence,

importance,

timestamps
)
```

---

# 3. 数据表设计

这里结合你现在 SQLite 的：

```
long_term_memories
```

进行扩展。

---

## long_term_memories

| 字段               | 类型         | 说明   |
| ---------------- | ---------- | ---- |
| id               | INTEGER    | 唯一ID |
| group_id         | TEXT       | 所属群  |
| user_id          | TEXT       | 关联用户 |
| memory_type      | TEXT       | 记忆类型 |
| summary          | TEXT       | 记忆内容 |
| usage_tags       | TEXT(JSON) | 用途标签 |
| visibility       | TEXT       | 访问权限 |
| trigger_data     | TEXT(JSON) | 触发条件 |
| behavior_rule    | TEXT       | 行为规则 |
| confidence       | FLOAT      | 置信度  |
| importance       | FLOAT      | 长期价值 |
| created_at       | TIMESTAMP  | 创建时间 |
| updated_at       | TIMESTAMP  | 更新时间 |
| last_accessed_at | TIMESTAMP  | 最近调用 |

---

# 4. 字段详细规范

---

# 4.1 memory_type

## 类型

枚举：

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

## 约束

必须且只能有一个。

错误：

```
用户喜欢游戏，并且最近玩过游戏
```

不要：

```
type:
PREFERENCE + EVENT
```

应该拆：

Memory A：

```
PREFERENCE

用户喜欢Helldivers2
```

Memory B：

```
EVENT

用户最近游玩Helldivers2
```

---

# 4.2 summary

这是给模型看的自然语言内容。

要求：

## 正确：

```
用户喜欢合作类射击游戏，例如Helldivers2。
```

---

## 错误：

```
用户：
2026年8月3日晚上表示……
经过分析认为……
```

原因：

Memory不是日志。

日志在：

```
group_messages
```

---

# 4.3 usage_tags

格式：

JSON Array

例如：

```json
[
"TOPIC_START",
"RECOMMEND"
]
```

---

允许值：

```
TOPIC_START

TOPIC_CONTINUE

ANSWER_CONTEXT

RECOMMEND

PERSONALIZE

RELATION_CONTEXT

HUMOR

EMOTIONAL_SUPPORT

BOUNDARY_PROTECTION

CONFLICT_AVOID
```

---

# 4.4 visibility

枚举：

```
OPEN

CONTEXTUAL

RESTRICTED

INTERNAL
```

---

## OPEN

特点：

普通聊天可使用。

例：

```
用户喜欢Helldivers2
```

---

## CONTEXTUAL

特点：

需要主题匹配。

例：

```
用户不吃榴莲
```

---

## RESTRICTED

特点：

禁止作为聊天素材。

只能进入：

Behavior Guard。

例：

```
用户不喜欢未经允许摸头
```

---

## INTERNAL

特点：

仅供系统决策。

禁止进入LLM Prompt。

---

# 4.5 trigger_data

用途：

描述：

> 什么情况下这条记忆可能相关。

格式：

JSON：

```json
{
"keywords":[
"摸头",
"肢体接触"
],

"topics":[
"boundary"
]
}
```

---

注意：

Trigger不是强制触发。

只是：

检索辅助。

---

# 4.6 behavior_rule

这是 v2.0 新增核心字段。

描述：

> Stella应该如何改变行为。

例如：

记忆：

```
用户不喜欢未经允许摸头
```

behavior：

```
避免主动对该用户进行摸头相关互动。
```

---

注意：

不是：

```
告诉模型：
用户讨厌摸头。
```

---

# 4.7 confidence

范围：

```
0.0 - 1.0
```

表示：

模型认为该记忆正确程度。

---

建议：

```
>0.9

明确表达

0.7-0.9

多次观察

<0.7

不要进入长期记忆
```

---

# 4.8 importance

表示：

长期保存价值。

不是：

调用优先级。

例如：

```
用户不喜欢摸头
```

importance:

0.9

但是：

retrieval priority:

可能很低。

---

# 5. 示例规范

---

## 示例1：公开兴趣

```
summary:

用户喜欢Helldivers2。

type:

PREFERENCE


usage_tags:

[
"TOPIC_START",
"RECOMMEND"
]


visibility:

OPEN


trigger:

GAME


behavior:

可以自然提及相关话题。
```

---

## 示例2：饮食限制

```
summary:

用户不喜欢榴莲。


type:

PREFERENCE


usage_tags:

[
"RECOMMEND"
]


visibility:

CONTEXTUAL


trigger:

FOOD


behavior:

避免推荐榴莲相关食物。
```

---

## 示例3：边界保护

```
summary:

用户不喜欢未经允许的摸头互动。


type:

PREFERENCE


usage_tags:

[
"BOUNDARY_PROTECTION"
]


visibility:

RESTRICTED


trigger:

[
摸头,
身体接触
]


behavior:

避免主动对该用户进行相关互动。
```

---

# 6. Memory 生成规范

Consolidator 输出 Memory Candidate 时：

必须同时生成：

```
content

type

usage_tags

visibility

confidence
```

不能只生成：

```
summary
```

---

# 7. Memory 删除规则

长期记忆不是永久保存。

删除条件：

## 低置信度

```
confidence < 0.5
```

---

## 长期未使用

```
last_accessed > threshold
```

---

## 被新记忆覆盖

例如：

旧：

```
用户喜欢A游戏
```

新：

```
用户现在不玩A游戏
```

旧 Memory：

进入 archive。

---

# 8. Schema 第一阶段完成标准

满足：

✅ Memory 能描述事实
✅ Memory 能描述用途
✅ Memory 能限制访问
✅ Memory 能指导行为
✅ Memory 不再只是文本摘要


