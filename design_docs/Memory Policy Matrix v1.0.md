
# Stella Memory System

# Memory Policy Matrix Specification

版本：

```text
Document: MPS-001
Version: 1.0 Draft
Status: Design
```

---

# 1. Policy 设计目标

Memory Policy 负责解决：

## 问题1

避免：

> 语义相关 ≠ 应该使用

例如：

当前：

```
群友正在玩摸头梗
```

检索：

```
用户不喜欢摸头
```

语义：

高度相关。

但是：

用途错误。

---

## 问题2

避免：

> 高重要性记忆污染普通聊天

例如：

```
用户边界
用户矛盾
用户负面经历
```

这些信息可能 importance 很高。

但是：

不能成为聊天素材。

---

## 问题3

支持不同 Stella 行为模式

例如：

主动插话：

需要：

```
群氛围
最近事件
轻关系
```

技术回答：

需要：

```
设备
项目
历史问题
```

---

# 2. Policy 总体结构

一次 Memory 调用必须经过：

```text
                 当前消息

                    |

                    v

            Stella Mode Detection

                    |

                    v

             Usage Permission

                    |

                    v

          Memory Type Filtering

                    |

                    v

          Visibility Access Check

                    |

                    v

              Memory Ranking

                    |

                    v

              Prompt Injection
```

---

# 3. Stella Mode 定义

Memory Policy 不直接绑定消息。

首先判断：

> Stella 当前正在执行什么行为。

---

## MODE 枚举

```text
CASUAL_REPLY

ACTIVE_JOIN

HUMOR

TECH_HELP

RECOMMEND

EMOTIONAL

CONFLICT_AVOID

GROUP_EVENT
```

---

# 4. 第一张表：Mode → Usage Matrix

这是第一层权限。

---

# 4.1 CASUAL_REPLY

普通聊天回复。

例如：

```
用户：
今天好累啊
```

目标：

自然交流。

---

允许：

| Usage             | 等级    |
| ----------------- | ----- |
| PERSONALIZE       | ★★★★★ |
| TOPIC_CONTINUE    | ★★★★★ |
| RELATION_CONTEXT  | ★★★   |
| TOPIC_START       | ★★★   |
| EMOTIONAL_SUPPORT | ★★★   |
| HUMOR             | ★★    |

---

谨慎：

| Usage          |
| -------------- |
| RECOMMEND      |
| ANSWER_CONTEXT |

---

禁止：

| Usage               |
| ------------------- |
| BOUNDARY_PROTECTION |
| CONFLICT_AVOID      |

原因：

普通聊天不应该主动加载防御性信息。

---

# 4.2 ACTIVE_JOIN

主动插话。

这是 Stella 最特殊的模式。

例如：

```
群里没有人@Stella

Stella想参与聊天
```

---

目标：

> 找一个自然切入口。

---

允许：

| Usage            | 等级    |
| ---------------- | ----- |
| TOPIC_START      | ★★★★★ |
| TOPIC_CONTINUE   | ★★★★★ |
| GROUP_CONTEXT    | ★★★★★ |
| HUMOR            | ★★★★  |
| RELATION_CONTEXT | ★★★   |

---

谨慎：

| Usage       |
| ----------- |
| PERSONALIZE |
| RECOMMEND   |

---

禁止：

| Usage               |
| ------------------- |
| BOUNDARY_PROTECTION |
| CONFLICT_AVOID      |
| EMOTIONAL_SUPPORT   |

原因：

主动插话不应该突然分析用户。

---

# 4.3 HUMOR

玩梗模式。

目标：

增加互动。

允许：

| Usage            | 等级    |
| ---------------- | ----- |
| HUMOR            | ★★★★★ |
| RELATION_CONTEXT | ★★★★★ |
| GROUP_CONTEXT    | ★★★★★ |
| TOPIC_CONTINUE   | ★★★★  |

谨慎：

| Usage       |
| ----------- |
| PERSONALIZE |

禁止：

| Usage               |
| ------------------- |
| BOUNDARY_PROTECTION |
| CONFLICT_AVOID      |

原因：

避免：

“为了开玩笑调用敏感信息”。

---

# 4.4 TECH_HELP

技术帮助。

例如：

```
为什么我的CUDA不能运行？
```

目标：

解决问题。

允许：

| Usage          | 等级    |
| -------------- | ----- |
| ANSWER_CONTEXT | ★★★★★ |
| PERSONALIZE    | ★★★★★ |
| TOPIC_CONTINUE | ★★★   |
| PLAN           | ★★★   |

谨慎：

| Usage            |
| ---------------- |
| RELATION_CONTEXT |

禁止：

| Usage               |
| ------------------- |
| HUMOR               |
| BOUNDARY_PROTECTION |

---

# 4.5 RECOMMEND

推荐模式。

例如：

```
推荐游戏
推荐电脑
推荐软件
```

允许：

| Usage          | 等级    |
| -------------- | ----- |
| RECOMMEND      | ★★★★★ |
| PERSONALIZE    | ★★★★  |
| ANSWER_CONTEXT | ★★★   |
| TOPIC_CONTINUE | ★★    |

---

重点：

这里允许大量 PREFERENCE。

因为推荐高度依赖个人喜好。

---

# 4.6 EMOTIONAL

情绪交流。

例如：

```
最近压力很大
```

目标：

陪伴。

允许：

| Usage             | 等级    |
| ----------------- | ----- |
| EMOTIONAL_SUPPORT | ★★★★★ |
| PERSONALIZE       | ★★★★★ |
| RELATION_CONTEXT  | ★★★   |
| TOPIC_CONTINUE    | ★★★   |

谨慎：

| Usage |
| ----- |
| EVENT |
| PLAN  |

禁止：

| Usage     |
| --------- |
| HUMOR     |
| RECOMMEND |

---

# 4.7 CONFLICT_AVOID

冲突规避模式。

这是 Behavior Guard 的入口。

例如：

```
用户可能被冒犯
```

允许：

| Usage               | 等级    |
| ------------------- | ----- |
| BOUNDARY_PROTECTION | ★★★★★ |
| CONFLICT_AVOID      | ★★★★★ |
| RELATION_CONTEXT    | ★★★★  |
| EVENT               | ★★    |

禁止：

| Usage       |
| ----------- |
| TOPIC_START |
| HUMOR       |

---

# 4.8 GROUP_EVENT

群事件模式。

例如：

```
群里正在组织活动
```

允许：

| Usage            | 等级    |
| ---------------- | ----- |
| GROUP_CONTEXT    | ★★★★★ |
| EVENT            | ★★★★★ |
| RELATION_CONTEXT | ★★★★  |
| TOPIC_CONTINUE   | ★★★★  |
| PLAN             | ★★★   |

---

# 5. 第二张表：Usage → Memory Type Compatibility Matrix

这一层解决：

> 某个用途应该从哪些类型记忆中寻找。

---

| Usage               | 主要来源                               |
| ------------------- | ---------------------------------- |
| TOPIC_START         | GROUP_CONTEXT / PREFERENCE / EVENT |
| TOPIC_CONTINUE      | EVENT / GROUP_CONTEXT / PLAN       |
| ANSWER_CONTEXT      | FACT / EVENT / PLAN                |
| RECOMMEND           | PREFERENCE / FACT / EVENT          |
| PERSONALIZE         | STYLE / PREFERENCE                 |
| RELATION_CONTEXT    | RELATION / EVENT                   |
| HUMOR               | RELATION / GROUP_CONTEXT / EVENT   |
| EMOTIONAL_SUPPORT   | EVENT / RELATION / STYLE           |
| BOUNDARY_PROTECTION | PREFERENCE / RELATION              |
| CONFLICT_AVOID      | RELATION / EVENT / PREFERENCE      |

---

# 6. 具体限制规则

这一部分非常重要。

---

## Rule 1：

## BOUNDARY_PROTECTION 不允许作为聊天素材

错误：

```text
Stella:
你不是不喜欢摸头嘛哈哈
```

原因：

暴露内部记忆。

正确：

Behavior Guard：

```
不要主动针对该用户进行摸头互动
```

---

## Rule 2：

## RELATION 不等于公开关系

例如：

Memory：

```
A喜欢调侃B
```

不能直接：

```
Stella:
你俩是不是又开始秀恩爱了
```

除非：

* 当前模式允许 HUMOR；
* 置信度足够；
* 双方近期互动支持。

---

## Rule 3：

## 推断型 Memory 默认降权

例如：

错误：

```
用户可能比较孤独
```

这种不是事实。

Policy：

```
INTERNAL
```

甚至不进入普通 Retrieval。

---

## Rule 4：

## 高 importance 不代表高优先级

排序必须：

```
Policy > Context > Similarity > Importance
```

而不是：

```
Importance > Everything
```

---

# 7. 第三张表：Visibility Access Matrix

这是最后一道安全门。

---

| Mode           | OPEN | CONTEXTUAL | RESTRICTED | INTERNAL |
| -------------- | ---- | ---------- | ---------- | -------- |
| CASUAL_REPLY   | ✓    | ✓          | ×          | ×        |
| ACTIVE_JOIN    | ✓    | △          | ×          | ×        |
| HUMOR          | ✓    | △          | ×          | ×        |
| TECH_HELP      | ✓    | ✓          | △          | ×        |
| RECOMMEND      | ✓    | ✓          | ×          | ×        |
| EMOTIONAL      | ✓    | ✓          | △          | ×        |
| GROUP_EVENT    | ✓    | ✓          | ×          | ×        |
| CONFLICT_AVOID | ✓    | ✓          | ✓          | △        |

---

解释：

## △

允许，但需要：

* 高相关度；
* 明确触发；
* 不直接展示。

---

例如：

TECH_HELP：

可以读取：

```
用户之前遇到过类似问题
```

但不能：

```
用户以前失败很多次
```

---

# 8. Memory Ranking 规则

Policy通过后才排序。

最终：

```text
Score =
Semantic Similarity

×

Mode Compatibility

×

Usage Match

×

Confidence

×

Importance
```

---

权重建议：

```
Mode Compatibility:
40%

Usage Match:
25%

Semantic Similarity:
20%

Confidence:
10%

Importance:
5%
```

原因：

现在最大问题不是找不到，而是找错。

---

# 9. Prompt Builder 规范

最终进入 Prompt 的 Memory 必须分类。

禁止：

```text
相关记忆:
xxx
xxx
xxx
```

---

应该：

## Conversation Context

例如：

```
可以参考的聊天背景：
最近群里经常讨论Helldivers2。
```

---

## Behavior Constraint

例如：

```
交流注意：
避免未经允许触碰相关玩笑。
```

---

两个区域不能混合。

---

# 10. 针对你的失败案例重新验证

输入：

```
ACTIVE_JOIN

主题:
摸头玩笑
```

---

检索候选：

A：

```
用户477喜欢摸头互动

Type:
RELATION

Usage:
HUMOR

Visibility:
OPEN
```

结果：

允许。

---

B：

```
用户235不喜欢摸头

Type:
PREFERENCE

Usage:
BOUNDARY_PROTECTION

Visibility:
RESTRICTED
```

结果：

Conversation Memory：

拒绝。

Behavior Guard：

允许。

---

最终 Prompt：

应该类似：

```
当前群聊：
大家正在围绕摸头玩梗。

聊天建议：
可以轻松参与调侃。

行为注意：
避免针对特定成员进行越界互动。
```

而不是：

```
用户235不喜欢摸头。
```

---

# 11. Policy 实施优先级

实现顺序：

## Phase 1

实现：

```
Mode
+
Usage Filter
```

效果最大。

---

## Phase 2

增加：

```
Visibility Control
```

解决敏感记忆泄露。

---

## Phase 3

增加：

```
Behavior Guard
```

让记忆真正影响行为。

---

## Phase 4

优化：

```
Ranking
```

