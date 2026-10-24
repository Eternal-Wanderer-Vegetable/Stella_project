# Corona / Nucleus 实施 CN03 — 独立控制面与单核心监管

日期：2026-10-23（Asia/Shanghai） · 分支：`codex/corona-nucleus-implementation` · CN03 基线：`73d7c60`

**包状态：CN03 实现与本机验收完成；CORONA-IMPL 仍 in progress / NOT READY。** 默认 `python bot.py` 仍为 legacy；本阶段加入可单独启动的 `python -m corona` 控制应用，但尚未接入启动器，Windows 及真实平台验收未完成。

## GitNexus 与编辑风险

编辑前索引绑定 CN02 HEAD `73d7c60`，GitNexus 1.6.12 / PDG 状态匹配；源编辑后索引报告 7 changed / 11 added。未对脏树重新 analyze。实施前 upstream impact：

| 目标 | 风险与影响 | 说明 |
| --- | --- | --- |
| `webui/app.py` | LOW，3 impacted / 2 direct | 独立 dev app 与 mount 装配；本包不改该文件。 |
| `webui/auth.py` | **HIGH**，20 / 17 | 认证依赖在 `rate_limit_capacity()` 调用点才加载配置；既有 auth/JWT 合同保留。 |
| `webui/security.py`、`auth_file` | File LOW 22 / 4；符号 **CRITICAL** 15 / 4 / 5 flows | 移除模块导入期配置绑定，支持 Corona 注入 home/TTL；旧路径调用仍延迟解析 legacy settings。 |
| `create_token`、`desktop_session_secret` | **HIGH** 5 impacted；LOW 4 / 2 | Token 签发兼容既有格式；桌面能力不进入 Nucleus 环境。 |
| `webui.audit._append` | File MEDIUM 8 / 5；符号 **CRITICAL** 30 / 1 / 26 processes / 3 modules | 本包未改用/修改高影响共享 audit 写入，Corona 另写密码脱敏审计文件。 |
| `webui/static.py`、`source_build.py`、`config/instance.py`、`webui/mount.py` | LOW：4/1、1、15/1、1 | 静态路径显式注入；source build 接收纯路径参数；home/identity 运行时路径保持原合同。 |
| `NucleusLifecycle`、`_make_server`、`prepare_managed_environment` | LOW：8/3、2/1、2/1 | 仅加受管进程树收尾和 owner-loss；既有 managed/legacy 分支与单一 shutdown deadline 保留。 |
| `get_current_instance_id`、`_force_shutdown_exit` | 图中缺失/UNKNOWN | 补查 identity/lifecycle 源码与测试；未把空结果解释为零调用。 |

HIGH `webui.auth.py`、CRITICAL `webui.security.auth_file` / `create_token` 与 audit `_append` 的影响已在编辑前提示；最终未编辑 audit 模块。图限制沿用 CN02：大文件跳过、入口候选和 callee/walk/depth 预算截断、动态接收者及跨语言引用缺边；新增模块此前无图节点，不能以零 caller 代替测试。

## 实现

- 增加独立 Corona bootstrap、ASGI app、管理 CLI 和 per-instance 进程句柄 OS 锁；Corona 登录、控制健康与核心状态不依赖 Nucleus 可用。管理面关闭时保留仅 loopback 的 Corona health。
- 新 `CoreSupervisor` 以 desired/phase 和 generation/controller/revision 身份管理单个核心：每代 launch capability 单独生成，health 必须匹配身份和 PID；记录 0600 启动日志、脱敏错误、失败状态及有界 crash retry。失败核心不会阻止 Corona auth/static 服务。
- `ManagedProcessTree` 在 POSIX 使用新 session/process group、父子 gate、Linux `PR_SET_PDEATHSIG` 和跨 POSIX owner-watch pipe；Windows 使用 kill-on-close Job Object，绑定失败则不放行业务启动。POSIX 用 `waitid(WNOWAIT)` 保留组 leader 身份，确认组内非 zombie 后代已退出再 reap，避免 PID/PGID 复用窗口。
- Nucleus 在业务装配前启动 owner watcher：Corona 失联时请求有限 drain；若尚无 server 则立即终止本代进程组。shutdown 收尾在同一个既有生命周期 deadline 内清理组内后代。不会按进程名清理外部服务。
- WebUI auth/security/static/source-build 改为惰性 legacy 配置解析或显式注入；Corona 复用 auth.json/JWT 兼容路径，审计独立且不写密码/token。桌面 session capability 从配置 revision 环境中剔除，不传入 Nucleus。
- 恢复 `tests/observability/test_message_flow_runtime.py::flow_db` 的 `social.db` 临时隔离、schema 初始化和 cache 清理。全量运行最初暴露该 fixture 只隔离 trace DB，三个交付事实用例将写入共享 `STELLA_HOME`；该变更只调整测试隔离，不改生产 social store。

## 验收与验证

| 命令 / 检查 | 结果 |
| --- | --- |
| `STELLA_HOME=/tmp/stella-cn03-final-targeted .venv/bin/python -m pytest tests/corona tests/nucleus tests/webui/test_webui_auth.py tests/webui/test_webui_mount.py -q` | **44 passed / 6.10s**；覆盖真 fake-core 成功、导入失败、挂起、崩溃、错误 PID、ready 后 crash/retry、Corona OS 锁跨进程拒绝、owner-loss pipe、后代清理、import fence、auth/static/loopback health 与既有 Nucleus。 |
| `STELLA_HOME=/tmp/stella-cn03-flow-final .venv/bin/python -m pytest tests/observability/test_message_flow_runtime.py -q` | **16 passed / 1.80s**；每例将 social store schema/cache 与 `turn_trace.db` 一并隔离在 pytest `tmp_path`。 |
| `.venv/bin/ruff check .` | 通过。 |
| `.venv/bin/python -m compileall -q corona nucleus webui/auth.py webui/security.py webui/static.py webui/source_build.py` | 通过。 |
| `.venv/bin/python scripts/generate_message_flow.py --check` | 通过；`message-flow.982a65f5aef2.json` 与源码匹配。 |
| `.venv/bin/python scripts/check_docs.py` | 119 files / 1,275 local links / 577 anchors / 0 errors（阶段报告与状态更新后复跑）。 |
| 全量 `STELLA_HOME=/tmp/stella-cn03-final-full .venv/bin/python -m pytest tests -q` | **4050 passed / 29 skipped / 2 failed / 251.81s**。失败：`tests/webui/test_message_flow_api.py::TestFlowMessagesApi::test_running_trace_with_live_process_stays_running`（列表 `data` 为 null）；`tests/webui/test_webui_cometa.py::TestQueryAndControl::test_cancel_then_state`（401 vs 202）。两项完全相同 node 单测各自隔离复跑均 passed；同模块隔离又暴露不同的 trace-data / Cometa-auth 失败，根因未确认，因此全量 NOT GREEN。 |
| `git diff --check` | 通过（报告和状态更新后的复跑）。 |
| `node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project --limit 1000` | 24 files / 36 symbols / 7 affected processes / **HIGH**。摘要完整；CLI 显示前 15 个 symbols 与前 7 个 flows，并标明其余数量；文本输出无 partial/truncated 标记。 |
| `node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | 163 files / 423 symbols / 65 affected processes / **CRITICAL**（含 CN00–CN03 累计）。摘要完整；CLI 显示前 15 个 symbols 与前 10 个 flows，并标明其余数量；文本输出无 partial/truncated 标记。 |

运行测试仅用 `/tmp` 的 `STELLA_HOME` 与 pytest `tmp_path`；未读取/改写用户配置、生产库、聊天/凭据，未启动 Bot、模型、QQ/WebChat 或部署服务。POSIX owner-loss 与 Linux real process 场景在当前 Linux 主机通过；Windows Job/ACL、macOS/BSD、Docker、干净 VM 与平台接入均未验收，因此跨平台和产品发布仍 NOT READY。

## 下一阶段

CN04：扩充版本化 Nucleus 私有协议，建立内部 capability / actor 身份转发、本机 deploy 控制接口和健康/错误合同；保持业务 API 不经未授权路径暴露。
