很好。现在进入第六份文档。

前五份文档解决了：

> Stella 应该如何产生、存储、调用记忆。

但是在真实运行过程中，还有一个更大的问题：

> **当 Stella 表现异常时，我们如何知道问题到底出在哪里？**

例如你之前那个失败案例：

主动发言：

> “你们在这儿演什么偶像剧呢”

表面看只是回复不够自然。

但内部可能有至少五种原因：

---

可能1：

Consolidator 错误。

它把：

```
摸头玩笑
```

错误总结成：

```
用户关系亲密
```

---

可能2：

Memory Policy 错误。

它允许：

```
BOUNDARY_PROTECTION
```

进入：

```
ACTIVE_JOIN
```

---

可能3：

Retriever 错误。

搜索算法认为：

```
不喜欢摸头
```

比：

```
喜欢玩梗
```

更相关。

---

可能4：

Prompt Builder 错误。

虽然筛选正确，但是组织方式导致模型误解。

---

可能5：

Gemma 本身生成偏差。

---

如果没有评估体系，你只能：

“调 Prompt”。

这会导致无限循环。

所以建立：

# Stella Memory System

# Evaluation & Debug Specification

---

# 1. 设计目标

定义：

1. 如何记录 Memory 决策过程；
2. 如何定位错误来源；
3. 如何建立测试集；
4. 如何衡量系统改进；
5. 如何长期维护人格一致性。

---

# 2. Agent Debug 核心原则

普通程序：

```
Input

↓

Function

↓

Output
```

错误容易定位。

Agent：

```
Input

↓

Context

↓

Memory

↓

Policy

↓

Prompt

↓

LLM

↓

Output
```

任何一层都可能导致错误。

因此必须记录：

> Decision Trace

---

# 3. Memory Decision Trace

新增概念：

## Memory Trace

每一次回复保存：

```
为什么这些记忆被调用？
为什么其他记忆没有调用？
```

---

结构：

```json
{
"message_id":

123456,


"mode":

"ACTIVE_JOIN",


"candidate_memories":

[

],

"filtered_memories":

[

],


"final_memories":

[

],


"rejected_memories":

[

]

}
```

---

例如你的失败案例。

应该记录：

---

输入：

```
群聊正在摸头玩梗
```

---

候选：

```
M001:
用户喜欢摸头互动

score:
0.91


M002:
用户讨厌越界摸头

score:
0.89
```

---

Policy：

```
M001:

ALLOW


M002:

DENY
```

---

最终：

```
Prompt Memory:

M001
```

---

这样以后看到：

回复错误：

可以知道：

不是 Retriever。

而是 LLM。

---

# 4. 错误分类体系

所有 Memory 错误必须归类。

---

# Type A

## Memory Creation Error

记忆产生错误。

例如：

聊天：

```
今天吃火锅
```

生成：

```
用户喜欢火锅
```

---

定位：

Consolidator。

---

修复：

调整 Candidate Rules。

---

# Type B

## Memory Classification Error

内容正确。

类型错误。

例如：

```
用户今天想吃炸鸡
```

分类：

```
PREFERENCE
```

错误。

应该：

```
EVENT
```

---

---

# Type C

## Policy Error

记忆正确。

权限错误。

例如：

```
用户不喜欢摸头
```

被用于：

```
HUMOR
```

---

这是最危险错误。

---

# Type D

## Retrieval Error

允许调用。

但是没找到正确记忆。

例如：

应该：

```
用户喜欢合作游戏
```

却找到：

```
用户喜欢FPS
```

---

---

# Type E

## Prompt Assembly Error

Memory正确。

Prompt组织错误。

例如：

把：

```
Behavior Constraint
```

放入：

```
Conversation Memory
```

---

---

# Type F

## Generation Error

所有输入正确。

模型仍然回复不好。

---

这种才应该调 Prompt。

---

# 5. Debug Dashboard

未来建议增加：

## Memory Statistics

---

每天：

```
Generated Memories:

152

Accepted:

43

Rejected:

109
```

---

## Retrieval Statistics

例如：

```
Average memories per reply:

3.2


Active Join:

2.1


Tech Help:

4.8
```

---

## Policy Statistics

例如：

```
Denied memories:

356


Most denied:

BOUNDARY_PROTECTION
```

---

如果：

BOUNDARY 被大量调用。

说明：

Retriever有问题。

---

# 6. Benchmark Dataset

这是最重要部分。

建立：

```
stella_memory_benchmark/
```

结构：

```
casual/

tech/

recommend/

active_join/

conflict/

emotion/
```

---

每个 Case：

例如：

```json
{
"input":

"群聊内容...",


"mode":

"ACTIVE_JOIN",


"expected_memory":

[
"M001"
],


"forbidden_memory":

[
"M002"
],


"expected_behavior":

"参与玩笑，不提用户边界"
}
```

---

# 7. 核心测试指标

不要只看：

回复好不好。

需要拆指标。

---

# Metric 1

## Memory Precision

召回的 Memory 中：

多少是真的需要。

公式：

```
Relevant Memories
/
Retrieved Memories
```

---

目标：

> 80%

---

# Metric 2

## Memory Recall

应该找到的：

找到多少。

---

技术问题：

很重要。

---

# Metric 3

## Forbidden Activation Rate

最重要。

定义：

错误激活：

```
Restricted Memory
```

次数。

目标：

接近：

0。

---

# Metric 4

## Memory Pollution Rate

Prompt 中：

无用 Memory 比例。

例如：

10条 Memory：

8条无关。

污染率：

80%。

---

# Metric 5

## Personality Consistency

人工评价。

例如：

100条回复。

评分：

1-5。

---

# 8. 自动化测试流程

未来：

每次修改 Memory：

自动运行。

流程：

```
Benchmark Dataset

        |

        v

Memory Retrieval

        |

        v

Prompt Snapshot

        |

        v

Gemma Generate

        |

        v

Evaluator
```

---

Evaluator 可以：

第一阶段：

人工。

第二阶段：

小模型评分。

---

# 9. Prompt Snapshot

这是非常推荐的功能。

保存：

每次 LLM 调用：

不仅保存：

```
最终回复
```

还保存：

```
完整Prompt
```

你现在日志已经接近这个方向。

建议结构化：

---

Input:

```
用户消息
```

---

Context:

```
短期摘要
```

---

Memory:

```
调用Memory
```

---

Constraint:

```
行为约束
```

---

Output:

```
模型回复
```

---

这样可以回放。

---

# 10. Memory Replay

非常适合你的项目。

功能：

选择历史消息：

点击：

```
Replay
```

然后：

使用：

不同 Memory Strategy

重新生成。

例如：

旧系统：

```
回复A
```

新系统：

```
回复B
```

比较。

---

# 11. Debug 优先级

出现问题时：

按照顺序检查：

---

## 第一：

Memory 是否应该存在？

↓

Consolidator

---

## 第二：

Memory 是否允许使用？

↓

Policy

---

## 第三：

Memory 是否找到？

↓

Retriever

---

## 第四：

Prompt 是否正确？

↓

Builder

---

## 第五：

模型是否理解？

↓

Gemma

---

不要反过来。

很多 Agent 项目失败就是：

一看到回复不好就改 Prompt。

---

# 12. 与现有日志系统结合

你现在日志：

已经保存：

```
完整Prompt

LLM输出

耗时

模型
```

这是非常好的基础。

升级：

增加：

```
memory_trace
```

即可。

例如：

日志：

```
[Memory]

Activated:
M001
M002


Rejected:

M003

Reason:

Visibility Restricted
```

---

# 13. Stella 项目推荐运行模式

长期运行：

建议：

## 普通模式

记录：

```
Input
Memory
Output
```

---

## Debug模式

记录：

全部：

```
Candidate
Policy
Ranking
Prompt
```

---

不要一直开 Debug。

否则数据库会膨胀。

---

# 14. 最终完整架构

现在六份文档合起来：

```
                  Stella Agent


                       |

                 Memory System


                       |


 -------------------------------------------------

 |             |             |          |          |

Schema     Policy    Consolidate Retrieval Evaluation


                       |

                   Migration

 -------------------------------------------------

```

---

# 15. 当前设计完成度

到这里，你的 Memory System 已经具备：

## 数据层

✅ 分类型 Memory
✅ 生命周期
✅ 冲突处理

## 逻辑层

✅ 生成规则
✅ 权限控制
✅ 检索策略

## 工程层

✅ 迁移路线
✅ 调试方案
✅ Benchmark 思路

这实际上已经接近一个小型 Agent Framework 的设计。

---

# 下一步建议

到这里，理论设计已经完整。

下一阶段我建议不要继续写更多抽象文档，而是进入：

# 文档七：Stella Memory System Implementation Blueprint

也就是：

把所有设计转换成工程任务列表：

例如：

```
Task M001:
新增 memory_candidates 表

Task M002:
修改 consolidator 输出协议

Task M003:
实现 Memory Policy Engine

Task M004:
实现 Retrieval Pipeline

Task M005:
改造 Prompt Builder
```

并且明确：

* 修改哪些模块；
* 先后顺序；
* 每一步完成标准；
* 如何测试。

这样你就可以直接按照文档推进代码重构。

从你的项目状态来看，这一步比继续讨论理论更有价值。你现在已经有完整设计，下一步应该进入“施工图”。
