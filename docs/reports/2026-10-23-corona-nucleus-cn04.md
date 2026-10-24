# Corona / Nucleus 实施 CN04 — 内部协议、身份转发与本机控制

日期：2026-10-23（Asia/Shanghai） · 分支：`codex/corona-nucleus-implementation` · CN04 基线：`38ceb89`

**包状态：实现与定向验收完成；全量 Python 门禁仍 NOT GREEN，CORONA-IMPL 保持 in progress / NOT READY。** 默认入口仍为 legacy；本包没有公开业务代理，业务路由迁移与平台入口代理继续留给 CN06/CN07。

## GitNexus 与编辑风险

编辑前 GitNexus 1.6.12 / PDG 对齐 `38ceb89`。关键 upstream impact：

| 目标 | 风险与影响 | 处理 |
| --- | --- | --- |
| `ManagedNucleusASGI` | **CRITICAL**，404 impacted / 4 direct / 109 inferred processes / 20 modules | 私有 ASGI 入口与全部 managed admission；只在既有生命周期控制边界追加版本检查。 |
| `nucleus/lifecycle.py`（File） | **CRITICAL**，390 / 4 direct / 108 processes / 20 modules | 本包唯一需要改动的高风险入口文件；健康/Drain/Stop 使用现有身份控制面。 |
| `status_api.py`（File） | **CRITICAL**，457 / 2 direct / 108 processes / 20 modules | 不改；Nucleus 健康身份由 managed 生命周期接口提供。 |
| `webui/responses.py`（File） | **CRITICAL**，41 / 33 direct | 不改；新协议错误使用独立、固定字段 JSON envelope。 |
| `AuthContext` | **HIGH**，23 / 19 direct | 不改类型；Corona 仅在 `require_auth` 验证 JWT 后创建新的内部 actor DTO。 |
| `status_source.py` / `chat_ingress.py` / `routers/chat.py` | LOW，分别 8/3、6/2、4/1 | 本包不改这些业务路由；仍属于之后的路由归属迁移。 |

File 级图风险的 processes/modules 轴不可用；表中的流程数是图谱推断下界，不是完整运行入口分母。`ManagedNucleusASGI` 的调用边为 exact。实施前已提示 CRITICAL 影响。状态 API 与响应共享模块保持不动，避免扩大修改面。

沿用该索引的提取限制：34 个大文件跳过；3,170 个入口候选中 2,970 个未排序进入图；767 个 callee 分支被跳过；38 次 walk 触及预算、24 条 trace 到深度上限；317 条跨语言属性引用和 33-callable 候选上限。图中零边与未解析调用均不视为未使用。

## 实现

- 新增 `stella_contracts.control` 标准库协议合同：独立的 `control_protocol_version=1`、controller / generation / revision / instance 身份、trusted actor、受控头名与生命周期 operation ID。
- Nucleus health 回应绑定协议版本和完整代际身份；Drain / Stop 要求协议版本、身份与 operation ID。`NucleusClient` 在 ready 前校验 health 版本和身份，并校验每个 ACK 的协议、代际和 operation ID；过期或错代 ACK 不会被接受。
- `InternalRequestGuard` 包裹 managed Nucleus 业务 ASGI。它要求原始 peer 回环、本代 launch capability、协议与四项身份一致、actor 类型与认证方式匹配；验过后把 actor 放入 ASGI `scope.state`，并在进入业务应用前移除所有 `X-Stella-*` 内部头。无 capability、错协议、错代或不可信 actor 都被拒绝。
- Corona 的 `NucleusClient.forward_browser_headers()` 先经既有 `require_auth` 验证浏览器 JWT，再签发内部 actor / capability / generation 头。它移除外部伪造的全部 `X-Stella-*`、管理员 Authorization 和 Cookie；adapter actor 的平台 Authorization 保留。客户端禁止重定向，且只接受回环上游。
- 本机 deploy 控制运行在独立回环监听，不依赖浏览器 WebUI 或核心业务进程。能力文件位于实例 ownership 目录，POSIX 模式为 `0600`；status/stop 同时核验 loopback peer、capability、协议、instance 与 controller boot。stop 使用 operation ID，先返回受理 ACK，再排空 Nucleus 并请求 Corona 退出。核心启动失败时状态与控制 API 仍可用。
- Corona 公共应用显式封锁 `/_corona/local/*`，避免控制命名空间落入静态 SPA fallback。没有启用公开业务代理；WebChat/业务路由和浏览器业务 API 转发未在 CN04 开放。

## 验收与验证

| 命令 / 检查 | 结果 |
| --- | --- |
| 定向 Corona/Nucleus 控制回归 | `STELLA_HOME=/tmp/stella-cn04-focused-20261023 .venv/bin/python -m pytest tests/nucleus/test_nucleus_lifecycle.py tests/nucleus/test_managed_process.py tests/nucleus/test_internal_api.py tests/corona/test_nucleus_client.py tests/corona/test_local_control.py tests/corona/test_corona_app.py tests/corona/test_supervisor_processes.py -q`：**29 passed / 5.21s**。覆盖错 token、错协议、错代、缺失/不可信 actor、合法 JWT actor、内部头剥离、迟到 ACK 拒绝、核心启动失败时本机控制、WebUI 关闭和 real loopback client。 |
| `.venv/bin/ruff check .` | 通过。 |
| changed-module `compileall` | 通过。 |
| `.venv/bin/python scripts/generate_message_flow.py --check` | 通过；`message-flow.982a65f5aef2.json` 匹配。 |
| 全量 Python，第 1 次 | **4056 passed / 29 skipped / 3 failed**。两个 proactive native 测试因隔离 home 的 `memory/` 目录未预建而无法打开 DB；预建该临时目录后两项各自通过。WebUI config 节点单独通过。 |
| 全量 Python，第 2 次（预建临时 `$STELLA_HOME/memory`） | **4057 passed / 29 skipped / 2 failed / 249.00s**：`test_running_trace_with_dead_incarnation_interrupted` 与 `test_port_item_kept_in_standalone`。两项单独隔离复跑均通过。完整 suite 连续出现不同的状态/鉴权顺序失败，原因未确认，因此全量结果 NOT GREEN。 |
| `.venv/bin/python scripts/check_docs.py` | **119 files / 1,280 local links / 577 anchors / 0 errors**（本报告与状态更新后复跑）。 |
| staged GitNexus `detect-changes --scope all --repo Stella_project --limit 1000` | **21 files / 31–32 symbols / 420–492 affected processes / CRITICAL**（多次串行运行观察范围）。输出列出前 15 个 symbols、前 10 条 flows 并标明 remainder；无 partial/truncated 标记。 |
| staged GitNexus `detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | **172 files / 363–382 symbols / 509–518 affected processes / CRITICAL**（含 CN00–CN04 累计；多次串行运行观察范围）。首次串行查询中断并标记 PARTIAL，已丢弃；后续串行重跑无 partial/truncated 标记，均列出前 15 个 symbols、前 10 条 flows 并标明 remainder。 |
| `git diff --check` | 通过（报告和任务状态更新后复跑）。 |

测试使用独立 `/tmp` `STELLA_HOME` 与 pytest `tmp_path`；没有读取或改写用户 home、生产数据库、聊天、凭据，也未启动真实 Bot、模型、QQ/WebChat 或部署服务。当前 Linux 本机验证了回环服务与子进程；Windows ACL、macOS/BSD、live 平台、Docker、clean VM 和发布尚未验收。

## 下一阶段

CN05：实现配置 revision CAS、单活动应用操作与至多一次配置恢复。本包的业务转发仍未启用，legacy 入口仍是默认；最终切换只由 CN11 负责。
