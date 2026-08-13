# Memory Verification Loop（主动记忆获取回路）

- 创建：2026-08-13
- 状态：设计中，未实现
- 前置：`check_point#1.md`（整合器过度生成修复）、`check_point#2.md`（两层过滤重构）

## 1. 设计动机

> 让 agent 主动发言时概率验证目前活跃用户的记忆是否正确。这个效果要比随机接话好得多。

主动发言当前是「随机找个切入口说句话」，只有防刷屏与冷却约束，没有目的。把它改造成**记忆获取与验证的手段**，可同时解决两个问题：发言有了动机，记忆有了来源。

## 2. 诊断依据：被动摄入的期望产出接近零

2026-08-12 夜间试运行（干净 v4 库）实测：

| 指标 | 数值 |
|---|---|
| 摄入群消息 | 985 条 |
| 整合执行 | 全部完成，无遗漏、无解析失败、checkpoint 与日志时间戳一致 |
| `memory_candidates` | **0 条** |
| `memories` | 0 条 |

关键判读：**这不是「筛选严苛」，而是捕获层零产出。** Gate 1 三档、复现强化、每用户配额三套机制一次都没被触发过。

### 2.1 与探针数据的表面矛盾及其解释

探针 `--limit 20`（约 600 条消息）产出 3 条候选，产出率 10%；生产 985 条产出 0 条。差异来自采样偏差，不是机制差异：

`scripts/sample_windows.py` 先按 `signal_score`（长句数 − 图片数）**降序排序**，再取 `windows[:12] + windows[n//2:n//2+8] + windows[-10:]`。而 `--limit 20` 截断到前 20 个，即「全库信号密度最高的 12 个 + 中等 8 个」，刷屏层根本未参与。

**该 10% 对应的是全库信噪比最高的那批窗口，不可外推到生产的自然分布。** 已在探针增加 `--stratum` 分层参数使口径显式化。

### 2.2 结论

被动摄入在 RP 型闲聊群的期望产出趋近于零，且**不是可调参数能改善的**——不是门槛太高，是信息本身不存在。用户在角色扮演与玩梗中不会陈述自己的稳定属性。

推论：`MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` 从「加速通道」变成**唯一的记忆生成路径**。@ 对话的质量直接决定记忆质量，容错空间显著变小。

## 3. 架构定位的改变

原设计把主动验证视为 OBSERVING 队列的出口（把「等复现」变成「主动问」）。既然队列在被动路径下会长期为空，定位需要修正：

| | 原设计 | 修正后 |
|---|---|---|
| 主动发言的角色 | 记忆系统的补充 | **唯一的记忆来源** |
| 首要任务 | 验证已有候选 | **从零获取初始信息** |
| 验证 | 第一阶段目标 | 第二阶段——先有候选才有东西可验证 |

因此「主动状态必须落库」的优先级提升为地基：既然要向用户逐步积累提问，就必须记住问过谁什么、得到了什么，否则每次重启都会重复追问同一个人同一件事——这是最容易招致反感的失败模式。

## 4. 两个核心算法

### 4.1 话题参与概率曲线（双锚点插值）

**要解决的冲突**：现有 `speak_probability` 的语义是「群越活跃越不说话」（间隔 ≤20s → 0.05，20~180s 线性升到 0.5，≥180s → 0），设计意图是「热闹时别插嘴」。新需求要求「频率高时才触发」，方向完全相反。

**不引入模式开关**，改为双锚点线性插值 + 幂次整形，同一函数覆盖两种意图：

```
interval = 最近 PROACTIVE_FREQ_WINDOW 条消息的平均间隔（秒）

interval <= FAST  → prob = PROB_AT_FAST
interval >= SLOW  → prob = PROB_AT_SLOW
中间             → t = (SLOW - interval) / (SLOW - FAST)      # t: 0=慢, 1=快
                   prob = PROB_AT_SLOW + (PROB_AT_FAST - PROB_AT_SLOW) * t**GAMMA
```

- `GAMMA = 1.0` 线性；`> 1` 把高概率压缩到最活跃的一端（更保守）；`< 1` 使曲线更平坦
- 「热闹时插话」（新默认）：`PROB_AT_FAST=0.35`、`PROB_AT_SLOW=0.0`
- 「热闹时闭嘴」（旧行为）：`PROB_AT_FAST=0.05`、`PROB_AT_SLOW=0.5`
- 完全关闭话题参与：两个锚点都设 0

因为群的性质差异很大（闲聊群 vs 技术群），这条曲线必须现场可调，所有参数进 `settings.py` + `.env`。

**话题预热延迟**（对应需求 2.a）：话题刚开始时模型无法总结出主题，贸然插话会答非所问。增加 `PROACTIVE_TOPIC_WARMUP_SECONDS`——当前话题（以 `short_term_context.pending_topic` 变更或首条消息时间为锚）持续时长不足该值时，不参与话题。这与「频率高才触发」是两个独立条件，需同时满足。

### 4.2 每用户 @ 配额（基础 + 频率奖励）

主动 @ 是侵入性最强的行为，必须有硬上限。基础 2 次/天，高频发言者小幅上浮：

```
msgs = 该用户最近 24h 在本群的发言条数
t    = clamp((msgs - BONUS_THRESHOLD_LOW) / (BONUS_THRESHOLD_HIGH - BONUS_THRESHOLD_LOW), 0, 1)
quota = AT_QUOTA_BASE + round(AT_QUOTA_BONUS_MAX * t)
```

默认 `BASE=2`、`BONUS_MAX=2`、`LOW=20`、`HIGH=100`：日发言 ≤20 条的用户配额 2 次，≥100 条的活跃用户 4 次，中间线性过渡。上限封顶在 `BASE + BONUS_MAX`，杜绝「越活跃越被骚扰」的失控。

奖励的依据是双向的：高频发言者本身信息产出多、值得多问；同时他们对群内消息的容忍度也更高。但奖励幅度必须小——`BONUS_MAX` 不建议超过 2。

配额计数必须落库（见 D1），按自然日重置，且**发出提问即计数**，不论用户是否回应。

## 5. 实施拆分

三阶段复杂度差一个量级，必须分批。D1 无行为变化可独立验证，D2 跑通即闭环，D3 风险最高。

### D1：地基（无对外行为变化）

**① Bot 自我发言入库** — 阶段 D2 的致命前置。当前 `record_group_chat` 只处理收到的 `GroupMessageEvent`，bot 自己发出的消息不进 `group_messages`。于是验证场景下整合模型看到的是：

```
消息ID(1) 用户(1001) [对Bot说]: 对，是的
```

「对」在确认什么？语境在 bot 的提问里，而那句提问不存在。结果要么无法生成候选，要么模型自行编造语境——恰好是 check_point#1/#2 花两天修掉的问题。

改动：`source_kind` 枚举增加 `BOT_SELF`；`ai_gateway` 在 `chat_handler` 与 `_proactive_speak_for_group` 发送成功后把自己的台词写入 `group_messages`；`consolidator._fetch_next_messages` 对该来源标注 `[我说]`。

约束：`BOT_SELF` 消息**只作上下文，绝不产出候选**。prompt 需明示「标注 `[我说]` 的是我自己的发言，不要从中提取关于任何用户的信息」；代码侧 `_write_memory_candidates` 的发送者白名单天然会挡掉 bot 自身 QQ 号，双重保险。

**② 按用户的活跃度追踪** — `ProactiveController._timestamps` 现为 `dict[group_id, list[float]]`，`record_message(group_id)` 不接收 user_id，「检测到目标用户正在活跃」所需信息不存在。改为 `dict[group_id, dict[user_id, list[float]]]`，并新增：

- `user_average_interval(group_id, user_id)` — 该用户的发言间隔
- `active_users(group_id, within_seconds)` — 近期活跃用户列表（D2 的选人依据）
- `user_message_count_24h(group_id, user_id)` — 配额奖励的输入

群级 `average_interval` 保留（D3 用），实现改为聚合各用户时间戳。

**③ 主动状态落库** — 现有状态全在内存且用 `time.monotonic()`（重启后基准漂移，不可持久化）。新建表：

```sql
CREATE TABLE IF NOT EXISTS proactive_state (
    group_id TEXT,
    user_id TEXT,              -- 群级记录用 '0'
    at_count_today INTEGER DEFAULT 0,
    at_count_date TEXT,        -- 自然日，用于跨日重置
    last_at_at DATETIME,       -- 上次主动 @ 该用户的时间
    last_asked_topic TEXT,     -- 上次问的主题（避免重复追问）
    last_asked_candidate_id TEXT,
    consecutive_no_reply INTEGER DEFAULT 0,  -- 连续未获回应次数
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (group_id, user_id)
);
```

`consecutive_no_reply` 是自我约束：连续 `PROACTIVE_MAX_NO_REPLY` 次无人回应即暂停对该用户的主动 @（进入更长冷却），避免对着不想聊的人反复搭话。

Schema 版本推进到 v5，走既有 additive 迁移。

### D2：主动获取与验证（需求 (1)）

**选人策略**（按优先级）：

1. 有 OBSERVING 候选且 `confidence` 最接近晋升线的活跃用户 —— 验证一次即可跨过门槛，收益最高
2. 无候选但近期活跃、当日配额未用尽的用户 —— 冷启动，从日常话题切入
3. 都没有 → 不发言

同时排除：当日配额已满、处于 `PROACTIVE_AT_USER_COOLDOWN` 内、`consecutive_no_reply` 超限。

**两种发言模式**：

- **验证式**：把候选内容转成一句自然的确认。要求「像朋友随口一问」，不能像审问，且**不得直接复述候选原文**（暴露内部状态，且措辞生硬）
- **冷启动式**：从 `PROACTIVE_COLDSTART_TOPICS`（日常/天气/偏好试探，可配置）里挑一个，结合当前群话题自然切入

**问答关联采用隐式方案**：不建立「提问 ↔ 回答」的显式追踪。用户的回答本身是 `AT_MENTION`，经整合会生成或强化同内容候选，`occurrence_count` +1 后跨过门槛。理由：显式关联需要一整套状态机与超时处理，而隐式方案复用已建成的复现强化机制，v1 足够。`last_asked_candidate_id` 仅用于避免重复追问，不参与判定。

**回应检测**：发出提问后 `PROACTIVE_REPLY_WINDOW_SECONDS` 内，该用户若有任何发言即视为有回应，`consecutive_no_reply` 归零；否则 +1。

### D3：话题连续参与（需求 (2)）

**触发条件**（需同时满足）：群平均间隔达到活跃标准（4.1 曲线）、当前话题持续超过 `PROACTIVE_TOPIC_WARMUP_SECONDS`、不在群级冷却内、概率命中。

**话题总结防编造**（需求 2.b）：参与前用 27B 快速总结「正在进行的话题」。这一步的 prompt 必须沿用捕获层的防编造原则——总结不出明确主题时输出「无」，并据此放弃本次参与。宁可不说，不可硬凑。

**会话状态机**（需求 2.c）：

```
IDLE ──概率命中+条件满足──> ENGAGED ──静默超时/轮次上限──> IDLE（结束时整合一次）
                                │
                                └─ 会话期内响应非 @ 消息（有硬上限）
```

会话上下文用**滚动窗口 + 纯代码拼接**，不每轮调模型压缩：27B 在 GPU 上回复约 2 秒，但每轮额外加一次压缩调用会让响应从 2 秒变 4 秒以上，且 `chat_llm_lock` 全局串行会放大延迟。仅在会话结束时整合一次即可——那时才需要把整段对话浓缩成记忆。

**这是整个阶段 D 风险最高的部分**：`is_chat_trigger` 当前要求 `event.is_tome()`，会话期内要对未 @ 自己的消息作出回应，是触发模型的根本改变。必须有多重硬限制：

- `PROACTIVE_SESSION_MAX_TURNS` — 单次会话最多发言轮数（建议 3）
- `PROACTIVE_SESSION_IDLE_TIMEOUT` — 静默即结束（建议 90 秒）
- `PROACTIVE_SESSION_MIN_GAP` — 两次会话之间的最小间隔
- 沿用现有 `recently_spoken` 相似度去重
- 全局开关 `PROACTIVE_SESSION_ENABLED` 默认 **false**，D2 稳定后再开

## 6. 配置项清单（全部进 `settings.py` + `.env.example`）

```python
# ---------- 主动发言 v2：话题参与概率曲线 ----------
PROACTIVE_INTERVAL_FAST            # 视为「高频」的平均间隔上界（秒），默认 20
PROACTIVE_INTERVAL_SLOW            # 视为「冷清」的平均间隔下界（秒），默认 180
PROACTIVE_PROB_AT_FAST             # 高频端概率，默认 0.35（旧行为设 0.05）
PROACTIVE_PROB_AT_SLOW             # 冷清端概率，默认 0.0（旧行为设 0.5）
PROACTIVE_PROB_GAMMA               # 曲线整形指数，默认 1.0（>1 更保守）
PROACTIVE_TOPIC_WARMUP_SECONDS     # 话题预热时长，默认 45

# ---------- 主动发言 v2：每用户 @ 配额 ----------
PROACTIVE_AT_ENABLED               # 主动 @ 总开关，默认 true
PROACTIVE_AT_QUOTA_BASE            # 基础配额（次/天），默认 2
PROACTIVE_AT_QUOTA_BONUS_MAX       # 高频用户最多上浮，默认 2
PROACTIVE_AT_BONUS_MSGS_LOW        # 奖励起点（24h 发言数），默认 20
PROACTIVE_AT_BONUS_MSGS_HIGH       # 奖励满点，默认 100
PROACTIVE_AT_USER_COOLDOWN         # 同一用户两次主动 @ 的最小间隔（秒），默认 7200
PROACTIVE_AT_ACTIVE_WITHIN         # 判定「正在活跃」的时间窗（秒），默认 300
PROACTIVE_MAX_NO_REPLY             # 连续无回应上限，超过则暂停追问，默认 2
PROACTIVE_REPLY_WINDOW_SECONDS     # 回应检测窗口，默认 300
PROACTIVE_COLDSTART_TOPICS         # 冷启动话题清单（逗号分隔）

# ---------- 主动发言 v2：连续参与会话 ----------
PROACTIVE_SESSION_ENABLED          # 默认 false（D3 稳定前不开）
PROACTIVE_SESSION_MAX_TURNS        # 单会话最大发言轮数，默认 3
PROACTIVE_SESSION_IDLE_TIMEOUT     # 静默超时（秒），默认 90
PROACTIVE_SESSION_MIN_GAP          # 会话间最小间隔（秒），默认 600
PROACTIVE_SESSION_CONTEXT_TURNS    # 滚动上下文保留轮数，默认 6
```

保留但语义变更：`PROACTIVE_MIN_PROB` / `PROACTIVE_MAX_PROB` / `PROACTIVE_HIGH_FREQ_INTERVAL` / `PROACTIVE_LOW_FREQ_INTERVAL` 被新曲线取代，标记废弃并保留定义以兼容既有 `.env`。

## 7. 风险与对策

| 风险 | 表现 | 对策 |
|---|---|---|
| 主动 @ 招致反感 | 用户被反复搭话 | 每用户日配额 + 用户级冷却 + `consecutive_no_reply` 自动退避 |
| 重启后重复追问 | 同一人同一问题被问两次 | 状态落库（D1-③），`last_asked_*` 与配额计数持久化 |
| 缺语境导致编造 | 「对」「是的」这类回答被误解 | Bot 自我发言入库 + `[我说]` 标注（D1-①） |
| 从自我发言提取记忆 | bot 把自己的话记成用户属性 | prompt 明示 + 发送者白名单双重拦截 |
| 话题总结硬凑 | 总结不出主题却强行插话 | 总结允许输出「无」，无主题即放弃 |
| 会话失控刷屏 | 连续发言几十轮 | 轮次上限 + 静默超时 + 会话间隔 + 相似度去重 + 默认关闭 |
| 验证式发言暴露内部状态 | 复述候选原文，措辞生硬 | prompt 要求自然转述，禁止直接引用候选文本 |

## 8. 验证方式

**D1** — 纯 pytest，无需模型：`BOT_SELF` 落库与 `[我说]` 标注、bot 自身发言不产出候选、按用户活跃度统计、配额计数与跨日重置、`consecutive_no_reply` 退避。同时新增护栏：断言 `BOT_SELF` 消息的发送者不会出现在候选白名单内。

**D2** — 探针扩展：构造「bot 提问 + 用户回答」的合成窗口，验证候选能否正确生成/强化，且归属为用户而非 bot。人工验证发言的自然度。

**D3** — 需真实群环境观察。关键指标：单会话平均轮数、被判定「话题转移」的准确性、有无刷屏投诉。

**共同指标**（对照 check_point#2 的基线）：

| 指标 | 被动路径基线 | D2 目标 |
|---|---|---|
| 候选产出 | 0 条 / 985 消息 | > 0 |
| 编造率 | 0% | 保持 0% |
| 每用户 active 记忆 | 0 | 逐步积累至配额内 |

## 9. 遗留问题

- RP 台词被当作真人属性的风险仍未解决。主动 @ 场景下用户更可能出戏回答，风险降低但不为零；`occurrence_count` 与来源门槛是现有防线
- `MEMORY_QUOTA_ENFORCE` 仍为 false。在记忆开始积累后才有观察意义
- `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE=2` 在被动路径下等于永不满足。是否下调需等主动路径产出数据后再评估——现在调它没有依据。