# WP05 实施记录：通用入口与 admission

- 日期：2026-10-21（Asia/Shanghai）
- 工作分支：`codex/cross-platform-implementation`
- 基线：WP04 状态提交 `3075d62`
- 实现提交：`28b296c`（`feat(transport): normalize platform message ingress (WP05)`）
- 状态：WP05 本地实现及定向验收完成；XPLAT-IMPL 整体仍 **NOT READY**。

## 范围和结果

新增 `core/transport/normalizers.py`，输出 Stella 自有的 `NormalizedEvent` 或带拒绝原因的 `UnsupportedEvent`。OneBot v11 保留 QQ 的用户域和群/私聊场景；通用 NoneBot fallback 要求调用方提供连接 ID，用户主体按连接隔离，会话保留为 opaque，不从 session 字符串猜测群或私聊。外部用户、场景、消息 ID 原样字符串化。

`AdmissionPolicy` 统一被动采集、群 @、私聊、WebChat 与插件入口的基础门槛：self echo、启用范围、私聊白名单、命令优先级、插件接管、纯图片与 VISION 开关都有明确决定/拒绝原因。AstrBot 的纯消息段事件仍可进入其 filter 管道；OneBot 专属工具事件构造拒绝显式标记为其他 adapter 的上下文。WebChat 固定管理员 ID 作为主体，用户名仅作为显示名。

`record_group_chat` 与 `handle_chat` 都调用 `get_or_register_group`，使用注册表的会话键、storage ID 和空间；被动入口在 capture gate 关闭时先返回，不写群行或注册表。群/私聊 `ChatContext` 填入可信 `BotRef`、`UserRef`、`SceneRef`、connection 与 opaque 平台消息 ID。图像提取接受 normalized event 并继续在 OneBot 原始事件上执行现有图片 codec。

本阶段只接通既有 QQ 与 WebChat 入口，并为后续 adapter 提供无框架核心合同；没有宣称新增平台可运行。线程/频道事件仍按 opaque 安全策略等待对应 adapter codec、会话注册与投递实现。

## GitNexus upstream impact

编辑前使用固定 `.gitnexus/gn` GitNexus 1.6.11。工作区索引基于 WP04 状态提交 `3075d62`；图是下界，不能因新文件未入旧索引而把风险降级。

| 目标 | 原始 upstream impact | 入口/流程补证 |
| --- | --- | --- |
| `stella_project/plugins/bot_main/ai_gateway.py` | HIGH；196 impacted，2 direct，181 processes，20 modules（文件级） | `record_group_chat` / `handle_chat` 方法级查询为 UNKNOWN/0；源码确认分别由 priority 0 的 `group_silent_listener.handle` 与 priority 3 的 `chat_handler.handle` 注册。上下文显示采集、记忆/社交和完整对话流程。 |
| `webui/chat_ingress.py` | CRITICAL；522 impacted，2 direct，181 processes，20 modules（文件级） | `run_turn` 为 LOW、2 impacted、1 direct、2 processes；图与源码确认 WebChat chat/stream 路由及测试调用。 |
| `memory.conversation_registry.get_or_register_group` | UNKNOWN/0 upstream callers | 编辑前 context 仅列 registry 测试。`rg` 补证确认群 matcher 尚未调用；本阶段将其接入被动采集与 @ 对话两条入口。 |
| `core/vision.py` | LOW；5 impacted、1 direct、2 processes（文件级） | `extract_image_sources` 从 normalized event 取回进程内原始句柄，保留 OneBot quote/image 语义。 |
| `capability.hooks._build_astr_event` | LOW；2 impacted、1 direct、1 module，0 processes | 唯一上游 `_run_comes`；下游是 OneBot `build_event`。显式 adapter 名不是 `onebot-v11` 时跳过，旧 context 未提供 adapter 名时保持兼容。 |

UNKNOWN/零调用者均按 NoneBot decorator 注册方式和源码补证，不作为未使用证明。`ai_gateway.py` 与 WebUI 的 CRITICAL/HIGH 文件级风险按原值保留；本报告不以 `riskSharedAxes` 抵消风险。

提交前 `detect-changes`（均使用 `--limit 1000`；CLI 仍缩略显示符号/流程名称，但完整摘要计数有给出）：

- `scope=all`：14 files / 26 symbols / 16 affected processes / **CRITICAL**。
- `scope=compare, base_ref=main`：首次 process query 中断并返回 PARTIAL，按门禁重跑后完整返回 254 files / 484 symbols / 76 affected processes / **CRITICAL**（含 WP00–WP05）。
- 比较摘要没有 PARTIAL 标记；列表显示“and N more”是 CLI 的固定摘要折叠。全量过程候选与跨语言缺边等限制仍按计划记录。

状态/报告文件单独提交前再次运行：`scope=all` 为 5 files / 14 symbols / 0 affected processes / LOW；`scope=compare` 首次 PARTIAL 后重跑为 255 files / 486 symbols / 76 processes / CRITICAL。compare 风险包含源码提交与既有工作包；文件级源码检测与状态文档检测分开记录。

## 验收证据

| 命令/范围 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/test_transport_normalizers.py tests/test_vision.py tests/test_capture_ingress_gating.py tests/test_private_chat_ingress.py tests/test_ai_gateway_deterministic_reply.py tests/cometa/test_gateway_wiring.py tests/capability/test_capability_hooks.py tests/webui/test_webui_chat.py tests/test_conversation_registry.py tests/test_context_projection_identity.py tests/test_multi_user_identity.py tests/astrbot_compat/test_dispatch.py tests/astrbot_compat/test_events.py tests/observability/test_message_flow_runtime.py tests/test_memory_capture_gate.py -q` | 214 passed |
| `.venv/bin/python -m ruff check`（本阶段修改的 Python 文件） | All checks passed |
| `.venv/bin/python scripts/check_docs.py`（状态/报告提交前） | 通过；119 files / 1,213 local links / 577 migration anchors / 0 errors |
| `.venv/bin/python -m json.tool feature_list.json` | 通过 |
| `.venv/bin/python scripts/generate_message_flow.py` | 新归档 `core/observability/flows/message-flow.3631d3d0ca29.json`，141 nodes / 139 source-resolved / 8,889 closure sites / 11,592 reachable symbols；拓扑版本不变 |
| `.venv/bin/python scripts/generate_message_flow.py --check` | 通过；归档与当前源码匹配 |
| `git diff --cached --check` | 通过 |

初次 `--check` 发现新函数体与所有既有 message-flow archive 均不匹配；按门禁生成新归档后复查通过。一次较早 `scope=compare` 返回 PARTIAL 后已重跑，报告采用重跑摘要。

## 数据边界与未完成验收

本机 `STELLA_HOME` 未设置；入口测试使用 pytest 临时 DB，群注册测试将空间解析替换为测试值，WebChat 使用隔离 home。没有读取、迁移或写入用户/生产数据库，没有启动 Bot、调用真实模型或平台。未运行完整 Python suite；WP02/WP03 报告的全量 Cometa/WebUI 问题未关闭。新平台 adapter fixture/live、QQ 灰度、线程/频道端到端、clean VM 与发布认证仍待后续工作包/外部验收，整体保持 **NOT READY**。
