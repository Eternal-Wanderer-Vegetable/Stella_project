# GitNexus Engineering Plan

> Task: 将 Stella Runtime 与一键部署架构按现有项目结构拆解为可执行的渐进式实施路线。
> Evidence verified at commit `20d12dfc2650b1f8cd3b34eb7012a74e8f8c972d`; GitNexus index stale (MCP reports 18 commits behind; resource snapshot reports 1 commit behind), refresh attempted and skipped because the local runner could not spawn `C:\windows\system32\cmd.exe`.
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
- [ ] 每个阶段都有可运行的 Python/Rust 测试与回归命令。

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

## 11. Reusable Implementation Context

The JSON below is the exact implementation context pack emitted by the provenance helper.


```json
{
  "implementation_context": {
    "task_summary": "按现有 deploy/LLM/Tauri/CLI/Docker 结构，渐进实现 Runtime Contract、Rust Supervisor、llama.cpp endpoint、OneBot adapter 和一键部署组件包。",
    "acceptance_criteria": [
      "Runtime state/manifest/operation schemas are shared by Rust, Python, Tauri, CLI and Docker.",
      "One process owner controls Stella lifecycle; legacy deploy commands remain compatible during migration.",
      "llama-server is optional and accessed through an OpenAI-compatible LOCAL endpoint.",
      "AI/llama failure does not prevent basic Bot operation.",
      "OneBot/NapCat MVP diagnoses and waits for reconnection without requiring automated QQ login.",
      "STELLA_HOME data survives migration, upgrade and component replacement."
    ],
    "evidence_provenance": {  "schema_version": 2,  "head_commit": "20d12dfc2650b1f8cd3b34eb7012a74e8f8c972d",  "generated_plan_path": "docs/plans/2026-09-11-gitnexus-plan-runtime-supervisor-rollout.md",  "global_dirty_digest": {    "algorithm": "sha256",    "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",    "value": "4f2127d942bc3c0dcd52ac1318daa80af5ae20bac347a9127e60e6dfb2439c58"  },  "cited_path_manifest": [    {      "path": ".github/CONTRIBUTING.md",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",      "index_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",      "worktree_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",      "untracked_digest": "absent"    },    {      "path": ".github/workflows/ci.yml",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:72ffa0a55d11fd17d17ca884615f5ae7976f2f0487d793f90720e61f5296fa5f",      "index_digest": "sha256:72ffa0a55d11fd17d17ca884615f5ae7976f2f0487d793f90720e61f5296fa5f",      "worktree_digest": "sha256:23cf14adfcf4c2ae1baeb9d4cb7ed173ac12c985f0bf5ddb217a02576039fb0f",      "untracked_digest": "absent"    },    {      "path": ".github/workflows/release.yml",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:58e09bd3826cbb39508b64f13e98e6e175f5e757e2cef92028d9de02c3036ee8",      "index_digest": "sha256:58e09bd3826cbb39508b64f13e98e6e175f5e757e2cef92028d9de02c3036ee8",      "worktree_digest": "sha256:58e09bd3826cbb39508b64f13e98e6e175f5e757e2cef92028d9de02c3036ee8",      "untracked_digest": "absent"    },    {      "path": "Dockerfile",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",      "index_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",      "worktree_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",      "untracked_digest": "absent"    },    {      "path": "cli/Cargo.toml",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:acf5fc221bc191d52801b9bfe0b268cdcb61d6ab433461de8678e6985b8e29c0",      "index_digest": "sha256:acf5fc221bc191d52801b9bfe0b268cdcb61d6ab433461de8678e6985b8e29c0",      "worktree_digest": "sha256:acf5fc221bc191d52801b9bfe0b268cdcb61d6ab433461de8678e6985b8e29c0",      "untracked_digest": "absent"    },    {      "path": "cli/src/main.rs",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:bdf162504d9ae77e24a0035e66c6477aae42c73522c149b9813484b0f4518304",      "index_digest": "sha256:bdf162504d9ae77e24a0035e66c6477aae42c73522c149b9813484b0f4518304",      "worktree_digest": "sha256:bdf162504d9ae77e24a0035e66c6477aae42c73522c149b9813484b0f4518304",      "untracked_digest": "absent"    },    {      "path": "cli/src/runner.rs",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:9096b01816c9a537e288a1d7f992ae70091861e17f2a5234e8ccaaafe0865cb6",      "index_digest": "sha256:9096b01816c9a537e288a1d7f992ae70091861e17f2a5234e8ccaaafe0865cb6",      "worktree_digest": "sha256:9096b01816c9a537e288a1d7f992ae70091861e17f2a5234e8ccaaafe0865cb6",      "untracked_digest": "absent"    },    {      "path": "cli/src/status.rs",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:32257befa27d2eb7be51a6abb4804601800fec8c503099df1731261ff00bc052",      "index_digest": "sha256:32257befa27d2eb7be51a6abb4804601800fec8c503099df1731261ff00bc052",      "worktree_digest": "sha256:32257befa27d2eb7be51a6abb4804601800fec8c503099df1731261ff00bc052",      "untracked_digest": "absent"    },    {      "path": "config/home.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:2a97b49aeeee31e26831b2585160cb80bcc7f82dda08856ee71cd85aad0d7484",      "index_digest": "sha256:2a97b49aeeee31e26831b2585160cb80bcc7f82dda08856ee71cd85aad0d7484",      "worktree_digest": "sha256:2a97b49aeeee31e26831b2585160cb80bcc7f82dda08856ee71cd85aad0d7484",      "untracked_digest": "absent"    },    {      "path": "config/instance.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:c6a71dd5591b5b2e924b98aca18b2806d6c8198104accb291ac4b21b1c13280e",      "index_digest": "sha256:c6a71dd5591b5b2e924b98aca18b2806d6c8198104accb291ac4b21b1c13280e",      "worktree_digest": "sha256:c6a71dd5591b5b2e924b98aca18b2806d6c8198104accb291ac4b21b1c13280e",      "untracked_digest": "absent"    },    {      "path": "config/settings.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:3ac5090048e85ee44fb6916b19b76e4f6f9ce2c2b8674fb8bdb8734e8debe39b",      "index_digest": "sha256:3ac5090048e85ee44fb6916b19b76e4f6f9ce2c2b8674fb8bdb8734e8debe39b",      "worktree_digest": "sha256:43a35f1cc6c502d81af15511970f9f1b84cb101464d91cfa4a98e6c0b957e992",      "untracked_digest": "absent"    },    {      "path": "core/llm/base.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:c99f95ddf62b440027360792c3c2a6d4c7506f1acfc38198be7396ae36b6a2a8",      "index_digest": "sha256:c99f95ddf62b440027360792c3c2a6d4c7506f1acfc38198be7396ae36b6a2a8",      "worktree_digest": "sha256:c99f95ddf62b440027360792c3c2a6d4c7506f1acfc38198be7396ae36b6a2a8",      "untracked_digest": "absent"    },    {      "path": "core/llm/lm_studio.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:6d2de9fc957c203aedb1e5bf42be9316ad37f31e8d672ac3a14a809ae8c7da11",      "index_digest": "sha256:6d2de9fc957c203aedb1e5bf42be9316ad37f31e8d672ac3a14a809ae8c7da11",      "worktree_digest": "sha256:6d2de9fc957c203aedb1e5bf42be9316ad37f31e8d672ac3a14a809ae8c7da11",      "untracked_digest": "absent"    },    {      "path": "core/llm/registry.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:2f4d2fa09f4540230478eece9548ce385a1658bc7b6e786b8fa54cb74424f379",      "index_digest": "sha256:2f4d2fa09f4540230478eece9548ce385a1658bc7b6e786b8fa54cb74424f379",      "worktree_digest": "sha256:d921a5d949179365b6554b7477609b7ce725cace51277b0ea5f5960ba025c512",      "untracked_digest": "absent"    },    {      "path": "core/llm/scheduler.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:1867025f4767030a779914106ec075106a3860baa67b247787aad90426d412a2",      "index_digest": "sha256:1867025f4767030a779914106ec075106a3860baa67b247787aad90426d412a2",      "worktree_digest": "sha256:1867025f4767030a779914106ec075106a3860baa67b247787aad90426d412a2",      "untracked_digest": "absent"    },    {      "path": "deploy/__main__.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:f8c50ff2ff953259d30c41566b9910fbf98d2194323ba59a2a291fc306d1e01b",      "index_digest": "sha256:f8c50ff2ff953259d30c41566b9910fbf98d2194323ba59a2a291fc306d1e01b",      "worktree_digest": "sha256:0d26e4144b91068f20d8e299cb187eabc0191f056966bd36c734926dde0c6f7d",      "untracked_digest": "absent"    },    {      "path": "deploy/checks.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:1b72c8ab1059ca439ed44291983c3825b1d9ad772214d9b480fa977512e09117",      "index_digest": "sha256:1b72c8ab1059ca439ed44291983c3825b1d9ad772214d9b480fa977512e09117",      "worktree_digest": "sha256:1b72c8ab1059ca439ed44291983c3825b1d9ad772214d9b480fa977512e09117",      "untracked_digest": "absent"    },    {      "path": "deploy/probe.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:c820c09953d767ea13a2b82bf1d5576fae5911f1fc537b78c1545b0b93503e87",      "index_digest": "sha256:c820c09953d767ea13a2b82bf1d5576fae5911f1fc537b78c1545b0b93503e87",      "worktree_digest": "sha256:c820c09953d767ea13a2b82bf1d5576fae5911f1fc537b78c1545b0b93503e87",      "untracked_digest": "absent"    },    {      "path": "deploy/process.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:759d33fee8dccf7feb435b87c8196519a95d8cbb10242d64d73b2e561b6125db",      "index_digest": "sha256:759d33fee8dccf7feb435b87c8196519a95d8cbb10242d64d73b2e561b6125db",      "worktree_digest": "sha256:454b7d666848f1f4ab3ff1726625531136d52846d7e03f6eb49382594d726b3c",      "untracked_digest": "absent"    },    {      "path": "design_docs/Stella Runtime & One-Click Deployment Architecture.md",      "object_kind": {        "head": "absent",        "index": "absent",        "worktree": "absent",        "untracked": "regular"      },      "state": "untracked",      "rename_from": null,      "rename_to": null,      "head_digest": "absent",      "index_digest": "absent",      "worktree_digest": "absent",      "untracked_digest": "sha256:d019d301f49878f81d6bf28583ba16ff2ee25436f957e82ff4ee1b27f403dde4"    },    {      "path": "design_docs/Stella Runtime 落地实施方案 v1.0.md",      "object_kind": {        "head": "absent",        "index": "absent",        "worktree": "absent",        "untracked": "regular"      },      "state": "untracked",      "rename_from": null,      "rename_to": null,      "head_digest": "absent",      "index_digest": "absent",      "worktree_digest": "absent",      "untracked_digest": "sha256:2313bf038e0887ea1811c1ba3c58e8a8a4a87b533ff4ad1c0034cb202b2da4b3"    },    {      "path": "docker-compose.yml",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:c3a54e3d74584e6bfeeee039c005e5073981227f5d563ed8479d89b6c88d3db3",      "index_digest": "sha256:c3a54e3d74584e6bfeeee039c005e5073981227f5d563ed8479d89b6c88d3db3",      "worktree_digest": "sha256:c3a54e3d74584e6bfeeee039c005e5073981227f5d563ed8479d89b6c88d3db3",      "untracked_digest": "absent"    },    {      "path": "extensions/link_monitor/__init__.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:7ac2d5798de437d48e9d7dde3de43593aa24d6c70e35315a7a877aa3fff722a4",      "index_digest": "sha256:7ac2d5798de437d48e9d7dde3de43593aa24d6c70e35315a7a877aa3fff722a4",      "worktree_digest": "sha256:7ac2d5798de437d48e9d7dde3de43593aa24d6c70e35315a7a877aa3fff722a4",      "untracked_digest": "absent"    },    {      "path": "pyproject.toml",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:399bfc85b63f1621d86a0df46b3df8c7589d8a3f64fc3ace604dc55dd6177c0d",      "index_digest": "sha256:399bfc85b63f1621d86a0df46b3df8c7589d8a3f64fc3ace604dc55dd6177c0d",      "worktree_digest": "sha256:dcbb0953a16b144dbec857608c774ca949e1e73373c69ba6449adfa702338a3a",      "untracked_digest": "absent"    },    {      "path": "stella-installer/src-tauri/Cargo.toml",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:6d13dcad6e1d7f99dbfa8fa52523fd26ac96272a59702883d36ac193075665f1",      "index_digest": "sha256:6d13dcad6e1d7f99dbfa8fa52523fd26ac96272a59702883d36ac193075665f1",      "worktree_digest": "sha256:6d13dcad6e1d7f99dbfa8fa52523fd26ac96272a59702883d36ac193075665f1",      "untracked_digest": "absent"    },    {      "path": "stella-installer/src-tauri/src/commands.rs",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:e2610bf7f9bdb768ed6d7b85d026a8aa22ab07582cc5f1f7c65824adda71f580",      "index_digest": "sha256:e2610bf7f9bdb768ed6d7b85d026a8aa22ab07582cc5f1f7c65824adda71f580",      "worktree_digest": "sha256:8d86dfe58f89a05b4b62624f295fb469327221782e3d216b01c693ea28c27d3e",      "untracked_digest": "absent"    },    {      "path": "stella-installer/src-tauri/src/python.rs",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:bf1015b51b9f0fcdade99bceac994f1fa46bf08808f929b257e42f410980b63b",      "index_digest": "sha256:bf1015b51b9f0fcdade99bceac994f1fa46bf08808f929b257e42f410980b63b",      "worktree_digest": "sha256:bf1015b51b9f0fcdade99bceac994f1fa46bf08808f929b257e42f410980b63b",      "untracked_digest": "absent"    },    {      "path": "stella-installer/src/api.js",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:f7b78c97636025c4569790ec2f0cdba201703fd2ff9c312f602fc5049c9cbd71",      "index_digest": "sha256:f7b78c97636025c4569790ec2f0cdba201703fd2ff9c312f602fc5049c9cbd71",      "worktree_digest": "sha256:f7b78c97636025c4569790ec2f0cdba201703fd2ff9c312f602fc5049c9cbd71",      "untracked_digest": "absent"    },    {      "path": "stella_project/plugins/bot_main/status_api.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:c59b32daf9adba0a09e37f8280479d7c42216ad81e50ad0aa5e97e9eee71e8ff",      "index_digest": "sha256:c59b32daf9adba0a09e37f8280479d7c42216ad81e50ad0aa5e97e9eee71e8ff",      "worktree_digest": "sha256:c59b32daf9adba0a09e37f8280479d7c42216ad81e50ad0aa5e97e9eee71e8ff",      "untracked_digest": "absent"    },    {      "path": "tests/test_deploy_checks.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:51892d2489fa45156142e09de5feb333bad91e8f67edeb063dfe5fbaa433d0fa",      "index_digest": "sha256:51892d2489fa45156142e09de5feb333bad91e8f67edeb063dfe5fbaa433d0fa",      "worktree_digest": "sha256:51892d2489fa45156142e09de5feb333bad91e8f67edeb063dfe5fbaa433d0fa",      "untracked_digest": "absent"    },    {      "path": "tests/test_deploy_cli.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:b3a67b10347246dea7b86d30858ee12ca0c7be701175ed1e9ce96f95adb01e5b",      "index_digest": "sha256:b3a67b10347246dea7b86d30858ee12ca0c7be701175ed1e9ce96f95adb01e5b",      "worktree_digest": "sha256:b3a67b10347246dea7b86d30858ee12ca0c7be701175ed1e9ce96f95adb01e5b",      "untracked_digest": "absent"    },    {      "path": "tests/test_deploy_migrate.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:d82b81d15923b2b69d77cf9c7e4da8842f3b5d458dd28f31a6098cf48a4f862d",      "index_digest": "sha256:d82b81d15923b2b69d77cf9c7e4da8842f3b5d458dd28f31a6098cf48a4f862d",      "worktree_digest": "sha256:d82b81d15923b2b69d77cf9c7e4da8842f3b5d458dd28f31a6098cf48a4f862d",      "untracked_digest": "absent"    },    {      "path": "tests/test_deploy_probe.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:670ec8e25c8a2065a5ab50a78446cc2be6fca76bc60b903b23ebad9cc0d1651a",      "index_digest": "sha256:670ec8e25c8a2065a5ab50a78446cc2be6fca76bc60b903b23ebad9cc0d1651a",      "worktree_digest": "sha256:9f7e2bdd550b00787d2125db1ff42f63525607efef298b4d1bcae06442a1c73a",      "untracked_digest": "absent"    },    {      "path": "tests/test_deploy_process.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:033ac72b315c5cfd4f0c673fd8af1897af997da598a3f214648257423cc5be1e",      "index_digest": "sha256:033ac72b315c5cfd4f0c673fd8af1897af997da598a3f214648257423cc5be1e",      "worktree_digest": "sha256:f4c94c4c681931a4c0e90098d7f3a19cf572bd0ce640703511138f6890915247",      "untracked_digest": "absent"    },    {      "path": "tests/test_link_monitor.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:c2cbd118b37d4812bb76200f2482411184038aa177728188b82742e56c145fd0",      "index_digest": "sha256:c2cbd118b37d4812bb76200f2482411184038aa177728188b82742e56c145fd0",      "worktree_digest": "sha256:c2cbd118b37d4812bb76200f2482411184038aa177728188b82742e56c145fd0",      "untracked_digest": "absent"    },    {      "path": "tests/test_llm_registry.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:7d9a0fabc56f66620e4bbf4dc713c8a651a8ab754b3bc8f1450baf6a057e8def",      "index_digest": "sha256:7d9a0fabc56f66620e4bbf4dc713c8a651a8ab754b3bc8f1450baf6a057e8def",      "worktree_digest": "sha256:7d9a0fabc56f66620e4bbf4dc713c8a651a8ab754b3bc8f1450baf6a057e8def",      "untracked_digest": "absent"    },    {      "path": "tests/test_scheduler_concurrency.py",      "object_kind": {        "head": "regular",        "index": "regular",        "worktree": "regular",        "untracked": "absent"      },      "state": "clean",      "rename_from": null,      "rename_to": null,      "head_digest": "sha256:6b69eecff94c40ddbc1a4bf2ee680ec08ce1a98544c1fb4c30297b69f199add0",      "index_digest": "sha256:6b69eecff94c40ddbc1a4bf2ee680ec08ce1a98544c1fb4c30297b69f199add0",      "worktree_digest": "sha256:6b69eecff94c40ddbc1a4bf2ee680ec08ce1a98544c1fb4c30297b69f199add0",      "untracked_digest": "absent"    }  ]},
    "primary_symbols": [
      {"symbol":"endpoints","file":"core/llm/registry.py","lines":"245-251","role":"shared endpoint resolver and cache"},
      {"symbol":"run_deploy_inner","file":"stella-installer/src-tauri/src/python.rs","lines":"825-860","role":"Tauri-to-Python control bridge"},
      {"symbol":"start_detached","file":"deploy/process.py","lines":"167-212","role":"current Stella process owner"},
      {"symbol":"setup_status_api","file":"stella_project/plugins/bot_main/status_api.py","lines":"145-212","role":"Core local status endpoint"},
      {"symbol":"LMStudioBackend","file":"core/llm/lm_studio.py","lines":"33-230","role":"existing OpenAI-compatible backend"}
    ],
    "related_symbols": [
      {"symbol":"process.stop/status","relationship":"calls/compatibility","relevance":"ownership, graceful shutdown and status fallback"},
      {"symbol":"_cmd_start/_cmd_status","relationship":"calls","relevance":"deploy CLI surface"},
      {"symbol":"_probe_llm_registry/collect","relationship":"calls","relevance":"doctor evidence collection"},
      {"symbol":"check_llm_config_issues/check_llm_endpoint_reachable","relationship":"calls","relevance":"doctor severity policy"},
      {"symbol":"run_deploy/run_deploy_without_prepare","relationship":"CALLS","relevance":"direct Tauri bridge dependents"},
      {"symbol":"link_monitor_task/link_status","relationship":"calls","relevance":"OneBot health and reconnect semantics"},
      {"symbol":"Ctx::deploy_cmd/compose_deploy_cmd","relationship":"calls","relevance":"CLI local/Docker adapter"}
    ],
    "execution_path": [
      "Tauri or stellacli receives an explicit operation.",
      "The control plane resolves local or Docker mode and the Runtime instance directory.",
      "Runtime validates component/operation and reads manifest.",
      "Supervisor starts or stops Stella, optionally starts llama, and records state/logs.",
      "Stella Core exposes /stella/status and uses the Runtime-provided OpenAI-compatible endpoint.",
      "OneBot/NapCat health is reported as nested component diagnostics and reconnection remains non-fatal."
    ],
    "pdg_constraints": [
      "No PDG layer was available; re-run analyze --pdg before relying on statement-level controls/data flow.",
      "Source-verified ordering: endpoint parse -> key-sharing validation -> cache; stop request -> graceful wait -> signal -> hard kill; migrate/init -> invalidate data_root cache."
    ],
    "architectural_patterns": [
      {"pattern":"Single Python deploy domain command with JSON contract","example_location":"deploy/__main__.py:401-516","usage_guidance":"Keep CLI/GUI thin and preserve exit-code meanings."},
      {"pattern":"One source of truth for LLM endpoint parsing","example_location":"core/llm/registry.py:190-251","usage_guidance":"Doctor and Runtime adapters consume resolved facts, not reparse settings."},
      {"pattern":"Externalized user data with instance-scoped control files","example_location":"config/home.py and config/instance.py","usage_guidance":"Keep program/runtime packages replaceable without moving user data."},
      {"pattern":"Optional status endpoint with defensive degradation","example_location":"stella_project/plugins/bot_main/status_api.py:145-212","usage_guidance":"Status observability must never block Core startup."}
    ],
    "files_to_modify": [
      {"file":"runtime-manager/","symbols":["new RuntimeManager","Supervisor","Component","Health","Manifest"],"intended_change":"Implement shared Runtime Contract and lifecycle supervision."},
      {"file":"deploy/process.py","symbols":["start_detached","stop","status"],"intended_change":"Migrate to one ownership implementation while preserving legacy commands."},
      {"file":"core/llm/lm_studio.py","symbols":["LMStudioBackend"],"intended_change":"Generalize/alias OpenAI-compatible backend for llama-server."},
      {"file":"core/llm/registry.py","symbols":["endpoints","_build_backend","describe"],"intended_change":"Expose Runtime endpoint without changing role/fallback/gate semantics."},
      {"file":"stella-installer/src-tauri/src/python.rs","symbols":["run_deploy_inner","data_root"],"intended_change":"Route GUI control to Runtime with Python fallback and cache invalidation."},
      {"file":"cli/src/runner.rs","symbols":["Ctx"],"intended_change":"Add local Runtime and Docker adapter commands."},
      {"file":"deploy/probe.py","symbols":["_probe_llm_registry","_probe_onebot","collect"],"intended_change":"Collect Runtime/llama/OneBot facts."},
      {"file":"stella_project/plugins/bot_main/status_api.py","symbols":["setup_status_api"],"intended_change":"Keep Core status stable and nest Runtime diagnostics."},
      {"file":"docker-compose.yml","symbols":["stella/llama/napcat services"],"intended_change":"Map Docker services to the same contract."}
    ],
    "tests": [
      {"file":"tests/test_runtime_contract.py","scenarios":["unknown operation -> structured rejection","secret in input/state -> redacted output","manifest/state fixture -> stable schema"]},
      {"file":"tests/test_runtime_adapter.py","scenarios":["Runtime unavailable -> Python fallback","migration -> one owner and no duplicate PID writes","fake component crash -> bounded backoff"]},
      {"file":"tests/test_deploy_process.py","scenarios":["foreign ownership -> no signal","sentinel before hard kill","status API unavailable -> PID fallback"]},
      {"file":"tests/test_llm_registry.py","scenarios":["llama LOCAL endpoint -> same cache/gate/fallback semantics","describe -> no key value"]},
      {"file":"tests/test_link_monitor.py","scenarios":["NapCat disconnect -> alert and wait, no Stella restart"]},
      {"file":"runtime-manager/src/*_test.rs","scenarios":["single instance lock","health timeout","atomic state","backoff cap"]}
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
      "CRITICAL endpoint registry blast radius; rerun impact and all dependent tests before editing.",
      "CRITICAL Tauri bridge blast radius; preserve prepare/no-prepare, exit codes and JSON extraction.",
      "Windows process trees, file locks, CTRL_BREAK/taskkill and self-update require native integration tests.",
      "NapCat distribution/login/license/anti-risk constraints remain unresolved for automatic management.",
      "Index is stale and PDG is absent; graph findings are navigation evidence, source is authoritative."
    ],
    "assumptions": [
      "Runtime can reuse config.instance instance IDs and STELLA_HOME without changing legacy path resolution; verify with current tests before Step 1.",
      "A local named pipe or localhost socket is acceptable for Desktop IPC; decide in Step 0.",
      "A CPU or one selected GPU llama backend is sufficient for MVP; confirm target hardware before packaging."
    ],
    "open_questions": [
      "Which Runtime IPC transport should be the Desktop default: named pipe or localhost socket?",
      "Will llama-server support embeddings in the first package, or will embedding remain an external/local endpoint?",
      "Which NapCat build/license is distributable, and is automatic acquisition permitted?",
      "Should Docker run a Runtime process in one container or model each component as a service?"
    ],
    "avoid": [
      "Do not edit shared symbols before rerunning impact on the current index.",
      "Do not treat UNKNOWN, empty callers, partial or truncated graph output as safe.",
      "Do not maintain Rust and Python as long-term co-owners of PID/manifest/sentinel.",
      "Do not parse LLM configuration a second time in doctor or GUI.",
      "Do not expose arbitrary shell commands through GUI or Runtime API.",
      "Do not make llama.cpp, NapCat or model files hard dependencies of Stella Core.",
      "Do not overwrite STELLA_HOME data during runtime/package upgrades."
    ]
  }
}
```

## 12. Assumptions and Open Questions

### Assumptions

- [assumed] `config.instance` can host Runtime state without changing legacy `STELLA_HOME` resolution; verify with migration tests.
- [assumed] One local IPC transport can serve CLI/Tauri; choose named pipe vs localhost socket in Step 0.
- [assumed] CPU or one selected GPU llama.cpp backend is enough for MVP; broad CUDA/HIP/Vulkan packaging is deferred.
- [assumed] NapCat can remain external in MVP; automatic distribution needs a legal/product decision.
- [assumed] Current provenance reports byte differences for some porcelain-clean paths; rerun provenance after source edits.

### Open questions

- Choose Desktop IPC and document authentication/ACL behavior.
- Decide whether Runtime owns only `runtime-manifest.json` or also the legacy `ownership.json`.
- Decide whether llama-server is long-lived, on-demand, or split into chat/embedding resources.
- Decide authoritative GGUF metadata format for architecture, quantization, context and VRAM estimates.
- Decide distributable NapCat artifacts and GUI representation of manual QR login.
- Decide single supervisor container versus compose services plus adapter.
- Re-run current GitNexus index and `--pdg` before implementation.

### Explicitly deferred follow-ups

- Automatic NapCat installation/login and unattended account management.
- Full hardware detector and all GPU backend combinations.
- Model marketplace, cloud sync, distributed inference and multi-QQ clustering.
- Backup/restore UX beyond preserving existing migration/data boundaries.

## 13. Definition of Done

1. A current GitNexus index exists; impact has been rerun on every edited shared symbol and HIGH/CRITICAL warnings resolved.
2. Runtime schemas validate fixtures and are consumed by Rust, Python, Tauri, CLI and Docker adapters.
3. One Runtime Supervisor owns Stella lifecycle; legacy deploy commands remain compatible without a second owner.
4. Status distinguishes installed/disabled/starting/running/healthy/degraded/failed/stopped, persists redacted state, and exposes component logs.
5. Stella can use Runtime-managed llama-server through the existing LLM abstraction; AI OFF or llama failure leaves basic Bot functionality available.
6. Endpoint registry, fallback, scheduler gates, doctor, status API and API-key secrecy tests pass.
7. OneBot/NapCat adapter reports configuration, reachability and disconnect state, waits for reconnection, and does not require automated QQ login.
8. Tauri and `stellacli` use Runtime operations with existing public command names and JSON/exit-code semantics; migration invalidates cached `STELLA_HOME`.
9. Windows integration tests cover process groups, stop sentinel ordering, file locks, port conflicts and update rollback; Linux CI covers unit/build checks.
10. Component/model packages have independent version/checksum records; upgrades do not overwrite user data; Docker/Desktop status share the contract.
11. Final verification passes Python, Ruff, CLI Rust, Runtime crate, Tauri and applicable Docker smoke tests.
12. `detect_changes({scope:"all"})` is complete (`partial=false`, `truncated=false`) and affected processes have been reviewed before commit.