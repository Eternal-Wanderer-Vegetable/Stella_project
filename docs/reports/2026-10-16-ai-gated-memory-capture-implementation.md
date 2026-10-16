# AI-Gated Memory Capture 实施报告

> 计划：[docs/plans/2026-10-16-gitnexus-plan-ai-gated-memory-capture-v2.md](../plans/2026-10-16-gitnexus-plan-ai-gated-memory-capture-v2.md)
> 分支：`feat/ai-gated-memory-capture`（基于 `codex/release-6.2.0` @ `c22dcec`）
> 日期：2026-10-16
> 结论：**代码面与测试面完成（M0–M8 全绿）；真实模型冒烟、QQ 灰度、clean-VM 验收 NOT READY。**

## 1. 交付概述

按计划 §7 的 8 步实施，全部落在本分支 6 个提交中；无 schema 迁移、无 `.env` 破坏性变更、`backend_for` 零改动。

| 提交 | 内容 |
|---|---|
| `3db81e7` | M1+M2：`memory/capture_gate.py` 状态机 + provider 中立有界探针 + 23 个确定性测试 + 两个操作员配置键 |
| `8bc6404` | M3：`record_message` 类型化拒绝契约（`capture` 决策参数 + `ctx.capture_result`）+ writer 契约测试 |
| `574250c` | M4+M5：QQ 群/私聊、WebChat、全部 BOT_SELF 写入方的门控；启动/优雅关闭钩子；consolidator 真实失败立即关门；三入口 e2e + 无回放测试；message-flow manifest 重生成（仅 body hash） |
| `0ab17fb` | M6：status API 脱敏 `memory_capture` 段 + `.env.example` + env schema 测试 |
| `427825c` | M7：双语文档（configuration / message-lifecycle / memory-system） |

## 2. 关键实现决策（对应计划开放问题）

1. **门在 `backend_for` 之外**（计划 §3）：`capture_gate` 只**调用** `backend_for(ROLE_CONSOLIDATION)` 取后端，不改解析器（CRITICAL / 16 direct / 95 impacted，§9 风险遵守）。
2. **探针即真实生成路径**（§12 问题 1/2 的定案）：探针经 `backend_for` 拿到的后端（含 `RoleBackend` 主/降级链语义）发一条固定 `"ping"` 补全；**不要求 `/v1/models`**；响应仅判非空，不做整合形状校验（更严校验会在 prompt 特异输出上误杀健康 provider）。探针正文不落盘、不进快照。
3. **`record_message` 拒绝是显式 opt-in**（§6.2）：`capture=None` 保持遗留直落库语义（夹具/受控迁移/显式调用方），生产入口一律经 `capture_gate.ingress_decision()` 取决策并传入。`ingress_decision()` 在门**未安装**时返回 `None`（= 遗留语义），生产 Bot 进程 on_startup 即装门且**永不置空**（`stop_gate` 只关门），因此生产生命周期内不存在「以为有门其实没有」的窗口；装门失败也会挂一个永不开门的实例。
4. **epoch 围栏**（§6.1）：任何进入关门态的跃迁 bump epoch；探针在途期间发生真实失败时，迟到的探针成功结果被弃用。真实整合失败经 `consolidator._generate` 的 `generate_detailed` 异常路径同步关门（截断异常 `OutputTruncatedError` 在调用点之后另抛，**不算** provider 故障、不关门）。
5. **派生副作用门控取「提前返回」形态**（§6.3）：群入口在资格过滤后、信封准备与落库前返回——身份声明、社会证据、表达/黑话学习、参与评分、participation speak 生成全部结构性地不再发生；私聊跳过落库/身份/共享授权/整合触发但回复照走；`_record_bot_lines` 单点覆盖全部 13 处 BOT_SELF 写入方。plan §6.3 列出的 compaction 未加门：压缩只汇总**已入库**的历史行（关门期间无新行），其输出属存量积压的既有处理策略（§6.5），不构成「闭门期内容的持久化」。
6. **关闭期缓冲**（§9 进程内存缓冲风险）：群入口在参与评分之前返回，`ParticipationManager.observe` 与 participation speak 对闭门期消息根本不执行；proactive 活跃度时间戳不含内容（§6.4 允许保留的操作计数）。无需新增缓冲清理 API。
7. **节奏常数**：探针间隔/超时进 `.env`（仅此两键，§6.4）；就绪租约 60s、退避封顶 300s 为代码内常数（改动需评审），与计划 provisional 值一致。
8. **无旁路开关**（§12 问题 5）：v1 不提供任何绕过验证开门的配置。

## 3. 验收矩阵（计划 §8）

| 场景 | 证据 |
|---|---|
| 启动未绑定整合角色 → 关门，无任何落库/派生 | `test_memory_capture_gate.py::test_default_probe_unbound_role_stays_closed`；`test_capture_ingress_gating.py::test_group_closed_gate_writes_nothing_derived` / `test_private_closed_gate_*` / `test_webchat_closed_gate_*` |
| 端点拒连 → 关门 + 有界重试 + 脱敏类别 | `test_default_probe_offline_provider`、`test_backoff_doubles_and_caps` |
| 不含 `/v1/models` 的在线兼容 provider → 开门 | `test_default_probe_success_without_models_endpoint`（全程零 models 调用） |
| 4xx/5xx/超时/空输出 → 关门、无泄漏 | `test_default_probe_bounded_timeout` / `test_default_probe_empty_output_not_ready` / `test_probe_offline_*`；快照泄漏测试 `test_status_snapshot_is_sanitized`、`test_capture_gate_snapshot_never_carries_secrets_or_content` |
| 就绪后真实整合失败 → 立即关门、迟到探针翻不了案 | `test_real_failure_closes_immediately_and_fences_stale_success` |
| 关闭→恢复，只采新消息、无回放 | `test_group_outage_interval_not_replayed_after_recovery`、`test_bot_self_lines_gated_then_recorded_after_recovery` |
| 就绪时群/私聊/WebChat 既有契约不回归 | `test_group_ready_*`、`test_private_ready_*`、`test_webchat_ready_*` + 既有套件全绿（test_message_relations / test_private_chat_ingress / test_webui_chat / test_bot_self_source 等） |
| 用量记账与门状态无关 | 记账链路未触碰；`test_usage_accounting.py` 全绿（全量套件内） |
| 显式授权命令不受关门影响 | 共享授权（`_maybe_personal_sharing`）在开门路径保持（`test_private_ready_*`）；关门时**随本条消息一起**跳过——它是从当前消息派生的授权，计划 §6.3 明确「without a source row, do not create sharing authorization」。显式设置命令（称呼等）不走 `record_message` 捕获面，未受影响 |
| 存量积压不变 | 未改动 checkpoint/清理/排空任何一行代码；`test_consolidator_core.py` 全绿 |

## 4. 验证证据（Windows，Python 3.14，隔离 STELLA_HOME）

- `python -m pytest tests -q -x --timeout=600`：**3707 passed, 17 skipped**（含本特性 41 个新用例：gate 23 + writer 3 + ingress e2e 9 + status/env schema 6）。
- `python -m ruff check $(git ls-files '*.py')`：全过（CI 同口径）。
- `python scripts/check_docs.py`：`ok: true`，0 errors，119 files，1190 local links。
- `python scripts/generate_message_flow.py --check`：manifest 与源码一致（重生成仅 body hash，无节点/边增删；新生命周期入口 `bot_main.start_capture_gate` 已登记 `internal_flow_catalog`）。

### 基线例外（非本分支引入）

- `python -m ruff check .`（含未跟踪文件）报 1 处 I001：`docs/reports/evidence/dialogue-attribution-20261008/guard_probe.py`——会话开始前已存在的未跟踪用户证据文件，前会话交接已记录同一发现，未改动。
- GitNexus CLI 本机 registry 损坏（既有问题，见会话记忆），`impact`/`detect_changes` 不可用。计划 §7 步骤 1 的调用方清点以文本检索兜底完成：`record_message` 生产调用共 5 处（群 1179 / 私聊 2014 / `_record_bot_lines` 3468 / WebChat 142、169），`_record_bot_lines` 13 处调用点全部经单点门控覆盖；提交门禁以全量测试 + ruff + 双 docs/flow 门禁替代。

## 5. NOT READY（外部验收缺口，不因本报告关闭）

| 项 | 状态 | 需要的证据 |
|---|---|---|
| 真实模型冒烟（本地 LM Studio / 在线 provider 探针实测） | NOT READY | 对真实端点跑探针开/关门与冷加载观察 |
| QQ 真机灰度 | NOT READY | 灰度清单执行 + 门关闭期消息不落库的运行观测 |
| clean-VM / 安装包验收 | NOT READY | 干净环境首启 + 状态接口 memory_capture 段核验 |
| Dashboard 可视化 readiness | Deferred（计划 §12） | 独立设计 |

## 6. 已知限制与后续

- 冷加载窗口：本地大模型加载期间探针持续超时 → 采集关门；加载完成后最迟一个退避周期（≤300s）开门。文档已给出调参建议。
- 关门期间 WebChat 仍会消费一次模型调用产出回复（回复路径不受门控）；该回复不落库。
- 存量积压的检查/排空是独立运维决策（计划 §12 Deferred），本特性不承诺。
- `status_api._capture_gate` 快照字段集合由测试钉死；Dashboard 若接 `memory_capture` 段，直接消费即可。
