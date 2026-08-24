# 能力系统（Capability Router 与 Comes）

本文描述 Stella 的任务调度层：Router 判断需要什么能力，Comes 执行工具，两者与聊天、记忆之间只传递任务与结果。设计过程见 `design_docs/Stella 智能机器人架构升级方案：基于 Capability Router 与 Comes 工具执行层的任务调度系统.md` 与 `design_docs/Capability Router 与 Comes 落地方案 v1.0.md`。

## 为什么需要它

兼容 AstrBot 生态时发现：大量功能型插件依赖 LLM 工具调用。如果把所有插件的工具定义直接注入 Stella 的主聊天上下文，会同时出现四个问题——

- 工具 schema 每个约 60~120 token，装满插件后 8192 的工作窗口装不下正常对话；
- 工具描述会干扰聊天，模型倾向于"找个工具用一下"而不是回话；
- 插件数量增加后完全不可扩展；
- Stella 的人格与工具逻辑高度耦合。

解决方式是**把能力解耦，用任务协议通信**：

```
                  User Message
                       |
                 +-------------+
                 |   Router    |   判断需要哪些能力
                 +-------------+
                       |
        +--------------+--------------+
        |              |              |
      Stella        Memory          Comes
     人格与回复     记忆检索       工具执行
        |              |              |
        +--------------+--------------+
                       |
                 Final Response
```

四个模块之间**不共享聊天上下文**，只传递 `Task` 与 `Result`。

## 上下文隔离的两个方向

这是整套设计的核心，两边都要挡住：

| 方向 | 挡什么 | 怎么挡 |
|---|---|---|
| Stella → Comes | Stella 的人格、聊天上下文、记忆 | Comes 的请求只有 `COMES_SYSTEM_PROMPT` + 任务目标 + 本次命中能力的 1~3 个工具 schema |
| Comes → Stella | 工具 schema、工具原始返回 | Stella 只拿到 `Result.summary`（压缩后的一句话）；`Result.data` 全程不进 prompt |

`Result.data` 也必须挡住：一次搜索能返回几千字，原样拼进 prompt 会把记忆与对话上下文一起挤出窗口。工具描述会污染上下文，结果数据同样会。

> `summary` 只在任务成功（`success` / `partial`）时产出。失败时的模型输出往往是受限 agent 的自言自语（「我觉得不用查」），它会被冠上「刚刚查到的信息（真实数据）」的标题送给 Stella，于是 Stella 把执行器的嘟囔当成事实转述给用户。这条不变量由 `Result` 自己保证，不依赖消费方记得先查 `.ok`。

## 目录结构

```text
core/tasks.py                    # Task / Result / TaskGraph 协议（四个模块共用）
capability/
├── registry.py                  # Capability / CapabilityProvider / 注册表单例
├── loader.py                    # config/capabilities/*.toml → 注册表
├── hooks.py                     # activate_capabilities 前置钩子（管线接入点）
├── router/
│   ├── __init__.py              # route() 三级级联入口
│   ├── types.py                 # Route / CapabilityHit
│   ├── rules.py                 # Level 0：关键词规则
│   ├── semantic.py              # Level 1：Embedding 原型匹配
│   ├── fallback.py              # Level 2：更强模型兜底
│   └── benchmark.py             # 路由准确率基准（决定能否开门控）
├── comes/
│   ├── __init__.py              # execute / execute_all
│   ├── executor.py              # Capability → Provider → Tool → Result
│   └── summarizer.py            # Result.data → Result.summary
└── adapters/
    └── astrbot.py               # llm_tools → Provider 自动派生 + bootstrap
```

## Task / Result 协议

```
Task                              Result
- task_id     任务号（DAG/调试）   - status     success / failed / partial / cancelled
- type        chat.respond 等      - data       工具原始返回，**不进 prompt**
- capability  需要的能力 id        - summary    压缩后的一句话，**只有它进 prompt**
- objective   语义层目标           - metadata   provider / 耗时 / 调试信息
- input       已知槽位
- dependencies 依赖的 task_id
- constraints  执行约束
```

两条容易写错的约定：

**`objective` 属于语义层。** 写「查询东京明天天气」，不写 `调用 weather_api()`。具体走哪个 Provider、填什么参数由 Comes 决定——这样换插件不必改任务生成侧。实现里直接用用户原话作为 objective：提炼只会丢信息（「东京明天」提炼成「查天气」后城市和日期就没了，Comes 反而要去猜）。

**`status` 与工具调用是否成功无关。** API 正常返回但查不到结果是 `failed`，不是 `success`：

| 情况 | status |
|---|---|
| 至少一个工具返回了非 error 的实质内容 | `success` |
| 部分工具成功、部分失败 | `partial` |
| 无工具被调用 / 全部报错 / 超时 | `failed` |
| 上游中止（`event.is_stopped()`） | `cancelled` |

`failed` 与 `cancelled` 必须分开：前者要告警（工具坏了），后者是正常的提前退出（插件钩子里 `stop_event` 了），混在一起会淹掉真问题。

## Capability 分层

> 插件不是能力，插件只是能力的实现方式。

```
Capability Domain  →  Capability     →  Provider          →  Tool
information           weather.query     AstrBot 天气插件     get_weather()
```

注册表是**唯一**知道「能力 ↔ 工具」映射的地方，别处不许自己拼这层。它是模块级单例（与 `star_handlers_registry`、`llm_tools` 同理）——放在类或函数里会让不同 import 路径各拿到一份，注册表分裂后表现为「插件明明装了但路由不到」。

> 注册表单例刻意**不从 `capability/__init__.py` 再导出**。在包入口 `from capability.registry import registry` 会让包属性 `capability.registry` 从子模块变成那个单例对象，于是 `import capability.registry as m` 拿到的是实例而不是模块（`import a.b as c` 会退化成 `getattr(a, "b")`）。这种遮蔽只在 `__init__` 已执行时出现，行为随 import 顺序变化。取用一律写 `from capability.registry import registry`。

### 两条注册通路

**显式声明** `config/capabilities/*.toml`（**文件名即 domain**，格式见同目录 `.example`）：

```toml
[[capability]]
id = "weather.query"
description = "查询天气信息"
examples = ["明天天气怎么样", "会不会下雨"]   # Level 1 语义原型语料，写自然句子
keywords = ["天气", "气温", "下雨"]            # Level 0 字面匹配，写名词
providers = ["get_weather"]                    # llm_tools 里的工具名，不是插件名
```

**自动派生**：启动时把没有被任何声明认领的活跃工具注册成 `tool.<工具名>`，`description` 取工具描述。零配置——装上插件就能被路由到。

两者的归属靠「先到先得」判定，而**装配顺序不可交换**：必须先读声明、再自动派生。反过来的话自动派生会先把每个工具占成 `tool.<name>`，声明再想认领同一个工具就抢不到，于是精心写的中文 examples 永远不会被用到——而这不报错，只表现为「路由准确率没提升」。顺序由 `adapters/astrbot.py::bootstrap` 保证，它在 `bot.py` 里注册于 `initialize_plugins` **之后**（插件可以在自己的 `initialize()` 里调 `add_llm_tools`，先跑就会漏掉）。

自动派生的能力有先天局限：工具描述大多是英文短句而用户说中文，跨语言语义匹配准确率明显偏低；且它没有 `keywords`，拿不到 Level 0 的零延迟通路。这个局限刻意不去补——从英文描述生成中文 examples 需要调模型且质量无法验证，错的 examples 比没有 examples 更糟（会把不相关的请求吸进来）。需要好的路由质量就写 TOML，是一次性的几行配置。

## Router 三级级联

```
Level 0  规则快速判断     零延迟，不调模型
   ↓ 给不出结论
Level 1  Embedding 语义   一次编码（原型向量按注册表版本缓存）
   ↓ 落在不确定带
Level 2  更强模型兜底     默认关闭，只处理极少量请求
   ↓ 不可用
降级     chat + memory，不调工具
```

**降级是唯一的失败归宿。** embedding 不可用、注册表为空、超时、任何异常，都返回 `chat=True, memory=True, tool=False`。路由绝不能成为主链路的硬依赖。保守方向是刻意的：漏调一次工具用户最多再问一遍，凭空调一次工具则可能真的发出消息或改变外部状态。

### Level 0 只在能确定「需要什么」时才短路

三种情形会拍板：keywords 命中某能力（`tool=true` 且能力已定）、整句纯寒暄（`memory=false`）、只有记忆意图无工具意图（省掉一次 embedding）。

命中「帮我查一下」**不算**拍板——后面可能跟天气、股价、番剧，能力选择必须交给 Level 1。

能力关键词**只认显式声明，绝不从 examples 里猜**。中文没有词边界，从「会不会下雨」切出来的候选里既有「下雨」也有「不会」，后者会命中几乎任何句子（「我不会用这个软件」→ 去查天气）。滑窗切词能切出好词，但同时一定会切出坏词，而坏词的代价是凭空调一次工具。

纯寒暄判定必须**整句匹配**且集合极窄：「你好，还记得我的旅行计划吗」不算寒暄。判为不需要记忆的代价不对称，宁可多查一次。

### Level 1 原型向量

原型向量 = 该能力全部 `prototype_texts()`（examples + description）编码后的**均值**再归一化。取均值而不是逐条取最大：examples 是同一意图的不同说法，均值代表这个意图的中心，对个别写得不好的 example 更稳健；逐条取最大会让一条跑偏的 example 把整个能力的召回拉歪。

原型向量按**注册表版本号**缓存。装了新插件（注册表变更 → version 自增）时缓存自动失效，否则新能力永远匹配不上——这个退化不报错，只表现为「插件装了但用不了」。换 embedding 模型也会失效（维度与语义空间都不同）。

复用 `memory/embeddings.py` 的 `EmbeddingService`（缓存、L2 归一化、经 chat 闸门串行、失败返回 `None` 让调用方降级），不另建客户端。

> `Route.top_score` 是**过滤之前**的最高分，必须单独记录。`capabilities` 已被 `ROUTER_SEMANTIC_THRESHOLD` 过滤过；从它推最高分会让 `(ROUTER_UNCERTAIN_FLOOR, ROUTER_SEMANTIC_THRESHOLD)` 区间内的分数一律读成 0，Level 2 的触发区间被无声地缩窄。

## Comes 执行

```
Task.capability
      ↓  registry.find_providers()（priority 降序，排除退避中的）
Provider 列表
      ↓  取 llm_tools 里对应的 FunctionTool，组成只含它们的 ToolSet
ToolSet（1~3 个工具，不是全部）
      ↓  受限 agent：run_tool_loop(provider, req, event)
LLMResponse + req.tool_calls_result
      ↓  summarizer
Result(status, data, summary, metadata)
```

工具循环复用 `astrbot_compat.llm.agent.run_tool_loop`：它已实现参数过滤（模型会编出 schema 外的参数，直接传给插件会 TypeError）、超时、异步生成器归一、以及插件依赖的全套生命周期钩子。这些行为是与上游多轮实测对齐出来的，重写一定漏。Comes 只换两样：更小的 ToolSet，和自己的 system prompt。

**`data` 与 `summary` 的来源**：`data` 是各 `ToolCallMessageSegment` 的 `(name, content)`（工具原始返回）；`summary` 是受限 agent 的 `completion_text`——它读完工具输出后写的那句自然语言，天然就是摘要。**压缩不再调模型**：为摘要多花一次 27B 往返是在聊天主链路上多加一次串行等待，而用户正在等回复。

**无参直调**（`COMES_DIRECT_CALL_NO_ARGS`）：命中能力只有一个 Provider、且其工具没有必填参数时跳过 LLM 直接调工具。省一次 27B 往返，且不可能填错参数。

**Provider 健康度**：工具级别记账，连续失败到 `COMES_PROVIDER_FAILURE_THRESHOLD` 后进入**时间窗**退避（`COMES_PROVIDER_RECOVER_SECONDS`），期间该能力的其它 provider 顶上。只对本次真的被调用过的工具记账——给没被选中的 provider 记账会让「一直没被选中」慢慢累积成退避。退避不是永久禁用：外部 API 抖动是常态，永久禁用会让一次网络波动永久关掉一个能力，而这不报错、只表现为「这个功能后来就不好使了」。

## 接入管线

pre hook 按 priority **降序**执行：

```
50  build_context           # 短期上下文（摘要 + 尾巴 + 会话摘要），始终执行
45  activate_capabilities   # Router 判定 → 并行 {长期记忆检索, Comes 执行}
```

`build_user_context` **不再单独注册**，已被 `activate_capabilities` 接管。方案要求 Memory 与 Comes 并行，两个独立钩子只能串行，必须收进同一个 `gather`。再单独注册一次会让记忆检索跑两遍。

`build_context` 保持无条件执行：短期上下文是对话素材，与「要不要检索长期记忆」无关。

> **关于并行的诚实说明**：Comes 的 LLM 调用与 Memory 的 embedding 编码共用 `RESOURCE_CHAT` 闸门，两者的**模型调用**仍会 FIFO 串行。`gather` 拿到的是真实收益的那部分：Memory 的 SQL/FTS 查询与 Comes 的 HTTP 等待互相重叠。这不是假并行，但也不是两块 GPU。

钩子**绝不抛异常**，两条分支互不拖累（`return_exceptions=True`）。能力层是增量功能，它坏掉的后果应该是「这轮没用上工具」，而不是「Stella 不说话了」。

### 平台句柄

Comes 调 AstrBot 工具时，工具 handler 内部会用 `event.send()` / `event.bot.call_action()`，必须是真实对象，构造不出等价替身。因此 `ChatContext` 带两个 opaque 字段 `raw_event` / `bot`，由 `handle_chat` 填入，core 不解释其类型。

只有 @ 回复这条路径能提供它们。主动发言没有对应的用户事件，那条路径上工具能力自然不可用——属正常，不报错。指令型 intent（`proactive_at` / `proactive_join`）也**不做能力路由**：`ctx.message` 是给 Stella 的任务指令而非用户请求，「生成一句搭话」里出现「查」字不代表用户想查什么。

### 结果如何回到 Stella

`core/pipeline.py::_compose_prompt` 的段落顺序：

```
{上下文}

【刚刚查到的信息（真实数据，回答时以此为准）】
东京明天 27℃，晴，降雨概率 10%。

【现在 用户(123) 对你说】帮我查一下东京天气
请回应这句话。上面的对话记录只是背景，不要去回应其中的其他内容。
```

工具结果夹在上下文与当前输入之间：它是「回答这句话的证据」，必须离当前输入近；而「请回应这句话」必须留在最后一行，否则模型会把它当成又一段背景。指令型 intent 下顺序为：指令 → 工具结果 → 上下文。

措辞明确标注**真实数据**是必要的：不标注的话模型会把它当成上下文里又一段别人说的话，进而复述、质疑甚至反驳它。

## 记忆门控：为什么默认关闭

`ROUTER_GATE_MEMORY=false` 时，Router 照常判定、照常写日志与决策轨迹，但记忆检索**仍无条件执行**。

Router 误判 `memory=False` 会让 Stella 当轮悄悄丢失长期记忆——不抛异常、不影响回复，只是「它突然不记得你了」。这与 2026-08-17 那次 `AT_MENTION` 全为 0 的缺陷同一类型：静默、难察觉、后果严重。

要打开它，先跑 benchmark 确认**记忆假阴为 0**：

```bash
python -m capability.router.benchmark              # 全链路（需要 embedding 服务）
python -m capability.router.benchmark --rules-only # 只测 Level 0，可进 CI
python -m capability.router.benchmark --cases my.json
```

报告把四类错误**分开计数，刻意不合成单一准确率**——合成会把高代价错误藏在平均值里：

| 错误 | 后果 | 严重度 |
|---|---|---|
| 记忆假阴（该读却不读） | Stella 突然不记得你了，不报错 | **高**，门控的唯一风险 |
| 记忆假阳（不该读却读了） | 多一次检索，浪费一点延迟 | 低 |
| 工具假阳（不该调却调了） | 凭空调工具，可能改变外部状态 | **高** |
| 工具假阴（该调却没调） | 用户再问一遍 | 低 |

退出码 0 表示记忆假阴为 0（可以开门控），非 0 表示不可以。

## 排查

线上判断「为什么这次没调工具」只看 `stella_thought_logs.md` 的这两行：

```
- **🧭 路由判定**: `chat+memory` via `semantic`（能力: 无，最高分 0.31，42ms）—— 最高分 0.31 未达工具置信线 0.45
- **🔧 工具执行**: weather.query → `success`（1 次工具调用，直调，0.83s）
  > 东京明天 27℃，晴，降雨概率 10%。
```

| 现象 | 先查 |
|---|---|
| 插件装了但从不被调用 | 启动日志 `[capability][boot] 能力装配完成` 的 `derived` 数；再看工具是否 `active` |
| 声明写了但 examples 没生效 | `registry.claimed_by(工具名)` 是否指向你的能力（应指向声明的 id，不是 `tool.<名字>`） |
| 路由判定总是 `default` | embedding 服务是否可用（`MEMORY_EMBEDDING_BASE_URL`）；注册表是否为空 |
| 工具调了但 Stella 不提结果 | `Result.status` 是否 `failed`（失败不产出 summary）；或工具直接给用户发了图片（成功但无可转述内容） |
| 回复变慢 | 每个命中能力都是一次独立的受限 agent 调用，都走 chat 闸门串行；降 `ROUTER_MAX_CAPABILITIES` |

配置项清单见 [配置参考](configuration.md#能力路由与工具执行)。
