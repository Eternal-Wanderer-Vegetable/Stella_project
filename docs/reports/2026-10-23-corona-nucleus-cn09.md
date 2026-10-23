# Corona / Nucleus 实施 CN09：Launcher、CLI、桌面与 Runtime ownership

日期：2026-10-23（Asia/Shanghai） · 基线：`6050bae`（CN08） · 分支：`codex/corona-nucleus-implementation`
范围：工程计划 §8.4。此提交记录实现；Rust 与 Windows 必要验收缺口仍使 CN09 / CORONA-IMPL 保持 NOT READY。

## 结果

- 新增 stdlib-only `stella_contracts.local_control` 与 `deploy.control_client`。`python -m deploy start/status/stop` 在定位 Corona live owner 前不加载 `config`/业务 settings、不读取可变 `.env` 端口；使用私有 ownership 记录、协议/实例/boot identity、loopback capability 和 OS-held owner lock。协议错误、owner 不可达或锁状态未知时 fail closed，不按端口/PID 杀进程，也不另启 legacy 核心。启动配置采用不可变 revision，`--force` 不能绕开 owner/协议约束。
- Corona 本机状态返回 controller PID 与公开监听地址。部署状态把 Corona 在线和 Nucleus ready/backoff 分开；Runtime schema-v1 `stella` 映射保留可选 `llama`/`onebot` 状态，Python 验证与 Rust round-trip fixture 覆盖无 `null` PID 的兼容形状。停止先通过认证 API 请求 Nucleus/Corona 关闭，再同时等待服务不可达和 OS ownership lock 释放。
- CLI 的 Stella lifecycle/status 响应无效或 Runtime 命令不可执行时不回退旧 deploy/端口探测。Tauri readiness 以 Corona 控制面和真实公开 URL 为准，核心未就绪时仍保留桌面管理面；关窗停止使用同一 deploy live-owner 路径。六种发布 profile 的 Tauri start 参数合同新增表驱动 Rust 单测。
- 桌面随机 session capability 只由 Tauri 通过 `start --detach` 传至 Corona，配置 revision 不保存该 secret，Nucleus 子进程环境过滤该 secret。Dashboard 仅在 Tauri、控制面可达、已完成 setup 且没有现存 JWT 时请求 capability 并换取正式 JWT；换票失败保持正常登录流程。浏览器和 setup 流程不会请求该能力。
- 管理路由已经由 `corona/routes.py` 映射到 Corona operation manager；未修改只供 legacy 路由使用的 `webui.services.system.restart`。对应 GitNexus 旧 service 的高风险流程不属于受管启动路径。

## GitNexus 编辑前影响

- `deploy/process.py:start_detached` 为 **CRITICAL**（报告 358 impacted / 103 direct / 25 processes / 12 modules）；`deploy/process.stop` 为 **CRITICAL/partial**，图中存在 receiver caller 丢失；`deploy/runtime.py` 与 `corona.local_control.create_local_control_app` 文件/符号为 **CRITICAL**。这些生命周期目标的调用者、deploy parser 分派、Corona startup、Tauri command 注册与 window-close 调用均进行了源码审计；旧 PID/端口停止路径仍保留给 legacy，不再由新 managed CLI 命令调用。
- `webui.services.system.restart` 为 **CRITICAL**（783 impacted / 315 direct / 38 flows / 20 modules，partial）；源码确认受管 `POST /api/v1/system/restart` 由 `corona/routes.py` 映射到 Corona，故旧 WebUI service 未改。
- `stella_bootstrap.config.build_config_revision` 和 `nucleus.bootstrap.prepare_managed_environment` 均为 **CRITICAL**（各 560 impacted / 163 direct / 25 processes / 15 modules）；修改前审阅 revision 构建与 child-env 边界，并添加不落盘/不传 Nucleus 的 secret 回归。
- Dashboard auth store 文件为 **CRITICAL**（238 impacted / 6 direct / 181 processes / 20 modules）。变更仅增加窄条件的 Tauri 换票；失败保留 login route。`dashboard/src/api/tauri.ts:tauriBridge` 为 **UNKNOWN/0**，文本审计确认现有 `BackendOfflinePage.vue` 引用，以及本次 auth store 新增引用；图未解析 Vue/Rust IPC 所有边。
- Rust/Vue 若干新或既有符号在图中为 UNKNOWN/0。通过路由注册表、IPC handler 注册、源码调用点和 frontend import 补足审计；跨语言 call graph 不作为通过依据。高风险值按原始输出保留，不以 shared-axis 或测试数豁免。

## 验证

- 在临时 `STELLA_HOME`、`STELLA_INSTANCE_ID=cn09-isolated` 执行控制面目标测试：**34 passed / 1.47s**，包含 deploy 假 Corona endpoint/owner-lock 状态、协议失配、Runtime schema 映射、本机控制 API、Nucleus secret 过滤和配置 revision secret 排除。
- `python -m py_compile`（全部修改的 Python 源码与测试）和 `.venv/bin/ruff check .`：通过。
- Dashboard：`pnpm --dir dashboard test -- tests/auth-store.spec.ts`（Vitest 当前配置执行整个 suite）：**9 files / 110 passed**；`pnpm --dir dashboard build` 通过；`pnpm --dir dashboard sync:webui` 通过；`diff -qr dashboard/dist webui/dist` 和 `diff -qr dashboard/dist desktop/dashboard-dist` 均无差异。Build 仍显示既有 mixed dynamic/static import 与 >500 KB chunk 警告。
- `.venv/bin/python scripts/check_docs.py`：**119 files / 1277 local links / 577 anchors / 0 errors**。`.venv/bin/python scripts/generate_message_flow.py --check`：通过；全仓 Ruff、`git diff --check`：通过。
- 本轮全量 Python 未重跑；CN07 最近全量为 **4103 passed / 29 skipped / 1 failed / 3 warnings**，一个 Cometa auth 401 在 suite order 失败、精确节点与模块单跑通过，原因未确定，状态仍 NOT GREEN。
- `cargo fmt`/`cargo test`/`cargo clippy` 未运行：当前主机没有 `cargo`、`rustc` 或 `rustup`。CN09 所需 Windows native ownership/Job Object 验收也未运行（当前主机非 Windows）。新增 Rust 测试和序列化变更未获得编译器验证；此为明确的退出条件缺口。

## 最终 GitNexus 门禁与验收边界

暂存后按要求串行运行 `node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project`：**26 changed files / CRITICAL**；随后 `node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo Stella_project`：**236 changed files / CRITICAL**。完整重复运行中的符号与受影响流程计数有波动。输出没有 partial/truncated 标记；CLI 按显示上限省略余下符号和流程名。风险保留，不豁免。

Fake local controller 覆盖证明 Python 控制器发现与协议合同，不是打包产品的真实 Tauri/CLI/Corona 真进程闭环。前台/后台 CLI、桌面关窗、Rust schema、Windows native lock/process tree、六种最终产品资产、真实 Nucleus 和平台尚未完整验收。legacy 默认不变；CN11 才切换。CN09 实现阶段提交不代表退出条件全部通过，整体仍 NOT READY。
