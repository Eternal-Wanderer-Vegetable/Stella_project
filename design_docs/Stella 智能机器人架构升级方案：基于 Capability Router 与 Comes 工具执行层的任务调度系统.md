# Stella 智能机器人架构升级方案

## 1. 项目背景

Stella 当前正在进行 AstrBot 插件兼容层开发。

在兼容 AstrBot 生态的过程中发现：

- 大量功能型插件依赖 LLM 工具调用能力；
- 如果将所有插件工具定义直接注入 Stella 主聊天上下文，会导致：
  - Context 长度快速增长；
  - 正常聊天受到工具描述干扰；
  - 8192 tokens 工作上下文限制无法满足长期扩展需求；
  - Stella 人格和工具逻辑高度耦合。

因此需要重新设计 Stella 的内部架构：

核心目标：

> 将“聊天能力”“记忆能力”“工具能力”彻底解耦，通过任务协议进行通信。

---

# 2. 总体架构设计

最终系统划分为四个核心模块：

```
                  User Message
                       |
                       v
                 +-------------+
                 |   Router    |
                 +-------------+
                       |
                Capability Route
                       |
        +--------------+--------------+
        |              |              |
        v              v              v
     Stella        Memory          Comes
        |              |              |
        |              |              |
        +--------------+--------------+
                       |
                       v
                Final Response
                       |
                       v
                      QQ
```

模块职责：

| 模块 | 职责 |
|-|-|
| Router | 判断本次请求需要哪些能力 |
| Stella | 用户交互、人格表达、最终回复 |
| Memory | 记忆检索与记忆管理 |
| Comes | 工具调用、插件执行 |

---

# 3. 核心设计原则

## 3.1 不共享上下文

禁止：

```
User
 |
 +-- Stella
 |
 +-- Comes
 |
 +-- Memory
```

直接共享完整聊天上下文。

原因：

- 工具描述会污染聊天上下文；
- 插件数量增加后不可扩展；
- 不同模块需要的信息不同。

采用：

```
Request
   |
 Task
   |
 Result
```

模块之间只传递任务和结果。

---

# 4. Task Protocol 设计

所有模块之间通过 Task 进行通信。

## 4.1 Task

Task 表示：

> 系统需要完成的一项工作。

结构：

```
Task

- task_id
- type
- capability
- objective
- input
- dependencies
- constraints
```

说明：

## task_id

任务唯一编号。

用于：

- 并行任务管理；
- DAG 依赖；
- 调试追踪。


---

## type

任务类型。

示例：

```
chat.respond
memory.retrieve
tool.execute
```

---

## capability

表示需要的能力。

例如：

```
weather.query
web.search
calendar.create
```

注意：

Capability 不等于具体工具。

---

## objective

任务目标。

例如：

正确：

```
查询东京明天天气
```

错误：

```
调用 weather_api()
```

任务目标属于语义层。

具体执行方式由 Comes 决定。

---

## dependencies

任务依赖。

例如：

```
Task A:
查询天气

Task B:
根据天气决定是否提醒

Task B depends on Task A
```

用于形成任务 DAG。

---

# 5. Result Protocol

Result 表示任务执行结果。

结构：

```
Result

- status
- data
- summary
- metadata
```

---

## status

允许：

```
success
failed
partial
cancelled
```

原因：

工具调用成功不代表任务成功。

例如：

API 正常运行，但没有查询结果。

---

## data

完整结果。

例如：

工具返回的 JSON。

---

## summary

压缩后的结果。

用于传递给 Stella。

例如：

完整天气数据：

```
大量 JSON
```

转换：

```
东京明天27℃，晴，降雨概率10%。
```

---

## metadata

记录：

- 来源；
- provider；
- 执行时间；
- 调试信息。

---

# 6. Router 设计

Router 的职责：

> 判断本次请求需要哪些能力。

Router 不负责：

- 记忆写入；
- 工具选择；
- 工具执行；
- 人格回复。

---

# 7. Router 输出

Router 输出 Multi-label Capability 判断：

例如：

用户：

```
你还记得我之前说的旅行计划吗？
帮我查一下东京天气。
```

输出：

```
chat = true

memory = true

tool = true
```

---

# 8. Router 三阶段结构

## Level 0：规则快速判断

目标：

处理高置信度请求。

例如：

```
搜索
查询
帮我找
还记得
之前说过
```

直接生成 Route。

特点：

- 极低延迟；
- 不调用模型。

---

## Level 1：Embedding Semantic Router

模型：

```
qwen3-embedding-0.6b
```

用途：

语义判断。

流程：

```
User Message

      |
      v

Embedding

      |
      v

Capability Prototype Matching

      |
      v

Capability Scores
```

输出：

例如：

```
chat      0.86
memory    0.12
tool      0.91
```

---

## Level 2：高级 fallback

极少量不确定请求：

```
confidence < threshold
```

才考虑使用更强模型判断。

目标：

避免浪费 27B SLM 推理资源。

---

# 9. Capability System

为了保证通用性，引入 Capability Registry。

核心思想：

> 插件不是能力，插件只是能力的实现方式。

---

# 10. Capability Registry

结构：

```
Capability

- id
- description
- examples
- input schema
- providers
```

示例：

```
Capability:

id:
weather.query


description:
查询天气信息


examples:

- 明天天气怎么样
- 会不会下雨
- 东京温度多少
```

---

# 11. Capability 分层

推荐结构：

```
Capability Domain

        |
        v

Capability

        |
        v

Provider

        |
        v

Tool
```

例如：

```
Information

    |

Weather

    |

weather.forecast

    |

AstrBot Weather Plugin

    |

get_forecast()
```

---

# 12. Comes 设计

Comes 是：

> 一个负责执行任务的工具代理。

Comes 不负责：

- 理解用户；
- 判断用户意图；
- 管理人格。

它只负责：

```
Capability
      |
      v
找到 Provider
      |
      v
调用 Tool
      |
      v
返回 Result
```

---

# 13. AstrBot 兼容层设计

AstrBot 插件进入 Stella 时：

```
AstrBot Plugin

       |

Adapter

       |

Capability Registry

       |

Comes
```

插件需要被映射为 Capability。

例如：

AstrBot：

```
get_weather()
```

转换：

```
Capability:

weather.query
```

这样：

- Stella 不依赖 AstrBot；
- Comes 不依赖插件名称；
- 插件生态可替换。

---

# 14. Memory 系统设计

Memory 系统保持现有设计。

包括：

- classification
- filtering
- promotion
- forgetting

不修改核心逻辑。

---

# 15. Router 与 Memory 的关系

Router 只决定：

```
是否需要读取记忆
```

Router 不决定：

```
是否应该保存记忆
```

原因：

记忆形成属于 Memory System 自己的判断。

流程：

```
User Message

      |

Router

      |

Memory Retrieval

      |

Memory Result

      |

Stella
```

---

# 16. Memory Write

记忆写入完全独立：

```
Conversation

      |

Memory Pipeline

      |

classification

      |

filtering

      |

promotion

      |

storage
```

不经过 Router。

---

# 17. 并行执行优化

复杂请求：

```
用户：

记得我的旅行计划吗？
帮我查东京天气。
```

执行：

```
             Router

          /          \

     Memory          Comes

        |              |

        +------+
               |
               v

            Stella

               |

          Final Reply
```

Memory 和 Tool 可以并行。

---

# 18. 最终数据流

完整流程：

```
User

 |

 v

Request

 |

 v

Router

 |

 v

Task Graph

 |

 +------------+-------------+

 |            |             |

 v            v             v

Stella     Memory        Comes

 |            |             |

 |            |          Tool

 |            |             |

 +------------+-------------+

              |

              v

        Final Response

              |

              v

             QQ
```

---

# 19. 后续开发优先级

建议执行顺序：

## Phase 1

完成：

- Task Protocol
- Result Protocol
- Capability Registry


---

## Phase 2

实现：

- Rule Router
- Embedding Router


---

## Phase 3

实现：

- Comes
- AstrBot Adapter


---

## Phase 4

优化：

- Capability 自动注册；
- Router benchmark；
- Provider 自动选择。


---

# 20. 最终目标

Stella 最终形成：

```
自然语言世界

        |

        v

Capability Layer

        |

        v

Task System

        |

        v

Tool Ecosystem
```

实现：

- Stella 与插件解耦；
- 工具不会污染聊天上下文；
- Memory 独立演化；
- AstrBot 生态可接入；
- 未来支持 MCP / API / Native Tool。

核心理念：

> Stella 负责理解人与交流。

> Router 负责决定需要什么能力。

> Memory 负责保存和提供过去。

> Comes 负责执行现实世界操作。

> Capability Layer 负责连接两者。