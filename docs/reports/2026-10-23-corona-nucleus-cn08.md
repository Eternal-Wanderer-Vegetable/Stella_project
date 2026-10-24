# Corona / Nucleus 实施 CN08：Dashboard 配置应用与离线状态

日期：2026-10-23（Asia/Shanghai） · 基线：`6ba8bdd`（CN07） · 分支：`codex/corona-nucleus-implementation`
范围：实施计划 §8.3；Corona 运行时尚未成为默认入口。

## 结果

- 增加 Dashboard system API 与 Pinia store：识别 protocol v1 托管状态，持续读取控制面状态，跟踪 desired/applied revision、核心 generation 和 operation；通过 operation SSE、事件 ID、状态快照轮询、断线指数退避和 sessionStorage 中的幂等 apply 请求恢复页面重连或丢失响应。
- 在已登录全局布局显示状态横幅，分开呈现控制面连接、保存/应用修订、核心阶段、操作阶段、失败错误摘要、回滚结果和 Corona 控制层重启提示。核心停机不清除 JWT，也不把已登录页面送到整个后端离线页；控制面断线会显示重连状态，控制面恢复后继续同步。
- Config、Providers、Platforms 的受管写入都携带 `If-Match` 和幂等键，每个表单只发一次 apply。Config 在受管模式下不再追加旧式 `/system/restart`；浏览器验收先捕获到该多余请求，修复后后续两次保存均只调用 apply。Legacy 模式保留原保存/重启行为。Providers 保存端点和角色时按前一写入返回的新修订串行 CAS。
- Welcome 页面读取 Corona 状态；Chat/Groups 在请求失败、核心不可用或 generation 改变时标记本地业务缓存 stale。Chat 请求失败后不自动重发。业务代理的 HTTP/SSE 401 作为业务错误，不触发全局登出；控制面认证端点 401 仍按旧策略清理无效登录态。
- 使用 `pnpm --dir dashboard sync:webui` 将同一 Dashboard build 同步到 WebUI 与桌面壳发行目录。

## GitNexus 编辑前影响

- `corona/config_api.py:_operations` upstream **HIGH**（8 影响项 / 6 直接 / 3 条 operation/status 流程）。本包只消费既有 apply、status、operation、SSE API，没有修改 Corona 操作管理器或生命周期。
- `clearToken` upstream **CRITICAL**（435 影响项 / 2 直接 / 124 条流程 / 20 模块）。直接处理位于 Axios 与 SSE 401 路径。保留控制面认证失败时的清登录行为，只将受控分类之外的业务代理 401 保持为页面请求错误，并通过本地浏览器聊天 401 场景确认不会登出。
- 多个 Vue SFC handler、`sseStream` 和新增系统 store 在当前图中为 UNKNOWN/0 或未建立节点。对 `/status`、配置表单模板事件、`sseStream` 调用点、FullLayout 中 SystemBanner 的 import/render 进行了源码/模板引用审计；`ConfigPage.save` 文件级 impact UNKNOWN/0，源码确认 template 的 `@click="save"`。`progress.md` 的文件级 impact 为 **CRITICAL**（286 影响项 / 3 直接 / 124 条流程 / 20 模块）；这是状态文档引用传播，不解释为运行时调用扇出。状态文件更新前再次检查 AGENTS、workflow、check_docs 和文档合同测试的实际引用。

## 验证

- `pnpm --dir dashboard typecheck`：通过。
- `pnpm --dir dashboard test`：**8 files / 107 passed**。
- `pnpm --dir dashboard build`：通过，736 modules transformed。Vite 保留既有动态/静态混合 import 提示，ApexCharts/charts 和入口 chunk 超过 500 KB 的体积提醒。
- `pnpm --dir dashboard sync:webui`：通过；`diff -qr dashboard/dist webui/dist` 与 `diff -qr dashboard/dist desktop/dashboard-dist` 均无差异。
- 中英文 locale JSON 解析与 `git diff --check`：通过。
- `python scripts/check_docs.py` 因系统未安装 `python` 命令无法启动；改用项目环境 `.venv/bin/python scripts/check_docs.py` 通过：119 文件 / 1280 本地链接 / 577 migration anchors / 0 errors。
- 浏览器验收使用 Vite + 仅监听回环的临时 mock 控制 API，不访问用户账户、Corona 生产数据或真实核心：登录并显示托管状态；配置成功保存带 revision CAS 与幂等键且一次 apply；核心 stopped 时配置仍可保存；注入启动失败分别显示回滚成功与回滚恢复失败；控制面断线提示保留登录并自动重连；聊天业务 SSE 401 后仍留在已登录 Chat 页，显示缓存 stale，mock 记录仅 1 次请求。控制面恢复后 `/config` 页面仍保持登录。
- 本轮未重跑 Python 全量套件。CN07 最近全量仍为 **4103 passed / 29 skipped / 1 failed / 3 warnings**；顺序中的 Cometa 401 精确节点与模块单独通过，原因未确认，故 Python 全量状态继续 **NOT GREEN**。

## 最终 GitNexus 门禁

暂存后的 `detect-changes --scope all` 串行完整运行返回 **20 files / CRITICAL**；`compare --base-ref main` 返回 **217 files / CRITICAL**（分支累计）。符号和 affected-process 计数在完整运行之间会波动，不作为稳定值。一次 compare 查询中断并标为 PARTIAL，已丢弃并单独重跑；本次完整门禁输出未带 `partial` / `truncated` 标记。CLI 为显示上限省略了部分符号与流程名称。

## 验收边界

浏览器场景验证的是 Dashboard 对合同形状的响应和登录/错误交互；没有把临时 mock 当作 Corona 与真实 Nucleus 核心的端到端验收。Corona 启动器、CLI、Tauri/runtime ownership 留给 CN09；默认启动仍为 legacy。QQ 灰度、真实模型、生产业务库、Windows/Linux clean VM、Docker 与发行验收未执行，整体 CORONA-IMPL 仍 NOT READY。
