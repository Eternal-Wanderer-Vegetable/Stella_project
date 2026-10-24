# PR #120 Windows 验收与修复

日期：2026-10-24（Asia/Shanghai） · 验证基线：`2d1eb736d65a993136b5215d15b1a00403547ea2` · 分支：`codex/corona-nucleus-implementation`

范围：在实际 Windows 主机完成 PR #120 的 Windows native、Rust/Tauri 与 Dashboard 检查；把版本设为 6.3.0；修复 GitNexus 闭环流程归因污染；构建真实 NSIS EXE 并在一次性 Windows Sandbox 验收；构建真实 Docker 镜像并使用独立 named volume 启动。测试没有读写宿主机用户配置、生产数据库、QQ 会话或真实平台数据，也没有连接 QQ、WebChat 或模型服务。

## 修复

- Windows 导入 `corona.process_tree` 时不再提前求值 POSIX 专用的 `signal.SIGKILL`。Windows 托管入口改为由 Job Object 成员 wrapper 启动并等待核心子进程；父子 PID 不再用不可靠的 Windows `getppid()` 校验。就绪校验要求 PID 确实属于当前 Job，并把核心 PID 写入监管快照。
- Windows 忽略 `os.open(..., 0o600)` 权限位的问题：为运行日志目录设置仅当前用户 SID 的受保护 DACL；配置 ACL 校验按 SID 与 ACE 类型读取真实安全描述符，不依赖本地化的 `icacls` 用户名文本。增加当前用户 ACL 接受和外部 SID 拒绝用例。
- HTTP/WebSocket 路径转发先从 `raw_path` 分离 query bytes，再执行编码斜杠检查与上游 URL 拼接，修复 query 含 `%2F`、UTF-8 百分号字节时的错误拒绝。
- Windows 的 asyncio 超时与系统 monotonic deadline 在极短 50ms 边界出现时钟读数分歧。关闭 hook 一旦等待超时就将共享关闭预算标为耗尽，后续 hook 会被跳过。
- 稳定 Windows 验收用例：子进程测试保留 `SYSTEMROOT`；fake-core 故障测试改用父进程 ready 后写入 generation marker；移除 30ms 调度窗口；无创建符号链接特权时跳过该平台能力用例；补齐 Tauri 测试模块缺失的 helper 导入。
- 版本号统一为 `6.3.0`：`pyproject.toml`、CLI/desktop Cargo manifests 与 locks、Tauri 配置、双语 README、迁移报告模板和未发布 release notes。数据库 schema 仍为 19、Rust API 仍为 3；legacy 仍是默认运行路径。
- GitNexus 1.6.12 的增量 LadybugDB readback 会生成空 Method ID，之后把无关流程挂到通用 `__call__`。官方 [issue #3564](https://github.com/abhigyanpatwari/GitNexus/issues/3564) 记录了同一 1.6.12 缺陷，并将其归因于 LadybugDB 0.18.3 在增量写入后的 filtered-scan readback；该 issue 也记录了上游 main 已加入 identity reconciliation 防护，但已有损坏索引仍需强制重建。
- Docker 实测发现桌面 Rust `target` 目录未被忽略；Windows 编译输出增长到约 5.39 GB，第一次 build context 传输到 1.89 GB 时中止。`.dockerignore` 现在排除 `**/target`。同时 Docker healthcheck 现在校验 JSON 字段，避免旧版 WebUI SPA 对未知 Corona URL 返回 HTML 200 时造成假健康。

## GitNexus 影响与源码补证

- Windows 代码与测试变更后以 PR worktree 绝对路径刷新 GitNexus 1.6.12 索引（runner identity current，`incompleteReasons=[]`）。`_set_windows_private_acl` HIGH（15 impacted nodes、3 direct callers、3 affected processes、4 modules）；`_check_windows_private_acl` CRITICAL（11 nodes、1 direct caller、9 affected processes、3 modules）。具体 DACL helper 路径已逐项对照源码和配置/进程测试；不以 `riskSharedAxes` 豁免。
- `_kill_process_group` LOW（3 个直接调用者、6 个节点）；`CoreSupervisor._await_ready` LOW（4 个节点、1 条 lifespan flow）；Windows process-tree 工厂调用因动态 receiver 为 UNKNOWN，沿 `CoreSupervisor._spawn` 和 `process_tree_factory` 源码补证。
- 代理 HTTP、WebSocket 与危险路径检查为 LOW；对应中间件注册与 Nucleus 代理调用已用源码核实。测试文件的图关系为 UNKNOWN/0，pytest 自动发现与测试引用另行核实。
- 关闭预算：`run_shutdown_callback` LOW（1 个直接调用者）；`remaining_shutdown_seconds` LOW（7 个受影响节点、3 个直接调用者，Nucleus 模块）。
- 归因问题的根因是 GitNexus 1.6.12 的索引 readback，不是这些源码方法之间存在调用。完整重建命令：`node .gitnexus/run.cjs analyze --force --no-parse-cache --index-only --pdg --workers 1 <PR-worktree>`。结果为 **3,230 个 Method / 0 个空 ID**。`AdapterProxyMiddleware.__call__` 和 `ProxyResponse.__call__` 分别解析为各自文件/类的唯一 UID；incoming 仅为同文件 `has_method`，进程列表均为空。强制重建修复了本机索引快照：源码闭环检查不再把相关 `__call__` 归入 Get_config/Cometa 流程。由于本 worktree 使用 1.6.12，后续增量刷新后应检查 Method ID，发现空 ID 时再强制重建。

## 验证结果

- Windows Python 3.11.16 完整套件：`pytest tests/ -q -n 4 --dist loadgroup --timeout=120 --timeout-method=thread` → **4117 passed / 32 skipped / 6 warnings / 126.37s**。使用锁定依赖；为让测试主动净化环境变量的子 Python 进程也能找到依赖，运行期间通过临时 `.pth` 加载测试 site-packages，结束后已移除。
- Windows 专项：`pytest tests/windows -q -rs --timeout=120 --timeout-method=thread` → **10 passed / 1 skipped / 1.60s**。唯一跳过项是 `test_nsis_installation`，当时未设置 `STELLA_INSTALL_TEST_EXE`；随后已在一次性 Windows Sandbox 内直接运行 `scripts/test_nsis_install.ps1` 验收真实 EXE。安装器退出码 0，程序树、`oneclick-python` profile、`online` payload 与 release metadata 检查通过；安装耗时 20s。EXE 为 **231,977,878 bytes**，SHA-256 `049eeaaf193efae0f5f74fe07a421b3db2a0ca83f2d740fa8f03b77cacca8a7a`，签名状态 `NotSigned`。这是安装树验收，不包含 GUI 首启、在线运行时/组件下载或升级回滚；本地 staging 未包含正式发布生成的 package catalog。
- 原全量运行唯一失败的 50ms 关闭预算用例在修复后连续 **10 次通过**；此前 14 个子进程/配置/NoneBot 重现用例在正确依赖环境下 **14 passed**。
- 改动 Python 文件 Ruff、`compileall`、`git diff --check` 均通过。`python scripts/generate_message_flow.py --check` 通过；归档为 `message-flow.bf4b1dd6f688.json`（144 nodes / 142 source-resolved / 9646 closure sites / 15736 reachable symbols）。
- Windows Rust：CLI `cargo fmt --check`、`cargo clippy --all-targets -- -D warnings`、CLI tests **22 passed**、runtime-manager tests **9 passed**、Tauri desktop tests **25 passed**。此前 CLI 实际构建验证发生在本轮版本 bump 前；本轮四个版本来源均检查为 `6.3.0`，CLI 与 desktop `cargo metadata` 均成功，Tauri 真实安装器文件名为 `Stella_6.3.0_x64-setup.exe`。
- `desktop/src-tauri` 全包 `cargo fmt --all --check` 仍失败，列出多个既存 `commands.rs`、`python.rs`、`main.rs` 格式差异；本轮没有批量格式化这些无关代码，新增测试导入自身已按 rustfmt 排列。
- Dashboard：Vitest **110 passed**，production build 与 `sync:webui` 成功；Dashboard / WebUI / Tauri 静态产物 48 个文件哈希一致。
- Docker：`docker build` 成功；最终镜像 `stella:pr120-20261024-630-hc2`，digest `sha256:5fe65d3fbe99b70654e0b5f1efe8f4ee41f559babca9358ca74e995e743d02a4`，大小 **2,244,941,899 bytes**。以仅绑定 `127.0.0.1:18863` 的容器运行，数据只写入独立命名卷；静态 WebUI 版本标记为 `6.3.0`，桌面 Rust `target` 不在镜像中。容器内 `/stella/status` 返回 JSON 200 且版本为 6.3.0；宿主机访问该本地状态端点返回 403，符合 loopback-only 限制。旧版进程对 `/_corona/v1/health` 返回 SPA HTML 200，新增 JSON 字段校验使 healthcheck 正确回退到 `/stella/status`；容器最终 `healthy`。测试配置无 token、未连接 QQ、没有可用的本地 LLM 服务，所以这不构成模型或平台验收。
- 可复核产物：安装器脚本的原始 JSON 报告 [installer-test-report.json](evidence/pr120-windows-docker-20261024/installer-test-report.json)；汇总版本、GitNexus 门禁、镜像与容器检查的 [summary.json](evidence/pr120-windows-docker-20261024/summary.json)。
- Windows 修复代码/测试 head `f1cc1fd` 的 Hosted CI run `40044987734` **12/12 jobs passed**，含 Python 3.10/3.11/3.12 与 Windows native reliability matrix；Docker Publish `40044987747`、Dashboard CI `40044987735` 均通过。
- 最终代码/测试 head `4422804` 的 hosted CI run `40051788830` **12/12 jobs passed**，Python 3.10/3.11/3.12 与 Windows native reliability 均通过；Docker Publish `40051788823`、Dashboard CI `40051788829` 也成功。

## GitNexus 变更门禁

- 提交前 GitNexus 门禁：scope=all 为 **18 files / 35 symbols / 0 processes / LOW**；相对 `2d1eb736` 为 **35 / 73 / 12 / HIGH**；相对 `main` 为 **292 / 1,945 / 165 / CRITICAL**（列表截断）。提交 `4422804` 后再次强制重建，索引与 HEAD 对齐：**114,608 nodes / 288,477 edges / 1,192 clusters / 796 flows**，3,230 个 Method 中 **0 个空 ID**；两个目标 `__call__` context 均精确解析到所属类且 process list 为空。该干净 HEAD 上 scope=all 为无变更；刷新后的 `main` 累计比较为 **294 files / 1,945 symbols / 165 processes / CRITICAL**（列表截断）。两种累计结果都保留，不豁免 CRITICAL。
- 文档/配置目标的 upstream impact 返回 UNKNOWN，源码补查确认 `progress.md` / `session-handoff.md` 由任务工作流读取、`feature_list.json` 由文档检查脚本校验；Dockerfile healthcheck 路由字面引用已核对 `corona_health` 和 Bot status endpoint 源码。没有把 UNKNOWN 或零调用者视为无影响证明。
- `main` 是整条分支累计风险，不是本轮 Windows diff。
- 图仍遗漏 3200/3400 个入口候选、跳过 952 个 callees、裁剪 43 个 walk、23 个 trace 达深度上限；339 个属性读写点因定义只在其它语言中而未跨语言连边。超过 512KB 的 38 个文件被跳过，包含 3.9MB flow manifest。all 与两个 compare 输出未报告 partial/truncated；`main` compare 明确报告列表被截断。缺图边不作为无影响证明。

## 未完成验收

EXE 已在一次性 Windows Sandbox 完成安装树验收，Docker 镜像和容器 liveness 已通过；仍未完成 GUI 首启/在线包下载、EXE 升级回滚、正式 clean-VM 生命周期矩阵、Docker Compose 部署、可用模型服务、WebChat 及真实 QQ/OneBot 链路。按用户要求，QQ 接入等 PR 合并至 `main` 后再实测。保持 PR Draft、legacy 默认和 `CORONA-IMPL` `in_progress` / **NOT READY**。
