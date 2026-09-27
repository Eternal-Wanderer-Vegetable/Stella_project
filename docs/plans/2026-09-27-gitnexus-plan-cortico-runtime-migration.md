# Stella → Cortico 整体运行时迁移计划

> 状态：**已修订（v2，2026-09-27）**——放弃引入 Cortico Core 运行时，转为**自有 facade 运行时（纯 Python）**。本 §R 为权威修订，与正文冲突处一律以本节为准；M0–M4 产物按 §R.4 重新定位。
> 原始基线（v1 存档）：Scope=Cortico Core 拥有轮次生命周期；Stella 证据基线 `390987e37847b5eea57f90f74d42e66b10664b8f`（分支 fix/webui-frontend）；Cortico 基线 `bc47c824d388345f1c13722f4a05a5f745a028f8`；GitNexus 索引 2026-09-27T00:12:46Z（726 文件/61,608 节点）；标记 `[verified]/[graph]/[inferred]/[assumed]` 语义见 §11。

## §R 修订记录 v2（深度收束：全 Python 运行时）

### R.1 决策依据（源自 M1 原型的实测结论）

- 领域复杂度全部留在 Python 之后，对 Cortico 的实际消费面收敛为「fork 执行一轮」：组装请求 → 恰好一次模型调用 → 返回正文。该语义与 M2 提取的 `turn_service.generate_reply` **等价**——继续保留 Node 层属于纯间接层。
- 跨进程桥带来一整类缺陷面（帧协议/双锁/子进程生命周期），实施中已实际触发一次 reset 锁重入死锁（计划 §9 预警的失败形态）。
- 性能账为负贡献：桥开销每轮约 4–5ms（单跳 p95=2.2ms 实测）对比秒级模型底盘；20 Core 实例 +67MiB RSS；轮次本就是 I/O 密集，进程内 asyncio 与 legacy 同姿势。
- M8 的 Node 发行链（Docker Node 层/NSIS 装载/start.bat 引导/离线闭包）是剩余工作里最重的一块，深度 2 直接删除该工作流；同时消除打包后的 Node22+ 运行时依赖。

### R.2 范围变更

- **保留**：M0 全部产物（功能清单/行为契约/基线报告/legacy oracle——最高验收基准不变）；M2 阶段服务（prepare/generate/finalize）与 ChatContext JSON 投影；M3 的 facade 语义（唯一 owner、per-key 锁、owner_epoch、reset fence、独立 JSONL 运行记录）与 M4 的入口分支——实现载体从「Node host + 双向桥」改为**进程内 asyncio 执行器**。
- **删除**：`vendor/cortico/` 快照、`node_runtime/cortico/`（host/桥/TS 测试/upstream-lock/补丁）、NDJSON 线协议（bridge.py/contracts.py）、M8 的 Node 打包工作流。
- **降级**：Cortico（参考克隆 `E:\stella\_reference\Cortico`，MIT）为纯设计参考，不再跟随其更新；turnPolicy 上游 PR 设想作废。
- 模式名同步更名：`STELLA_RUNTIME` 取值 `legacy|cortico` → **`legacy|native`**（native = 自有 facade 运行时；默认仍 legacy，切默认延后至 M9 与旧引擎退役一并处理）。

### R.3 修订后的验收（替代 §13 相应条目）

- 生产对话生成入口统一经 facade（`STELLA_RUNTIME=native`）；轮次生命周期由 facade 运行记录承载（accepted→prepared→generating→completed|failed|cancelled），投递状态另记。
- **行为 oracle 不变**：冻结 legacy traces 逐字节一致仍是每次提交的最高基准；DIRECT/SILENT 早退、预算/超时兜底（BC-1..17）逐条保持。
- 无 Node 依赖：全部发行渠道无需 Node22+（M8 缩减为「确认无新增发行物 + 原渠道回归」）。
- M6（主动/调度迁 facade）、M7（bot.py 生命周期接 facade）结构不变，落点改为 facade；M9 差异回放的对比基准仍是 M0 冻结 traces。

### R.4 M1–M4 产物的重新定位

- M1：定位为「依赖面测量原型」。其结论（消费面极薄、桥无必要、行为可逐字节对齐）即本次修订的输入；vendor 快照/补丁/TS host 移出仓库（git 历史保留可溯）。
- M2–M4：全部保留，载体置换为纯 Python；置换验收 = 34 例 runtime 测试重构后全绿 + 10 份冻结 oracle 逐字节不变。

> Evidence provenance schema 2；全局 dirty digest：ddae2d79e44267d6fd40de31c3f37d8d0f10af2a37e7e7e7753d1c4300704ecf；引用文件清单见 §11；只排除本计划的精确路径。
> 标记：`[verified]` 已读源码；`[graph]` 图查询结果；`[inferred]` 基于证据的设计判断；`[assumed]` 尚需验证。下文“拟新增”均为设计，不代表已有 API。

## 1. Objective

将 Stella 从以 `Pipeline.run` 为中心的逐次请求编排，迁移为由 Cortico Core 承担事件接收、会话生命周期、轮次执行、取消与运行记录的持续运行系统。当前 Python 领域服务和 QQ、WebChat、WebUI、桌面端继续提供原有功能。

本计划作出以下范围决定：

- **真正使用 Cortico Core**。兼容期间可以保留旧引擎；迁移完成后，所有原有对话生成入口经新运行时执行，不能由 Cortico 再调用完整旧 `Pipeline.run` 冒充迁移完成。
- **整体替换核心，分阶段交付**。保留记忆、人格、知识、Skills、Comes、MCP、调度的业务实现与数据所有权；“整体”不等于将全部 Python 代码重写为 TypeScript。
- **行为兼容优先**。提示词构建、模型调用次数、主动发言门禁、WAIT、输出后处理、平台投递和现有配置默认值均有兼容验收。
- **本次不新增自主能力**。不接 Codex、不加 Coding Agent SDK/进程、代码工作区或子 Agent 调度器；也不借迁移启用新梦境、无限反思、自治目标生成或更多主动发言。当前已有 scheduled-agent 功能必须保留，它不属于本次排除的未来 Coding Agent。
- **数据不重建**。现有记忆与任务数据继续使用；新增运行时记录采用独立、可回退的存储。

完成后，Stella 获得统一的持续运行底座；未来子 Agent 集成作为独立计划实施，不作为本计划任何阶段的依赖或验收条件。

## 2. Current Behaviour

[verified] 当前主要执行路径为：QQ 事件／WebChat／主动发言 → 构造 `ChatContext` → 前置 hooks → 可选 Planner → 提示词与预算 → LLM → 后置 hooks → 各入口完成记录和发送。主要证据为 `core/pipeline.py:220`、`stella_project/plugins/bot_main/ai_gateway.py:520`、`webui/chat_ingress.py`。

| 当前契约 | 已核对行为 | 迁移中必须保留 |
| --- | --- | --- |
| 普通回复 | [verified] `tests/test_pipeline_compose.py:178` 验证一次聊天模型调用 | 新核心不能自动增加总结、续写、重试或工具推理轮次 |
| 前置直接回复 | [verified] 同文件的 direct-capability 场景为零次聊天生成 | 工具已有最终答复时直接结束；不能仍进入 Core 的默认生成路径 |
| Planner | [verified] `core/planner.py:163` 及 `tests/test_planner.py:167`：WAIT 有触发条件与调用上限 | 被动回应、主动插话、主动 @ 的语义区别保留；不能把“没有内容”统一变成兜底回复 |
| 提示词 | [verified] `core/pipeline.py:116`、`:264`、`:303`：记忆分支、工具/知识/技能文本、人格解析与裁剪 | 不因 Cortico 持久会话而额外拼入第二份历史 |
| hooks | [verified] `stella_project/plugins/bot_main/ai_gateway.py:208` 起的注册与 Pipeline 排序 | 前置视觉、上下文、能力的先后；后置解析、过滤、分行、日志的顺序，以执行代码为准 |
| QQ 发送 | [verified] `stella_project/plugins/bot_main/ai_gateway.py:614` 起在实际发送前已有学习、BOT_SELF 记录和压缩调度；首行引用，后续分行有间隔 | 本次不顺带调整这项既有副作用顺序；发送失败兼容单独记录 |
| WebChat | [verified] `webui/chat_ingress.py` 使用独立锁、负 group ID 和 `webchat` 空间 | 与 QQ 隔离；输入与 BOT_SELF 记录、thought/lines 返回结构保留 |
| SSE 与重置 | [verified] `webui/routers/chat.py`：run_started/complete/error；不是逐 token 模型流；reset 清聊天记录和汇总状态 | 不更改前端协议；reset 必须同时清除该会话的新运行记录，不能恢复已清历史 |
| 主动 @ | [verified] `stella_project/plugins/bot_main/ai_gateway.py:1763`：虽为主动发起，`trigger="reply"`、`intent="proactive_at"`；目标、配额、去重、发送和回访有特定顺序 | 不依据 trigger 单字段粗暴合并为普通主动任务 |
| 定时任务 | [verified] scheduling runtime 与 delivery 使用现有任务状态、租约和投递判断 | 保留执行/投递区分；UNKNOWN 不盲目重发；非生成型提醒不新增 LLM |
| 扩展 | [verified] `extensions/__init__.py` 通过 `setup(pipeline)` 注册 hooks 或替换后端 | 已有扩展接口需要兼容 facade，不能只迁移内置插件 |

“保持不变”指同样输入和配置下的路由、提示词、调用预算、状态写入、API 与发送策略相同；真实模型文本存在随机性，不承诺逐字相同。验收使用固定模型响应和规范化事件 trace，真实模型另做质量抽查，不能以抽查替代确定性回归。

## 3. Relevant Architecture

### 3.1 已验证的 Cortico 边界

[verified] 固定版本的 [package.json](https://github.com/Pal-AI-Lab/Cortico/blob/bc47c824d388345f1c13722f4a05a5f745a028f8/package.json) 标记 `version: 0.1.4`、`private: true`、Node `>=22`、pnpm `11.5.0`。因此不能假定它是可直接安装、接口稳定、Windows 离线发行已验证的成熟发行包。

[verified] [types.ts](https://github.com/Pal-AI-Lab/Cortico/blob/bc47c824d388345f1c13722f4a05a5f745a028f8/src/core/types.ts#L396) 的 SessionDecl 区分 persistent 与 receivesEvents；[core.ts](https://github.com/Pal-AI-Lab/Cortico/blob/bc47c824d388345f1c13722f4a05a5f745a028f8/src/core/core.ts#L130) 要求恰好一个主会话同时持久化并接收事件。[generation.ts](https://github.com/Pal-AI-Lab/Cortico/blob/bc47c824d388345f1c13722f4a05a5f745a028f8/src/core/generation.ts#L66) 允许注入 ResponseClient。

[verified] Persona 的 `onDelivery` 返回 void；`sessionHead` 是在持久历史前追加内容；[loop.ts](https://github.com/Pal-AI-Lab/Cortico/blob/bc47c824d388345f1c13722f4a05a5f745a028f8/src/core/loop.ts#L525) 对 onDelivery 异常记录警告后继续。它们不直接提供 Stella 所需的“前置 hook 决定零生成并结束”与“只使用原提示词而不叠加 Core 历史”的保证。

[inferred] 因此第一道工程门槛是兼容性原型，而不是直接把所有入口接到默认 Persona。需要验证公开接口是否足够；不足时采用有限、通用的上游补丁，并明确长期维护成本。

### 3.2 目标责任划分

| 层 | 迁移后的责任 | 不能重复拥有的责任 |
| --- | --- | --- |
| Python 接入层 | NoneBot/QQ、WebChat API、原鉴权、输入解析、真实平台发送 | 不再拥有另一套完整会话生成循环 |
| Cortico host（拟新增 TypeScript 进程） | 会话注册、事件队列、轮次状态、执行/取消/终结、运行记录 | 不直接访问 QQ Bot 对象或写 Stella 记忆数据库 |
| Stella Persona/turn adapter（拟新增） | 将一次 Core 轮次映射为 prepare、生成/直接回复/静默、finalize | 不能通过再调用旧 Pipeline 来绕开新核心 |
| Python 领域服务 | 原人格、记忆、上下文、Planner、能力/Comes、知识、Skills、MCP、LLM 后端和预算 | 不擅自启动第二个同会话 owner；不额外重试已消费的轮次 |
| 原调度系统 | 持久化业务任务、到期、lease、任务执行与投递状态 | 不把所有持久任务改成仅存在于 Node 内存的 timer |
| RuntimeFacade（拟新增 Python） | 统一 submit/cancel/drain/reset/health 和后端切换；持有唯一入口互斥策略 | 不跨桥传 pickle、可执行代码或原始 Bot/Event 对象 |
| 原 UI 与发行体系 | 维持 API、配置、桌面/网页体验、Windows 和 Docker 使用方式 | 不强制用户使用 Cortico 示例控制台代替 Stella 界面 |

设计路径为 `QQ / WebChat / 当前主动与调度入口 → RuntimeFacade → Cortico Core → Python 领域服务 → Core 终结 → 原入口投递适配器`。业务提醒可走确定性任务路径，不必为获得统一 trace 而变为模型轮次。

[assumed A1] 首选在单一 Node host 中按逻辑对话懒创建 Core 实例。QQ 组的 key 至少含平台/机器人身份/group ID，WebChat 使用独立命名空间；共享记忆空间只影响检索范围，不等于合并运行会话。M1 必须验证多实例资源、回收与恢复；不可未经验证改成所有群共用一个 Core 主会话。

## 4. GitNexus Findings

本次采用五个主符号，impact 深度 3；没有把图中缺边视为未使用。以下查询在同一源码基线上完成；PDG 刷新没有改变源码。

| 主符号及查询 | 图结果与限制 | 对计划的影响 |
| --- | --- | --- |
| `context/impact`，UID `Method:core/pipeline.py:Pipeline.run#1`，upstream | [graph] `risk: LOW`，6 个可达依赖、3 个直接 caller；`epistemic: lower-bound`，20 个名为 run 的未解析调用点 | 直接覆盖 handle_chat、_proactive_at_user、_proactive_speak_for_group；不能据 LOW 判整体迁移低风险 |
| `impact ChatContext --direction upstream --depth 3` | [graph] `risk: MEDIUM`，14 个依赖、7 个直接依赖文件 | §9 逐项处理这 7 个使用方；保留上下文兼容协议 |
| `impact activate_capabilities --direction upstream --depth 3` | [graph] `risk: UNKNOWN`，`No callers resolved. Absence of edges is not evidence the symbol is unused` | 已用源码确认 capability/hooks.py:419 的注册及 gateway 的调用；callback 风险仍不能由空图排除 |
| `impact run_turn --direction upstream --depth 3` | [graph] `risk: LOW`，直接 caller 是 chat 路由内嵌 stream | [verified] 实际通过动态解析访问 Pipeline；因此 WebChat 必须显式列入迁移 |
| `impact SchedulerRuntime --direction upstream --depth 3` | [graph] `risk: LOW`，4 个依赖、1 个直接 import 使用方 ai_gateway | 迁移调度 wiring 时保留已有 lease、共享锁、stop 生命周期 |

[graph] 概念查询覆盖消息/主动回复、能力与记忆隔离、启动关闭、WebChat；context/clusters/processes 资源显示 core、memory、capability、scheduling、webui、deploy 等跨模块边界。资源返回的 top 列表不是完整功能清单。

[graph] 索引器还报告 receiver/property 与跨语言解析缺口、部分流程遍历预算截断。因此本计划结合源码和测试，M0 继续做“入口/API/配置/发行物”全量清单；不宣称当前图已经证明全功能覆盖。实施时每次改符号仍须重新 impact；HIGH/CRITICAL 必须报告，UNKNOWN 必须补源码确认；提交前必须完成非 partial、非 truncated 的 detect_changes。

## 5. Statement-Level PDG Findings

执行 `pdg_query(controls, handle_chat, limit=200)` 得 51 条，`pdg_query(controls, core/pipeline.py, limit=200)` 得 81 条；初次小 limit 截断后已扩容重查，完整响应未标记 truncated。执行 `pdg_query(flows, core/pipeline.py, variable=user_prompt, limit=100)` 得 4 条。只保留下述关键切片，不将图的 F 标签误读为业务“失败”。

| 证据切片 | 约束与实施含义 |
| --- | --- |
| [graph] Pipeline:248 的 planner_wait 控制 :251 return；非 WAIT 才进入后续路径 | [verified] 主动静默必须是有类型的结果，不能被最终统一后处理补成“……？” |
| [graph] Pipeline:256 的调用上限控制提示词与生成分支；:301 控制动态人格解析 | 一个 turn 的调用计数不能因跨进程丢失，必须保留配置对应的 system prompt |
| [graph] user_prompt 的 :266/:281 定义流向 :303，裁剪结果再流向 :322 generate | 实际 provider 输入与预算估算使用同一份最终 prompt；仅在 provider 末端替换文本会导致 Core 提前进行的容量判断不一致 |
| [graph] handle_chat:576 控制预算拦截与 :584 Pipeline 调用 | 预算拒绝发生在生成前；IPC/队列不能绕过或重新解释为可重试任务 |
| [graph] handle_chat:596 控制 WAIT 退出与 :601 空回复补偿 | 兼容层必须区分 silent、empty-result、failed，不能都映射为空 lines |
| [graph] handle_chat:630 控制压缩调度；:636/:639/:643 控制逐行间隔、首行引用、末行 finish | 生成完成与平台发送是两个阶段；保留平台端分行逻辑与原异常处理 |

[verified] 源码补充：前置直接回复短路、后置 hooks、学习/记录/发送的顺序均已读源核对。它们不是本次 PDG 数据依赖查询的额外发现。Cortico 未建本地图，相关接口结论来自固定提交源码，不伪称 GitNexus 结论。

## 6. Proposed Changes

### 6.1 固定上游，建立可维护的真实依赖

拟新增 `vendor/cortico/` 固定源码快照与 `runtime/cortico/upstream-lock.json`，记录仓库、完整 SHA、包管理器、许可证与必要补丁校验值。采用独立 lockfile，不能让 dashboard 的依赖升级被迁移顺带触发。优先使用 Core 的 headless 路径，关闭示例 console/world 行为。

[inferred] 固定源码比依赖尚未验证的 npm 发布形态更可控。M1 必须验证 headless 构建可剔除示例应用与非必要原生依赖；若必须带入 canvas/其他与 Stella 无关的重依赖，先记录体积、平台兼容和替代打包方案，不直接纳入离线发行。

### 6.2 拆分旧编排，复用领域逻辑

拟新增 `core/runtime/turn_service.py`：将 `Pipeline.run` 的业务阶段提取为三个可独立测试的操作。旧 Pipeline 在过渡期调用同一批实现，避免两套 prompt/过滤逻辑分叉。

1. `prepare_turn`（拟新增）：运行原 pre hooks、Planner、记忆/知识/工具注入、人格解析和 prompt budget。返回 `generate | direct | silent | failed` 的决策及调用计数。
2. `generate_reply`（拟新增）：仅封装原 LLMBackend、ROLE_CHAT gate、超时、raw output 和用量记录；Core 的 ResponseClient 通过此薄接口调用，**不调用整个 Pipeline**。Comes、Planner、compact 使用原角色与预算逻辑。
3. `finalize_turn`（拟新增）：按原路径条件执行解析、过滤、分行、trace 和结果结构化；平台记录/发送仍由明确的原适配器负责，不在多个钩子重复执行。

提取过程中逐条保留异常回退和短路语义，不能机械保证每个分支都执行 finalize。`ChatContext` 保留为 Python 领域对象；跨进程仅传 JSON 投影，新增字段都有 schema/version，不重命名当前 group/shared_space/user/trigger 等语义。

### 6.3 让 Cortico 真正拥有一次轮次

拟新增 `runtime/cortico/src/stella-persona.ts`、`runtime/cortico/src/turn-adapter.ts`、`runtime/cortico/src/provider-bridge.ts`。常规轮次不能暴露一套新的自主工具 schemas，避免原 Comes 能力和 Cortico 工具循环重复执行。

M1 按顺序验证：

- Core 收到事件后，在调用 provider 和容量检查之前取得 prepare 结果。
- `direct` 不调用聊天模型；`silent` 不发送、不被兜底补偿；`failed` 走现有入口错误语义。
- `generate` 使用既有 prompt 投影；运行日志可持续保存，但 Core 的事件历史不能额外进入模型上下文。
- finalize 和必要平台处理完成后，该轮次才允许释放占有权；取消信号覆盖 Python LLM 等待和 Node 状态。

[assumed A2] 若公开扩展点不足，需要给固定上游增加一个**通用 turn-policy 接口**，覆盖生成前决策、请求投影/容量计算与轮次终结。这是拟议补丁，绝不是当前 Persona API 已具备的功能。限定补丁不承载 Stella 的业务规则；必须附上游单测与补丁重放检查。若需要重写大块 MainLoop、维护另一套事件循环或侵入多个不相关子系统，M1 判为架构门槛未通过，修订设计后再继续迁移，不能降低兼容标准硬切。

### 6.4 跨进程协议、唯一 owner 与恢复

拟新增 `core/runtime/contracts.py`、`core/runtime/bridge.py`、`core/runtime/facade.py` 与对应 TypeScript schema/host。默认 Python 主进程启动一个随生命周期管理的 Node 子进程，采用带 request ID 的双向 stdio JSON-RPC；stdout 专用于协议，日志走 stderr。M1 验证 framing、最大帧、背压、双向请求、崩溃清理和 Windows 行为。

- Envelope 最少包含 schema_version、event_id、conversation_key、turn_id、owner_epoch、source、trigger、deadline、trace_id 与 JSON payload；默认不序列化 raw_event/bot，改为 Python 进程内短期 handle，重启后失效。
- 带副作用的请求必须按 event/turn/effect ID 去重；仅允许列出的领域方法，不开放任意 Python 方法调用。媒体沿用既有处理结果或受控引用，不能把大图随意塞进帧。
- 每个 conversation 只有一个入口 owner。迁移期互斥由 RuntimeFacade 在原入口锁边界统一；同一 turn 的回调不再重入该锁。Core 负责内部顺序；锁顺序与取消路径写成协议测试，防止 Python 等 Node、Node 又等 Python 同一锁。
- 建议轮次状态 `accepted → preparing → generating/direct/silent → finalizing → completed/failed/cancelled`；投递状态另记，不能将 generated 当 delivered。
- 崩溃后只自动恢复确定无副作用、且 deadline/上下文仍有效的工作。发送结果未知、工具已执行但未确认、原始 Event handle 失效的工作标记待判定，禁止自动重放。不能承诺平台不支持的 exactly-once。
- 不使用“新引擎超时后同一事件自动交给旧引擎重跑”。回退发生在后续安全接入点，经 drain/fence/epoch 切换处理。

### 6.5 记忆、能力、调度与扩展的适配

| 对象 | 拟变更责任 | 不变契约与依赖 |
| --- | --- | --- |
| 记忆/人格 | 作为 prepare/finalize 领域服务；Core 使用独立 runtime store | `memory/session_context.py` 的进程内摘要生命周期、空间隔离、V1/V2 开关和 `memory/session_compact.py` 的压缩逻辑保留；不直接以 Cortico memory 替换现有长期记忆 |
| 能力/知识/Skills/MCP | `activate_capabilities` 留在兼容阶段，适配上下文投影 | 保留并行 gather 的异常语义、隔离检查、工具事实注入与原权限；不新增 autonomous tool loop |
| 当前调度 | `SchedulerRuntime` 保留业务 store/lease，生成型工作提交统一 runtime | 现有 reminder/agent 执行器、计划管理 API、取消和 UNKNOWN 投递策略必须通过回归；无需生成的任务保持确定性 |
| 主动发言 | 现有 gate/配额/候选选择继续产生原触发事件 | 迁移 `_proactive_at_user`、`_proactive_speak_for_group`；保持共同锁、去重、skip/WAIT 和回访；不新增触发器 |
| 扩展 hooks | 提供兼容的 hook/backend 注册 facade | 继续支持已有 `setup(pipeline)` 用法、优先级与异常策略；facade 的 run 如保留，必须路由新运行时而非旧引擎 |
| WebUI/桌面 | 保留外部 API，只补 runtime 健康、owner、queue、trace 的诊断映射 | 不修改既有 SSE/鉴权/配置含义；现有 status endpoint 健康判断必须涵盖 Node host |

### 6.6 切换与发布策略

拟新增启动配置 `STELLA_RUNTIME=legacy|cortico`，过渡期默认 legacy，最终默认 cortico。shadow 仅用于隔离回放：所有模型、数据库写入、工具、MCP、平台发送均使用 fixture/stub，不同时执行两套真实副作用；不能因“没有发送 QQ”就认定 shadow 无副作用。

新增运行时存储独立于原数据库。配置和 schema 迁移先采用可向后读取的加法；备份使用 SQLite 一致性备份或停写快照，覆盖 WAL 和其他有状态文件，不能直接复制忙碌中的单个 .db。记录原引擎版本、配置摘要、任务状态与备份恢复步骤。

## 7. Implementation Sequence

执行纪律：以下都是待实施阶段。每阶段先做本阶段符号 impact，完成针对性验证再提交；提交前 detect_changes 必须完整。失败停在当前阶段修复，不继续切生产流量。依赖主链为 M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7 → M8 → M9。业务接入虽可局部开发，验收仍按顺序收敛。

### M0 — 冻结现有契约与功能清单

- 工作：记录当前 commit/配置矩阵；从图中的所有入口补全 QQ 消息类型、命令、WebChat、主动触发、调度类型、工具/知识/Skills/MCP、插件 hooks、模型部署模式、所有 UI API 与发行渠道清单。`openspec/openapi-v1.yaml` 仅作参考，不能替代实际路由枚举。
- 产物：`docs/migration/cortico/feature-parity.md`、`behavior-contract.md`、`baseline-report.md`；每项必须有旧入口、数据归属、旧行为、目标入口、测试/人工步骤、状态和负责人角色。
- 建立固定模型响应、固定时钟/随机种子、去敏后的消息/工具样本；冻结 legacy reference traces。覆盖普通1次、直回0次、Planner分支、超时/预算/取消、QQ分行、WebChat、主动和调度。
- 性能基线：空闲/1/20/100 会话场景、排队延迟、进程 RSS、启动时间、日志增长；按实际部署能力标注不支持的规模，不宣称已有压测结果。
- 验收：当前测试基线明确；已有失败单列，不通过修改断言让它“绿”；功能清单无未归类入口。代码行为不变，legacy 可独立运行。

### M1 — 固定 Cortico 并完成兼容性原型（阻断门槛）

- 工作：vendor 固定 SHA，安装隔离依赖；构建无示例服务的 headless Core 原型；测试 Core 实例隔离、onDelivery/请求投影的实际边界、ResponseClient 注入、取消与退出。
- 试验：普通1次、direct0次、silent0发送、Planner受控次数、固定 provider request 等价、容量检查等价、无额外工具循环、两个群不串历史、reset 后不复活、批处理不合并两个原本独立轮次。
- 若需通用 turn-policy 补丁，先写最小失败测试，再实现补丁；列出触及的上游文件/符号与维护理由。不能先把 Stella 业务塞进 MainLoop 后再反推边界。
- 资源门槛：用 M0 样本验证；暂定本地桥额外延迟 p95 ≤100ms，1/20 会话 RSS 总增量 ≤150MiB，冷启动增量 ≤3s，均排除模型加载/推理；这些是拟议工程预算，不是已测性能。100 会话用于诊断扩展性。超标需优化或明确修订预算依据，不得不报。
- 产物：`compatibility-spike.md`、实际补丁、最小运行时测试、Windows/Docker 构建结果。退出条件：上述行为与发布可行性通过；未通过则方案仍待验证，不能开启入口迁移。

### M2 — 提取领域阶段与兼容注册接口

- 工作：从 `Pipeline.run` 提取 prepare/generate/finalize；旧 Pipeline 改为复用服务，仍是默认。先保持函数签名与 ChatContext，随后添加 JSON 投影，保留 raw_event/bot 的本地 handle。
- 工作：提取 hook registry/backend facade，使 gateway 与 extensions 仍能注册；枚举已存在扩展使用的公开属性，兼容已验证范围。
- 验证：旧实现基准 trace 与提取后 trace 对比；每种短路、异常、优先级、上下文裁剪、工具注入、LLM gate 一致。旧基准不能随实现修改。
- 退出：legacy 行为全通过，服务可独立调用，无 Node 必需依赖。回退仅需切回提取前实现，无数据格式改变。

### M3 — 建立双向桥与新运行时

- 工作：实现 schema、supervisor、facade、Core session registry、persona/turn adapter、薄 provider bridge 与独立运行记录；接入 deadline/cancel/drain/reset/health。
- 工作：以同一 fixture 经完整新链路跑一轮；记录 owner_epoch 和副作用 ID，限制队列和 frame 大小；实现 idle Core 回收及无重复副作用的恢复判断。
- 验证：协议不匹配、乱序响应、断管、节点崩溃、Python退出、超时、取消、同群互斥/异群并发、stdio日志污染、锁重入和积压。
- 退出：新链路在测试入口可用；进程关闭无僵尸，旧引擎仍可选；完全没有平台流量自动切换。

### M4 — 迁移被动聊天入口

- 工作：`handle_chat` 与 `webui.chat_ingress.run_turn` 通过 facade 提交；QQ 发送/引用/间隔与 WebChat SSE 输出保留。将动态 Pipeline 查找改为明确 runtime 依赖。
- 工作：WebChat reset 与当前 in-flight turn 协调：先 fence/cancel/drain，再清该会话记录并递增 epoch；已取消旧轮次不能晚到后重建历史。鉴权与原 120s 请求超时继续适配。
- 验证：回复、@、多行、工具直回、预算静默、provider异常、客户端断开、重复入口事件、两平台隔离。中途故障不得启动 legacy 重发同一条消息。
- 退出：QQ 与 WebChat 在 cortico 模式完成兼容回放；所有外部 API schema 与现有 UI 客户端兼容。

### M5 — 完成领域能力和插件兼容

- 工作：全量检查记忆、空间/人格、画像、会话摘要、压缩、知识、Skills、Comes、MCP、视觉与扩展路径；保留 Python 服务并处理跨桥必需字段。按 M0 清单逐项标记，不凭模块“未改源码”判断兼容。
- 验证：MEMORY_V2 两种分支、共享空间与群隔离、插件优先级/直接回复/backend替换、能力部分失败、工具真实结果、MCP连接与关闭、长输出裁剪、现有本地/混合/远端模型模式。
- 退出：功能清单中上述各项均关联可执行测试或可复现人工步骤；无丢失的 context 字段，无重复记忆写入或额外摘要。

### M6 — 迁移主动行为与当前调度

- 工作：接入两类主动发言与现有 participation 触发路径；迁移生成型定时任务的执行入口，共享 facade 所有权。业务定时器/lease/任务数据库由原调度持有。
- 工作：明确定义启动恢复时到期任务交接、任务取消、生成完成后投递、投递结果不明四种状态；非模型提醒只增加必要运行追踪，不改变执行方式。
- 验证：主动WAIT、skip、冷却/配额/预算、重复话题、主动@回访、被动与主动竞争、多个scheduler worker、任务READY/SENDING/SENT/UNKNOWN、无receipt合法成功、重启后不双发。
- 退出：现有 scheduled-agent 与 reminder 功能齐全；Cortico 定时器没有取代业务持久任务；未新增 Coding Agent 或新自主触发。

### M7 — 统一状态、配置和应用生命周期

- 工作：bot.py 启动顺序增加 runtime supervisor：配置/服务完成 → Node handshake → 接收生成工作；关闭时停接入/停任务派发 → drain或取消 → 关闭Core与桥 → 原资源关闭。保留 MCP 等依赖的正确关闭顺序。
- 工作：status/WebUI/桌面保持已有字段，按需加兼容字段显示 runtime模式、健康、排队、最近失败与trace；新增配置默认值和旧配置迁移说明。
- 验证：冷启、重复进程、Node缺失/版本不符/崩溃、provider不可用、配置重载、graceful shutdown、无网络部署；启动失败有可诊断原因，不悄悄降级为双引擎。
- 退出：现有 WebUI/桌面调用无需改变使用流程；可区分桥断开、模型失败、发送失败；日志不记录密钥或完整隐私 prompt。

### M8 — 打包、数据与回退演练

- 工作：按当前发行工作流逐项纳入 Node22+、编译后TS、上游快照/补丁、依赖许可与版本检查；覆盖 Windows一键/离线/standalone、Docker、开发启动及桌面启动链。Cortico与dashboard锁文件分别固定。
- 工作：新增诊断/备份/迁移预检；从旧数据副本升级，核对记录数量、任务状态、shared space和人格配置；保留可启动的旧版本与兼容数据。
- 演练：Cortico运行后 drain → fence owner → 切 legacy → 同一数据继续工作；必要恢复备份只在验证无新增用户数据丢失的前提下做，不能默认覆盖迁移期间产生的新数据。
- 验证：全新安装、覆盖升级、回退、无网络启动、路径含空格/中文、非管理员Windows、Docker非root、卷权限、SIGTERM；检查子进程随父进程退出。
- 退出：所有原支持发行渠道均能交付；回退演练证据齐全。不能仅开发机跑通就进入最终切换。

### M9 — 差异回放、分批切换与旧核心退役

- 工作：完整确定性回放对比 legacy reference；仅规范化时间/随机ID等已列出字段。测试新增结果文件在本阶段一次性定稿，旧行为 oracle 始终保留；不能用新输出覆盖旧 oracle 消除差异。
- 切换：先单个测试会话，再受控使用范围，最后默认 cortico；每次切换前停止新接入并 drain/fence。每个层级至少覆盖普通/主动/定时/reset/重启及原最长相关调度周期，不能只按运行几分钟判断稳定。
- 回退触发：重复发送、串空间、丢任务、数据不一致、调用次数增加、未解释prompt差异或资源预算失败，任一即停扩容并按 M8 演练回退。
- 收尾：所有生产入口不再调用旧 Pipeline 编排；删除/封存 legacy backend 和迁移专用双路开关，保留必要 plugin兼容facade与旧发行包回退资料。源码搜索只作补充，图查询和执行trace都须证明无旧运行循环。
- 退出：§13全部满足；更新架构、运行、发行、升级说明；列出后续独立 Coding Agent 集成的接口边界说明即可，不编写其实现。

## 8. Test Strategy

### 8.1 已定位的回归入口

| 现有测试或范围 | 必保场景 |
| --- | --- |
| `tests/test_pipeline_compose.py` | prompt结构、工具事实、普通1次/直回0次、输出解析；迁移后覆盖共享领域服务与新runtime |
| `tests/test_planner.py` | 深度、调用上限、WAIT允许条件、预算不足 |
| `tests/capability/test_capability_hooks.py` | 路由/能力hook注册、字段回填、并行失败与隔离；具体断言在实施阶段按相关测试定位 |
| `tests/test_session_context.py`、`tests/test_session_context_cache.py`、`tests/test_session_compact.py` | 摘要生命周期、cache、压缩与裁剪；保证重启/reset不因Core历史改变语义 |
| `tests/webui/test_webui_chat.py` | 负group/space隔离、USER与BOT_SELF记录、SSE、历史/reset、鉴权、standalone错误返回 |
| `tests/scheduling/test_scheduling_delivery.py` | receipt/无receipt、silent、失败UNKNOWN、不自动重发 |
| `tests/test_graceful_shutdown.py`、`tests/test_runtime_contract.py` | 生命周期和runtime契约；需增加Node子进程相关断言 |
| `tests/windows/` 及现有知识/Skills/MCP/participation/主动测试范围 | 在M0逐项映射，不宣称仅上述核心测试已经覆盖整个项目 |

### 8.2 新增测试的具体场景

- 拟新增 `tests/runtime/test_behavior_parity.py`：同一fixture分别执行旧参考与新runtime → 比较规范化prompt、角色/次数、hooks、副作用trace及最终lines；模型内容由stub固定。
- 拟新增 `tests/runtime/test_bridge_protocol.py`：无效schema/大帧/断管/迟到响应 → 有界失败；取消后返回的响应不得继续finalize；双向请求不能锁死。
- 拟新增 `tests/runtime/test_session_ownership.py`：同群两个事件+主动任务竞争 → 顺序完成且只有一个owner；异群并行；切换epoch后旧owner发送被拒绝；旧调度与新runtime无重复领取。
- 拟新增 `tests/runtime/test_restart_recovery.py`：准备前、工具后、生成后、发送中分别崩溃 → 只恢复可证明安全的工作，未知副作用不自动重跑；runtime reset后旧数据不可复活。
- 拟新增 `tests/runtime/test_extension_compat.py`：原setup注册不同priority、直接回复、替换backend → 与原契约相同；新facade不回调legacy引擎。
- 拟新增 `runtime/cortico/tests/turn-compat.test.ts`：实际Core执行generate/direct/silent/cancel → 调用次数/历史投影/容量判断正确；不用mock整个Core来“验证”Core集成。
- 拟新增 `runtime/cortico/tests/host-lifecycle.test.ts`：多Core隔离、idle回收、drain、进程信号、provider取消、关闭无未完成工作泄漏。
- 发行验收：Windows和Docker真实产物执行同一最小聊天fixture；不是仅检查打包文件存在。离线模式禁止启动时联网拉包。

### 8.3 验证命令与前提

[verified] 以下命令依据现有工作流/脚本；本次规划没有运行项目测试，不能视为已通过。使用项目开发环境并先安装 requirements 与测试依赖，沿用 CI 的环境设置。

```powershell
python -m pytest tests/test_pipeline_compose.py tests/test_planner.py tests/capability/test_capability_hooks.py tests/webui/test_webui_chat.py tests/scheduling/test_scheduling_delivery.py -q
python -m pytest tests/ -v --cov=. --cov-branch --cov-report=xml -n auto --dist loadgroup --timeout=120 --timeout-method=thread
python -m pytest tests/windows -q --junitxml=windows-native.xml
ruff check . --output-format=github
pnpm --dir dashboard install --frozen-lockfile
pnpm --dir dashboard build
```

新增runtime包在 M1 明确提供 typecheck/test/build 脚本，之后运行 `pnpm --dir runtime/cortico install --frozen-lockfile`、`pnpm --dir runtime/cortico typecheck`、`pnpm --dir runtime/cortico test`、`pnpm --dir runtime/cortico build`。这些是拟建立的命令，目前不可声称存在。上游固定版本已有 test/typecheck 脚本；按其固定Node/pnpm在vendor工作目录运行，补丁后必须通过。Rust/桌面包装若有改动，追加当前CI对应fmt/clippy/test与产物构建。

GitNexus 可使用 `node .gitnexus/run.cjs`；本次已验证的替代 runner 是 `docker exec -w /repo stella-gitnexus gitnexus`。提交前执行 `detect-changes --scope all --repo .`；最终回归使用 `--scope compare --base-ref <实施起点>`。任何 partial/truncated 不是通过；先解决输出或分析范围不足。

## 9. Risk and Impact Analysis

[inferred] **整体迁移风险高**，即使几个符号的局部 impact 为 LOW。根因是跨语言生命周期、状态所有权和副作用路径的组合变化，不是单一函数 caller 数量。

| 风险 | 控制方式／停止条件 |
| --- | --- |
| Cortico扩展面不足或维护分叉过大 | M1阻断门槛；最小通用补丁、固定SHA、补丁可重放；不得把“成熟”作为未经验证的前提 |
| Core历史与Stella记忆双重注入、8K预算失真 | 同一最终请求用于预算和provider；V1/V2、长上下文、reset固定trace比对 |
| 自动batch/preempt/continuation/retry改变回复 | 兼容模式显式测试逐事件边界；默认禁用会增调用次数/合并轮次的行为，不能只凭配置名称猜测 |
| Python↔Node双锁、取消失联 | facade唯一owner、回调不重入入口锁、deadline和epoch贯穿；故障注入必须无死锁 |
| 工具/记忆/平台双执行 | 影子回放隔离全部副作用；执行和投递分态；未知结果禁止盲重试 |
| 插件依赖Pipeline公共对象 | 保留已验证的注册/backend兼容面，M0扫描现有插件用法；不能未经证据保证任意私有属性访问兼容 |
| 发行和资源开销 | Windows/Docker原生产物验收、离线依赖、Node版本和原生依赖审计、M1预算 |
| 数据回退丢失迁移后消息 | 加法schema/独立runtime库、owner切换、一致性备份；保留迁移后数据，不默认覆盖回滚 |
| 可观测性与状态显示变差 | event/turn/effect/trace关联；区分queue、prepare、model、finalize、send时间与失败；敏感信息脱敏 |

直接依赖逐项处理：

- `Pipeline.run` 三个直接生产caller：handle_chat → M4；_proactive_at_user 与 _proactive_speak_for_group → M6；图漏掉的 WebChat 动态调用经源码补充 → M4。
- `ChatContext` 七个直接依赖：`capability/hooks.py` → M5上下文投影；`core/pipeline.py` → M2提取；`core/planner.py` → M2调用计数/WAIT；`memory/post_processors.py` → M2输出契约；`memory/pre_processors.py` → M5空间/记忆字段；`stella_project/plugins/bot_main/ai_gateway.py` → M4/M6入口；`webui/chat_ingress.py` → M4。
- `activate_capabilities` 无解析caller，但已确认register callback → M2/M5保留注册与运行；UNKNOWN不作为删改许可。
- `run_turn` 的直接 stream caller（`webui/routers/chat.py`）→ M4保留事件序列、错误和超时。
- `SchedulerRuntime` 的直接 gateway import/wiring → M6/M7保留store/service/delivery/共享锁注入。

## 10. Files Expected to Change

以下是实施范围，不代表本次已编辑。现有符号修改前重新查询 impact；尚未定位的入口在对应阶段先用query/context定位并读源码，不能按目录批量替换。

| 文件／范围 | 符号或责任 | 原因 |
| --- | --- | --- |
| `core/pipeline.py` | Pipeline.run、hook注册兼容面 | 分阶段提取，最终退役旧编排 |
| `core/context.py` | ChatContext | 保留领域对象与显式JSON投影 |
| `core/planner.py` | 原Planner行为 | 原则复用；只在提取确需时适配依赖，不改策略 |
| `core/runtime/`（拟新增） | facade、contracts、bridge、turn_service、supervisor、compat_hooks | Python稳定边界 |
| `runtime/cortico/`（拟新增） | host、registry、persona、adapter、provider、tests、lock | 实际Cortico运行时 |
| `vendor/cortico/`（拟新增） | 固定快照与最小通用补丁 | 可追溯上游依赖 |
| `stella_project/plugins/bot_main/ai_gateway.py` | handle_chat、_proactive_at_user、_proactive_speak_for_group、启动wiring | 全部聊天入口切换 |
| `webui/chat_ingress.py`、`webui/routers/chat.py` | run_turn、SSE/reset | WebChat兼容 |
| `stella_project/plugins/bot_main/scheduling/runtime.py`、`stella_project/plugins/bot_main/scheduling/delivery.py` | SchedulerRuntime及已有投递责任 | 统一owner，保留业务调度 |
| `capability/hooks.py`、`memory/pre_processors.py`、`memory/post_processors.py` | activate_capabilities、已有领域hooks | 优先直接复用，必要时小范围解耦 |
| `extensions/__init__.py`、`extensions/link_monitor/__init__.py` | load_extensions、setup | 插件兼容和运行状态 |
| `bot.py`、`webui/services/runtime.py`、`stella_project/plugins/bot_main/status_api.py`、`config/__init__.py` | 生命周期/状态/配置责任 | supervisor、健康和迁移模式 |
| `Dockerfile`、`docker-compose.yml`、`.github/workflows/ci.yml`、`.github/workflows/release.yml` | 构建和发行 | Node与新runtime产物 |
| `scripts/build_offline_payload.py`、现有发行脚本和desktop启动链 | 具体修改点由M0清单定位 | 离线/Windows/桌面兼容 |
| `tests/runtime/`（拟新增）与§8现有测试 | 契约、故障、兼容、回退 | 防止迁移退化 |
| `docs/architecture.md`、`docs/migration/cortico/`（拟新增） | 架构、兼容报告、升级回退文档 | 可维护和可交付 |

不默认重写 memory 数据库、知识索引、Rust模块、dashboard页面或现有 provider；仅在确认接口接入需要时局部改动。新增文件名允许实现时微调，但责任边界和验收不能省略。

## 11. Reusable Implementation Context

以下 JSON 是实施入口；路径相对仓库。证据发生漂移时只重查受影响部分，不能只改HEAD字段洗白旧结论。

```json
{
  "implementation_context": {
    "task_summary": "整体迁移Stella运行时到固定Cortico，保持原功能；仅计划，不含Coding Agent集成。",
    "acceptance_criteria": [
      "M0完整功能清单全通过",
      "Core真实拥有生命周期，生产不调用旧Pipeline编排",
      "prompt/调用预算/静默/副作用契约相同",
      "单owner与隔离恢复故障测试通过",
      "原数据/发行/回退完整",
      "无新增Coding Agent或自治行为"
    ],
    "evidence_provenance": {
      "schema_version": 2,
      "head_commit": "390987e37847b5eea57f90f74d42e66b10664b8f",
      "generated_plan_path": "docs/plans/2026-09-27-gitnexus-plan-cortico-runtime-migration.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "ddae2d79e44267d6fd40de31c3f37d8d0f10af2a37e7e7e7753d1c4300704ecf"
      },
      "cited_path_manifest": [
        {
          "path": ".github/workflows/ci.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:bd4bc7fccb641a01d37fecc43014a27a0e01fbee36f8b892b39721e207af1419",
          "index_digest": "sha256:bd4bc7fccb641a01d37fecc43014a27a0e01fbee36f8b892b39721e207af1419",
          "worktree_digest": "sha256:34d982e2622d379623fa8dcb96e87e6b2b352afadb1ae1be27de86e1ef7ec957",
          "untracked_digest": "absent"
        },
        {
          "path": ".github/workflows/dashboard_ci.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c9f15155dc634596c4e7d6fe56ae04ff565af072189b07aabe8492ba8691fcd8",
          "index_digest": "sha256:c9f15155dc634596c4e7d6fe56ae04ff565af072189b07aabe8492ba8691fcd8",
          "worktree_digest": "sha256:c9f15155dc634596c4e7d6fe56ae04ff565af072189b07aabe8492ba8691fcd8",
          "untracked_digest": "absent"
        },
        {
          "path": ".github/workflows/release.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b5ebda1fd5bba1f2361dcd245d9049e5a81edc6b627e26f48241c7fad12a3930",
          "index_digest": "sha256:b5ebda1fd5bba1f2361dcd245d9049e5a81edc6b627e26f48241c7fad12a3930",
          "worktree_digest": "sha256:efb44f0d2a5d2db8d503d0b1c2de00d410625c5645e0a369af342e2520ea9c43",
          "untracked_digest": "absent"
        },
        {
          "path": "Dockerfile",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",
          "index_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",
          "worktree_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",
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
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:18d7763a4536a283b23c849261157109f71941e6163dd98e0ed20bb854ac2a88",
          "index_digest": "sha256:18d7763a4536a283b23c849261157109f71941e6163dd98e0ed20bb854ac2a88",
          "worktree_digest": "sha256:a59c0591470fbba7fe195ebbdfba08044c63839642dfcc6372ad9bbd6c8ce8ab",
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
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2e47fd4c0aa0f0fffe666ba800837ef2c3034ec8f265a76be145bff9bed875a4",
          "index_digest": "sha256:2e47fd4c0aa0f0fffe666ba800837ef2c3034ec8f265a76be145bff9bed875a4",
          "worktree_digest": "sha256:2e47fd4c0aa0f0fffe666ba800837ef2c3034ec8f265a76be145bff9bed875a4",
          "untracked_digest": "absent"
        },
        {
          "path": "config/__init__.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:36274a767090f1fa9c1cab58e3639becb9c80a10541b887e0b15b8de07bcabaa",
          "index_digest": "sha256:36274a767090f1fa9c1cab58e3639becb9c80a10541b887e0b15b8de07bcabaa",
          "worktree_digest": "sha256:647b68b31b32b8713a17e0a9050fac96415aac83ad1a0868d3228243546bb72c",
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
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3ca8c974bc19040b7298abf40e6ab5d45c64d1560f42fe2288d1315fd4cfd7bb",
          "index_digest": "sha256:3ca8c974bc19040b7298abf40e6ab5d45c64d1560f42fe2288d1315fd4cfd7bb",
          "worktree_digest": "sha256:3ca8c974bc19040b7298abf40e6ab5d45c64d1560f42fe2288d1315fd4cfd7bb",
          "untracked_digest": "absent"
        },
        {
          "path": "core/context_budget.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c251a2d207c10db899aff227938fa98ff09a8f9aeb9edc3c6be97dedb364b849",
          "index_digest": "sha256:c251a2d207c10db899aff227938fa98ff09a8f9aeb9edc3c6be97dedb364b849",
          "worktree_digest": "sha256:c251a2d207c10db899aff227938fa98ff09a8f9aeb9edc3c6be97dedb364b849",
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
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b622f79f3ccfe09e162c3ff599a030f92ec7001bccba5c3c85e5355144767bbf",
          "index_digest": "sha256:b622f79f3ccfe09e162c3ff599a030f92ec7001bccba5c3c85e5355144767bbf",
          "worktree_digest": "sha256:502094c4dc7052c1a585aee06332d5d7d35cc48e421ea827d8b3222b8d9ac40a",
          "untracked_digest": "absent"
        },
        {
          "path": "core/planner.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b16e935370700c14d75e832968634a95bc77337b947212ed5c488851b39c4873",
          "index_digest": "sha256:b16e935370700c14d75e832968634a95bc77337b947212ed5c488851b39c4873",
          "worktree_digest": "sha256:b16e935370700c14d75e832968634a95bc77337b947212ed5c488851b39c4873",
          "untracked_digest": "absent"
        },
        {
          "path": "core/runtime/bridge.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "core/runtime/contracts.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "core/runtime/facade.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "core/runtime/turn_service.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "dashboard/package.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:516f1c81cd0ed984fab054796095ffd2aac2637c1668043bf83629655e5d903e",
          "index_digest": "sha256:516f1c81cd0ed984fab054796095ffd2aac2637c1668043bf83629655e5d903e",
          "worktree_digest": "sha256:516f1c81cd0ed984fab054796095ffd2aac2637c1668043bf83629655e5d903e",
          "untracked_digest": "absent"
        },
        {
          "path": "docker-compose.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:edd8054f3c860edbf2e6797794854476ba6ec35c4ca70284dbf9fd5b3abd5340",
          "index_digest": "sha256:edd8054f3c860edbf2e6797794854476ba6ec35c4ca70284dbf9fd5b3abd5340",
          "worktree_digest": "sha256:edd8054f3c860edbf2e6797794854476ba6ec35c4ca70284dbf9fd5b3abd5340",
          "untracked_digest": "absent"
        },
        {
          "path": "docs/architecture.md",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e58dd9b34348ac526ef89a7d231d7f9c2f72e7f74cc29f2c302ca93402ab45b8",
          "index_digest": "sha256:e58dd9b34348ac526ef89a7d231d7f9c2f72e7f74cc29f2c302ca93402ab45b8",
          "worktree_digest": "sha256:4b87d8da23483cf4a800e4473c11bcd9681f6aa91aac3862b3b3d5da2f1678aa",
          "untracked_digest": "absent"
        },
        {
          "path": "docs/migration/cortico/baseline-report.md",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "docs/migration/cortico/behavior-contract.md",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "docs/migration/cortico/compatibility-spike.md",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "docs/migration/cortico/feature-parity.md",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "extensions/__init__.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:eec183d6851067131d5167d534f811f0c6ce96d0bbae4259a50c50540161828a",
          "index_digest": "sha256:eec183d6851067131d5167d534f811f0c6ce96d0bbae4259a50c50540161828a",
          "worktree_digest": "sha256:eec183d6851067131d5167d534f811f0c6ce96d0bbae4259a50c50540161828a",
          "untracked_digest": "absent"
        },
        {
          "path": "extensions/link_monitor/__init__.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c4fecb4a9a24143065064153b61be65dffe88c57c0cd8357beaf4f8d8a6c3595",
          "index_digest": "sha256:c4fecb4a9a24143065064153b61be65dffe88c57c0cd8357beaf4f8d8a6c3595",
          "worktree_digest": "sha256:c4fecb4a9a24143065064153b61be65dffe88c57c0cd8357beaf4f8d8a6c3595",
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
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c725f8e42911a8bfcf4a951d4e29dd7f283c0644e6511f57e65b26d87d560d33",
          "index_digest": "sha256:c725f8e42911a8bfcf4a951d4e29dd7f283c0644e6511f57e65b26d87d560d33",
          "worktree_digest": "sha256:47f77377864959e6e1d4dc75ee8d50f1f96e3c3927f4ec0ff9d6381610a5650d",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/pre_processors.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c9ed86b5e52ca9c0d12c121039be66e6c4b955e3a4d2fd5935882c6d628c9940",
          "index_digest": "sha256:c9ed86b5e52ca9c0d12c121039be66e6c4b955e3a4d2fd5935882c6d628c9940",
          "worktree_digest": "sha256:cf5a22c54e5c799efec1bd2572e2cb237def5a35f15c8a2e10939701f519ff34",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/session_compact.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:71aff941c832c0a414a402cc6d75b75f679bbd7dd937da066372e62135b8c915",
          "index_digest": "sha256:71aff941c832c0a414a402cc6d75b75f679bbd7dd937da066372e62135b8c915",
          "worktree_digest": "sha256:ca308a266204763eb59053b3745b61d78bad6b5cd663dec2550ce53a20b76b96",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/session_context.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4508dcb1c8dfcc893fd2297198bdf65c0fad3a0300d4035f50e7182bb7d6ec46",
          "index_digest": "sha256:4508dcb1c8dfcc893fd2297198bdf65c0fad3a0300d4035f50e7182bb7d6ec46",
          "worktree_digest": "sha256:4508dcb1c8dfcc893fd2297198bdf65c0fad3a0300d4035f50e7182bb7d6ec46",
          "untracked_digest": "absent"
        },
        {
          "path": "openspec/openapi-v1.yaml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:bc554d488fea52ea292edf68d037a5206591e9a51183837df95a530dbde18566",
          "index_digest": "sha256:bc554d488fea52ea292edf68d037a5206591e9a51183837df95a530dbde18566",
          "worktree_digest": "sha256:bc554d488fea52ea292edf68d037a5206591e9a51183837df95a530dbde18566",
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
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:29e3ff6d72e13626e6a15d563f87e9addd9497738867ad744bd241117816e3e3",
          "index_digest": "sha256:29e3ff6d72e13626e6a15d563f87e9addd9497738867ad744bd241117816e3e3",
          "worktree_digest": "sha256:9e0d63e82aaef57ea3900a7059a6c320a235d268097556331c011f58e705b56c",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime/cortico/src/host.ts",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime/cortico/src/provider-bridge.ts",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime/cortico/src/stella-persona.ts",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime/cortico/src/turn-adapter.ts",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime/cortico/tests/host-lifecycle.test.ts",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime/cortico/tests/turn-compat.test.ts",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime/cortico/upstream-lock.json",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/build_offline_payload.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e82be87f37027c29b72b773ce62337d87c6f7d35ca5c409700b321d4c9a29eb4",
          "index_digest": "sha256:e82be87f37027c29b72b773ce62337d87c6f7d35ca5c409700b321d4c9a29eb4",
          "worktree_digest": "sha256:6b80ba164964e931f9db621f948af35c69ad12aebfd53da51c2982a753bef324",
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
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:8d6ee109a698fa9410f0e6479932df24db92a986297cc5e4aa313d8e9e8fc20d",
          "index_digest": "sha256:8d6ee109a698fa9410f0e6479932df24db92a986297cc5e4aa313d8e9e8fc20d",
          "worktree_digest": "sha256:1520ca31cc9efa187e3acc96ea528cbd541982934cf9d47bf01562bf1f47a377",
          "untracked_digest": "absent"
        },
        {
          "path": "stella_project/plugins/bot_main/scheduling/delivery.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3c3662e45d8fceecea65ad015733f78858c02a7a8b259ef06ebd2adfa602249f",
          "index_digest": "sha256:3c3662e45d8fceecea65ad015733f78858c02a7a8b259ef06ebd2adfa602249f",
          "worktree_digest": "sha256:3c3662e45d8fceecea65ad015733f78858c02a7a8b259ef06ebd2adfa602249f",
          "untracked_digest": "absent"
        },
        {
          "path": "stella_project/plugins/bot_main/scheduling/runtime.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4151e88bb1974a83851b6062ae539aa0e3338840b4607183c46af6cba369f501",
          "index_digest": "sha256:4151e88bb1974a83851b6062ae539aa0e3338840b4607183c46af6cba369f501",
          "worktree_digest": "sha256:4151e88bb1974a83851b6062ae539aa0e3338840b4607183c46af6cba369f501",
          "untracked_digest": "absent"
        },
        {
          "path": "stella_project/plugins/bot_main/status_api.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1c31cc9dadbb14df348e07e532a2aa47a7221234dfe20a7d5a0a87098b148ddb",
          "index_digest": "sha256:1c31cc9dadbb14df348e07e532a2aa47a7221234dfe20a7d5a0a87098b148ddb",
          "worktree_digest": "sha256:2f867820852fb670fc6e9a6bfc95d5e83c019d5401800286e03efcf6c7d8e513",
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
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:5e9c17a6f67e797480984165284bb6b0348ad36661969d4e48a62c62c090c5b3",
          "index_digest": "sha256:5e9c17a6f67e797480984165284bb6b0348ad36661969d4e48a62c62c090c5b3",
          "worktree_digest": "sha256:5e9c17a6f67e797480984165284bb6b0348ad36661969d4e48a62c62c090c5b3",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/runtime/test_behavior_parity.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/runtime/test_bridge_protocol.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/runtime/test_extension_compat.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/runtime/test_restart_recovery.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/runtime/test_session_ownership.py",
          "object_kind": {
            "head": "absent",
            "index": "absent",
            "worktree": "absent",
            "untracked": "absent"
          },
          "state": "absent",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "absent",
          "index_digest": "absent",
          "worktree_digest": "absent",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/scheduling/test_scheduling_delivery.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4ede262c889a537751748e837ed2850ad32d55ea70a2c959011ebb3aaf81d953",
          "index_digest": "sha256:4ede262c889a537751748e837ed2850ad32d55ea70a2c959011ebb3aaf81d953",
          "worktree_digest": "sha256:4ede262c889a537751748e837ed2850ad32d55ea70a2c959011ebb3aaf81d953",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_graceful_shutdown.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:bf286311b0ba46dab0e215eb8086ef558967fda5894f210cd4b9b0174282eb3f",
          "index_digest": "sha256:bf286311b0ba46dab0e215eb8086ef558967fda5894f210cd4b9b0174282eb3f",
          "worktree_digest": "sha256:bf286311b0ba46dab0e215eb8086ef558967fda5894f210cd4b9b0174282eb3f",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_pipeline_compose.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:cc9d6f54871db100107067f60833e3682dc8ae30daf64281949cd82faceb36a2",
          "index_digest": "sha256:cc9d6f54871db100107067f60833e3682dc8ae30daf64281949cd82faceb36a2",
          "worktree_digest": "sha256:5714b0bf23cb8d02942230ac3991dcec8e9a080fcc74cf213a824366cdf79658",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_planner.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a840745bc70e37eebf31c36cf2d56edd52600995507c003a42e5acca82f7b7db",
          "index_digest": "sha256:a840745bc70e37eebf31c36cf2d56edd52600995507c003a42e5acca82f7b7db",
          "worktree_digest": "sha256:4b441a3387c88e4c65fefe6eef28f700d3fb73dcd727b98a59c1dc78d11791c3",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_runtime_contract.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2068cea76e3d87b241a3bf0e18e302b108d2ed9586eb6eaef544b0485df922f0",
          "index_digest": "sha256:2068cea76e3d87b241a3bf0e18e302b108d2ed9586eb6eaef544b0485df922f0",
          "worktree_digest": "sha256:2068cea76e3d87b241a3bf0e18e302b108d2ed9586eb6eaef544b0485df922f0",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_session_compact.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e06e882faf89c06ddc76b8e7cf66539719453b1c158dc422048430947b015bd2",
          "index_digest": "sha256:e06e882faf89c06ddc76b8e7cf66539719453b1c158dc422048430947b015bd2",
          "worktree_digest": "sha256:e06e882faf89c06ddc76b8e7cf66539719453b1c158dc422048430947b015bd2",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_session_context.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c5c77eb943603de3b1d18e319529df6592ea63b85b60992610dc0e23ed25c0d7",
          "index_digest": "sha256:c5c77eb943603de3b1d18e319529df6592ea63b85b60992610dc0e23ed25c0d7",
          "worktree_digest": "sha256:c5c77eb943603de3b1d18e319529df6592ea63b85b60992610dc0e23ed25c0d7",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_session_context_cache.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:fb0daed74e7326fffaa745b5cacfe558b4bb5b853ce135798fe3e276df40b63a",
          "index_digest": "sha256:fb0daed74e7326fffaa745b5cacfe558b4bb5b853ce135798fe3e276df40b63a",
          "worktree_digest": "sha256:fb0daed74e7326fffaa745b5cacfe558b4bb5b853ce135798fe3e276df40b63a",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/webui/test_webui_chat.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:731b7e06f28008a370fca9aac76eba41925268b25301cbdfa1e7279d52a8d82a",
          "index_digest": "sha256:731b7e06f28008a370fca9aac76eba41925268b25301cbdfa1e7279d52a8d82a",
          "worktree_digest": "sha256:e0256a4e62f80b3f472b95cca873e7b9e1fa88e37e2a8cd2bc5c3d6203200b50",
          "untracked_digest": "absent"
        },
        {
          "path": "webui/chat_ingress.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a4325104b7b23b67baac6aafac70121afd8c69e3d4f1ab93d767fbb6d4a7a67f",
          "index_digest": "sha256:a4325104b7b23b67baac6aafac70121afd8c69e3d4f1ab93d767fbb6d4a7a67f",
          "worktree_digest": "sha256:8f59a5ca0961e041ac6188f09261403e6b0d8f6dd6d4242604a4dcf96e33d3bb",
          "untracked_digest": "absent"
        },
        {
          "path": "webui/routers/chat.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c2c7ae347f0764c2fef0d17946103bbbf0eb3f4eb445796bede35c049ec2a435",
          "index_digest": "sha256:c2c7ae347f0764c2fef0d17946103bbbf0eb3f4eb445796bede35c049ec2a435",
          "worktree_digest": "sha256:c2c7ae347f0764c2fef0d17946103bbbf0eb3f4eb445796bede35c049ec2a435",
          "untracked_digest": "absent"
        },
        {
          "path": "webui/services/runtime.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2090e62e299ef427cc7e84e3bc7483ccba0972cb5bbb5ea2540fa2d193c5ab5d",
          "index_digest": "sha256:2090e62e299ef427cc7e84e3bc7483ccba0972cb5bbb5ea2540fa2d193c5ab5d",
          "worktree_digest": "sha256:2090e62e299ef427cc7e84e3bc7483ccba0972cb5bbb5ea2540fa2d193c5ab5d",
          "untracked_digest": "absent"
        }
      ]
    },
    "primary_symbols": [
      {
        "symbol": "Pipeline.run",
        "file": "core/pipeline.py",
        "lines": "220-374",
        "role": "旧聊天编排与领域阶段提取"
      },
      {
        "symbol": "ChatContext",
        "file": "core/context.py",
        "lines": "1-180",
        "role": "Python领域上下文与JSON投影边界"
      },
      {
        "symbol": "activate_capabilities",
        "file": "capability/hooks.py",
        "lines": "328-387",
        "role": "能力hook与上下文回填"
      },
      {
        "symbol": "run_turn",
        "file": "webui/chat_ingress.py",
        "lines": "1-97",
        "role": "WebChat旧Pipeline入口"
      },
      {
        "symbol": "SchedulerRuntime",
        "file": "stella_project/plugins/bot_main/scheduling/runtime.py",
        "lines": "58-117",
        "role": "调度租约和生命周期"
      }
    ],
    "related_symbols": [
      {
        "symbol": "handle_chat",
        "relationship": "CALLS",
        "relevance": "QQ被动入口"
      },
      {
        "symbol": "_proactive_at_user",
        "relationship": "CALLS",
        "relevance": "主动@，reply trigger但proactive_at intent"
      },
      {
        "symbol": "_proactive_speak_for_group",
        "relationship": "CALLS",
        "relevance": "主动话题入口"
      },
      {
        "symbol": "fit_prompt_to_window",
        "relationship": "CALLS",
        "relevance": "实际provider前的预算裁剪"
      },
      {
        "symbol": "load_extensions",
        "relationship": "CALLS",
        "relevance": "setup(pipeline)兼容"
      },
      {
        "symbol": "parse_output",
        "relationship": "hook",
        "relevance": "原输出解析"
      },
      {
        "symbol": "bad_phrase_filter",
        "relationship": "hook",
        "relevance": "过滤语义"
      },
      {
        "symbol": "split_lines",
        "relationship": "hook",
        "relevance": "分行与兜底"
      },
      {
        "symbol": "LLMBackend.generate",
        "relationship": "CALLS",
        "relevance": "provider薄桥目标，避免完整Pipeline调用"
      }
    ],
    "execution_path": [
      "入口筛选/锁/预算",
      "ChatContext与pre hooks",
      "能力和可选Planner短路",
      "人格+记忆prompt+预算裁剪",
      "原LLM gate与生成",
      "原条件后处理",
      "入口记录与平台投递"
    ],
    "pdg_constraints": [
      {
        "description": "WAIT早退不能兜底",
        "affected_statements": [
          "core/pipeline.py:248",
          "core/pipeline.py:251",
          "stella_project/plugins/bot_main/ai_gateway.py:596"
        ],
        "implementation_consequence": "typed silent与empty/failure分离"
      },
      {
        "description": "最终prompt裁剪后才generate",
        "affected_statements": [
          "core/pipeline.py:266",
          "core/pipeline.py:281",
          "core/pipeline.py:303",
          "core/pipeline.py:322"
        ],
        "implementation_consequence": "Core容量检查与实际provider使用同一投影"
      },
      {
        "description": "预算与分行发送条件",
        "affected_statements": [
          "stella_project/plugins/bot_main/ai_gateway.py:576",
          "stella_project/plugins/bot_main/ai_gateway.py:639",
          "stella_project/plugins/bot_main/ai_gateway.py:643"
        ],
        "implementation_consequence": "保留门禁、首行引用、末行finish及旧副作用顺序"
      }
    ],
    "architectural_patterns": [
      {
        "pattern": "按群互斥和共享空间独立语义",
        "example_location": "stella_project/plugins/bot_main/ai_gateway.py:520",
        "usage_guidance": "conversation key不能等同shared space"
      },
      {
        "pattern": "hook注册扩展",
        "example_location": "extensions/__init__.py",
        "usage_guidance": "兼容setup(pipeline)，执行由新runtime负责"
      },
      {
        "pattern": "持久业务调度与投递状态",
        "example_location": "stella_project/plugins/bot_main/scheduling/runtime.py",
        "usage_guidance": "保留lease，UNKNOWN不自动重发"
      }
    ],
    "files_to_modify": [
      {
        "file": "core/pipeline.py",
        "symbols": [
          "Pipeline.run"
        ],
        "intended_change": "提取共享业务阶段，最终退役旧运行循环"
      },
      {
        "file": "core/context.py",
        "symbols": [
          "ChatContext"
        ],
        "intended_change": "保留语义并建立JSON投影"
      },
      {
        "file": "core/runtime/turn_service.py",
        "symbols": [
          "prepare_turn (proposed)",
          "generate_reply (proposed)",
          "finalize_turn (proposed)"
        ],
        "intended_change": "新增阶段服务"
      },
      {
        "file": "core/runtime/facade.py",
        "symbols": [
          "RuntimeFacade (proposed)"
        ],
        "intended_change": "统一入口owner和切换"
      },
      {
        "file": "core/runtime/bridge.py",
        "symbols": [],
        "intended_change": "双向stdio协议和取消"
      },
      {
        "file": "core/runtime/contracts.py",
        "symbols": [],
        "intended_change": "版本化协议"
      },
      {
        "file": "runtime/cortico/src/host.ts",
        "symbols": [],
        "intended_change": "Core host进程及会话注册"
      },
      {
        "file": "runtime/cortico/src/turn-adapter.ts",
        "symbols": [],
        "intended_change": "generate/direct/silent/failure映射"
      },
      {
        "file": "runtime/cortico/src/provider-bridge.ts",
        "symbols": [],
        "intended_change": "ResponseClient薄桥"
      },
      {
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "symbols": [
          "handle_chat",
          "_proactive_at_user",
          "_proactive_speak_for_group"
        ],
        "intended_change": "QQ与主动入口"
      },
      {
        "file": "webui/chat_ingress.py",
        "symbols": [
          "run_turn"
        ],
        "intended_change": "WebChat入口"
      },
      {
        "file": "webui/routers/chat.py",
        "symbols": [],
        "intended_change": "SSE/reset保持兼容"
      },
      {
        "file": "stella_project/plugins/bot_main/scheduling/runtime.py",
        "symbols": [
          "SchedulerRuntime"
        ],
        "intended_change": "统一owner但保留调度存储"
      },
      {
        "file": "bot.py",
        "symbols": [],
        "intended_change": "supervisor启动关闭"
      },
      {
        "file": "Dockerfile",
        "symbols": [],
        "intended_change": "Node与编译产物发行"
      },
      {
        "file": ".github/workflows/ci.yml",
        "symbols": [],
        "intended_change": "新runtime验证"
      },
      {
        "file": ".github/workflows/release.yml",
        "symbols": [],
        "intended_change": "完整发行渠道"
      }
    ],
    "tests": [
      {
        "file": "tests/test_pipeline_compose.py",
        "scenarios": [
          "普通1次",
          "工具直回0次",
          "prompt投影和工具事实"
        ]
      },
      {
        "file": "tests/test_planner.py",
        "scenarios": [
          "WAIT条件",
          "模型调用上限",
          "预算"
        ]
      },
      {
        "file": "tests/webui/test_webui_chat.py",
        "scenarios": [
          "空间隔离",
          "SSE",
          "reset",
          "鉴权",
          "standalone错误"
        ]
      },
      {
        "file": "tests/scheduling/test_scheduling_delivery.py",
        "scenarios": [
          "receipt可选",
          "UNKNOWN不重发",
          "silent"
        ]
      },
      {
        "file": "tests/runtime/test_behavior_parity.py",
        "scenarios": [
          "旧fixture→新runtime→规范化trace一致"
        ]
      },
      {
        "file": "tests/runtime/test_bridge_protocol.py",
        "scenarios": [
          "取消/断管/迟到→有界失败且无副作用"
        ]
      },
      {
        "file": "tests/runtime/test_session_ownership.py",
        "scenarios": [
          "同群竞争→唯一owner",
          "异群隔离",
          "epoch切换拒旧owner"
        ]
      },
      {
        "file": "tests/runtime/test_restart_recovery.py",
        "scenarios": [
          "副作用各阶段崩溃→不盲目重放"
        ]
      },
      {
        "file": "tests/runtime/test_extension_compat.py",
        "scenarios": [
          "setup/hook优先级/backend替换兼容"
        ]
      },
      {
        "file": "runtime/cortico/tests/turn-compat.test.ts",
        "scenarios": [
          "实际Core direct/silent/prompt/capacity兼容"
        ]
      },
      {
        "file": "runtime/cortico/tests/host-lifecycle.test.ts",
        "scenarios": [
          "multi-core/idle/drain/cancel/shutdown"
        ]
      }
    ],
    "verification_commands": [
      "python -m pytest tests/test_pipeline_compose.py tests/test_planner.py tests/capability/test_capability_hooks.py tests/webui/test_webui_chat.py tests/scheduling/test_scheduling_delivery.py -q",
      "python -m pytest tests/ -v --cov=. --cov-branch --cov-report=xml -n auto --dist loadgroup --timeout=120 --timeout-method=thread",
      "python -m pytest tests/windows -q --junitxml=windows-native.xml",
      "ruff check . --output-format=github",
      "pnpm --dir dashboard install --frozen-lockfile",
      "pnpm --dir dashboard build",
      "docker exec -w /repo stella-gitnexus gitnexus detect-changes --scope all --repo ."
    ],
    "risks": [
      "整体HIGH工程风险；不是局部图risk",
      "Pipeline lower-bound及capability UNKNOWN",
      "公开Cortico接口未直接满足零生成/精确历史",
      "跨语言双锁和未知副作用",
      "发行与资源增加"
    ],
    "assumptions": [
      "A1 per-conversation Core: M0规模清单+M1 1/20/100会话测量，失败不能合群",
      "A2 public API/minimal generic patch: M1实际Core兼容测试，失败阻断迁移",
      "A3 headless packaging: M1依赖闭包+M8 Windows离线/Docker实际产物",
      "A4 stdio bridge: M1/M3 Windows framing、双向背压、取消和锁验证",
      "A5 plugin boundary: M0查现有公开接口使用和部署扩展，私有接口不虚构保证"
    ],
    "open_questions": [
      "Q1原有失败与怪异行为默认保留另开修复",
      "Q2补丁范围和资源预算在M1凭测量收敛",
      "Q3M9覆盖完整业务周期后退役旧引擎，保留旧发行包回退资料"
    ],
    "avoid": [
      "Do not repeat full repository discovery",
      "Do not replace established patterns without evidence",
      "不实现Coding Agent/子Agent执行器/新自治目标",
      "不把完整Pipeline.run包在Core内作为最终实现",
      "不双写真实副作用或超时后同事件自动转legacy",
      "不将所有群共享一个Core主会话",
      "不以Core日志追加第二份prompt历史",
      "不直接改写用户记忆库或以备份覆盖迁移后数据",
      "不为通过验收覆盖旧行为oracle",
      "不把UNKNOWN或截断当安全证明"
    ],
    "upstream_pin": {
      "repository": "https://github.com/Pal-AI-Lab/Cortico",
      "commit": "bc47c824d388345f1c13722f4a05a5f745a028f8",
      "version": "0.1.4",
      "private": true,
      "node": ">=22",
      "pnpm": "11.5.0",
      "policy": "immutable vendor snapshot + verified minimal generic patches"
    },
    "graph_index": {
      "indexed_at": "2026-09-27T00:12:46.017Z",
      "version": "1.6.11",
      "pdg": true,
      "runner_build_digest": "sha256:9faaea7491d7a9f1955c300305fb7a21a14f44196981c249bf1c9a905083c4bc",
      "limitations": [
        "receiver/property unresolved",
        "cross-language gaps",
        "process walk caps; not full coverage"
      ]
    },
    "stage_order": [
      "M0 contracts",
      "M1 blocking compatibility spike",
      "M2 domain extraction",
      "M3 bridge/core",
      "M4 passive ingress",
      "M5 domain/plugins",
      "M6 proactive/scheduling",
      "M7 lifecycle/UI",
      "M8 packaging/rollback",
      "M9 switch/retire"
    ],
    "planned_commands_not_yet_available": [
      "pnpm --dir runtime/cortico install --frozen-lockfile",
      "pnpm --dir runtime/cortico typecheck",
      "pnpm --dir runtime/cortico test",
      "pnpm --dir runtime/cortico build"
    ]
  }
}
```

## 12. Assumptions and Open Questions

这些问题安排在实施阶段验证，目前不需要用户补充材料才能使用本计划。

| ID | 假设／未决项 | 验证与失败处理 |
| --- | --- | --- |
| A1 | [assumed] 单Node host、每逻辑会话一个懒加载Core足够支撑现有规模 | M0量化实际会话规模；M1测1/20/100会话与idle回收；失败先优化或修订分片方案，禁止直接合群 |
| A2 | [assumed] 公开API或有限通用补丁可保证direct/silent、精确prompt与终结顺序 | M1使用实际Core测试；失败阻断后续迁移，不退化为旧Pipeline套壳 |
| A3 | [assumed] headless快照可在当前Windows离线及Docker发行内合理打包 | M1验证依赖闭包；M8验真实产物；失败必须调整依赖/打包设计 |
| A4 | [assumed] 双向stdio桥能满足原始事件handle和当前并发要求 | M1/M3验证Windows framing、背压、取消、无锁重入；不满足时重新选择本地IPC并补同等测试 |
| A5 | [assumed] 仓库内可见插件覆盖主要兼容需求 | M0记录公开接口及当前部署插件；未知第三方私有接口不虚构保证，保持兼容层并记录确切边界 |
| Q1 | M0发现的现有失败/怪异行为是否应修复 | 默认保留并记录，另开修复项；不能把修复混入迁移且改变兼容基准 |
| Q2 | 上游补丁可接受的维护规模与资源预算是否需调整 | M1给出具体文件、测试、测量；无法解释的扩大意味着设计未通过，而非自动批准 |
| Q3 | 最终旧引擎撤除与回退窗口 | M9退出前需完整业务周期和M8演练；旧发行包保留，迁移结束不长期运行双核心 |

明确后置：Codex/Coding Agent接入、子Agent委派与结果回收、代码工作区/权限模型、新的长期目标自治策略、对记忆系统的功能升级。后续计划可以使用本次统一runtime接口，但本次不提前实现这些功能。

## 13. Definition of Done

- [ ] M0功能清单逐项通过；所有原入口、配置、API和发行渠道都有验证记录，无“未检查但估计兼容”。
- [ ] Cortico使用固定真实源码；运行trace表明它负责轮次生命周期；所有生产聊天生成入口不再使用旧Pipeline编排。
- [ ] direct0次、普通1次及Planner原有上限成立；WAIT/预算静默、prompt/人格/历史边界、后处理和投递契约一致。
- [ ] QQ、WebChat、主动发言、当前定时reminder/agent、记忆/知识/Skills/Comes/MCP、扩展与UI功能全部保留。
- [ ] 同会话单owner、跨会话隔离、reset、取消、崩溃、重启、关闭与未知副作用的恢复测试通过；无重复发送/工具执行。
- [ ] 原有数据不丢失；新旧存储边界明确；升级/回退演练通过且不覆盖迁移后用户数据。
- [ ] Windows、离线、Docker及原有启动链真实产物通过；性能和资源预算通过或有明确测量支持的修订。
- [ ] 相关现有测试与新增测试通过；全量CI、必要前端/Rust构建通过；GitNexus提交检查无未处理partial/truncated。
- [ ] 旧引擎退役、兼容facade责任明确；架构、补丁维护、部署、诊断与回退文档完成。
- [ ] 没有引入Coding Agent、子Agent执行器或新增自主行为；这些另立计划。

### R.5 切换与退役清单（M9，待负责人实测后执行）

前置：负责人按「一并实测」完成真实部署下的 native 模式验证（QQ @对话 / WebChat / 主动 @ / 主动插话 / 定时任务）。

切换步骤（每步可独立回退）：
1. `STELLA_RUNTIME=native` 灰度运行（.env，重启生效）→ 观察 `/stella/status` 的 `chat_engine` 与 `logs`。
2. 全量测试 + oracle 逐字节复核（`pytest tests/runtime/test_legacy_reference_traces.py`）。
3. 默认切换：config/settings.py `RUNTIME_MODE` 默认值 legacy→native，`RUNTIME_MODE` 注释与 .env.example 同步。
4. 实机再验证一个完整调度周期（含到期补跑/投递/UNKNOWN）。

退役步骤（确认稳定后）：
- 删除 ai_gateway `_run_turn_via_engine` 的 legacy 分支与 `pipeline.run` 编排路径、`webui/chat_ingress` 的 legacy 分支；
- `core/pipeline.py` 保留为兼容 facade（钩子注册面），删除其内不再可达的 legacy 分支语义；
- 保留：M0 oracle、behavior-contract、`tests/runtime/`（基准永不过期）。

回退触发（任一即切回 `STELLA_RUNTIME=legacy` 并告警）：重复发送、串空间/串会话、丢任务、调用次数异常增加、未解释的 prompt 差异、预算静默缺失。

### R.6 退役执行记录（2026-09-27）

§R.5 退役步骤已执行：`_run_turn_via_engine` 的 legacy 分支、`chat_ingress` 的 legacy 分支与 `RUNTIME_MODE` 双路开关（settings/env.example/conftest 钉子）全部删除；`pipeline.py` 保留为 TurnService 兼容门面（钩子注册面）。唯一引擎 = facade；用户 `.env` 中残留的 `STELLA_RUNTIME=native` 键无害（不再被读取）。迁移至此**全部完成**。
