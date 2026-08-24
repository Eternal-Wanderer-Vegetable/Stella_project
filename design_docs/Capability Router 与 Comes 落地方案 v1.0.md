# Capability Router 与 Comes 落地方案 v1.0

上游设计见 `design_docs/Stella 智能机器人架构升级方案：基于 Capability Router 与 Comes 工具执行层的任务调度系统.md`。
本文只谈**怎么落到现在这份代码里**：模块放哪、接口长什么样、按什么顺序改、每步怎么验证。

---

## 0. 现状与切入点

读过代码后确认三件事，它们决定了整个落地方式：

**1）Stella 主链路目前完全看不到插件工具。**

`core/pipeline.py` 调的是 `LMStudioBackend.generate(prompt, system_prompt)`——两个字符串进、一段文本出，
表达不了 `tools` 数组。插件的 `llm_tools` 只在插件自己 `yield ProviderRequest`（`event.request_llm()`）时
才被用到，走的是 `astrbot_compat/pipeline.py::run_provider_request`。

> 这条结论很重要：**Comes 是纯增量**。它不是把已有行为搬个地方，而是接上一条从未存在的通路。
> 因此 Comes 上线不存在"回归"风险——之前 Stella 一次都没调过插件工具。

**2）工具执行的循环、Provider、预算裁剪已经写好了，可以直接复用。**

`astrbot_compat/llm/agent.py::run_tool_loop` + `astrbot_compat/llm/provider.py::StellaChatProvider`
已经实现了完整的 OpenAI function-calling 循环（含参数过滤、超时、异步生成器归一、钩子分发）。
Comes 不需要另写一套，只需要**换一个更小的 ToolSet 和一句自己的 system prompt** 去驱动它。

这正好实现方案第 3.1 节的"不共享上下文"：Comes 的请求里只有
`COMES_SYSTEM_PROMPT + objective + 本次命中能力的 1~3 个工具 schema`，
既没有 Stella 的人格，也没有聊天上下文；Stella 那边则只拿到 `Result.summary`，看不到任何工具 schema。

**3）Embedding 服务已经有了，Level 1 语义路由不用从零搭。**

`memory/embeddings.py::EmbeddingService` 已具备缓存（`model:dim:sha256`）、L2 归一化、余弦相似度、
经 `chat` 闸门串行、以及**任何一步失败都返回 None 让调用方降级**的契约。语义路由直接建在它上面。

**4）Comes 调 AstrBot 工具需要真实的 event/bot。**

`execute_tool` 里是 `tool.handler(event, **args)`，工具内部会用 `event.send()` / `event.bot.call_action()`。
所以 `ChatContext` 必须能把平台原始句柄带下来（见 §4.1）。

---

## 1. 模块划分

方案里的四个模块（Router / Stella / Memory / Comes）与现有目录的对应关系：

| 方案模块 | 落到哪里 | 说明 |
|-|-|-|
| Task / Result 协议 | `core/tasks.py`（新增） | 协议被四个模块共用，属于"与业务无关的编排骨架"，与 `core/context.py` 同级 |
| Capability Registry | `capability/registry.py`（新增） | 能力注册表 + 全局单例 |
| Router | `capability/router/`（新增） | 三级级联；原型向量取自 Registry 的 examples，故放在 capability 之下 |
| Comes | `capability/comes/`（新增） | 能力执行器 |
| AstrBot 适配 | `capability/adapters/astrbot.py`（新增） | `llm_tools` → Capability Provider |
| Stella | `core/pipeline.py`（改） | 只多认一个"工具结果"段落 |
| Memory | `memory/*`（不动核心逻辑） | 按方案第 14 节，不修改 |

新增一个顶层包 `capability/`，而不是三个（`router/` / `capability/` / `comes/`）：
Router 的原型向量来自 Capability 的 `examples`，Comes 的执行目标来自 Capability 的 `providers`，
三者围绕同一个注册表，拆成三个顶层包会让 import 方向变绕，且 `router` 这个名字太泛容易撞。

```text
core/
  tasks.py                       # Task / Result / TaskGraph 协议（新增）
  context.py                     # 加 route / task_results / tool_summaries / 平台句柄（改）
  pipeline.py                    # _compose_prompt 认"工具结果"段落（改）

capability/
  __init__.py                    # 包入口：re-export registry / route / execute
  registry.py                    # Capability / CapabilityProvider / CapabilityRegistry + 单例
  loader.py                      # 载入 config/capabilities/*.toml
  hooks.py                       # activate_capabilities 前置钩子（管线接入点）
  router/
    __init__.py                  # route() 三级级联入口
    types.py                     # Route / CapabilityHit
    rules.py                     # Level 0：规则快速判断
    semantic.py                  # Level 1：Embedding 原型匹配
    fallback.py                  # Level 2：SLM 兜底
    benchmark.py                 # Router benchmark 运行器（Phase 4）
    benchmark/                   # 用例集
  comes/
    __init__.py                  # execute() 入口
    executor.py                  # Task → Capability → Provider → Tool → Result
    summarizer.py                # Result.data → Result.summary
  adapters/
    __init__.py
    astrbot.py                   # llm_tools → Provider 自动注册

config/
  capabilities/*.toml            # 显式能力声明（照 config/spaces/*.toml 的惯例）
```

---

## 2. Task / Result 协议（`core/tasks.py`）

照方案第 4、5 节，字段一一对应，不多加：

```python
class TaskType(str, Enum):
    CHAT_RESPOND   = "chat.respond"
    MEMORY_RETRIEVE = "memory.retrieve"
    TOOL_EXECUTE   = "tool.execute"

@dataclass
class Task:
    task_id: str
    type: TaskType
    capability: str = ""          # 能力 id；chat/memory 类任务为空
    objective: str = ""           # 语义层目标，绝不是 "调用 weather_api()"
    input: dict = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    constraints: dict = field(default_factory=dict)

class ResultStatus(str, Enum):
    SUCCESS = "success"; FAILED = "failed"; PARTIAL = "partial"; CANCELLED = "cancelled"

@dataclass
class Result:
    task_id: str
    status: ResultStatus
    data: Any = None              # 完整结果（工具原始返回），不进 prompt
    summary: str = ""             # 压缩后的结果，只有这个进 Stella 的 prompt
    metadata: dict = field(default_factory=dict)   # provider / 耗时 / 调试信息
```

`TaskGraph` 提供 `add()` / `ready()` / `topological_order()`，并在成环时抛错——
方案第 4 节要 DAG，成环必须显式失败而不是死循环。

**`status` 的判定规则**（方案第 5 节强调"工具调用成功不代表任务成功"）：

| 情况 | status |
|-|-|
| 至少一个工具返回了非 error 的实质内容 | `success` |
| 部分工具成功、部分失败 | `partial` |
| 无工具被调用 / 全部报错 / 超时 | `failed` |
| 上游中止（`event.is_stopped()`、闸门取消） | `cancelled` |

---

## 3. Capability Registry（`capability/registry.py`）

```python
@dataclass
class CapabilityProvider:
    provider_id: str
    capability_id: str
    kind: str = "astrbot_tool"    # 预留 mcp / api / native
    tool_name: str = ""           # astrbot_tool：llm_tools 里的工具名
    priority: int = 0             # 越大越优先
    enabled: bool = True

@dataclass
class Capability:
    id: str                       # weather.query
    domain: str = ""              # information
    description: str = ""
    examples: list[str] = field(default_factory=list)   # Router 原型语料
    input_schema: dict = field(default_factory=dict)
    providers: list[CapabilityProvider] = field(default_factory=list)
```

`CapabilityRegistry` 提供 `register/get/all/find_providers/clear`，模块级单例 `registry`
（与 `star_handlers_registry` / `llm_tools` 同理：**必须模块级**，否则多 import 路径会让注册表分裂）。

### 3.1 两条注册通路（本次都做）

**A. 显式声明** `config/capabilities/*.toml`，文件名即 domain，照 `config/spaces/*.toml` 的读法
（`tomllib`，Py3.10 回退 `tomli`；单文件解析失败只跳过该文件）：

```toml
# config/capabilities/information.toml
[[capability]]
id = "weather.query"
description = "查询天气信息"
examples = ["明天天气怎么样", "会不会下雨", "东京温度多少"]
providers = ["get_weather", "weather_forecast"]   # llm_tools 里的工具名
```

**B. 自动派生**：`sync_astrbot_tools()` 扫描 `llm_tools`，把**没有被任何显式声明认领**的活跃工具
注册成 `tool.<name>`，`description` 取工具描述、`examples` 取描述本身。

两条通路的关系：显式声明优先且拥有工具的归属权；自动派生只兜没人管的工具。
这样既零配置可用（装上插件就能路由），又允许用中文 examples 把路由质量调上去——
工具描述大多是英文短句，只靠自动派生的 Level 1 中文语义匹配会明显偏低。

---

## 4. Router（`capability/router/`）

```python
@dataclass
class CapabilityHit:
    capability_id: str
    score: float

@dataclass
class Route:
    chat: bool = True             # Stella 永远要说话，默认 True
    memory: bool = True           # 保守默认见 §4.2
    tool: bool = False
    capabilities: list[CapabilityHit] = field(default_factory=list)
    level: str = ""               # rule / semantic / fallback / default
    reason: str = ""
    elapsed: float = 0.0
```

三级级联，任一级给出高置信结论即短路：

- **Level 0（`rules.py`）**：关键词规则。memory 侧「还记得 / 之前说过 / 我跟你说过」；
  tool 侧「搜索 / 查一下 / 帮我找」+ 各 Capability examples 里抽出的字面词。零延迟、不调模型。
- **Level 1（`semantic.py`）**：`EmbeddingService` 编码用户消息，与各 Capability 的原型向量
  （examples + description 编码后取均值）算余弦，超过 `ROUTER_SEMANTIC_THRESHOLD` 即命中。
  原型向量进程内缓存，注册表变更时失效。
- **Level 2（`fallback.py`）**：仅当 Level 1 最高分落在「不确定带」（`< ROUTER_TOOL_THRESHOLD`
  但 `> ROUTER_UNCERTAIN_FLOOR`）时才调 27B 做一次多标签判断。方案第 8 节明确要求
  "避免浪费 27B SLM 推理资源"，所以默认 `ROUTER_FALLBACK_ENABLED=false`，先靠 L0/L1 跑一段时间看数据。

**降级契约**：embedding 不可用 / 注册表为空 / 任何异常 → 返回 `Route(chat=True, memory=True, tool=False, level="default")`。
与 `memory/embeddings.py` 的既有约定一致：路由绝不能成为主链路的硬依赖。

### 4.1 ChatContext 新增字段

```python
# ---- Capability Router / Comes（任务调度层） ----
route: Any = None                  # Route 快照（诊断/日志用；core 不 import capability，故为 Any）
task_results: list = field(default_factory=list)      # Result 列表（完整 data，不进 prompt）
tool_summaries: list[str] = field(default_factory=list)  # 只有这些进 prompt
# 平台原始句柄（opaque）：Comes 调 AstrBot 工具时 handler 内部要用 event.send /
# event.bot.call_action，必须是真实对象。core 不解释它们的类型，只负责传递。
raw_event: Any = None
bot: Any = None
```

### 4.2 管线接入（`capability/hooks.py`）

管线钩子按 priority **降序**执行，现状是 `build_context(50)` → `build_user_context(40)`。
接入后：

```
50  build_context           # 不变，始终执行（这是对话上下文，不是"记忆检索"）
45  activate_capabilities   # 新增：Router 判定 → 并行 {Memory 检索, Comes 执行}
```

`activate_capabilities` 内部：

```python
route = await route_request(ctx)      # L0 → L1 → L2
ctx.route = route
jobs = []
if route.memory or not ROUTER_GATE_MEMORY:   # ← 默认不门控，见下
    jobs.append(build_user_context(ctx))
if route.tool and COMES_ENABLED:
    jobs.append(run_comes(ctx))
await asyncio.gather(*jobs, return_exceptions=True)   # 异常不击穿主链路
```

`build_user_context(40)` 的独立注册被这个钩子接管——方案第 17 节要求 Memory 与 Comes 并行，
而两个独立钩子只能串行，必须收进同一个 `gather`。

> **关于并行的诚实说明**：Comes 的 LLM 调用与 Memory 的 embedding 编码共用 `RESOURCE_CHAT`
> 闸门，两者的**模型调用**仍会 FIFO 串行。`gather` 拿到的是真实收益的那部分：
> Memory 的 SQL/FTS 查询与 Comes 的 HTTP 等待互相重叠。这不是"假并行"，但也不是两块 GPU。

**记忆门控默认关闭（`ROUTER_GATE_MEMORY=false`）。** Router 照常判定、照常写日志与 trace，
但 `build_user_context` 仍无条件执行。理由：Router 误判 memory=false 会让 Stella 当轮悄悄丢失长期记忆——
这种退化不抛异常、不影响回复、只是"它突然不记得你了"，与 2026-08-17 那次 `AT_MENTION` 全为 0 的
缺陷同一类型（静默、难察觉、后果严重）。先用 Phase 4 的 benchmark 量出准确率，再决定是否打开。

---

## 5. Comes（`capability/comes/`）

`execute(task, *, event, bot) -> Result`：

```
Task.capability
      ↓  registry.find_providers()（按 priority 降序，过滤 disabled）
Provider 列表
      ↓  取对应 llm_tools 里的 FunctionTool，组成一个只含它们的 ToolSet
ToolSet（1~3 个工具，不是 32 个）
      ↓  run_tool_loop(provider, req, event, max_steps=COMES_MAX_TOOL_STEPS)
LLMResponse + req.tool_calls_result
      ↓  summarizer
Result(status, data, summary, metadata)
```

其中 `req = ProviderRequest(prompt=task.objective, func_tool=scoped_tools,
system_prompt=COMES_SYSTEM_PROMPT, session_id=...)`。

**`data` 与 `summary` 的来源**（这一点很省事）：
- `data` = `req.tool_calls_result` 里各 `ToolCallMessageSegment` 的 `(name, content)`——工具原始返回；
- `summary` = 这个受限 agent 的 `resp.completion_text`——它读完工具输出后写的那句自然语言，
  天然就是方案第 5 节要的"压缩后的结果"。超过 `COMES_SUMMARY_MAX_CHARS` 时再由 `summarizer` 截断。

**无参直调优化**（`COMES_DIRECT_CALL_NO_ARGS=true`）：命中能力只有一个 Provider、
且其工具 schema 没有必填参数时，跳过 LLM 直接调工具。省掉一次 27B 往返，且不可能填错参数。

**Comes 的 system prompt 刻意不是 Stella 的人格**，与 `ASTRBOT_LLM_SYSTEM_PROMPT` 同一考量：
默认 `"你是一个工具执行器。根据给定的任务目标选择合适的工具并填好参数。只调用工具，不要闲聊，不要扮演角色。"`

---

## 6. 结果如何回到 Stella（`core/pipeline.py`）

`_compose_prompt` 多认一个段落。位置在上下文之后、当前输入标记之前——
工具结果是"回答当前这句话的证据"，必须离它近；而"请回应这句话"必须留在最后：

```
{context_text}

【刚刚查到的信息（真实数据，回答时以此为准）】
- 东京明天 27℃，晴，降雨概率 10%。

【现在 用户(123) 对你说】帮我查一下东京天气
请回应这句话。上面的对话记录只是背景，不要去回应其中的其他内容。
```

指令型 intent（`proactive_at`）下顺序为：指令 → 工具结果 → 上下文，与既有规则一致。

工具结果段落**只吃 `Result.summary`**，`Result.data` 全程不进 prompt——这是方案第 3.1 节
"工具描述会污染聊天上下文"的另一半：结果数据同样不该污染。

`log_thought` 增记路由判定与工具结果，`memory/trace.py` 的轨迹里加 route 快照，
否则线上排查"为什么这次没调工具"只能靠猜。

---

## 7. 执行顺序与验证

对齐方案第 19 节的四个 Phase，每阶段都跑全量回归（基线：**718 passed**）。

| Phase | 内容 | 验证 |
|-|-|-|
| 1 | `core/tasks.py`、`capability/registry.py`、`capability/loader.py` | 新增 `tests/capability/test_tasks.py` `test_registry.py` `test_loader.py`；协议与注册表纯逻辑，可完全离线单测 |
| 2 | `router/{types,rules,semantic,fallback}.py` + 配置项 | `test_router_rules.py`（规则表）、`test_router_semantic.py`（打桩 EmbeddingService）、`test_router_cascade.py`（级联与降级） |
| 3 | `comes/{executor,summarizer}.py`、`adapters/astrbot.py`、`hooks.py`、ChatContext / pipeline / ai_gateway 接入 | `test_comes_executor.py`（复用 `fake_llm` 夹具，不发真实请求）、`test_capability_hooks.py`（并行与异常不击穿）、扩充 `test_pipeline_compose.py` 钉死工具段落位置 |
| 4 | `router/benchmark.py` + 用例集、Provider 健康度选择、`docs/` 与 `.env.example` | `test_router_benchmark.py`；`docs/architecture.md` 增节 + 新增 `docs/capability-system.md`；配置项补进 `.env.example` 与 `docs/configuration.md` |

### 新增配置项一览

```
CAPABILITY_ROUTER_ENABLED=true      # 总开关
ROUTER_RULE_ENABLED=true            # Level 0
ROUTER_SEMANTIC_ENABLED=true        # Level 1
ROUTER_FALLBACK_ENABLED=false       # Level 2（默认关，省 27B）
ROUTER_SEMANTIC_THRESHOLD=0.35      # 语义命中阈值
ROUTER_TOOL_THRESHOLD=0.45          # 判定 tool=true 的置信线
ROUTER_UNCERTAIN_FLOOR=0.25         # 低于此值不进 Level 2（确定不需要工具）
ROUTER_MAX_CAPABILITIES=3           # 单次最多路由几个能力
ROUTER_GATE_MEMORY=false            # 是否真的按 route.memory 门控记忆检索
COMES_ENABLED=true
COMES_SYSTEM_PROMPT=...
COMES_MAX_TOOL_STEPS=5
COMES_TOOL_TIMEOUT=60
COMES_SUMMARY_MAX_CHARS=300
COMES_DIRECT_CALL_NO_ARGS=true
```

---

## 8. 刻意不做的事

- **不改 Memory 核心逻辑**（方案第 14 节）：classification / filtering / promotion / forgetting 一行不动。
- **不让 Router 决定记忆写入**（方案第 15 节）：写入链路 `maybe_consolidate` 完全不经 Router。
- **不动 `plugin_handler(priority=2)` 的显式指令分发**：`/help` 这类是确定性分发，不是能力路由。
  Router 只治理 chat 路径（`chat_handler`），两者互不干扰。
- **不动 `LMStudioBackend.generate()`**：它的行为是主链路多轮实测调出来的。工具能力经 Comes 旁路接入，
  不给主后端加 tools 参数。
- **不做 MCP / API / Native Tool 适配**：`CapabilityProvider.kind` 留好了口子，本轮只实现 `astrbot_tool`。
