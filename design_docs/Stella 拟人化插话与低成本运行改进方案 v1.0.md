# Stella 拟人化插话与低成本运行改进方案 v1.0

## 1. 目标

在保留 Stella 现有记忆策略、隐私边界和增量整合能力的前提下，引入 MaiBot 的会话节奏控制能力：

1. 更自然地判断什么时候应该插话；
2. 始终在 8192 tokens 上下文窗口内运行；
3. 普通消息不增加额外 LLM 调用；
4. 深度规划具有明确的调用次数、工具次数和主动发言预算；
5. 防止缓存命中率下降导致部署成本失控。

本方案不直接移植 A_Memorix，也不让每条消息都进入 Planner。

## 2. 总体架构

```text
消息进入
  ↓
SessionRuntime
  ↓
本地 ReplyGate
  ├─ 静默消费：0 次 LLM
  ├─ 快速回复：1 次 LLM
  └─ 深度回复：最多 2 次 LLM
        ↓
     Planner / 工具
        ↓
     Replyer
        ↓
     发送
        ↓
     异步记忆与表达学习
```

核心原则：绝大多数消息在本地完成“是否值得回复”的判断，只有真正需要语言理解的消息才进入 LLM。

## 3. 阶段一：成本与上下文基线

先增加观测，不改变回复行为。

需要记录：

- 每条入站消息是否调用 LLM；
- 调用了几次；
- 快速路径、深度路径和静默路径比例；
- 输入、输出、缓存命中 tokens；
- 是否触发上下文截断；
- 是否调用记忆工具；
- 主动发言后是否得到用户后续回应。

指标：

```text
llm_calls_per_event
fast_path_rate
deep_path_rate
silent_path_rate
prompt_tokens_p50/p95
cached_tokens_ratio
context_budget_exhausted
planner_tool_call_rate
proactive_followup_rate
```

## 4. 阶段二：统一 ContextBudget

所有 Prompt 内容共享同一个 8192 tokens 预算。快速路径不加载 Planner 工具 schema。

### 快速回复预算

```text
系统提示词与格式：1200
最近消息：2200
短期摘要：500
用户画像：300
行为约束：150
聊天记忆：500
当前消息与元数据：500
输出预留：1000
安全余量：1842
```

### 深度回复预算

```text
系统提示词与格式：1200
最近消息：1800
短期摘要：500
用户画像：300
行为约束：250
Episode / 深度记忆：700
当前消息与元数据：500
工具 schema：600
输出预留：1000
安全余量：1142
```

建议新增 `core/context_budget.py`，让所有上下文区域通过统一预算对象申请空间。超预算时按优先级确定性裁剪，不允许直接拼接。

## 5. 阶段三：本地 ReplyGate 与 TurnRuntime

建议新增：

```text
core/reply_gate.py
core/turn_runtime.py
```

ReplyGate 输入：

- 是否被 @ 或明确提及；
- 是否为私聊；
- 是否为问题或请求；
- 是否正在回应 Stella；
- 当前话题相关度；
- 群聊消息速度；
- 最近机器人发言比例；
- 距离上次回复时间；
- cooldown；
- 待处理消息压力；
- ParticipationManager 的插话机会评分。

状态：

```text
IDLE
RUNNING
WAITING
COOLDOWN
INTERRUPTED
```

低分静默，中分快速回复，高分才允许进入深度路径。

接入位置：

```text
ai_gateway.handle_chat
  → ReplyGate
  → Pipeline
```

## 6. 阶段四：缓存与快速路径

现有检索缓存不能简单扩展为 Planner 缓存。

建议区分：

```text
会话上下文缓存：
session_id + history_version + mode + policy_version

语义检索缓存：
shared_space + user + normalized_topic_hash + mode
```

重要话题或历史版本变化时失效缓存。

LLM Prompt 前缀保持稳定：

```text
系统提示词
→ 固定输出格式
→ 固定工具定义
→ 稳定行为规则
→ 动态上下文
→ 当前输入
```

普通回复必须保持单次调用：

```text
本地 Gate
  → Stella Retrieval v2
  → 单次 LLM
  → 回复
```

## 7. 阶段五：受限 Planner

仅在以下情况启动：

- 历史指代；
- 需要旧事件或 Episode；
- 需要工具；
- 当前话题存在歧义；
- 需要等待更多消息；
- 高插话机会但表达方式不明确。

硬限制：

```text
普通路径：最多 1 次 LLM
深度路径：最多 2 次 LLM
每轮最多 1 次深度工具调用
Planner 最多 2 轮
wait 不轮询 LLM
工具结果必须压缩后回填
```

`query_memory` 优先调用 Stella 本地检索；工具只返回压缩后的事实、时间、参与者、置信度和证据。

## 8. 阶段六：表达与插话效果学习

单独存储：

```text
expression_examples
jargon_glossary
behavior_patterns
reply_effects
```

学习用户是否继续回应、复用表达、使用表情、纠正 Stella 或忽略主动发言。该过程放在异步后处理中，不能阻塞主回复路径。

## 9. 验收标准

- 静默路径不调用 LLM；
- 快速路径最多 1 次 LLM；
- 深度路径最多 2 次 LLM；
- 单轮最多 1 次深度记忆查询；
- `wait` 不轮询 LLM；
- 任意路径不超过 8192 tokens；
- 快速路径不包含工具 schema；
- 上下文超预算时能够确定性裁剪；
- 话题变化后不会错误复用旧检索结果；
- 缓存命中率和单次有效回复成本不明显劣化；
- 主动发言具备独立的群级、时间级和每日预算。

## 10. 实施顺序

```text
Phase 0：成本与 token 观测
Phase 1：ContextBudget
Phase 2：ReplyGate + TurnRuntime
Phase 3：缓存 key 与 Prompt 前缀稳定化
Phase 4：受限 Planner
Phase 5：表达、黑话与回复效果学习
```

本轮先实施 Phase 0～Phase 2。Phase 3～Phase 5 保持为后续阶段，不在本轮扩大范围。
