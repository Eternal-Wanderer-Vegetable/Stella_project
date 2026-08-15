# 配置参考

配置集中在 [`config/settings.py`](../config/settings.py)，通过读取项目根目录的 `.env` 导出模块级常量。业务代码不需要改动该文件即可调参。

```bash
cp .env.example .env
```

按 `ENVIRONMENT` 可加载环境覆盖文件：`dev` / `development` → `.env.dev`，`prod` / `production` → `.env.prod`（覆盖 `.env` 中的同名项）。

布尔值接受 `true` / `1` / `yes`（大小写不敏感），其余视为 false。

## 最小可用配置

```env
ALLOWED_GROUPS=123456789
LM_STUDIO_BASE_URL=http://127.0.0.1:1234
LM_STUDIO_MODEL=your-chat-model
CONSOLIDATION_LM_STUDIO_MODEL=your-small-model
```

---

## 群聊与路径

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `ALLOWED_GROUPS` | 空 | 允许响应的群号，逗号分隔。**留空则不响应任何群** |
| `SYSTEM_PROMPT_PATH` | `memory/SYSTEM.md` | 系统提示词文件 |
| `DB_PATH` | `memory/agent_memory.db` | SQLite 数据库 |
| `THOUGHT_LOG_PATH` | `stella_thought_logs.md` | 思考过程日志 |
| `EXTENSIONS_DIR` | `extensions/` | 扩展自动加载目录 |
| `CONSOLIDATION_LOG_PATH` | `memory_consolidation_log.md` | 整合过程日志 |
| `MEMORY_BENCHMARK_DIR` | `memory/benchmark` | Benchmark 用例目录 |

路径类配置若在 `.env` 中设置，会被解析为绝对路径。

## 模型服务

### 主聊天模型

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `LM_STUDIO_BASE_URL` | `http://127.0.0.1:1234` | LM Studio 地址 |
| `LM_STUDIO_MODEL` | 空 | 模型 ID，留空由服务端默认路由 |
| `LLM_TIMEOUT` | `90.0` | 单次生成超时（秒） |

### 记忆整理模型

整合与聊天分离，可指向同一实例的不同模型或独立端口。**建议整合模型走 CPU 推理**，避免与主聊天模型抢占显存。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `CONSOLIDATION_LM_STUDIO_BASE_URL` | 同 `LM_STUDIO_BASE_URL` | 整合服务地址 |
| `CONSOLIDATION_LM_STUDIO_MODEL` | `google/gemma-4-e4b` | 整合模型 ID |
| `CONSOLIDATION_LM_STUDIO_TEMPERATURE` | `0.3` | 低温保证 JSON 输出稳定 |
| `CONSOLIDATION_LOCAL_BATCH_SIZE` | `30` | 常规整合批次大小 |
| `CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE` | `10` | force 路径（@ 触发/主动发言前）的小批次 |
| `CONSOLIDATION_OVERLAP` | `15` | 向前回看条数，保证话题不被批次边界切断 |
| `CONSOLIDATION_LOCAL_MAX_TOKENS` | `1200` | 整合最大生成 token |
| `CONSOLIDATION_TRIGGER_NEW_MESSAGES` | `10` | 累积多少新消息才触发一次整合 |

> **注意 `CONSOLIDATION_LOCAL_MAX_TOKENS`**：批次 30 + overlap 15 意味着单次最多喂入 45 条消息，输出被截断会导致 JSON 解析失败，而解析失败时 checkpoint **仍会推进**（防止同批反复重跑），那批消息就永久丢失了。`core/llm/lm_studio.py` 会在 `finish_reason=length` 时输出告警，建议运行一段后检查日志有无该告警。

### 向量语义检索（可选）

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_EMBEDDING_ENABLED` | `false` | 关闭时用规则版词面语义（离线、确定） |
| `MEMORY_EMBEDDING_BASE_URL` | `http://127.0.0.1:1234` | embedding 服务地址 |
| `MEMORY_EMBEDDING_MODEL` | 空 | 向量模型 ID |
| `MEMORY_EMBEDDING_TIMEOUT` | `10.0` | 单次请求超时（秒） |
| `MEMORY_EMBEDDING_CONTEXTUAL_MIN` | `0.25` | embedding 路径下 `CONTEXTUAL` 记忆的主题匹配余弦阈值 |

服务或模型不可用时**自动回退规则版**，链路不中断。

## 上下文

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `RECENT_TAIL_LIMIT` | `12` | 每次回复附加的最近原始消息条数（含 Bot 自己的发言） |
| `MAX_REPLY_LINES` | `5` | 单次回复最大行数 |
| `SEND_INTERVAL` | `0.8` | 多行之间的发送间隔（秒） |
| `FALLBACK_REPLY` | `......？` | 兜底回复 |
| `BAD_PHRASES` | 见 settings.py | 破防语句清单，命中即替换为兜底回复 |

> **`RECENT_TAIL_LIMIT` 的权衡**：太小会让活跃群的刷屏把 Bot 自己的提问挤出窗口，用户的简短回应（「手机」「对」）会被接到上一个话题上；太大则无关历史干扰模型且 prompt 变长。12 是起点，需按群的刷屏速度调整。

`RECENT_MESSAGE_LIMIT` 已废弃（被 `RECENT_TAIL_LIMIT` 取代），保留定义以兼容既有 `.env`。

## 记忆：捕获与晋升

### 来源分级与候选强化

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_SOURCE_KIND_ENABLED` | `true` | 关闭后所有消息等权，prompt 不标注来源 |
| `MEMORY_AT_MENTION_CONFIDENCE_BONUS` | `0.05` | `AT_MENTION` 来源候选的置信度奖励 |
| `MEMORY_CANDIDATE_REOCCURRENCE_BONUS` | `0.12` | 同一事实复现时的置信度增益 |
| `MEMORY_CANDIDATE_MAX_OBSERVING_DAYS` | `30` | 观察区停留上限，超期标 `REJECTED`（不删除） |
| `MEMORY_CANDIDATE_EVIDENCE_MAX_CHARS` | `800` | `evidence` 累积上限 |

`0.12` 的取值使 0.5 起步的候选约 2 次复现后跨过 0.6 门槛。

### Gate 1 三档

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_CONFIRM_HIGH_CONFIDENCE` | `0.85` | 达到即直接晋升 |
| `MEMORY_OBSERVE_LOW_CONFIDENCE` | `0.6` | 达到则看证据充分度 |
| `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE` | `2` | 被动来源晋升所需的最低观察次数 |
| `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` | `true` | `AT_MENTION` 来源是否单次即可晋升 |
| `MEMORY_PROMOTE_MIN_IMPORTANCE` | `0.3` | 晋升所需的最低重要度（下限，不单独构成依据） |

`MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE` / `MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE` 已废弃（被三档取代），保留定义以兼容既有 `.env`。

### 每用户配额

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_QUOTA_ENFORCE` | **`false`** | 关闭时只输出 dry-run 日志，不实际淘汰 |
| `MEMORY_USER_QUOTA` | `25` | 单用户在单群的 active 记忆上限 |
| `MEMORY_QUOTA_W_IMPORTANCE` | `0.4` | 竞争分权重：重要度 |
| `MEMORY_QUOTA_W_CONFIRMATION` | `0.3` | 竞争分权重：被确认次数 |
| `MEMORY_QUOTA_W_RECENCY` | `0.3` | 竞争分权重：近期访问 |
| `MEMORY_QUOTA_CONFIRMATION_CAP` | `3` | 确认次数归一化上限 |

> **开启前先观察**。`MEMORY_QUOTA_ENFORCE=false` 时日志会输出 `[Quota dry-run] ... 本来会淘汰 xxx`，确认淘汰对象合理后再开启。淘汰是置 `archived` 而非删除，但恢复需要手工 SQL。

## 记忆：检索与排序

### RAG 开关

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `RAG_ENABLED` | `true` | 关闭则永远走加权回退排序 |
| `RAG_SQLITE_FTS_ENABLED` | `true` | 是否使用 FTS5 全文索引 |
| `RAG_TOP_K` | `5` | FTS 候选池下限 |
| `MEMORY_V2_ENABLED` | `true` | 关闭则回退旧检索与旧 Prompt 组装 |

### 排序权重

六维加权，权重和约为 1.0。原则是 **Policy / Context 优先于相似度**——避免「找错」而非「找不到」。

| 配置项 | 默认值 | 维度 |
|---|---|---|
| `MEMORY_SCORE_W_CONTEXT` | `0.25` | 上下文契合（触发条件 / 用途契合度） |
| `MEMORY_SCORE_W_USAGE` | `0.20` | 用途与当前模式的匹配度 |
| `MEMORY_SCORE_W_SEMANTIC` | `0.35` | 语义相似（embedding 余弦或词面回退） |
| `MEMORY_SCORE_W_RECENCY` | `0.10` | 时效衰减（指数，τ=30 天） |
| `MEMORY_SCORE_W_CONFIDENCE` | `0.05` | 置信度 |
| `MEMORY_SCORE_W_IMPORTANCE` | `0.05` | 重要度 |

`confidence` / `importance` 权重刻意压低：它们描述「记忆本身可靠/重要」，与「当前该不该用这条」关系弱，只适合做 tie-breaker。

未启用 embedding 时，语义维会被丢弃并把剩余权重重新归一化。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_SCORE_MIN` | `0.40` | 低于此分不进 Prompt（动态数量而非固定 Top-K） |
| `MODE_DETECT_MIN_SCORE` | `0.5` | Mode 检测的最低得分，低于则回退 `CASUAL_REPLY` |
| `USAGE_TYPE_MISMATCH_PENALTY` | `0.75` | 用途与类型不兼容时的降权系数（非硬排除） |

### 各模式记忆条数上限

| 配置项 | 默认值 |
|---|---|
| `MEMORY_LIMIT_CASUAL_REPLY` | `3` |
| `MEMORY_LIMIT_ACTIVE_JOIN` | `3` |
| `MEMORY_LIMIT_HUMOR` | `3` |
| `MEMORY_LIMIT_TECH_HELP` | `5` |
| `MEMORY_LIMIT_RECOMMEND` | `5` |
| `MEMORY_LIMIT_EMOTIONAL` | `3` |
| `MEMORY_LIMIT_CONFLICT_AVOID` | `10` |
| `MEMORY_LIMIT_GROUP_EVENT` | `5` |

`CONFLICT_AVOID` 上限最大是安全优先——行为约束宁多勿漏。

### Prompt 长度预算

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_CONVERSATION_MAX_TOKENS` | `500` | 聊天素材区上限 |
| `MEMORY_CONVERSATION_TECH_MAX_TOKENS` | `1000` | 技术场景放宽 |
| `MEMORY_BEHAVIOR_MAX_TOKENS` | `150` | 行为约束区上限 |

### 旧检索（`MEMORY_V2_ENABLED=false` 时生效）

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `PROACTIVE_LONG_TERM_LIMIT` | `10` | 主动发言时引用的记忆条数 |
| `REPLY_LONG_TERM_LIMIT` | `3` | @ 回复时引用的该用户记忆条数 |
| `LONG_TERM_RELEVANCE_ENABLED` | `true` | 是否对他人旧记忆做关键词相关度筛选 |
| `LONG_TERM_RELEVANCE_KEYWORDS` | `5` | 提取的关键词数量 |
| `LONG_TERM_RELEVANCE_CANDIDATE_LIMIT` | `20` | 候选池上限 |
| `LONG_TERM_RELEVANCE_WEIGHT_KEYWORDS` | `2.0` | 加权：关键词重叠 |
| `LONG_TERM_RELEVANCE_WEIGHT_RECENCY` | `1.0` | 加权：最近访问 |
| `LONG_TERM_RELEVANCE_WEIGHT_IMPORTANCE` | `1.2` | 加权：重要度 |
| `LONG_TERM_RELEVANCE_WEIGHT_CONFIDENCE` | `0.8` | 加权：置信度 |
| `LONG_TERM_RELEVANCE_WEIGHT_USER_RELEVANCE` | `0.6` | 加权：用户相关性 |

## 主动发言

### 话题参与概率曲线

双锚点插值 + 幂次整形。同一条曲线通过参数即可表达两种相反意图，无需模式开关。

```
interval <= FAST → PROB_AT_FAST
interval >= SLOW → PROB_AT_SLOW
中间             → t = (SLOW - interval) / (SLOW - FAST)
                   prob = PROB_AT_SLOW + (PROB_AT_FAST - PROB_AT_SLOW) × t^GAMMA
```

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `PROACTIVE_ENABLED` | `true` | 主动发言总开关 |
| `PROACTIVE_INTERVAL_FAST` | `20.0` | 视为「高频」的平均间隔上界（秒） |
| `PROACTIVE_INTERVAL_SLOW` | `180.0` | 视为「冷清」的平均间隔下界（秒） |
| `PROACTIVE_PROB_AT_FAST` | `0.35` | 高频端概率 |
| `PROACTIVE_PROB_AT_SLOW` | `0.0` | 冷清端概率 |
| `PROACTIVE_PROB_GAMMA` | `1.0` | 曲线整形指数，>1 更保守 |
| `PROACTIVE_TOPIC_WARMUP_SECONDS` | `45.0` | 话题预热时长，不足则不参与 |
| `PROACTIVE_COOLDOWN` | `120` | 群级硬冷却（秒） |
| `PROACTIVE_CHECK_INTERVAL` | `30` | 定时检查间隔（秒） |
| `PROACTIVE_FREQ_WINDOW` | `10` | 频率估算窗口（最近 N 条消息） |
| `PROACTIVE_MAX_LINES` | `1` | 主动插话最大行数 |

**三种预设**：

```env
# 热闹时插话（默认，适合闲聊群）
PROACTIVE_PROB_AT_FAST=0.35
PROACTIVE_PROB_AT_SLOW=0.0

# 热闹时闭嘴（旧行为，适合技术群）
PROACTIVE_PROB_AT_FAST=0.05
PROACTIVE_PROB_AT_SLOW=0.5

# 完全关闭话题参与（保留主动 @）
PROACTIVE_PROB_AT_FAST=0.0
PROACTIVE_PROB_AT_SLOW=0.0
```

`PROACTIVE_MIN_PROB` / `PROACTIVE_MAX_PROB` / `PROACTIVE_HIGH_FREQ_INTERVAL` / `PROACTIVE_LOW_FREQ_INTERVAL` 已废弃（被双锚点曲线取代），保留定义以兼容既有 `.env`。

### 主动 @ 用户

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `PROACTIVE_AT_ENABLED` | `true` | 主动 @ 总开关 |
| `PROACTIVE_AT_QUOTA_BASE` | `2` | 每用户每日基础配额 |
| `PROACTIVE_AT_QUOTA_BONUS_MAX` | `2` | 高频用户最多上浮次数 |
| `PROACTIVE_AT_BONUS_MSGS_LOW` | `20` | 奖励起点（24h 发言数） |
| `PROACTIVE_AT_BONUS_MSGS_HIGH` | `100` | 奖励满点 |
| `PROACTIVE_AT_USER_COOLDOWN` | `7200.0` | 同一用户两次主动 @ 的最小间隔（秒） |
| `PROACTIVE_AT_ACTIVE_WITHIN` | `300.0` | 判定「正在活跃」的时间窗（秒） |
| `PROACTIVE_MAX_NO_REPLY` | `2` | 连续无回应上限，超过则暂停追问 |
| `PROACTIVE_REPLY_WINDOW_SECONDS` | `300.0` | 回应检测窗口（秒） |
| `PROACTIVE_COLDSTART_TOPICS` | 见 settings.py | 冷启动话题清单，逗号分隔 |

配额上限硬封顶在 `BASE + BONUS_MAX`（默认 4 次/天）。**「越活跃越被骚扰」是必须避免的失控模式**，因此奖励幅度不建议调大。

配额为「发出即计数」，不论用户是否回应——否则无回应的追问不占配额，会导致对同一人连续搭话。

## 记忆压缩

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_COMPRESS_LIGHT_THRESHOLD` | `500` | 轻量压缩触发的 active 记忆数 |
| `MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS` | `3600` | 轻量压缩冷却（秒） |
| `MEMORY_ARCHIVE_IMPORTANCE_THRESHOLD` | `0.3` | 低价值归档的重要度阈值 |
| `MEMORY_ARCHIVE_INACTIVE_DAYS` | `180` | 低价值归档的未访问天数 |
| `MEMORY_COMPRESS_LOG_FILENAME` | `memory_compressor_log.md` | 压缩日志 |
| `MEMORY_RECENCY_HALF_LIFE_DAYS` | `120.0` | Recency 兜底半衰期（天） |

`MEMORY_DECAY_DAYS` 是代码内的字典（不走 `.env`），定义各类型记忆的生命周期：

| 类型 | 天数 |
|---|---|
| `FACT` | 730 |
| `STYLE` | 365 |
| `PREFERENCE` / `RELATION` | 180 |
| `EVENT` / `PLAN` | 60 |
| `GROUP_CONTEXT` | 30 |

## 决策追踪与清理

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_TRACE_ENABLED` | `true` | 是否记录记忆决策轨迹 |
| `MEMORY_TRACE_TABLE` | `memory_traces` | 追踪表名 |
| `MESSAGE_CLEANUP_ENABLED` | `true` | 是否启用消息表定期清理 |
| `MESSAGE_CLEANUP_KEEP_COUNT` | `1000` | 每群保留的最近消息条数 |
| `MESSAGE_CLEANUP_HOUR` | `4` | 每日清理时间（24 小时制） |
| `DB_CLEANUP_ON_START` | `false` | **测试期用**：启动时清空短期/长期记忆并重置 checkpoint |
| `DB_CLEANUP_CLEAR_MESSAGES` | `false` | 清理时是否连原始消息一起删除（危险） |

> `DB_CLEANUP_ON_START=true` 会在每次启动时丢失记忆并重置整合进度。测试结束后务必改回 `false`。

## NapCat 进程管理

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `NAPCAT_SHELL_PATH` | `../NapCat.Shell` | NapCat.Shell 安装目录 |
| `NAPCAT_AUTO_START` | `true` | 启动时若 NapCat 未运行则自动拉起 |
| `NAPCAT_QQ_ACCOUNT` | 空 | 自动登录账号 |
| `NAPCAT_QQ_PASSWORD` | 空 | 明文密码 |
| `NAPCAT_QQ_PASSWORD_MD5` | 空 | MD5 密码（优先于明文） |
| `NAPCAT_LAUNCH_LOG_PATH` | `napcat_launch.log` | NapCat 启动输出日志 |
| `NAPCAT_SHOW_WINDOW` | `false` | 是否显示 NapCat 控制台窗口 |

登录变量会同时通过环境变量注入与写入 `NapCat.Shell/config/.env`——部分 NapCat 版本的启动链不透传外部环境变量，后者是可靠兜底。

> 调试期建议 `NAPCAT_SHOW_WINDOW=true`，掉线时能直接看到窗口里发生了什么（是否退化为扫码），而不必事后推断。

### 链路看门狗

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `NAPCAT_WATCHDOG_TIMEOUT` | `300` | 距上次收到**任何** OneBot 事件（含心跳元事件）超过该秒数，**且主动探活失败**，才判定链路中断 |
| `NAPCAT_WATCHDOG_CHECK_INTERVAL` | `60` | 检查间隔（秒） |
| `NAPCAT_WATCHDOG_RESTART_COOLDOWN` | `120` | 重启后把心跳拨后的秒数，给恢复留缓冲 |
| `NAPCAT_WATCHDOG_MAX_RESTARTS` | `3` | 连续重启上限，连接恢复后清零 |

> `NAPCAT_WATCHDOG_MAX_RESTARTS` 是**安全项而非优化项**。若重启换不回连接（如自动登录退化为扫码），无上限的重启会持续把 Bot 踢下线，且高频登录尝试可能触发 QQ 风控。

## 调参建议

| 想要的效果 | 调整方向 |
|---|---|
| Bot 太吵 | 降 `PROACTIVE_PROB_AT_FAST`；升 `PROACTIVE_COOLDOWN`；降 `PROACTIVE_AT_QUOTA_BASE` |
| Bot 太安静 | 升 `PROACTIVE_PROB_AT_FAST`；降 `PROACTIVE_TOPIC_WARMUP_SECONDS` |
| 记不住事 | 降 `MEMORY_OBSERVE_LOW_CONFIDENCE`；降 `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE`；确认 `PROACTIVE_AT_ENABLED=true`（被动摄入的产出接近零） |
| 记错事 | 升 `MEMORY_CONFIRM_HIGH_CONFIDENCE`；升 `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE`；关闭 `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` |
| 回复提到不相关的旧事 | 升 `MEMORY_SCORE_MIN`；降各 `MEMORY_LIMIT_*` |
| 接错话题 | 升 `RECENT_TAIL_LIMIT` |
| 记忆库膨胀 | 开启 `MEMORY_QUOTA_ENFORCE`（先看 dry-run）；降 `MEMORY_USER_QUOTA` |
| 整合太慢 | 降 `CONSOLIDATION_LOCAL_BATCH_SIZE`；换更小的整合模型 |

改动阈值前建议先跑一次探针验证，见 [开发指南](development.md)。