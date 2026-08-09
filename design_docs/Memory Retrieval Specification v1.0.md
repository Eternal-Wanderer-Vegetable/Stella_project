# Stella Memory System

# Memory Retrieval Specification

这一部分解决的问题是：

> **当 Stella 需要生成一句回复时，如何从大量长期记忆中选择真正有用的少量信息？**

注意，这和传统 RAG 有一个本质区别。

普通 RAG：

> 找最相关的文本。

Stella Memory：

> 找当前 Stella 行为真正需要的记忆。

所以 Retrieval 不是搜索问题，而是：

**Context-aware Memory Activation（上下文感知记忆激活）**

---

# Stella Memory System

# Memory Retrieval Specification

版本：

```text
Document: MRS-001

Version: 1.0 Draft

Status: Design
```

---

# 1. Retrieval 设计目标

系统必须满足：

## 目标1

找到正确记忆。

例如：

用户问：

> 推荐一个游戏

应该找到：

```text
用户喜欢合作游戏
用户电脑配置
用户玩过的游戏
```

而不是：

```text
用户和某群友关系很好
用户曾经讨论摸头
```

---

## 目标2

避免过度召回。

错误：

```text
给LLM 50条记忆
```

结果：

模型开始：

* 分析用户；
* 复述历史；
* 变得不像真人。

---

## 目标3

记忆必须经过权限控制。

流程：

不是：

```
搜索 → 给LLM
```

而是：

```
搜索 → 筛选 → 排序 → 注入
```

---

# 2. Retrieval 总体架构

最终流程：

```text
                 当前消息

                    |

                    v

           Context Analyzer

                    |

                    v

            Stella Mode

                    |

                    v

          Candidate Retrieval

                    |

                    v

          Policy Filtering

                    |

                    v

             Re-ranking

                    |

                    v

          Memory Selection

                    |

                    v

            Prompt Builder

                    |

                    v

                 Gemma
```

---

# 3. Retrieval 的核心原则

## Principle 1

# Policy 优先于 Similarity

这是整个系统最重要的规则。

错误：

```text
相似度最高
=
应该使用
```

---

例如：

当前：

```
群里讨论摸头
```

数据库：

A：

```
用户喜欢被朋友摸头
```

Similarity:

0.95

B：

```
用户不喜欢陌生人摸头
```

Similarity:

0.94

如果只看向量：

两个都会出现。

---

但是：

Policy：

A:

```
HUMOR
OPEN
```

允许。

B:

```
BOUNDARY_PROTECTION
RESTRICTED
```

不进入 Conversation Memory。

所以：

最终：

只给A。

---

# 4. Retrieval Pipeline 详细设计

---

# Stage 1：Context Analyzer

首先分析当前情况。

输入：

```text
当前消息
最近聊天
发送者
群状态
```

输出：

```json
{
"mode":
"ACTIVE_JOIN",

"topic":
"摸头玩笑",

"participants":
[
477346995,
2351598367
],

"keywords":
[
"摸头",
"互动",
"玩笑"
]
}
```

---

这里不需要 LLM。

建议：

第一阶段：

规则 + 小模型。

原因：

这是高频操作。

---

# Stage 2：Mode Detection

得到：

Stella 当前行为模式。

例如：

主动发言：

```text
ACTIVE_JOIN
```

技术问题：

```text
TECH_HELP
```

推荐：

```text
RECOMMEND
```

---

这个结果会决定：

后面允许哪些 Memory。

---

# Stage 3：Candidate Retrieval

这里才是真正搜索。

建议：

不要只用一种方法。

采用：

## Hybrid Retrieval

混合：

```
Keyword Search

+

Vector Search

+

Metadata Filter
```

---

## 3.1 Keyword Search

适合：

明确关键词。

例如：

用户：

```
RTX5080 怎么跑模型？
```

关键词：

```
RTX5080
模型
显存
```

直接命中：

```text
用户拥有RTX5080
```

---

优势：

准确。

缺点：

无法理解同义词。

---

## 3.2 Vector Search

适合：

语义。

例如：

当前：

```
推荐合作游戏
```

Memory：

```
用户喜欢和朋友一起玩的游戏
```

关键词：

不同。

向量：

高度相似。

---

## 3.3 Metadata Filter

这个非常重要。

不是所有 Memory 都进入搜索。

例如：

ACTIVE_JOIN：

先过滤：

允许：

```
OPEN
```

和：

```
CONTEXTUAL
```

禁止：

```
RESTRICTED
```

---

所以：

不要：

```
Search all memories
```

而是：

```
Search allowed memories
```

---

# 5. Retrieval 顺序

这里是关键。

推荐：

## 错误方案：

```
Vector Search Top50

↓

Policy Filter

↓

留下3条
```

问题：

敏感记忆可能污染候选池。

---

## 正确方案：

```
Mode Detection

↓

Policy Filter

↓

Metadata Filter

↓

Vector Search

↓

Rerank
```

---

也就是：

先决定：

> 什么东西有资格被找到。

然后：

> 在合法范围内找最相关。

---

# 6. Candidate Score 设计

最终排序：

推荐：

```
Memory Score
=
0.35 Context Match

+
0.25 Usage Match

+
0.20 Semantic Similarity

+
0.10 Confidence

+
0.10 Importance
```

---

解释：

## Context Match

最高。

因为：

当前是否需要，比内容像不像更重要。

---

## Usage Match

例如：

当前：

RECOMMEND

那么：

RECOMMEND标签：

加分。

BOUNDARY：

无效。

---

## Semantic Similarity

传统向量相似度。

---

## Confidence

可信程度。

---

## Importance

长期价值。

---

# 7. Memory Activation 阈值

不要固定 Top-K。

推荐：

动态数量。

---

## 普通聊天

最多：

```
3条
```

---

## 技术回答

最多：

```
5条
```

---

## 推荐

最多：

```
5条
```

---

## Conflict Guard

最多：

```
10条
```

因为安全优先。

---

# 8. Memory Selection Rules

即使 Score 高，也需要检查：

---

## Rule 1

同类 Memory 合并。

例如：

三个：

```
用户喜欢FPS
用户喜欢合作游戏
用户喜欢Helldivers2
```

不要：

给模型三条。

合并：

```
用户喜欢合作射击游戏，尤其是Helldivers2。
```

---

## Rule 2

避免重复人格描述。

错误：

```
用户随和
用户温柔
用户友好
用户热心
```

这些不是四条记忆。

应该：

```
用户交流风格偏友好随和。
```

---

## Rule 3

低置信度不进入 Prompt。

例如：

```
confidence=0.55
```

只用于未来观察。

---

# 9. Memory Injection 规范

这是非常容易影响模型表现的地方。

---

## 错误：

```
用户记忆：

1. 用户喜欢...
2. 用户讨厌...
3. 用户曾经...
```

问题：

像数据库。

---

## 正确：

分区。

---

## Conversation Memory

例如：

```
可参考聊天背景：

用户喜欢合作类游戏。
用户最近在研究本地AI部署。
```

---

## Behavior Constraint

例如：

```
交流注意：

避免未经允许对某用户进行边界相关玩笑。
```

---

两者绝不能混合。

---

# 10. Retrieval 与 Prompt 长度控制

这是你的 Gemma 27B 很重要的问题。

虽然 RTX5080 + 64GB 可以撑较大的上下文。

但是：

不是越多越好。

推荐：

普通聊天：

```
Conversation Memory:
<500 tokens

Behavior:
<150 tokens
```

技术：

```
Conversation:
<1000 tokens
```

---

# 11. 主动发言特殊 Retrieval

你的失败案例属于：

```text
ACTIVE_JOIN
```

这个模式必须特殊处理。

主动发言目标：

不是回答问题。

而是：

找到：

> 一个自然参与点。

所以 Retrieval 优先级：

```
GROUP_CONTEXT

>

RECENT EVENT

>

HUMOR

>

RELATION
```

---

禁止：

```
PRIVATE PREFERENCE

BOUNDARY

EMOTIONAL HISTORY
```

---

例如：

当前：

群：

```
大家玩摸头梗
```

正确：

找到：

```
最近群里经常玩摸头梗
A喜欢开玩笑
```

生成：

```
你们又开始演偶像剧了？
```

---

错误：

找到：

```
B不喜欢摸头
```

然后：

模型开始：

```
注意B的边界……
```

像管理员。

---

# 12. Retrieval Cache

由于你的机器人是长期运行的。

建议增加缓存。

---

## 短期缓存

例如：

当前群话题：

```
topic_cache
```

保存：

5~10分钟。

避免：

每句话重新检索。

---

## 用户缓存

例如：

```
user_memory_cache
```

保存：

最近访问的用户 Memory。

---

# 13. Retrieval Failure Handling

如果没有找到记忆：

不要强行调用。

例如：

没有：

```
用户喜欢什么游戏
```

不要：

编造。

---

输出：

```
Memory Context:
None
```

即可。

---

# 14. 最终 Retrieval 伪流程

完整逻辑：

```
Receive Message

↓

Analyze Context

↓

Detect Stella Mode

↓

Load Policy

↓

Filter Memory Permission

↓

Hybrid Search

↓

Calculate Score

↓

Remove Conflict

↓

Merge Similar Memory

↓

Limit Token

↓

Build Prompt

↓

Generate Reply
```

---

# 15. 针对当前 Stella 项目的推荐实现路线

结合你的情况：

你的环境：

* SQLite
* 本地 Gemma 27B
* RTX5080
* Python

我不建议一开始上复杂向量数据库。

---

## 第一阶段

SQLite + FTS5

实现：

关键词检索。

---

## 第二阶段

增加：

Embedding 表。

例如：

```
memory_embeddings
```

---

## 第三阶段

增加：

Reranker。

---

## 第四阶段

优化：

缓存。

---

# 16. 四份设计文档关系

现在完整架构：

```
              Stella Memory System


                    Memory

                      |

        +-------------+-------------+

        |                           |

 Schema Specification        Policy Specification


        |

        |

 Consolidation Specification


        |

        |

 Retrieval Specification
```

---

# 17. 到这里，理论设计已经闭环

现在 Stella 的 Memory System 已经具备：

✅ 如何产生记忆
✅ 如何保存记忆
✅ 如何判断权限
✅ 如何调用记忆
✅ 如何避免错误使用
✅ 如何控制 Prompt 污染


