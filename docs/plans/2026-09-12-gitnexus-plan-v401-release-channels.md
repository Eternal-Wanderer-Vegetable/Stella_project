# GitNexus Engineering Plan

> Task: 将 Stella v4.0.1 拆分为一键安装与 Stella 本体两条发行线，默认安装 qwen3-embedding-0.6b，精简包内容，并将一键版本改为单个可点击安装程序。
> Evidence verified at commit `e774299f468eae3ee86211e2dd9e35a975aa0151`; GitNexus index refreshed this session with Docker `analyze --index-only --pdg` (GitNexus 1.6.11), current at `e774299`.
> Evidence provenance schema 2; global dirty digest `01287e297b63aafe9ff377cfc3294a17e1163d375ca7b4c6d5d067e3b447cc92`; cited-path manifest 24 sorted entries; exact generated plan path excluded.

## 1. Objective

[verified] 为 v4.0.1 建立四个明确的 Windows 产品资产：`OneClick-Python`、`OneClick-Rust`、`Standalone-Python`、`Standalone-Rust`。一键资产发布为单个 Tauri 安装程序，首次安装自动准备 Stella、嵌入式 Python、所选 Rust/Python 核心、llama.cpp CPU 默认后端、固定版本 NapCat，并默认下载并校验 `qwen3-embedding-0.6b`；Standalone 资产只包含 Stella 本体及对应 Python/Rust 记忆实现，不带 NapCat、llama.cpp 或任何 GGUF 模型。

[assumed] 一键版仍允许用户在首次向导中跳过 NapCat 登录；QQ 登录必须人工扫码，不能实现无人值守扫码、OCR 或自动确认。

## 2. Current Behaviour

[verified] `runtime_bootstrap::prepare_runtime` 只下载/解压 Python、pip、requirements 和可选 Rust wheel（`stella-installer/src-tauri/src/python.rs:72-140`），没有组件或模型下载。

[verified] `run_deploy_inner` 在 `prepare=true` 时先执行 `prepare_runtime`，再调用 `python -m deploy`；`run_runtime_operation` 是 Tauri Runtime 操作的统一入口（`stella-installer/src-tauri/src/python.rs:807-888`）。GitNexus 对 `runtime_bootstrap.prepare_runtime` 的 upstream impact 为 CRITICAL，影响 10 个 Runtime/Tauri 流程；`try_runtime_operation` 也为 CRITICAL，直接影响 `get_status`、`run_doctor`、`start_bot`、`stop_bot` 及 Tauri 启动链。

[verified] `deploy.napcat.install_archive` 只接受本地 ZIP 和外部 manifest，执行 digest、license、source、SBOM 校验及原子安装，不负责远程下载或 GUI 首次启动（`deploy/napcat.py:55-186`）。其唯一直接调用者是 `deploy.__main__._cmd_packages`，GitNexus 风险为 LOW。

[verified] `deploy.packages._catalog_records` 只从发布目录实际文件和可选 `.stella-llama-catalog.json` 生成清单；`build_catalog -> write_catalog -> _cmd_packages` 构成发布清单链路，GitNexus upstream impact 为 LOW、3 个受影响符号。

[verified] 主 Release 当前构造一个 `dist/Stella` 后打成 `Stella-v*-win64.zip`，Tauri 只执行 `cargo tauri build --no-bundle` 并上传裸 `Stella.exe`（`.github/workflows/release.yml:23-67,216-347`）。其 rsync 排除清单虽已排除测试、文档、开发目录和运行期文件，但仍是“全量复制后排除”，不是产品 allowlist。

[verified] `release-llama.yml` 只有 `workflow_dispatch`，构建结果上传为 workflow artifact，`publish` job 仅输出说明，未上传 GitHub Release asset；产物名仍硬编码 `v4.0.0`（`.github/workflows/release-llama.yml:1-70`）。

[verified] `tauri.conf.json`、`stella-installer/src-tauri/Cargo.toml` 仍为 `0.1.0`，而 `pyproject.toml` 与 `cli/Cargo.toml` 已为 `4.0.0`；Release 只在构建时临时同步 Tauri 版本（`stella-installer/src-tauri/tauri.conf.json:1-33`, `pyproject.toml:1-4`, `cli/Cargo.toml:10-13`）。

## 3. Relevant Architecture

[verified] 现有架构已将 Runtime、组件包、模型包、SHA-256、原子导入与回滚定义为独立边界；运行时架构文档要求模型独立于程序，embedding 位于 `models/embedding`，NapCat 保持独立版本与许可证边界（`design_docs/Stella Runtime & One-Click Deployment Architecture.md:585-646,678-830,1091-1225`）。

[verified] 落地方案已明确 `bootstrap installer + component packages + model packages`，并将 NapCat 自动安装、完整 Supervisor 和 GPU 矩阵列为后续能力（`design_docs/Stella Runtime 落地实施方案 v1.0.md:198-240,362-383`）。本计划把其中“自动安装”限定为固定来源下载、校验、安装和人工扫码，不扩大为无人值守登录。

[inferred] 发行层应采用“产品 profile + 远程 component/model catalog + 单文件 bootstrap installer”：安装器本身保持较小，下载内容由 profile 决定；Standalone 不消费远程组件 catalog，从而保持体积和行为稳定。

## 4. GitNexus Findings

- [graph] `runtime_bootstrap.prepare_runtime` 精确 impact：5 个符号、10 个受影响流程，风险 CRITICAL；深层调用涉及 `run_deploy_inner`、`run_runtime_operation`、Tauri `get_config/get_status/run_doctor/start_bot`。
- [graph] `try_runtime_operation` 精确 impact：6 个直接/间接受影响符号，风险 CRITICAL；任何首次启动准备逻辑变更都必须覆盖状态、自检、启动、停止和迁移入口。
- [graph] `_catalog_records` impact：d=1 为 `build_catalog`，d=2 为 `write_catalog`，d=3 为 `_cmd_packages`；变更必须保持 CLI catalog/verify 行为。
- [graph] `install_archive` impact：d=1 为 `_cmd_packages`；自动下载应新增独立 acquire 层，不能把网络副作用隐式塞进现有本地归档 API。
- [graph] PDG `run_deploy_inner` 从 `prepare` 分支桥接到 `run_deploy`、`run_deploy_without_prepare`、`run_runtime_operation`，并影响 11 个流程；实现必须保留 `prepare=false` 的 stop/close 路径。
- [graph] PDG `build_catalog` 桥接到 `write_catalog` 和 `_cmd_packages`；清单生成与校验应在最后的 release assembly 阶段一次性生成，不能在中间步骤生成过期 fingerprint。
- [verified] 相关测试已存在：`tests/test_release_layout.py`、`tests/test_packages.py`、`tests/test_napcat_package.py`、`tests/test_gpu_catalog.py`、`tests/test_runtime_contract.py`；它们目前覆盖清单、checksum、原子模型导入、NapCat 本地归档和 backend provenance，但没有四类产品 profile、单文件安装器或干净 Windows 首次启动矩阵。
- [assumed] GitNexus 对 YAML workflow 的调用关系有限，CI 资产依赖以源码读取和 workflow smoke test 为准；索引已提示 96 个跨语言字段解析限制与部分流程截断，不能把空图结果当作无依赖。

## 5. Statement-Level PDG Findings

- [graph] `runtime_bootstrap.prepare_runtime` 的核心控制边界是依赖 marker 命中、Python 是否存在、下载/校验/解压、pip/requirements 安装、Rust wheel 安装和失败清理（`python.rs:76-140`）；现有 `PREPARE_LOCK` 与失败回滚必须包住新增组件/model staging。
- [graph] `run_deploy_inner` 的 `if prepare { prepare_runtime(&root)?; }` 位于命令创建之前（`python.rs:854-866`）。安装阶段失败必须在调用 Python deploy 前返回可诊断错误；`prepare=false` 的 stop 路径不得触发下载。
- [graph] `build_catalog` 的 PDG 结果桥接到 `write_catalog` 和 `_cmd_packages`；catalog 记录必须先完成实际文件存在、digest、platform/backend/status 校验，再原子写入。
- [graph] NapCat PDG 在当前 line anchor 没有形成可用的 intra-procedural block，只有 `_cmd_packages` 的 callgraph bridge；计划不依赖伪造的语句边，保留 `install_archive` 作为已验证的事务边界。
- [graph] `scripts.build_llama_package.build` 只被脚本 `main` 直接调用，PDG 未发现额外上游；其真实约束来自源码：CMake 构建 `llama-server`、复制动态库、写 `BACKEND.json`/`SBOM.json`/`SHA256SUMS.txt`（`scripts/build_llama_package.py:30-108`）。
- [inferred] 新的 `prepare_runtime` 应只负责 bootstrap prerequisite 和组件编排；下载、校验、staging、激活、进度和回滚应抽为可单测的 Rust component installer，避免继续把所有行为塞进 Python 准备函数。

## 6. Proposed Changes

### 6.1 Product profiles and names

- **Files:** new `release_assets/product-profiles/*.json`, `runtime-manager/schemas/product-profile.schema.json`, `deploy/packages.py`.
- **Symbols:** `build_catalog`, `_catalog_records`, `verify_catalog`.
- **Change:** 定义 `oneclick-python`, `oneclick-rust`, `standalone-python`, `standalone-rust` 四个 profile；固定资产命名为 `Stella-OneClick-{Python|Rust}-v4.0.1-windows-amd64.exe` 与 `Stella-Standalone-{Python|Rust}-v4.0.1-windows-amd64.zip`。CLI、Docker 和 llama backend 独立资产不混入四个产品包。
- **Constraints:** profile 必须记录 version、platform、core flavor、included components、default models、optional components、catalog URL、license/SBOM、SHA-256、size；没有精确 digest 的第三方资产不得进入 one-click 发布。

### 6.2 Single-file one-click bootstrap

- **Files:** `stella-installer/src-tauri/src/python.rs`, `stella-installer/src-tauri/src/commands.rs`, new `stella-installer/src-tauri/src/bootstrap.rs`, `stella-installer/src-tauri/tauri.conf.json`, `stella-installer/src-tauri/Cargo.toml`, `.github/workflows/release.yml`.
- **Symbols:** `runtime_bootstrap::prepare_runtime`, `run_runtime_operation`, `run_deploy_inner`, `try_runtime_operation`.
- **Change:** 将安装器分为 bootstrap prerequisite、component/model acquire、activation 三段；下载远程 catalog，按 profile 下载 Python/Rust core、llama CPU、NapCat 与默认 embedding；每个下载项执行断点续传、SHA-256、大小/磁盘空间检查、staging 解压、原子激活、`.bootstrap-progress` 持久化和失败清理。
- **Bundle:** 改用 Tauri NSIS/单文件安装器作为 one-click 资产，CI 不再把裸 `Stella.exe` 当作安装器。安装器内部不预装 chat GGUF；安装后可进入模型选择页。NapCat 安装后打开其正常登录界面，状态写为 `not_logged_in/qr_waiting`，要求人工扫码。
- **Constraints:** 保留 `prepare=false` stop/close 语义；组件和模型必须落到独立 data/runtime 目录，升级只替换程序目录，不覆盖 `StellaData`、NapCat QQ data 或已下载模型。

### 6.3 Default embedding model

- **Files:** `deploy/packages.py`, `deploy/runtime.py`, `runtime-manager/schemas/package-catalog.schema.json`, new model catalog/profile fixtures, `stella-installer/src/settings.html` or first-run page, tests.
- **Symbols:** `import_model`, `rollback_model`, `build_catalog`, `verify_catalog`.
- **Change:** one-click profile 强制声明并安装一个固定 artifact `qwen3-embedding-0.6b`；安装完成后注册为 active embedding，并写入 `MEMORY_EMBEDDING_MODEL` 与本地 embedding endpoint。除该模型外不得自动下载 chat/consolidation/reranker GGUF。
- **Constraints:** exact GGUF filename/quantization、来源、许可证、digest、大小和 embedding dimension 必须在实现前锁定；模型下载失败必须阻止“安装完成”状态，但不能删除用户已有模型；模型切换沿用现有 active/rollback 事务。

### 6.4 NapCat automatic acquisition without unattended login

- **Files:** `deploy/napcat.py`, `deploy/__main__.py`, new `deploy/acquire.py` or Rust bootstrap adapter, `tests/test_napcat_package.py`.
- **Symbols:** `validate_manifest`, `install_archive`, `status`, `_cmd_packages`.
- **Change:** 保持 `install_archive` 为“本地已下载归档”的纯安装 API；新增 pinned manifest resolve/download 层，下载后复用现有 digest/license/source/SBOM 校验，再调用 `install_archive`。为 GUI/CLI 增加“已安装、等待扫码、已连接、过期”状态和人工操作提示。
- **Constraints:** 禁止 `latest`、禁止隐式替换第三方 license、禁止 OCR/自动扫码/自动确认；NapCat QQ data 和登录凭据不得进入诊断、catalog 或安装日志。

### 6.5 Slim standalone packages

- **Files:** `.github/workflows/release.yml`, `scripts/check_release_layout.py`, new `scripts/build_release_package.py`, `tests/test_release_layout.py`, `release_assets/README-快速开始.txt`.
- **Change:** 用可审计 allowlist 构造发布目录，分别生成 Standalone-Python/Rust；明确排除 `runtime/python`、NapCat、llama backend、GGUF、模型 catalog 下载缓存、测试、design_docs、`.git*`、开发脚本、日志、数据库和真实用户数据。Rust Standalone 只保留 Stella Rust memory wheel/运行所需文件，不带第三方运行时。
- **Constraints:** release layout 检查必须验证“允许文件集合”和“禁止文件集合”双向一致；README 按产品类型分流，不再让 Standalone 文案承诺自动安装 NapCat/LM Studio。

### 6.6 v4.0.1 release contract

- **Files:** `pyproject.toml`, `cli/Cargo.toml`, `stella-installer/src-tauri/Cargo.toml`, `stella-installer/src-tauri/tauri.conf.json`, `.github/workflows/release.yml`, `.github/workflows/release-llama.yml`, `.github/workflows/release-memory-rust.yml`, release notes.
- **Change:** 版本统一为 `4.0.1`；tag 必须为 `v4.0.1`；Release 必须是正式版而不是 prerelease。保留 `v4.0.0` 为历史 Pre-release，不覆盖、不复用其资产。
- **Release gate:** tag、pyproject、CLI Cargo、installer Cargo、Tauri config 和 Rust engine package version 全部一致；主 workflow 必须上传四类产品资产及既有 CLI 资产；llama workflow 改为由主 release 传入 tag/version，验证后用 `gh release upload --clobber` 上传实际 backend assets，并生成与 Release assets 一致的 catalog。

## 7. Implementation Sequence

1. **Freeze product contract.** 定义四类资产名、profile schema、Standalone allowlist、OneClick 默认组件和 v4.0.1 release matrix；锁定 qwen3-embedding-0.6b 的实际 GGUF 来源、量化、许可证、digest、尺寸和 embedding dimension。风险：第三方资产许可证或下载地址无法固定时，阻塞 one-click 发布。
2. **Add catalog/profile schemas and fixtures.** 扩展 package catalog 以表达 artifact、profile、backend、model role、size、source、license、SBOM、status；先补纯 Python schema/validation tests，保持现有 `packages catalog/verify` 兼容。
3. **Extract bootstrap installer.** 在 Rust 中实现 catalog fetch、resume、hash、staging、atomic activation、progress、rollback；将 `prepare_runtime` 变成编排入口；确保 `prepare=false` 不触发网络。风险：该步骤触及 CRITICAL Tauri path，必须同步回归 `get_config/get_status/run_doctor/start_bot/stop_bot/run_migrate`。
4. **Wire one-click profiles.** 让 Python/Rust profile 选择不同 Stella core 和 wheel；安装 `llama-server` CPU component、固定 NapCat 和 qwen embedding；只把 chat model 留给向导中的用户选择/导入。
5. **Integrate NapCat acquire/status.** 新增远程 pinned archive 下载和人工扫码状态；复用 `install_archive` 的事务安装和保留 QQ data 约束；不实现无人值守登录。
6. **Replace release assembly with allowlists.** 生成四类成品目录；Standalone 不携带第三方组件，OneClick 只输出一个 setup executable；生成 manifest/catalog 作为最后一步，禁止中间步骤复制过时清单。
7. **Complete llama/backend publication.** 将 `release-llama.yml` 接入 `v4.0.1` 主发布，至少保证 windows-amd64 CPU 可用；Vulkan/CUDA/Metal 等资产必须按 `build-only` 与 `hardware-verified` 状态区分，未验收不得标成硬件已验证。
8. **Update docs and release notes.** 分别说明四类下载对象、体积、依赖、首次启动、人工扫码、默认 embedding 和 chat model 不预装；移除“所有依赖已完整一键安装”的不准确表述，直到 clean-machine 验收通过。
9. **Final packaging and release.** 先在 CI 运行完整 tests、allowlist/layout、catalog/artifact consistency、签名/版本 gate，再创建 `v4.0.1` 正式 Release；禁止通过覆盖 `v4.0.0` 修复资产。

## 8. Test Strategy

- `tests/test_packages.py`: profile catalog round-trip；默认 embedding 必须存在且只有一个 default model；profile 缺 digest/source/license/SBOM、artifact 缺失或 checksum 错误必须失败；active embedding 安装失败不得改变已有 active 记录。
- `tests/test_napcat_package.py`: pinned resolve/download 后复用本地安装；网络失败、digest 错误、路径穿越、重复安装、安装回滚、QQ data 保留；状态始终 `unattended=false`。
- `tests/test_release_layout.py`: 四种 package profile 的 allowlist；Standalone 不含 NapCat/llama/GGUF/runtime/cache；OneClick archive 目录不作为发布资产；Rust/Python 只含其对应核心实现；用户数据、日志、`.env`、数据库和开发目录均被拦截。
- `tests/test_gpu_catalog.py`: backend package 的 artifact、provenance、status、SHA-256 和 Release asset 名称一致；build-only 不得被判为 hardware-verified。
- New `tests/test_product_profiles.py`: 四种 profile 的文件集合、默认组件、默认 embedding、禁止 chat model、版本和平台矩阵。
- New Windows integration tests: 在没有 LM Studio、NapCat、系统 Python 的干净 Windows runner 上运行 OneClick-Python/Rust，断言安装器只需点击一次即可展开，Python、llama CPU、NapCat 和 qwen embedding 可见且可校验；NapCat 进入人工扫码等待态；Standalone 不产生这些下载。
- New workflow smoke test: 解包/安装四类产物，检查 Release asset 数量、名称、大小上限、签名、SHA-256、catalog 引用和 `v4.0.1` 版本一致性。
- Existing regression commands: `python -m pytest tests/test_packages.py tests/test_napcat_package.py tests/test_gpu_catalog.py tests/test_release_layout.py tests/test_runtime_contract.py`; Rust/Tauri 使用仓库现有 Windows build job 验证；完整 clean-machine 验收必须在 Windows runner/真实机器完成。

## 9. Risk and Impact Analysis

- **CRITICAL:** `runtime_bootstrap::prepare_runtime`, `run_deploy_inner`, `try_runtime_operation`。直接影响 Tauri 状态、自检、启动、停止、迁移和首次配置；必须保持 mutex、marker、失败回滚、UTF-8 输出和 `prepare=false` 语义。
- **HIGH:** 发布资产和 profile schema。错误的 allowlist 会导致程序缺失或把用户数据/凭据发布出去；CI 必须同时做 allowlist 正向检查与敏感文件负向检查。
- **HIGH:** 第三方 NapCat/llama provenance。版本、来源、许可证、SBOM、digest 不完整时必须阻塞 OneClick，而不是退化成不可验证下载。
- **MEDIUM:** 默认 embedding 模型。首次安装体积、网络失败和磁盘空间会显著影响用户体验；显示大小/进度，允许重试，不静默下载其它大型模型。
- **MEDIUM:** v4.0.0 到 v4.0.1 迁移。旧 ZIP 仍需可运行，旧 `StellaData`、models、NapCat data 必须保留；新安装器不得把数据目录当作程序目录覆盖。
- **Observability:** 每个 artifact 记录 id/version/platform/backend/model role/status/checksum/size；安装日志只记录脱敏的状态和错误码，不能记录 token、QQ 登录数据或用户 prompt。
- [graph] GitNexus 的跨语言字段和流程截断意味着 Rust/Python/Workflow 边界不能只依赖图索引；所有高风险结论均已用源码和现有测试复核。

## 10. Files Expected to Change

| File | Symbols | Reason |
| ---- | ------- | ------ |
| `.github/workflows/release.yml` | release jobs | 四种产品资产、allowlist assembly、v4.0.1 gate、正式 Release |
| `.github/workflows/release-llama.yml` | build/publish jobs | backend artifact 与 Release catalog 对齐 |
| `.github/workflows/release-memory-rust.yml` | release package job | 与四种 profile 的 Rust core 版本和资产命名对齐 |
| `stella-installer/src-tauri/src/python.rs` | `prepare_runtime`, `run_runtime_operation`, `run_deploy_inner` | bootstrap 编排和 prepare 语义保持 |
| `stella-installer/src-tauri/src/commands.rs` | `try_runtime_operation`, status/start/doctor commands | GUI 进度、错误和安装状态桥接 |
| `stella-installer/src-tauri/src/bootstrap.rs` | new component installer API | 下载、校验、staging、激活、回滚 |
| `stella-installer/src-tauri/tauri.conf.json` | bundle config | 单文件 NSIS/安装器元数据与 4.0.1 |
| `stella-installer/src-tauri/Cargo.toml` | package version/dependencies | 安装器版本与 bootstrap 依赖 |
| `deploy/packages.py` | `_catalog_records`, `build_catalog`, `verify_catalog`, model helpers | profile/model/component catalog |
| `deploy/napcat.py` | `validate_manifest`, `install_archive`, `status` | pinned acquisition 后的安全安装和人工扫码状态 |
| `deploy/__main__.py` | `_cmd_packages` | 新 catalog/acquire/profile CLI surface |
| `deploy/runtime.py` | manifest/default model integration | embedding active state 和 runtime manifest |
| `scripts/build_release_package.py` | new | allowlist 构造四种产品目录 |
| `scripts/check_release_layout.py` | `check` | 产品 profile 的正负向布局校验 |
| `scripts/build_llama_package.py` / `scripts/verify_llama_package.py` | `build`, `verify` | versioned artifact、provenance 和 backend 状态 |
| `runtime-manager/schemas/package-catalog.schema.json` | package schema | artifact/profile/model 元数据约束 |
| `runtime-manager/schemas/product-profile.schema.json` | new | 四类产品合同 |
| `release_assets/README-快速开始.txt` | quick-start text | 按产品线区分安装方式和人工扫码 |
| `tests/test_product_profiles.py` | new | profile contract |
| existing package/layout/NapCat/GPU tests | existing tests | regression and release gates |
| `pyproject.toml`, `cli/Cargo.toml` | project versions | v4.0.1 consistency |

## 11. Reusable Implementation Context

```yaml
implementation_context:
  task_summary: "Build v4.0.1 dual release channels: one-click Python/Rust installers with default qwen3-embedding-0.6b, and slim Stella-only Python/Rust archives."
  acceptance_criteria:
    - "Four explicitly named Windows assets exist: OneClick-Python, OneClick-Rust, Standalone-Python, Standalone-Rust."
    - "OneClick assets are single clickable installer executables, not ZIP archives."
    - "OneClick installs pinned Python/Rust core, llama CPU backend, pinned NapCat package, and qwen3-embedding-0.6b by default."
    - "No chat/consolidation/reranker GGUF is automatically installed."
    - "Standalone assets contain only Stella core plus their Python/Rust flavor and no NapCat/llama/GGUF."
    - "NapCat login remains manual QR scan and all status/diagnostics keep unattended=false."
    - "Release is v4.0.1 formal, while v4.0.0 remains historical pre-release."
  evidence_provenance:
    schema_version: 2
    head_commit: "e774299f468eae3ee86211e2dd9e35a975aa0151"
    generated_plan_path: "docs/plans/2026-09-12-gitnexus-plan-v401-release-channels.md"
    global_dirty_digest:
      algorithm: "sha256"
      canonicalization: "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records"
      value: "01287e297b63aafe9ff377cfc3294a17e1163d375ca7b4c6d5d067e3b447cc92"
    cited_path_manifest:
      - path: ".github/workflows/release-llama.yml"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:ec3ca01cf3cb0e7d316c63f9529c4634d1b32e8d9d3206e6d56dfd2d96b42829"
        index_digest: "sha256:ec3ca01cf3cb0e7d316c63f9529c4634d1b32e8d9d3206e6d56dfd2d96b42829"
        worktree_digest: "sha256:ec3ca01cf3cb0e7d316c63f9529c4634d1b32e8d9d3206e6d56dfd2d96b42829"
        untracked_digest: "absent"
      - path: ".github/workflows/release-memory-rust.yml"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:931a023f460581a7b96331627935c6793f4b2823ff37935278d2b2d6f50ccaac"
        index_digest: "sha256:931a023f460581a7b96331627935c6793f4b2823ff37935278d2b2d6f50ccaac"
        worktree_digest: "sha256:931a023f460581a7b96331627935c6793f4b2823ff37935278d2b2d6f50ccaac"
        untracked_digest: "absent"
      - path: ".github/workflows/release.yml"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:d2d1b00f5f92c3dcec0d78560b47ae769c4f92ab6001db0d82d36568a08093d4"
        index_digest: "sha256:d2d1b00f5f92c3dcec0d78560b47ae769c4f92ab6001db0d82d36568a08093d4"
        worktree_digest: "sha256:d2d1b00f5f92c3dcec0d78560b47ae769c4f92ab6001db0d82d36568a08093d4"
        untracked_digest: "absent"
      - path: "cli/Cargo.toml"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:b4c775fb048ab6137bb35747ce3bf224fde9cea37fb8a2ff59e4dbbef0d75638"
        index_digest: "sha256:b4c775fb048ab6137bb35747ce3bf224fde9cea37fb8a2ff59e4dbbef0d75638"
        worktree_digest: "sha256:b4c775fb048ab6137bb35747ce3bf224fde9cea37fb8a2ff59e4dbbef0d75638"
        untracked_digest: "absent"
      - path: "deploy/__main__.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:9438f673bb3f9e9f3f84e8f4c5e4e6f4ba445a9c625dedad233649353ab39ecc"
        index_digest: "sha256:9438f673bb3f9e9f3f84e8f4c5e4e6f4ba445a9c625dedad233649353ab39ecc"
        worktree_digest: "sha256:86b02cc47be32a8975566372c416cdf410c6e1e054fa4cc8fcb8ddf1d6503f02"
        untracked_digest: "absent"
      - path: "deploy/napcat.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:e464bf6e6e78a209ac6218f80630087dbbda202487d2ca71f60136baf9ec9aa0"
        index_digest: "sha256:e464bf6e6e78a209ac6218f80630087dbbda202487d2ca71f60136baf9ec9aa0"
        worktree_digest: "sha256:e464bf6e6e78a209ac6218f80630087dbbda202487d2ca71f60136baf9ec9aa0"
        untracked_digest: "absent"
      - path: "deploy/packages.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:f8ab33b7bed58ea381c8d14daee44947baae06d6e98dc6854c9d1dddfa2eab7e"
        index_digest: "sha256:f8ab33b7bed58ea381c8d14daee44947baae06d6e98dc6854c9d1dddfa2eab7e"
        worktree_digest: "sha256:f8ab33b7bed58ea381c8d14daee44947baae06d6e98dc6854c9d1dddfa2eab7e"
        untracked_digest: "absent"
      - path: "design_docs/Stella Runtime & One-Click Deployment Architecture.md"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:e33d2b0bbf9f7c843207d8684d4809e4a5a8ce66f530e1509c265d87b72efc95"
        index_digest: "sha256:e33d2b0bbf9f7c843207d8684d4809e4a5a8ce66f530e1509c265d87b72efc95"
        worktree_digest: "sha256:e33d2b0bbf9f7c843207d8684d4809e4a5a8ce66f530e1509c265d87b72efc95"
        untracked_digest: "absent"
      - path: "design_docs/Stella Runtime 落地实施方案 v1.0.md"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:4225f26afbd38c24756fa71b0420ea0a39d982859eda7c927dbc8f236e36bd03"
        index_digest: "sha256:4225f26afbd38c24756fa71b0420ea0a39d982859eda7c927dbc8f236e36bd03"
        worktree_digest: "sha256:4225f26afbd38c24756fa71b0420ea0a39d982859eda7c927dbc8f236e36bd03"
        untracked_digest: "absent"
      - path: "pyproject.toml"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:eb2d1696502fd58e344d4cacef3965453ff52c4cc68f95d64919a49784eab51e"
        index_digest: "sha256:eb2d1696502fd58e344d4cacef3965453ff52c4cc68f95d64919a49784eab51e"
        worktree_digest: "sha256:079ea1977201238688688e58445fd9df9ee170da57833e7276e23670d36020df"
        untracked_digest: "absent"
      - path: "release_assets/README-快速开始.txt"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:b10d51a36ce068153e2ed21275e7be5c7ecc2722f0ac70642356713a85ab874b"
        index_digest: "sha256:b10d51a36ce068153e2ed21275e7be5c7ecc2722f0ac70642356713a85ab874b"
        worktree_digest: "sha256:7c637d1409472fb96ba38953589b14386596e4c156b34ebbd9caf1bb3008c10f"
        untracked_digest: "absent"
      - path: "runtime-manager/schemas/package-catalog.schema.json"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:8e92ffeff201ac003600896e5614baffddead92134312b30dd195b49807628b3"
        index_digest: "sha256:8e92ffeff201ac003600896e5614baffddead92134312b30dd195b49807628b3"
        worktree_digest: "sha256:8e92ffeff201ac003600896e5614baffddead92134312b30dd195b49807628b3"
        untracked_digest: "absent"
      - path: "scripts/build_llama_package.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:c84e27cbc2e75a5194b109925dba412aa79ef26126608aeb4c42cad5c762dff4"
        index_digest: "sha256:c84e27cbc2e75a5194b109925dba412aa79ef26126608aeb4c42cad5c762dff4"
        worktree_digest: "sha256:c84e27cbc2e75a5194b109925dba412aa79ef26126608aeb4c42cad5c762dff4"
        untracked_digest: "absent"
      - path: "scripts/check_release_layout.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:ad44a7456f8c7afe38067ad68ecea4fb85707f4419af2e1775a496e855cdedb6"
        index_digest: "sha256:ad44a7456f8c7afe38067ad68ecea4fb85707f4419af2e1775a496e855cdedb6"
        worktree_digest: "sha256:ad44a7456f8c7afe38067ad68ecea4fb85707f4419af2e1775a496e855cdedb6"
        untracked_digest: "absent"
      - path: "scripts/verify_llama_package.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:156d671f43011bdf9811b575a708726ab0f50389cccb2205f5076a9d8d8ed134"
        index_digest: "sha256:156d671f43011bdf9811b575a708726ab0f50389cccb2205f5076a9d8d8ed134"
        worktree_digest: "sha256:156d671f43011bdf9811b575a708726ab0f50389cccb2205f5076a9d8d8ed134"
        untracked_digest: "absent"
      - path: "stella-installer/src-tauri/Cargo.toml"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:6d13dcad6e1d7f99dbfa8fa52523fd26ac96272a59702883d36ac193075665f1"
        index_digest: "sha256:6d13dcad6e1d7f99dbfa8fa52523fd26ac96272a59702883d36ac193075665f1"
        worktree_digest: "sha256:6d13dcad6e1d7f99dbfa8fa52523fd26ac96272a59702883d36ac193075665f1"
        untracked_digest: "absent"
      - path: "stella-installer/src-tauri/src/commands.rs"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:5c03e835dcbbbbb2a17e350df4c2e79a03127b17587d95aed864f0ce0789e350"
        index_digest: "sha256:5c03e835dcbbbbb2a17e350df4c2e79a03127b17587d95aed864f0ce0789e350"
        worktree_digest: "sha256:447311fe592e04ff23313eacc4f200271d8faa4ec353d5b95f027d973c8e72fb"
        untracked_digest: "absent"
      - path: "stella-installer/src-tauri/src/python.rs"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:6143aaf005847467d6a318f87d88513f85585c4d719f0d2484d5908cc08394fd"
        index_digest: "sha256:6143aaf005847467d6a318f87d88513f85585c4d719f0d2484d5908cc08394fd"
        worktree_digest: "sha256:6143aaf005847467d6a318f87d88513f85585c4d719f0d2484d5908cc08394fd"
        untracked_digest: "absent"
      - path: "stella-installer/src-tauri/tauri.conf.json"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:703978a7afe3153a96dbff49ff0a7f1b3cf64415c94c80e53ebb9af4cefd1519"
        index_digest: "sha256:703978a7afe3153a96dbff49ff0a7f1b3cf64415c94c80e53ebb9af4cefd1519"
        worktree_digest: "sha256:703978a7afe3153a96dbff49ff0a7f1b3cf64415c94c80e53ebb9af4cefd1519"
        untracked_digest: "absent"
      - path: "tests/test_gpu_catalog.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:915b0234415afd84bfe31394d8e04ca562b287b43f4b50a648e529d7f2d29ec6"
        index_digest: "sha256:915b0234415afd84bfe31394d8e04ca562b287b43f4b50a648e529d7f2d29ec6"
        worktree_digest: "sha256:915b0234415afd84bfe31394d8e04ca562b287b43f4b50a648e529d7f2d29ec6"
        untracked_digest: "absent"
      - path: "tests/test_napcat_package.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:4206fad661d27e196b6e5021170b871e71e0a32f925d0ec1e08538a67af9335c"
        index_digest: "sha256:4206fad661d27e196b6e5021170b871e71e0a32f925d0ec1e08538a67af9335c"
        worktree_digest: "sha256:4206fad661d27e196b6e5021170b871e71e0a32f925d0ec1e08538a67af9335c"
        untracked_digest: "absent"
      - path: "tests/test_packages.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:4f59f103095478e419a91bf861002aac9abc990b4f3165f098e3d793622d6597"
        index_digest: "sha256:4f59f103095478e419a91bf861002aac9abc990b4f3165f098e3d793622d6597"
        worktree_digest: "sha256:4f59f103095478e419a91bf861002aac9abc990b4f3165f098e3d793622d6597"
        untracked_digest: "absent"
      - path: "tests/test_release_layout.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:0aeef5aaeb73f9509ed8f7f243a0a6259ff12ce7ca928c47d6d41de20740c0a2"
        index_digest: "sha256:0aeef5aaeb73f9509ed8f7f243a0a6259ff12ce7ca928c47d6d41de20740c0a2"
        worktree_digest: "sha256:836a168e29288381410299d919afd1c8cbe32bced85d6eacea4f3f3015e2b3cf"
        untracked_digest: "absent"
      - path: "tests/test_runtime_contract.py"
        object_kind:
          head: "regular"
          index: "regular"
          worktree: "regular"
          untracked: "absent"
        state: "clean"
        rename_from: null
        rename_to: null
        head_digest: "sha256:a0c4fef65b91864052a2db1758b108cbe3e65e8c7aecf0a1ab355bac10df5245"
        index_digest: "sha256:a0c4fef65b91864052a2db1758b108cbe3e65e8c7aecf0a1ab355bac10df5245"
        worktree_digest: "sha256:a0c4fef65b91864052a2db1758b108cbe3e65e8c7aecf0a1ab355bac10df5245"
        untracked_digest: "absent"
  primary_symbols:
    - {symbol: "runtime_bootstrap.prepare_runtime", file: "stella-installer/src-tauri/src/python.rs", lines: "76-140", role: "Python/runtime bootstrap entry"}
    - {symbol: "run_deploy_inner", file: "stella-installer/src-tauri/src/python.rs", lines: "854-888", role: "prepare gate and deploy subprocess"}
    - {symbol: "try_runtime_operation", file: "stella-installer/src-tauri/src/commands.rs", lines: "caller surface", role: "Tauri runtime owner bridge"}
    - {symbol: "_catalog_records/build_catalog", file: "deploy/packages.py", lines: "405-460", role: "release catalog construction"}
    - {symbol: "install_archive", file: "deploy/napcat.py", lines: "127-186", role: "transactional NapCat activation"}
  related_symbols:
    - {symbol: "write_catalog", relationship: "CALLS", relevance: "persists release catalog"}
    - {symbol: "_cmd_packages", relationship: "CALLS", relevance: "CLI catalog/NapCat entry"}
    - {symbol: "build", relationship: "called-by main", relevance: "llama backend assembly"}
    - {symbol: "verify", relationship: "called by release workflow", relevance: "backend provenance gate"}
    - {symbol: "check", relationship: "release layout gate", relevance: "user data/package boundary"}
  execution_path:
    - "Tauri/OneClick starts and selects product profile."
    - "Bootstrap downloads and verifies catalog entries into staging."
    - "Rust/Python core, llama CPU, NapCat and qwen3-embedding-0.6b are atomically activated."
    - "NapCat is started/configured and waits for manual QR login."
    - "Stella Runtime starts; chat model remains user-selected or external."
  pdg_constraints:
    - {description: "prepare gate executes before Python deploy subprocess", affected_statements: ["stella-installer/src-tauri/src/python.rs:859-866"], implementation_consequence: "component/model failure must return before deploy; prepare=false must remain network-free"}
    - {description: "catalog construction flows through write_catalog and _cmd_packages", affected_statements: ["deploy/packages.py:452-460"], implementation_consequence: "generate/verify catalog only after final artifact assembly"}
    - {description: "existing runtime bootstrap owns marker/lock/cleanup ordering", affected_statements: ["stella-installer/src-tauri/src/python.rs:76-140"], implementation_consequence: "new installer must preserve lock, marker invalidation and partial cleanup"}
  architectural_patterns:
    - {pattern: "atomic staging and activation", example_location: "deploy/napcat.py:143-185", usage_guidance: "reuse for component/model downloads"}
    - {pattern: "checksum and provenance catalog", example_location: "scripts/verify_llama_package.py:22-59", usage_guidance: "require digest/license/SBOM/status before publication"}
    - {pattern: "release layout defense in depth", example_location: "scripts/check_release_layout.py:45-90", usage_guidance: "combine allowlist and forbidden-content checks"}
    - {pattern: "runtime/data separation", example_location: "design_docs/Stella Runtime & One-Click Deployment Architecture.md:1133-1168", usage_guidance: "replace runtime, preserve data/models/config migration"}
  files_to_modify:
    - {file: ".github/workflows/release.yml", symbols: ["release jobs"], intended_change: "build four product lines and v4.0.1 formal Release"}
    - {file: ".github/workflows/release-llama.yml", symbols: ["build/publish"], intended_change: "publish verified backend assets and catalog"}
    - {file: "stella-installer/src-tauri/src/python.rs", symbols: ["prepare_runtime", "run_deploy_inner"], intended_change: "bootstrap orchestration"}
    - {file: "stella-installer/src-tauri/src/bootstrap.rs", symbols: ["new installer API"], intended_change: "download/verify/stage/activate/rollback"}
    - {file: "deploy/packages.py", symbols: ["_catalog_records", "build_catalog", "verify_catalog"], intended_change: "profile/component/model catalog"}
    - {file: "deploy/napcat.py", symbols: ["install_archive", "status"], intended_change: "pinned acquisition integration and manual-login state"}
    - {file: "scripts/build_release_package.py", symbols: ["new allowlist builder"], intended_change: "slim Standalone and OneClick assembly"}
    - {file: "runtime-manager/schemas/product-profile.schema.json", symbols: ["new schema"], intended_change: "four product contracts"}
  tests:
    - {file: "tests/test_product_profiles.py", scenarios: ["profile -> expected components/assets -> pass", "missing digest/license/SBOM -> reject", "default embedding present and only default model -> pass"]}
    - {file: "tests/test_packages.py", scenarios: ["embedding install -> active embedding recorded", "failed checksum -> active state unchanged"]}
    - {file: "tests/test_napcat_package.py", scenarios: ["pinned download -> install_archive -> not_logged_in", "network/checksum/path failure -> no activation"]}
    - {file: "tests/test_release_layout.py", scenarios: ["Standalone -> no third-party/model/runtime files", "OneClick -> only installer executable asset", "user data/development files -> reject"]}
    - {file: "tests/test_gpu_catalog.py", scenarios: ["backend asset/catalog digest match", "build-only is not hardware-verified"]}
    - {file: "tests/windows/test_oneclick_install.py", scenarios: ["clean Windows without LM Studio/NapCat/Python -> one click installs defaults", "manual QR wait -> unattended false"]}
  verification_commands:
    - "python -m pytest tests/test_product_profiles.py tests/test_packages.py tests/test_napcat_package.py tests/test_gpu_catalog.py tests/test_release_layout.py tests/test_runtime_contract.py"
    - "cargo tauri build --bundles nsis"
    - "python scripts/check_release_layout.py <profile-release-dir>"
    - "python scripts/verify_llama_package.py <backend-package>"
    - "gitnexus detect-changes --scope all --repo ."
  risks:
    - "CRITICAL Tauri prepare/runtime path regression"
    - "Third-party provenance or license unavailable"
    - "Default embedding download size/network failure"
    - "Allowlist accidentally omits required runtime files or includes user data"
    - "v4.0.0/v4.0.1 asset name/version drift"
  assumptions:
    - "The exact qwen3-embedding-0.6b GGUF artifact and license can be pinned before implementation; otherwise OneClick release is blocked."
    - "Tauri NSIS can produce the supported single-click Windows installer for the chosen per-user/per-machine install policy."
    - "NapCat distribution terms permit pinned redistribution or the product profile will use an approved download source."
  open_questions:
    - "Which exact qwen3-embedding-0.6b GGUF quantization/source/digest is approved?"
    - "Should OneClick install per-user or per-machine, and is code signing certificate available for v4.0.1?"
    - "Which NapCat fixed version/source/license/SBOM is approved for redistribution?"
  avoid:
    - "Do not merge OneClick and Standalone assets or silently add optional components to Standalone."
    - "Do not package chat/consolidation/reranker models by default."
    - "Do not implement unattended QQ login, OCR or automatic QR confirmation."
    - "Do not mark build-only GPU packages as hardware-verified."
    - "Do not overwrite or convert v4.0.0 pre-release into v4.0.1."
    - "Do not bypass the existing atomic staging, checksum and rollback patterns."
    - "Do not repeat full repository discovery; re-verify only cited assumptions before execution."

## 12. Assumptions and Open Questions

**Assumptions**

- [assumed] “默认安装 qwen3-embedding-0.6b” means the OneClick profile downloads one fixed GGUF artifact during installation and registers it active; it does not mean embedding bytes are embedded inside the small installer executable.
- [assumed] “只包含 Stella 本体” means Standalone excludes NapCat, llama.cpp, GGUF, embedded Python runtime and runtime download cache; the Rust flavor may include only the Stella Rust memory engine required by its own core.
- [assumed] Windows OneClick can use a Tauri NSIS installer as the single user-facing executable; whether installation is per-user or per-machine remains a product decision.

**Open Questions**

- Approve exact qwen3-embedding-0.6b GGUF quantization, source, license, SHA-256, size and dimension.
- Approve NapCat fixed version, redistribution terms, source URL and SBOM.
- Decide code signing and installation scope for `v4.0.1`.
- Confirm whether Linux/macOS release channels should receive the same profile split now or remain a later phase; this plan's acceptance scope is Windows because the request targets the single-click Windows installer.

**Deferred follow-ups**

- Full GPU backend hardware validation matrix remains separate from the v4.0.1 packaging contract; only provenance and build-status gates belong here.
- Model marketplace, multi-account QQ cluster and cloud synchronization remain outside this release.

## 13. Definition of Done

1. CI produces and verifies the four v4.0.1 Windows product assets with stable names and non-overlapping contents.
2. OneClick Python/Rust assets are single signed/clickable installer executables; they do not require the user to unzip a release archive.
3. On a clean Windows machine without LM Studio, NapCat or system Python, OneClick installs the selected Stella flavor, embedded Python, llama CPU backend, pinned NapCat package and qwen3-embedding-0.6b; it stops at manual QR login rather than pretending login is unattended.
4. No chat/consolidation/reranker GGUF is downloaded by default.
5. Standalone Python/Rust archives contain only the Stella core flavor and pass allowlist/forbidden-file checks; they do not contain NapCat, llama backend or GGUF/model cache.
6. `pyproject.toml`, `cli/Cargo.toml`, installer Cargo/Tauri metadata and release tag all resolve to `4.0.1`; the GitHub Release is formal, not prerelease; `v4.0.0` remains unchanged.
7. Catalogs, SHA-256 files, SBOM/provenance records and Release assets are mutually consistent; missing or unverified third-party assets fail CI.
8. Existing Tauri doctor/status/start/stop/migrate and Python deploy tests pass, including `prepare=false` shutdown behavior, marker invalidation and rollback on partial installation.
9. Docker GitNexus is refreshed after implementation, `status` is up-to-date, and `detect-changes --scope all` is clean for the final staged/committed tree.
