# 架构说明

本文描述 Stella 的目录结构、模块职责与一次消息的完整处理流程。记忆系统的设计理由见 [记忆系统](memory-system.md)，能力路由与工具执行见 [能力系统](capability-system.md)，配置项见 [配置参考](configuration.md)。

## 分层概览

```
QQ 群消息
    ↓  OneBot V11 / NapCat
stella_project/plugins/bot_main/ai_gateway.py     ← 事件接入层
    ↓
core/pipeline.py                                  ← 编排层（pre hooks → LLM → post hooks）
    ↓
capability/*                                      ← 能力层（Router 判定 / Comes 执行工具）
memory/*                                          ← 记忆层（写入 / 晋升 / 检索 / 压缩）
    ↓
SQLite（memory/agent_memory.db）
```

五层各自独立：接入层只做协议适配与调度，编排层不含业务逻辑，能力层不感知人格与记忆内容，记忆层不感知 QQ，存储层由 `memory/schema.py` 统一管理迁移。

能力层与记忆层是**并列**的两条分支，都由编排层的同一个前置钩子激活，彼此之间只通过 `ChatContext` 通信、不互相调用。

> 存储层有**两层归属维度**：`group_id` 是真实 QQ 群，`group_shared_space` 是群组共享空间。前者承载「当下这场对话的状态」，后者承载「对人的长期认知」。详见下文「主要数据表」。

## 目录结构

```text
Stella_project/
├── bot.py                          # NoneBot 启动入口
├── pyproject.toml                  # 依赖、NoneBot 配置、ruff/pytest 规则
├── pyrightconfig.json              # 类型检查配置
│
├── config/
│   ├── settings.py         # 集中配置：读 .env，导出模块级常量
│   ├── spaces.py           # 群组共享空间解析（config/spaces/*.toml）
│   ├── spaces/             # 空间配置（文件名即空间名，不进 .env）
│   └── capabilities/       # 能力声明（文件名即 domain，可选；见 *.example）
│
├── core/                           # 与业务无关的编排骨架
│   ├── context.py                  # ChatContext：一次处理的运行期载体
│   ├── tasks.py                    # Task / Result / TaskGraph 协议（四模块共用）
│   ├── pipeline.py                  # Pipeline 编排器 + prompt 拼装顺序
│   └── llm/
│       ├── base.py                 # LLM 后端抽象接口
│       ├── lm_studio.py            # LM Studio 后端（含重试与截断告警）
│       ├── openai_client.py        # 完整 chat-completions 客户端（tools / 图片 / 流式）
│       └── scheduler.py    # 模型级资源闸门（FIFO 串行 + 排队可观测性）
│
├── capability/                     # 能力层（详见 docs/capability-system.md）
│   ├── registry.py                 # Capability / Provider / 注册表单例 + 健康度退避
│   ├── loader.py                   # config/capabilities/*.toml → 注册表
│   ├── hooks.py                    # activate_capabilities 前置钩子（管线接入点）
│   ├── router/                     # 三级路由
│   │   ├── types.py                # Route / CapabilityHit
│   │   ├── rules.py                # Level 0：关键词规则（零延迟）
│   │   ├── semantic.py             # Level 1：Embedding 原型匹配
│   │   ├── fallback.py             # Level 2：更强模型兜底（默认关闭）
│   │   └── benchmark.py            # 路由准确率基准（决定能否开记忆门控）
│   ├── comes/                      # 工具执行层
│   │   ├── executor.py             # Capability → Provider → Tool → Result
│   │   └── summarizer.py           # Result.data → Result.summary
│   └── adapters/
│       └── astrbot.py              # llm_tools → Provider 自动派生 + bootstrap
│
├── memory/                         # 记忆系统主体
│   ├── SYSTEM.md                   # 机器人系统提示词
│   ├── schema.py                   # Schema 迁移（Additive，当前 v8）+ 来源枚举
│   ├── timeutil.py                 # DB 时间戳统一按 UTC 解析
│   ├── text_similarity.py          # 内容相似度与合并（单一真相源）
│   │
│   ├── pre_processors.py           # 消息落库、短期上下文、用户上下文组装
│   ├── session_context.py          # 会话压缩的状态与判定（纯逻辑）
│   ├── session_compact.py          # 会话压缩的执行侧（取消息、调 LLM、写回）
│   ├── post_processors.py          # 输出解析、破防过滤、分行、思考日志
│   ├── prompt_builder.py           # 记忆与上下文 → 分区 Prompt
│   │
│   ├── consolidator.py             # 整合：消息 → 摘要/画像/候选（含候选强化）
│   ├── consolidation_prompt.py     # 整合任务的 JSON 输出模板
│   ├── extraction_prompt.py        # 阶段2 候选提取的 prompt 模板
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
│   └── link_monitor/               # OneBot 链路监测（心跳 + 主动探活，只告警）
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
群消息 → group_silent_listener（priority 0, block=False）
        → pre_processors.record_message() → group_messages 表
        → proactive.record_message() → 活跃度时间戳（内存）
        → session_context.touch() → 会话活动时间戳（内存）
```

静默监听器处理**每一条**群消息，包括不 @ 机器人的。落库时按来源分级打标：

| `source_kind` | 含义 | 在记忆系统中的权重 |
|---|---|---|
| `AT_MENTION` | 用户直接对 Bot 说 | 高密度证据，单次即可晋升 |
| `PASSIVE` | 被动摄入的群聊 | 需复现才能晋升 |
| `BOT_SELF` | Bot 自己的发言 | **只作上下文，绝不产出候选** |

`BOT_SELF` 是必需的：没有它，用户回答「对」「手机」这类简短回应时，整合模型看不到 Bot 问了什么，只能放弃或自行编造语境。

链路监测由**独立的** `event_preprocessor` 刷新心跳（任何 OneBot 事件都算，包括协议端的心跳元事件），不是 `group_silent_listener` 的职责。

> **落库监听器必须是最高优先级（0）**，且必须排在所有 `block=True` 的处理器之前。
>
> NoneBot 中 `block=True` 会阻止事件继续传播给优先级更低的处理器。落库监听器若排在 `chat_handler` 之后，**@ 机器人的消息会被拦截而永不入库**——普通群聊正常记录，唯独最有价值的 @ 对话全部丢失。
>
> 2026-08-17 实测：落库监听器为 `priority 99` 时，13 批整合共消费 270 条消息，`AT_MENTION` 计数**全部为 0**。@ 对话是设计上唯一稳定的用户信息源（见 `design_docs/check_point/`），这条回路从未运行过；连带 `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT`、`MEMORY_AT_MENTION_CONFIDENCE_BONUS` 与主动 @ 的候选验证模式（`mode=verify`）全部空转。
>
> 职责顺序是「先落库，再决定要不要回复」。新增任何 `block=True` 的处理器时，其 priority 必须大于 0。
>
> 落库先行的连带影响：当前这条消息会同时出现在自己的上下文尾巴里与「【现在 用户(X) 对你说】」标记中。这个重复是可接受的——同句重复是强化而非混淆，而当前输入的显式标记仍在（2026-08-16 接错话缺陷的修复）。

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

> 三个监听器的优先级关系（数字越小越先执行）：
>
> | 监听器 | priority | block | 职责 |
> |---|---|---|---|
> | `group_silent_listener` | 0 | 否 | 落库（必须最先，见上文） |
> | `toggle_handler` | 1 | 是 | 运行时开关命令 |
> | `chat_handler` | 2 | 是 | @ 回复主流程 |
>
> `toggle_handler` 必须早于 `chat_handler`，否则「安静」这类命令会被当成普通对话交给 LLM。

### 3. 上下文构建（pre hooks）

Pipeline 的 pre hook 按 priority **降序**执行：

```
build_context          (50)  → ctx.short_term
activate_capabilities  (45)  → ctx.route，并行激活 {长期记忆检索, Comes 工具执行}
```

**`build_context`** 组装三层并存的短期上下文：

- **话题层摘要**：`short_term_context.active_summary` / `pending_topic`，由整合器产出，按设计滞后；超过 `SHORT_TERM_SUMMARY_STALE_MINUTES` 未更新时标题改为「之前的话题」并注明时长
- **原始尾巴**：最近 `RECENT_TAIL_LIMIT` 条原始消息，含 Bot 自己的发言（渲染为「我」）。超出 `RECENT_TAIL_MAX_AGE_MINUTES` 时间窗的旧消息被过滤（2026-08-15 修复），窗口内部相邻消息间隔超过 `RECENT_TAIL_GAP_MARK_MINUTES` 时插入断层标记「（……中间隔了 X……）」
- **会话摘要**：本场对话中已滚出尾巴窗口的较早内容，由 `session_compact` 在每次回复后异步压缩产出

三层按消息 id 划分，**绝不重叠**：

```
会话摘要：summarized_up_to_id → 尾巴起点（较早部分，已压缩）
原始尾巴：最近 RECENT_TAIL_LIMIT 条（原文）
话题摘要：整合器产出的跨会话背景
```

重叠会导致同一段对话出现两个版本，模型以摘要为准从而接错话题（2026-08-13 缺陷的成因）。尾巴起点（`ctx.tail_start_id`）取「第一条真正进入尾巴」的消息 id——被时间窗过滤掉的归入待压缩区间，不会丢失。

三层必须并存。摘要要累积到阈值才更新，只靠它会看不到最近几轮对话——Bot 会把用户的简短回应接到上一个话题上去。

**`activate_capabilities`** 做两件事：先由 Router 判定本次需要哪些能力，再**并行**激活记忆检索与工具执行（详见 [能力系统](capability-system.md)）。

```
capability.router.route(消息)              ← 三级级联：规则 → Embedding → 模型兜底
  → ctx.route（判定快照，写进 thought 日志与决策轨迹）
  ↓
asyncio.gather(
    build_user_context(ctx),               ← 长期记忆检索（下方）
    run_comes(ctx, route),                 ← 工具执行，仅 route.tool 时
)
```

`build_user_context` **不再单独注册为钩子**，已被本钩子接管：Memory 与 Comes 必须并行，两个独立钩子只能串行。

`build_context` 保持无条件执行——短期上下文是对话素材，与「要不要检索长期记忆」无关。

> **记忆门控默认关闭**（`ROUTER_GATE_MEMORY=false`）：Router 照常判定与记录，但记忆检索仍无条件执行。误判 `memory=False` 会让 Stella 当轮悄悄丢失长期记忆——不抛异常、不影响回复，只是「它突然不记得你了」，与 2026-08-17 那次 `AT_MENTION` 全为 0 的缺陷同一类型。要打开先跑 `python -m capability.router.benchmark` 确认记忆假阴为 0。

**`build_user_context`** 走 v2 检索（`MEMORY_V2_ENABLED`）：

画像与记忆按**共享空间**检索（`resolve_space(ctx.group_id)`），而非按 QQ 群。

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

`core/pipeline.py` 把上下文、工具结果与消息拼成最终 prompt。**拼装顺序取决于 `intent`**：

| intent | 顺序 | 原因 |
|---|---|---|
| 普通 | 上下文 → 工具结果 → 用户消息 | 用户输入在最后，模型自然去回应它 |
| `proactive_at` | **任务指令 → 工具结果 → 上下文** | `ctx.message` 是指令而非用户输入；若放在最后，模型会去接上下文尾部的对话而不是执行指令 |

工具结果段落只吃 `ctx.tool_summaries`（压缩后的一句话），**`Result.data` 全程不进 prompt**——一次搜索能返回几千字，原样拼进来会把记忆与对话上下文一起挤出窗口。它夹在上下文与当前输入之间：工具结果是「回答这句话的证据」，必须离当前输入近，而「请回应这句话」必须留在最后一行。

> 调用经 `core/llm/scheduler.py` 的资源闸门串行。**LM Studio 不限制并发**，多请求同时打到同一模型会并发推理、互相拖慢，因此应用层必须为每个共享模型设一道闸门：
>
> | 资源 | 模型 | 使用者 |
> |---|---|---|
> | `chat` | 主聊天模型 | 聊天回复、会话压缩、候选提取、embedding 编码、Comes 工具循环、Router Level 2 |
> | `consolidation` | 整合模型 | 两阶段整合的阶段 1 |
>
> 同一资源内严格 FIFO（`asyncio.Lock` 的等待队列本就是 FIFO），不同资源之间可真正并行。
>
> 这也是「Memory 与 Comes 并行」的边界：两者的**模型调用**仍在 `chat` 闸门里 FIFO 串行，`gather` 换来的是 Memory 的 SQL/FTS 查询与 Comes 的 HTTP 等待互相重叠。不是假并行，但也不是两块 GPU。
>
> **调用方绝不能同时持有两把闸门**：若先持 consolidation 再等 chat（或反之），会发生跨模型队头阻塞——一个资源空闲时却在等另一个资源的队头任务释放，把两条队一起堵死。这正是 `consolidate_group` 用独立的群级锁、把阶段 1 与阶段 2 拆成两个互不嵌套的持有窗口的原因。
>
> 每次获取都记录等待时长、持有时长与队列深度，超阈值告警；`core.llm.snapshot()` 可导出各资源的累计统计。多群部署下这是判断「延迟来自哪个资源、谁在排队」的唯一手段。
>
> 超时与异常都有兜底回复。诊断信息（后端、模型、耗时、完整 prompt）写入 `ctx`，由 `log_thought` 落盘。

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
消息积累 → maybe_consolidate()（@ 触发 / 主动发言前 / 定时排空 / 会话结束）
        → 阶段1（整合模型，CPU）
        │    输出短期摘要 + 用户画像 + has_self_disclosure 布尔
        ↓ 仅当 has_self_disclosure 为真
        → 阶段2（主聊天模型，GPU）
        │    精确提取 memory_candidates，结果覆盖阶段1（含空数组）
        → 候选强化：同事实累积证据而非重复插入
        → MemoryManager.process_new_candidates()
          ├─ 超期 OBSERVING → REJECTED
          ├─ Gate 1 三档判定 → 晋升 / 继续观察
          ├─ 冲突检测 → 旧记忆标 CONFLICT
          ├─ 相似合并（同空间同用户同类型）或新建
          └─ 每用户配额淘汰（按空间）
        → FTS5 索引同步
        → 轻量压缩（节流触发）
```

> **为什么拆两阶段**：小模型能总结主题，却在噪音环境下系统性地把候选提取判空——2026-08-16 实测 7 批整合全部返回空候选，而信息明确出现在它自己写的 `active_summary` 里，是「读到了但主动弃掉」。候选提取是高精度抽取任务，交给主聊天模型。
>
> 阶段 2 由软门槛控制（阶段 1 的布尔判断），只在真有用户自我披露时唤醒，日常刷屏与寒暄不消耗 GPU。阶段 2 成功时其结果**覆盖**阶段 1 的候选，**包括返回空数组的情况**——那是大模型复核认为确实没有，正好纠正小模型的误判；调用或解析失败则回退阶段 1 候选。
>
> 两阶段各自持有对应资源的闸门，**绝不同时持有**（见上文）。整合的群级串行由 `consolidator` 内的模块级群锁保证，与模型闸门分离。
>
> 整合的四个触发点：@ 触发前（force 小批次）、主动发言前（force）、定时排空（`CONSOLIDATION_SCHEDULE_INTERVAL`）、会话空闲结束。定时排空是必需的——被动摄入速度超过整合速度时会无界积压，超过 `MESSAGE_CLEANUP_KEEP_COUNT` 后未整合消息会被清理丢弃。

### 7. 定时任务

| 任务 | 周期 | 作用 |
|---|---|---|
| 主动发言检查 | `PROACTIVE_CHECK_INTERVAL` | 睡眠/苏醒播报 → 尝试主动 @ → 尝试主动插话 |
| 链路监测 | `LINK_MONITOR_CHECK_INTERVAL` | 事件超时后主动探活，失败则告警（不重启） |
| 消息表裁剪 | 每日 `MESSAGE_CLEANUP_HOUR` 点 | 每群保留最近 N 条，同时清理过期追踪 |
| 周度压缩 | 每 7 天 | 全量去重、原子化、归档、衰减 |
| 定时整合排空 | `CONSOLIDATION_SCHEDULE_INTERVAL` | 逐批消化各群的整合积压 |
| 会话空闲检查 | `SESSION_IDLE_CHECK_INTERVAL` | 空闲超时的会话清空压缩状态并触发一次完整整合 |

## 关键数据结构

### ChatContext

一次处理的运行期载体，是各模块间传递数据的唯一通道。

| 分组 | 字段 |
|---|---|
| 输入标识 | `user_id` `group_id` `group_shared_space` `msg_id` `message` `source_kind` |
| 处理产物 | `raw_output` `thought` `action` `reply` `lines` |
| 诊断 | `trigger` `intent` `intent_detail` `llm_backend` `llm_model` `llm_elapsed` `prompt_log` |
| 结构化上下文 | `short_term` `user_profile` `memories_for_prompt` `tail_start_id` |
| 记忆 v2 | `memory_mode` `conversation_memories` `behavior_constraints` `memory_trace` |
| 任务调度 | `route` `task_results` `tool_summaries` |
| 平台句柄 | `raw_event` `bot` |

`group_id` 始终是真实 QQ 群号；`group_shared_space` 由 `config.spaces.resolve_space()` 自动填入，是记忆与画像的归属标识。两者不可混用。

`raw_event` / `bot` 是**不透明句柄**：Comes 调 AstrBot 工具时，工具 handler 内部会用 `event.send()` / `event.bot.call_action()`，必须是真实对象，构造不出等价替身。`core` 不解释它们的类型、也不碰任何方法，只负责从接入层传递到能力层。两者都标了 `repr=False`——OneBot 事件的 `repr` 会把整条消息与 sender 全展开，日志里 `ChatContext` 一旦被 `repr` 就会刷屏。

`route` 的类型标注是 `Any` 而非 `Route`：`core` 是「与业务无关的编排骨架」，不该 import `capability`，反向依赖会成环。

### 主要数据表

**两层归属**。`group_id` 承载「当下这场对话的状态」，`group_shared_space` 承载「对人的长期认知与身份」。多个 QQ 群可归入同一空间以共享认知，但绝不能反过来——把两个群的消息混进同一条尾巴，Bot 会在 A 群回应 B 群的对话。

| 表 | 归属 | 作用 |
|---|---|---|
| `group_messages` | QQ 群 | 原始群消息（含 `source_kind`） |
| `short_term_context` | QQ 群 | 每群的话题摘要与关键发言 |
| `consolidation_state` | QQ 群 | 每群的整合 checkpoint |
| `proactive_state` | QQ 群 | 主动 @ 的配额、冷却、退避状态 |
| `group_runtime_state` | QQ 群 | 静音开关、睡眠/苏醒播报去重 |
| `memory_candidates` | **空间** | 记忆候选（含 `occurrence_count` / `source_kinds` / `first_seen_at`） |
| `memories` | **空间** | 长期记忆（含 `usage_tags` / `visibility` / `behavior_rule`） |
| `memories_fts` | **空间** | FTS5 全文索引（按 `mem_id` 与 `memories` 同步） |
| `user_profiles` | **空间** | 用户稳定画像，主键 `(group_shared_space, user_id)` |
| `atomic_facts` | **空间** | 长记忆拆分出的原子事实 |
| `memory_traces` | 两者 | 记忆决策追踪（`group_id` 记触发来源，`group_shared_space` 记检索空间） |
| `compressor_stats` / `compressor_state` | 全局 | 压缩统计与节流状态 |
| `schema_meta` | 全局 | Schema 版本号 |

Schema 迁移采用 **Additive Migration**：只加字段与索引，绝不删数据；首次迁移前自动备份。独立执行：

```bash
python -m memory.schema --dry-run   # 预览
python -m memory.schema             # 执行
python -m memory.schema --backup    # 仅备份
```

> **列名变更是例外**。SQLite 无法 ALTER 主键或重命名列，v7（画像分群）与 v8（记忆表改按空间归属）都选择**不写一次性迁移代码，而是归档旧库让程序重建**——一次性迁移代码只用一次却要长期维护，且当时的库数据量很小。`_migrate` 里保留了旧库检测：发现记忆表仍有 `group_id` 列时输出 error 提示归档重建。
>
> 归档旧库时**连 `stella_memory_backup.db` 一起移走**，否则 `backup_database()` 见备份已存在即跳过，会留下「看起来有备份、实际备份错了」的状态。

## 本地状态接口

`deploy status` 与桌面 GUI 需要读到进程内状态（`link_status()`、调度器排队深度），外部进程拿不到。

**为什么用 HTTP 而不是状态文件**：状态文件有陈旧问题——Bot 崩了之后文件仍在，读到的「运行中」是假的。HTTP 端点天然「连不上就是没运行」，还顺带覆盖了「进程在但 HTTP 服务没起来」的中间态（`api_reachable=false`，GUI 据此显示「正在启动…」）。

**为什么不新增端口**：NoneBot 本就跑着 FastAPI/uvicorn，反向 WS 端点 `/onebot/v11/ws` 就是它提供的。状态路由直接挂在同一个 app 上（`GET /stella/status`），Stella 仍然只有一个监听端口（`PORT`）。

**实现**：`stella_project/plugins/bot_main/status_api.py`。`setup_status_api()` 在 ai_gateway 的启动段（扩展加载之后）调用；`build_payload()` 聚合 `link_status()`、`core.llm.snapshot()` 与版本/进程信息，返回 `{version, pid, uptime_seconds, allowed_group_count, link, scheduler}`。消费方是 `deploy/process.py` 的 `_fetch_live_status()`（回环查询、1 秒超时）与 GUI。

**安全约束**：`HOST` 可能是 `0.0.0.0`（NapCat 在另一台机器时必须如此），此时路由暴露到局域网。两道防护：① 只接受回环地址的请求，其余返回 403；② 响应体不含凭据与群聊内容——`allowed_group_count` 只给数量不给群号。

## 扩展机制

`extensions/` 下的每个模块/包若提供 `setup(pipeline)`，启动时会被自动加载。扩展可以注册 Hook、注入实现、启动自己的定时任务。

`link_monitor` 是参考实现：它在 import 时注册一个 `event_preprocessor`（任何 OneBot 事件刷新心跳）、两个 driver 钩子（`on_bot_connect` / `on_bot_disconnect`）与一个自己的定时任务（事件超时后主动探活，探活失败只告警不重启）。扩展无需改动业务主程序即可接入。

## 时间处理约定

SQLite 的 `CURRENT_TIMESTAMP` 写入 **UTC**。所有「拿 Python 时间与 DB 时间戳比较」的地方**必须**走 `memory/timeutil.py`，否则在非 UTC 时区会产生固定偏移。

SQL 内部的比较（`julianday('now')` vs `julianday(col)`）两侧同为 UTC，无需处理。

## 两层归属的分界线

「群」在本项目里有两个含义，混用会产生难查的错乱。

**按 QQ 群归属的**（当下这场对话的状态）：
- 消息尾巴、整合 checkpoint、短期话题、会话压缩状态
- 静音开关、主动 @ 配额与冷却、活跃度统计

**按共享空间归属的**（对人的长期认知与身份）：
- 用户画像、长期记忆、原子事实、FTS 索引
- 人格（system prompt）、发言策略

**分界依据**：如果一个数据被两个群共用会造成「答错话」，它必须按 QQ 群；如果被两个群共用是「同一个人的同一份认知」，它应该按空间。

代码里的约定：函数形参用 `group_id: int` 表示 QQ 群，用 `group_shared_space: str` 表示空间。`resolve_space(qq_group_id)` 是唯一的转换入口。

一个遗留的歧义：`long_term_memories`（待废弃的旧兼容表）列名仍是 `group_id`，但**写入与查询的都是空间标识**。为一张即将淘汰的表改列名不值得，但这个不一致必须知道。