# GitNexus Engineering Plan

> Task: 将 Stella 的 AI 能力与普通插件/确定性能力运行时分离，使聊天模型缺席时仍能自动识别、执行并回复不需要聊天模型的插件功能；embedding 模型不属于本次“无模型”范围。
> Evidence verified at commit `d00d7309b072951aa9d8d8628a2e1795d1de327a`; GitNexus index refreshed this session with `--index-only --pdg`, runner `npx gitnexus` / CLI `1.6.11`, provenance current.
> Evidence provenance schema 2; the generated plan path is excluded from the global dirty digest.

## 1. Objective

[verified] 在聊天生成模型、Agent 模型和 Level 2 router fallback 均不可用时，普通 AstrBot 插件仍可加载、初始化、处理 command/regex/event-message，并发送结果；这类“无模型”定义**不排除 embedding**。

[inferred] 对自然语言能力请求，允许 Level 0 规则和 Level 1 embedding 识别能力；命中后必须沿模型无关的确定性执行路径完成参数提取、工具调用和用户回复。示例验收：用户询问东京天气，embedding 识别 `weather.query`，确定性提取 `city=东京`，调用天气工具，直接发送工具摘要，不经过聊天 Pipeline 的生成模型。

[verified] 需要自然语言生成、Agent 选工具、复杂多步规划或无法可靠填参的能力仍进入可选 LLM runtime；无法进入时返回明确的缺失参数/模型不可用状态，不凭空执行。

## 2. Current Behaviour

[verified] `capability/router/__init__.py:66-123` 的级联是 Level 0 规则、Level 1 embedding、Level 2 生成模型；Level 0 命中显式 `keywords` 可直接确定能力，Level 1 复用 embedding，Level 2 默认关闭；embedding 失败统一返回 `default_route()`，当前默认 `chat=True, tool=False`（`router/types.py:42-108`）。

[verified] `Capability.input_schema` 已存在（`capability/registry.py:125-174`），`Task.input` 明确用于已知槽位（`core/tasks.py:74-96`），但 `build_tool_tasks()` 只填 `objective` 和 router 分数（`capability/hooks.py:67-86`），没有从原话提取参数。

[verified] Comes 能在单工具无必填参数时绕过模型（`capability/comes/executor.py:121-129,263-318`）；有必填参数或多个工具时调用 `_agent_call()`，provider 缺失即失败。`Result.summary` 的现有生成优先使用 Agent 文本，才退回工具输出（`capability/comes/summarizer.py:53-97`）。

[verified] `_run_comes()` 只把结果写入 `ctx.task_results`/`ctx.tool_summaries`（`capability/hooks.py:101-118`）；`core/pipeline.Pipeline.run()` 若前置钩子设置 `ctx.reply` 会跳过 LLM，但 `ai_gateway.handle_chat()` 最终发送 `ctx.lines`，当前没有把工具摘要转成 `reply/lines`（`core/pipeline.py:155-175`; `ai_gateway.py:522-542`）。无模型时因此可能发送 `......？`。

[verified] `capability/router/fallback.py:106-171` 的 Level 2 明确依赖生成 backend；它不能被视为 embedding 的一部分。`config/settings.py:1025-1029,1062,1233-1258` 已将 AstrBot LLM、角色端点和 embedding 配置分开，但 router/Comes 的代码仍需按角色独立判定。

## 3. Relevant Architecture

[verified] 普通插件入口当前由 `bot_main.ai_gateway:plugin_handler/handle_plugin`（`ai_gateway.py:438-457`）桥接到 `astrbot_compat.pipeline.dispatch`；同模块还装配主聊天 Pipeline，因此普通插件与 AI runtime 在 import/注册层面耦合。

[verified] `astrbot_compat.pipeline.dispatch` 普通返回值直接 `event.send`，只有 `ProviderRequest` 才进入 provider；`Context.llm_generate/tool_loop_agent` 是显式模型 API。普通插件兼容层本身不应等待聊天模型。

[verified] `CapabilityRegistry.routable()` 只返回 route-enabled、有 live provider 和 prototype 文本的能力（`capability/registry.py:351-392`）；`FunctionTool.parameters` 提供 JSON schema 与 required 字段（`astrbot_compat/llm/tool.py:16-52`），可与能力级 `input_schema` 合并作为确定性解析约束。

[verified] `capability.comes.summarizer` 已有无模型可复用的原始工具输出压缩逻辑；工具结果直接回复应复用其过滤 error/no-return、截断和多工具拼接规则，不应把原始 JSON 或内部错误发给用户。

## 4. GitNexus Findings

[graph] `query("plugin bootstrap dispatch command event handler without LLM")` 找到 `handle_plugin → dispatch → get_handlers_by_event_type`，并关联普通命令、多插件独立加载和 dispatch 测试。

[graph] `impact(get_provider_manager, upstream, depth=3)`: `risk=HIGH`，45 个受影响符号，d=1 包括 `run_provider_request`、Comes `_agent_call`、`Context.provider_manager` 与 5 个 provider probe；保持 provider 语义不变。

[graph] `impact(call_event_hook, upstream, depth=3)`: `risk=HIGH`，59 个受影响符号，d=1 为 `run_tool_loop`、`dispatch`、`run_provider_request`；普通 dispatch 的 `OnAfterMessageSentEvent` 与 agent hook 顺序必须回归。

[graph] `impact(dispatch, upstream, depth=3)`: `risk=MEDIUM`，33 个受影响符号，主入口为 `handle_plugin`；拆分入口时要保留 `_plugin_handled_msgs`、优先级和群锁协作。

[graph] `impact(route, upstream, depth=3)`: `risk=LOW`，4 个受影响符号，d=1 为 capability hook 与 benchmark；修改 Route 需同步 `activate_capabilities` 和 router tests。

[graph] `impact(_run_comes, upstream, depth=3)`: `risk=LOW`，1 个直接上游为 `activate_capabilities`；它是新增“自动执行并直接回复”状态的最小落点，但行为仍受主 Pipeline/网关消费方式约束。

[graph] `pdg_query(controls, _run_comes)`: 6 条控制边，关键守卫是无任务直接返回、事件构造失败直接返回，否则调用 `execute_all` 并写回两个 context 字段。`pdg_query(controls, route)` 在函数锚定下无边；该空结果不证明没有分支约束。

## 5. Statement-Level PDG Findings

[graph] 已有 `--pdg` 索引；`_run_comes` 的控制依赖确认：`tasks` 为空时 return；`event is None` 时记录并 return；否则执行 `execute_all`，然后写入 `ctx.task_results` 与 `ctx.tool_summaries`（`capability/hooks.py:101-118`）。

[graph] `route` 的 PDG 查询未产生可用 statement 结果，且其函数锚定存在解析歧义；以当前源码和测试作为路由分支的权威证据。

[inferred] 直接回复必须发生在 `execute_all` 成功结果已过滤之后，并与 `Pipeline.run` 的“预置 reply 可短路”机制及网关的 `ctx.lines` 发送机制绑定；失败结果不能被当成事实或内部诊断发送。

## 6. Proposed Changes

1. **拆分模型角色状态。**
   - Files: `astrbot_compat/llm/manager.py`, `config/settings.py`，必要时 `core/llm` 的角色状态接口。
   - Responsibility: 区分 CHAT/PLUGIN/ROUTER/AGENT 生成模型是否可用与 embedding 是否可用；保留 `get_provider_manager().provider`、`provider_insts`、`ProviderRequest` 和旧异常导出。
   - Behaviour: 只读状态应能表达 disabled、endpoint missing、provider init failure、available；“聊天模型不可用”不能推出 embedding 不可用。
   - Constraint: 不直接改变 provider 属性语义；不得把所有 `StellaCompatNotSupported` 视作模型缺失。

2. **建立无模型能力路由契约。**
   - Files: `capability/router/types.py`, `capability/router/__init__.py`, `capability/router/rules.py`, `capability/router/semantic.py`, `capability/router/fallback.py`。
   - Responsibility: 保留规则与 embedding 为模型无关识别层，显式标记 `route` 是否需要生成模型/是否允许确定性执行；Level 2 只在对应生成 backend 可用时尝试。
   - Behaviour: `ASTRBOT_LLM_ENABLED=false` 不会关闭 Level 0/Level 1；embedding 不可用仍保守降级，不凭空执行；`Route` 必须能表达“tool=true 且 chat generation=false”。
   - Constraint: 不把工具选择、工具执行或人格回复塞回 Router；保持现有 `to_dict()`/日志兼容。

3. **增加确定性输入提取协议。**
   - Files: `capability/registry.py`, `core/tasks.py`, `capability/hooks.py`, possibly a new small parser module under `capability/`.
   - Responsibility: 以 `Capability.input_schema` 为能力级声明，允许 provider/capability 声明 regex、枚举、默认值、上下文提取器等确定性规则；将可靠提取结果填入 `Task.input`。
   - Behaviour: `build_tool_tasks()` 保留用户原话为 `objective`，同时生成结构化 `input`；合并工具 schema 的 required 字段，校验类型/枚举/缺失项。天气示例应从“查东京明天天气”提取 `city=东京`（日期若为工具必填也必须显式提取或使用声明默认值）。
   - Constraint: 只能执行“能力确定 + provider 唯一/选择确定 + 必填参数完整且校验通过”的任务；提取失败返回结构化 `missing_input`/`needs_clarification`，不得调用 agent 猜参数；禁止用脆弱的通用 NLP 猜槽位。

4. **扩展 Comes 的模型无关执行模式。**
   - Files: `capability/comes/executor.py`, `capability/comes/__init__.py`, `capability/comes/summarizer.py`。
   - Responsibility: 在 `Task.input` 完整且工具选择无歧义时，直接调用工具；多工具仅在确定性 provider 选择协议能唯一确定时执行，否则保持模型路径或结构化失败。
   - Behaviour: 单工具无参和单工具有参均可无模型执行；成功结果生成不依赖模型的 `Result.summary`；部分成功保留可回复摘要；失败保留内部 metadata，不将内部异常直接回传。
   - Constraint: `_agent_call()`、tool loop 和 scheduler 在有模型时行为不变；直接调用必须复用现有超时、provider 健康度和 `ResultStatus` 语义。

5. **建立工具结果直接回复路径。**
   - Files: `capability/hooks.py`, `core/context.py`, `core/pipeline.py`, `stella_project/plugins/bot_main/ai_gateway.py` 或新 ordinary plugin/capability runtime module。
   - Responsibility: 将成功/部分成功的确定性 `Result.summary` 转为 `ctx.reply` 与 `ctx.lines`，设置“已处理/不再生成”的状态；由现有网关继续完成引用回复、发送、post-send hook、记录和群锁收尾。
   - Behaviour: 没有聊天模型时，天气请求自动执行后直接回复摘要；不进入 `Pipeline` 的 CHAT 生成段，不生成 `......？`；若结果为空、缺参、失败或存在歧义，则返回清晰的缺失信息/暂不可用提示，且不泄漏内部 JSON、异常栈或 Agent 文本。
   - Constraint: 不能让 `ctx.reply` 短路后 `ctx.lines` 为空；不能重复发送；继续触发必要的 `OnAfterMessageSentEvent`、消息记账和 post-send 逻辑。

6. **隔离普通插件 runtime 与 AI gateway。**
   - Files: `stella_project/plugins/bot_main/__init__.py`, `stella_project/plugins/bot_main/ai_gateway.py`, new ordinary plugin runtime module, `astrbot_compat/loader.py`, `astrbot_compat/pipeline.py`, `astrbot_compat/llm/agent.py`。
   - Responsibility: 普通插件加载、生命周期、command/regex/event dispatch 常驻；主聊天、主动生成、Agent/ProviderRequest hook 按角色可用性装配。
   - Behaviour: 普通插件 import/initialize/dispatch 不依赖 CHAT/PLUGIN 生成模型；模型 API 只在调用时报告 unavailable；模型插件故障不停用不相关普通插件。
   - Constraint: 保持 `plugin_handler` 优先级、`_plugin_handled_msgs`、热重载、群锁、生命周期和异常隔离；保留旧导入路径与兼容层 API。

7. **文档与诊断。**
   - Files: `docs/plugin-spec.md`, `docs/configuration.md`，必要时 `.env.example`。
   - Responsibility: 说明 ordinary runtime、embedding capability routing、deterministic input schema、direct tool reply、optional LLM runtime 的兼容矩阵和错误语义；明确“无模型”不包含 embedding。
   - Behaviour: 插件作者能知道何时写 `input_schema`/parser、何时只能依赖模型；启动日志分别展示 chat/agent/router/embedding 状态。

## 7. Implementation Sequence

1. 先固定角色状态与异常分类契约，补充 CHAT/PLUGIN/ROUTER/embedding 的状态矩阵；用 `get_provider_manager` 的 8 个直接调用者做兼容基线。高风险：不可改变 provider 懒创建与旧调用者观察到的 `None`/实例语义。
2. 在不接入发送链路前，实现 `Route` 的“确定性执行 vs 需生成模型”标记，并让 Level 2 在生成 backend 不可用时跳过；保留 Level 0 规则、Level 1 embedding 和现有保守 default。
3. 定义并实现 schema/parser 解析器：能力级优先，工具 schema 必填字段作为校验边界；为城市、日期、枚举、默认值、类型转换、缺失字段编写纯函数测试。禁止以“把原话交给 agent”作为无模型成功标准。
4. 改造 `build_tool_tasks` 填充 `Task.input` 和输入状态；改造 Comes，使单工具有参任务在输入完整时 direct call，输入不完整时返回结构化失败/需要澄清；多工具只有唯一确定 provider 时才可 direct call。
5. 增加确定性摘要与直接回复：成功/部分成功只使用 `Result.summary` 或工具输出纯函数压缩；把 `ctx.reply` 与 `ctx.lines` 一致设置，调用 `Pipeline.run` 的 pre-hook short-circuit 或专用 ordinary capability runtime，并确认网关不会补发占位符。
6. 将普通插件 dispatch 从 `ai_gateway` 的 AI 装配中抽出；保留兼容导出、优先级、事件 hook 和 `_plugin_handled_msgs`，让无模型启动不触发主聊天 Pipeline 生成。
7. 最后更新 loader 异常分类、文档、日志诊断，再做端到端和兼容回归；执行 `detect_changes({scope:"all"})`，若 `partial`/`truncated` 为 true 必须重跑并复核。

## 8. Test Strategy

[verified] 已有 router 级联测试覆盖 Level 0 不调用 embedding、Level 1 embedding 命中、Level 2 fallback、embedding 失败保守降级（`tests/capability/test_router_cascade.py:231-379`）；Comes 测试覆盖无参直调及有参任务当前依赖 fake LLM（`tests/capability/test_comes_executor.py:125-210,242-305`）；hook 测试覆盖任务 objective、结果摘要和并行异常隔离（`tests/capability/test_capability_hooks.py:107-244`）。

[inferred] 应新增/更新以下场景：
- `ASTRBOT_LLM_ENABLED=false` + embedding 可用 + 显式能力关键词 + 有参天气工具 → 提取城市/日期，工具被调用一次，用户收到摘要，聊天生成调用次数为 0。
- `ASTRBOT_LLM_ENABLED=false` + embedding 可用 + 语义命中天气 → 同上，验证 Level 1 仍能路由。
- embedding 不可用 → 不调用工具，返回保守结果；不能因为聊天模型缺席而混淆两种状态。
- 工具必填参数缺失/解析不确定 → 不执行工具，返回缺失槽位或澄清结果；不进入 `_agent_call`。
- 无参工具 → 继续 direct call；有参但 `Task.input` 完整 → direct call；多工具不唯一 → 结构化失败或明确要求模型。
- 成功/partial 工具结果 → `ctx.reply` 与 `ctx.lines` 均非空，网关只发送一次并完成 post-send/after-send；失败/内部异常 → 不发送原始错误或 JSON。
- 普通 command/regex/event 插件与模型依赖插件同进程 → 前者仍初始化、activated、dispatch，后者只在调用模型 API 时降级。
- CHAT 端点缺失或主聊天模型失败 → 普通插件/确定性能力仍运行，不发送 `......？` 作为工具成功结果。
- 热重载/卸载 → 普通 handler、能力 registry、embedding prototype cache 和 hooks 不重复注册或泄漏。

[verified] 现有验证命令存在：`python -m pytest tests -q`、CI 等价 pytest 命令（`pyproject.toml:102-110`; `.github/workflows/ci.yml:93-103`）和 `ruff check .`（`.github/CONTRIBUTING.md:49-50`）。

## 9. Risk and Impact Analysis

[graph] `get_provider_manager` 与 `call_event_hook` 均为 HIGH；必须逐一回归其直接依赖。`dispatch` 为 MEDIUM；入口拆分需覆盖普通返回值、ProviderRequest 分流、异常通知与 after-send hook。

[verified] `StellaCompatNotSupported` 同时覆盖数据库、事件队列、Web API 等非模型不支持 API（`docs/plugin-spec.md:409-425`）；异常分类必须窄化到模型角色，不能把插件初始化中的任何兼容异常都标成模型缺失。

[inferred] 最大行为风险是错误地把 embedding/规则路由关闭、让确定性工具仍进入 `_agent_call`、或将摘要写进 context 却未填 `ctx.lines`，导致重复执行、无回复或 `......？`。

[inferred] 能力声明与工具 schema 可能冲突；优先级、默认值、类型转换和 parser 失败必须可观测。外部天气 API 的延迟、失败退避、event 句柄和工具副作用仍需沿用现有 Comes 约束。

[assumed] 若用户消息同时命中多个能力，只有全部 provider/参数均能确定性执行时才走纯无模型直发；否则保留模型路径或结构化澄清，不得部分执行后伪装成完整回答。该产品策略需实现前确认。

## 10. Files Expected to Change

| File | Symbols / area | Reason |
| ---- | ---- | ---- |
| `config/settings.py` | role/model/embedding flags | 明确独立状态与配置语义。 |
| `astrbot_compat/llm/manager.py` | `ProviderManager`, `get_provider_manager` | 暴露可用性原因，保持旧 provider 形状。 |
| `astrbot_compat/llm/context.py` or `astrbot_compat/context.py` | explicit LLM APIs | 统一模型不可用契约。 |
| `astrbot_compat/loader.py` | `initialize_plugins` | 模型缺失与真实初始化失败分类。 |
| `astrbot_compat/pipeline.py` | `dispatch`, `_emit`, `run_provider_request` | 普通分发与模型请求边界。 |
| `astrbot_compat/llm/agent.py` | `call_event_hook`, `run_tool_loop` | 可选 Agent runtime 与 hook 兼容。 |
| `capability/router/types.py` | `Route` | 表达确定性 tool execution / chat generation 分离。 |
| `capability/router/__init__.py`, `rules.py`, `semantic.py`, `fallback.py` | cascade | 保留规则/embedding，跳过不可用 LLM fallback。 |
| `capability/registry.py` | `Capability`, `CapabilityProvider` | input schema/parser/确定性 provider 元数据。 |
| `core/tasks.py` | `Task`, `Result` | input、missing/clarification、direct result 状态协议。 |
| `capability/hooks.py` | `build_tool_tasks`, `_run_comes`, `activate_capabilities` | 填槽、执行和直接回复状态。 |
| `capability/comes/__init__.py`, `executor.py`, `summarizer.py` | direct execution | 有参无模型调用、纯函数摘要、失败契约。 |
| `core/context.py`, `core/pipeline.py` | short-circuit fields | 支持无需生成模型的回复并避免占位符。 |
| `stella_project/plugins/bot_main/__init__.py`, `ai_gateway.py`, new ordinary runtime | entry points | 普通插件常驻，AI gateway 可选。 |
| `tests/capability/test_router_cascade.py` | routing no-chat-model cases | embedding/LLM 状态隔离。 |
| `tests/capability/test_capability_hooks.py` | task input/direct reply | 结果消费闭环。 |
| `tests/capability/test_comes_executor.py` | direct parameterized calls | 无模型有参、缺参、多工具边界。 |
| `tests/astrbot_compat/test_dispatch.py`, `test_loader.py`, `test_request_llm.py`, `test_llm_hooks.py` | compatibility | 普通插件与 LLM API 回归。 |
| `docs/plugin-spec.md`, `docs/configuration.md` | contracts | 插件作者/部署者可执行说明。 |

## 11. Reusable Implementation Context

```json
{
  "implementation_context": {
    "task_summary": "Separate model-independent plugin and deterministic capability execution from optional chat/agent LLM runtime; embedding remains allowed and is not included in no-model.",
    "acceptance_criteria": [
      "With chat/agent generation models unavailable but embedding available, rules or embedding can identify a capability.",
      "A deterministically parseable parameterized tool such as weather.query executes without _agent_call and directly replies with its result.",
      "Direct replies populate both ctx.reply and ctx.lines, bypass chat generation, send exactly once, and preserve post-send/after-send bookkeeping.",
      "Missing or ambiguous required inputs never cause guessed tool calls; they yield a structured clarification/unavailable result.",
      "Ordinary command/regex/event plugins load and dispatch without any chat or agent model.",
      "Existing ProviderRequest, Context LLM APIs, agent hooks, scheduler gates, and provider compatibility remain stable when models exist.",
      "Embedding availability is tracked independently from chat/agent model availability."
    ],
    "evidence_provenance": {
      "schema_version": 2,
      "head_commit": "d00d7309b072951aa9d8d8628a2e1795d1de327a",
      "generated_plan_path": "docs/plans/2026-09-10-gitnexus-plan-optional-model-plugin-runtime.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "62e6e949661ae204cb53f844a9362f781c1c699d03bdc28b265f01213d7866c3"
      },
      "cited_path_manifest": {
  "schema_version": 2,
  "head_commit": "d00d7309b072951aa9d8d8628a2e1795d1de327a",
  "generated_plan_path": "docs/plans/2026-09-10-gitnexus-plan-optional-model-plugin-runtime.md",
  "global_dirty_digest": {
    "algorithm": "sha256",
    "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
    "value": "62e6e949661ae204cb53f844a9362f781c1c699d03bdc28b265f01213d7866c3"
  },
  "cited_path_manifest": [
    {
      "path": ".github/CONTRIBUTING.md",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",
      "index_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",
      "worktree_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",
      "untracked_digest": "absent"
    },
    {
      "path": ".github/workflows/ci.yml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:72ffa0a55d11fd17d17ca884615f5ae7976f2f0487d793f90720e61f5296fa5f",
      "index_digest": "sha256:72ffa0a55d11fd17d17ca884615f5ae7976f2f0487d793f90720e61f5296fa5f",
      "worktree_digest": "sha256:23cf14adfcf4c2ae1baeb9d4cb7ed173ac12c985f0bf5ddb217a02576039fb0f",
      "untracked_digest": "absent"
    },
    {
      "path": "AGENTS.md",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
      "index_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
      "worktree_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
      "untracked_digest": "absent"
    },
    {
      "path": "astrbot_compat/context.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:2b54c2e4908b0c983044836dc1979493fb554c8a69faf2128f9cdb67070d3215",
      "index_digest": "sha256:2b54c2e4908b0c983044836dc1979493fb554c8a69faf2128f9cdb67070d3215",
      "worktree_digest": "sha256:2b54c2e4908b0c983044836dc1979493fb554c8a69faf2128f9cdb67070d3215",
      "untracked_digest": "absent"
    },
    {
      "path": "astrbot_compat/llm/agent.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:2de7b63a50a516dc5a0d2dcb360b62e2f1f69f7a8e546afbcb442bffa4f40852",
      "index_digest": "sha256:2de7b63a50a516dc5a0d2dcb360b62e2f1f69f7a8e546afbcb442bffa4f40852",
      "worktree_digest": "sha256:2de7b63a50a516dc5a0d2dcb360b62e2f1f69f7a8e546afbcb442bffa4f40852",
      "untracked_digest": "absent"
    },
    {
      "path": "astrbot_compat/llm/manager.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:260fb07e90a3081f2bd3064a34ad5f427285bd1ab9eb07608ab7edab9d83af03",
      "index_digest": "sha256:260fb07e90a3081f2bd3064a34ad5f427285bd1ab9eb07608ab7edab9d83af03",
      "worktree_digest": "sha256:260fb07e90a3081f2bd3064a34ad5f427285bd1ab9eb07608ab7edab9d83af03",
      "untracked_digest": "absent"
    },
    {
      "path": "astrbot_compat/llm/tool.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:98189386e6ef4a14dc90eef7d4f085537e674723ff5652c9267d4901bd6485da",
      "index_digest": "sha256:98189386e6ef4a14dc90eef7d4f085537e674723ff5652c9267d4901bd6485da",
      "worktree_digest": "sha256:98189386e6ef4a14dc90eef7d4f085537e674723ff5652c9267d4901bd6485da",
      "untracked_digest": "absent"
    },
    {
      "path": "astrbot_compat/loader.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:558c6c103802e99fc1746c211f8737e2426f5b1c8984a457ca8a98edc9dcf7c2",
      "index_digest": "sha256:558c6c103802e99fc1746c211f8737e2426f5b1c8984a457ca8a98edc9dcf7c2",
      "worktree_digest": "sha256:558c6c103802e99fc1746c211f8737e2426f5b1c8984a457ca8a98edc9dcf7c2",
      "untracked_digest": "absent"
    },
    {
      "path": "astrbot_compat/pipeline.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:14c93669d156da03d38e0f2caa2555e9f0cc08ebe0700996bc5784572ec81deb",
      "index_digest": "sha256:14c93669d156da03d38e0f2caa2555e9f0cc08ebe0700996bc5784572ec81deb",
      "worktree_digest": "sha256:14c93669d156da03d38e0f2caa2555e9f0cc08ebe0700996bc5784572ec81deb",
      "untracked_digest": "absent"
    },
    {
      "path": "bot.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:fc7c0cf82b79f764e82f712bcc8c6efa631c393920d63fc4bc340fd0fcd92cb4",
      "index_digest": "sha256:fc7c0cf82b79f764e82f712bcc8c6efa631c393920d63fc4bc340fd0fcd92cb4",
      "worktree_digest": "sha256:dd5966be29de7535bf80e62b33235583b75a2de5c86fe07b3819324c522556f7",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/comes/__init__.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:093e161a3ea22b6e05ddd7024fdd5b667103171729b313e3fc976d7f00b11f3c",
      "index_digest": "sha256:093e161a3ea22b6e05ddd7024fdd5b667103171729b313e3fc976d7f00b11f3c",
      "worktree_digest": "sha256:093e161a3ea22b6e05ddd7024fdd5b667103171729b313e3fc976d7f00b11f3c",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/comes/executor.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:6afff69379940b657388bcc87d0e256661aa8a4a61e634fc638b86e4d65160a4",
      "index_digest": "sha256:6afff69379940b657388bcc87d0e256661aa8a4a61e634fc638b86e4d65160a4",
      "worktree_digest": "sha256:6afff69379940b657388bcc87d0e256661aa8a4a61e634fc638b86e4d65160a4",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/comes/summarizer.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:d1dda057d2a1f81e990c2034f93a14a0140fdda055b2d2c08280f62025557c5f",
      "index_digest": "sha256:d1dda057d2a1f81e990c2034f93a14a0140fdda055b2d2c08280f62025557c5f",
      "worktree_digest": "sha256:d1dda057d2a1f81e990c2034f93a14a0140fdda055b2d2c08280f62025557c5f",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/hooks.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:3191c5a4d065b4af5b65d58b0087cfa116cd943376407b6eb81e1463a8e836f2",
      "index_digest": "sha256:3191c5a4d065b4af5b65d58b0087cfa116cd943376407b6eb81e1463a8e836f2",
      "worktree_digest": "sha256:2ef9b3ce5730920cf0243c0a792c108e9aba5cc4919e8b5a7b169bb26e8a1a22",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/registry.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:3005b1ec83db2f36ec67ef68d8c26d01344bc66a82c5a14cbdef6171304b4db5",
      "index_digest": "sha256:3005b1ec83db2f36ec67ef68d8c26d01344bc66a82c5a14cbdef6171304b4db5",
      "worktree_digest": "sha256:326d9210fbce8a14d1579ad62029d077bb7dcee80822b813ff4438523174306a",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/router/__init__.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:78e640acb52d2a8d1a92bf3eaffba126cb4d2a2cb02791895c9c06ae83041da4",
      "index_digest": "sha256:78e640acb52d2a8d1a92bf3eaffba126cb4d2a2cb02791895c9c06ae83041da4",
      "worktree_digest": "sha256:78e640acb52d2a8d1a92bf3eaffba126cb4d2a2cb02791895c9c06ae83041da4",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/router/fallback.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:d94c2d3638ce5f5cb1961d0ddf8236510e9c18f3282a803e89448757be1a3b2d",
      "index_digest": "sha256:d94c2d3638ce5f5cb1961d0ddf8236510e9c18f3282a803e89448757be1a3b2d",
      "worktree_digest": "sha256:d94c2d3638ce5f5cb1961d0ddf8236510e9c18f3282a803e89448757be1a3b2d",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/router/rules.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:7ff516ef0e353a0cc1c2c94ee20572390b1b0c3a5cf3d37be83a63e9d4e6306f",
      "index_digest": "sha256:7ff516ef0e353a0cc1c2c94ee20572390b1b0c3a5cf3d37be83a63e9d4e6306f",
      "worktree_digest": "sha256:7ff516ef0e353a0cc1c2c94ee20572390b1b0c3a5cf3d37be83a63e9d4e6306f",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/router/semantic.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a71b598e84081656697f0d58b669456763dba698b62b6ea76c4e9513268d09b2",
      "index_digest": "sha256:a71b598e84081656697f0d58b669456763dba698b62b6ea76c4e9513268d09b2",
      "worktree_digest": "sha256:6691236abd25f1d701232fe100a090f26ac679349e342bea0d34c7d51bb06afe",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/router/types.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:43d7b6b7235dbc1052aa4d85296596a6f9610a613b59498333f4550bfa1b27f2",
      "index_digest": "sha256:43d7b6b7235dbc1052aa4d85296596a6f9610a613b59498333f4550bfa1b27f2",
      "worktree_digest": "sha256:43d7b6b7235dbc1052aa4d85296596a6f9610a613b59498333f4550bfa1b27f2",
      "untracked_digest": "absent"
    },
    {
      "path": "config/settings.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:3ac5090048e85ee44fb6916b19b76e4f6f9ce2c2b8674fb8bdb8734e8debe39b",
      "index_digest": "sha256:3ac5090048e85ee44fb6916b19b76e4f6f9ce2c2b8674fb8bdb8734e8debe39b",
      "worktree_digest": "sha256:43a35f1cc6c502d81af15511970f9f1b84cb101464d91cfa4a98e6c0b957e992",
      "untracked_digest": "absent"
    },
    {
      "path": "core/context.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:f803801779fb3d3784a53ee65389b786932c2dc96694e801b48e31f3ba74de01",
      "index_digest": "sha256:f803801779fb3d3784a53ee65389b786932c2dc96694e801b48e31f3ba74de01",
      "worktree_digest": "sha256:a74ad5c89025fd4707433e67302ce1bd0af0dd41cafece0455545af9e3e9684d",
      "untracked_digest": "absent"
    },
    {
      "path": "core/pipeline.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:107b07fd66405dd20fc648706175375e26560b438164b451d9e73df404ca8a4e",
      "index_digest": "sha256:107b07fd66405dd20fc648706175375e26560b438164b451d9e73df404ca8a4e",
      "worktree_digest": "sha256:2168ad8cdb2557768980cc1c3cb8932f081102e3f4eda39b0c857909b0fd0944",
      "untracked_digest": "absent"
    },
    {
      "path": "core/tasks.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:966c957758bd6a2ca4218f2afb0a4f23f0971abed734e6024bb4dab1c4bde791",
      "index_digest": "sha256:966c957758bd6a2ca4218f2afb0a4f23f0971abed734e6024bb4dab1c4bde791",
      "worktree_digest": "sha256:966c957758bd6a2ca4218f2afb0a4f23f0971abed734e6024bb4dab1c4bde791",
      "untracked_digest": "absent"
    },
    {
      "path": "docs/configuration.md",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:2e9a4995d0fa35f9cf534d3b4b2494eb8e2ae52ad2fc4536161aa8adb5cb2dcd",
      "index_digest": "sha256:2e9a4995d0fa35f9cf534d3b4b2494eb8e2ae52ad2fc4536161aa8adb5cb2dcd",
      "worktree_digest": "sha256:0b19c3e129a14af77a561178145ab4a4dc95136be6a431a3e5a66e798373081e",
      "untracked_digest": "absent"
    },
    {
      "path": "docs/plugin-spec.md",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:41adbdd0661ea47a1ed9472242541c62d3793c6156f86ac5e08d81a0caa9d315",
      "index_digest": "sha256:41adbdd0661ea47a1ed9472242541c62d3793c6156f86ac5e08d81a0caa9d315",
      "worktree_digest": "sha256:732d24916680c1234c1a69ef9b5c34aef780572ea5e69dbed33e9bd6d70e036a",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/post_processors.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:c725f8e42911a8bfcf4a951d4e29dd7f283c0644e6511f57e65b26d87d560d33",
      "index_digest": "sha256:c725f8e42911a8bfcf4a951d4e29dd7f283c0644e6511f57e65b26d87d560d33",
      "worktree_digest": "sha256:47f77377864959e6e1d4dc75ee8d50f1f96e3c3927f4ec0ff9d6381610a5650d",
      "untracked_digest": "absent"
    },
    {
      "path": "pyproject.toml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:fcba17a80adf3fe48c2a4076a19ee6cdab093efa325bc91a0466cf299105dd16",
      "index_digest": "sha256:fcba17a80adf3fe48c2a4076a19ee6cdab093efa325bc91a0466cf299105dd16",
      "worktree_digest": "sha256:7a6d5b0d3a4d9d29b63c19afa3a2a3759fa00295173dbb0209b04aa2455c09ec",
      "untracked_digest": "absent"
    },
    {
      "path": "stella_project/plugins/bot_main/__init__.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:ce2eac6e2bea8659161ba5957589655f7dede40a6d85b5819627037cbb6405e1",
      "index_digest": "sha256:ce2eac6e2bea8659161ba5957589655f7dede40a6d85b5819627037cbb6405e1",
      "worktree_digest": "sha256:ce2eac6e2bea8659161ba5957589655f7dede40a6d85b5819627037cbb6405e1",
      "untracked_digest": "absent"
    },
    {
      "path": "stella_project/plugins/bot_main/ai_gateway.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:90e26001cf16b098ef0a80118ca2324770d43114e4228269a21c05fbbafff006",
      "index_digest": "sha256:90e26001cf16b098ef0a80118ca2324770d43114e4228269a21c05fbbafff006",
      "worktree_digest": "sha256:b3fb809144345b032aa1af72a0556cea8aa1d83cef16e3c8bd31bc7ebe89723f",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/astrbot_compat/test_dispatch.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:266ce9db14592909d964921e31effe6d2cf288cd58afda5e0f23cce22c1a0a00",
      "index_digest": "sha256:266ce9db14592909d964921e31effe6d2cf288cd58afda5e0f23cce22c1a0a00",
      "worktree_digest": "sha256:99fec24d6dcd3cfd3c66c39acb61e91d206c5df33075a4f482e3765271c1dc70",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/astrbot_compat/test_llm_hooks.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:0c1fd9cf4df3b41a5184136c15c2e89bde63555fd357f82ff6c9fae5c906ae1b",
      "index_digest": "sha256:0c1fd9cf4df3b41a5184136c15c2e89bde63555fd357f82ff6c9fae5c906ae1b",
      "worktree_digest": "sha256:0c1fd9cf4df3b41a5184136c15c2e89bde63555fd357f82ff6c9fae5c906ae1b",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/astrbot_compat/test_loader.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:640d9294f841c4a1417ed84264bee9bfd6c8c926c33c94d1143c757cecbcb867",
      "index_digest": "sha256:640d9294f841c4a1417ed84264bee9bfd6c8c926c33c94d1143c757cecbcb867",
      "worktree_digest": "sha256:640d9294f841c4a1417ed84264bee9bfd6c8c926c33c94d1143c757cecbcb867",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/astrbot_compat/test_request_llm.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:bf662d8a49f4c21b2a9678eaa066a8185e967e136ae2b4848fc64089c8d03f9c",
      "index_digest": "sha256:bf662d8a49f4c21b2a9678eaa066a8185e967e136ae2b4848fc64089c8d03f9c",
      "worktree_digest": "sha256:bf662d8a49f4c21b2a9678eaa066a8185e967e136ae2b4848fc64089c8d03f9c",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/capability/test_capability_hooks.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:eadac6f357ccb2274ee5e0bd64b102986dd8709cb6228069a97c2e5528d13d11",
      "index_digest": "sha256:eadac6f357ccb2274ee5e0bd64b102986dd8709cb6228069a97c2e5528d13d11",
      "worktree_digest": "sha256:e121ac9e87a5413ddc903cc10546462cb8934ae21b434030f2c27e86ca556bfc",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/capability/test_comes_executor.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:3da62df29c54737eff8f72623f4c2202d3630e52b84e26e831a0560ef39816bd",
      "index_digest": "sha256:3da62df29c54737eff8f72623f4c2202d3630e52b84e26e831a0560ef39816bd",
      "worktree_digest": "sha256:3da62df29c54737eff8f72623f4c2202d3630e52b84e26e831a0560ef39816bd",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/capability/test_router_cascade.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a4a60520662bce6de291ccb01a4b9afa2526a836094140f780256d0f8d7896b5",
      "index_digest": "sha256:a4a60520662bce6de291ccb01a4b9afa2526a836094140f780256d0f8d7896b5",
      "worktree_digest": "sha256:a4a60520662bce6de291ccb01a4b9afa2526a836094140f780256d0f8d7896b5",
      "untracked_digest": "absent"
    }
  ]
}
    },
    "primary_symbols": [
      {"symbol":"route","file":"capability/router/__init__.py","lines":"66-123","role":"rules/embedding/optional fallback routing"},
      {"symbol":"build_tool_tasks","file":"capability/hooks.py","lines":"67-86","role":"deterministic task input construction"},
      {"symbol":"_run_comes","file":"capability/hooks.py","lines":"101-118","role":"capability execution and context result handoff"},
      {"symbol":"execute","file":"capability/comes/executor.py","lines":"263-381","role":"direct versus agent tool execution"},
      {"symbol":"dispatch","file":"astrbot_compat/pipeline.py","lines":"317-380","role":"ordinary plugin dispatch and model request split"}
    ],
    "related_symbols": [
      {"symbol":"Route","relationship":"DATA CONTRACT","relevance":"must distinguish deterministic tool execution from chat generation"},
      {"symbol":"Capability.input_schema","relationship":"INPUT CONTRACT","relevance":"capability-level deterministic slots"},
      {"symbol":"Task.input","relationship":"DATA FLOW","relevance":"known slots bypass model guessing"},
      {"symbol":"FunctionTool.parameters","relationship":"INPUT CONTRACT","relevance":"required/type/enum validation boundary"},
      {"symbol":"summarize/from_tool_outputs","relationship":"CALLS","relevance":"model-free safe summary"},
      {"symbol":"get_provider_manager","relationship":"CALLS","relevance":"HIGH-risk provider availability boundary"},
      {"symbol":"call_event_hook","relationship":"CALLS","relevance":"HIGH-risk lifecycle/after-send hook boundary"},
      {"symbol":"Pipeline.run","relationship":"CALLS","relevance":"pre-hook short-circuit and optional chat generation"},
      {"symbol":"handle_plugin","relationship":"CALLS","relevance":"ordinary plugin entry and handled-message coordination"}
    ],
    "execution_path": [
      "Message enters ordinary plugin dispatch and capability-aware chat entry independently.",
      "Router runs Level 0 rules, then Level 1 embedding; Level 2 generation fallback only when its backend is available.",
      "Capability hit is converted to Task with objective plus deterministic Task.input from declared schema/parser.",
      "Comes resolves a unique live provider/tool and direct-calls it when required input is complete; otherwise returns structured missing/ambiguous/model-required result.",
      "Successful deterministic Result.summary is written to ctx.reply and ctx.lines; chat generation is skipped.",
      "Existing gateway sends the lines once and performs reply bookkeeping/hooks; ordinary plugin dispatch remains model-independent."
    ],
    "pdg_constraints": [
      {"description":"_run_comes returns early for empty tasks or missing event; otherwise execute_all writes task_results and tool_summaries.","affected_statements":["capability/hooks.py:101-118"],"implementation_consequence":"Keep event/task guards, then add direct-reply state only after successful results are available."},
      {"description":"route had no usable PDG statement result; source/tests are authoritative for its cascade.","affected_statements":["capability/router/__init__.py:66-186"],"implementation_consequence":"Re-verify every rule/embedding/fallback branch after edits; empty PDG is not a safe-unused signal."}
    ],
    "architectural_patterns": [
      {"pattern":"Independent embedding configuration and gate","example_location":"config/settings.py:460-472,1062","usage_guidance":"Never infer embedding availability from ASTRBOT_LLM_ENABLED."},
      {"pattern":"Conservative router degradation","example_location":"capability/router/types.py:101-108","usage_guidance":"Embedding failure must not trigger guessed tools."},
      {"pattern":"Task.input known-slot protocol","example_location":"core/tasks.py:74-96","usage_guidance":"Use structured inputs to avoid model parameter guessing."},
      {"pattern":"No-argument Comes direct call","example_location":"capability/comes/executor.py:121-129,305-318","usage_guidance":"Extend to validated parameterized direct calls without changing agent fallback semantics."},
      {"pattern":"Pure output summarization fallback","example_location":"capability/comes/summarizer.py:53-97","usage_guidance":"Direct replies use safe tool-output summaries, never raw internal errors."},
      {"pattern":"Pre-hook short-circuit","example_location":"core/pipeline.py:167-175","usage_guidance":"Set reply and lines coherently before bypassing chat generation."}
    ],
    "files_to_modify": [
      {"file":"capability/router/types.py","symbols":["Route"],"intended_change":"Represent deterministic tool execution separately from chat generation while retaining serialization."},
      {"file":"capability/router/__init__.py","symbols":["route","_cascade"],"intended_change":"Keep rules/embedding available without chat model and gate Level 2 by backend availability."},
      {"file":"capability/registry.py","symbols":["Capability","CapabilityProvider"],"intended_change":"Declare deterministic input/provider metadata."},
      {"file":"core/tasks.py","symbols":["Task","Result"],"intended_change":"Carry structured input and missing/clarification execution state."},
      {"file":"capability/hooks.py","symbols":["build_tool_tasks","_run_comes","activate_capabilities"],"intended_change":"Extract slots, invoke model-free execution, and hand off direct replies."},
      {"file":"capability/comes/executor.py","symbols":["execute","_direct_call","_agent_call"],"intended_change":"Direct-call validated parameterized tools; preserve optional agent branch."},
      {"file":"capability/comes/summarizer.py","symbols":["summarize","from_tool_outputs"],"intended_change":"Guarantee safe model-free summaries."},
      {"file":"core/context.py","symbols":["ChatContext"],"intended_change":"Carry direct-reply/handled state without core-capability import cycle."},
      {"file":"core/pipeline.py","symbols":["Pipeline.run"],"intended_change":"Honor direct capability replies without entering chat generation."},
      {"file":"stella_project/plugins/bot_main/ai_gateway.py","symbols":["handle_chat","handle_plugin"],"intended_change":"Send direct lines once and avoid no-model placeholder responses."},
      {"file":"stella_project/plugins/bot_main/__init__.py","symbols":["module imports"],"intended_change":"Load ordinary plugin runtime independently of AI gateway."},
      {"file":"astrbot_compat/loader.py","symbols":["initialize_plugins"],"intended_change":"Classify model-only initialization limitations separately."},
      {"file":"astrbot_compat/pipeline.py","symbols":["dispatch","_emit","run_provider_request"],"intended_change":"Preserve ordinary dispatch and optional model request boundaries."},
      {"file":"astrbot_compat/llm/agent.py","symbols":["call_event_hook","run_tool_loop"],"intended_change":"Keep agent runtime optional and lifecycle-compatible."},
      {"file":"astrbot_compat/llm/manager.py","symbols":["ProviderManager","get_provider_manager"],"intended_change":"Expose availability reason without changing provider shape."},
      {"file":"config/settings.py","symbols":["model/embedding settings"],"intended_change":"Document independent availability roles."},
      {"file":"tests/capability/test_router_cascade.py","symbols":["route tests"],"intended_change":"Test embedding-without-chat-model routing and fallback skip."},
      {"file":"tests/capability/test_capability_hooks.py","symbols":["build_tool_tasks","activate_capabilities"],"intended_change":"Test slot extraction and direct reply handoff."},
      {"file":"tests/capability/test_comes_executor.py","symbols":["execute tests"],"intended_change":"Test parameterized direct calls, missing inputs, and no agent invocation."},
      {"file":"tests/astrbot_compat/test_dispatch.py","symbols":["dispatch tests"],"intended_change":"Test ordinary plugin behavior with no generation model."},
      {"file":"tests/astrbot_compat/test_loader.py","symbols":["loader tests"],"intended_change":"Test model-only initialization degradation."},
      {"file":"tests/astrbot_compat/test_request_llm.py","symbols":["ProviderRequest tests"],"intended_change":"Preserve model-enabled compatibility and explicit unavailable behavior."},
      {"file":"tests/astrbot_compat/test_llm_hooks.py","symbols":["hook tests"],"intended_change":"Preserve hook order and no-model behavior."},
      {"file":"docs/plugin-spec.md","symbols":["runtime/capability contract"],"intended_change":"Document schema-driven deterministic execution and no-model scope."},
      {"file":"docs/configuration.md","symbols":["router/Comes/model settings"],"intended_change":"Document independent embedding and generation availability."}
    ],
    "tests": [
      {"file":"tests/capability/test_router_cascade.py","scenarios":["chat model disabled + embedding enabled + semantic weather hit -> tool route","chat model disabled + uncertain semantic result -> Level 2 skipped, no model call","embedding unavailable -> conservative no-tool route"]},
      {"file":"tests/capability/test_capability_hooks.py","scenarios":["weather message -> Task.input contains city/date slots","successful deterministic result -> ctx.reply and ctx.lines populated","missing required slot -> structured clarification, no execution"]},
      {"file":"tests/capability/test_comes_executor.py","scenarios":["single parameterized tool + complete Task.input + no model -> direct success","single parameterized tool + missing input -> failed/needs-clarification without agent","multiple tools without unique deterministic selection -> no guessed execution","partial direct results -> safe summary only"]},
      {"file":"tests/astrbot_compat/test_dispatch.py","scenarios":["LLM disabled + command/regex/event plugin -> load, dispatch, send","ordinary handler after model-dependent handler -> still runs","ProviderRequest -> explicit unavailable only at request boundary"]},
      {"file":"tests/astrbot_compat/test_loader.py","scenarios":["ordinary initialize with model disabled -> activated","model API initialize failure -> model-limited, unrelated ordinary handlers preserved","non-model unsupported API -> existing failure semantics"]},
      {"file":"tests/astrbot_compat/test_llm_hooks.py","scenarios":["ordinary post-send hook remains ordered","agent hook order unchanged when model exists","no-model path does not duplicate or leak internal errors"]}
    ],
    "verification_commands":["python -m pytest tests -q","pytest tests/ --cov=. --cov-branch -n auto --dist loadgroup --timeout=120 --timeout-method=thread","ruff check .","git status --short","node C:\\Users\\Vegetable\\.agents\\skills\\gitnexus-plan\\scripts\\evidence-provenance.mjs snapshot --repo . --schema-version 2 --generated-plan docs/plans/2026-09-10-gitnexus-plan-optional-model-plugin-runtime.md"],
    "risks":["HIGH: get_provider_manager has 8 direct callers and 45 impacted symbols; provider property and probe callers must remain compatible.","HIGH: call_event_hook has direct callers dispatch, run_provider_request, and run_tool_loop; preserve ordinary after-send and agent hook ordering.","Deterministic parser errors can cause false tool calls if schema/parser boundaries are permissive; fail closed on ambiguity.","Direct result handoff can duplicate sends or fall through to chat placeholder if reply/lines/handled state diverge.","Import-time registration and hot reload can duplicate ordinary handlers when ai_gateway is split.","Embedding and chat model availability can be conflated unless role-specific status is explicit.","The same StellaCompatNotSupported hierarchy covers non-model APIs; classify narrowly."],
    "assumptions":["The existing Capability.input_schema and Task.input are the preferred extension points; confirm no third-party plugin depends on a conflicting schema shape.","A deterministic parser/provider selector can be declared without importing core or LLM modules into core/tasks.py.","Direct reply is allowed to use safe deterministic text derived from tool output; it must not require a natural-language generator.","A product decision is still needed for partial multi-capability requests: execute safe subset or require all capabilities to be deterministic."],
    "open_questions":["Should deterministic parsers be declared only in capability.toml, or may plugin code register parser callables?","For a missing city/date, should Stella ask one fixed clarification question, or expose a structured result to an outer reply formatter?","Should ordinary capability direct replies share the existing chat group lock and post-send bookkeeping, or use a separate always-on runtime with a shared send finalizer?","Should local maintenance tasks in ai_gateway stay active when chat generation is unavailable, or move to the always-on operational module?"],
    "avoid":["Do not treat embedding as part of chat/agent model availability.","Do not make Level 2 router fallback run without its generation backend.","Do not route deterministic parameterized tasks through _agent_call merely because the old path did.","Do not execute a tool when required slots are missing or ambiguous.","Do not write raw Result.data, internal errors, or agent failure text to the user.","Do not directly rewrite get_provider_manager().provider semantics.","Do not make all StellaCompatNotSupported exceptions mean model unavailable.","Do not remove ProviderRequest, Context.llm_generate, Context.tool_loop_agent, old import paths, or ordinary after-send hooks.","Do not treat empty PDG output as proof a branch is unused.","Do not modify unrelated user changes or generated runtime data."]
  }
}
```

## 12. Assumptions and Open Questions

**Assumptions**

- [assumed] 本任务的“无模型”明确排除 embedding；embedding 可作为 Level 1 能力识别器继续运行。聊天生成、Agent 工具选择和 Level 2 生成 fallback 才属于可选模型 runtime。
- [assumed] 能力输入解析优先使用声明式 `input_schema`/regex/枚举/默认值；插件代码 parser 若允许，必须有明确的安全边界与异常隔离。
- [assumed] 工具成功摘要可由现有纯函数摘要器从工具输出生成；不要求聊天模型改写自然语言。
- [assumed] 无法可靠填参时宁可澄清/不执行，不让 agent 猜测。
- [verified] Git porcelain 当前只显示本计划文件为 untracked；证据快照仍记录若干 cited path 的 worktree 字节层差异，可能受 Windows 换行归一化影响，执行前应以 Git 状态与 helper 快照双重复核；本计划文件路径按契约排除在全局 dirty digest 外。

**Open Questions**

- [open] 参数解析协议最终采用纯 TOML 声明、插件注册 callable，还是两者并存。
- [open] 缺参时固定澄清语句的归属：Comes 返回结构化状态，还是 capability/网关负责格式化。
- [open] 多能力请求的部分执行策略。
- [open] `ai_gateway` 中本地维护任务是否一并移到 always-on operational runtime。
- [deferred] 不在本任务内重构整个 `core.pipeline.Pipeline` 的记忆/Planner 体系；只为确定性能力增加可验证的短路与发送契约。

## 13. Definition of Done

- [ ] 聊天/Agent 生成模型不可用但 embedding 可用时，规则或 embedding 能识别可路由能力；Level 2 不会因缺模型而强行调用。
- [ ] 对 `weather.query` 这类有参工具，声明式/确定性 parser 能从用户消息填充必填槽位，Comes 在无聊天模型时直接调用一次。
- [ ] 工具成功/部分成功结果以安全摘要填充 `ctx.reply` 和 `ctx.lines`，只发送一次，不经过聊天生成模型，也不落到 `......？`。
- [ ] 缺失或歧义参数不会调用工具/Agent，用户得到明确且不泄漏内部细节的澄清或不可用反馈。
- [ ] 无模型时普通 command/regex/event 插件完成加载、初始化、dispatch、消息发送和生命周期 hook。
- [ ] 有模型时 ProviderRequest、Context LLM API、Agent hook、scheduler 和旧导入路径保持兼容；无模型时只在模型边界给出明确状态。
- [ ] `get_provider_manager`、`call_event_hook`、`dispatch` 的直接调用者均完成回归验证。
- [ ] 文档明确“无模型不包含 embedding”，并说明能力声明、参数解析、直接回复和模型依赖边界。
- [ ] 定向测试、全量 pytest、CI 等价测试、`ruff check .` 通过；最终 `detect_changes({scope:"all"})` 非 partial/truncated，且高风险影响已复核。