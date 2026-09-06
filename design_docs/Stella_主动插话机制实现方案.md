# Stella 主动插话机制 · 落地实现方案（v1.1）

> 状态：已定稿，进入实施
> 上游文档：`design_docs/Stella_主动插话机制工程方案.md`（架构原则与评分模型）
> 本文：将上游架构映射到现有代码结构的具体修改方案
>
> 额外要求（v1.1）：
> 1. 打分结果全程输出日志，过程可视化。
> 2. 所有打分表（权重/阈值/词表/兴趣锚）外置为数据文件，禁止内嵌代码。
> 3. 提供基于数据库真实群聊数据的模拟 benchmark 用于调试与评估。

---

## 0. 总体思路

现有代码已有一套"频率掷骰子式"主动发言机制（`memory/proactive*.py` + `ai_gateway.py` 中的定时任务）。本方案将其升级为"基于群聊状态的评分决策层"：

- 消息路径天然分离：`is_tome()` 走 `handle_chat`（Hard Trigger），被动消息走 `group_silent_listener`（优先级 0，唯一逐条看到所有群消息的位置）。上游原则 7 已成立，不改动 @ 触发链路。
- 新层挂在被动消息路径上：输入为 OneBot 事件 + `group_messages` 近期尾部，输出为 `ParticipationDecision`（should_speak / score / mode / topic_id / reason_flags）。
- 命中 `ALLOW_LLM` 时复用 `_proactive_speak_for_group` 已有的执行管线（群锁、预算门、consolidate、`pipeline.run(trigger="proactive")`、行数截断、`recently_spoken` 去重、发送）。
- 替换关系：评分层替换 `ProactiveController.should_speak` 的掷骰子逻辑；保留 `proactive_gate.can_speak` 的全部硬性闸门（总开关/静音/睡眠窗口/冷却/最少新消息数）作为评分之前的准入检查。
- 第一版零 LLM 调用（上游原则 8）：评分完全由规则 + 状态机 + 可选 embedding 完成。

---

## 1. 新增模块：`memory/participation/`

```
memory/participation/
├── __init__.py          # get_participation_manager() 单例，对 ai_gateway 暴露唯一入口
├── buffer.py            # MessageBuffer：每群内存环形缓冲（默认 200 条）
├── state.py             # ConversationState + TopicStateMachine（NEW/ACTIVE/COOLING/EXPIRED）
├── scorer.py            # ParticipationScorer：9 项指标加权求和 → 0~100 分
├── signals.py           # 信号提取：开放问题/悬念/充分回应/社交钩子的规则识别
├── decision.py          # ParticipationDecision + 阈值状态机(IGNORE/OBSERVE/CANDIDATE/ALLOW_LLM)
└── observability.py     # 评分日志（loguru + JSONL + Markdown）
```

### 1.1 MessageBuffer
- 每群一个内存 deque，字段：`timestamp / sender_id / text / reply_to / mentioned_users / has_image / has_emoji / message_type / embedding`。
- 数据来源：`group_silent_listener` 已解析好的 OneBot 事件，不二次查库。
- embedding 懒计算：仅在话题建立/换话题/进入 CANDIDATE 时对关键消息调 `EmbeddingService.embed`。
- 重启恢复：从 `group_messages` 表回填最近 N 条（`memory/pre_processors.py::_fetch_recent_tail` 同源查询）。

### 1.2 ConversationState + Topic 状态机
- 每群维护单个状态：当前 topic、参与者集合、消息速度（30s 滑窗离散化 LOW/MEDIUM/HIGH/VERY_HIGH）、`stella_involved`、Stella 发言统计。
- 话题切换（第一版规则优先）：新消息与当前 topic 最近 K 条文本 embedding 余弦相似度低于阈值（默认 0.45，可调）且满足"参与者转移/距上次活跃超时"→ 旧 topic 置 COOLING，新消息建 NEW topic。embedding 不可用时退化为时间间隔 + 参与者变化 + 承接词（"对了/另外"）。
- COOLING→EXPIRED 由低频定时任务推进，不依赖新消息。
- topic 状态持久化到 `participation_topics` 表，重启后不丢失 EXPIRED 判定。

### 1.3 ParticipationScorer
9 项独立打分函数（分值范围见 `config/participation/weights.toml`）：

- **Relevance（0~30）**：Long-Term 来自 `topics.toml` 兴趣锚（关键词 + embedding 相似度取 max）；Current Relevance 来自"Stella 最近 30 分钟参与过的话题"短期加权。
- **Opportunity（-20~30）/ SocialOpportunity（0~20）**：由 `signals.py` 规则识别器产出（词表在 `signals.toml`）：开放问句、未完成表达、已被充分回应、高速消息流、悬念/强情绪钩子。
- **TopicInvolvement（0~20）**：`stella_involved` 时提高继续参与倾向。
- **SilenceBonus（0~10）**：随距上次发言时间增长、封顶。
- **RecentSpeechPenalty（0~60）/ RepetitionPenalty（0~20）**：数据源为 `proactive_state` 表 + 本 topic 主动发言计数。区分被动应答与主动插话（`handle_chat` 的发言记为被动，不累积同等级惩罚）。
- **MessageVelocityPenalty（0~30）/ TopicExpiredPenalty（0~40）**：直接读状态机与速度窗口。

### 1.4 阈值与 Candidate 机制
- 每群一个 candidate 槽位：得分 ≥60 进入 CANDIDATE（不立即触发）；下一条消息重算，仍 ≥60 → `ALLOW_LLM`；跌破 → 清除。
- 例外：强社交钩子（SocialOpportunity≥18 且 score≥80）允许直通 `ALLOW_LLM`。
- ParticipationMode 五种（DIRECT_MENTION / DIRECT_RELEVANCE / CONTINUE_EXISTING_CONVERSATION / TOPIC_INTEREST / SOCIAL_HOOK）；本层只产生后四种，写入 `ChatContext.intent` 透传，第一版不消费。

---

## 2. 现有文件修改点

### 2.1 `stella_project/plugins/bot_main/ai_gateway.py`
1. `group_silent_listener`：在 `get_proactive().record_message(...)` 后追加 `get_participation_manager().observe(group_id, event)`。保持 block=False、priority 0 不变。observe 内部完成缓冲→状态→评分→状态机；产出 ALLOW_LLM 时以 asyncio task 走统一执行器。
2. 改造 `_proactive_speak_for_group` 为参数化共用执行器（intent、instruction 可变），决策层与兜底定时任务共用。
3. `proactive_speak_job` 职责收缩：(a) 推进 COOLING→EXPIRED 与清理；(b) 兜底插话（长时沉默但存在未过期 topic 的低频机会）。`PARTICIPATION_ENABLED=true` 时掷骰子路径不再触发。
4. `handle_chat` 中 `record_spoken` 增加 `kind="passive"` 区分惩罚等级。

### 2.2 `memory/proactive.py` / `proactive_gate.py`
不删除。`should_speak` 掷骰子分支用 `PARTICIPATION_ENABLED` 旁路；`recently_spoken`、`mark_spoke`、`record_tome` 继续使用；`can_speak` 全部保留。

### 2.3 `memory/schema.py`：版本 v3→v4（additive 迁移），新增两表
- `participation_topics`：`group_id, topic_id, label, status, started_at, last_active_at, stella_involved, speak_count`
- `participation_log`：文档 §29 全字段评分日志（调参依据）

### 2.4 `config/settings.py`：新增 `PARTICIPATION_*` 配置段
仅行为开关类参数（enabled、buffer 大小、速度窗口、cooling/expire 时长、打分表目录路径、日志级别）；数值权重/阈值/词表一律在外置表中（见 §B）。

---

## 3. 补充要求 A：打分结果全程可视化

1. **loguru 实时日志**：`📊 [参与评分]` 标签，每次评分一行摘要（群号/score/decision/主要加减分项）。
2. **结构化 JSONL**：`logs/participation_decisions.jsonl`，字段按上游文档 §29：各指标分项、总分、decision、mode、topic_id、reason_flags、群快照。
3. **Markdown 人类可读日志**：按天写 `logs/participation_logs.md`，格式即上游文档 §29 示例块。
4. **status API**（可选）：`status_api.py` 增加 participation 端点，返回每群 ConversationState 快照与最近决策。

配置：`PARTICIPATION_LOG_LEVEL`（full/summary/off，默认 full）；off 时 ALLOW_LLM 级别决策仍强制记录。

## 4. 补充要求 B：打分表外置（禁止内嵌代码）

```
config/participation/
├── weights.toml        # 9 项指标加/减分值与上下限（上游 §17 表的机器可读版）
├── thresholds.toml     # 分级阈值、二次确认参数、强钩子直通条件
├── signals.toml        # 信号词表：开放问句/悬念/情绪/认可性回应/低信息量/承接词
└── topics.toml         # 长期兴趣锚：关键词 + 兴趣描述文本
```

- scorer 中不出现任何数值常量。
- 加载器支持热重载（接入现有 admin reload 机制），调参不改代码不重启。
- 加载时完整性校验（指标覆盖齐全、词表非空、无未知引用），失败拒绝启动。
- `.env.example`、`docs/configuration.md` 同步更新。

## 5. 补充要求 C：Benchmark（基于真实群聊数据）

```
tests/benchmark/participation/
├── runner.py           # 回放驱动器：按时间序重放 group_messages 真实数据
├── scenarios.toml      # 场景定义（对应上游 §30 情况 A~F）
├── metrics.py          # 评估指标
└── reports/            # markdown 摘要 + JSONL 明细
```

- 数据源：`group_messages` 表真实历史（PASSIVE 逐条喂 observe()，BOT_SELF 还原发言统计）；支持时间窗/群号筛选与脱敏。
- 六场景通过标准：
  | 场景 | 通过标准 |
  |---|---|
  | A 被明确发问 | 100% 触发（Hard Trigger 旁路验证） |
  | B 高速刷屏 | 插话率 ≤ 阈值 |
  | C 强社交钩子 | 至少进入 CANDIDATE |
  | D 感兴趣无机会 | 允许全程沉默 |
  | E 刚说过话 | 平均分显著低于基线 |
  | F 话题已过期 | 不触发（必须建新 topic） |
- 指标：各场景触发率（FP/FN）、分数分布、CANDIDATE→ALLOW 转化/Cancel 率、决策延迟。
- 调参闭环：改打分表 → 重跑 → 报告 diff。
- 准入：阶段④接通真实发送的前提 = 场景 A/B/D/F 通过（先压 False Positive）。

---

## 6. 实施顺序

| 阶段 | 内容 | 交付物 |
|---|---|---|
| ① | schema v4 + MessageBuffer + observe() 挂载（只记日志不触发） | 可观察评分但零行为变化 |
| ② | ConversationState + Topic 状态机 + 持久化 | 话题生命周期可调 |
| ③ | scorer + signals + 阈值状态机 + participation_log | 离线核对分数 |
| ④ | 接通执行器，开关灰度 | 第一轮真实群聊测试 |
| ⑤ | ParticipationMode 透传 + 定时任务职责收缩 + benchmark | 完整第一版 |

①~③ 完成前不改变任何发言行为。

## 7. 风险与缓解

- 高频路径性能：observe() 全内存；embedding 懒计算带 gate，可降级为规则。
- 与 `proactive_at_user` 冲突：第一版独立不动，后续再统一。
- 群多内存：状态按群惰性创建 + LRU 上限（64），超限置 EXPIRED 释放。
- 重启丢 candidate：允许丢失（等价 Cancel）。
