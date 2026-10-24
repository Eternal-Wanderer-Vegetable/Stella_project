# Corona / Nucleus 实施 CN07：稳定平台入口与 HTTP/SSE/WS 代理

日期：2026-10-23（Asia/Shanghai）
基线：`eb7f889`（CN06）
分支：`codex/corona-nucleus-implementation`
范围：执行实施计划 §8.1–§8.2 与 CN07；默认启动仍为 legacy。

## 结果

- 新增共享路由目录合同，绑定 control protocol、instance/controller/generation/revision 身份和路由 SHA-256。验证拒绝保留路径、动态模板碰撞、重复方法路由、根/路径捕获器、非法分隔符和不支持的方法。Nucleus 仅从当前 FastAPI Driver 中导出名称归属于已注册 adapter 的 HTTP/WebSocket 路由；其它 adapter 形态不导出、不视为 certified。
- Nucleus 在回环与代际 capability 保护下提供 `GET /_nucleus/v1/routes`。Corona 先核验 health 身份，再拉取并校验目录；目录与 ready 状态写入同一个不可变快照。路由请求只有在该目录仍是当前 ready 快照对象时才可取得客户端，故旧代目录不能被复用到新代端口。
- 新增 Corona ingress middleware，在静态资源/SPA 前精确匹配已发布目录。HTTP 使用固定的本代回环 endpoint，流式发送原始请求体并透传 method、编码 path、query、平台 Authorization/Cookie/签名头、状态码与重复响应头；移除 caller `X-Stella-*` 和转发头、拒绝 unsafe path，不跟随 HTTP 重定向并改写泄漏私有 Nucleus origin 的 Location。SSE 走同一有界异步流，断连经响应 `finally` 关闭上游。
- WebSocket 使用 websockets 的无重定向连接器，透传 Origin、subprotocol、平台认证/签名头与文本/二进制消息；双向 send 均 await 以形成背压，限制单消息 4 MiB、队列 4 条和写缓冲 32 KiB，保留上游关闭码/原因；没有重放消息或自动重连。重连由平台客户端自行发起。
- 对 FastAPI 尾斜杠行为发 307 到公开相对路径。Corona 先检查 `/stella/status` 的原始 ASGI peer，只有回环连接才使用 system actor 转发；公开 Uvicorn 显式 `proxy_headers=False`，X-Forwarded-For 不能绕过。`/_nucleus` 与未登记的 `/_corona` 命名空间在 SPA 前返回 404。

## GitNexus 编辑前影响

在 CN06 HEAD `eb7f889` 刷新索引后，用精确 UID/context 和源码注册审计：

| 目标 | 上游结果 | 处理 |
| --- | --- | --- |
| `ManagedNucleusASGI` | **CRITICAL**，17 影响项 / 4 直接 / 124 流程 / 20 模块 | 按计划扩展单一私有 ASGI 控制入口，添加目录响应并保留现有 admission/lifecycle 行为。 |
| `NucleusClient.proxy_http` | **CRITICAL**，300 / 1 直接 / 130 流程 / 20 模块 | 现有业务转发默认保持；平台凭据保留及 Location 处理走新增专用 adapter 方法。 |
| `create_corona_app` | **CRITICAL**，301 / 2 直接 / 130 流程 / 20 模块 | 仅装配新增 ingress middleware；控制 API、WebUI 和业务 API 仍按原顺序装配。 |
| `NucleusClient` class | **HIGH**，7 / 3 直接 / 3 模块 | 新增私有目录读取与 adapter 专用代理方法，不修改原有浏览器 actor合同。 |
| `CoreSnapshot` | LOW，2 直接 | 目录为私有不可变字段，不加入 public status。 |
| `nucleus.__main__.main` | LOW，1 直接 / Tests 模块 | Driver 装配后构造目录并注入 managed ASGI。 |
| `corona.__main__.main` | LOW，1 直接 | 禁止公共 Uvicorn 信任 forwarded proxy headers。 |
| `core/transport/adapter_loader.py` | 函数查询 UNKNOWN/0；文件候选含 CRITICAL 514 / 2 直接 | 未修改；用已注册 Driver adapter registry 和实际 FastAPI route table 构建目录，并以真实 OneBot V11 注册测试补证。 |

Graph-RAG 对 `create_corona_app` / `proxy_http` 的扇出主要是既有业务代理流程。索引过程候选和调用闭包有预算截断，CRITICAL 下界与 UNKNOWN/0 均按源码和动态注册补查，不据此宣称没有影响。完整索引限制在本包 evidence 中保留：当前分析跳过 34 个超过 512 KB 文件；flow 提取存在 32-callable 上限、跨语言属性调用缺边、未排序入口候选、budget/depth capped walk 等情况。

## 验证

- `.venv/bin/python -m ruff check .`（全仓）：通过。
- `.venv/bin/python -m compileall -q corona nucleus stella_contracts`：通过。
- CN07 核心定向回归（合同/真实 OneBot Driver 注册/真实子进程 HTTP、SSE、下载、WS、关闭码、斜杠、重连、XFF/raw-peer、Supervisor、Nucleus lifecycle）：**42 passed / 5.86s**。最终增加的 HTTP 重连断言单独重跑：**1 passed / 2.09s**。
- 补充 Corona/Nucleus/WebUI 组：第一次 **210 passed / 2 failed**，两项 fake-core 因缺少 CN07 route catalog 握手失败；补齐夹具后为 **211 passed / 1 failed / 2 warnings / 37.26s**。剩余 `TestFlowMessagesApi.test_list_and_detail` 收到 401；精确节点 **1 passed / 0.73s**，所在模块 **24 passed / 3.19s**。顺序/认证共享状态根因未知。
- 全 Python：`STELLA_HOME=/tmp/stella-cn07-full-20261023 .venv/bin/python -m pytest -q` 得 **4103 passed / 29 skipped / 1 failed / 3 warnings / 278.93s**。失败为 `TestAuthStatusAndCustomEndpoint.test_status_none_when_unconfigured`（suite order 401）；精确节点 **1 passed / 0.44s**，所属 `tests/webui/test_webui_cometa.py` **29 passed / 4.81s**。根因未确认，全量门禁 **NOT GREEN**。测试 home 与子进程 DB/快照均隔离于 `/tmp`。
- 真实 NoneBot OneBot V11 Driver 子进程确认公开路由为 HTTP `POST /onebot/v11/`、`/http`、`/http/` 与 WS `/onebot/v11/`、`/ws`、`/ws/`。另以 Supervisor 管理的真实本机 Uvicorn fake Nucleus 验证 HTTP 上传/签名原字节、SSE、下载、WS 子协议/Origin/平台凭据/关闭码、断核 503、代际重启及客户端重连。
- `.venv/bin/python scripts/check_docs.py`：`ok=true`，119 个文件 / 1278 个本地链接 / 577 个 migration anchors / 0 errors。
- `.venv/bin/python scripts/generate_message_flow.py --check`：通过，`message-flow.982a65f5aef2.json` 与当前源码一致。
- `git diff --check`：通过。最终聚焦回归重跑：42 passed / 5.61s。

## 验收边界

OneBot V11 的 Driver 路由形状和本地假进程收发/重连通过；这不等同于真实 OneBot 服务器、QQ 灰度、浏览器/代理链或其它 adapter 的 live 验收。未知/非典型 adapter 不纳入可 certified 声明；32 平台矩阵仍按其原状态保留。未访问用户生产数据库、聊天、配置、真实模型或平台账号。CN07 未改变默认 launcher；CN08 下一步。

## 最终门禁附记

Staged GitNexus 两项命令按顺序单独运行，输出没有 `partial` / `truncated` 标记：`all` 为 **20 files / 39 symbols / 12 processes / HIGH**；最后一次完整 `compare --base-ref main` 为 **200 files / 553 symbols / 605 processes / CRITICAL**（累计回归范围）。重复 compare 的 symbol/process 计数有小幅波动；此处记录最后一次完整输出。
