# Stella Runtime 落地实施方案

> **关联架构文档：** `design_docs/Stella Runtime & One-Click Deployment Architecture.md`
>
> **文档类型：** Engineering Implementation Proposal
>
> **状态：** Proposed
>
> **版本：** 1.0
>
> **日期：** 2026-09-11

## 1. 结论

Stella Runtime 架构可以在现有项目上渐进落地，不需要重写 Stella Core，也不需要
立即制作包含所有组件的超级单文件 EXE。

推荐顺序：

```text
Runtime Contract
    ↓
Rust Runtime Supervisor
    ↓
llama.cpp / llama-server
    ↓
CLI 与 Tauri 统一接入
    ↓
模型包与安装器
    ↓
NapCat 可选管理
    ↓
Docker / Server Runtime
```

核心边界：

- Python `deploy` 继续负责 doctor、迁移、配置 schema、插件检查等领域工具。
- Rust Runtime 负责 Stella、llama-server 以及未来可选 NapCat 的生命周期。
- Stella Core 只通过现有 LLM/OneBot 抽象访问外部能力，不直接管理第三方进程。
- Tauri 和 `stellacli` 只做控制面和渲染，不复制领域逻辑。

## 2. 现有基础

项目已有以下可复用能力：

| 现有模块 | 可复用能力 |
| --- | --- |
| `deploy/process.py` | PID、ownership manifest、停止哨兵、优雅停止、硬杀兜底 |
| `deploy/probe.py` / `deploy/checks.py` | 环境、端口、OneBot、LLM、数据库和版本诊断 |
| `config/home.py` | `STELLA_HOME`、指针文件、旧布局和便携布局兼容 |
| `config/instance.py` | 实例 ID、实例运行目录、PID 和 manifest 路径 |
| `core/llm/base.py` | `LLMBackend` 抽象 |
| `core/llm/registry.py` | Endpoint × Role、fallback、并发闸门、运行时描述 |
| `core/llm/lm_studio.py` | 已可调用通用 OpenAI-compatible `/v1/chat/completions` |
| `status_api.py` | `/stella/status` 进程内状态接口 |
| `cli/` | 本地和 Docker 双形态命令编排 |
| `stella-installer/` | Tauri GUI 与嵌入式 Python 启动流程 |
| `docker-compose.yml` | Stella + NapCat 双容器部署基础 |

## 3. 目标架构

```text
Tauri GUI             stellacli
     \                   /
      \                 /
       Runtime API / IPC
               |
       Rust Runtime Manager
       |        |        |
       |        |        +-- NapCat / OneBot adapter
       |        +----------- llama-server
       +--------------------- Stella Core
               |
           STELLA_HOME
      config / data / logs
      manifest / state / locks
```

建议新增独立 Rust 工程 `runtime-manager/`，不要把 Supervisor 继续堆进
`cli/` 或 Tauri crate。CLI、GUI、未来 Docker Runtime 都实现同一份操作和状态契约。

## 4. Runtime Contract

第一版定义组件：

```text
stella
llama
onebot
```

每个组件有以下状态：

```text
disabled
stopped
starting
running
healthy
degraded
failed
```

最小控制操作：

```text
start(component)
stop(component)
restart(component)
status()
logs(component, tail, follow)
doctor()
```

状态对象至少包含：

```json
{
  "component": "llama",
  "desired": "running",
  "actual": "healthy",
  "pid": 1234,
  "endpoint": "http://127.0.0.1:8081/v1",
  "version": "unknown",
  "started_at": "2026-09-11T10:00:00Z",
  "restart_count": 0,
  "last_error": null
}
```

`STELLA_HOME/.stella/instances/<instance-id>/` 作为实例级控制目录，继续复用
现有 `config.instance.runtime_dir()`，新增：

```text
runtime-manifest.json
runtime-state.json
locks/
```

组件日志落在 `STELLA_HOME/logs/`，至少区分：

```text
runtime.log
stella.jsonl
llama.log
napcat.log
```

## 5. 分阶段落地

### Phase 0：契约和测试基线

1. 新增 Runtime manifest、state、operation 的 JSON schema。
2. 固定组件依赖：`stella` 可独立运行，`llama` 是可选依赖，`onebot` 是链路能力。
3. 固定错误码、状态枚举、日志字段和脱敏规则。
4. 先补齐现有 `deploy/process.py`、`registry.py`、Tauri bridge 的回归测试。

验收：契约文件可被 Rust、Python、TypeScript 读取；API key 不出现在状态和日志中。

### Phase 1：Rust Supervisor 管理 Stella

1. 创建 `runtime-manager/` Rust crate。
2. 实现单实例锁、组件配置、子进程启动、stdout/stderr 重定向和状态落盘。
3. 迁移 Windows 下的进程树处理、优雅停止、超时和硬杀策略。
4. 迁移期间先调用 `python -m deploy start/stop/status`，保证只有一方最终拥有
   Stella 进程控制权。
5. 稳定后再将 `deploy/process.py` 降为兼容层，避免 Rust/Python 双重写 PID、
   manifest 或停止哨兵。

验收：Supervisor 能启停 Stella、识别非自身实例、崩溃后按退避策略重启，并输出
统一 JSON 状态。

### Phase 2：llama-server

1. 将 llama.cpp 作为独立 runtime package，不写入 Stella Core。
2. 实现模型路径、端口、上下文长度、CPU/单一 GPU backend 的配置。
3. 以 `/v1/models` 和一次最小 chat 请求作为健康检查。
4. 失败时只将 LLM 标记为 `failed/degraded`，不阻断基础 Bot。
5. 第一版只支持 CPU 或一个明确的 GPU backend；其他 backend 延后。

验收：无 LM Studio 时可以由 Runtime 启动 `llama-server`，Stella 通过
`http://127.0.0.1:<port>/v1` 调用。

### Phase 3：LLM Provider 接入

1. 优先复用现有 `LMStudioBackend` 的 OpenAI-compatible 请求实现，必要时改名为
   `OpenAICompatibleBackend`，保留兼容导出和旧调用行为。
2. `core/llm/registry.py` 继续作为唯一的 Endpoint × Role 解析入口。
3. Runtime 只提供 endpoint、model、kind 和健康状态，不让 Core 拼接
   `llama-server.exe` 参数。
4. 保留现有 fallback、并发闸门、模型继承和 400 不降级规则。
5. 增加 Runtime endpoint 与 `deploy doctor` 的联动检查。

验收：LOCAL endpoint 可指向 llama-server；llama 不可用时 AI 能力优雅退化，
Memory、规则命令和基础插件仍可运行。

### Phase 4：OneBot/NapCat adapter

MVP 不强制自动下载、安装和登录 NapCat。QQ 登录需要人工扫码，且第三方分发、
许可证和风控风险应独立评估。

第一版只实现：

- OneBot endpoint 可达性检查；
- 反向 WS 配置生成或校验；
- NapCat 未启动、未登录、断线的可操作提示；
- 自动重连等待和状态告警；
- 将 OneBot 状态汇总到 Runtime 状态。

后续再增加可选 `NapCatManager`，并为 NapCat 保留独立版本、目录、日志、更新和
回滚边界，不修改第三方源码。

### Phase 5：Tauri 和 CLI

1. Tauri 命令改为调用 Runtime API，保留现有 `run_doctor`、`get_status`、
   `start_bot`、`stop_bot`、`run_migrate` 的前端兼容行为。
2. 迁移 `data_root` 缓存时继续遵守“迁移/初始化后失效”的不变量。
3. `stellacli` 增加 Runtime 子命令或将现有 `start/stop/restart/status/logs`
   映射到 Runtime。
4. 本地模式连接本机 Runtime；Docker 模式连接容器内 Runtime 或 compose adapter。

验收：GUI 和 CLI 不再各自解析 PID、日志或第三方进程，只消费统一 JSON。

### Phase 6：安装包和模型管理

采用 bootstrap installer + component packages + model packages：

```text
bootstrap-installer
  ├── Stella application
  ├── embedded Python
  ├── Rust Runtime
  ├── llama.cpp package
  ├── optional NapCat package
  └── model packages
```

每个组件和模型都要有版本、平台、backend、SHA-256、下载记录和回滚信息。
模型不随主安装器强制携带，GGUF 导入必须先做完整性和基础兼容性检查。

### Phase 7：Docker

Docker 复用 Runtime Contract，不复制桌面版的业务逻辑：

- `docker-compose.yml` 负责容器、网络、卷和依赖；
- `stella`、`llama`、`napcat` 可拆分服务；
- `STELLA_HOME=/data` 继续作为用户数据边界；
- Docker status 与桌面 status 使用同一字段语义。

## 6. 文件落地映射

### 新增文件

```text
runtime-manager/Cargo.toml
runtime-manager/src/main.rs
runtime-manager/src/api.rs
runtime-manager/src/supervisor.rs
runtime-manager/src/component.rs
runtime-manager/src/health.rs
runtime-manager/src/manifest.rs
runtime-manager/src/logging.rs
runtime-manager/src/backoff.rs
runtime-manager/schemas/runtime-manifest.schema.json
runtime-manager/schemas/runtime-state.schema.json
```

### 首批需要协同修改的现有文件

```text
deploy/process.py
deploy/probe.py
deploy/checks.py
deploy/__main__.py
config/instance.py
core/llm/lm_studio.py
core/llm/registry.py
config/settings.py
stella_project/plugins/bot_main/status_api.py
stella-installer/src-tauri/src/python.rs
stella-installer/src-tauri/src/commands.rs
cli/src/runner.rs
cli/src/main.rs
cli/src/status.rs
docker-compose.yml
Dockerfile
```

修改顺序应遵守：

1. 先加契约和测试；
2. 再加 Runtime adapter；
3. 再迁移控制面；
4. 最后调整默认配置、发布包和 Docker。

## 7. 测试和验收

必须覆盖：

- 启动已运行的自身实例时拒绝重复启动；
- PID 存在但 ownership 不匹配时拒绝停止；
- 停止先发停止请求，等待超时后才降级信号和硬杀；
- 状态接口不可达时仍返回可用的降级状态；
- doctor 失败不泄露 API key；
- LOCAL/ONLINE endpoint 的模型、超时、并发和 fallback 语义不变；
- llama-server 不可用时 Bot 基础功能仍可启动；
- OneBot 断线只告警并等待重连；
- migrate/init 后 GUI 重新解析 `STELLA_HOME`；
- Runtime 崩溃重启受最大次数和退避上限约束；
- GUI、CLI、Docker 使用同一份状态字段。

开发期基线命令：

```bash
python -m pytest tests -q
ruff check .
cd cli && cargo fmt --all --check
cd cli && cargo clippy --all-targets -- -D warnings
cd cli && cargo test
```

## 8. 主要风险

1. `core/llm/registry.py` 是高连接度共享点，任何 endpoint 语义变化都必须运行
   LLM、Memory、doctor 和调度测试。
2. Tauri `run_deploy_inner` 是所有 GUI Python 操作的公共入口，迁移时必须保持
   stdout/stderr/退出码和 JSON 提取兼容。
3. Rust 与 Python 不得长期双重管理 Stella 进程。
4. Windows 的进程树、文件锁、后台窗口和自更新需要真实 Windows 集成测试。
5. GPU backend 和模型包矩阵复杂，第一版必须限制范围。
6. NapCat 的人工登录、第三方许可证和账号风控不能被“全自动安装”承诺掩盖。
7. Runtime state、`/stella/status`、CLI status 和 Docker status 若不共用 schema，
   最终会重新形成多套状态模型。

## 9. 明确非目标

第一阶段不实现：

- 自动模型训练或微调；
- 在线模型市场；
- 多 QQ 集群；
- 分布式推理；
- 无人值守 QQ 登录；
- 把 NapCat/QQ 源码改造成 Stella 内部模块；
- 以一个超级单文件 EXE 携带全部模型和第三方运行时。

## 10. 第一阶段完成定义

当以下条件全部满足时，Runtime MVP 才算完成：

1. 双击 GUI 或 `stellacli start` 能启动 Stella。
2. Runtime 能报告 Stella 的启动、健康、失败和停止状态。
3. Stella 崩溃后能按退避策略自动恢复。
4. llama-server 可以作为可选组件启动并通过 OpenAI-compatible API 使用。
5. `/stella/status`、CLI、GUI 能显示统一的组件状态。
6. OneBot/NapCat 断线有明确诊断，不要求重启 Stella。
7. AI 关闭或 LLM 失败时，基础 Bot 仍能工作。
8. 日志、manifest、版本和 checksum 可定位到具体组件。
9. 迁移和升级不会覆盖 `STELLA_HOME` 中的用户数据。
