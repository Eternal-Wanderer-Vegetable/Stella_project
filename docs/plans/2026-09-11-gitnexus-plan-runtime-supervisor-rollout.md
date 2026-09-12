# GitNexus Engineering Plan

> Task: 将 Stella Runtime 与一键部署架构按现有项目结构拆解为可执行的渐进式实施路线。
> Evidence verified at commit `45630b7107e29620f7e1a6039e71b3f79bf7c1e1`; GitNexus index refreshed in Docker with `analyze --index-only --pdg` and status is up-to-date at the pinned commit. The host MCP endpoint still reports a 37-commit stale view, so Docker graph results and current source are authoritative; MCP PDG probes returned no edges and are not used as load-bearing evidence.
> Evidence provenance schema 2; the exact snapshot is embedded in §11; generated plan path is `docs/plans/2026-09-11-gitnexus-plan-runtime-supervisor-rollout.md` and excluded from the snapshot.

## 1. Objective

[verified] 将 `design_docs/Stella Runtime & One-Click Deployment Architecture.md` 的目标落到现有
Python `deploy`、LLM registry、Tauri、`stellacli`、`STELLA_HOME` 和 Docker 结构中，形成可分阶段执行的
Runtime Contract、Rust Supervisor、llama.cpp 接入、控制面迁移、安装包和 Docker 计划。

[inferred] 第一阶段不一次性实现 NapCat 自动安装、全 GPU backend 矩阵、模型市场和超级单文件 EXE；
先交付 Windows Desktop MVP，再让 Docker 复用同一份契约。

Acceptance criteria:

- [ ] Runtime Contract 定义组件、状态、操作、错误、日志和版本/checksum 字段。
- [ ] Rust Supervisor 在不破坏 Python deploy 的前提下逐步接管 Stella 生命周期。
- [ ] `llama-server` 通过 OpenAI-compatible endpoint 接入，且不是 Stella Core 硬依赖。
- [ ] CLI、Tauri、`/stella/status` 和 Docker status 使用同一状态语义。
- [ ] OneBot/NapCat MVP 只做检测、配置校验、告警和等待重连，保留人工扫码登录。
- [ ] 迁移和升级继续保护 `STELLA_HOME` 用户数据。
- [ ] 每个阶段都有可运行的 Python/Rust 测试与回归命令。`n- [ ] Windows 原生进程树、文件锁、运行中升级与失败回滚矩阵全部通过，红项阻断发布。`n- [ ] NapCat 安装包可校验、可隔离、可卸载，登录态不泄露；默认保留人工扫码，无批准不得声称无人值守登录。`n- [ ] llama.cpp CPU/CUDA/HIP/Metal/Vulkan 的构建、元数据、校验和、硬件兼容与回滚链路可审计。

## 2. Current Behaviour

[verified] `deploy/__main__.py:_cmd_start` 先运行 `probe.collect()` 和 `checks.run_all()`，有阻塞项时要求
`--force`，后台模式调用 `deploy/process.py:start_detached`，前台模式直接运行 `bot.py`
(`deploy/__main__.py:134-150`)。

[verified] `start_detached` 当前只管理 Stella Bot：检查入口和已有 PID，创建带 launch token 的子进程，
然后写 PID 与 ownership manifest；记录失败会终止子进程并清理记录 (`deploy/process.py:167-212`)。

[verified] `process.stop()` 的顺序是 ownership 校验、停止哨兵、等待优雅退出、降级信号、最后硬杀；无 PID
但状态接口可达时拒绝假装停止成功 (`deploy/process.py:215-303`)。`process.status()` 优先使用进程内状态
接口，PID/进程存活作为兜底，并返回链路、scheduler、usage、capabilities 等字段
(`deploy/process.py:362-417`)。

[verified] `config/home.py` 将程序目录 `PROJECT_ROOT` 与用户数据目录 `STELLA_HOME` 分离，支持环境变量、
机器级指针、旧布局和便携布局 (`config/home.py:4-35`, `106-148`)；`config/instance.py` 已提供实例运行目录、
PID、ownership manifest 和 stop sentinel 路径 (`config/instance.py:17-67`)。

[verified] `core/llm/registry.py:endpoints` 从四个静态 endpoint slot 解析配置、校验 key sharing，并缓存
结果 (`core/llm/registry.py:170-251`)；`backend_for()` 通过 `_build_backend()` 构造带 fallback 的后端
(`core/llm/registry.py:661-698`)。`LMStudioBackend` 实际已是通用 OpenAI-compatible chat-completions
实现，只因兼容旧调用点保留类名 (`core/llm/lm_studio.py:4-16`, `33-80`)。

[verified] doctor 复用 registry 的解析结果和 `/v1/models` 探测，不在 checks 层重复解析 LLM 键；探针失败
降级为空结果，检查层按 local/error、online/warn 区分 (`deploy/probe.py:267-313`, `deploy/checks.py:805-881`)。

[verified] `/stella/status` 只在开关开启且能获取 ASGI app 时注册，限制 loopback，读取 OneBot、scheduler、
usage、fallback 和 capabilities；取数失败不能让状态接口返回 500 (`stella_project/plugins/bot_main/status_api.py:145-212`)。

[verified] Tauri 的 `run_deploy_inner` 是所有 Python deploy 调用的公共桥：定位项目根、准备嵌入式 Python、
选择 Python、执行 `python -m deploy`，并保留 stdout/stderr/退出码
(`stella-installer/src-tauri/src/python.rs:694-860`)。

[verified] `stellacli` 当前把 local 命令透传到 Python deploy，把 Docker 命令透传到 compose；状态在 Docker
模式聚合容器状态和容器内 status API (`cli/src/runner.rs:61-104`, `cli/src/main.rs:216-285`,
`cli/src/status.rs:58-113`)。

## 3. Relevant Architecture

[verified] 现有边界是：Python 负责部署诊断、迁移和业务运行；Tauri 负责 GUI 命令包装；CLI 负责编排和渲染；
Docker compose 负责容器、卷、网络和 restart policy (`cli/src/runner.rs:5-7`, `Dockerfile:11-15`,
`docker-compose.yml:19-79`)。

[verified] `STELLA_HOME` 是升级不覆盖的用户数据边界，当前数据内容包括 `.env`、记忆库、插件、人格和日志；
运行控制应优先落在已有 `STELLA_HOME/.stella/instances/<instance-id>` 命名空间，不另造第二套路径。

[inferred] 推荐新增独立 `runtime-manager/` Rust crate。`stellacli` 和 Tauri 作为控制入口，Python `deploy`
作为迁移期领域工具；Desktop Runtime 和 Docker Runtime 只替换生命周期适配器，不替换 Stella Core。

[inferred] Runtime 与 Core 的稳定边界是 OpenAI-compatible HTTP endpoint、OneBot V11 和 JSON 状态契约：
Core 不应知道 `llama-server.exe` 参数，也不应知道 NapCat 的安装目录或登录流程。

## 4. GitNexus Findings

[graph] Query `runtime manager deployment lifecycle start stop health check supervisor llama.cpp onebot installer`
定位到 `deploy/__main__.py:main`、Tauri `prepare_runtime` 和 `commands.rs:stop_bot` 等控制路径；索引陈旧，
这些结果只用于导航，实际行为以当前源码为准。

[graph] Query `LLM endpoint registry local online memory fallback concurrency backend` 定位到
`core/llm/registry.py`、`deploy/probe.py:_probe_llm_usage`、`core/llm/scheduler.py` 和现有 LLM 测试。

[graph] Query `Tauri installer Python deploy JSON command start stop status` 定位到
`run_deploy_inner`、`commands.rs`、`api.js`、`cli/src/runner.rs` 和 `deploy/__main__.py:_cmd_status`。

[graph] Query `OneBot NapCat status API health link monitor reconnect` 定位到
`extensions/link_monitor/__init__.py:link_monitor_task`、`link_status`、`status_api.py` 和 Docker status。

[graph] Impact `endpoints`, upstream, maxDepth 3, includeTests: `risk=CRITICAL`, `impactedCount=83`,
`direct=11`, `d1=11`, `d2=38`, `d3=34`，影响 4 个 execution flows 和 5 个 modules。d=1 依赖为
`_legacy_key_warnings`、`_local_slot_override_warning`、`bindings`、`concurrency_of`、`describe`、
`embedding_gate`、`endpoint`、`deploy/probe.py:_probe_llm_registry` 以及三组 registry tests。

[graph] Impact `run_deploy_inner`, upstream, maxDepth 3, includeTests: `risk=CRITICAL`, `impactedCount=12`，
`direct=2`，d=1 是 `run_deploy` 与 `run_deploy_without_prepare`；d=2 直接覆盖 Tauri 的 `get_config`、
`get_status`、`run_doctor`、`run_migrate`、`save_config`、`start_bot`、`stop_bot` 等命令，并影响 10 个执行流。

[graph] Impact `start_detached`, upstream: `risk=LOW`, `direct=1`，唯一直接调用者是
`deploy/__main__.py:_cmd_start`。这允许先以兼容层迁移进程管理，再扩大 Supervisor 覆盖面。

[graph] Impact `setup_status_api`, upstream: `risk=LOW`, `direct=1`，入口来自 `ai_gateway.py`；状态接口属于
可选观测能力，不应成为 Bot 启动硬依赖。

[graph] Impact `LMStudioBackend`, upstream: `risk=MEDIUM`, `impactedCount=33`, `epistemic=lower-bound`，
图谱报告 `LLMBackend` 接口存在 2 个实现、2 个 dispatch boundary；改名或改变构造语义前必须用文本搜索
确认动态/接口调用点，并保留兼容别名。

[assumed] GitNexus MCP 不同入口对陈旧程度报告为 18 commits 与 1 commit 两种值；本计划不以旧图谱的
“无调用者”结论作为安全证明，执行时应先重建索引并重新跑影响分析。
[verified] 当前 `runtime-manager` 已存在 `InstanceLock.acquire`、Runtime manifest/state schema 和有限的 `status/init/validate` CLI；它还不是完整 Supervisor，Windows 进程树和升级锁验证仍缺少原生矩阵 (`runtime-manager/src/lock.rs:19-55`, `runtime-manager/src/main.rs:9-48`)。

[graph] Docker GitNexus `context/impact` 对 `deploy/process.py:stop` 定位到 `_cmd_stop` 和现有停止测试，直接风险 LOW；对 `deploy/migrate.py:run` 报告 1 个 receiver typing 缺口，属于 lower-bound，必须用文本搜索和原生测试补齐未知调用者。

[verified] `stop()` 已按停止哨兵 → 优雅等待 → Windows `CTRL_BREAK_EVENT` → `taskkill /F /T` 的顺序工作；`start_detached()` 使用 `CREATE_NEW_PROCESS_GROUP`，写 PID/ownership 后更新 Runtime 状态 (`deploy/process.py:169-329`)。

[verified] `_rollback()` 只删除本次迁移写入目标目录的文件；`run()` 同时处理发布树、`.env`、runtime 复用和数据库迁移。它没有覆盖“目标文件被 Windows 句柄锁住”“交换过程中进程仍在运行”“跨版本恢复安装目录”的完整矩阵 (`deploy/migrate.py:300-525`)。

[verified] `deploy/packages.py` 已提供 `runtime/component/model/onebot` catalog kind、校验和复制、model active/history 和回滚；当前 catalog 只有单一 `platform` 字段，未表达 backend、驱动下限、ABI 或 artifact 依赖 (`deploy/packages.py:12-17`, `240-455`)。

[verified] Docker 现有 `llama` profile 使用 `ghcr.io/ggml-org/llama.cpp:server`，模型只读挂载、`/v1/models` healthcheck；NapCat 使用 `mlikiowa/napcat-docker:latest`，QQ/config 分卷，登录仍需 WebUI 人工扫码 (`docker-compose.yml:55-120`)。

[verified] `link_monitor_task()` 在未连接或探活失败时告警并等待重连，不自动重启 Stella/NapCat；现有 e2e 已验证 NapCat 未登录或断线不会停止 Stella (`extensions/link_monitor/__init__.py:135-191`, `tests/test_runtime_e2e.py:1-164`)。

[verified] release workflow 已能生成 package catalog、检查发布布局，并单独组装 Rust memory wheel 完整 Windows 包；尚无 llama backend 构建矩阵、NapCat provenance/SBOM、GPU 运行时 smoke 或 artifact 兼容性字段 (`.github/workflows/release.yml:250-375`, `.github/workflows/release-memory-rust.yml:1-260`, `tests/test_release_layout.py:1-170`)。
## 5. Statement-Level PDG Findings

[verified] 本次 `pdg_query({target: "core/llm/registry.py:endpoints", mode: "controls"})` 返回
`no PDG layer`。因此没有可引用的 CDG、REACHING_DEF 或语句级影响切片；本节只记录源码中的不变量，
不把人工阅读伪装成 PDG 结果。

[verified] `endpoints()` 的关键顺序是：懒初始化 `_endpoints`，按固定 `SLOTS` 调用 `_endpoint_from_settings`，
再调用 `_check_key_sharing`，最后缓存并返回。Runtime endpoint 适配必须保持该顺序。

[verified] `_endpoint_from_settings` 对 `BASE_URL`、`API_KEY`、`MODEL`、`KIND`、`CONCURRENCY`、`TIMEOUT`
做默认和纠错；local 并发超过 1 只告警，online 无 key 报错，非法 URL 和超时进入 issues
(`core/llm/registry.py:190-242`)。

[verified] `process.stop()` 的状态变更顺序决定数据一致性：先写 stop request，再等待 Bot watcher 完成
优雅关闭，之后才发送信号或硬杀；`finally` 必须清除 sentinel
(`deploy/process.py:250-303`)。

[verified] `run_deploy_inner` 的关键分支是 `prepare=true/false`：普通 GUI 命令允许准备嵌入式运行时，关闭窗口
和读取路径的命令必须跳过准备；它还根据 wheel 是否存在注入 `MEMORY_BACKEND=rust`
(`stella-installer/src-tauri/src/python.rs:815-859`)。迁移后必须保留此语义，并让 `data_root` 缓存失效
(`python.rs:723-762`, `commands.rs:470-487`)。

[verified] `link_monitor_task` 对未连接、事件超时和主动 `get_status()` 探活失败分别处理，只告警、不重启
NapCat；这是第一阶段 OneBot adapter 应保留的行为
(`extensions/link_monitor/__init__.py:135-191`)。

## 6. Proposed Changes

### 6.1 Runtime Contract 与 Rust crate

- [new] `runtime-manager/`：`Cargo.toml`、`src/main.rs`、`api.rs`、`supervisor.rs`、`component.rs`、
  `health.rs`、`manifest.rs`、`logging.rs`、`backoff.rs`。
- [new] `runtime-manager/schemas/runtime-manifest.schema.json` 和 `runtime-state.schema.json`。
- [inferred] Contract 定义 `stella`、`llama`、`onebot`；操作为 `start/stop/restart/status/logs/doctor`；
  状态为 `disabled/stopped/starting/running/healthy/degraded/failed`。
- [inferred] manifest 保存可执行文件、参数、工作目录、环境变量、健康检查、日志、依赖、自动重启策略、
  版本和 checksum；state 保存 desired/actual、PID、endpoint、启动时间、重启次数和脱敏错误。
- [constraint] 复用 `config.instance.runtime_dir()` 的实例隔离；不要在 `STELLA_HOME` 外写运行状态，也不要
  在 Runtime 内复制另一套 instance ID 算法。
- [constraint] GUI 只能提交枚举操作和校验参数，禁止暴露任意 shell command。

### 6.2 Python deploy 进程所有权迁移

- [existing] `deploy/process.py:start_detached/stop/status` 和 `deploy/__main__.py:_cmd_start/_cmd_stop`
  保持兼容命令和退出码。
- [inferred] 迁移期由 Rust Supervisor 成为唯一最终 owner；初期可调用 `python -m deploy`，但不能 Rust/Python
  同时写 PID、manifest、sentinel。
- [inferred] 迁移完成后 `deploy/process.py` 降为兼容 facade，旧脚本仍可调用，生命周期实现只有一份。
- [constraint] 保留 ownership 校验、手工启动实例不可跨实例停止、优雅停止优先于硬杀和 status fallback。

### 6.3 llama-server 与 OpenAI-compatible LLM

- [new] Runtime manifest 增加 `llama` component、模型路径、监听地址、端口、ctx-size、backend、日志和健康检查；
  第一版限制 CPU 或一个明确 GPU backend。
- [existing] 优先复用 `core/llm/lm_studio.py:LMStudioBackend`；如需改名，新增
  `OpenAICompatibleBackend` 后保留 `LMStudioBackend` 兼容别名，不改变 `LLMBackend.generate`/
  `generate_detailed` 契约。
- [existing] `core/llm/registry.py` 继续是唯一 Endpoint × Role 解析点；llama 只表现为 LOCAL endpoint 的
  `BASE_URL/MODEL/KIND/TIMEOUT/CONCURRENCY`。
- [existing] 保留 400 不降级、401/402/403/408/409/425/429/5xx fallback、端点级模型优先级、
  local 并发闸门和 API key 不出 describe/log 的规则。
- [inferred] doctor 复用 `_probe_llm_registry`、`fetch_endpoint_models`、`check_llm_endpoint_reachable`；
  探针采集事实，checks 决定 error/warn。

### 6.4 OneBot/NapCat adapter

- [existing] 复用 `_probe_onebot`、`link_status`、`link_monitor_task` 和 `/stella/status`；第一阶段不自动
  登录 QQ，也不把 NapCat 崩溃直接转化为 Stella Core 退出。
- [inferred] Runtime 生成或校验反向 WebSocket 配置、检测可达性、展示未启动/未登录/断线原因，并等待重连；
  真正的 `NapCatManager` 作为后续可选 component。
- [constraint] NapCat 保持独立版本、目录、日志、许可证和更新生命周期，不修改第三方源码，不把凭据写进 state。

### 6.5 Tauri、CLI、安装器和 Docker

- [existing] Tauri 保留 `run_doctor/get_status/start_bot/stop_bot/run_migrate` 的 invoke 名称和结果兼容；
  `run_deploy_inner` 改为 Runtime client + Python fallback 的迁移入口。
- [existing] `stella-installer/src/api.js` 继续只消费 JSON/文本结果；前端不解析 PID、日志路径或 shell。
- [existing] `cli/src/runner.rs` 增加 Runtime client，local 访问本机 Runtime，Docker 访问容器 adapter；
  旧 deploy/compose 透传在迁移期间保留。
- [inferred] `cli/src/status.rs` 和 Tauri status 统一渲染 Runtime state；`/stella/status` 作为 nested diagnostics。
- [inferred] 发布流程使用 bootstrap installer、Runtime、llama、可选 NapCat 和 model packages，包间独立版本、
  平台、checksum 和回滚记录。
- [existing] Docker 继续以 `STELLA_HOME=/data` 和 compose volume 为数据边界；后续可拆 `llama` service。

### 6.6 Windows 原生可靠性与升级回滚

- [new] 新增 `tests/windows/` 原生 harness 与短生命周期 helper 进程；覆盖真实 `subprocess.Popen`、Windows process group、子孙进程、句柄锁和退出码，不以 monkeypatch 代替系统行为。
- [existing] 加固 `deploy/process.py:start_detached/stop/_hard_kill/status` 与 `runtime-manager/src/lock.rs:InstanceLock.acquire`：明确 owner、PID、launch token、runtime.lock、manifest/state 的单一写入者；清理必须区分“自己的文件”和竞争者新建的文件。
- [existing] 扩展 `deploy/migrate.py:run/_rollback` 为两阶段升级：预检（进程停止、目标目录可写、磁盘空间、版本/签名/checksum）→ versioned staging → 原子切换 → postflight；任何阶段失败都恢复旧 active pointer，不删除用户数据。
- [new] 为运行中安装引入显式 `upgrade.lock`/maintenance state；Windows 句柄占用时返回结构化 `file_locked`，记录被阻塞的相对路径和恢复动作，不循环覆盖或强制删除用户文件。
- [constraint] 真实 Windows 失败时不得将测试降级为 Linux-only；release gate 必须保留失败矩阵的日志、进程树、锁文件和回滚快照。

### 6.7 NapCat 可选安装、登录态隔离与无人值守风险门

- [existing] 复用 `deploy/packages.py` 的 `onebot` package kind、`docker-compose.yml` 的独立 QQ/config volume 和 `link_monitor` 的等待重连语义；不让 NapCat 的崩溃或未登录状态终止 Stella。
- [new] 新增 NapCat package manifest：固定版本与 digest、来源、许可证、SBOM、安装目录、配置目录、QQ data 目录、WebUI 端口和兼容的 OneBot 协议版本；禁止 `latest` 进入发布 manifest。
- [new] 安装流程只下载到 staging，验证 checksum/signature/license 后再原子落地；升级保留旧版本目录和登录态，卸载默认只移除程序，不删除 QQ 数据，删除数据必须二次确认。
- [new] 登录 adapter 只负责展示 `not_installed/not_logged_in/qr_waiting/connected/expired`，凭据写入 Windows Credential Manager/受保护存储或保持外置，不进入 Runtime state、普通日志、catalog 或 crash dump。
- [constraint] “无人值守扫码”默认是禁用状态。只有在 NapCat 官方支持、账号授权、许可证和风控审查全部通过后，才允许实现预置登录态/受控 QR broker；不得 OCR、截取二维码、代替用户确认或绕过平台风控。GA 验收只要求安装无人值守，登录保留人工扫码兜底。

### 6.8 完整 GPU backend 打包

- [existing] 以 `deploy/packages.py:import_model/rollback_model/_catalog_records` 和 Runtime llama manifest 为唯一模型/组件登记入口；模型字节不进入主程序 zip，active model 切换必须可回滚。
- [new] 将 llama backend 资产拆为 `cpu`、`cuda`、`hip`、`metal`、`vulkan` 五类 capability；每个 artifact 带 OS/arch、backend、llama source commit、compiler/toolchain、ABI、最低驱动/loader、依赖 DLL/SO/dylib、license/SBOM 和 SHA256SUMS。
- [new] 推荐命名：`Stella-llama-v<version>-<os>-<arch>-<backend>.zip`；模型单独命名 `Stella-model-<id>-<version>-<format>.{zip,tar.zst}`。catalog 增加 `backend`, `runtime_api`, `driver_min`, `requires_gpu`, `artifact_sha256`, `dependencies`，旧字段保持兼容。
- [new] Windows/Linux CI 分别构建 CPU/Vulkan、CUDA、HIP/ROCm、Metal 所需资产；没有对应硬件的 runner 只能做链接/启动/`/v1/models` smoke，真实生成测试必须在受控 self-hosted GPU runner 执行。
- [constraint] 硬件探测不能把“可执行文件存在”当作 GPU 可用；驱动、显存、架构、模型量化和 ctx-size 不满足时必须明确降级到 CPU 或 `degraded`，不得静默选择错误 backend。
- [constraint] backend 包升级沿用 versioned directory + active pointer + checksum + stop/readiness + rollback；安装失败或运行时加载失败不得改变 active backend/model。
## 7. Implementation Sequence

### Step 0: 重新锚定图谱并冻结契约

1. 解决 GitNexus runner 环境，执行 `node .gitnexus/run.cjs analyze --index-only`；需要语句级分析时再执行
   一次带 `--pdg` 的刷新；重新跑五个主要 symbol 的 impact。
2. 新增 Runtime manifest/state/operation schemas 和字段说明；先不接管进程。
3. 新增契约测试：状态枚举、未知 component 拒绝、任意 shell 参数拒绝、secret 脱敏和版本字段。
4. 产出 schema fixture，作为 Rust、Python、Tauri、CLI 的共同测试输入。

风险门：schema 未稳定前不得改 GUI 或发布布局。

### Step 1: Runtime Manager 最小 crate

1. 创建 `runtime-manager`，把 manifest/state/logging/backoff/component 做成可单测结构。
2. 实现单实例锁和实例目录解析，复用 `config.instance` 的 ID 语义，Rust 不复制 `STELLA_HOME` 定位。
3. 实现显式操作枚举和 JSON I/O；错误使用稳定 code + message，日志不得含 secret。
4. 实现 stdout/stderr 重定向、PID 记录、退出观察和 state 原子写入，先用 fake component 测试。

风险门：Supervisor 先提供 `status`，再提供 `start/stop`；失败不影响旧 `python -m deploy`。

### Step 2: 兼容 adapter 管理 Stella

1. 为 `stella` 接入现有 `deploy start/stop/status`，先让 Runtime 做上层控制器而非第二个 owner。
2. 选定唯一 ownership 方案；推荐 Runtime 最终写自己的 manifest，Python facade 只透传。
3. 映射 stop lifecycle：request stop → graceful wait → signal → hard kill。
4. 用 status API ready、PID alive、ownership match 合成 `starting/running/healthy/failed`。
5. 保留 `python -m deploy start/stop/status` 兼容入口直到 CLI/Tauri 完成迁移。

风险门：修改 `process.py`/`__main__.py` 前重跑 `start_detached`、`process.status`、`_cmd_start` impact。

### Step 3: llama-server，AI 可选

1. 在 manifest 增加 llama component 和模型包引用；模型不进入主程序目录。
2. 实现 host/port/model/ctx/backend 配置；模型缺失、端口占用、进程退出只落为可诊断状态。
3. 用 `/v1/models` + 最小 chat 请求做 readiness，错误写入脱敏 state。
4. 通过 LOCAL endpoint 的 `BASE_URL` 指向 Runtime endpoint，保持 registry 的 role/fallback/gate 语义。
5. 泛化或新增 OpenAI-compatible backend，再跑 registry 全量测试；不要同时重命名所有调用点。

风险门：`registry.py` impact 为 CRITICAL，必须覆盖 doctor、Memory embedding、role backend、fallback、
plugin 和 scheduler。

### Step 4: OneBot adapter 和状态聚合

1. 将 `_probe_onebot`、`link_status`、`link_monitor_task` 映射到 Runtime component state。
2. 生成/校验反向 WS URL、token 一致性和端口可达性；凭据不写 state 和普通日志。
3. NapCat 未运行/未登录/断线显示可操作错误；不自动下载或无人值守扫码。
4. `/stella/status` 保持 loopback 和防御性降级；Runtime 将内部 payload 作为 nested diagnostics。
5. 新增 integration tests，验证断线后等待重连且不会误停 Stella。

风险门：现有 link monitor 只告警不重启；NapCat restart 必须是独立 feature flag。

### Step 5: Tauri 控制面

1. Tauri 加 Runtime client，保持 invoke 名称、错误显示和 JSON shape。
2. Runtime 可用时走 Runtime API，旧目录走 Python fallback；`prepare=true/false` 语义不变。
3. 迁移/初始化后保留 `data_root` invalidate。
4. `read_log_tail` 默认读取 Runtime/组件日志，保留 stella 日志兼容，路径限制在数据根。
5. 更新 Tauri tests 和 GUI smoke path，再删除重复进程管理代码。

风险门：`run_deploy_inner` impact 为 CRITICAL，先确保 GUI doctor/status 每一步仍可运行。

### Step 6: stellacli 和 Docker adapter

1. `cli/src/runner.rs` 增加 Runtime operation client，保留 domain fallback。
2. local 调 Runtime，Docker 调 compose adapter，但字段归一到同一 schema。
3. `cli/src/status.rs` 统一 local/docker 的 state、health、error、endpoint 字段。
4. Docker 增加可选 llama service/adapter，保留现有 volume、healthcheck、依赖和 restart policy。

风险门：CLI `main` 是二进制 entry point，GitNexus upstream UNKNOWN 不代表无使用者；以 README/CI/release 为准。

### Step 7: 安装器、组件包和模型管理

1. Tauri first-run 增加系统检测、Runtime 安装、manifest 写入和 checksum 校验。
2. 模型下载/导入使用临时文件 + checksum + 原子移动；失败不改变 active model。
3. 组件/模型独立版本与回滚记录，用户数据只在 `STELLA_HOME`。
4. 复用 release workflow 组装逻辑，增加安装后 Python/Runtime/llama/schema smoke check。
5. NapCat 作为可选 package，显示许可证、版本和人工扫码步骤。

风险门：只有 Runtime 契约稳定后才处理发布布局和下载器。

### Step 8: 端到端 MVP 和 Docker Server Edition

1. Windows Desktop 完成 Runtime → 可选 llama → Stella → OneBot status 的双击启动。
2. 验证 AI OFF、llama 缺失、NapCat 未登录、OneBot 断线四种降级场景。
3. Docker 映射同一 Contract，允许 NapCat 继续独立部署。
4. 真实 Windows 验证进程树、文件锁、后台窗口、端口冲突和升级回滚。

### Step 9: 收口

1. 执行 `detect_changes({scope:"all"})`；`partial` 或 `truncated` 时重跑。
2. 控制面切换成功后删除重复 Rust/Python owner，只保留一个生命周期实现。
3. 更新设计文档、README、Docker 文档、发布说明和迁移报告模板。
4. 最后生成 goldens、help snapshots 和发布 manifest。

依赖图（推荐顺序）：

`Step 10 Windows 可靠性基线` → `Step 11 升级/回滚矩阵与发布闸门` → `Step 12 NapCat 包合同与来源固定` → `Step 13 NapCat 安装/登录隔离` → `Step 14 GPU capability/catalog 合同` → `Step 15 GPU backend 构建与验证` → `Step 16 统一发布收口`。

其中 Step 12 与 Step 14 在 Step 10 完成后可以并行开发，但任何发布验收仍依赖 Step 11 的 Windows 回滚闸门；Step 15 依赖 Step 14 的 catalog/schema，Step 16 依赖三项全部通过。

### Step 10: Windows 原生可靠性基线

1. 新增受控 helper：父进程启动一个 Stella-like worker，并再启动孙进程；记录 PID、父子关系、stdout/stderr 和退出码。
2. 在 `tests/test_deploy_process.py` 保留逻辑单测，新增 `tests/windows/test_process_tree.py`：真实 `CREATE_NEW_PROCESS_GROUP`、优雅退出、`CTRL_BREAK_EVENT`、`taskkill /T`、孤儿孙进程和重复 stop。
3. 在 `runtime-manager/src/lock.rs` 增加 Windows lock tests：同一目录并发 acquire、异常退出后的残留 lock、句柄仍持有时删除/替换、不同 instance 互不阻塞；明确 stale lock 只能在 PID/owner 证据可信时恢复。
4. 在 `runtime-manager/src/lib.rs`/`deploy/runtime.py` 增加 state/manifest 写入与读取竞态测试；验证半写 JSON、同名临时文件、Windows rename/replace 和 fsync 失败的结构化错误。
5. 输出机器可读 `windows_raw.json` 和人类可读测试报告，报告中必须有 process tree、locked path、state transition 和 cleanup 结果。

风险门：Step 10 任一真实 Windows 场景失败，不能进入 NapCat/GPU 的 Release 集成；Linux 模拟只算开发反馈。

### Step 11: 升级/回滚矩阵与发布闸门

1. 为 `deploy/migrate.py:run/_rollback` 增加 versioned staging、active pointer、backup manifest 和恢复原因；旧安装目录保持只读，`STELLA_HOME` 与登录态不在切换范围。
2. 新增 `tests/windows/test_upgrade_matrix.py`，执行以下矩阵：全新安装、空闲升级、Stella 运行中升级、Stella+llama+NapCat 同时运行、目标文件被占用、用户文件被改写、磁盘空间不足、checksum/signature 失败、进程崩溃后重试、切换后 postflight 失败、重复回滚。
3. 每个矩阵断言：旧版本是否仍可启动、用户数据 hash 是否不变、active pointer 指向何处、锁是否释放、旧目录是否可恢复、退出码/error code 是否稳定。
4. 在 `.github/workflows/ci.yml` 增加 Linux 单测与 Windows 无 GPU native job；在 release workflow 增加 Windows matrix job，未通过时禁止上传 zip/installer。
5. 只有“安装后启动、停止、升级、失败回滚、再次启动”完整通过，才把 `upgrade` 状态从实验标记提升为可发布。

风险门：任何 file lock、用户数据 hash、回滚 pointer 或进程残留断言失败，发布必须停止；不能以人工清理机器替代修复。

### Step 12: NapCat 包合同与来源固定

1. 在 `runtime-manager/schemas/package-catalog.schema.json` 扩展 onebot 字段；新增 NapCat fixture，固定版本、digest、license、source、平台和安装后探针版本。
2. 新增 `deploy/napcat.py` 或等价 adapter，职责限于下载、校验、解包、目录隔离、版本枚举、健康状态和卸载计划；不得把任意命令透传给 GUI。
3. 将 compose 的 `latest` 改为发布 manifest 注入的固定 tag/digest；保留 `./napcat/QQ` 和 `./napcat/config` 的数据边界，并为外部 NapCat 明确 token/网络安全提示。
4. 新增 `tests/test_napcat_package.py`：来源不可信、digest 不匹配、许可证缺失、路径穿越、重复安装、旧版本保留、卸载不删 QQ data、manifest catalog 可验证。
5. 生成 SBOM/license notice；若来源、许可证、digest 或兼容性无法复核，停止发布 onebot artifact。

风险门：先完成“可安装可卸载”，再接登录；不把二维码流程塞进下载器的隐式副作用。

### Step 13: NapCat 安装、登录态隔离与人工扫码兜底

1. 新增 `tests/windows/test_napcat_login.py` 与 mock WebUI server，覆盖未安装、首次启动、QR waiting、人工确认后 connected、过期、断线、重启恢复登录态。
2. Runtime state 只记录枚举状态、时间、脱敏诊断和等待动作；QQ 登录 token、cookie、二维码原文和 WebUI secret 只留在受保护目录/凭据存储。
3. 安装器/CLI 提供 `install/status/login/open-webui/uninstall` 等固定操作；`login` 默认打开本地 WebUI 并显示人工扫码，不承诺后台代扫。
4. 在 `tests/test_runtime_e2e.py` 保留“NapCat 未登录/断线不停止 Stella”；增加 NapCat 进程退出后 Stella 仍 healthy、恢复后状态自动回到 healthy 的断言。
5. 只有官方支持的预置登录态协议、法律批准和风控批准同时存在，才另开 feature flag 研究无人值守登录；该 flag 默认 off，CI 和正式包不得开启。

风险门：任何凭据进入日志/state/catalog、任何未经授权的 QR 自动确认或任何 NapCat 重启连带停止 Stella，立即阻断发布。

### Step 14: GPU capability 与 catalog 合同

1. 扩展 `runtime-manager/schemas/package-catalog.schema.json`、package registry fixture 和 Runtime manifest：声明 backend、artifact、运行时 API、驱动下限、依赖和 fallback。
2. 在 `deploy/packages.py:_catalog_records/build_catalog/verify_catalog` 增加 backend artifact 记录；在 `import_model/rollback_model` 中校验 model/backend 兼容关系，失败不改变 active 状态。
3. 新增 `scripts/verify_llama_package.py`：检查目录布局、可执行文件、依赖库、license/SBOM、SHA256SUMS、manifest/catalog 一致性和不含用户数据。
4. 新增 `tests/test_gpu_catalog.py`：五 backend 元数据、重复/缺失 artifact、错误平台、错误 driver_min、checksum 变化、旧 catalog 兼容和 rollback。
5. 定义兼容决策：CPU 必须可用；CUDA/HIP/Metal/Vulkan 缺失或驱动不满足时返回 `degraded` 并可切 CPU；不支持的组合返回可操作错误而不是启动崩溃。

风险门：schema/catalog 没有表达实际依赖时不得构建发布包；“二进制能启动”不等于“backend 可用”。

### Step 15: GPU backend 构建、硬件验证与资产发布

1. 新增 `.github/workflows/release-llama.yml` 或等价矩阵：锁定 llama.cpp commit，按 OS/arch/backend 构建，上传临时 artifact，不直接覆盖 Release。
2. 构建后运行 `verify_llama_package.py`、`--version`、依赖扫描、`/v1/models` readiness；GPU self-hosted runner 再执行最小 chat、显存/ctx-size 和 CPU fallback smoke。
3. 打包每个 backend 的 `VERSION.txt`、`BACKEND.json`、`SHA256SUMS.txt`、LICENSES、SBOM 和启动说明；模型包独立构建，不重复塞入 backend zip。
4. 修改 `.github/workflows/release.yml` 聚合 backend assets、catalog 和 checksum index；上传前先在干净目录解包再验证，失败不上传任何新 asset。
5. 在 Windows runner 验证 `.exe` + DLL，Linux runner 验证 ELF + SO，Metal 只在 macOS runner 验证；对不具备硬件的 runner 标记为 build-only，不伪造 runtime pass。

风险门：任一 backend 的依赖、license、checksum、`/v1/models` 或真实硬件 smoke 失败，只有该 backend 可被标记 unavailable；若它是默认配置则整个 Release 停止。

### Step 16: 三项任务统一收口

1. Tauri、stellacli、Python deploy、Docker adapter 都只消费同一 catalog/runtime schema；保留 `prepare=true/false` 和旧命令退出码。
2. 执行完整组合：Windows CPU、Windows CUDA/Vulkan（有硬件时）、Windows NapCat 人工扫码、运行中升级回滚、AI OFF、llama 缺失、OneBot 断线。
3. 运行 `detect_changes({scope:"all"})`，要求 `partial=false`、`truncated=false`；再跑 compare against `main`，审阅所有受影响流程。
4. 重新生成 release manifest、goldens、SBOM、license notices 和安装/回滚报告；把实验性无人值守登录保持在默认关闭状态。
5. 只有 Windows matrix、NapCat provenance/login gate、GPU artifact matrix、全量测试和回滚演练都为绿色，才允许发布 4.0.0 后续补丁/正式资产。
## 8. Test Strategy

Existing tests to preserve/update:

- `tests/test_deploy_process.py`: PID、ownership mismatch、sentinel ordering、优雅停止、硬杀、status shape，
  新增 Runtime adapter 不双写 owner。
- `tests/test_deploy_probe.py`: OneBot URL/端口、LLM endpoint、`collect()` never raises，新增 llama readiness。
- `tests/test_deploy_checks.py`: LLM local/online error/warn、model suggestion、STELLA_HOME、OneBot，
  新增 Runtime component health 映射。
- `tests/test_deploy_cli.py`: status JSON、link disconnected、paths/capabilities，新增 Runtime fallback。
- `tests/test_deploy_migrate.py`: runtime reused/fresh、数据分离、dry-run，新增 manifest 不被覆盖。
- `tests/test_llm_registry.py`: endpoint cache、slot lookup、model inheritance、fallback、gate、secret，
  新增 llama LOCAL 等价行为。
- `tests/test_scheduler_concurrency.py`: endpoint resource resolver 保守并发值。
- `tests/test_link_monitor.py`: 断线告警、探活成功、禁用；保持只告警不重启。

New tests:

- `tests/test_runtime_contract.py`: schema fixtures、未知操作拒绝、secret 脱敏、稳定序列化。
- `tests/test_runtime_adapter.py`: Runtime unavailable → Python fallback；迁移 → 单 owner；crash → bounded backoff。
- `runtime-manager/src/*_test.rs`: single-instance lock、health timeout、atomic state、backoff cap、Windows command。
- `tests/test_openai_compatible_backend.py` 或并入 registry：chat/models、model-not-found、400 不 fallback、
  5xx/timeout fallback、API key 脱敏。
- `tests/test_status_contract.py`: status nested diagnostics、loopback 拒绝、取数失败仍降级。

Verification commands:

```bash
python -m pytest tests -q
ruff check .
cd cli && cargo fmt --all --check
cd cli && cargo clippy --all-targets -- -D warnings
cd cli && cargo test
cd cli && cargo build --release
cd stella-installer/src-tauri && cargo tauri build --no-bundle
cd runtime-manager && cargo fmt --all --check
cd runtime-manager && cargo clippy --all-targets -- -D warnings
cd runtime-manager && cargo test
```

[assumed] `cargo tauri` 是否已安装在开发机上尚未执行；CI release workflow 已声明该命令，执行前确认
Windows Tauri CLI 和 WebView2 prerequisites。

### Deferred-task test matrix

- Windows process: 真实父子孙进程、优雅退出、CTRL_BREAK、taskkill tree、重复 stop、foreign PID/launch token、残留 lock、locked manifest/state、临时目录清理。
- Upgrade rollback: 每个场景均记录旧/新版本、运行 PID、被锁路径、前后用户数据 hash、active pointer、state/error code；失败后必须可再次启动旧版本。
- NapCat: 固定 digest 安装、许可证/SBOM、路径隔离、人工 QR 状态、登录态恢复、token 脱敏、断线等待重连、NapCat 退出不影响 Stella。
- GPU: CPU/CUDA/HIP/Metal/Vulkan catalog、平台/架构/驱动拒绝、依赖缺失、checksum、`/v1/models`、最小 chat、CPU fallback、backend/model rollback。

新增/更新文件建议：`tests/windows/test_process_tree.py`、`tests/windows/test_upgrade_matrix.py`、`tests/windows/test_napcat_login.py`、`tests/test_napcat_package.py`、`tests/test_gpu_catalog.py`、`scripts/verify_llama_package.py`；真实 GPU smoke 放在受控 runner，不在普通 PR 中下载模型。

发布阻断命令：`python -m pytest tests -q`、Windows `pytest tests/windows -q -m windows`、`python scripts/check_release_layout.py dist/Stella`、`python scripts/verify_llama_package.py <artifact>`、`docker compose config`、适用 backend 的 `llama-server --version` 与 `/v1/models` smoke。
## 9. Risk and Impact Analysis

- [graph] `core/llm/registry.py:endpoints` 是 CRITICAL hub，d=1 的 11 个依赖必须逐一回归：
  `_legacy_key_warnings`、`_local_slot_override_warning`、`bindings`、`concurrency_of`、`describe`、
  `embedding_gate`、`endpoint`、`_probe_llm_registry` 和三组 registry tests；d=2/3 覆盖
  `backend_for_endpoint`、`collect`、`EmbeddingService.embed`、LLM registry tests 和 scheduler tests。
- [graph] `run_deploy_inner` 是 CRITICAL bridge；两个直接 wrapper 会影响 Tauri doctor/status/start/stop/migrate/
  config/persona/log flows。任何接口、退出码、stdout JSON 或 prepare 行为变化都会波及 GUI。
- [graph] `LMStudioBackend` 是 MEDIUM/lower-bound，存在 interface dispatch boundary；先 grep 所有 imports/
  constructors，并保留 alias。
- [verified] Windows 停止流程依赖 `CTRL_BREAK_EVENT`/`taskkill /T`、文件哨兵和进程树；必须真实 Windows 验证。
- [verified] `STELLA_HOME` 和 `data_root` 缓存是迁移风险点；init/migrate 写指针后必须 invalidate。
- [inferred] Runtime state 与 `/stella/status` 有不同时间尺度；使用 nested diagnostics，避免覆盖同字段。
- [inferred] llama 模型加载、端口、ctx-size 和 GPU backend 是资源风险；第一版限制 backend。
- [verified] OneBot monitor 当前只告警并等待重连；自动重启必须独立 flag、测试和 release note。
- [inferred] 安装/更新必须 checksum、临时文件、文件锁和回滚，不覆盖运行中的 binary。
- [assumed] NapCat 分发/许可证/登录/风控尚未形成仓库内合同，自动管理后置为可选阶段。

- [verified] Windows `start_detached/stop/_hard_kill` 的行为依赖进程组、CTRL_BREAK、taskkill tree 和句柄时序；mock 通过不能替代 native pass。
- [verified] `InstanceLock.acquire` 当前使用 `create_new(true)` 并在 Drop 删除锁文件；异常退出、残留 lock、删除/替换竞态和 stale owner 恢复尚未形成完整合同。
- [verified] `migrate.run` 的 incoming 是 lower-bound，且 `_rollback` 只按本次写入列表清理；跨版本目录切换必须新增 active pointer/backup 证据，不能扩大删除范围。
- [verified] NapCat 当前 image 是 `latest`，登录态挂载在 `napcat/QQ`；未固定来源或误删卷会造成不可审计升级和强制重新扫码。
- [inferred] 无人值守 QR 的最大风险不是技术实现，而是账号授权、平台风控、第三方条款和凭据保管；因此默认关闭且不作为 4.0.0 GA 的成功条件。
- [verified] 当前 catalog 只记录 kind/id/version/path/checksum/platform；GPU 依赖和驱动信息必须在 schema 扩展后才可被安装器安全选择。
- [inferred] GPU runner 没有硬件时只能证明构建/链接/启动，不能证明真实推理；发布矩阵必须区分 build-only 与 runtime-verified。
- [constraint] 发布前必须同时满足：Windows 回滚矩阵全绿、NapCat 来源/许可证/凭据闸门全绿、默认 GPU backend 的真实 smoke 全绿；否则停止发布而不是降级为“已知问题”。
## 10. Files Expected to Change

| File | Symbols | Reason |
| ---- | ------- | ------ |
| `runtime-manager/Cargo.toml` | new crate | Rust Supervisor boundary |
| `runtime-manager/src/*.rs` | new RuntimeManager/Supervisor/Component/Health/Manifest | Contract implementation |
| `runtime-manager/schemas/*.json` | new schemas | Shared JSON contract |
| `deploy/process.py` | `start_detached`, `stop`, `status` | Single ownership migration |
| `deploy/__main__.py` | `_cmd_start`, `_cmd_stop`, `_cmd_status`, `main` | Runtime routing and CLI compatibility |
| `deploy/probe.py` | `_probe_llm_registry`, `_probe_onebot`, `collect` | Runtime facts |
| `deploy/checks.py` | LLM checks, `_ALL_CHECKS` | Doctor severity policy |
| `config/instance.py` / `config/settings.py` | runtime paths/settings | Instance and llama config |
| `core/llm/lm_studio.py` | `LMStudioBackend` | OpenAI-compatible generalization |
| `core/llm/registry.py` | `endpoints`, `_build_backend`, `describe` | Runtime LOCAL endpoint |
| `stella_project/plugins/bot_main/status_api.py` | `setup_status_api` | Stable nested diagnostics |
| `stella-installer/src-tauri/src/python.rs` | `run_deploy_inner`, `data_root` | Runtime client/fallback |
| `stella-installer/src-tauri/src/commands.rs` | GUI commands | Control-plane migration |
| `stella-installer/src/api.js` | status/start/stop/log wrappers | Frontend compatibility |
| `cli/src/runner.rs` / `main.rs` / `status.rs` | command builders and renderers | CLI Runtime adapter |
| `docker-compose.yml` / `Dockerfile` | services and healthcheck | Docker adapter |
| existing and new tests | named in §8 | Regression and contract coverage |
| release workflows/scripts | existing release jobs | Component packages/checksums |
| `runtime-manager/src/lock.rs` / `src/lib.rs` / `src/main.rs` | `InstanceLock.acquire`, `RuntimeStore`, CLI dispatch | Windows lock、原子 state 和 supervisor operation 约束 |
| `tests/windows/test_process_tree.py` | new native harness tests | 真实进程树、CTRL_BREAK、taskkill tree |
| `tests/windows/test_upgrade_matrix.py` | new upgrade matrix | 文件锁、运行中升级、失败恢复、用户数据 hash |
| `deploy/migrate.py` | `run`, `_rollback` | versioned staging、active pointer、回滚原因 |
| `tests/test_napcat_package.py` / `tests/windows/test_napcat_login.py` | new package/login tests | NapCat 安装、许可证、隔离、人工扫码状态 |
| `deploy/packages.py` | `_catalog_records`, `build_catalog`, `verify_catalog`, `import_model`, `rollback_model` | backend/artifact metadata 与 model/backend rollback |
| `runtime-manager/schemas/package-catalog.schema.json` / fixtures | package schema | backend、driver、ABI、依赖、provenance 字段 |
| `scripts/verify_llama_package.py` | new verifier | llama artifact 布局、依赖、license、SBOM、checksum |
| `.github/workflows/ci.yml` / `release.yml` / new `release-llama.yml` | CI/release jobs | Windows matrix、GPU matrix、artifact aggregation 和阻断闸门 |
| `docker-compose.yml` | llama/napcat services | 固定 digest、contract labels、可选组件状态 |
| `tests/test_gpu_catalog.py` / `tests/test_release_layout.py` | new/updated tests | GPU 包、敏感文件、catalog 和发布布局闭环 |

## 11. Reusable Implementation Context

The JSON below is the exact implementation context pack emitted by the provenance helper.


```json
{
  "implementation_context": {
    "task_summary": "在已落地的 Runtime Contract、Python 兼容层、Runtime manager、包 catalog 和 Docker profile 基础上，按依赖完成 Windows 原生可靠性/升级回滚、NapCat 可选安装与登录隔离、完整 llama.cpp GPU backend 打包，并将三者纳入统一发布闸门。",
    "acceptance_criteria": [
      "Windows native process-tree, file-lock and upgrade/rollback matrix passes on supported runners.",
      "NapCat package has pinned provenance, license/SBOM, isolated QQ/config data and manual QR fallback; unattended login remains disabled unless separately approved.",
      "CPU/CUDA/HIP/Metal/Vulkan llama artifacts have backend metadata, checksum, dependency and driver compatibility records.",
      "Failed install or runtime readiness never changes active package/model/backend and can restore the previous version.",
      "4.0.0 release is blocked when any required native, provenance, security or runtime smoke gate is red."
    ],
    "evidence_provenance": {
      "schema_version": 2,
      "head_commit": "45630b7107e29620f7e1a6039e71b3f79bf7c1e1",
      "generated_plan_path": "docs/plans/2026-09-11-gitnexus-plan-runtime-supervisor-rollout.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "ddae2d79e44267d6fd40de31c3f37d8d0f10af2a37e7e7e7753d1c4300704ecf"
      },
      "cited_path_manifest": [
        {
          "path": ".github/CONTRIBUTING.md",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",
          "index_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",
          "worktree_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",
          "untracked_digest": "absent"
        },
        {
          "path": ".github/workflows/ci.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:72ffa0a55d11fd17d17ca884615f5ae7976f2f0487d793f90720e61f5296fa5f",
          "index_digest": "sha256:72ffa0a55d11fd17d17ca884615f5ae7976f2f0487d793f90720e61f5296fa5f",
          "worktree_digest": "sha256:23cf14adfcf4c2ae1baeb9d4cb7ed173ac12c985f0bf5ddb217a02576039fb0f",
          "untracked_digest": "absent"
        },
        {
          "path": ".github/workflows/release-memory-rust.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:931a023f460581a7b96331627935c6793f4b2823ff37935278d2b2d6f50ccaac",
          "index_digest": "sha256:931a023f460581a7b96331627935c6793f4b2823ff37935278d2b2d6f50ccaac",
          "worktree_digest": "sha256:931a023f460581a7b96331627935c6793f4b2823ff37935278d2b2d6f50ccaac",
          "untracked_digest": "absent"
        },
        {
          "path": ".github/workflows/release.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d2d1b00f5f92c3dcec0d78560b47ae769c4f92ab6001db0d82d36568a08093d4",
          "index_digest": "sha256:d2d1b00f5f92c3dcec0d78560b47ae769c4f92ab6001db0d82d36568a08093d4",
          "worktree_digest": "sha256:d2d1b00f5f92c3dcec0d78560b47ae769c4f92ab6001db0d82d36568a08093d4",
          "untracked_digest": "absent"
        },
        {
          "path": "Dockerfile",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",
          "index_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",
          "worktree_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",
          "untracked_digest": "absent"
        },
        {
          "path": "cli/Cargo.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b4c775fb048ab6137bb35747ce3bf224fde9cea37fb8a2ff59e4dbbef0d75638",
          "index_digest": "sha256:b4c775fb048ab6137bb35747ce3bf224fde9cea37fb8a2ff59e4dbbef0d75638",
          "worktree_digest": "sha256:b4c775fb048ab6137bb35747ce3bf224fde9cea37fb8a2ff59e4dbbef0d75638",
          "untracked_digest": "absent"
        },
        {
          "path": "cli/src/main.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:042339644e0a368a95b4be51086133fa51842b6b56202760bee382f73275d305",
          "index_digest": "sha256:042339644e0a368a95b4be51086133fa51842b6b56202760bee382f73275d305",
          "worktree_digest": "sha256:042339644e0a368a95b4be51086133fa51842b6b56202760bee382f73275d305",
          "untracked_digest": "absent"
        },
        {
          "path": "cli/src/runner.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:16e3f1f1420fc995c1796180afdf87ab3bc275246b66d69c9dada1d4c4f42abd",
          "index_digest": "sha256:16e3f1f1420fc995c1796180afdf87ab3bc275246b66d69c9dada1d4c4f42abd",
          "worktree_digest": "sha256:16e3f1f1420fc995c1796180afdf87ab3bc275246b66d69c9dada1d4c4f42abd",
          "untracked_digest": "absent"
        },
        {
          "path": "cli/src/status.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:22d7fe2093fcb2e773fb83248cb66f5aaae2acaf80086aaf83fb1a464c986047",
          "index_digest": "sha256:22d7fe2093fcb2e773fb83248cb66f5aaae2acaf80086aaf83fb1a464c986047",
          "worktree_digest": "sha256:22d7fe2093fcb2e773fb83248cb66f5aaae2acaf80086aaf83fb1a464c986047",
          "untracked_digest": "absent"
        },
        {
          "path": "config/home.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2a97b49aeeee31e26831b2585160cb80bcc7f82dda08856ee71cd85aad0d7484",
          "index_digest": "sha256:2a97b49aeeee31e26831b2585160cb80bcc7f82dda08856ee71cd85aad0d7484",
          "worktree_digest": "sha256:2a97b49aeeee31e26831b2585160cb80bcc7f82dda08856ee71cd85aad0d7484",
          "untracked_digest": "absent"
        },
        {
          "path": "config/instance.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c6a71dd5591b5b2e924b98aca18b2806d6c8198104accb291ac4b21b1c13280e",
          "index_digest": "sha256:c6a71dd5591b5b2e924b98aca18b2806d6c8198104accb291ac4b21b1c13280e",
          "worktree_digest": "sha256:c6a71dd5591b5b2e924b98aca18b2806d6c8198104accb291ac4b21b1c13280e",
          "untracked_digest": "absent"
        },
        {
          "path": "config/settings.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3ac5090048e85ee44fb6916b19b76e4f6f9ce2c2b8674fb8bdb8734e8debe39b",
          "index_digest": "sha256:3ac5090048e85ee44fb6916b19b76e4f6f9ce2c2b8674fb8bdb8734e8debe39b",
          "worktree_digest": "sha256:43a35f1cc6c502d81af15511970f9f1b84cb101464d91cfa4a98e6c0b957e992",
          "untracked_digest": "absent"
        },
        {
          "path": "core/llm/base.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c99f95ddf62b440027360792c3c2a6d4c7506f1acfc38198be7396ae36b6a2a8",
          "index_digest": "sha256:c99f95ddf62b440027360792c3c2a6d4c7506f1acfc38198be7396ae36b6a2a8",
          "worktree_digest": "sha256:c99f95ddf62b440027360792c3c2a6d4c7506f1acfc38198be7396ae36b6a2a8",
          "untracked_digest": "absent"
        },
        {
          "path": "core/llm/lm_studio.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e6525af6e3d15662ef441647276a2a1d51cb05851f83f3fe407b44d51fc85b1d",
          "index_digest": "sha256:e6525af6e3d15662ef441647276a2a1d51cb05851f83f3fe407b44d51fc85b1d",
          "worktree_digest": "sha256:e6525af6e3d15662ef441647276a2a1d51cb05851f83f3fe407b44d51fc85b1d",
          "untracked_digest": "absent"
        },
        {
          "path": "core/llm/registry.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f2770c6f2e85ac3460a20d1916b0d087768f769df51c932859dfa51780a79269",
          "index_digest": "sha256:f2770c6f2e85ac3460a20d1916b0d087768f769df51c932859dfa51780a79269",
          "worktree_digest": "sha256:3e3796108763cf2f7f53eaad7dce6ae3ea7eb987d39266e18a1738049aa21c04",
          "untracked_digest": "absent"
        },
        {
          "path": "core/llm/scheduler.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1867025f4767030a779914106ec075106a3860baa67b247787aad90426d412a2",
          "index_digest": "sha256:1867025f4767030a779914106ec075106a3860baa67b247787aad90426d412a2",
          "worktree_digest": "sha256:1867025f4767030a779914106ec075106a3860baa67b247787aad90426d412a2",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/__main__.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:bf2f75ef9f68bb3ad3cd8dbbf64160fa0e7cc4af5e798d10a41ba2959f5cc556",
          "index_digest": "sha256:bf2f75ef9f68bb3ad3cd8dbbf64160fa0e7cc4af5e798d10a41ba2959f5cc556",
          "worktree_digest": "sha256:7cecd45be64b9e9fdd23efe2270845b9d45fc4cff5cc290b2aebf1aa8fb184ea",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/checks.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:7546006cda25badc3d59e1d3caa79ec0d5fd039b1362d74435a76047227b4e77",
          "index_digest": "sha256:7546006cda25badc3d59e1d3caa79ec0d5fd039b1362d74435a76047227b4e77",
          "worktree_digest": "sha256:7546006cda25badc3d59e1d3caa79ec0d5fd039b1362d74435a76047227b4e77",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/migrate.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9a01ffbd252fb23d53be14d29747333657578afd85a5d96a0f41f7b51ef8bd08",
          "index_digest": "sha256:9a01ffbd252fb23d53be14d29747333657578afd85a5d96a0f41f7b51ef8bd08",
          "worktree_digest": "sha256:9a01ffbd252fb23d53be14d29747333657578afd85a5d96a0f41f7b51ef8bd08",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/packages.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a7cde5a3c4308b75b89b4f91b26019add014aa66c31300882c380703d4feb9e4",
          "index_digest": "sha256:a7cde5a3c4308b75b89b4f91b26019add014aa66c31300882c380703d4feb9e4",
          "worktree_digest": "sha256:a7cde5a3c4308b75b89b4f91b26019add014aa66c31300882c380703d4feb9e4",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/probe.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c9c845c5f21c040502f3abc51352c6d4b2ba609e511c1c5b12d763acf8d21a30",
          "index_digest": "sha256:c9c845c5f21c040502f3abc51352c6d4b2ba609e511c1c5b12d763acf8d21a30",
          "worktree_digest": "sha256:c9c845c5f21c040502f3abc51352c6d4b2ba609e511c1c5b12d763acf8d21a30",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/process.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:40c926d5e3253eca498e30996cc46763a65e11a53f6ab9f5e77902e912bd8684",
          "index_digest": "sha256:40c926d5e3253eca498e30996cc46763a65e11a53f6ab9f5e77902e912bd8684",
          "worktree_digest": "sha256:02e21cdf9a5ea5cb4a3ab539b1fea578239b776d2c9290068bb1ed2f5c2c3f85",
          "untracked_digest": "absent"
        },
        {
          "path": "deploy/runtime.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:81f0050d527e7f5004862650affe0fb965d12388a62a9628b6ea32cdc13b23ea",
          "index_digest": "sha256:81f0050d527e7f5004862650affe0fb965d12388a62a9628b6ea32cdc13b23ea",
          "worktree_digest": "sha256:81f0050d527e7f5004862650affe0fb965d12388a62a9628b6ea32cdc13b23ea",
          "untracked_digest": "absent"
        },
        {
          "path": "design_docs/Stella Runtime & One-Click Deployment Architecture.md",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e33d2b0bbf9f7c843207d8684d4809e4a5a8ce66f530e1509c265d87b72efc95",
          "index_digest": "sha256:e33d2b0bbf9f7c843207d8684d4809e4a5a8ce66f530e1509c265d87b72efc95",
          "worktree_digest": "sha256:e33d2b0bbf9f7c843207d8684d4809e4a5a8ce66f530e1509c265d87b72efc95",
          "untracked_digest": "absent"
        },
        {
          "path": "design_docs/Stella Runtime 落地实施方案 v1.0.md",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4225f26afbd38c24756fa71b0420ea0a39d982859eda7c927dbc8f236e36bd03",
          "index_digest": "sha256:4225f26afbd38c24756fa71b0420ea0a39d982859eda7c927dbc8f236e36bd03",
          "worktree_digest": "sha256:4225f26afbd38c24756fa71b0420ea0a39d982859eda7c927dbc8f236e36bd03",
          "untracked_digest": "absent"
        },
        {
          "path": "docker-compose.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4e8ce128138aafe1309b5a28ea9914d42d6684b25739a600024b9223bc8392af",
          "index_digest": "sha256:4e8ce128138aafe1309b5a28ea9914d42d6684b25739a600024b9223bc8392af",
          "worktree_digest": "sha256:4e8ce128138aafe1309b5a28ea9914d42d6684b25739a600024b9223bc8392af",
          "untracked_digest": "absent"
        },
        {
          "path": "extensions/link_monitor/__init__.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c4fecb4a9a24143065064153b61be65dffe88c57c0cd8357beaf4f8d8a6c3595",
          "index_digest": "sha256:c4fecb4a9a24143065064153b61be65dffe88c57c0cd8357beaf4f8d8a6c3595",
          "worktree_digest": "sha256:c4fecb4a9a24143065064153b61be65dffe88c57c0cd8357beaf4f8d8a6c3595",
          "untracked_digest": "absent"
        },
        {
          "path": "pyproject.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:eb2d1696502fd58e344d4cacef3965453ff52c4cc68f95d64919a49784eab51e",
          "index_digest": "sha256:eb2d1696502fd58e344d4cacef3965453ff52c4cc68f95d64919a49784eab51e",
          "worktree_digest": "sha256:079ea1977201238688688e58445fd9df9ee170da57833e7276e23670d36020df",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/Cargo.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4e2e0d84a264e51fcde8322b9f3e90029b831897831c7d3a9c4eadb1255c2de7",
          "index_digest": "sha256:4e2e0d84a264e51fcde8322b9f3e90029b831897831c7d3a9c4eadb1255c2de7",
          "worktree_digest": "sha256:4e2e0d84a264e51fcde8322b9f3e90029b831897831c7d3a9c4eadb1255c2de7",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/schemas/fixtures/runtime-manifest.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3ecb9e537fc06ea350f6a6714d15c12e2a7778c0fd1fd96c11602c0952126c2f",
          "index_digest": "sha256:3ecb9e537fc06ea350f6a6714d15c12e2a7778c0fd1fd96c11602c0952126c2f",
          "worktree_digest": "sha256:3ecb9e537fc06ea350f6a6714d15c12e2a7778c0fd1fd96c11602c0952126c2f",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/schemas/fixtures/runtime-state.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:0510414cadd75adbe93d9ad52be06cc3bbfa2408177335447d53724533104c60",
          "index_digest": "sha256:0510414cadd75adbe93d9ad52be06cc3bbfa2408177335447d53724533104c60",
          "worktree_digest": "sha256:0510414cadd75adbe93d9ad52be06cc3bbfa2408177335447d53724533104c60",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/schemas/package-catalog.schema.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c170f7ab711c18bf1f9169d6aa2ffa0bf049ca06be53017c2ffc83ef89fe6ae0",
          "index_digest": "sha256:c170f7ab711c18bf1f9169d6aa2ffa0bf049ca06be53017c2ffc83ef89fe6ae0",
          "worktree_digest": "sha256:c170f7ab711c18bf1f9169d6aa2ffa0bf049ca06be53017c2ffc83ef89fe6ae0",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/schemas/package-registry.schema.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2a5c09fb044b7d245f994eb4205e3463eb9c5a2fa0396f5c98272091e25b0d7b",
          "index_digest": "sha256:2a5c09fb044b7d245f994eb4205e3463eb9c5a2fa0396f5c98272091e25b0d7b",
          "worktree_digest": "sha256:2a5c09fb044b7d245f994eb4205e3463eb9c5a2fa0396f5c98272091e25b0d7b",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/schemas/runtime-manifest.schema.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:10a4baf1b5d718d9462d7cc5ee6d53e981acc4e9202fc924c2216410f2b1aa0b",
          "index_digest": "sha256:10a4baf1b5d718d9462d7cc5ee6d53e981acc4e9202fc924c2216410f2b1aa0b",
          "worktree_digest": "sha256:10a4baf1b5d718d9462d7cc5ee6d53e981acc4e9202fc924c2216410f2b1aa0b",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/schemas/runtime-state.schema.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:5fd63e6cecb79f5662c407cd64d6c711e6dbbc92ce3627a6007331c5b4afd689",
          "index_digest": "sha256:5fd63e6cecb79f5662c407cd64d6c711e6dbbc92ce3627a6007331c5b4afd689",
          "worktree_digest": "sha256:5fd63e6cecb79f5662c407cd64d6c711e6dbbc92ce3627a6007331c5b4afd689",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/src/backoff.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:0949b89de3a80b23f92105c98fe4b457436081b4320c0db6fd4988ed757984d6",
          "index_digest": "sha256:0949b89de3a80b23f92105c98fe4b457436081b4320c0db6fd4988ed757984d6",
          "worktree_digest": "sha256:0949b89de3a80b23f92105c98fe4b457436081b4320c0db6fd4988ed757984d6",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/src/lib.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:74c8a0f8e406d60b0ce5ac0baaf607e49274a851058851eefef66b3d4c63efa2",
          "index_digest": "sha256:74c8a0f8e406d60b0ce5ac0baaf607e49274a851058851eefef66b3d4c63efa2",
          "worktree_digest": "sha256:74c8a0f8e406d60b0ce5ac0baaf607e49274a851058851eefef66b3d4c63efa2",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/src/lock.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:142edb1ed2361be2eb5504a9405efd1e0b67ae65258965373410649a6e6f1994",
          "index_digest": "sha256:142edb1ed2361be2eb5504a9405efd1e0b67ae65258965373410649a6e6f1994",
          "worktree_digest": "sha256:142edb1ed2361be2eb5504a9405efd1e0b67ae65258965373410649a6e6f1994",
          "untracked_digest": "absent"
        },
        {
          "path": "runtime-manager/src/main.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:0f6fa61fc02e7a1fa2736b889b1d4d8fe0663f952bb5241a488f845ae5297e60",
          "index_digest": "sha256:0f6fa61fc02e7a1fa2736b889b1d4d8fe0663f952bb5241a488f845ae5297e60",
          "worktree_digest": "sha256:0f6fa61fc02e7a1fa2736b889b1d4d8fe0663f952bb5241a488f845ae5297e60",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/check_release_layout.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:ad44a7456f8c7afe38067ad68ecea4fb85707f4419af2e1775a496e855cdedb6",
          "index_digest": "sha256:ad44a7456f8c7afe38067ad68ecea4fb85707f4419af2e1775a496e855cdedb6",
          "worktree_digest": "sha256:ad44a7456f8c7afe38067ad68ecea4fb85707f4419af2e1775a496e855cdedb6",
          "untracked_digest": "absent"
        },
        {
          "path": "stella-installer/src-tauri/Cargo.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:6d13dcad6e1d7f99dbfa8fa52523fd26ac96272a59702883d36ac193075665f1",
          "index_digest": "sha256:6d13dcad6e1d7f99dbfa8fa52523fd26ac96272a59702883d36ac193075665f1",
          "worktree_digest": "sha256:6d13dcad6e1d7f99dbfa8fa52523fd26ac96272a59702883d36ac193075665f1",
          "untracked_digest": "absent"
        },
        {
          "path": "stella-installer/src-tauri/src/commands.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:5c03e835dcbbbbb2a17e350df4c2e79a03127b17587d95aed864f0ce0789e350",
          "index_digest": "sha256:5c03e835dcbbbbb2a17e350df4c2e79a03127b17587d95aed864f0ce0789e350",
          "worktree_digest": "sha256:447311fe592e04ff23313eacc4f200271d8faa4ec353d5b95f027d973c8e72fb",
          "untracked_digest": "absent"
        },
        {
          "path": "stella-installer/src-tauri/src/python.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:6143aaf005847467d6a318f87d88513f85585c4d719f0d2484d5908cc08394fd",
          "index_digest": "sha256:6143aaf005847467d6a318f87d88513f85585c4d719f0d2484d5908cc08394fd",
          "worktree_digest": "sha256:6143aaf005847467d6a318f87d88513f85585c4d719f0d2484d5908cc08394fd",
          "untracked_digest": "absent"
        },
        {
          "path": "stella-installer/src/api.js",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f7b78c97636025c4569790ec2f0cdba201703fd2ff9c312f602fc5049c9cbd71",
          "index_digest": "sha256:f7b78c97636025c4569790ec2f0cdba201703fd2ff9c312f602fc5049c9cbd71",
          "worktree_digest": "sha256:f7b78c97636025c4569790ec2f0cdba201703fd2ff9c312f602fc5049c9cbd71",
          "untracked_digest": "absent"
        },
        {
          "path": "stella_project/plugins/bot_main/status_api.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c0acc65e86642517df3db68d6d8b926a3f18be15b19259bd484cddb0e00bf768",
          "index_digest": "sha256:c0acc65e86642517df3db68d6d8b926a3f18be15b19259bd484cddb0e00bf768",
          "worktree_digest": "sha256:c0acc65e86642517df3db68d6d8b926a3f18be15b19259bd484cddb0e00bf768",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_deploy_checks.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:41c7c983d23ea003284258501b2df39ef7986367450506797d8c734158b86139",
          "index_digest": "sha256:41c7c983d23ea003284258501b2df39ef7986367450506797d8c734158b86139",
          "worktree_digest": "sha256:41c7c983d23ea003284258501b2df39ef7986367450506797d8c734158b86139",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_deploy_cli.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:05fcc53db06c319e7770f5cd4bbad2f9f99d9d9d15763a6a759b494f1785c69e",
          "index_digest": "sha256:05fcc53db06c319e7770f5cd4bbad2f9f99d9d9d15763a6a759b494f1785c69e",
          "worktree_digest": "sha256:05fcc53db06c319e7770f5cd4bbad2f9f99d9d9d15763a6a759b494f1785c69e",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_deploy_migrate.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d82b81d15923b2b69d77cf9c7e4da8842f3b5d458dd28f31a6098cf48a4f862d",
          "index_digest": "sha256:d82b81d15923b2b69d77cf9c7e4da8842f3b5d458dd28f31a6098cf48a4f862d",
          "worktree_digest": "sha256:d82b81d15923b2b69d77cf9c7e4da8842f3b5d458dd28f31a6098cf48a4f862d",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_deploy_probe.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1510d99623ed951f98cca1297f5fc0fd38b698577bd6ecc5ddceb43e728dd6fb",
          "index_digest": "sha256:1510d99623ed951f98cca1297f5fc0fd38b698577bd6ecc5ddceb43e728dd6fb",
          "worktree_digest": "sha256:1b3518a17569ef9381cc3e084c6402fcdb6e50af4c2a17be616147a9cf9a7b01",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_deploy_process.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:bb7d737a86f5f9f9ab1705ae4eb5fdb5cfe7e04f654d06e74e986c74fdfbb2de",
          "index_digest": "sha256:bb7d737a86f5f9f9ab1705ae4eb5fdb5cfe7e04f654d06e74e986c74fdfbb2de",
          "worktree_digest": "sha256:076a1cab125975a9ea9c72040a774a1c1ebb54adb9f73f996094242d095419ad",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_link_monitor.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:429abe73c6cf7fbff776ac2caa8889d658caffa3e43ba5c6b93f4373a21233ab",
          "index_digest": "sha256:429abe73c6cf7fbff776ac2caa8889d658caffa3e43ba5c6b93f4373a21233ab",
          "worktree_digest": "sha256:429abe73c6cf7fbff776ac2caa8889d658caffa3e43ba5c6b93f4373a21233ab",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_llm_registry.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a6b33b4ca9003c287ed698864cda9f15b74bb3cf403c4813e5ecd0dbd190690a",
          "index_digest": "sha256:a6b33b4ca9003c287ed698864cda9f15b74bb3cf403c4813e5ecd0dbd190690a",
          "worktree_digest": "sha256:a6b33b4ca9003c287ed698864cda9f15b74bb3cf403c4813e5ecd0dbd190690a",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_packages.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4f59f103095478e419a91bf861002aac9abc990b4f3165f098e3d793622d6597",
          "index_digest": "sha256:4f59f103095478e419a91bf861002aac9abc990b4f3165f098e3d793622d6597",
          "worktree_digest": "sha256:4f59f103095478e419a91bf861002aac9abc990b4f3165f098e3d793622d6597",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_release_layout.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:0aeef5aaeb73f9509ed8f7f243a0a6259ff12ce7ca928c47d6d41de20740c0a2",
          "index_digest": "sha256:0aeef5aaeb73f9509ed8f7f243a0a6259ff12ce7ca928c47d6d41de20740c0a2",
          "worktree_digest": "sha256:836a168e29288381410299d919afd1c8cbe32bced85d6eacea4f3f3015e2b3cf",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_runtime_contract.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:50aca6aac9f1e78f07a8c0ef207a4af0108ea39236eeebe46a88f23df69e03e7",
          "index_digest": "sha256:50aca6aac9f1e78f07a8c0ef207a4af0108ea39236eeebe46a88f23df69e03e7",
          "worktree_digest": "sha256:50aca6aac9f1e78f07a8c0ef207a4af0108ea39236eeebe46a88f23df69e03e7",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_runtime_e2e.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:71ff2101f051f3e599d9337d9d81b20c18a92bbf1ce32b9940a5de16a0c12fdb",
          "index_digest": "sha256:71ff2101f051f3e599d9337d9d81b20c18a92bbf1ce32b9940a5de16a0c12fdb",
          "worktree_digest": "sha256:71ff2101f051f3e599d9337d9d81b20c18a92bbf1ce32b9940a5de16a0c12fdb",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_scheduler_concurrency.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:6b69eecff94c40ddbc1a4bf2ee680ec08ce1a98544c1fb4c30297b69f199add0",
          "index_digest": "sha256:6b69eecff94c40ddbc1a4bf2ee680ec08ce1a98544c1fb4c30297b69f199add0",
          "worktree_digest": "sha256:6b69eecff94c40ddbc1a4bf2ee680ec08ce1a98544c1fb4c30297b69f199add0",
          "untracked_digest": "absent"
        }
      ]
    },
    "primary_symbols": [
      {
        "symbol": "endpoints",
        "file": "core/llm/registry.py",
        "lines": "245-251",
        "role": "shared endpoint resolver and cache"
      },
      {
        "symbol": "run_deploy_inner",
        "file": "stella-installer/src-tauri/src/python.rs",
        "lines": "825-860",
        "role": "Tauri-to-Python control bridge"
      },
      {
        "symbol": "start_detached",
        "file": "deploy/process.py",
        "lines": "167-212",
        "role": "current Stella process owner"
      },
      {
        "symbol": "setup_status_api",
        "file": "stella_project/plugins/bot_main/status_api.py",
        "lines": "145-212",
        "role": "Core local status endpoint"
      },
      {
        "symbol": "LMStudioBackend",
        "file": "core/llm/lm_studio.py",
        "lines": "33-230",
        "role": "existing OpenAI-compatible backend"
      }
    ],
    "related_symbols": [
      {
        "symbol": "process.stop/status",
        "relationship": "calls/compatibility",
        "relevance": "ownership, graceful shutdown and status fallback"
      },
      {
        "symbol": "_cmd_start/_cmd_status",
        "relationship": "calls",
        "relevance": "deploy CLI surface"
      },
      {
        "symbol": "_probe_llm_registry/collect",
        "relationship": "calls",
        "relevance": "doctor evidence collection"
      },
      {
        "symbol": "check_llm_config_issues/check_llm_endpoint_reachable",
        "relationship": "calls",
        "relevance": "doctor severity policy"
      },
      {
        "symbol": "run_deploy/run_deploy_without_prepare",
        "relationship": "CALLS",
        "relevance": "direct Tauri bridge dependents"
      },
      {
        "symbol": "link_monitor_task/link_status",
        "relationship": "calls",
        "relevance": "OneBot health and reconnect semantics"
      },
      {
        "symbol": "Ctx::deploy_cmd/compose_deploy_cmd",
        "relationship": "calls",
        "relevance": "CLI local/Docker adapter"
      }
    ],
    "execution_path": [
      "Re-anchor Docker GitNexus at 45630b7 and freeze the contract/schema and release gates.",
      "Prove real Windows process ownership, locks, upgrade staging and rollback before changing release eligibility.",
      "Pin NapCat source/version/digest and install it into isolated program/config/QQ data roots; expose manual QR states only.",
      "Extend package catalog with backend/driver/ABI/provenance data and keep model/backend activation transactional.",
      "Build and verify llama CPU/CUDA/HIP/Metal/Vulkan artifacts on appropriate runners, distinguishing build-only from GPU runtime verification.",
      "Run combined Windows/NapCat/GPU release matrix, detect graph changes, regenerate manifest/SBOM/goldens, then publish only if all gates pass."
    ],
    "pdg_constraints": [
      {
        "description": "The exposed MCP pdg_query returned no edges while its host view was stale; Docker CLI has no pdg-query subcommand, so no PDG edge is treated as authoritative.",
        "affected_statements": [],
        "implementation_consequence": "Use current source ordering and native tests for stop/migrate/package transactions; re-probe PDG during implementation after the MCP index is refreshed."
      },
      {
        "description": "Source-verified stop ordering is stop request -> graceful wait -> signal -> hard kill, with sentinel cleanup in finally.",
        "affected_statements": [
          "deploy/process.py:250-312"
        ],
        "implementation_consequence": "Do not move cleanup or hard-kill before the graceful window; native tests must assert ordering."
      },
      {
        "description": "Source-verified model import ordering is verified copy -> registry active/history write -> Runtime manifest update.",
        "affected_statements": [
          "deploy/packages.py:272-326"
        ],
        "implementation_consequence": "Backend/model activation must remain unchanged on checksum, dependency or readiness failure."
      }
    ],
    "architectural_patterns": [
      {
        "pattern": "Single Python deploy domain command with JSON contract",
        "example_location": "deploy/__main__.py:401-516",
        "usage_guidance": "Keep CLI/GUI thin and preserve exit-code meanings."
      },
      {
        "pattern": "One source of truth for LLM endpoint parsing",
        "example_location": "core/llm/registry.py:190-251",
        "usage_guidance": "Doctor and Runtime adapters consume resolved facts, not reparse settings."
      },
      {
        "pattern": "Externalized user data with instance-scoped control files",
        "example_location": "config/home.py and config/instance.py",
        "usage_guidance": "Keep program/runtime packages replaceable without moving user data."
      },
      {
        "pattern": "Optional status endpoint with defensive degradation",
        "example_location": "stella_project/plugins/bot_main/status_api.py:145-212",
        "usage_guidance": "Status observability must never block Core startup."
      }
    ],
    "files_to_modify": [
      {
        "file": "runtime-manager/",
        "symbols": [
          "new RuntimeManager",
          "Supervisor",
          "Component",
          "Health",
          "Manifest"
        ],
        "intended_change": "Implement shared Runtime Contract and lifecycle supervision."
      },
      {
        "file": "deploy/process.py",
        "symbols": [
          "start_detached",
          "stop",
          "status"
        ],
        "intended_change": "Migrate to one ownership implementation while preserving legacy commands."
      },
      {
        "file": "core/llm/lm_studio.py",
        "symbols": [
          "LMStudioBackend"
        ],
        "intended_change": "Generalize/alias OpenAI-compatible backend for llama-server."
      },
      {
        "file": "core/llm/registry.py",
        "symbols": [
          "endpoints",
          "_build_backend",
          "describe"
        ],
        "intended_change": "Expose Runtime endpoint without changing role/fallback/gate semantics."
      },
      {
        "file": "stella-installer/src-tauri/src/python.rs",
        "symbols": [
          "run_deploy_inner",
          "data_root"
        ],
        "intended_change": "Route GUI control to Runtime with Python fallback and cache invalidation."
      },
      {
        "file": "cli/src/runner.rs",
        "symbols": [
          "Ctx"
        ],
        "intended_change": "Add local Runtime and Docker adapter commands."
      },
      {
        "file": "deploy/probe.py",
        "symbols": [
          "_probe_llm_registry",
          "_probe_onebot",
          "collect"
        ],
        "intended_change": "Collect Runtime/llama/OneBot facts."
      },
      {
        "file": "stella_project/plugins/bot_main/status_api.py",
        "symbols": [
          "setup_status_api"
        ],
        "intended_change": "Keep Core status stable and nest Runtime diagnostics."
      },
      {
        "file": "docker-compose.yml",
        "symbols": [
          "stella/llama/napcat services"
        ],
        "intended_change": "Map Docker services to the same contract."
      }
    ],
    "tests": [
      {
        "file": "tests/test_runtime_contract.py",
        "scenarios": [
          "unknown operation -> structured rejection",
          "secret in input/state -> redacted output",
          "manifest/state fixture -> stable schema"
        ]
      },
      {
        "file": "tests/test_runtime_adapter.py",
        "scenarios": [
          "Runtime unavailable -> Python fallback",
          "migration -> one owner and no duplicate PID writes",
          "fake component crash -> bounded backoff"
        ]
      },
      {
        "file": "tests/test_deploy_process.py",
        "scenarios": [
          "foreign ownership -> no signal",
          "sentinel before hard kill",
          "status API unavailable -> PID fallback"
        ]
      },
      {
        "file": "tests/test_llm_registry.py",
        "scenarios": [
          "llama LOCAL endpoint -> same cache/gate/fallback semantics",
          "describe -> no key value"
        ]
      },
      {
        "file": "tests/test_link_monitor.py",
        "scenarios": [
          "NapCat disconnect -> alert and wait, no Stella restart"
        ]
      },
      {
        "file": "runtime-manager/src/*_test.rs",
        "scenarios": [
          "single instance lock",
          "health timeout",
          "atomic state",
          "backoff cap"
        ]
      }
    ],
    "verification_commands": [
      "python -m pytest tests -q",
      "ruff check .",
      "cd cli && cargo fmt --all --check",
      "cd cli && cargo clippy --all-targets -- -D warnings",
      "cd cli && cargo test",
      "cd cli && cargo build --release",
      "cd stella-installer/src-tauri && cargo tauri build --no-bundle",
      "cd runtime-manager && cargo test"
    ],
    "risks": [
      "Windows native behavior cannot be inferred from Linux mocks.",
      "migrate.run caller graph is lower-bound because one receiver could not be typed.",
      "NapCat latest tag, login credentials, license and platform risk require explicit provenance gates.",
      "GPU build success without hardware is not runtime compatibility proof.",
      "A failed backend/model/NapCat upgrade must leave active state and STELLA_HOME unchanged."
    ],
    "assumptions": [
      "Windows CI runners can execute the helper process and inspect descendants; if not, a controlled self-hosted runner is required.",
      "NapCat distribution and license permit the pinned artifact; otherwise only external/manual integration is released.",
      "Unattended QR login is not a GA requirement and remains disabled until legal/security/product approval.",
      "The five backend enum in the current Runtime schema is the intended target matrix; any DirectML/oneAPI backend requires a separate schema decision.",
      "GPU model packages remain separate from backend binaries and are selected through checksum-verified catalog records."
    ],
    "open_questions": [
      "Which exact NapCat release/source and license text may be redistributed?",
      "Which Windows GPU runners and driver versions are available for CUDA/Vulkan runtime smoke?",
      "Should HIP/ROCm on Windows be build-only or explicitly unsupported in the first complete matrix?",
      "What is the final protected credential store contract for NapCat WebUI/session data?",
      "Which rollback pointer format should Tauri and CLI display to users?"
    ],
    "avoid": [
      "Do not treat empty or stale GitNexus callers as proof of safety.",
      "Do not bypass Docker for GitNexus refresh/status in this environment.",
      "Do not use latest tags in release manifests.",
      "Do not automate QR capture/confirmation or bypass platform risk controls.",
      "Do not publish an artifact without checksum, license/SBOM, dependency metadata and post-unpack verification.",
      "Do not delete STELLA_HOME or NapCat QQ data during package rollback.",
      "Do not claim GPU runtime support from build-only CI."
    ]
  }
}
```

## 12. Assumptions and Open Questions

### Assumptions

- [assumed] The checked-in Runtime schema backend enum (`cpu`, `cuda`, `hip`, `metal`, `vulkan`) is the target complete matrix; adding DirectML/oneAPI is a separate decision.
- [assumed] A Windows GitHub-hosted runner can run process-tree and file-lock tests; otherwise the project will provision a controlled self-hosted runner and keep the same test contract.
- [assumed] NapCat can be distributed only from a pinned, license-compatible source; until verified, the installer may support external/manual acquisition but must not publish a bundled artifact.
- [assumed] “Unattended QR” means unattended package installation and headless status monitoring; automatic QR capture/confirmation is not accepted for GA without explicit legal/security/product approval.
- [assumed] GPU runtime verification requires hardware runners; ordinary CI can prove build/link/package integrity but not real inference throughput or VRAM compatibility.

### Open questions

- Confirm the exact NapCat version, source URL, digest, license notice, SBOM format and redistribution permission.
- Confirm CUDA/Vulkan Windows driver baselines and whether HIP/ROCm Windows is supported, build-only, or excluded.
- Choose the protected credential/session storage contract and the user-visible rollback pointer format.
- Decide whether a failed optional GPU backend should be hidden, shown as `unavailable`, or shown as `degraded` when CPU fallback exists.
- Re-run Docker GitNexus `impact` and `detect-changes` after each implementation batch; refresh the host MCP index before relying on PDG edges.

### Explicitly deferred follow-ups

- Automatic QR capture, OCR, QR forwarding or account confirmation on behalf of a user.
- GPU performance tuning, multi-GPU scheduling, distributed inference and model marketplace behavior.
- NapCat source modifications or protocol patches outside the adapter boundary.
- Deleting or rewriting legacy user data beyond versioned program/package directories.

## 13. Definition of Done

1. Docker GitNexus status is up-to-date at the implementation commit; impacts for edited shared symbols and complete `detect-changes` have been reviewed.
2. Windows native tests pass for process tree ownership, graceful/forced stop, instance locks, locked files, stale locks and cleanup.
3. The upgrade matrix passes for fresh install, idle/running upgrade, locked files, checksum/signature failure, postflight failure, retry and rollback; user data hashes remain unchanged.
4. NapCat artifact provenance, license, SBOM, digest, install directory, QQ/config data roots and uninstall behavior are verified; `latest` is absent from release metadata.
5. NapCat login states are observable and redacted; manual QR login works; disconnect/reconnect does not stop or restart Stella; unattended login flag remains off unless separately approved.
6. Package catalog and Runtime schemas validate backend, platform, ABI, driver, dependency, license and checksum metadata while remaining compatible with existing catalog consumers.
7. CPU/CUDA/HIP/Metal/Vulkan assets are built for their supported OS/arch combinations, unpack cleanly, pass dependency and `/v1/models` checks, and clearly distinguish build-only from hardware-verified results.
8. Model/backend activation is transactional: checksum/readiness failure leaves the previous active pair intact, and rollback restores the previous version without touching `STELLA_HOME`.
9. Tauri, CLI, Python deploy and Docker consume the same status/package contract; existing command names, exit codes and `prepare=true/false` semantics remain compatible.
10. `python -m pytest tests -q`, Windows native tests, Rust checks, release layout checks, llama package verification and `docker compose config` pass.
11. Release upload is blocked on any native reliability, provenance/license, secret-safety, checksum, dependency, hardware compatibility or rollback red result.