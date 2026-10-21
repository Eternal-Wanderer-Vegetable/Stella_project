# WP02 上下文与消息身份实施记录

日期：2026-10-21（Asia/Shanghai）
分支：`codex/cross-platform-implementation`
WP02 实现提交：`8ab18ce`（`feat(context): upgrade cross-platform message identity (WP02)`）

## 结果与边界

- `ChatContext` 新写 projection v7，并可安全读取 v6；保留可信 `UserRef`、`BotRef`、`SceneRef` 和连接/平台字段，限制投影字段、大小与类型。
- 对话投影升级至格式 v2。外部平台消息 ID 按不透明字符串保真（含 `abc`、`007`、Unicode 和分隔符）；旧 QQ 数据库 INTEGER 查找仍单独采用十进制兼容 codec。
- 回复协议升级至 `2026-10-21.1` / schema 2。模型只选择由服务端生成的有界 `target_ref`；映射绑定 turn、身份修订和 generation epoch。旧数字 `target_user_id` 只在明确的 QQ 兼容路径读取。来源作者和对象 ID保留字符串。
- 增补 reset 的会话局部隔离回归；非当前 turn、身份修订或 generation epoch 的引用不能解析成目标。
- 本阶段尚未给现有 SQLite 表新增外部消息 ID 列或改变 schema；按 WP03 处理 schema 20→21、数据迁移及 Python/native 双后端。`parse_qq_message_id` 仍服务现有整数列。
- 新旧 transcript 与 legacy P2 fixtures 同步；只按已审阅字段更新对应 oracle，M0 fixture 未改。消息流程 manifest 按源码生成器重建。

## GitNexus 上游影响（编辑前）

GitNexus 1.6.11，仓库 `Stella_project`。关键结果：

| 锚点 | Risk / 影响 | 调用与流程摘要 |
| --- | --- | --- |
| `parse_platform_message_id` | CRITICAL；22 impacted、2 direct、7 flows、4 modules | 覆盖 `handle_toggle`、`handle_reload`、`proactive_speak_job`、`handle_addressing`、`handle_chat`、`handle_private_chat`、`record_group_chat`；因下游触及共享消息路径，分离通用 codec 与 QQ INTEGER codec。 |
| `parse_reply_envelope` | HIGH；6 impacted、2 direct、1 flow、3 modules | 流程为 `scripts/evaluate_dialogue_attribution.py::main`；同步评测器与线上协议。 |
| `reply_envelope_from_projection` | HIGH；5 impacted、2 direct、1 flow、3 modules | 同一 evaluator 流程；投影解析和线上验证器同时升级。 |
| `_extract_reply_candidate` | HIGH；4 impacted、1 direct、3 flows | `handle_chat`、`handle_private_chat`、`record_group_chat`；保留数字 `0` 这种通用解析值，随后在 QQ codec 处拒绝不兼容数据库 ID。 |
| `ChatContext` / `MessageIdentityEnvelope` | MEDIUM；分别 22/11 direct、22/11 impacted | 多个上下文与 ingress 消费点；projection whitelist 和各入口回归覆盖。 |
| `TurnService` | MEDIUM；15 impacted、5 direct | turn 生命周期受影响；验证会话所有权与取消隔离。 |

其他已查锚点：`resolve_correction_target` LOW/3；`build_summary_packet` LOW/5；`build_attribution_evidence` LOW/3；`evidence_table_from_projection` LOW/7；`protocol_instructions` LOW/8；`cancel_turn` LOW/1（直接调用 `reset_session`）。`reset_session` 和 `parse_output` 为 UNKNOWN/0，已补源码检查：`webui/chat_ingress.py:265` 与测试调用 reset；`ai_gateway.py` 通过动态 hook 注册 `parse_output`。`memory/SYSTEM.md` 的图结果 UNKNOWN/0，已用文本搜索确认并更新协议说明。以上低图边不替代测试；图的入口候选、动态回调和跨语言边限制继续按方案 §2 处理。

提交前 GitNexus `detect-changes --scope all`：31 files、121 symbols、21 affected processes、CRITICAL；`--scope compare --base-ref main`：187 files、232 symbols、21 affected processes、CRITICAL。compare 首次运行因图查询中断，按门禁重跑后得到完整结果（无 partial/truncated 标记）。生成结果是风险摘要，不豁免逐项 impact 和定向验证。

## 验证

- 定向命令：

  ```bash
  .venv/bin/python -m pytest -q tests/test_context_projection_identity.py tests/test_transport_identity.py tests/test_conversation_projection.py tests/test_conversation_identity.py tests/test_dialogue_attribution_repair.py tests/test_attribution_wiring.py tests/test_session_compact.py tests/test_context_tail.py tests/test_full_workflow.py tests/test_message_relations.py tests/test_private_chat_ingress.py tests/runtime/test_turn_service.py tests/runtime/test_session_ownership.py tests/runtime/test_facade_turns.py tests/runtime/test_legacy_reference_traces.py
  ```

  结果：**310 passed in 13.85s**。
- `.venv/bin/ruff check $(git ls-files '*.py') tests/test_context_projection_identity.py`：通过。
- `.venv/bin/python scripts/generate_message_flow.py --check`：通过；生成文件 `core/observability/flows/message-flow.35e94e5e8bf4.json` 已随实现提交。
- `git diff --cached --check`：通过。
- 全量 `pytest tests -q`：**3782 passed / 29 skipped / 4 failed**。尚未关闭的失败为 `tests/cometa/test_worker.py::TestStartupLeaseRetry::test_worker_takes_over_after_stale_lease`、`tests/webui/test_webui_cometa.py::TestSubmit::test_submit_returns_202_with_idempotent_replay`、`tests/webui/test_webui_cometa.py::TestSubmit::test_submit_conflicting_key_rejected`、`tests/webui/test_webui_chat.py::test_chat_endpoints_sse_and_history`。这些测试不在 WP02 的改动文件内，但完整回归仍未全绿；WebUI 单测存在模块顺序下 401，需单独定位。此项保留为 NOT READY，不作为 WP02 代码回归通过证据。
- `STELLA_HOME` 未设置；验证使用 pytest 临时隔离目录。未启动 Bot，未读取或迁移生产数据库，未做真实平台、模型、QQ 灰度或干净 VM 验收。

## 下一阶段

WP03 将处理 schema 20→21、旧库副本迁移/中断/重跑、API 4 wheel 检查和 Python/native parity。先刷新 GitNexus 并对 schema/migration/backend/native 合同运行 upstream impact；迁移只在临时数据库副本上验证。跨平台认证和发布结论保持 NOT READY。
