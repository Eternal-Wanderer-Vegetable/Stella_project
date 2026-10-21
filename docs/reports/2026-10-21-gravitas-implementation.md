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

## 未完成与验收边界

- 当前仅 G00–G03 完成；G04–G09 仍须逐包实现、验证和提交。
- 真实模型质量/适配、QQ 与 WebChat 灰度、跨进程 live 恢复、clean VM、发布资产均未验收。方案规定整体保持 **NOT READY**，不得用 fake 测试或本地回归替代。
- 所有新跑 pytest 使用临时 `STELLA_HOME` 与隔离数据库；未访问用户生产库、聊天、凭据或本机配置。
