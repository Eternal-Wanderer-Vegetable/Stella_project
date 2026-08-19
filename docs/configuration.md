# 配置参考

**首次配置推荐用向导** `python -m deploy init`：只需回答 5 个必答项（群号、连接方式、
地址、两个模型 ID），模型 ID 会从 LM Studio 拉列表让你选编号，避免手打完整 ID
漏掉 `google/` 前缀；它会基于 `.env.example` 逐行生成 `.env`，模板里的注释（尤其
OneBot 连接那段跨 NapCat 的说明书）会原样保留。也可用 `--answers` 保存/复用答案。

本文是完整配置参考，用于调参。

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

## 群组共享空间

多个 QQ 群可以归入同一个**群组共享空间**，共享用户画像、长期记忆与人格；而「当下这场对话的状态」仍按真实 QQ 群隔离。

### 两层归属

| 数据 | 归属 | 理由 |
|---|---|---|
| 消息尾巴、整合 checkpoint、短期话题、会话压缩 | **QQ 群** | 混群会让 Bot 在 A 群回应 B 群的对话 |
| 静音开关、主动 @ 配额 | **QQ 群** | 打扰程度是针对具体群的 |
| 用户画像、长期记忆、原子事实 | **共享空间** | 同一个人在同一空间就是一份认知 |
| 人格（system prompt）、发言策略 | **共享空间** | 同一形象应有同一套行为 |

### 配置方式

空间配置**不在 `.env` 里**，而是 `config/spaces/` 下的 TOML 文件，**文件名即空间名**：

```toml
# config/spaces/casual.toml —— 空间名为 "casual"
qq_groups = [123456789, 987654321]
```

目前只解析 `qq_groups`。`persona` 与 `[proactive]` 等字段是为将来的人格分群与群级配置预留的，当前会被忽略。

### 隐式空间

未被任何 TOML 收录的群会**自动分配**一个空间名（`space_1` / `space_2` …），并持久化在数据库目录下的 `.space_assignments.json`。单群部署零配置即可工作。

编号必须持久化而不是现算：若按群号排序的下标计算，加入一个群号更小的新群会让所有编号平移，原有记忆的归属随之错位且无声无息。

### 改名的代价

把一个已运行的群从自动分配的 `space_1` 改成显式的 `casual` 时，**历史记忆仍挂在 `space_1` 下**。程序会输出告警并提示需要手工迁移：

```sql
UPDATE memories          SET group_shared_space='casual' WHERE group_shared_space='space_1';
UPDATE memory_candidates SET group_shared_space='casual' WHERE group_shared_space='space_1';
UPDATE user_profiles     SET group_shared_space='casual' WHERE group_shared_space='space_1';
UPDATE atomic_facts      SET group_shared_space='casual' WHERE group_shared_space='space_1';
UPDATE memories_fts      SET group_shared_space='casual' WHERE group_shared_space='space_1';
```

因此**建议在正式积累记忆之前就定好空间名**。

### 冲突处理

同一个群出现在多个 TOML 里时，按文件名排序取先者并输出 error 日志。静默取后者会让记忆在两次启动间落到不同空间，这种错乱事后极难发现。

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

### 整合调度

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `CONSOLIDATION_SCHEDULE_INTERVAL` | `120` | 定时整合的检查间隔（秒） |
| `CONSOLIDATION_MAX_ROUNDS_PER_RUN` | `3` | 单次定时任务最多连续整合几批 |
| `CONSOLIDATION_BACKLOG_WARN` | `300` | 积压超过该条数时日志提升为 warning |

> **为什么需要定时整合**：整合此前只在 @ 触发与主动发言前进行，被动摄入速度超过整合速度时会无界积压（2026-08-16 实测积压 1004 条），且超过 `MESSAGE_CLEANUP_KEEP_COUNT` 后未整合消息会被清理直接丢弃。
>
> 单次批数不宜过多：CPU 小模型单批 20~60 秒，批次太多会长时间占用整合模型，太少则追不上积压。

### 记忆候选提取（阶段 2）

整合分两阶段执行：

| 阶段 | 任务 | 模型 |
|---|---|---|
| 阶段 1 | 短期摘要 + 用户画像 + `has_self_disclosure` 布尔判断 | 整合模型（CPU 小模型） |
| 阶段 2 | 精确提取 `memory_candidates` | 本段配置的模型（默认继承主聊天模型） |

阶段 2 **只在阶段 1 判定本批含用户自我披露时才唤醒**（软门槛）。这样日常刷屏、寒暄、第三方讨论只花小模型的算力。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_EXTRACT_ENABLED` | `true` | 关闭则退回单阶段（整合模型一次性出全部） |
| `MEMORY_EXTRACT_LM_STUDIO_BASE_URL` | 同 `LM_STUDIO_BASE_URL` | 提取服务地址 |
| `MEMORY_EXTRACT_LM_STUDIO_MODEL` | 同 `LM_STUDIO_MODEL` | 默认继承主聊天模型 |
| `MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE` | `0.2` | 抽取任务不需要发散，比整合的 0.3 更低 |
| `MEMORY_EXTRACT_MAX_TOKENS` | `1000` | 只输出候选数组，不需要很大 |

**为什么要拆**：小模型能总结主题，却在噪音环境下系统性地把候选提取判空。2026-08-16 实测 7 批整合全部返回空候选，而信息明确出现在它自己写的摘要里——是「读到了但主动弃掉」，不是没看到。候选提取是高精度抽取任务，交给大模型。

`probe_consolidation.py` 的 `insomnia_breakfast_noisy` 用例锁住了这个差异：同样的信息埋在 Bot 寒暄与刷屏之中，单阶段命中 1/2、两阶段命中 2/2。

**代价**：实测提取单次占用主聊天模型约 20 秒（1600 prompt tokens + 280 生成 @19 tok/s）。它与聊天走同一道闸门、FIFO 串行，因此聊天期间发起的提取会排在后面，反之亦然。

### 向量语义检索（可选）

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `MEMORY_EMBEDDING_ENABLED` | `false` | 关闭时用规则版词面语义（离线、确定） |
| `MEMORY_EMBEDDING_BASE_URL` | `http://127.0.0.1:1234` | embedding 服务地址 |
| `MEMORY_EMBEDDING_MODEL` | 空 | 向量模型 ID |
| `MEMORY_EMBEDDING_TIMEOUT` | `10.0` | 单次请求超时（秒） |
| `MEMORY_EMBEDDING_CONTEXTUAL_MIN` | `0.25` | embedding 路径下 `CONTEXTUAL` 记忆的主题匹配余弦阈值 |

服务或模型不可用时**自动回退规则版**，链路不中断。

### LLM 资源调度

LM Studio **不限制并发**：多个请求同时打到同一模型时服务端不会排队，只会把并发推理挤在一起，让每个请求都变慢且难以定位是谁在抢算力。因此应用层必须为共享模型加闸门。

两种资源各自独立，同一资源内 FIFO 严格串行，不同资源之间可真正并行：

| 资源 | 模型 | 使用者 |
|---|---|---|
| `chat` | 主聊天模型 | 聊天回复、会话压缩、候选提取、embedding 编码 |
| `consolidation` | 整合模型 | 两阶段整合的阶段 1 |

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `LLM_SCHEDULER_WAIT_WARN_SECONDS` | `30.0` | 排队等待超过该秒数则告警 |
| `LLM_SCHEDULER_HOLD_WARN_SECONDS` | `90.0` | 单次持有超过该秒数则告警 |
| `LLM_SCHEDULER_QUEUE_WARN_DEPTH` | `3` | 排队深度达到该值即告警 |
| `LLM_SCHEDULER_PRIORITY_ENABLED` | `false` | **尚未实现**，保留开关 |
| `LLM_SCHEDULER_GATE_EMBEDDING` | `true` | embedding 编码是否也走 chat 闸门 |

持有告警的阈值考虑了后端的 3 次重试（每次超时 120 秒），因此单次持有的上界远大于一次正常请求；持续超阈值说明不是排队，而是调用本身卡住了。

`LLM_SCHEDULER_GATE_EMBEDDING` 默认开启的原因：`MEMORY_EMBEDDING_BASE_URL` 默认与主聊天同一个实例，而一次检索要对每条候选记忆各编码一次（候选池可达 20+），不串行会出现间歇性变慢且极难定位。若把 embedding 部署在独立实例，可关闭本项避免不必要的串行。

**优先级为什么没实现**：多群下严格 FIFO 会让 @ 回复排在后台任务之后。但后台任务每群最多 1 个在途、数量有界，实际影响需要真实排队数据才能判断。先积累 `core.llm.snapshot()` 的观测数据，再决定是否偏离 FIFO。

## 上下文

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `RECENT_TAIL_LIMIT` | `12` | 每次回复附加的最近原始消息条数（含 Bot 自己的发言） |
| `RECENT_TAIL_MAX_AGE_MINUTES` | `45.0` | 尾巴时间窗（分钟）：超出时长的消息不再算「最近的对话」；`0` 不做时间过滤 |
| `RECENT_TAIL_GAP_MARK_MINUTES` | `15.0` | 相邻消息间隔超过该分钟数时在尾巴里插入断层标记；`0` 关闭 |
| `SHORT_TERM_SUMMARY_STALE_MINUTES` | `60.0` | 摘要超时未更新则标题改为「之前的话题」并注明时长；`0` 关闭 |
| `MAX_REPLY_LINES` | `5` | 单次回复最大行数 |
| `SEND_INTERVAL` | `0.8` | 多行之间的发送间隔（秒） |
| `FALLBACK_REPLY` | `......？` | 兜底回复 |
| `BAD_PHRASES` | 见 settings.py | 破防语句清单，命中即替换为兜底回复 |

> **`RECENT_TAIL_LIMIT` 的权衡**：太小会让活跃群的刷屏把 Bot 自己的提问挤出窗口，用户的简短回应（「手机」「对」）会被接到上一个话题上；太大则无关历史干扰模型且 prompt 变长。12 是起点，需按群的刷屏速度调整。

> **尾巴的时间窗与断层标记**：仅按 id 取最近 N 条时，停机数小时后重启会把几小时前的对话当成刚刚发生的事（2026-08-15 缺陷）。`RECENT_TAIL_MAX_AGE_MINUTES` 过滤掉超时消息；窗口内部相邻消息间隔超过 `RECENT_TAIL_GAP_MARK_MINUTES` 时插入一行「（……中间隔了 X……）」标记，让模型知道「之前聊过但已经过去很久」，而非直接失忆。

`RECENT_MESSAGE_LIMIT` 已废弃（被 `RECENT_TAIL_LIMIT` 取代），保留定义以兼容既有 `.env`。

### 会话上下文压缩

短时连续对话中，早期消息会滚出尾巴窗口而彻底消失。本机制把滚出的部分压缩成一段回顾，使 Bot 在长对话里保持连贯（类似 coding agent 的 compact）。

**三层上下文按消息 id 划分，绝不重叠**：

| 层 | 范围 |
|---|---|
| 会话摘要 | `summarized_up_to_id` → 尾巴起点（较早部分，已压缩） |
| 原始尾巴 | 最近 `RECENT_TAIL_LIMIT` 条（原文） |
| 话题摘要 | 整合器产出的跨会话背景 |

重叠会导致同一段对话出现两个版本，模型以摘要为准从而接错话题（2026-08-13 缺陷的成因）。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `SESSION_CONTEXT_ENABLED` | `true` | 会话压缩总开关 |
| `SESSION_COMPACT_THRESHOLD_TOKENS` | `600` | 待压缩文本超过该 token 估算值才触发 |
| `SESSION_SUMMARY_MAX_TOKENS` | `300` | 摘要自身的预算，超过则连同新内容重新压缩 |
| `SESSION_COMPACT_MAX_MESSAGES` | `60` | 单次压缩最多喂入的消息条数 |
| `SESSION_IDLE_TIMEOUT_SECONDS` | `900.0` | 空闲多久视为会话结束（结束时清空摘要并触发一次完整整合） |
| `SESSION_IDLE_CHECK_INTERVAL` | `300` | 空闲检查间隔（秒） |

压缩用**主聊天模型**而非整合模型：整合模型跑 CPU、单次 20~60 秒，而压缩在每次回复之后异步触发，必须快。压缩不阻塞当前回复，摘要从下一轮开始生效。

会话结束时整合一次的理由：这一场对话的内容此前只以压缩摘要形式存在于内存，重启即失；结束时整合把它沉淀为长期记忆的候选。

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
| `MEMORY_USER_QUOTA` | `25` | 单用户在**单个共享空间**的 active 记忆上限 |
| `MEMORY_QUOTA_W_IMPORTANCE` | `0.4` | 竞争分权重：重要度 |
| `MEMORY_QUOTA_W_CONFIRMATION` | `0.3` | 竞争分权重：被确认次数 |
| `MEMORY_QUOTA_W_RECENCY` | `0.3` | 竞争分权重：近期访问 |
| `MEMORY_QUOTA_CONFIRMATION_CAP` | `3` | 确认次数归一化上限 |

> **开启前先观察**。`MEMORY_QUOTA_ENFORCE=false` 时日志会输出 `[Quota dry-run] ... 本来会淘汰 xxx`，确认淘汰对象合理后再开启。淘汰是置 `archived` 而非删除，但恢复需要手工 SQL。

> 多个 QQ 群归入同一空间时配额实际收紧了（同一个人在同一空间只有一份认知）。这符合设计，但调参时需要知道。

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
| `PROACTIVE_PROB_AT_FAST` | `0.15` | 高频端概率 |
| `PROACTIVE_PROB_AT_SLOW` | `0.0` | 冷清端概率 |
| `PROACTIVE_PROB_GAMMA` | `1.0` | 曲线整形指数，>1 更保守 |
| `PROACTIVE_TOPIC_WARMUP_SECONDS` | `45.0` | 话题预热时长，不足则不参与 |
| `PROACTIVE_COOLDOWN` | `600` | 群级硬冷却（秒） |
| `PROACTIVE_CHECK_INTERVAL` | `60` | 定时检查间隔（秒） |
| `PROACTIVE_FREQ_WINDOW` | `10` | 频率估算窗口（最近 N 条消息） |
| `PROACTIVE_MAX_LINES` | `1` | 主动插话最大行数 |
| `PROACTIVE_MIN_MESSAGES_SINCE_SPOKE` | `15` | 距上次自己发言，群里至少要有多少条新消息才允许再开口。0 表示不限制 |

**三种预设**：

```env
# 热闹时插话（默认，适合闲聊群）
PROACTIVE_PROB_AT_FAST=0.15
PROACTIVE_PROB_AT_SLOW=0.0

# 热闹时闭嘴（旧行为，适合技术群）
PROACTIVE_PROB_AT_FAST=0.05
PROACTIVE_PROB_AT_SLOW=0.5

# 完全关闭话题参与（保留主动 @）
PROACTIVE_PROB_AT_FAST=0.0
PROACTIVE_PROB_AT_SLOW=0.0
```

**为什么需要消息数门槛**：纯时间冷却在冷清群里会造成「自己说完等 10 分钟又自己说」。消息数门槛能保证「话题真的往前走了」才插话。该计数是进程内的，重启后视为「新消息足够」，不会因重启而永久卡住主动发言。

三种预设的实际频率参考（`CHECK_INTERVAL=60`）：`PROB_AT_FAST=0.15` 时活跃群命中期望约 6.7 分钟，叠加 `COOLDOWN=600` 与消息门槛后，实际发言间隔通常在 10 分钟以上。

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
| `PROACTIVE_AT_EXCLUDE_USERS` | 空 | 不会被选为主动搭话对象的 QQ 号（逗号分隔） |

排除名单的主要用途是**群内其他 AI** —— 互相 @ 会触发无终止的循环对话。被排除的账号仍会被动收集信息（消息照常落库与整合），只是不主动向它们提问。

配额上限硬封顶在 `BASE + BONUS_MAX`（默认 4 次/天）。**「越活跃越被骚扰」是必须避免的失控模式**，因此奖励幅度不建议调大。

配额为「发出即计数」，不论用户是否回应——否则无回应的追问不占配额，会导致对同一人连续搭话。

### 睡眠时段

模拟人类作息：睡眠期间关闭一切主动发言（话题插话 + 主动 @），但**被 @ 时照常回复**。

不在睡眠期停止回复的理由：用户主动叫它却不回应看起来像掉线，且 `AT_MENTION` 是当前唯一的记忆来源，睡眠期不回复等于每天损失数小时的采集。被动信息收集（消息落库、整合）在睡眠期照常进行。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `PROACTIVE_SLEEP_ENABLED` | `true` | 睡眠时段总开关 |
| `PROACTIVE_SLEEP_START` | `23:30` | 入睡时刻（`HH:MM`，**本地时间**） |
| `PROACTIVE_SLEEP_END` | `07:30` | 苏醒时刻（`HH:MM`，**本地时间**） |
| `PROACTIVE_WAKEUP_GRACE_SECONDS` | `900.0` | 醒来缓冲：苏醒后多久内仍不主动发言 |
| `PROACTIVE_SLEEP_ANNOUNCE` | `true` | 是否在入睡/苏醒时播报一句 |
| `PROACTIVE_SLEEP_MESSAGES` | 见 settings.py | 入睡播报台词（逗号分隔，随机选一条） |
| `PROACTIVE_WAKEUP_MESSAGES` | 见 settings.py | 苏醒播报台词 |

支持跨午夜区间（`START > END` 时视为跨天）。`START == END` 视为不睡眠。时间格式非法时回退到默认值并输出警告——配置笔误不应让 Bot 通宵说话。

**这里用本地时间而非 UTC**：它描述的是人类作息，与数据库时间戳无关。这是全项目唯一该用本地时间的地方。

**醒来缓冲的必要性**：积压一夜的活跃度统计会让 Bot 一睁眼就连发几句。缓冲期从「检测到苏醒跃变」开始计时。

播报按「每群每类每日最多一次」去重（记录在 `group_runtime_state`）。播报由定时任务触发，不去重的话睡眠期内重启会重复播报「我去睡了」。播报不经过 Pipeline（无需 LLM），但会写入 `group_messages`（`BOT_SELF`）供下一轮整合理解语境。

### 运行时开关

管理员可在群内临时关闭主动发言，作为配置级开关之外的另一道闸门。便于部署者在群成员反馈后即时调整。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `PROACTIVE_RUNTIME_TOGGLE_ENABLED` | `true` | 是否启用运行时开关命令 |
| `PROACTIVE_TOGGLE_ADMINS` | 空 | 额外授权的 QQ 号（逗号分隔）。留空则仅群主/管理员可操作 |

用法：@ 机器人并说出关键词。

| 动作 | 关键词 |
|---|---|
| 静音 | 安静、闭嘴、别说话、停止主动发言 |
| 恢复 | 恢复、醒醒、可以说话、开启主动发言 |

静音状态**持久化在 `group_runtime_state` 表，重启后仍生效**——管理员关掉它通常是因为出了问题，重启不该把它悄悄打开。

静音只影响主动发言，被 @ 时仍照常回复。非管理员触发时不做任何改动也不回复。

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
| `MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED` | `true` | 清理时保护未整合的消息（checkpoint 之后的不删除） |
| `DB_CLEANUP_ON_START` | `false` | **测试期用**：启动时清空短期/长期记忆并重置 checkpoint |
| `DB_CLEANUP_CLEAR_MESSAGES` | `false` | 清理时是否连原始消息一起删除（危险） |

> `DB_CLEANUP_ON_START=true` 会在每次启动时丢失记忆并重置整合进度。测试结束后务必改回 `false`。

> 关闭 `MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED` 会导致积压超过 `MESSAGE_CLEANUP_KEEP_COUNT` 时未整合消息被永久丢弃，那些内容永远不会进入记忆系统，且 checkpoint 对齐会让丢失变得不可见。

## OneBot 连接

Bot 通过 OneBot V11 WebSocket 与 NapCat 通信。**NapCat 侧必须先登录**：用
[NapCatQQ Desktop](https://github.com/NapNeko/NapCatQQ-Desktop) 安装并完成 QQ 登录，
Bot 不再代管 NapCat 进程——自动登录会退化为扫码，登录必须有人在场
（见 `design_docs/deprecated_napcat_manager.md`）。

| 方式 | Bot 侧（`.env`） | NapCat 侧（WebUI 网络配置） |
|---|---|---|
| 反向 WS（推荐） | `HOST` + `PORT`（NoneBot 默认 `0.0.0.0:8080`），反向 WS 端点固定 `/onebot/v11/ws` | 添加「WebSocket 客户端」，URL 填 `ws://<Bot地址>:<PORT>/onebot/v11/ws` |
| 正向 WS | `ONEBOT_WS_URLS`（JSON 数组）+ `ONEBOT_ACCESS_TOKEN` | 开启「WS 服务端」，记下监听地址与 token |

若两侧都配了 access token，两边的值必须一致。相关环境变量见 `.env.example` 顶部。

## 端口占用一览

**Stella 只监听一个端口**——反向 WS 端点与状态接口复用同一个 HTTP 服务器（NoneBot 的 FastAPI app），不新增端口。排查网络问题时先确认这张表：

| 端口 | 归属 | 谁在监听 | 配置项 |
|---|---|---|---|
| 8080 | **Stella 唯一的监听端口** | 本项目 | `PORT` |
| 1234 | LM Studio | 外部程序 | `LM_STUDIO_BASE_URL` |
| 6099 | NapCat WebUI | 外部程序 | NapCat 侧 |
| 3001 | NapCat 正向 WS 服务端 | 外部程序（仅 forward 模式） | `ONEBOT_WS_URLS` |
| 8765 | 原型预览 | 开发期 `serve.bat` | 不进 Release |

## 本地状态接口

`deploy status` 与桌面 GUI 通过 `http://HOST:PORT/stella/status` 读取**进程内**状态（链路健康度、调度器排队深度、启动时长）——那些数据外部进程拿不到，HTTP 端点则天然「连不上就是没运行」。

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `STELLA_STATUS_API_ENABLED` | `true` | 是否注册状态路由 |
| `STELLA_STATUS_API_PATH` | `/stella/status` | 路由路径（与将来的其他路由冲突时再改） |

**只接受回环地址的请求**（`127.0.0.1` / `::1`），且响应体不含凭据与群聊内容（`allowed_group_count` 只给数量不给群号）——`HOST` 可能配成 `0.0.0.0`（NapCat 在另一台机器时），那时路由会暴露到局域网。设计说明见 architecture.md 的「本地状态接口」。

## 链路监测

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `LINK_MONITOR_ENABLED` | `true` | 是否启用链路监测 |
| `LINK_MONITOR_TIMEOUT` | `300` | 距上次收到**任何** OneBot 事件（含心跳元事件）超过该秒数，才做一次主动探活 |
| `LINK_MONITOR_CHECK_INTERVAL` | `60` | 定时检查间隔（秒） |
| `LINK_MONITOR_ALERT_INTERVAL` | `300` | 告警节流（秒）：断线期间不重复刷同样的 error |

**只告警、不重启。** 登录风控使自动重启无效（自动登录会退化为扫码），进程管理因此
没有收益（见 `design_docs/deprecated_napcat_manager.md`）。Bot 只负责监测链路并给出
排查提示，NapCat 的启停与登录由 NapCatQQ Desktop 人工完成。

> **静默 ≠ 断线。** NapCat 周期性发 `meta_event.heartbeat`（默认 15s），群里没人
> 说话时心跳仍在。判定超时后 Bot 会主动调用一次 `get_status()` 二次确认：探活成功
> 只说明「没人说话」，探活失败才是真断开。只挂 `on_message` 会把安静的群误判为
> 链路中断（2026-08-14 重启循环的成因）。

## 调参建议

| 想要的效果 | 调整方向 |
|---|---|
| Bot 太吵 | 降 `PROACTIVE_PROB_AT_FAST`；升 `PROACTIVE_COOLDOWN` 与 `PROACTIVE_MIN_MESSAGES_SINCE_SPOKE`；降 `PROACTIVE_AT_QUOTA_BASE`；或让管理员在群内说「安静」临时关闭 |
| Bot 太安静 | 升 `PROACTIVE_PROB_AT_FAST`；降 `PROACTIVE_TOPIC_WARMUP_SECONDS` |
| 深夜还在说话 | 确认 `PROACTIVE_SLEEP_ENABLED=true`，检查 `PROACTIVE_SLEEP_START/END` 是否覆盖目标时段 |
| 一觉醒来连发几句 | 升 `PROACTIVE_WAKEUP_GRACE_SECONDS` |
| 记不住事 | 降 `MEMORY_OBSERVE_LOW_CONFIDENCE`；降 `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE`；确认 `PROACTIVE_AT_ENABLED=true`（被动摄入的产出接近零） |
| 记错事 | 升 `MEMORY_CONFIRM_HIGH_CONFIDENCE`；升 `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE`；关闭 `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` |
| 回复提到不相关的旧事 | 升 `MEMORY_SCORE_MIN`；降各 `MEMORY_LIMIT_*` |
| 接错话题 | 升 `RECENT_TAIL_LIMIT` |
| 把几小时前的旧对话当成当前话题 | 降 `RECENT_TAIL_MAX_AGE_MINUTES` |
| 尾巴里断层太多/太少 | 调整 `RECENT_TAIL_GAP_MARK_MINUTES` |
| 记忆库膨胀 | 开启 `MEMORY_QUOTA_ENFORCE`（先看 dry-run）；降 `MEMORY_USER_QUOTA` |
| 整合太慢 | 降 `CONSOLIDATION_LOCAL_BATCH_SIZE`；换更小的整合模型 |
| @ 对话完全学不到东西 | 查 `SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind`；`AT_MENTION` 为 0 说明 @ 消息未入库（见 development.md 排查表） |
| 记忆晋升过快、配额压力大 | `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` 生效后 @ 对话单次即可晋升，属预期；先看 `MEMORY_QUOTA_ENFORCE=false` 的 dry-run 日志再决定是否收紧 |
| 回复变慢、日志出现 Scheduler 告警 | 27B 上排队较重（聊天 + 压缩 + 提取共用）；可临时关 `MEMORY_EXTRACT_ENABLED` 或调大 `CONSOLIDATION_SCHEDULE_INTERVAL` |
| 链路掉线 / 收不到消息 | 看日志里的 `[LinkMonitor]` 告警，按告警文案的排查步骤检查（Bot 只告警不重启，NapCat 侧需人工处理） |

改动阈值前建议先跑一次探针验证，见 [开发指南](development.md)。