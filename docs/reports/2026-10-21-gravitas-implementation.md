# Gravitas 实施记录（2026-10-21）

目标：[Gravitas 稳态系统工程方案](../plans/2026-10-21-gravitas-engineering-plan.md)。工作分支 `codex/gravitas-implementation`，基线 `origin/main@c662746`。本报告按工作包记录代码、风险、验证和外部验收边界；不替代 live、平台或 clean VM 证据。

## 已提交工作包

- G00：默认 Facade 模型调用进入既有资源闸门；scheduler waiter 取消安全；清理器对零、缺失、非法和越界水位保守保护。提交 `709a4b4`、`82f377d`、`88de58c`、`f03eb0f`。隔离组合回归 78 passed。
- G01：版本化合同、严格配置、ControlClock、admission DTO 与包布局。提交 `dbcbe41`。定向合同/发布/flow 回归 65 passed；Python 3.10/3.11/3.12 导入与 Standalone/OneClick 包内导入通过。
- G02：有界事实与 shadow 控制器，提交 `8e87c6c`。
- G03a：有界公平调度票据，提交 `dd8bb72`。
- G03b：生产模型调用迁入共享 executor，提交 `6c625f9`。

G02 与 G03a/b 的逐提交回归记录保留在提交历史与当时的工作状态记录中；本轮 G03c 回归重新覆盖 Gravitas、模型注册/客户端、memory、Vision、AstrBot、插件脚手架、Compact、Planner、Router 与 compact 评估路径。

## G03c 实际资源交接与 attempt 预算

实现项：

- RoleBackend 逐真实 endpoint slot 申请共享票据；主端点票据释放后才等待 fallback 票据。主端点最多两次 transient 请求，配置的 fallback 最多一次；adaptive payload 形状改变后，每次新 HTTP 请求都须重新取得票据。
- 一个业务调用的真实 HTTP 请求总数最多 3 次；同一 scope 下阶段/适配器嵌套共享预算。队列拒绝、逾期与未实际发出请求的取消不消耗 attempt 额度，也不伪装成 endpoint failure。
- managed OpenAI-compatible HTTP 路径一次 executor 调用只发一个请求；raw 兼容 API 保留旧调用合同。AstrBot、Vision、embedding、memory consolidation、Compact 与 plugin scaffold 使用共享执行入口。
- `probe_consolidation.py` 的单阶段与两阶段调用也进入实际端点队列；两阶段共享同一 3-request 预算。live 评估包装改为透明观察器，保留 RoleBackend primary/fallback 路由和 endpoint 身份，录制只收成功回复。

### GitNexus 与调用审计

GitNexus 1.6.12 索引基于 G03b `6c625f9`，尚未包含本工作树改动。编辑前 impact 摘要：

- `RoleBackend.generate_detailed` LOW，1 直接调用者；一处接收者解析不完整，已继续审查 RoleBackend 调用和 raw API 兼容边界。
- `RoleBackend` MEDIUM，67 impacted、14 个直接导入；包含动态 `LLMBackend` 分派，故以源码和定向测试补证。
- `core/llm/lm_studio.py` MEDIUM（37 impacted、2 direct）；`core/llm/openai_client.py` LOW（13 impacted、2 direct）；插件脚手架低风险并检查其生成流程。
- G03c 初次编辑后才补跑 `execute_model_call` exact symbol impact：CRITICAL，8 个直接调用者、6 个推断流程、11 个模块。该遗漏已向用户报告；之后逐一审查 Facade、Router fallback、Compact、Planner、TurnService、CaptureGate、Consolidator 与评测接线，增加包装器路由回归。此事记为流程偏差，低风险文件结果不豁免该符号风险。
- `scripts/probe_consolidation.py` 的 `run_window` LOW（4 impacted/2 direct），`run_window_two_stage` LOW（3/1）。两个评估脚本文件 impact UNKNOWN/0；按规则执行文本/入口补查。之后又对已改的 `run_compact_evaluation` 补跑 exact impact，LOW（2 impacted/1 direct/1 process）；回放脚本 `main` LOW（1 impacted/1 direct）。这两项函数级 impact 也在编辑后才补查，已向用户说明并记为门禁偏差；脚本调用通过观察器回归覆盖，没有将文件零边或函数低风险解释为事前许可。

源代码调用搜索结果：业务模块中新增的实际模型尝试均经过 `execute_model_call` / `execute_model_operation` / `execute_model_stream`；搜索命中的 `generate` / `generate_detailed` 直接调用仅为共享 executor 和低层兼容实现内部路径。未发现未解释的生产模型调用旁路。该结论只覆盖当前仓库源码，不能证明未安装插件或外部消费者的调用行为。

### 验证

- `STELLA_HOME=/tmp/stella-gravitas-g03c-20261021 .venv/bin/python -m pytest ...`（本轮 G03 相关模块与入口集合）：**446 passed**。未启动真实模型、Bot 或平台。
- `.venv/bin/ruff check .`：全仓通过。
- `.venv/bin/python -m py_compile` 覆盖模型执行器与三个脚本：通过。
- `scripts/generate_message_flow.py` 生成 `message-flow.cddec54b82c7.json`（141 nodes、139 source-resolved、8,927 closure sites、13,773 reachable symbols）；随后 `--check` 通过。
- `scripts/check_docs.py`：119 files / 1,238 local links / 577 migration anchors / 0 errors；`feature_list.json` JSON parse 与 `git diff --check` 通过。
- GitNexus 1.6.12 `detect-changes --scope all`：21 changed files / 74 symbols / 31 affected processes / CRITICAL；`--scope compare --base-ref main`：441 files / 652 symbols / 59 affected processes / CRITICAL。完整展示上限设为 2,000，CLI 未输出 partial/truncated 标记；CRITICAL 是累计高风险调用路径，不等于本包每个文件都为 CRITICAL。

## G04a 入口总期限

提交 `c3d4c4d` 在可信入口创建单调时钟 `Deadline`，并把同一实例贯穿 ChatContext、Facade 默认 provider 与旧 TurnService 生成入口。QQ 群聊/私聊在预处理前创建；两类主动轮次在锁与整合工作前创建；WebChat 在 `run_turn` 开始、规范化和数据库操作前创建。直接调用 `RuntimeFacade.submit_turn` 的旧调用方仍可不传参数，由 Facade 创建兼容期限。

- `ChatContext.turn_deadline` 是 runtime-only 字段，不进入 projection JSON。进程级 `system_control_clock()` 保证 Deadline 创建者与执行端使用相同 clock identity；未带 deadline 的旧 `role_call_context` 调用保留原时钟行为。
- Facade 的旧 `deadline` 参数仍表示生成阶段上限；新增 `turn_deadline` 后，生成等待取总剩余时间与旧阶段上限的较小值。默认 pipeline provider 和 TurnService 生成调用也接收同一 Deadline。
- 编辑前 exact impact：`_run_turn_via_engine` HIGH（4 direct / 3 inferred flows）；`role_call_context` CRITICAL（12 direct / 7 processes / 13 modules）；`ChatContext` MEDIUM（29 impacted / 12 direct imports）；`SystemControlClock` MEDIUM（47 / 4 direct）。已在编辑前向用户提示 HIGH/CRITICAL。`RuntimeFacade.submit_turn` LOW（1 direct edge）、`TurnService.generate_reply` LOW（2 direct / 2 flows）、WebChat `run_turn` LOW（1 direct / 2 flows）、两个 proactive helper LOW；Facade 的生产入口图解析较少，另逐处源码审查。`handle_chat` / `handle_private_chat` 为 UNKNOWN/0 edge，通过 `on_message` 装饰器注册源码确认入口。测试函数 impact 均 UNKNOWN/0，`pyproject.toml` 的 pytest `testpaths = ["tests"]` 与测试收集补证其执行方式。
- 定向回归：`STELLA_HOME=/tmp/stella-gravitas-g04a-20261021 .venv/bin/python -m pytest tests/runtime/test_facade_turns.py tests/runtime/test_turn_service.py tests/test_context_projection_identity.py tests/gravitas/test_g03_model_calls.py tests/test_ai_gateway_deterministic_reply.py tests/test_private_chat_ingress.py tests/runtime/test_ingress_native.py tests/runtime/test_proactive_native.py tests/webui/test_webui_chat.py tests/test_capture_ingress_gating.py -q -x` 覆盖 Facade、TurnService、上下文 projection、model_calls、QQ 群聊/私聊、proactive、WebChat 与 CaptureGate，共 **77 passed / 1 warning**。一个现有 NoneBot fixture 提示未发现 adapter；不影响结果。
- `.venv/bin/ruff check .`、改动文件 `py_compile`、`python scripts/check_docs.py`（119 files / 1,238 local links / 577 anchors / 0 errors）通过。源码变化使旧 flow archive body hash 漂移，生成新不可变归档 `message-flow.41882cf74ffa.json`（141 nodes / 139 source-resolved / 9,044 closure sites / 13,873 reachable symbols），随后 `--check` 通过。
- 提交前 GitNexus：scope all 15 files / 39 symbols / 24 affected processes / CRITICAL；compare main 451 files / 774 symbols / 67 affected processes / CRITICAL。完整统计命令退出 0，未返回 partial/truncated；compare 是累计分支风险。CLI 只展示部分符号/流程样例，不代表计数被截断。

G04b 将把总期限扩展到锁、prepare、路由/工具等待和 finalize；G04c 再对每个副作用和逐段发送设围栏。G04a 完成不代表整轮总期限已闭合。

## G04b 域内期限传播

代码提交 `6458764` 把总 Deadline 贯穿 Facade/WebChat 会话锁、整个 `prepare_turn`（包含 Router、Planner、工具与并行分支）、模型队列/生成，以及所有 finalize 分支。新增 `gravitas.errors.DeadlineExceeded` 作为专用控制信号；`gravitas.deadlines.run_with_deadline` 懒启动阶段工作，区分总期限到期与旧阶段 timeout cap，`lock_with_deadline` 超时后只回收本次已取得的锁。

- 旧 `RuntimeFacade.submit_turn(deadline=...)` 继续作为生成阶段上限：只有该 cap 到期且总期限仍有余量时才保留 legacy 兜底；总期限到期则记为 `deadline_exceeded` 并抛出控制信号。Facade 和直接 `TurnService.run` 路径都按总剩余时间限制生成与 finalize；在期限已过时不启动新阶段，也不为未启动的生成虚增调用次数。
- Planner、Router 和 Capability hook 显式传播 DeadlineExceeded；队列延期仅在总期限仍有效时走原降级语义。QQ 群聊、私聊与 proactive 入口遇到总期限到期时静默结束，不落入通用异常兜底回复。WebChat 独立会话锁也由同一 Deadline 限制；HTTP 层保留错误帧语义。G04c 仍需围住 Facade 返回后的副作用和最终发送边界。
- 编辑前精确影响绑定 `af35e11`：`TurnService.prepare_turn` HIGH（7 impacted / 3 direct / 3 processes / 4 modules）、`finalize_turn` HIGH（同值）、`generate_reply` HIGH（4 / 2 / 2 / 3）；`RuntimeFacade.submit_turn` LOW（3 / 1 / 1 / 1）。既有 `Deadline` DTO 为 HIGH（83 impacted / 22 direct），没有修改；控制异常放在独立 `gravitas/errors.py`。Planner `maybe_plan`、`activate_capabilities`、QQ handler 图结果为 UNKNOWN/0，已逐项用动态调用、hook 注册和 `on_message` 装饰器源码补证；proactive 与 WebChat 目标有 LOW 边并按直接调用链补查。该组编辑前图分析已向用户提示 HIGH 项。
- 定向验收命令：`STELLA_HOME=/tmp/stella-gravitas-g04b-20261021 .venv/bin/python -m pytest tests/runtime tests/capability tests/test_planner.py tests/test_ai_gateway_deterministic_reply.py tests/test_private_chat_ingress.py tests/webui/test_webui_chat.py tests/test_capture_ingress_gating.py -q -x`：**470 passed / 1 warning**。warning 是现有 NoneBot fixture 未发现 adapter。最初两次 proactive 测试因临时根目录及其 `memory/` 子目录尚未创建而失败；建立隔离目录后重跑通过。该路径只在 `/tmp`，未访问用户数据。
- `.venv/bin/ruff check .`、上述改动 Python 文件 `py_compile`、`git diff --check` 通过。`python3 scripts/check_docs.py` 为 119 files / 1,238 local links / 577 migration anchors / 0 errors。源码变化生成不可变归档 `message-flow.c36cccb0c356.json`（141 nodes / 139 source-resolved / 9,394 closure sites / 13,943 reachable symbols），之后 `python3 scripts/generate_message_flow.py --check` 通过；中间草稿 `message-flow.747474cf208a.json` 已移除。
- GitNexus 编辑前 impact 索引落在 `af35e11`；提交后为追平 G04b 提交 `6458764`，用仓库 pinned CLI 1.6.11 全量重建，状态显示 indexed/current commit 均为 `6458764`、覆盖 1,812 files。重建器报告流程候选受预算截断（2,851 candidates 未排序、24 traces depth-capped、801 callees 被 branch cap 跳过、45 walks 超 per-entry budget）；流程路径属于下界，不宣称完整。提交前 `detect-changes --scope all`：11 files / 33 symbols / 34 affected processes / CRITICAL；`compare --base-ref main`：454 / 785 / 70 / CRITICAL（累计）。第一次 all 因 graph query interrupted 返回 PARTIAL，按门禁重跑成功；最终 all/compare 输出未报告 partial/truncated。当前 launcher 1.6.11 与编辑前记录使用的 1.6.12 不同，此差异保留在证据中；CLI 展示列表是样例，计数为报告值。状态文档编辑前的 exact File impact 为 LOW：本报告 11、`progress.md` 26、`session-handoff.md` 19、`feature_list.json` 19 impacted files；File 图未包含过程轴，且已用相对链接与状态引用检查补证。
- 状态记录提交的 GitNexus 检查：scope all 为 4 files / 7 symbols / 0 processes / LOW；compare/main 为 457 / 796 / 59 / CRITICAL（分支累计）。首次 compare 因图查询中断标记 PARTIAL，重跑后退出码 0 且无 partial/truncated。该轮 `check_docs.py` 为 119 files / 1,240 local links / 577 anchors / 0 errors，`feature_list.json` 可解析，`git diff --check` 通过。

## G04c 副作用与最终发送围栏

代码提交 `8160289` 与补充提交 `5b87efa` 把现有 turn deadline 延伸到用户可见的最终发送和 WebChat HTTP 完成边界：

- `deliver_lines` 新增可选 Deadline。未到期前不启动下一段；段间隔与发送 callback 都受同一 deadline 限制。若 callback 尚未开始即到期，则不产生发送或回执；callback 开始后超时或取消，当前段落一条 `unknown` 回执、停止后续段且不重试。
- 超时时不等待忽略取消的 callback 收敛：在途任务保留为进程内隔离任务，该 conversation key 的后续发送被围栏；活动或隔离中的 callback 总数最多 16，达到上限时跳过新发送并记录 flow decision。callback 实际结束后释放隔离项。该隔离是单进程状态，进程重启后的在途 adapter 状态仍属于 unknown。
- QQ 群聊、私聊普通回复、两类 Cometa ACK、主动 @ 和主动群聊六个 `deliver_lines` 调用点都传入 `ctx.turn_deadline`；四个 adapter callback 也向 `OutboundService.send` 传入同一 Deadline。物理消息每个分片调用 exporter 前再次检查，deadline 到期不启动后续分片；已 ACK 的前段与未启动后段返回 partial，逻辑回执仍保守记为 unknown。
- WebChat router 在 SSE stream 开始时创建 120 秒总期限，并将同一 Deadline 传入 `run_turn`、Facade 与会话锁。用户消息/回复采集、social receipt 和 HTTP complete 帧之前检查期限；超时返回现有 SSE error 事件“回复超时”。
- 外部取消仍继续传播；如果物理发送 callback 已开始，当前段会先记 `unknown`，之后取消不触发第二段。期限前未开始的发送不虚构为 `failed` 或 `unknown`。

### GitNexus 与调用审计

编辑前索引绑定 `8258736`，内容覆盖 1,812 个文件。主要精确影响：`deliver_lines` HIGH（10 impacted / 6 direct / 3 inferred processes / 2 modules），涉及 `handle_chat`、`handle_private_chat` 与 `proactive_speak_job`；`run_with_deadline` CRITICAL（14 / 6 direct / 4 processes），包含 Planner 与评估路径。`OutboundService.send` 为 MEDIUM（11 / 6 direct）；相同文件内的 `MessageExporter.send` 是 UNKNOWN/0 图边，已按 Protocol 声明和 exporter 实现补查；不修改该 adapter 接口。WebChat `run_turn` 为 LOW（2 个 router flows）；router handler `chat` 图为 UNKNOWN/0，已检查 `/api/v1/chat` 路由注册与 `run_turn` 实际调用。HIGH/CRITICAL 项在编辑前已向用户报告；没有用 shared-axis 风险豁免。

提交 `8160289` 后 GitNexus 全量索引更新至该提交，状态为 up-to-date、覆盖 1,812 个文件。流程推断保留工具自身预算限制：2,853 个候选入口未排名、24 条 trace 达深度上限、813 个 callee 被分支上限跳过、45 条 walk 达单入口预算；827 flows 是下界，不能视为完整流程全集。

### 验证

- 隔离回归：
  `STELLA_HOME=/tmp/stella-gravitas-g04c-20261021 .venv/bin/pytest tests/runtime tests/capability tests/test_planner.py tests/test_ai_gateway_deterministic_reply.py tests/test_private_chat_ingress.py tests/webui/test_webui_chat.py tests/test_social_delivery.py tests/test_transport_outbound.py tests/test_capture_ingress_gating.py tests/cometa/test_gateway_wiring.py -q -x`
  **517 passed / 1 warning**。warning 是既有 NoneBot fixture 未发现 adapter。新增回归覆盖期限前不发送、超时/取消后 unknown 且不启动下一段、忽略取消的 callback 隔离与容量拒绝、物理分片围栏，以及 WebChat 超时 SSE error frame。
- `.venv/bin/ruff check .` 通过；G04c 修改的 Python 文件 `py_compile` 通过；`git diff --check` 通过。
- `.venv/bin/python scripts/check_docs.py`：119 files / 1,241 local links / 577 anchors / 0 errors。
- 源码已有 message-flow 节点仅 body hash 变化、拓扑不变；最后归档为 `message-flow.c00e93615f8b.json`（141 nodes / 139 source-resolved / 9,489 closure sites / 14,108 reachable symbols），`.venv/bin/python scripts/generate_message_flow.py --check` 通过。较早提交的 `message-flow.d378d11c527d.json` 保留为不可变历史归档。
- 两次代码提交前 GitNexus 1.6.11 `detect-changes --scope all`：10 files / 40 symbols / 15 processes / HIGH；`--scope compare --base-ref main`：464 files / 840 symbols / 72 processes / CRITICAL（累计分支风险）。此时 scope=all 也包含未提交的 G04c `progress.md` 与本报告更新；两次命令退出码为 0，无 partial/truncated 标记。流程列表只是 CLI 展示样例，计数按工具摘要记录。
- 状态记录提交前检查：GitNexus scope all 4 files / 10 symbols / 0 processes / LOW；compare main 465 files / 849 symbols / 72 processes / CRITICAL（累计），无 partial/truncated。文档门禁 119 files / 1,241 local links / 577 anchors / 0 errors；`feature_list.json` JSON parse 与 `git diff --check` 通过。

此阶段只验证离线测试和 fake callback，没有真实 QQ/WebChat、模型、adapter、跨进程或 clean VM 验收。G04 软件包完成不代表 V1 验收完成；整体仍 **NOT READY**。

## G05 压力闭环与记忆边界

代码提交 `e7ee716` 将共享资源压力和 backlog 限制接入可延迟的后台路径：

- 压力状态保持 NORMAL → CONSTRAINED → RECOVERING → NORMAL。CONSTRAINED 仅允许到龄任务在显式完整性健康时占用最小份额；RECOVERING 每 10 秒最多开放一个新后台 token，空闲时间不会累计成恢复突发。主动发言机会在压力下静默过期，不排队补发。
- Memory capture 在 `BEGIN IMMEDIATE` 写事务中只读取待整合行数与最早时间，不把消息正文传给控制器。会话/实例高水位为 500/5000 行，低水位为 250/2500 行，年龄阈值 600 秒；这些是离线夹具起点，不是生产 SLO。达到阈值时新行写入前拒绝，结果码 `not_captured_pressure`，不排队、不补录，旧来源与 checkpoint 保持不变。缺口状态仅含计数、起止时间和低基数原因码。
- Consolidation 与 Compact 在开始后台模型工作前检查资源准入，拒绝后来源行与成功水位保留；proactive 检查在业务流程入口；capture 压力状态独立于 CaptureGate readiness。旧 schema v1 profile 可省略新增 backlog 配置字段并加载夹具默认值。
- 配置为 `enforce` 时 controller 仍因 coverage 不完整而拒绝启用，保持 shadow/off 业务语义；主动路径的异常只在实际 enforce 时 fail closed。现阶段没有 producer 发布可信完整性事实，因此受压时的 aged bypass 会保持拒绝，不能宣称后台会在真实故障中自动恢复。
- 更新了发布测试合成源码树以包含既有 G01 根包 `gravitas/`。同步修正 proactive fake task/outbound 对 G04c deadline wrapper 的测试签名。

### GitNexus 与接线范围

编辑前基于 G04c HEAD `6f95a20` 的精确 upstream impact：`evaluate_pressure` LOW；`MemoryConsolidator.backlog` 与 `consolidate_group` LOW；`compact_once` HIGH（9 impacted / 3 processes）；`CaptureGate.capture_allowed` 方法 HIGH（状态、记忆与测试调用方）；`MemoryConsolidator._consolidate_group_core` HIGH（7 impacted）；`record_message` CRITICAL（18 impacted / 10 inferred processes，另有 3 个接收者未解析）；`_proactive_speak_impl`、`setup_gravitas`、`GravitasController.tick`、`default_config` LOW。HIGH/CRITICAL 在编辑前已向用户提示。

`capture_allowed` 模块函数、嵌套 scheduler 函数 `consolidation_drain_job`、`ChatContext.capture_result` 的图结果为 UNKNOWN/0；源码与注册入口审计确认 capture API 的内部/测试引用、定时 job 装饰器注册、capture result 写入与测试读取，未把零图边当作无人调用。索引重建保留流程候选预算下界（2,854 候选入口被裁剪、24 条 trace 达深度上限、813 callee 被跳过、45 walks 达预算）。

### 验证

- 隔离 G05 组合回归：
  `STELLA_HOME=/tmp/stella-gravitas-g05-20261021 .venv/bin/pytest tests/gravitas tests/test_consolidator_core.py tests/test_session_compact.py tests/test_db_cleaner.py tests/test_memory_capture_gate.py tests/test_capture_ingress_gating.py tests/test_message_relations.py tests/test_proactive_rules.py tests/test_proactive_at_flow.py tests/test_ai_gateway_deterministic_reply.py -q -x`
  **216 passed / 1 现有 NoneBot fixture warning**。新增覆盖 schema v1 兼容、恢复 token 防累积、到龄共享的 integrity 硬门、capture 高低水位滞回、shadow 行为等价及拒采不写正文。
- 全量 Python suite：`STELLA_HOME=/tmp/stella-gravitas-g05-full-20261021b .venv/bin/pytest tests -q`：**3968 passed, 29 skipped, 1 warning / 355.00s**。第一次全量尝试得到 3954 passed、29 skipped、14 failed：flow manifest 尚未按新源码生成；多个 release staging 测试的合成树漏建 `gravitas/`；共用一个临时 `STELLA_HOME` 的 WebUI 用例出现 401。生成新 flow archive、补全合成树并改用全新隔离根后再次全量通过。warning 为既有 class-scoped fixture 的 pytest deprecation。
- `.venv/bin/ruff check .` 与 G05 改动 Python 文件 `py_compile` 通过；`scripts/check_docs.py`：119 files / 1,241 links / 577 anchors / 0 errors；`generate_message_flow.py --check` 通过。新归档 `message-flow.b72338474a6c.json`：141 nodes / 139 source-resolved / 9,536 closure sites / 14,275 reachable symbols。`git diff --check` 与 `feature_list.json` JSON parse 通过。
- 提交前 GitNexus 1.6.11 `detect-changes --scope all`：13 files / 44 symbols / 3 affected processes / MEDIUM；`--scope compare --base-ref main`：469 files / 867 symbols / 75 processes / CRITICAL（累计分支风险）。CLI 无 partial/truncated 标记；展示列表是摘要样例。代码提交 `e7ee716`。

本阶段只有隔离 SQLite、fake 与离线测试；没有启动 Bot、真实模型、QQ/WebChat、Cometa 子进程或 clean VM，也未使用用户生产数据库。coverage 未闭合时 enforce 保持拒绝；G05 完成不代表发布就绪，整体仍 **NOT READY**。

## G06 只读控制面诊断

代码提交 `21fb77f` 增加 Gravitas 只读状态视图：状态 API 只读取缓存快照，不触发 controller tick、探针或新的采集；按配置资源白名单展示事实、年龄与 fresh 标记、压力阈值、策略/配置版本和 digest、boot ID、未评估维度与显式 `applied_ack=not_received`。未知来源/原因不透出任意字符串，未知 scope 只计数；状态 payload 不包含消息正文、凭据或原始配置。

- deploy process、CLI 与 authenticated Dashboard 透传并呈现同一快照；Dashboard 提供中英文文案。没有状态事实时显示未评估，不将缺失事实转成 healthy，也不改变 shadow/enforce 决策。
- Flow catalog/inventory 登记 Gravitas setup、controller run、status API 三个观测节点和 runtime entries；明确这些是组件/控制面节点，不宣称它们是消息入口流程根。拓扑版本为 `2026.10.21`，生成并保留不可变归档 `message-flow.d2b36de1444a.json`（144 nodes / 142 source-resolved / 9,637 closure sites / 14,346 reachable symbols）。
- 编辑前 GitNexus 对 status collection、controller snapshot、CLI health 与 flow coverage/validator 的 upstream impact 均为 LOW。`set_gravitas_status_provider` 为 UNKNOWN/0；源码审计确认唯一装配点是 `gravitas_bootstrap.py` 的启动注入。状态文档刷新前的 File impact：`progress.md` LOW（26 impacted / 3 direct）、`session-handoff.md` LOW（19 / 2）、`feature_list.json` LOW（19 / 2）；报告文件不在图中，显示 UNKNOWN。引用扫描确认这些状态文件仅由根级工作流/交接规则、`check_docs.py` 的状态一致性校验、发布打包排除项和文档合同测试使用；报告路径由 `progress.md`、handoff 与 feature evidence 链接，没有发现运行时调用者。UNKNOWN 与文档文件风险尺度限制已通过源码/文本补证，不用风险等级豁免。
- 编辑前索引重建于提交 `21fb77f`，GitNexus 1.6.11：26,572 nodes / 60,855 edges / 1,098 clusters / 828 flows。构建跳过 31 个超过 512 KB 的生成归档；流程推断有预算截断（2,867 candidate entry points 未排序、24 条 trace 达深度上限、814 callees 被跳过、45 walks 达预算），因此不把缺失流程解释成不存在调用。此限制与 G06 源码 impact 结论分开记录。

### G06 验证

- 隔离 Python 回归：`STELLA_HOME=/tmp/stella-gravitas-g06-final-20261021 .venv/bin/pytest tests/gravitas/test_g02_control_loop.py tests/gravitas/test_g06_status.py tests/test_deploy_process.py tests/test_deploy_cli.py tests/test_status_api.py tests/webui/test_webui_redaction.py tests/observability/test_internal_flow_inventory.py -q -x`：**97 passed / 1 existing PytestRemovedIn10Warning**。警告为现有 class-scoped fixture method deprecation。
- Dashboard 直接调用已安装的 Node 工具入口：`vue-tsc.js --noEmit` 通过；`vitest.mjs run` 为 7 files / **101 passed**；`vite.js build` 成功。构建仅有既存分包提示和大 chunk (>500 KB) 警告。项目 pnpm 包装器在依赖预检时报 `ERR_PNPM_IGNORED_BUILDS`（esbuild/vue-demi）；没有变更 build approval，使用本机已安装工具入口完成以上检查。
- 本地浏览器 fake API 验收：临时 Vite preview 与 mock 服务仅绑定 localhost，使用测试 token 和合成状态；authenticated `/gravitas` 页面显示 shadow/configured mode、fact age/pressure、unassessed、`not_received` acknowledgement、阈值与版本/digest。Welcome 页面可选 readiness 请求 `/providers/endpoints` 返回 404，但 Gravitas 页面加载和展示正常。临时服务、配置和 token 已清理；没有连接模型、Bot 或平台。
- `.venv/bin/ruff check .`、改动 Python 文件 `py_compile`、`python scripts/generate_message_flow.py --check` 与 `git diff --check` 通过。Flow check 对应归档 `message-flow.d2b36de1444a.json`。
- 提交前 GitNexus 1.6.11 `detect-changes --scope all`：16 files / 40 symbols / 2 processes / MEDIUM；`--scope compare --base-ref main`：484 files / 938 symbols / 69 processes / CRITICAL（累计分支风险）。两个命令退出 0，未报告 partial/truncated；compare 值不是 G06 局部风险。
- G06 状态/evidence 文档提交前 GitNexus：scope all 为 4 files / 7 symbols / 0 processes / LOW；compare main 为 489 files / 982 symbols / 78 processes / CRITICAL（累计）。均退出 0 且无 partial/truncated 标记。`scripts/check_docs.py` 为 119 files / 1,244 local links / 577 migration anchors / 0 errors；`feature_list.json` 可解析，`git diff --check` 通过。

G06 仅证明离线状态/API、合成 Dashboard 与本地 flow 目录。生产账号/数据、真实模型、QQ/WebChat、Cometa 跨进程、干净 VM 和发布验收均未执行；整体继续 **NOT READY**。G07 离线组合验收记录如下，之后进入 G08。

## G07 V1 组合验收与发布夹具

代码提交 `bfb1fa2` 增加 V1 场景清单、隔离评测 runner 和 Python CI 步骤：

- `tests/gravitas/fixtures/v1/suite.json` 将 S01–S12 按冻结 inventory 顺序映射到现有 runtime、调度、期限、回执、记忆和控制面回归，并逐项核验计划版本、场景与不变量。冻结的 `docs/plans/2026-10-21-gravitas-inventory.json` 未改动。
- `scripts/run_gravitas_evaluation.py` 要求显式 suite 与空 workdir；每个场景进程使用独立临时 `STELLA_HOME`，清除继承的 Gravitas/模型评估配置和 pytest 附加参数。每次评估两轮执行 S01–S12，保存每条测试日志、源文件指纹、结构化 `ExperimentReport` 和同 seed 语义摘要；失败时输出不变量、seed、策略版本和事件前缀。
- 状态模型对 off/shadow 各回放 10 个连续固定 seed（20261021–20261030），每个 256 个事件，共 2,560 个合成事件；核验资源/队列上限、身份与 endpoint 拒绝、期限、unknown 不重放、记忆成功水位/清理以及 shadow 效果等价。CI 的 3.11 job 显式运行固定 10 seeds 并上传报告/日志；原 Python 3.10/3.11/3.12 测试矩阵不变。
- runner 将 Standalone Python 与 OneClick Python resources 分别暂存，并从暂存根导入 `gravitas.controller` 和 `core.runtime.facade`。这是包布局/import smoke，不是 Windows installer 执行、clean VM 或发布验收。

### G07 验证与风险

- 定向守卫：`STELLA_HOME=/tmp/stella-gravitas-g07-unit-final-20261021b .venv/bin/pytest tests/gravitas/test_g07_v1_scenarios.py -q -x`：**4 passed**。全量隔离回归：`STELLA_HOME=/tmp/stella-gravitas-g07-full-final-20261021 .venv/bin/pytest tests -q -x`：**3,976 passed / 29 skipped / 1 existing PytestRemovedIn10Warning，359.95s**；warning 是 `tests/observability/test_internal_flow_inventory.py` 的 class-scoped fixture method deprecation。
- 离线组合命令：`STELLA_HOME=/tmp/stella-gravitas-g07-cli-home-final2-20261021 .venv/bin/python scripts/run_gravitas_evaluation.py --suite tests/gravitas/fixtures/v1 --workdir /tmp/stella-gravitas-g07-eval-final2-20261021 --seed 20261021 --trace-seeds 10 --steps 256 --repeat 2`。结果 `status=completed`，S01–S12、generated trace、package layout/import 与 same-seed semantic digest 全部 PASS；报告 digest `6d35e75631c1861239cb4ac2cd8555a8e6a5058e`，两个 scenario replay digest 一致。live model/platform 与 clean VM/release 明确为 SKIPPED。完整离线 JSON 位于该临时 workdir 的 `report.json`。
- `.venv/bin/ruff check .`、runner/test `py_compile`、`scripts/check_docs.py`（119 files / 1,244 local links / 577 anchors / 0 errors）、`scripts/generate_message_flow.py --check`（归档仍为 `message-flow.d2b36de1444a.json`）、CI YAML 解析和 `git diff --check` 均通过。没有生产 runtime/schema 改动；测试与包构建使用隔离 `/tmp` 路径。
- GitNexus 1.6.11 对新 runner 符号 `_trace_model` / `_evaluate_seeded_traces` 的 impact 查询均为 UNKNOWN（索引中无目标）；`.github/workflows/ci.yml` 文件同为 UNKNOWN。源码引用审计确认 runner 只由 G07 守卫测试导入，workflow 只在 Python 3.11 测试 job 调用它，且仓库 pytest `testpaths` 覆盖 `tests`。提交前 `detect-changes --scope all`：4 个暂存文件、未发现索引符号与 hunks 重叠；这不是“干净”或 LOW 结论，新增文件/CI 以源码审计补证。`compare --base-ref main`：493 files / 984 symbols / 78 processes / CRITICAL（累计分支风险）；两次都未报告 partial/truncated，compare 的累计风险不等于 G07 局部风险。

G07 的离线 V1 组合验收完成，但不会据此启用 enforce 或宣告 release READY。真实模型质量、QQ/WebChat 灰度、Cometa 跨进程恢复、Windows/Linux clean VM、实际 installer 和发布资产仍缺验收。下一步是 G08 依赖与存储分域恢复。

## G08 依赖与存储分域恢复

代码提交 `b78c72e` 增加 `gravitas.dependency_recovery`，将依赖与存储故障作为有界、分作用域的运行事实接入现有 owner：

- Endpoint、Provider、Connection 与 Storage scope 使用线程安全的进程内有界注册表。被动请求结果有序列围栏；迟到结果不能覆盖新一代状态。主动 probe 通过有期限的 single-flight lease、代际校验和每 scope/全局滑动预算，预算耗尽不会再发请求。恢复退避含注入随机源的 jitter，测试可用固定 seed。
- HTTP 401/403、配置/权限错误进入终止分类，避免重复探测；正常 transient 失败进入退避。事实快照只导出低基数类别、范围、年龄和有界 ID，不带异常文本、凭据或消息内容。
- Role model call 在真实端点实际取得 model slot 后记录结果；primary 失败不会被 fallback 成功清零。CapabilityProvider 的迟到成功不能清除更新的 cooldown。CaptureGate 保留自身 epoch 语义并共享 active-probe 限额；默认 LinkMonitor 只探测 OneBot V11，任意平台事件可报告连接存活，非 OneBot 平台没有等价心跳时保持 UNKNOWN。
- `connect_sqlite` 将 memory、social、Cometa、scheduling、knowledge、observability 数据库连接的错误按域分类。locked/busy 是 contention/degraded，不误报 corruption；readonly、disk-full 与 corrupt 分类区分。存储恢复只能来自显式维护成功，不启动自动 integrity probe，也不把读取成功当作库健康证明。
- 新增 S13/S14 的隔离单测，覆盖作用域互不污染、迟到成功围栏、single-flight/预算、错误分类和各存储域故障正反例。冻结的 `docs/plans/2026-10-21-gravitas-inventory.json` 未修改。

### G08 GitNexus 与验证

- 编辑前风险已向用户提示：`gravitas/model_calls.execute_role_model_call` CRITICAL（26 impacted nodes、2 inferred processes、10 modules）；`memory.timeutil.log_sqlite_error` CRITICAL（146 impacted、16 processes、8 modules），该符号未修改；CapabilityProvider HIGH（40/24）；CometaStore `_tx` HIGH（48/24）、`_read` HIGH（39/16）；`message_flow.py` HIGH（55/27）；scheduling migration MEDIUM、trace MEDIUM、knowledge schema LOW。UNKNOWN/零调用者结果按注册点和源码引用补证。GitNexus 过程图仍受 31 个大文件跳过、调用值流与流程推断预算影响：2,876 个候选入口、23 条深度截断 trace、810 个分支上限跳过的 callee、44 条预算截断 walk，不能把推断流程视作完整全集。
- 定向隔离回归：`STELLA_HOME=/tmp/stella-gravitas-g08-auth-focused-20261021 .venv/bin/pytest tests/gravitas/test_g08_dependency_recovery.py tests/gravitas/test_g03_model_calls.py tests/test_memory_capture_gate.py tests/test_link_monitor.py -q -x`：**60 passed / 4.03s**。最终全量回归：`STELLA_HOME=/tmp/stella-gravitas-g08-final-verify-20261021 .venv/bin/pytest tests -q -x`：**3,989 passed / 29 skipped / 1 existing PytestRemovedIn10Warning，220.82s**。warning 是 `tests/observability/test_internal_flow_inventory.py` 中 class-scoped fixture method 的既有弃用提示。
- 最终全量回归前曾有两次整套运行分别在 WebUI submit replay 与 Cometa shutdown 用例中失败；两个单例重跑均通过（29 passed、1 passed），随后第四次全量运行完整通过。未确认这两次失败的根因，作为间歇性测试稳定性风险保留。
- `.venv/bin/ruff check .`、所有改动 Python 文件的 `.venv/bin/python -m py_compile`、`scripts/check_docs.py`（119 files / 1,246 links / 577 migration anchors / 0 errors）、`scripts/generate_message_flow.py --check` 与 `git diff --check` 均通过。最终 flow 归档 `message-flow.643390a24eac.json`：144 nodes / 142 source-resolved / 9,637 closure sites / 14,624 reachable symbols。
- 提交前 GitNexus 1.6.11 `detect-changes --scope all --repo Stella_project --limit 50000`：13 files / 47 symbols / 31 affected processes / CRITICAL；`--scope compare --base-ref main --limit 50000`：503 files / 1,076 symbols / 113 processes / CRITICAL（累计分支风险）。两条命令均退出 0。提高展示上限后统计不变；compare 明示符号展示清单 capped，但计数和风险覆盖全量变更；all 的符号/流程输出是样例。未返回 partial/truncated 标记。
- G08 状态文档提交前，GitNexus all 为 4 files / 7 symbols / 0 processes / LOW；compare/main 为 506 files / 1,076 symbols / 113 processes / CRITICAL（累计）。`check_docs.py` 为 119 files / 1,248 links / 577 anchors / 0 errors，`feature_list.json` JSON parse 与 `git diff --check` 通过；compare 的展示清单仍 capped，统计覆盖全量。
- 全部 pytest 使用隔离 `/tmp/stella-gravitas-*` 的 `STELLA_HOME`。没有连接模型、Bot、QQ/WebChat、真实平台或跨进程 worker；没有对用户数据库运行探针。G08 的 S13/S14 仅为本地软件回归，不能据此关闭真实依赖/存储恢复验收。

## G09 Cometa 策略传递与受控 worker 恢复

代码提交 `ddb1c53` 增加默认关闭的跨进程策略文件与 worker ACK：

- `cometa/policy_transport.py` 定义严格 schema=1 信封，身份绑定 instance/controller boot/worker/process digest/config hash；文件路径以 `STELLA_HOME` 和 instance 哈希派生，读写有尺寸上限、原子替换、POSIX 权限与 symlink 防护。内容不含任务正文、目标 ID 或凭据。worker 校验时间偏差、TTL、revision/replay 和 monotonic 期限；失效时只阻止新 claim，租约续期、deadline、恢复扫描与控制消费继续运行。重复读同 revision 不延长 TTL。
- Bot 侧每 2 秒发布，worker 以独立 ACK 回报实际应用结果；Gravitas 状态只有看到当前 revision 的匹配 ACK 才显示 applied。策略检查紧贴每次 DB claim。`PolicySnapshot` 实现未改；`Operation` 仅新增 `cometa.claim` / `cometa.restart` 两个子门禁用于授权新操作。
- 可选自动重启默认关闭，需要新鲜策略允许、DB 可达、旧 owner lease 已过期且无活动 attempt；退避和每窗口预算有限，新 worker 以新身份启动并执行现有恢复扫描。日志明确重启成功不证明任务或投递成功。
- 双语 Cometa 指南记录开关、信任边界及 ACK 语义。冻结的 `docs/plans/2026-10-21-gravitas-inventory.json` 未改。

### G09 GitNexus 与验证

- 编辑前 upstream impact 已刷新并向用户报告：`CometaWorker._tick` 与 `claim_next_task` 为 LOW（各 3 impacted / 1 direct）；`WorkerSupervisor.start` 为 LOW lower-bound（4 个未解析 caller），构造器、`CometaRuntime.start`、`ai_gateway._start_cometa` 为 UNKNOWN/lower-bound 并按源码、装配注册与测试引用补证；`CometaRuntime._watch_worker`、`build_runtime`、status/bootstrap 接线为 LOW。`PolicySnapshot` 与 `Operation` 类为 HIGH（约 155 impacted），编辑前已提示；前者实现未改，后者只增加两个 planned enum member。所有 UNKNOWN/零 caller 均未按“无影响”处理。
- 提交前 GitNexus 1.6.12 原索引存储版本 v43 与当前运行时 v42 不兼容，按门禁以 `analyze --force --index-only --pdg` 重建（HEAD `66fb21f`，105,429 nodes / 263,193 edges / 1,119 clusters / 814 inferred flows）。图谱仍有边界：33 个 >512KB 文件跳过；2,880 / 3,080 个 process candidates 未入排名、21 条 trace depth-capped、804 个 callee 因分支上限跳过、41 条 walk 预算截断；另有 317 个跨语言属性引用未连边。提交前 `detect-changes --scope all`：13 files / 180 symbols / 0 affected processes / LOW；`compare --base-ref main`：515 files / 1,348 symbols / 118 processes / CRITICAL cumulative，符号清单 capped，完整统计与风险仍覆盖全部变更。all 的零受影响流程不覆盖上述 upstream 结果，也不证明零 caller；两条最终命令均退出 0，未返回 partial/truncated 标记。
- 实施报告与状态文档提交前 `detect-changes --scope all`：4 files / 9 symbols / 0 processes / LOW；`compare --base-ref main`：515 files / 1,348 symbols / 118 processes / CRITICAL cumulative，符号清单 capped。compare 首次并行调用被中断并标为 PARTIAL，单独顺序重跑后恢复完整计数；最终两条命令退出 0，未返回 partial/truncated 标记。文档门禁 119 files / 1,248 links / 577 anchors / 0 errors，feature JSON parse 与 staged `git diff --check` 通过。
- 定向顺序回归：`STELLA_HOME=/tmp/stella-gravitas-g09-auth-sequence-20261021 .venv/bin/pytest tests/cometa/test_g09_policy_runtime.py tests/gravitas/test_g09_policy_transport.py tests/webui/test_webui_cometa.py -q -x`：**56 passed / 12.61s**。含真实 worker 子进程暂停/恢复 claim、硬杀后租约到期再由新身份 worker 接任并获 ACK；unknown recovery task 不重发由既有 recovery 守卫覆盖。此顺序下未复现 WebUI 鉴权问题。
- 最终树全量回归：`STELLA_HOME=/tmp/stella-gravitas-g09-final-recheck-20261021 .venv/bin/pytest tests -q -x`：**3,942 passed / 22 skipped / 1 failed / 1 existing PytestRemovedIn10Warning，226.97s**。失败位于既有 `tests/webui/test_webui_cometa.py::TestAuthStatusAndCustomEndpoint::test_custom_endpoint_first_time_empty_key_rejected`，预期 400、实际 401（鉴权 fixture/JWT）；之前全量尝试亦在不同 WebUI 鉴权节点出现 401，而该文件单独及上述 G09→WebUI 同进程顺序均通过。根因未确认，不能将此轮全量记作通过。此前增加真实 hard-kill 测试前的一次全量曾通过 4,015 passed / 29 skipped；该历史结果不替代最终树结果。
- `.venv/bin/ruff check .`、全部改动 Python 文件 `py_compile`、`.venv/bin/python scripts/check_docs.py`（119 files / 1,248 links / 577 anchors / 0 errors）、`.venv/bin/python scripts/generate_message_flow.py --check`（`message-flow.f49877957442.json` 与源码一致）和 `git diff --check` 均通过。
- 所有验证使用隔离 `/tmp/stella-gravitas-*` 路径；未启动真实模型、Bot 或平台，未访问用户数据库、聊天、凭据或本机配置。真实模型/QQ/WebChat 灰度、生产跨进程故障恢复、Windows/Linux clean VM、安装器和发布资产仍未验收，整体 **NOT READY**。

## 未完成与验收边界

- G00–G09 源码工作已按工作包完成；分阶段提交包括 G09 代码提交 `ddb1c53` 与本报告/状态证据提交。`GRAVITAS-IMPL` 是否关闭仍以最后的 PR CI 与状态记录为准。
- 真实模型质量/适配、QQ 与 WebChat 灰度、跨进程 live 恢复、clean VM、发布资产均未验收。方案规定整体保持 **NOT READY**，不得用 fake 测试或本地回归替代。
- 所有新跑 pytest 使用临时 `STELLA_HOME` 与隔离数据库；未访问用户生产库、聊天、凭据或本机配置。
