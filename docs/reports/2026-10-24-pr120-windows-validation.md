# PR #120 Windows 验收与修复

日期：2026-10-24（Asia/Shanghai） · 验证基线：`2d1eb736d65a993136b5215d15b1a00403547ea2` · 分支：`codex/corona-nucleus-implementation`

范围：在实际 Windows 主机上补跑 PR #120 未覆盖的 Python、Windows native、Rust/Tauri 与 Dashboard 检查，并修复在本机触发的跨平台问题。验证期间使用临时目录与锁定依赖，没有读写用户配置、生产数据库、QQ 会话或真实平台数据。

## 修复

- Windows 导入 `corona.process_tree` 时不再提前求值 POSIX 专用的 `signal.SIGKILL`。Windows 托管入口改为由 Job Object 成员 wrapper 启动并等待核心子进程；父子 PID 不再用不可靠的 Windows `getppid()` 校验。就绪校验要求 PID 确实属于当前 Job，并把核心 PID 写入监管快照。
- Windows 忽略 `os.open(..., 0o600)` 权限位的问题：为运行日志目录设置仅当前用户 SID 的受保护 DACL；配置 ACL 校验按 SID 与 ACE 类型读取真实安全描述符，不依赖本地化的 `icacls` 用户名文本。增加当前用户 ACL 接受和外部 SID 拒绝用例。
- HTTP/WebSocket 路径转发先从 `raw_path` 分离 query bytes，再执行编码斜杠检查与上游 URL 拼接，修复 query 含 `%2F`、UTF-8 百分号字节时的错误拒绝。
- Windows 的 asyncio 超时与系统 monotonic deadline 在极短 50ms 边界出现时钟读数分歧。关闭 hook 一旦等待超时就将共享关闭预算标为耗尽，后续 hook 会被跳过。
- 稳定 Windows 验收用例：子进程测试保留 `SYSTEMROOT`；fake-core 故障测试改用父进程 ready 后写入 generation marker；移除 30ms 调度窗口；无创建符号链接特权时跳过该平台能力用例；补齐 Tauri 测试模块缺失的 helper 导入。

## GitNexus 影响与源码补证

- Windows 代码与测试变更后以 PR worktree 绝对路径刷新 GitNexus 1.6.12 索引（runner identity current，`incompleteReasons=[]`）。`_set_windows_private_acl` HIGH（15 impacted nodes、3 direct callers、3 affected processes、4 modules）；`_check_windows_private_acl` CRITICAL（11 nodes、1 direct caller、9 affected processes、3 modules）。具体 DACL helper 路径已逐项对照源码和配置/进程测试；不以 `riskSharedAxes` 豁免。
- `_kill_process_group` LOW（3 个直接调用者、6 个节点）；`CoreSupervisor._await_ready` LOW（4 个节点、1 条 lifespan flow）；Windows process-tree 工厂调用因动态 receiver 为 UNKNOWN，沿 `CoreSupervisor._spawn` 和 `process_tree_factory` 源码补证。
- 代理 HTTP、WebSocket 与危险路径检查为 LOW；对应中间件注册与 Nucleus 代理调用已用源码核实。测试文件的图关系为 UNKNOWN/0，pytest 自动发现与测试引用另行核实。
- 关闭预算：`run_shutdown_callback` LOW（1 个直接调用者）；`remaining_shutdown_seconds` LOW（7 个受影响节点、3 个直接调用者，Nucleus 模块）。

## 验证结果

- Windows Python 3.11.16 完整套件：`pytest tests/ -q -n 4 --dist loadgroup --timeout=120 --timeout-method=thread` → **4117 passed / 32 skipped / 6 warnings / 126.37s**。使用锁定依赖；为让测试主动净化环境变量的子 Python 进程也能找到依赖，运行期间通过临时 `.pth` 加载测试 site-packages，结束后已移除。
- Windows 专项：`pytest tests/windows -q -rs --timeout=120 --timeout-method=thread` → **10 passed / 1 skipped / 1.60s**。唯一跳过项是 `test_nsis_installation`，没有设置 `STELLA_INSTALL_TEST_EXE`；最终安装器 EXE 验收仍须由 install-test job 或显式提供的隔离测试环境完成。Windows 进程 Job、私有 ACL 和真实 makensis hook 编译用例均通过。
- 原全量运行唯一失败的 50ms 关闭预算用例在修复后连续 **10 次通过**；此前 14 个子进程/配置/NoneBot 重现用例在正确依赖环境下 **14 passed**。
- 改动 Python 文件 Ruff、`compileall`、`git diff --check` 均通过。`python scripts/generate_message_flow.py --check` 通过；归档为 `message-flow.bf4b1dd6f688.json`（144 nodes / 142 source-resolved / 9646 closure sites / 15736 reachable symbols）。
- Windows Rust：CLI `cargo fmt --check`、`cargo clippy --all-targets -- -D warnings`、CLI tests **22 passed**、runtime-manager tests **9 passed**、Tauri desktop tests **25 passed**。Release CLI 构建成功；`stellacli.exe --version` 返回 `6.2.0`，`--help` 可用。
- `desktop/src-tauri` 全包 `cargo fmt --all --check` 仍失败，列出多个既存 `commands.rs`、`python.rs`、`main.rs` 格式差异；本轮没有批量格式化这些无关代码，新增测试导入自身已按 rustfmt 排列。
- Dashboard：Vitest **110 passed**，production build 与 `sync:webui` 成功；Dashboard / WebUI / Tauri 静态产物一致。Docker Compose 静态配置校验通过，没有启动容器或完成应用镜像构建。

## GitNexus 变更门禁

- 刷新索引快照含 **114,606 nodes / 1,192 clusters / 796 flows**。报告/状态文档更新时多次 `detect-changes --scope all` 有波动，观察到 **5 files / 10 symbols / 0 processes / LOW**、带有泛化 `Section ?` 映射的 **5 files / 1 symbol / 783 processes / CRITICAL**、以及 **5 files / 8 symbols / 0 processes / LOW**。比较结果也有波动：相对 Windows follow-up 基线 `2d1eb736` 为 **22 files / 10–27 symbols / 782–790 processes / CRITICAL**；相对 `main` 为 **282 files / 488–833 symbols / 784–791 processes / CRITICAL**。这些比较均未报告 partial/truncated。变更路径覆盖 DACL、Job/PID readiness、代理与测试。输出还把通用 `__call__` 扇出到 Get_config 与 Cometa 流程；对全部改动代码/测试文件做的字面搜索找不到 `Get_config`、`install_signal_handlers`、`Sha256_hex`、`Cometa_auth_api_key` 等对应名字。此流程归因未能由源码闭环，所有 CRITICAL 结果均保留、不作豁免。最终提交索引后 `scope=all` 返回 no changes，只表示提交后的工作树没有未提交 diff。
- `main` 是整条分支累计风险，不是本轮 Windows diff。
- 图仍遗漏 3200/3400 个入口候选、跳过 952 个 callees、裁剪 43 个 walk、23 个 trace 达深度上限。超过 512KB 的 38 个文件被跳过，包含 3.9MB flow manifest。缺图边不作为无影响证明。

## 未完成验收

本机 Windows 测试不是干净 VM。最终安装器 EXE 安装/升级/回滚、Windows/Linux clean VM、Docker 应用构建与运行、真实 QQ/OneBot、WebChat、模型和最终六类产品生命周期矩阵未运行。保持 PR Draft、legacy 默认和 `CORONA-IMPL` `in_progress` / **NOT READY**。
