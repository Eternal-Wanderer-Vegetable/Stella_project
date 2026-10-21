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

## 未完成与验收边界

- G00–G03、G04a、G04b 已完成；G04c、G05–G09 仍须逐包实现、验证和提交。
- 真实模型质量/适配、QQ 与 WebChat 灰度、跨进程 live 恢复、clean VM、发布资产均未验收。方案规定整体保持 **NOT READY**，不得用 fake 测试或本地回归替代。
- 所有新跑 pytest 使用临时 `STELLA_HOME` 与隔离数据库；未访问用户生产库、聊天、凭据或本机配置。
