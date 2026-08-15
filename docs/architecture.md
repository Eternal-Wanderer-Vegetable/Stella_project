# 架构说明

本文描述 Stella 的目录结构、模块职责与一次消息的完整处理流程。记忆系统的设计理由见 [记忆系统](memory-system.md)，配置项见 [配置参考](configuration.md)。

## 分层概览

```
QQ 群消息
    ↓  OneBot V11 / NapCat
stella_project/plugins/bot_main/ai_gateway.py     ← 事件接入层
    ↓
core/pipeline.py                                  ← 编排层（pre hooks → LLM → post hooks）
    ↓
memory/*                                          ← 记忆层（写入 / 晋升 / 检索 / 压缩）
    ↓
SQLite（memory/agent_memory.db）
```

四层各自独立：接入层只做协议适配与调度，编排层不含业务逻辑，记忆层不感知 QQ，存储层由 `memory/schema.py` 统一管理迁移。

## 目录结构

```text
Stella_project/
├── bot.py                          # NoneBot 启动入口
├── pyproject.toml                  # 依赖、NoneBot 配置、ruff/pytest 规则
├── pyrightconfig.json              # 类型检查配置
│
├── config/
│   └── settings.py                 # 集中配置：读 .env，导出模块级常量
│
├── core/                           # 与业务无关的编排骨架
│   ├── context.py                  # ChatContext：一次处理的运行期载体
│   ├── pipeline.py                  # Pipeline 编排器 + prompt 拼装顺序
│   └── llm/
│       ├── base.py                 # LLM 后端抽象接口
│       └── lm_studio.py            # LM Studio 后端（含重试与截断告警）
│
├── memory/                         # 记忆系统主体
│   ├── SYSTEM.md                   # 机器人系统提示词
│   ├── schema.py                   # Schema 迁移（Additive，当前 v6）+ 来源枚举
│   ├── timeutil.py                 # DB 时间戳统一按 UTC 解析
│   ├── text_similarity.py          # 内容相似度与合并（单一真相源）
│   │
│   ├── pre_processors.py           # 消息落库、短期上下文、用户上下文组装
│   ├── post_processors.py          # 输出解析、破防过滤、分行、思考日志
│   ├── prompt_builder.py           # 记忆与上下文 → 分区 Prompt
│   │
│   ├── consolidator.py             # 整合：消息 → 摘要/画像/候选（含候选强化）
│   ├── consolidation_prompt.py     # 整合任务的 JSON 输出模板
│   ├── consolidation_log.py        # 整合过程日志
│   ├── memory_manager.py           # 晋升：Gate 1 三档、配额淘汰、FTS 同步
│   ├── policy.py                   # Policy：Mode 检测、三层过滤、排序、候选校验
│   ├── compressor.py               # 压缩：去重合并、原子化、归档、衰减
│   │
│   ├── retrieval_v2.py             # v2 检索（Context-aware Memory Activation）
│   ├── retriever.py                # FTS5 检索 + 加权回退排序
│   ├── embeddings.py               # 本地 embedding 客户端（可选语义分）
│   │
│   ├── proactive.py                # 活跃度统计与发言概率曲线
│   ├── proactive_state.py          # 主动发言的持久化状态（配额/冷却/退避）
│   ├── proactive_gate.py           # 主动发言的统一准入闸门（六道条件）
│   ├── proactive_target.py         # 主动 @ 的目标选择与配额判定
│   ├── proactive_prompt.py         # 主动 @ 的任务指令模板
│   │
│   ├── trace.py                    # 记忆决策追踪
│   ├── benchmark.py                # Memory Benchmark 运行器
│   ├── benchmark/                  # 检索层用例 + _fixtures（含整合正例基准）
│   └── db_cleaner.py               # 脏数据清理 + 消息表定时裁剪
│
├── extensions/                     # 自动加载的扩展（扫描 setup(pipeline)）
│   ├── __init__.py                 # 扩展加载器
│   └── napcat_manager/             # NapCat 进程管理
│       ├── manager.py              # 启动/停止/重启 NapCat.Shell 进程树
│       └── watchdog.py             # 链路看门狗（心跳 + 主动探活 + 重启上限）
│
├── stella_project/plugins/bot_main/
│   ├── ai_gateway.py               # QQ 事件监听、Pipeline 装配、主动发言调度
│   └── config.py                   # 插件配置（pydantic）
│
├── scripts/                        # 开发期工具（不进 CI）
│   ├── probe_consolidation.py      # 整合探针 / 正例回归基准
│   ├── sample_windows.py           # 从真实库分层采样消息窗口
│   ├── probe_embedding.py          # embedding 服务探针
│   └── build_embedding_fixture.py  # 构建 benchmark 向量 fixture
│
├── tests/                          # pytest 测试
├── docs/                           # 使用文档
├── design_docs/                    # 设计过程记录（规范/检查点/缺陷报告/日志）
└── _deprecated/                    # 废弃代码与旧数据库归档（gitignore）
```

## 一次消息的处理流程

### 1. 接入与落库

```
群消息 → group_silent_listener（priority 99, block=False）
       → pre_processors.record_message()  → group_messages 表
       → proactive.record_message()       → 活跃度时间戳（内存）
```

静默监听器处理**每一条**群消息，包括不 @ 机器人的。落库时按来源分级打标：

| `source_kind` | 含义 | 在记忆系统中的权重 |
|---|---|---|
| `AT_MENTION` | 用户直接对 Bot 说 | 高密度证据，单次即可晋升 |
| `PASSIVE` | 被动摄入的群聊 | 需复现才能晋升 |
| `BOT_SELF` | Bot 自己的发言 | **只作上下文，绝不产出候选** |

`BOT_SELF` 是必需的：没有它，用户回答「对」「手机」这类简短回应时，整合模型看不到 Bot 问了什么，只能放弃或自行编造语境。

同一个监听器还负责刷新 NapCat 看门狗心跳（通过 `event_preprocessor`，任何 OneBot 事件都算，包括协议端的心跳元事件）。

### 2. 触发路径

| 路径 | 触发条件 | `trigger` | `intent` |
|---|---|---|---|
| @ 回复 | 群在白名单 + 被 @ + 有文本 | `reply` | `""` |
| 主动 @ | 定时检查命中，选中活跃用户 | `reply` | `proactive_at` |
| 主动插话 | 定时检查命中，概率曲线通过 | `proactive` | `proactive_join` |
| 运行时开关 | 管理员 @ 机器人 + 命中开关关键词 | — | — |

三条路径共用同一个 Pipeline，靠 `ChatContext` 的字段区分行为。每群一把 `asyncio.Lock`，保证同一群同时只跑一次推理。

主动 @ 与主动插话**互斥**：定时任务先尝试主动 @，命中即跳过插话，同一轮只发一次言。

主动路径（主动 @ / 主动插话）的准入判定统一走 `memory/proactive_gate.py` 的 `can_speak(group_id, kind)`，按顺序检查六项：

```
总开关 → 分路开关 → 运行时静音 → 睡眠时段 → 醒来缓冲 → 群级冷却 → 新消息门槛
```

返回值带原因字符串，便于排查「为什么这次没说话」。收敛到单一入口是有原因的：这些条件原先散在 `proactive_speak_job` / `_proactive_at_user` / `should_speak` 三处，每加一个条件都要改三个调用点。

话题插话的**概率掷骰不在 gate 内** —— 那是 join 路径独有的，由调用方在 gate 通过后自行掷骰（主动 @ 有配额与用户级冷却约束，不掷骰）。

**@ 回复不经过 gate。** 睡眠或静音期间被 @ 照常回复。

运行时开关 handler 的 `priority=0`，必须早于 `chat_handler(priority=1, block=True)`，否则「安静」这类命令会被当成普通对话交给 LLM。

### 3. 上下文构建（pre hooks）

Pipeline 的 pre hook 按 priority **降序**执行：

```
build_context      (50)  → ctx.short_term
build_user_context (40)  → ctx.user_profile / conversation_memories / behavior_constraints
```

**`build_context`** 组装两部分并存的短期上下文：

- **话题层摘要**：`short_term_context.active_summary` / `pending_topic`，由整合器产出，按设计滞后
- **原始尾巴**：最近 `RECENT_TAIL_LIMIT` 条原始消息，含 Bot 自己的发言（渲染为「我」）

两者必须并存。摘要要累积到阈值才更新，只靠它会看不到最近几轮对话——Bot 会把用户的简短回应接到上一个话题上去。

**`build_user_context`** 走 v2 检索（`MEMORY_V2_ENABLED`）：

```
detect_mode(消息, 触发方式)                     ← 判定行为模式
  → SQL 可见性预过滤                            ← 先决定什么有资格被找到
  → FTS5 / 加权回退 取候选池
  → Usage 层过滤 + Ranking（Policy 优先于相似度）
  → 同类合并（按用户，不跨归属）
  → 分离聊天素材 / 行为约束
  → 分数门槛 + 模式条数上限
```

### 4. LLM 调用

`core/pipeline.py` 把上下文与消息拼成最终 prompt。**拼装顺序取决于 `intent`**：

| intent | 顺序 | 原因 |
|---|---|---|
| 普通 | 上下文 → 用户消息 | 用户输入在最后，模型自然去回应它 |
| `proactive_at` | **任务指令 → 上下文** | `ctx.message` 是指令而非用户输入；若放在最后，模型会去接上下文尾部的对话而不是执行指令 |

调用全程持有 `chat_llm_lock`（全局串行），超时与异常都有兜底回复。诊断信息（后端、模型、耗时、完整 prompt）写入 `ctx`，由 `log_thought` 落盘。

### 5. 输出处理（post hooks）

按 priority 降序：

```
parse_output      (100)  → 解析 thought / action / reply
bad_phrase_filter  (80)  → 破防语句兜底
split_lines        (60)  → 拆分为可逐条发送的多行
log_thought        (40)  → 写 stella_thought_logs.md
```

发送前先把 Bot 自己的台词写入 `group_messages`（`BOT_SELF`）。**必须在发送前**：最后一行走 `finish()` 会抛 `FinishedException`，之后的代码不执行。

### 6. 记忆写入与晋升

异步进行，不阻塞回复：

```
消息积累 → maybe_consolidate()（@ 触发或主动发言前，或达批次阈值）
        → LLM 输出 JSON（短期摘要 + 用户画像 + 记忆候选）
        → 候选强化：同事实累积证据而非重复插入
        → MemoryManager.process_new_candidates()
             ├─ 超期 OBSERVING → REJECTED
             ├─ Gate 1 三档判定 → 晋升 / 继续观察
             ├─ 冲突检测 → 旧记忆标 CONFLICT
             ├─ 相似合并（同群同用户同类型）或新建
             └─ 每用户配额淘汰
        → FTS5 索引同步
        → 轻量压缩（节流触发）
```

整合固定使用独立配置的 LM Studio 实例（建议 CPU 推理的小模型），与主聊天模型分离，避免抢占显存。整合自身串行（`consolidation_llm_lock`）。

规则细节见 [记忆系统](memory-system.md)。

### 7. 定时任务

| 任务 | 周期 | 作用 |
|---|---|---|
| 主动发言检查 | `PROACTIVE_CHECK_INTERVAL` | 睡眠/苏醒播报 → 尝试主动 @ → 尝试主动插话 |
| NapCat 看门狗 | `NAPCAT_WATCHDOG_CHECK_INTERVAL` | 心跳超时 + 探活失败 → 外部重启 |
| 消息表裁剪 | 每日 `MESSAGE_CLEANUP_HOUR` 点 | 每群保留最近 N 条，同时清理过期追踪 |
| 周度压缩 | 每 7 天 | 全量去重、原子化、归档、衰减 |

## 关键数据结构

### ChatContext

一次处理的运行期载体，是各模块间传递数据的唯一通道。

| 分组 | 字段 |
|---|---|
| 输入标识 | `user_id` `group_id` `msg_id` `message` `source_kind` |
| 处理产物 | `raw_output` `thought` `action` `reply` `lines` |
| 诊断 | `trigger` `intent` `intent_detail` `llm_backend` `llm_model` `llm_elapsed` `prompt_log` |
| 结构化上下文 | `short_term` `user_profile` `memories_for_prompt` |
| 记忆 v2 | `memory_mode` `conversation_memories` `behavior_constraints` `memory_trace` |

### 主要数据表

| 表 | 作用 |
|---|---|
| `group_messages` | 原始群消息（含 `source_kind`） |
| `short_term_context` | 每群的话题摘要与关键发言 |
| `consolidation_state` | 每群的整合 checkpoint |
| `memory_candidates` | 记忆候选（含 `occurrence_count` / `source_kinds` / `first_seen_at`） |
| `memories` | 长期记忆（含 `usage_tags` / `visibility` / `behavior_rule`） |
| `memories_fts` | FTS5 全文索引（按 `mem_id` 与 `memories` 同步） |
| `user_profiles` | 用户稳定画像（人格判断已被过滤） |
| `proactive_state` | 主动 @ 的配额、冷却、退避状态 |
| `group_runtime_state` | 群级运行时状态：主动发言静音开关、睡眠/苏醒播报去重 |
| `memory_traces` | 记忆决策追踪 |
| `atomic_facts` | 长记忆拆分出的原子事实 |
| `compressor_stats` / `compressor_state` | 压缩统计与节流状态 |
| `schema_meta` | Schema 版本号 |

Schema 迁移采用 **Additive Migration**：只加字段与索引，绝不删数据；首次迁移前自动备份。独立执行：

```bash
python -m memory.schema --dry-run   # 预览
python -m memory.schema             # 执行
python -m memory.schema --backup    # 仅备份
```

## 扩展机制

`extensions/` 下的每个模块/包若提供 `setup(pipeline)`，启动时会被自动加载。扩展可以注册 Hook、注入实现、启动自己的定时任务。

`napcat_manager` 是参考实现：它通过 `set_restart_impl()` 把具体的重启逻辑注入看门狗，因此换成其他 OneBot 协议端只需替换实现，看门狗逻辑可直接复用。

## 时间处理约定

SQLite 的 `CURRENT_TIMESTAMP` 写入 **UTC**。所有「拿 Python 时间与 DB 时间戳比较」的地方**必须**走 `memory/timeutil.py`，否则在非 UTC 时区会产生固定偏移。

SQL 内部的比较（`julianday('now')` vs `julianday(col)`）两侧同为 UTC，无需处理。