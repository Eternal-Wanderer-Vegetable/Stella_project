# Cometa 外部 Agent 任务运行层实施方案 v1.0

> 状态：待实施；本次仅存档设计，不表示功能已经落地。
> 日期：2026-09-30。
> 目标：Stella 按需委派 Codex 等外部 Agent，持续回报运行状态，并可靠交付结果。
> 源码基线：`bda9af928207c2901d873b87999f8fc18cc334d5`，起草前工作树干净。
> GitNexus：1.6.12；当前项目独立索引已执行 `analyze --index-only --pdg`，67,820 nodes / 162,614 edges / 750 flows。执行流构建存在截断，不能把图中没有的调用视为不存在。
> 存档位置遵循用户要求：`design_docs`。本文采用项目设计文档格式；不是 `docs/plans` 下带标准 schema-2 provenance 的可直接执行计划。实施前须重新核验基线，对实际修改符号运行 impact，提交前运行 detect_changes。

证据标记：`[verified]` 为当前源码核验；`[graph]` 为本次图分析；`[inferred]` 为基于证据的设计推论；`[assumed]` 为实施时必须验证的假设。第 6 节及新增路径均为设计提案，不代表现有代码。

## 1. 目标与验收范围

### 1.1 四项目标

1. Stella 在缺少适合的能力、任务需要长期执行，或用户明确指定时，创建外部 Agent 任务。
2. 长程任务执行期间，Stella 能向原请求者回报阶段、最近活动、等待输入、失败和完成状态，同时继续正常聊天。
3. 返回有依据的最终结果和可访问产物，保留部分完成、测试失败、结果未验证等事实。
4. 调度、存储、权限、通知和结果协议独立于 Codex；新增编程 Agent 通过适配器接入。

### 1.2 产品边界

- Stella 负责用户入口、能力判断和对外表达。
- Comes 继续执行当前轮次内的有界工具任务。
- cometa 管理跨轮次任务的受理、执行、输入、恢复、取消、结果和投递。
- AgentBackend 负责与具体 Agent 的 SDK / CLI / 协议交互。
- 首版支持单机 Windows / Linux、本地 Codex、QQ 群请求及 WebChat；QQ 私聊只预留地址类型，不承诺首版支持。
- 首版每个用户请求最多创建一个顶层任务；复合目标交给一个执行后端处理。跨 Agent DAG、递归委派和自动合并代码不在首版范围。
- 第二个真实后端属于完整项目验收阶段；只有 FakeBackend 通过测试不能证明已支持多种编程 Agent。

### 1.3 关键不变量

1. 先持久化任务，再启动 Agent；只有落库成功才返回 accepted。
2. accepted、running、succeeded 和消息 sent 是不同事实。
3. 聊天轮次结束不等于后台任务结束；后台任务不能持有聊天锁或占用 CHAT 模型闸门。
4. 任务所有者、原始会话和授权来自入口，不由模型生成。
5. 执行状态不明时先核对，不能把重启或网络错误解释成可以重跑。
6. 用户可见进度有真实事件依据；没有可衡量总量时不生成百分比或预计完成时间。
7. Agent 自述“完成”不能覆盖失败的命令、测试或验收记录。
8. 完整日志和文件不塞入 Stella 的聊天上下文；只传有界摘要和产物引用。

## 2. 现有行为与准确接入点

| 当前模块 | 已核验行为 | 对 cometa 的约束 |
| --- | --- | --- |
| `capability/hooks.py:328` / `activate_capabilities` | `[verified]` Router 判定后，将 Memory、Comes、Skills 放入 gather；分支异常隔离 | 委派选择必须在有副作用的分支执行前完成，不能让 Comes、Skills 和外部 Agent 重复执行同一目标 |
| `capability/hooks.py:171` / `_run_comes` | `[verified]` 等待 execute_all，再回写 task_results / tool_summaries | 新增的委派分支只能等受理回执，不能等 Agent 最终结果 |
| `capability/hooks.py:304` / `_build_astr_event` | `[verified]` 要求 raw_event、bot 与 AstrBot 兼容层可用 | cometa 不依赖 AstrMessageEvent，不为 WebChat 伪造 QQ 事件 |
| `core/runtime/turn_service.py:273` / `prepare_turn` | `[verified]` 先执行前置钩子；ctx.reply 非空时返回 DIRECT | 受理确认可通过 ctx.reply / ctx.lines 确定性直回，不需要再调 CHAT 模型 |
| `core/runtime/facade.py:195` / `submit_turn` | `[verified]` prepare 在 per-key lock 内；约 257 行的 wait_for 仅包住生成 provider | 120 秒默认值不是整轮超时；不能通过增大它实现长程执行 |
| `core/tasks.py:33`、`:106` | `[verified]` 任务号为进程内计数；Result 分离 data 与 summary | cometa 使用持久 UUID；独立 SubmissionReceipt / AgentResult，不把排队伪装为 Result.SUCCESS |
| `core/context.py:98`、`:154` | `[verified]` 上下文已有工具/技能摘要；JSON 投影是显式白名单 | 新字段默认空，身份信任信息不进 prompt，也不经通用投影恢复成授权 |
| `stella_project/plugins/bot_main/ai_gateway.py:608` | `[verified]` handle_chat 在群锁内构建 ctx 并执行轮次 | 入口构建可信 Origin；受理后尽快释放锁，任务通知只在发送时短暂取锁 |
| `webui/chat_ingress.py:26`、`:66` | `[verified]` 固定 WebChat 用户和负群号，有独立 key/lock；msg_id 为 0 | 不使用 msg_id=0 作为幂等键；由 HTTP 客户端请求 ID 标识提交 |
| `stella_project/plugins/bot_main/scheduling/migrations.py:46` | `[verified]` 独立 SQLite、WAL、busy_timeout；迁移失败停用功能 | 借鉴独立库和迁移模式，不向记忆库或调度库塞 cometa 表 |
| `stella_project/plugins/bot_main/scheduling/delivery.py:124` | `[verified]` 结果落库 → CAS sending → 发送 → 回执；异常视为 delivery_unknown | 复用设计原则，首版不改写现有 DeliveryService 的调度专用类型 |
| `stella_project/plugins/bot_main/ai_gateway.py:1682`、`:2720` | `[verified]` 调度栈装配与有界 shutdown 已有接入模式 | cometa 单独装配，不侵入 SchedulerRuntime 的 Cron 执行循环 |
| `config/settings.py:58`、`:290` | `[verified]` 用户数据以 STELLA_HOME 为根，运行目录按实例定位 | 任务、配置和产物不能写进随升级替换的程序目录 |
| `webui/app.py:78`、`webui/routers/manage.py:20` | `[verified]` 管理 API 使用 require_auth，API 注册在静态路由前 | 新路由保持鉴权、响应 envelope 和审计习惯 |
| `webui/security.py:10` | `[verified]` WebUI 当前是单管理员模型 | 不虚构多租户 RBAC；WebUI 管理员与 QQ 请求者的授权分别处理 |

**对上一轮概述的修正：** 默认 120 秒限制的是生成阶段。cometa 必须从前置钩子的等待路径和会话锁中脱离，而不是只调整 timeout。

## 3. 总体架构与依赖方向

```text
QQ / WebChat
  └─ 可信 Origin + 原始用户请求
      └─ capability：委派策略 / 常规工具路由
          ├─ 原有 Memory / Comes / Skills
          └─ CometaService.submit → SQLite 提交 → SubmissionReceipt
                                      │
                         独立 cometa worker 认领
                                      │
                         BackendRegistry → AgentBackend
                                      │
                         Codex SDK / App Server
                                      │
                         统一事件、结果、产物落库
                                      │
                         Bot 内 DeliveryPump → 原请求者
                         WebUI 查询 / 事件流 / 下载
```

### 3.1 进程模型

- Bot 进程：持有 CometaService、只读/短事务仓储、后台通知投递器和 WorkerSupervisor。
- worker 进程：通过 `python -m cometa.worker` 运行，不导入 NoneBot gateway；认领任务、管理 Agent 子进程、写事件与结果。
- Agent 子进程：由后端适配器管理；首版每个活动任务使用独立会话/受控连接，限制并发。
- 进程间任务和控制命令通过单机 SQLite 队列传递；首版无需 Redis、消息总线或额外公开端口。
- asyncio.to_thread 只用于短数据库/文件操作，不承担长程任务生命周期；取消等待线程不能被当成事务已回滚。
- WorkerSupervisor 只管理自己启动且身份核验一致的进程，不按进程名扫描并结束其他 Codex。

独立 worker 提供故障隔离，不承诺 Bot 关闭期间所有执行继续运行。首版采用受控关闭与下次启动核对恢复，见 §6.8。

### 3.2 模块结构（全部为拟新增）

```text
cometa/
  __init__.py                # 无运行时副作用
  models.py                  # Origin、TaskSpec、Receipt、Snapshot、Event、Result
  config.py                  # typed 配置、profile、后端配置加载
  migrations.py              # cometa 库 schema 与版本门禁
  store.py                   # 短事务、CAS、租约、事件游标、outbox
  service.py                 # 用户授权、提交幂等、查询、输入、取消
  policy.py                  # 能力、配额、工作区和委派可行性
  runtime.py                 # Bot 进程服务定位、装配、关闭
  supervisor.py              # worker 启停、进程身份与健康检查
  worker.py                  # 独立进程入口与任务调度
  executor.py                # attempt 生命周期、事件归一与恢复
  workspace.py               # 工作区/worktree 准备、锁和保留
  artifacts.py               # 产物收集、内容校验、manifest
  delivery.py                # outbox、节流、回执与平台 Sender 协议
  presentation.py            # 有界、确定性的状态与结果表达
  backends/
    base.py                  # AgentBackend 协议与能力声明
    registry.py              # 显式注册、可用性与版本快照
    codex.py                 # Codex 适配；SDK 优先
    codex_events.py          # 原始事件 → AgentEvent
capability/delegation.py     # 聊天请求 → 委派意图；不启动子进程
stella_project/plugins/bot_main/cometa_bridge.py
                              # QQ Origin、命令、Sender、生命周期桥
webui/routers/cometa.py       # API 与 SSE
webui/services/cometa.py      # 获取服务、DTO、错误映射
dashboard/src/views/CometaPage.vue
dashboard/src/api/cometa.ts
tests/cometa/                 # FakeBackend、故障注入与协议契约
```

依赖方向：入口/能力层 → cometa.service → store/policy；worker → executor → backend。cometa 内核不得 import ai_gateway、ChatContext 或聊天人格。cometa 不注册成一个会阻塞 Comes 的长时间 FunctionTool。

新增类/方法名均为计划命名。不要把本文的拟新增符号当成可查询的现有符号。

## 4. GitNexus 发现与改动风险

分析绑定 `E:\stella\stella_project`。项目默认 runner 存在本机 pnpm 路径问题；本次使用已安装的 GitNexus 1.6.12 CLI，独立索引位于 `C:\Users\Vegetable\.cache\gitnexus-cometa`。未修改默认 runner 或旧索引中的 `/repo` 元数据。

| 查询 | 返回事实 | 实施影响 |
| --- | --- | --- |
| context `_run_comes` | `[graph]` activate_capabilities 调用它；它调用 execute_all、事件构造与直回处理 | 新增委派分支与旧 Comes 分支分离 |
| impact `activate_capabilities` upstream depth=3 include-tests | `[graph]` HIGH；23 个 d=1 依赖，均在 test_capability_hooks.py | 高风险警告：保留旧分支行为、关闭功能时零回归 |
| impact `ChatContext` upstream depth=1 include-tests | `[graph]` HIGH；24 个 d=1 import 依赖 | 新字段必须有默认值；不得改变既有字段语义和授权边界 |
| impact `RuntimeFacade.submit_turn` upstream depth=3 include-tests | `[graph]` MEDIUM；12 个 d=1 调用点 | 首版不改它；用回归测试保护会话锁、reset、DIRECT/SILENT |
| impact `DeliveryService` upstream depth=3 include-tests | `[graph]` LOW；4 个 d=1、13 个总影响项 | 借鉴投递状态机；不直接泛化调度库与 DeliveryService |

### 4.1 d=1 依赖覆盖决策

- activate_capabilities 的 23 个直接测试覆盖：Memory 门控、Router 传参/失败、Comes 启停/缺事件、确定性成功/澄清/失败、两分支并发和失败隔离、Skills 关闭/无运行时/浏览/沙盒/失败。保留全部断言，新增委派分支测试，不重写旧 oracle。
- submit_turn 的 12 个调用点分布于 `tests/runtime/test_facade_turns.py`（6）、`test_session_ownership.py`（4）、`test_proactive_native.py`（2）：保持原 API；检查长任务不进入 provider 等待，旧 reset 语义不被扩大成取消所有后台任务。
- DeliveryService 的 4 个直接依赖为 ai_gateway、scheduling/runtime、`tests/scheduling/test_scheduling_delivery.py`、`test_scheduling_runtime.py`：全部保持现行接口，仅作为模式与回归参照。
- ChatContext 的 24 个直接依赖逐项归组如下，实施时不得遗漏：
  - 生产：`capability/hooks.py`、`core/planner.py`、`core/runtime/facade.py`、`core/runtime/turn_service.py`、`memory/post_processors.py`、`memory/pre_processors.py`、`stella_project/plugins/bot_main/ai_gateway.py`、`webui/chat_ingress.py`。
  - 测试：`tests/capability/test_capability_hooks.py`、`tests/knowledge/test_isolation.py`、`tests/runtime/legacy_harness.py`、`tests/runtime/runtime_harness.py`、`tests/runtime/test_facade_turns.py`、`tests/runtime/test_turn_service.py`、`tests/test_ai_gateway_deterministic_reply.py`、`tests/test_bot_self_source.py`、`tests/test_context_tail.py`、`tests/test_full_workflow.py`、`tests/test_jargon_service.py`、`tests/test_pipeline_compose.py`、`tests/test_planner.py`、`tests/test_proactive_at_flow.py`、`tests/test_session_context_cache.py`、`tests/test_short_term_attribution.py`。
  - 处理：入口填充新字段；其他构造器继续使用默认空值；不把 Origin 加入通用 JSON 投影；只新增对委派字段的定向断言。

图中的 affected_processes 为空不代表没有生产调用。钩子注册、动态 dispatch 和生成流程的截断均限制了覆盖；源码中的 `register_pre_hook` 和实际入口调用具有更高证据权重。

## 5. 语句级 PDG 与顺序约束

本次补建 PDG 后使用 `impact --mode pdg`，两个切片均曾在 depth=3 截断；改为 depth=12 后不再报告 truncated。两者 risk 仍是 UNKNOWN，不能作为低风险判据。以下控制结论已对照源码，不声称跨进程依赖由 PDG 证明。

### 5.1 能力钩子

- 查询锚点：`capability/hooks.py:377`，activate_capabilities，upstream。
- `[graph]` 返回 328、337、340、342、346、372 行，涉及路由/降级、ctx.route 和 jobs 空判断。
- `[verified]` 352 行决定 Memory，361 行决定 Comes，368 行决定 Skills，377 行等待全部分支。
- `[inferred]` 委派选择在 360 行之前决定任务所有权。提交协程只执行鉴权和短事务；不能将 stream/run 放入 gather。
- `[verified]` 419 行通过 register_pre_hook 注册；UNKNOWN 和空生产 caller 集已由此源码确认，不能认定钩子未使用。

### 5.2 投递事务

- 查询锚点：`stella_project/plugins/bot_main/scheduling/delivery.py:145`，deliver，upstream。
- `[graph]` 返回 90、99、112、124、125、128、136 行；跨函数部分是 callgraph bridge，不是纯语句级证据。
- `[verified]` 128 行保存结果并转 ready；136 行先转 sending；145 行调用外部 sender；异常进入 unknown；154 行记录回执。
- `[inferred]` cometa 的结果提交和通知入队需同事务；投递必须在平台调用前保存 sending，不能以发送后的标记去重。
- `[verified]` scheduling/runtime.py:280、342 调用 delivery.deliver，确认存在生产路径。

### 5.3 聊天锁与确认

- `[verified]` RuntimeFacade.submit_turn 在会话锁内执行 prepare，再检查 epoch；生成调用另外包 timeout。
- `[inferred]` cometa 一旦提交事务成功，任务独立存在；聊天 reset 不撤销已受理任务，也不能借聊天 epoch 自动重放任务。
- 查询/取消等显式 cometa 命令应走有界服务接口，不等待任务持有的锁。

## 6. 拟实施设计

### 6.1 公共协议

所有持久 DTO 带 `schema_version=1`。任务和 attempt 使用 UUID；展示短 ID 只供人阅读，短 ID 冲突必须返回候选或要求完整 ID。

| 类型 | 必需字段 |
| --- | --- |
| Origin | instance_id、platform、bot_id、conversation_id、requester_id、source_request_id、reply_to_message_id、conversation_generation |
| TaskSpec | objective、context_excerpt、required_capabilities、backend_preference、workspace_id、permission_profile、acceptance_criteria、limits |
| SubmissionReceipt | task_id、accepted_at、state、backend_selection_state、ack_notification_id |
| TaskSnapshot | task_id、state、backend_id、attempt_id、phase、last_activity_at、heartbeat_at、waiting_request、result_ref、delivery_state |
| AgentEvent | schema_version、task_id、attempt_id、sequence、backend_event_id（可空）、kind、occurred_at、payload |
| AgentResult | outcome、summary、final_text_ref、artifacts、evidence、verification_status、limitations、error、usage |

Origin 只由 QQ / WebChat 入口构造。它来自受信宿主，不是可接受用户任意提交的 JSON。服务层再核验 profile 与用户的绑定。长文本输出、原始事件和异常堆栈不作为身份依据。

CometaService 拟公开：

```python
submit(spec, *, actor, origin, idempotency_key) -> SubmissionReceipt
get(task_id, *, actor) -> TaskSnapshot
list_tasks(*, actor, cursor=None) -> TaskPage
events(task_id, *, actor, after_sequence=0) -> EventPage
respond(task_id, request_id, answer, *, actor, expected_revision) -> ControlReceipt
cancel(task_id, *, actor, idempotency_key) -> ControlReceipt
result(task_id, *, actor) -> AgentResult
```

`actor` 为入口确定的主体；Backend 不接触 actor 的认证凭据。cancel 返回“已请求取消”，不能提前返回“已取消”。respond 的 answer 使用各请求的校验 schema；只有 request_id 对应的请求能消费答复。

### 6.2 状态与时间语义

```text
queued → starting → running → succeeded | partial | failed
                     ↕
           waiting_input / waiting_approval

queued → cancelled
starting/running/waiting_* → cancelling → cancelled
starting/running/waiting_* → recovering → running / waiting_* / recovery_required
任一未完成任务到达预算/期限 → cancelling → timed_out（确认停止后）
```

- `recovery_required`：系统无法确认是否仍在执行或能否安全恢复，等待管理员处理，不等同失败后可重跑。
- `succeeded` 表示验收标准满足；`partial` 表示有可用产物但目标未全部完成；没有可用产物且失败则 failed。
- 后端 turn completed 映射为“待结果校验”，由 executor 校验后转业务终态。
- 数据库保存 UTC 时间和绝对 deadline；进程内延时使用 monotonic。等待输入有单独上限，但计入整个任务的墙钟期限。
- heartbeat_at 是 worker 存活，last_activity_at 是最近 Agent 事件，两者不得混用。
- 终态不可被迟到的 progress 覆盖；所有变更检查 task revision / attempt / lease epoch。
- 重试创建新 attempt，保留前次结果与错误；终态任务的“重新执行”创建新任务并关联 retry_of，避免复写历史。

### 6.3 持久化与事务

默认位置：`STELLA_HOME/cometa/tasks.db`，同一数据根的实例共库，用 instance_id 划分所有权。首版只支持本地磁盘 SQLite，不将 WAL 库放在网络共享目录。

| 表 | 核心字段与约束 |
| --- | --- |
| meta | schema_version；未知更高版本拒绝启动 worker |
| tasks | task_id PK；origin/spec/config_snapshot；state、revision、current_attempt；UNIQUE(instance_id, origin_scope, idempotency_key) |
| attempts | attempt_id PK；task_id、attempt_no、backend_id/version、session_id、turn_id、launch_phase、lease_owner/epoch/until；UNIQUE(task_id, attempt_no) |
| events | task_id、sequence、attempt_id、kind、payload；PK(task_id, sequence)，可选原生事件唯一键 |
| results | result_id PK；task_id、attempt_id、outcome、evidence、summary、manifest_ref；每个任务一个当前最终结果引用 |
| artifacts | artifact_id PK；task_id、relative_storage_key、sha256、size、mime、display_name、availability |
| input_requests | request_id PK；task_id、attempt_id、connection_generation、backend_request_id、kind、schema、state、expires_at、revision |
| controls | control_id PK；task_id、kind、request_id、payload、state、lease；取消/答复幂等键 |
| notifications | notification_id PK；task_id、kind、sequence、target_snapshot、payload、state、receipt；UNIQUE(task_id, dedupe_key) |
| worker_leases | instance_id PK；worker_id、process_identity、epoch、lease_until |
| workspace_leases | canonical_workspace_key PK；task_id、attempt_id、epoch、lease_until |
| audit | actor、action、task/request/attempt IDs、时间、结果；不保存密钥或完整提示词 |

必要索引：tasks(instance_id,state,created_at)、attempts(lease_until)、events(task_id,sequence)、notifications(state,next_attempt_at)、controls(state,created_at)。

事务边界：

1. **受理**：BEGIN IMMEDIATE → 校验幂等键/配额 → tasks + queued 事件 + ack notification → COMMIT。相同 key 同内容返回原 receipt；同 key 不同内容返回冲突，不能覆盖任务。
2. **认领**：可运行任务条件更新 → 新 attempt、租约和 starting 事件同事务。调用 Agent 前必须完成这次提交。
3. **事件**：校验 lease epoch → 追加事件、更新 snapshot → 按策略 upsert 通知同事务；原始 token delta 不要求逐 token 刷盘，可有界合并，但终态/输入/审批事件必须立即提交。
4. **完成**：产物先写临时文件并校验/原子归档 → results/artifacts manifest + terminal event + final notification 同事务 → 释放运行槽。
5. **投递**：claim notification → 持久 sending → 平台调用 → sent/server_emitted/delivery_unknown。网络调用不放在 SQLite 事务内。

SQLite 锁等待需要小于受理接口预算；数据库繁忙返回明确忙碌状态。若提交等待超时而事务结果不明，先按幂等键查 receipt；返回“提交状态待确认”，客户端继续用原 key 查询，禁止换 key 重提。

### 6.4 能力选择与自动委派

新增 `capability/delegation.py`，输入是可信 Origin、用户文本、现有路由结果和 cometa 能力快照，输出 `local | delegate | clarify | unavailable`。

执行顺序：

1. 无可信用户 Origin、主动插话 intent、功能关闭 → 原路径；禁止从被动群聊、通知文本或 Agent 输出自动生成任务。
2. 明确 cometa 命令或明确指定后端 → 确定性解析；缺工作区等必要信息先澄清。
3. 自动模式启用时：结合可用工具、后端能力、任务类型判断。编码/测试/多步调查可委派；现有可靠短工具仍走 Comes。
4. 用户点名但该后端不可用 → 告知原因；不静默换厂商。未点名时可按配置优先级选择。
5. 委派选中后，整个请求由 cometa 负责；本轮不再对同一目标执行 Comes 或 Skills。Memory 的门控不改变。
6. 自动委派需记录 reason_code 和决策依据。无法确定是否需要实际行动时，继续聊天或澄清，不靠“模型自称不会”触发执行。

默认候选能力：`research.web`、`code.read`、`code.edit`、`code.test`。能力 ID 是 cometa 自身语义，后端可映射多种实际工具；不把后端全部工具 schema 注入 Stella。

**接入实现：** `activate_capabilities` 在启动分支前调用新的委派选择器；成功后写 `ctx.cometa_submission`，并填 `ctx.reply` / `ctx.lines` 的受理确认，使 prepare_turn 返回 DIRECT。新增 `ChatContext.cometa_origin` 与 `cometa_submission`，默认 None；core 使用不反向 import cometa 的数据承载方式。两个字段均不进入既有投影白名单。

当前 QQ handle_chat 构造 ctx 时未显式设置 source_kind，不能单靠 source_kind 判断用户授权；由真实 handler 的事件构造 Origin。WebChat 必须从认证上下文和客户端请求 ID 构造 Origin，不能把固定虚拟用户 ID 当成认证。

**失败后升级：** M3 才开启，且只适用于明确无副作用的任务。现有 Result.metadata 的 reason 文本不足以判定是否已经执行，拟新增可选 metadata：`error_code`、`effect_state=none|confirmed|unknown`。只有确认 effect_state=none，或明确可重复的纯查询，才能自动委派。缺信息、拒绝权限、已部分写入和结果不明均不自动升级。

### 6.5 受理确认与聊天发送归属

必须避免“当前聊天发送一次 ack，后台又发送一次 ack”。

- 任务受理事务创建 ack notification；ctx 携带其 ID 和可展示文本，不标记已发送。
- QQ handle_chat 发现 cometa_submission 后，通过桥接 `deliver_ack` 认领该 notification，用当前 bot 发送；跳过原普通回复发送分支的这条 ack。
- 后台 DeliveryPump 可以接管尚未发送的 ack，但与入口使用同一通知租约/CAS。二者竞争只有一个发送者。
- ack 无回执/超时为 delivery_unknown，不能无限重发；后续状态/结果附上任务短 ID 与简短目标，保证用户仍能识别任务。
- WebChat 的 ack 经当前 HTTP/SSE complete 发出后记 server_emitted，含义是服务端发出了响应，不声称用户已阅读；重复请求仍能返回同一 receipt。
- progress/final 的排序在 ack 进入已发送、server_emitted、unknown 或明确不可投递状态后推进。连接断开时不丢最终结果，也不无限等待 ack。
- 即便聊天在受理后 reset 或断开，已提交任务仍存在；通过任务列表查询和显式取消管理。

对“立即”的验收是：不等待 Agent 运行或鉴权联网后才确认。服务受理目标为本地条件正常时 2 秒内；前置上下文/模型路由耗时单独测量，不能把整个聊天请求保证为 2 秒。

### 6.6 AgentBackend 协议

后端不调用 QQ/WebUI，不写任务数据库，不决定最终用户权限。建议定义 Python Protocol：

```python
describe() -> BackendDescriptor
probe() -> BackendHealth
open_session(spec, workspace, policy) -> SessionHandle
start_turn(session, request, launch_token) -> TurnHandle
stream(handle) -> AsyncIterator[BackendEvent]
inspect(handle) -> BackendSnapshot
respond(handle, backend_request_id, answer) -> BackendControlResult
cancel(handle) -> BackendControlResult
close(session) -> None
```

这些是 cometa 内部方法，不是 Codex SDK 的逐字 API。

能力描述区分：任务能力和生命周期能力。后者包括 `supports_inspect`、`supports_resume`、`supports_event_replay`、`supports_cancel`、`supports_approval`、`supports_steer`、`supports_usage`。不支持的能力返回明确 unsupported；不能用一次新执行伪装 resume。

`launch_token` 是 cometa 跟踪字段，不能假设后端支持幂等启动。只有后端明确验证支持时，才把它作为后端幂等键使用。

注册方式：内置显式映射 `backend_type -> factory`。新增第三方适配器由部署者安装和登记；不要允许群聊传 Python import 路径或任意 executable。首版无需动态插件市场。

### 6.7 Codex 后端

官方资料核对日期为 2026-09-30：

- 官方 Python SDK `openai-codex` 控制本地 App Server，提供异步接口，适合本项目的 Python 技术栈；通过可选依赖安装并固定经过验证的版本。[SDK 文档](https://learn.chatgpt.com/docs/codex-sdk)
- App Server 提供线程/轮次控制与事件流；首版使用本地 stdio。握手、线程创建/恢复、轮次启动/中断由适配器封装，业务层不接触原始协议。[App Server 文档](https://learn.chatgpt.com/docs/app-server)
- `codex exec --json` 可用于非交互执行与 JSONL 事件验证；它是可选的独立适配模式，不与 App Server 混用会话协议。[非交互文档](https://learn.chatgpt.com/docs/non-interactive-mode)

本机 CLI 为 0.147.0，帮助仍将 app-server 标为 experimental。它只是勘察基线，不是本项目已经通过的兼容版本。M0 必须冻结 SDK/runtime 组合、生成或保存其协议 fixture，并测到下列映射：

| 后端事实 | cometa 归一行为 |
| --- | --- |
| 会话/轮次成功创建 | 保存 session_id / turn_id，再进入运行态 |
| item 开始或完成 | 更新活动和阶段；以完成事件作为该 item 权威值 |
| 消息增量 | 有界缓冲；不把任意中间消息当最终答复 |
| 命令/文件/搜索记录 | 保存脱敏证据与产物线索，形成进度 |
| 请求信息或审批 | 持久 input_request，进入等待态；不自动同意 |
| 轮次完成/失败/中断 | 核对明确状态，收集结果；不能只检查进程 exit code |
| 断流或子进程退出 | 转 recovering；不是直接重发原始任务 |

如果选定 SDK 缺少必要事件，优先在 CodexAdapter 内补协议封装；该决定在 M0 结束时固定，业务层接口不变。普通任务只选择当前账号可用的已配置模型，不在代码中硬编码某个最新模型。

搜索 profile 启动前验证工具配置、账号和网络条件；不能把“能启动 Codex”视为“实时联网搜索已可用”。资料类结果应保留 URL、查询时间及无法获取的来源。

认证由管理员预先完成，或由明确的凭据引用提供。cometa 不复制桌面应用的私有会话，不抓取 UI，不把当前聊天工具当外部应用 API。子 Agent 不自动继承 Stella 的所有插件、聊天记录和环境变量。

### 6.8 启动、租约、恢复和取消

**启动协议：**

1. worker 认领任务并持久 starting；记录 attempt_id、launch_token、配置版本和工作区。
2. 启动/连接后端，得到 session 后立即保存；start_turn 前记 launch_phase=dispatching。
3. 收到 turn handle 后保存并转 running。若在请求发出到 handle 落库之间崩溃，launch_phase 可证明这是启动结果不明窗口。
4. 宿主崩溃后，只有 inspect 能确认已有任务状态，或有经测试的后端启动幂等保证时，才允许继续；否则 recovery_required。

**恢复矩阵：**

| 恢复时看到的事实 | 行为 |
| --- | --- |
| queued，确定未启动 | 可以重新认领 |
| starting，确定启动请求尚未发出 | 清理自己创建的空会话后重新准备 |
| dispatching，后端 turn 是否创建不明 | 核对；无法核对则 recovery_required |
| 后端仍运行且支持连接/查询 | 重新订阅或查询；记录事件缺口，不捏造缺失历史 |
| 后端已完成，cometa 未写结果 | 收集结果，按唯一约束补交终态一次 |
| 后端已中断且有持久会话 | 明确停止后，按恢复策略决定继续；有外部副作用的任务先核对证据 |
| 后端不可达且旧进程生死不明 | 保留恢复状态和工作区锁，不启动第二份执行 |
| 旧审批请求所属连接已失效 | 标记 expired；由新执行重新发出审批，不重放旧 RPC request ID |

租约默认 30 秒，每 5 秒续租，使用 CAS 与递增 epoch。租约过期只允许接管数据库控制权，不能证明旧 Agent 停止了外部副作用。工作区写锁只有确认旧执行已停止才能释放；跨进程锁与 PID+创建时间/启动 nonce 共同验证。不要仅凭 PID 杀进程。

**取消：** service 持久 cancel 控制命令 → worker 请求后端中断 → 确认停止 → 保存已产生的结果/变更 → cancelled。取消与完成竞争由同一终态 CAS 裁决；已完成返回当前终态。强制终止仅限自身进程树，超时无法确认停止则 recovery_required。

**关闭：** 先停止接单/认领，再通知在途任务中断和保存，最后停止 DeliveryPump、worker 和自己启动的 Agent；共享现有有界 shutdown 预算，不给每个子系统串行叠加完整超时时间。下次启动按恢复矩阵处理，不无条件 running→queued。

### 6.9 工作区与权限

- 管理员在 cometa.toml 声明 workspace_id → 允许的仓库根路径；用户提交的是 ID，模型不能指定任意 cwd。
- 编程任务默认在固定 base commit 的独立 worktree 中执行；保存 base_commit、工作区路径、分支和初始状态。首版基于提交快照，不自动拷贝用户未提交修改。
- 同一工作区最多一个写任务；即使多实例共享数据根也必须守同一工作区锁。
- 默认交付 patch / 改动清单 / 测试证据，合并、push、部署是新的显式操作，不由“写代码”自动推导。
- worktree 是冲突隔离，不是安全沙盒。实际文件、网络、命令权限由后端沙盒和宿主策略约束；后端不能落实 profile 时拒绝启动，不降级成无限权限。
- 管理员预授权 profile 范围内的操作正常执行；越界操作才形成具体审批。QQ 请求者可以取消/补充自己的任务；扩大机器权限默认只允许配置的 cometa 管理员。
- 允许的 QQ 用户/群和 workspace/profile 绑定单独配置；不能把“群管理员”自动等同“主机管理员”。
- 子进程使用参数数组和固定 executable，无 shell 拼接；Windows 隐藏窗口，stdin 传任务文本。清理明确归属的进程树和路径。
- 产物和工作区保留默认 7 天；恢复中的任务、有未交付结果的任务不自动清理。到期清理前先确认引用与进程已释放。

### 6.10 输入和审批

input_requests 保存任务、attempt、连接代际、原生请求 ID、允许选项、权限差量、过期时间与版本。客户端答复必须同时匹配这些信息。

- 自己的普通补充信息由原请求者回答；权限提升按管理员规则授权。
- 群内其他用户说“同意”、引用过期消息或传入别人的 request_id 均不能放行。
- 同一请求重复答复：相同内容返回原结果，不同内容冲突。
- 控制答复已发出但确认丢失：检查后端请求是否仍挂起；不把同一审批重放给新的请求。
- 等待期间继续发真实等待状态；到期请求中断任务。用户沉默不等于批准。
- UI 无法显示某种后端交互时返回可解释的 unsupported/blocked，不无限挂起。

### 6.11 进度与通知

统一事件 kind：accepted、started、progress、input_required、approval_required、artifact_created、completed、failed、cancel_requested、cancelled、recovery_required。

通知默认值（均可配置）：

- 受理确认立即发送；开始和重要阶段变化最短合并间隔 30 秒。
- 长时间运行每 120 秒允许一条状态；没有新活动时明确“仍在运行，最近一次活动是……”。
- 等待输入/审批、失败、完成立即入队，不被普通进度节流抹掉。
- 用户主动查询不受自动通知节流限制；平台发送频率仍受发送器控制。
- 同任务未发送的旧 progress 可以合并；final 和 input_required 不可被覆盖。final 出现后取消过时进度。
- 只转述工作阶段、公开进展和工具执行事实，不转发推理全文、凭据或原始命令输出。

投递器使用单独的通知租约；任务执行 lease 已释放也能发送最终结果。平台发前重新检查账号、群允许状态和目标有效性。群被移除或 Bot 不在线时保留结果；不存在平台调用的失败可退避重试，已经调用但结果不明则 delivery_unknown，不自动重发。

**QQ：** 保存原 bot_id/group_id/user_id/reply_to；按配置 @ 请求者并引用原消息。引用已失效时只发送到同一授权群并带任务号，不能转发到其他会话。发送内容按 text 组件处理，不将 Agent 文字解释为 CQ 控制码。摘要/最终答复按既有 BOT_SELF 记录规则写短文本，原始日志不进记忆。

**WebChat：** 沿用服务端单管理员身份。现有聊天 SSE 是单轮响应，新增 `/cometa/.../events` 供跨轮次订阅，断线用游标补读。持久任务卡片/事件记录是结果真源；server_emitted 不代表客户端收到或读过。

**reset：** WebChat reset 清空聊天不会删除/取消 cometa 任务；增加持久 conversation_generation。旧 generation 的通知保留在任务中心，不在 reset 后重新写入聊天历史。新 QQ 消息推进的主动插话版本不能使已受理任务结果失效。

### 6.12 结果校验与产物交付

AgentResult.outcome 与 verification_status 分开：例如任务生成了有用补丁但测试失败，outcome=partial，verification_status=failed；只完成代码阅读而无需运行测试的任务，按它自己的 acceptance_criteria 判定。

evidence 保存来源和置信边界：`agent_reported`、`observed_tool_event`、`host_checked`。宿主只执行任务 profile 已授权的验收命令；不能为了“验证”任意运行模型提供的新命令。

处理顺序：

1. 收集后端最终答复、命令退出码、测试记录、文件差异和引用。
2. 按预先保存的 acceptance_criteria 校验。无法验证时保留 limitations，不补造成功。
3. 生成有界 summary；首版用模板组合状态、主要产物和验证事实。后续允许模型润色，但状态、来源、测试结果和文件引用由结构化字段固定。
4. 产物进入 `STELLA_HOME/cometa/artifacts/<task_id>/`，保存 SHA-256、长度和 MIME；只接受该任务工作区内的允许文件，拒绝路径穿越、越界链接和未授权敏感文件。
5. 发布结果 manifest 与 final notification。文件写入成功但事务失败的孤立产物由延迟清理回收；已发布但文件缺失必须显示 unavailable。

QQ 附件通过平台文件上传适配器交付；若 NapCat 与 Stella 不共享文件系统，必须使用平台支持的字节/上传接口或受控传输，不能直接把 Stella 本地路径交给远端容器。附件上传失败时文本仍报告结果，并说明产物未送达，保留可重试入口。

WebUI 下载使用 task_id/artifact_id 的鉴权接口，服务端解析 manifest，不接受任意 path 参数。首版不创建匿名公开下载链接；QQ 用户不能因为收到一个需要管理员登录的 URL 就被视为已收到产物。

### 6.13 配置与可观测性

配置以 `STELLA_HOME/config/cometa.toml` 为详细配置，环境变量只提供总开关、模式、路径和运维上限。以下是拟新增字段，尚不存在于当前项目。

| 环境项 | 建议默认值 | 语义 |
| --- | --- | --- |
| COMETA_ENABLED | false | 关闭时不导入可选 SDK，不启动 worker |
| COMETA_DELEGATION_MODE | explicit | explicit / auto；自动委派单独灰度 |
| COMETA_CONFIG_FILE | cometa.toml | 相对 STELLA_HOME/config |
| COMETA_DB_PATH | STELLA_HOME/cometa/tasks.db | 独立任务库 |
| COMETA_MAX_CONCURRENT | 2 | 每实例活动执行数；同用户默认 1 |
| COMETA_SUBMIT_TIMEOUT_SECONDS | 2 | 受理服务预算，不含整轮聊天/路由时间 |
| COMETA_TASK_TIMEOUT_SECONDS | 1800 | 总墙钟期限，profile 可缩短 |
| COMETA_PROGRESS_INTERVAL_SECONDS | 120 | 无关键变化时的长任务状态间隔 |
| COMETA_RESULT_MAX_CHARS | 2000 | Stella 可见摘要上限；完整产物另存 |

TOML 示例为配置设计，不是现有 Codex CLI 配置：

```toml
schema_version = 1

[limits]
per_user_active = 1
per_group_active = 2
input_wait_seconds = 600
artifact_max_bytes = 20971520
artifact_total_max_bytes = 104857600
retention_days = 7

[backends.codex_local]
type = "codex"
enabled = true
transport = "stdio"
executable = "C:/path/to/codex.exe"
auth_profile = "operator_codex"
capabilities = ["research.web", "code.read", "code.edit", "code.test"]
# 只是期望能力；probe 未通过的能力不可路由。

[workspaces.stella]
repository = "E:/stella/stella_project"
base_ref = "HEAD"
mode = "worktree"

[profiles.research]
backend = "codex_local"
allow_network = true
allow_workspace_write = false

[profiles.coding]
backend = "codex_local"
workspace = "stella"
allow_network = false
allow_workspace_write = true

[access]
qq_user_ids = []
qq_group_ids = []
operator_user_ids = []
# 空列表表示未授权；WebUI 管理员走现有认证。
```

配置 loader 为单一真源：服务与 worker 保存相同版本/hash。配置调整不静默扩大在途任务权限；权限撤销由显式控制动作中断在途任务。模型名留空采用经 probe 确认的配置默认值。

遵循 settings 的 `_env_*` 辅助函数，使 deploy/env_schema 可提取。一般不需要为每个新键改 schema 解析器；若 UI 分组不能自动覆盖，只添加 cometa 分组，不重构配置系统。

健康状态：disabled / ready / degraded / auth_required / incompatible。日志记录 task_id、attempt_id、backend/version、phase、时延、错误码、事件数、投递状态。用量无法取得时是 unknown，不能记成 0；只得到 token 数时不虚构费用。cometa 暂用独立 usage 记录，后续聚合进现有用量界面。

### 6.14 WebUI 与命令交互

拟新增 API 使用现有 `ok/error` envelope：

```text
GET    /api/v1/cometa/backends
GET    /api/v1/cometa/tasks
POST   /api/v1/cometa/tasks                 # accepted 返回 202
GET    /api/v1/cometa/tasks/{task_id}
GET    /api/v1/cometa/tasks/{task_id}/events # SSE 或有游标分页
POST   /api/v1/cometa/tasks/{task_id}/cancel
POST   /api/v1/cometa/tasks/{task_id}/inputs/{request_id}
GET    /api/v1/cometa/tasks/{task_id}/result
GET    /api/v1/cometa/tasks/{task_id}/artifacts/{artifact_id}
```

- 所有端点 require_auth；当前 WebUI 管理员可管理实例内任务，不能将 task_id 当凭据。
- 写操作记 audit；受理、取消带客户端幂等键，回答带 expected_revision。
- SSE 支持 sequence 游标与断线补读；只推归一且脱敏的事件。游标超出保留范围返回 reset_required + snapshot，不假装重放完整日志。
- 新增 CometaPage 展示任务列表、阶段、等待问题、结果、产物；支持查询、取消、补充输入和审批。
- ChatPage 展示受理任务卡片并订阅任务事件，不把 Agent 日志逐字追加进普通聊天历史。
- QQ 显式命令建议：`@Stella 委派 codex <目标>`、`任务状态 <id>`、`任务结果 <id>`、`取消任务 <id>`、`任务补充 <id> <内容>`。若一个任务有多个待答问题，必须带 request_id 或引用对应消息。
- 命令规则与现有定时/插件重载/能力查询/开关规则做双向互斥测试。不得仅增加一个 priority=1 handler 后假设不会抢消息。

## 7. 分阶段实施顺序

| 阶段 | 交付内容 | 完成门槛 |
| --- | --- | --- |
| M0：协议验证 | Codex probe、版本矩阵、事件录制 fixture、FakeBackend、交互/取消/恢复最小探针 | 确认选定 SDK 的事件覆盖和本机实际沙盒能力；未支持的能力显式关闭 |
| M1：持久执行内核 | models/config/store/migrations/service/worker/executor；启动与恢复状态；幂等和配额 | 不接聊天也能提交、查询、取消、故障恢复；双 worker 不重复启动 |
| M2：可用闭环 | QQ/WebChat 显式入口、ack、长程状态、最终结果、附件、管理 API 和基础页面 | 请求者能独立完成提交→状态→补充/取消→结果；Bot 可同时继续聊天 |
| M3：自动委派 | capability/delegation、hooks 接线、能力快照、只读失败升级、预算与 benchmark | 联网搜索缺能力和复杂编码请求能正确委派；闲聊/主动发言不误触发 |
| M4：扩展与发布 | 第二个真实 AgentBackend、共享契约测试、Windows/Linux 集成、运维文档 | 更换后端不修改任务库/通知协议；兼容性矩阵、退回 explicit/off 可操作 |

实施细化：

1. M0 不先重构现有框架；用受控目录和固定 fixture 验证最小协议。记录原生事件但提交前脱敏。
2. M1 先实现事务和迁移，再实现 worker；先使用 FakeBackend 注入“启动后崩溃”“终态提交前断电”等场景，再接 Codex。
3. M2 先让显式命令走 CometaService，避免依赖自动路由准确率；同步完成结果和产物交付，不把“能拉起进程”当 MVP 完成。
4. M3 再让能力钩子提交后台任务；新增字段默认空，关闭时保留原输出。自动模式先灰度到指定用户/群。
5. M4 选择实际部署需要的第二种 Agent，先确认官方接入协议，再实现它的适配。对不支持 resume/approval 的后端展示真实差异。
6. 每阶段提交前执行 GitNexus detect_changes，记录所有 partial/truncated 限制；有截断就补查，不将 0 解释成无影响。

## 8. 测试策略

本次是设计存档，未执行生产功能或带账号的 Agent 任务。以下为实施必须新增/保留的测试，不是已完成测试结果。

### 8.1 新测试（拟新增路径）

| 文件 | 场景：输入/故障 → 预期 |
| --- | --- |
| tests/cometa/test_store.py | 重复同 key → 同 task_id；同 key 不同目标 → 冲突；提交取消/超时后查回真实结果；配额检查与插入原子 |
| tests/cometa/test_migrations.py | 新库/旧库/更高版本/迁移中断 → 正确迁移或停用；不得清空旧任务 |
| tests/cometa/test_worker.py | 并发 worker / 续租失败 / 旧 epoch 写入 → 单 owner；没有停止证据不启动第二执行 |
| tests/cometa/test_recovery.py | starting 各崩溃窗口、Agent 完成后 DB 未提交、事件流断开 → 不重复执行；不支持恢复 → recovery_required |
| tests/cometa/test_backend_contract.py | 同一套任务/事件/取消/输入/错误测试运行于 FakeBackend、CodexAdapter 和第二个后端 |
| tests/cometa/test_codex_events.py | fixture 中重复/未知/乱序事件、completed/failed/interrupted、无 final 文本 → 保持事实，不误报成功 |
| tests/cometa/test_delivery.py | ack 入口与 pump 竞争、阶段合并、final 优先、send 后崩溃、平台超时 → 不盲目重投 |
| tests/cometa/test_authorization.py | A 查询/取消/批准 B 的任务、跨群同 ID、伪造 Origin、过期 request → 拒绝，无后端调用 |
| tests/cometa/test_artifacts.py | 越界路径、symlink/junction、超大文件、缺文件、哈希不符、远端 NapCat 无共享路径 → 明确拒绝/未交付 |
| tests/cometa/test_workspace.py | 两任务写同工作区、脏主仓、worktree 创建失败、清理活动目录 → 保留原改动并阻止冲突 |
| tests/cometa/test_lifecycle.py | 功能关闭/SDK 缺失/配置损坏/shutdown 超时 → Stella 正常运行，不留不可追踪的子进程 |
| tests/capability/test_delegation.py | 搜索有本地工具/无本地工具、复杂编码、点名离线后端、普通闲聊、主动插话、已有副作用失败 → 正确分流 |
| tests/webui/test_webui_cometa.py | 401、任务/产物授权、202、幂等、SSE 补读/reset、审批冲突、响应脱敏 |

### 8.2 现有测试与回归面

- `[verified]` `tests/capability/test_capability_hooks.py:200`、`:246` 等已有 Memory/Comes 断言；完整保留并新增“受理后不执行同目标 Comes/Skills”。
- `[verified]` `tests/runtime/test_session_ownership.py:18`、`:32`、`:50` 保护同 key 串行、跨 key 并发、reset fence；不修改其原语义。
- `[verified]` `tests/scheduling/test_scheduling_delivery.py:84` 起验证先保存 ready、发送和回执；现有调度模块不做通用化重构，保留该基线。
- 已定位的回归文件还包括 `tests/runtime/test_facade_turns.py`、`tests/runtime/test_turn_service.py`、`tests/runtime/test_ingress_native.py`、`tests/test_ai_gateway_deterministic_reply.py`、`tests/webui/test_webui_chat.py`、`tests/webui/test_webui_manage.py`、`tests/test_env_schema.py`。
- 新增字段在现有构造器默认空；不得为通过测试将旧 ChatContext 全部调用点强制加入 cometa 参数。

### 8.3 人工与集成验收

1. 搜索任务：无本地搜索工具但 Codex 搜索可用，受理后返回至少一个可访问来源；搜索不可用时报告限制。
2. 编程任务：在临时仓库持续运行数分钟；同群继续正常对话，状态查询及时；最终收到补丁与真实测试记录。
3. 任务运行中重启 Stella，核对不重复启动，状态/结果仍可查；若后端不能恢复，明确显示恢复待处理。
4. QQ 用户 A 与 B 同时提问，结果只回到各自原请求会话；B 不能审批 A 的任务。
5. 取消后确认受控 Agent 已停止；修改过的文件保留并标注，不自动回滚用户工作。
6. WebChat 页面断开/刷新/reset 后，任务仍在任务中心；旧结果不重建被清空的聊天历史。
7. 使用第二种真实 Agent 完成一次相同受理/状态/结果流程；记录其不支持的可选能力。

### 8.4 验证命令

当前 CI 已核验采用 Python 3.10/3.11/3.12、pytest、ruff；dashboard 已有 typecheck/build 脚本。实施环境安装 requirements 与 requirements-dev，新增测试文件落地后运行：

```powershell
python -m pytest tests/cometa tests/capability tests/runtime tests/scheduling tests/webui -q
python -m pytest tests/test_ai_gateway_deterministic_reply.py tests/test_env_schema.py -q
python -m ruff check cometa capability core webui stella_project config tests/cometa
npm --prefix dashboard run typecheck
npm --prefix dashboard run build
```

发布前按 `.github/workflows/ci.yml` 运行完整测试，Windows 单独覆盖子进程、路径和停止行为。带真实账号的探针手动启用，不在普通 CI 里消耗用户额度。

## 9. 风险、恢复与兼容策略

| 风险 | 具体处理 |
| --- | --- |
| 能力入口/ChatContext 为 HIGH | 默认关闭，新增字段默认空；控制改动范围；原有 hooks/runtime 测试先保持绿 |
| 启动确认丢失导致重复改代码 | launch_phase + backend IDs + inspect；不明即恢复待处理 |
| 租约过期但旧执行仍活着 | lease epoch 只隔离数据库写，另核验/停止旧进程；工作区锁保留 |
| 受理成功但聊天确认失败 | 任务库与 outbox 仍在；幂等查询返回原 receipt，不能重提新任务 |
| Agent 完成但消息未送达 | 结果与投递独立；unknown 保留原结果，用户查询可重取 |
| 动态能力/账号限额变化 | 后端 health 缓存有时效；启动前复验，失败有明确错误码 |
| 工具输出被当作授权或事实 | Origin 隔离、审批 ID 绑定；证据注明 agent_reported / observed / checked |
| 大输出压垮 8K 上下文或磁盘 | 摘要、事件缓冲、产物数量/大小和保留期均有限制 |
| SDK/CLI 变更 | 固定版本，协议 fixture 和契约测试；升级先跑 M0 探针 |
| 现有定时任务行为受影响 | 不重构调度库/worker；共享的是设计原则和入口锁，不是执行循环 |
| 打包/升级丢任务 | 数据写 STELLA_HOME，新增包进发布文件清单；Codex 依赖首版可选安装 |

灰度顺序：off → explicit（指定管理员/用户）→ auto（指定群）→ 扩大范围。切回 explicit 只停止自动新委派，不取消已受理任务；关闭新提交与紧急停止执行应是两个明确操作。完全关闭前先有界停止 worker，保存可恢复状态。

迁移只新增 cometa 库，不迁移 memory/scheduling 数据。发布回退不删除新库；旧版本遇到更高 schema 停用 cometa，保留其他聊天能力。升级前保存 SQLite 一致性备份，不能只复制有活动 WAL 的主 db 文件。

## 10. 预计改动文件

下表的“改动”是后续实施清单；本次只新增本文。

| 路径 | 拟改动内容 | 阶段 |
| --- | --- | --- |
| cometa/** | 新增完整子系统，职责见 §3.2 | M0–M2 |
| capability/delegation.py | 新增委派意图、现有工具优先、后端能力判断 | M3 |
| capability/hooks.py / activate_capabilities | 提交有界委派分支，保留 Memory 行为，防重复执行 | M3 |
| capability/hooks.py / _run_comes | 仅在实现只读失败升级时回传结构化失败信息 | M3 |
| capability/comes/executor.py / execute | 可选 metadata 错误分类；不改变 Result.ok 和终态枚举 | M3 |
| core/context.py / ChatContext | origin/submission 默认空，保持旧投影白名单 | M2 |
| stella_project/plugins/bot_main/cometa_bridge.py | 新增 QQ 可信入口、命令规则、ack/通知 Sender | M2 |
| stella_project/plugins/bot_main/ai_gateway.py | handle_chat 身份和确认桥接、命令互斥、生命周期薄接线 | M2 |
| webui/chat_ingress.py / run_turn、reset_webchat_runtime | 可信请求 ID、受理确认、持久 conversation_generation | M2 |
| webui/routers/chat.py | WebChat 请求 ID 与 receipt DTO；保持既有单轮 SSE 兼容 | M2 |
| webui/routers/cometa.py、webui/services/cometa.py | 新增鉴权 API / SSE / 产物下载 | M2 |
| webui/app.py / create_webui_app | 静态 catch-all 前注册 cometa router | M2 |
| config/settings.py、.env.example | COMETA_* 设置与说明；详细配置走 TOML | M1 |
| pyproject.toml | 可选 cometa 依赖及验证后的 SDK 版本约束 | M0/M4 |
| dashboard/src/views/CometaPage.vue、dashboard/src/api/cometa.ts | 新增任务页面和客户端 | M2 |
| dashboard/src/router/index.ts、dashboard/src/views/ChatPage.vue | 页面路由和受理卡片 | M2 |
| dashboard/src/i18n/locales/zh-CN.json、en-US.json | 状态、错误、操作文案；不显示内部协议名给普通用户 | M2 |
| tests/cometa/**、tests/capability/test_delegation.py、tests/webui/test_webui_cometa.py | 新增测试 | 各阶段 |
| 现有 hooks/runtime/WebChat 测试 | 新默认字段与兼容回归 | M2/M3 |
| docs/cometa.md（新增） | 安装、认证、权限、恢复、取消、故障诊断 | M4 |

暂不改 RuntimeFacade / TurnService 主执行器、SchedulerRuntime / DeliveryService、记忆 schema、runtime-manager 组件协议和桌面壳进程管理协议。若实际实现必须改动，先更新本方案并重新 impact，不能顺手扩大重构。

发布文件收集、菜单入口及配置分组的具体文件在 M4 按当前发布链定位，本文不猜测未核验的实现符号。该项是发布前必要核验项，不是省略交付。

## 11. 实施上下文与证据复用

### 11.1 源码与工具基线

- HEAD：`bda9af928207c2901d873b87999f8fc18cc334d5`。
- 起草前 `git status --porcelain=v1` 无输出；本方案不包含用户未提交的业务变更。
- 复用前一轮已核验的 Comes、Task/Result、ProviderRuntime、RuntimeFacade、DeliveryService 证据；本轮补查入口、锁范围、配置、WebUI、测试与 PDG。
- GitNexus 调用入口：`node C:/Users/Vegetable/AppData/Local/npm-cache/_npx/5e786f48223a616c/node_modules/gitnexus/dist/cli/index.js`；每次指定 repo 绝对路径和 GITNEXUS_STORAGE_ROOT。该缓存路径仅描述本次环境，执行者应先探测可用 runner，不将其写进产品代码。
- 本文按用户指定位置归档，未生成标准 GitNexus schema-2 provenance，也不把普通 Git 状态检查伪称为全路径摘要。若后续使用严格 gitnexus-work 工作流，先从本文建立标准实施计划并由技能 helper 生成当时的 provenance。

### 11.2 精简实现上下文

```yaml
implementation_context:
  format: project-design-v1
  task_summary: 为 Stella 新增跨轮次外部 Agent 任务运行层 cometa
  verified_at_commit: bda9af928207c2901d873b87999f8fc18cc334d5
  artifact_path: design_docs/Cometa 外部 Agent 任务运行层实施方案 v1.0.md
  evidence_status: source-verified; graph refreshed with PDG; flow coverage bounded
  primary_symbols:
    - capability/hooks.py::activate_capabilities
    - core/context.py::ChatContext
    - core/runtime/facade.py::RuntimeFacade.submit_turn
    - stella_project/plugins/bot_main/ai_gateway.py::handle_chat
    - stella_project/plugins/bot_main/scheduling/delivery.py::DeliveryService.deliver
  execution_path:
    - trusted ingress -> delegation policy -> transactional submit -> immediate receipt
    - worker claim -> backend session/turn -> normalized events -> validated result
    - durable notification -> Stella channel sender -> delivery receipt
  constraints:
    - prepare hooks run under the session lock; provider timeout does not cover them
    - database accepted does not mean backend started or user notified
    - unknown launch outcome must not trigger blind resubmission
    - lease fencing alone cannot stop an old agent from causing side effects
    - no backend-specific protocol fields in Stella prompts
    - task outcome and notification delivery are independent
  implementation_order: [M0_protocol, M1_runtime, M2_delivery, M3_auto_delegation, M4_second_backend]
  tests:
    new: [tests/cometa, tests/capability/test_delegation.py, tests/webui/test_webui_cometa.py]
    regression: [tests/capability, tests/runtime, tests/scheduling, tests/webui]
  top_risks: [duplicate_execution, lost_delivery, cross_user_authorization, orphan_process, protocol_drift]
  assumptions_to_verify:
    - SDK exposes required events and approvals; verify with pinned-version fixtures
    - deployed sandbox can enforce profiles; fail closed if unavailable
    - QQ attachment transport works across deployed NapCat topology
  avoid:
    - extending chat timeouts to run coding tasks
    - treating queued as success
    - reusing in-memory t1 identifiers for durable tasks
    - changing existing cron delivery semantics
    - inferring ownership from model output or a guessed conversation identifier
    - assuming session resume provides event replay or exactly-once execution
```

## 12. 假设、待验证项与明确延后

### 12.1 实施前需要验证，方案不作已完成承诺

1. `[assumed]` 选定 openai-codex 版本能提供流事件、审批、取消及恢复所需能力：M0 用真实受控探针与协议 fixture 验证，决定 SDK 或适配器内直连。
2. `[assumed]` 目标机器的 Codex 认证、搜索与沙盒可用：probe 分别检查，任何一项失败只禁用对应后端能力。
3. `[assumed]` 第二个 Agent 的选择：M4 根据实际部署选择并核对其官方协议；本文不宣称其已兼容。
4. `[assumed]` QQ 文件发送方式适配部署拓扑：M2 在同机与 NapCat 容器两种环境验证；不可达时明确未交付附件。
5. 发布打包是否自动包含顶层 cometa 包与可选依赖：M4 通过发布文件清单和冷启动安装验证，不仅以源码环境 import 成功验收。
6. 默认时间/配额为初始配置建议，未做性能测量；通过集成验收调整，不承诺模型完成时间。

### 12.2 已作出的设计取舍

- 本地 SQLite + 独立 worker；不依赖云队列。
- 受理用新 Receipt，最终用新 AgentResult；不扩大现有 core.tasks.ResultStatus。
- 首版一个请求一个外部任务；不实现跨后端 DAG。
- 会话 reset 与任务取消分离；旧 WebChat generation 的结果留在任务中心。
- 全部状态和产物可通过持久任务查询获得；不能以聊天消息作为唯一结果存储。
- 显式委派先上线，自动委派灰度；多后端最终用真实适配器验证。

### 12.3 延后

远程 worker 集群、分布式事务、多用户 WebUI RBAC、QQ 私聊、后台递归 Agent 团队、自动合并/部署、通用插件市场、自动安装所有编程 Agent、统一重构现有 Cron/Skills/Comes，以及将外部用量完全并入现有账单系统。

## 13. 完成定义

- [ ] COMETA_ENABLED=false 时，现有聊天/Memory/Comes/Skills/Cron 行为保持一致。
- [ ] 明确委派和两类自动委派场景（联网能力缺口、长程编码）均有可复现验收。
- [ ] 提交在落库后立即返回 receipt，不等待 Agent 完成；重复提交不会创建第二个任务。
- [ ] 同群长任务运行期间可以继续聊天和查询/取消任务。
- [ ] 所有进度来自真实事件，等待输入和失败不被显示为“仍在思考”。
- [ ] 重启、断流、启动确认丢失和租约过期均有故障注入测试，不能盲目重复执行。
- [ ] 权限、来源用户、原会话和审批请求绑定可靠，跨用户/跨群不能读写任务。
- [ ] 最终结果保留来源、验证记录、未完成项；产物可实际获取，不能只返回本机路径。
- [ ] 任务终态与投递状态分开；delivery_unknown 不自动重复发送。
- [ ] Windows/Linux 子进程终止与工作区清理验证通过，没有误杀其他 Agent。
- [ ] Codex 与第二个真实 Agent 通过共用契约测试和一次端到端交付。
- [ ] SDK/runtime 版本矩阵、配置示例、安装及恢复文档齐备。
- [ ] 对实际改动符号完成最新 impact；提交前 detect_changes 无未处理的 partial/truncated 结果。

