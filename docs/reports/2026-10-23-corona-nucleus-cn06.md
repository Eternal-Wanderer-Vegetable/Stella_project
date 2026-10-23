# Corona / Nucleus 实施 CN06 — WebUI 路由拆分、业务代理与群绑定协调

日期：2026-10-23（Asia/Shanghai） · 分支：`codex/corona-nucleus-implementation` · CN06 基线：`5ae639b`

**实现包状态：代码和本地定向回归完成；全量 Python 门禁 NOT GREEN，CORONA-IMPL 继续 in progress / NOT READY。** 默认启动仍为 legacy；CN11 才切换。没有迁移业务数据库。

## GitNexus 与编辑风险

CN05 HEAD `5ae639b` 的 GitNexus 1.6.12/PDG 索引在本包编辑前对齐。`webui.auth.require_auth` 上游为 **CRITICAL（145 impacted / 2 direct / 67 processes / 20 modules）**；编辑前已向用户报告该风险。为支持核心代内签名身份，只在经过 `InternalRequestGuard` 标记、且 actor 明确为 `admin+jwt` 时建立 managed admin 上下文；普通 JWT 路径不变。`webui.app.create_webui_app` 为 MEDIUM，`webui.mount.mount_webui` 为 MEDIUM，`ManagedNucleusASGI` 为 MEDIUM；`setup_webui` 与 Nucleus main 为 LOW。上下文复核后只在 mount 启动模式分支切换过滤后的业务 app；默认 legacy 行为保留。

`OperationManager.accept` 为 LOW（5 impacted / 3 direct / 2 processes）；`_operation_api_error` 为 LOW（5 / 3 / 2），分别新增未完成群 saga 时拒绝普通 apply 及返回 409。`ConfigStore.save` 为 CRITICAL（117 impacted），未改共享保存符号。新 coordinator 类的唯一 UID upstream 为 LOW（1 direct，由 `corona.app` 装配，再由 `corona.__main__` 启动）；Nucleus 新 store 文件 upstream 为 LOW，唯一直接边是 `nucleus.routes`，后续经 WebUI mount 到 `bot.py`。

方法名 `execute` 在全仓高度复用；未消歧的 GitNexus 查询给出 CRITICAL 281 结果并报告 15 个 receiver 类型缺边，不能当作 coordinator 方法的影响。按文件和类 UID 校准后，已通过 `context GroupBindingsCoordinator` 确认 Corona app 装配调用，并用源码检查装饰器路由、私有 Nucleus endpoints 及业务 router tuple。索引刷新限制：34 个大文件跳过；Python callable-flow 至少一处候选集超 32 未生成部分 CALLS；process 抽取 3119/3319 个候选入口未入选、42 条预算截断、23 条深度截断、960 个 callee 跳过；324 个跨语言字段 site 不推断。GitNexus 仅是下界。

## 实现

- 新增 `corona.routes` 冻结计划清单的 133 个 `(method,path,owner)` 合同：21 Corona、111 Nucleus、1 个 `split-config-and-business`。未知 API 404，已登记路径的错误 method 返回 405；业务代理只接收 `/api/v1/` 已登记 Nucleus 路径。Corona 代理位于 SPA/static catch-all 之前。
- `webui.app.webui_route_routers()` 提供按原有顺序的 router tuple；managed Nucleus app 仅克隆装配 111 个业务 `APIRoute`，并检查差集/重复项。Corona 管理端保留控制路由。`WEBUI_SERVE_DIST=true` 时业务 GET 仍落到代理并在核心不可用时显式 503。
- 新增 HTTP 代理，向当前 ready 且 generation 身份匹配的 Nucleus client 转发；传递原始路径/query/body 和重复应用请求头，去除浏览器 JWT、Cookie、伪造控制头、hop-by-hop 及 `Connection` 点名头。响应保留状态、重复 `Set-Cookie` 和原始字节流，剥除响应 hop-by-hop 头，并正确压制 HEAD/204/304 body。核心离线返回 503，协议错误返回 502；不接受客户端 upstream URL。
- 内部 guard 在验证 capability、协议、身份和 actor 后标记受信状态；`require_auth` 只对可信 `admin+jwt` 构造 managed 身份，保持 legacy JWT 认证。Corona import fence 不加载业务 DB、模型、记忆、Cometa、知识库或 Bot 模块。
- 群绑定旧 PUT 端点由 Corona saga 协调：预验证 Nucleus 空间快照，持久化请求/步骤，按期望 revision 提交 `ALLOWED_GROUPS`，让 Nucleus 以 operation ID 幂等写空间文件并 reload cache，必要时提交 apply。失败执行 `.env` 和空间的条件补偿；外部编辑或补偿失败保留 `needs_reconcile` 并阻止后续 apply。Nucleus 独立 journal 保存文件前后快照；崩溃恢复遇到非预期内容时记为 `CONFLICT`，不覆盖外部编辑。Nucleus 离线时混合端点拒绝，单独控制 API 仍在线。

## 验收与验证

| 命令 / 检查 | 结果 |
| --- | --- |
| 核心 CN06 路由/群绑定/client/mount 聚焦回归 | `.venv/bin/python -m pytest tests/corona/test_group_bindings.py tests/corona/test_nucleus_client.py tests/webui/test_webui_mount.py -q`：**25 passed / 12.42s / 2 OpenAPI duplicate-operation-ID warnings**。包含 21/111/1 精确合同、Nucleus 装配精确性、核心离线/静态 catch-all、guard 身份、私有接口、原始 HTTP 转发、群 saga 成功、补偿失败阻止 apply，以及 Nucleus 部分写崩溃恢复遇外部编辑不覆盖。
| Corona/WebUI 与个人记忆相关回归 | `STELLA_HOME=/tmp/stella-cn06-related-final-20261023-7e81ad .venv/bin/python -m pytest tests/corona tests/webui tests/test_webui_personal_memory.py -q`：**192 passed / 29.24s / 2 OpenAPI duplicate-operation-ID warnings**。
| Ruff | `.venv/bin/ruff check corona nucleus webui tests/corona/test_group_bindings.py tests/webui/test_webui_mount.py`：通过。 |
| compileall | `.venv/bin/python -m compileall -q corona nucleus webui`：通过。 |
| message-flow manifest | `.venv/bin/python scripts/generate_message_flow.py --check`：通过，`message-flow.982a65f5aef2.json` 匹配。 |
| 文档链接/锚点 | `.venv/bin/python scripts/check_docs.py`：**119 files / 1,275 local links / 577 anchors / 0 errors**。 |
| 完整 Python suite（隔离 `STELLA_HOME=/tmp/stella-cn06-full-final-20261023-7e81ad`，预建 `memory/`） | **4087 passed / 29 skipped / 1 failed / 3 warnings / 256.16s**，NOT GREEN。失败为 `tests/webui/test_message_flow_api.py::TestSegmentsTruncationHonesty::test_command_full_text_via_receipt_path`，full suite 中 context 数据为空；精确节点单跑 **1 passed / 0.59s**，整个 `tests/webui/test_message_flow_api.py` 在隔离 home 下 **24 passed / 2.90s**。顺序/共享状态根因未知，不能据复跑宣称全量通过。 |
| 数据边界和外部验收 | 聚焦及全量均显式使用 `/tmp` 的 `STELLA_HOME` 与 pytest 临时目录；没有读取/改写用户配置、聊天、生产库，也未启动真实模型、Bot、QQ/WebChat、部署服务。Windows/macOS/BSD clean VM、Docker、live platform/model、发布验收尚未执行。 |
| staged GitNexus `detect-changes --scope all --repo Stella_project --limit 1000` | **21 files / 51 symbols / 745 affected processes / CRITICAL**。 |
| 回归审查 `detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | **193 files / 442 symbols / 745 affected processes / CRITICAL**（CN00–CN06 累计）。 |
| GitNexus 输出完整性 | 两条命令串行执行；输出无 PARTIAL 或 truncated 标记。流程列表显示上限不影响汇总数量。 |
| `git diff --cached --check` | 通过。 |

## 下一阶段

CN07：建设 generation 绑定的 adapter route catalog、HTTP/SSE/WS 稳定入口与 `/stella/status` 原始回环检查。CN06 只交付已登记 `/api/v1/` 业务 HTTP 代理，未交付平台 adapter/SSE/WS 入口认证。默认仍为 legacy。
