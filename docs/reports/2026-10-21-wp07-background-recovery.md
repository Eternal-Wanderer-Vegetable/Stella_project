# WP07 实施记录：后台目标与任务恢复

- 日期：2026-10-21（Asia/Shanghai）
- 工作分支：`codex/cross-platform-implementation`
- 基线：WP06 实现提交 `d2270d1`
- 实现提交：`7bea280`（`feat(scheduling): bind background delivery targets (WP07)`）
- 状态：WP07 定向实现和回归完成；XPLAT-IMPL 整体仍 **NOT READY**。

## 范围和结果

后台调度、Cometa 通知和主动发言现在携带版本化投递目标与 BotRef。投递前从 NoneBot 当前 Bot 注册表按 `self_id` 精确解析，并校验连接、adapter、平台和目标一致；不调用默认 `get_bot()`，也不从模型输出恢复路由。目标不完整、过期、Bot 离线或连接不匹配时不发送。

Scheduling SQL schema 从 1 升到 2，为 task、run、audit 和 quota 保存 target、subject 与 scope。迁移只在旧 QQ Bot 与群号可验证且目标无歧义时绑定旧任务；不能证明身份的任务保留但不可投递。旧 quota 留在不可路由的 legacy scope，避免转成新连接额度。每次任务运行都快照目标与作用域，运行时再次验证。

Cometa Origin JSON 从 v2 升到 v3，新增 BotRef 与 DeliveryTarget 并要求两者一致。旧版本只在符合已知 OneBot QQ 语义时兼容；不能证明目标身份的记录 fail closed。Cometa SQL 仍为 schema 1。投递状态保留 CAS/租约；明确平台拒绝可以走既有安全 fallback，超时或不确定副作用记录 delivery_unknown 并停止，避免重复发送。WebChat 的 server-emitted 响应进入独立状态，不伪装成 QQ SENT。

主动路径使用注册表会话键进行 session touch、上下文读取、压缩和记录。Proactive timer 只有在 OneBot v11 目标 Bot 唯一时运行；没有 Bot 或存在多 Bot 歧义时跳过。参与度后台 job 从触发事件绑定 BotRef。Scheduling 命令在入站阶段保存精确目标、subject 和 conversation scope；旧任务不会根据 prompt 文本补目标。

## GitNexus upstream impact

编辑前固定使用 GitNexus 1.6.11。图索引有注册调用遗漏、框架动态入口与跨语言边界，故 UNKNOWN/零调用者另用 decorator、导入关系和源码引用核实。原始风险按图记录；没有使用 `riskSharedAxes` 降级。

| 目标 | 编辑前 upstream impact | 处置 |
| --- | --- | --- |
| Cometa `Origin` | HIGH；31 impacted / 19 direct / 0 process hits | 新版本仅追加字段并校验交叉一致性；v1/v2 读取路径保留并 fail closed；目标调用者由测试与 sender 源码审计。 |
| Scheduling `DeliveryService` | LOW；24 impacted / 4 direct | 保留状态/claim 语义，持久化明确的目标与 unknown 结果。 |
| Cometa `NotificationPump` | LOW；29 impacted / 4 direct | 保留租约与 CAS，只将 server-emitted 映射为独立状态。 |
| Cometa `_target_from_origin` | LOW；6 impacted / 2 direct | 仅从可信 Origin 生成版本化目标，不使用调用者默认 Bot。 |
| `SchedulingService.create_task` | LOW；19 impacted / 1 direct；接收端下界 | 调用处由 OneBot 事件构造 BotRef、DeliveryTarget、subject 与 scope；静态类型边界再经源码核对。 |
| `_proactive_at_user` | LOW；1 direct；命中 `proactive_speak_job` | 使用当前触发事件 Bot 与注册会话；后台入口由 scheduler decorator 动态注册。 |
| `_proactive_speak_for_group` | LOW；4 impacted；命中 `proactive_speak_job`、`record_group_chat` | 群上下文和记录均带注册表的 conversation ref / storage key。 |
| `session_context.touch` | LOW；1 direct (`record_group_chat`) | 完整模块限定后消除同名歧义；传入 storage key，既有入站入口经源码核查。 |
| `_announce_sleep_transition` | LOW；1 direct (`proactive_speak_job`) | 明确目标发送并按 scoped session key 记录。 |
| `_register_group_conversation` | LOW；2 direct (`handle_chat`、`record_group_chat`) | 复用注册表并携带连接域。 |
| `proactive_speak_job` | UNKNOWN / 0 静态上游 | `@scheduler.scheduled_job` 动态注册已由源码确认；在多 Bot/无 Bot 时跳过。 |
| `_spawn_participation_speak` | LOW；1 direct (`record_group_chat`) | 从触发事件捕获 BotRef，后台任务使用精确解析器。 |

## 验收证据

| 命令/范围 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/observability/test_proactive_flow_lifecycle.py tests/test_proactive_at_flow.py tests/test_proactive_gate.py tests/test_proactive_target.py tests/test_proactive_rules.py tests/test_session_compact.py tests/test_context_tail.py tests/test_session_context.py tests/test_session_context_cache.py tests/test_session_idle_finalize.py tests/test_conversation_identity.py tests/scheduling -q` | 401 passed。覆盖 exact target、作用域、旧目标迁移、unknown、无 Bot/多 Bot timer、主动参与 job 和 session key。 |
| `.venv/bin/python -m pytest tests/cometa --ignore=tests/cometa/test_worker.py -q` | 194 passed / 7 skipped。 |
| `.venv/bin/python -m pytest tests/cometa/test_bridge.py tests/cometa/test_qq_delivery.py tests/cometa/test_runtime_assembly.py tests/cometa/test_cometa_store.py tests/cometa/test_delivery.py -q` | 79 passed。 |
| `.venv/bin/python -m pytest tests/test_conversation_identity.py tests/test_transport_outbound.py -q` | 67 passed；2 条 adapter 未安装环境 warning。 |
| `.venv/bin/ruff check`（WP07 修改的 Python 源码和测试） | All checks passed。 |
| `.venv/bin/python scripts/generate_message_flow.py` | 生成 `core/observability/flows/message-flow.cf2c175bb77b.json`：141 nodes、139 source-resolved、8,973 closure sites、11,892 reachable symbols。 |
| `.venv/bin/python scripts/generate_message_flow.py --check` | 生成后通过。 |
| `git diff --check` | 通过。 |
| `.venv/bin/python -m pytest tests/cometa -q` | 超过 8 分钟停留在 worker 用例；中断时 180 passed / 7 skipped，退出为 KeyboardInterrupt（非通过）。此前隔离复现该 worker 测试 30 秒无进展。 |

实现提交前 `.gitnexus/gn detect-changes --scope all --limit 1000 --repo Stella_project` 返回 31 files / 162 symbols / 36 affected flows / CRITICAL；`--scope compare --base-ref main --limit 1000` 返回 287 files / 908 symbols / 102 processes / CRITICAL。两条完整摘要均未标 partial/truncated；compare 包含 WP00–WP07 的累计变更。图输出记录 2,731 个入口候选因预算未进入排名、25 条 trace 深度截断、780 个 callee 分支裁剪和 910 个跨语言属性边界，因此源码调用点和动态 scheduler decorator 另行审计。

状态文档提交前 scope all 为 8 files / 18 symbols / 0 processes / LOW；compare main 为 288 files / 913 symbols / 102 processes / CRITICAL（累计风险）。`python scripts/check_docs.py` 经 `.venv/bin/python` 运行：119 files / 1,223 local links / 577 anchors / 0 errors；feature JSON、message-flow `--check`、Ruff 和 diff 检查通过。

## 数据边界与未完成验收

`STELLA_HOME` 未设置，pytest 使用临时目录。没有读取、迁移或写入生产库，也没有启动真实 Bot、模型或平台。没有代表性平台 live、多 Bot 离线/重启、clean VM 或发布验收。Cometa worker 的挂起尚未修复；全量 Python 与外部验收缺口保留，整体 **NOT READY**。
