# Corona / Nucleus 实施 CN10：故障注入、跨进程恢复与资源验收

日期：2026-10-23（Asia/Shanghai） · 基线：`d010dd5`（CN09） · CN10 实现提交：`a300151` · 分支：`codex/corona-nucleus-implementation`

范围：工程计划 [CN10](../plans/2026-10-23-corona-nucleus-engineering-plan.md#cn10)。本报告记录 CN10 实施和已执行验收。整体 CORONA-IMPL 仍为 **NOT READY**；full Python 有一项 suite-order 失败，Rust 与 Windows 原生门禁没有可用工具/主机。

## 交付

- 为 fake Nucleus 增加三种真实子进程行为：成功 ready、启动后崩溃、ready 后崩溃。Linux 测试运行 100 个成功/失败/停止/恢复循环，检查独占 writer 锁、PID 回收、FD、线程和 async task 趋势。指标按 40 次 warmup 后的第 41–60 与 81–100 次窗口比较，带容差，不将 OS 计数宣称为严格不变。
- 新增真实 Nucleus 子进程代理负载检查：普通 HTTP、SSE、WebSocket、并行上传与核心重启时的独立控制健康端点；验证请求 ID 由 Nucleus 铸造并可关联。
- `internal_flow_catalog.py` 登记 Corona owner start/stop、配置 apply、桌面/CLI IPC dispatch、adapter proxy 到 Nucleus 五条跨进程生命周期入口。每项保留显式 process boundary、契约文件和跨进程 correlation 字段；不会把跨进程边伪装成本地调用边。
- 扩展 message-flow 生成器索引根，确保 `corona/`、`nucleus/`、`deploy/`、`stella_bootstrap/`、`stella_contracts/` 的入口锚点可解析；生成并检查新的 message-flow 清单。
- 修复回归运行时暴露的测试隔离/旧断言问题：proactive 测试同时隔离 DB 常量；deploy CLI 测试改为检查 Corona live-owner；安装 handler 先加载 legacy settings；包目录 catalog 的根目录固定到临时路径。没有改变生产行为。

## 指标

原始结果保存在 [CN10 evidence](evidence/corona-nucleus-cn10/)。

- Linux WSL2 / Python 3.12.14：100 个唯一 child PID 全部退出；100/100 次独占 writer `flock` 成功；orphan child 为 0。FD 两窗口中位数为 15 → 15（末窗 max 15）；线程 19 → 20（末窗 max 20）；pending async task 1 → 1。计数符合设定容差。每代写入独立日志文件 100 个，无内存日志队列。
- 30 次普通代理请求 p50/p95 为 **10.606 / 15.077 ms**。完成 5 个 SSE event、12 次 WS round-trip 和 4 路并行 256 KiB 上传；上传 p50/p95 为 **61.674 / 61.848 ms**。
- 3 次核心重启期间，控制健康端点返回 156 个成功响应，0 个 5xx/传输错误；控制延迟 p50/p95 为 **3.072 / 5.181 ms**，初始目标为 p95 < 500 ms。代理请求的 30/30 个 request ID 都是有效 Nucleus ID，调用方伪造值被替换。峰值 RSS：控制器/测试进程 435,344 KiB，fake core 51,032 KiB。
- 这些是当前 WSL2 fake-core 负载的观测值，不是 Windows、容器、真实业务 Nucleus、QQ 或模型性能承诺。

## A01–A34 分类

机器可读的逐项状态、关联测试和限制见 [CN10 scenarios](2026-10-23-corona-nucleus-cn10-scenarios.json)：**12 pass / 17 partial / 5 not_run**。通过项主要是配置/CAS/崩溃事务、内部鉴权、路径保护、100-cycle Linux soak、锁定 NoneBot 快照及群绑定 saga。Partial 保留了真实浏览器、外部平台/模型、插件/MCP/Chromium、SIGKILL storm、PID reuse、多实例全矩阵、host reboot 和 final 产品矩阵等缺口。A11、A13、A14、A15、A32 本轮未运行。

## GitNexus 编辑前影响

- `CoreSupervisor.start` LOW：2 个直接 caller / 1 个 Corona startup flow，另有 6 个 receiver-typed caller 未解析。`CoreSupervisor.stop` LOW：3 个受影响、4 个未解析 receiver caller。
- `OperationManager.accept` **HIGH**：7 个受影响 / 4 直接 caller / 3 flows，另有一个 caller 未解析。改动只在内部 flow catalog 登记该跨进程边界；高风险值按原结果保留，没有用 `riskSharedAxes` 抵消。
- `AdapterProxyMiddleware` LOW；`build_manifest` LOW。`RUNTIME_ENTRY_INVENTORY` 与新增测试模块为 UNKNOWN/0；源码审计确认 generator 对 inventory 的读取、pytest `tests/` discovery 及 CI 调用。索引仍有入口候选、callee、budget/depth 截断及动态/跨语言边缺失，零调用者不作为无影响证据。

## 验证结果

- 隔离 `STELLA_HOME` 的 CN10 相关 Python 回归：**142 passed / 4 warnings / 50.79s**，覆盖 `tests/corona`、`tests/nucleus`、flow inventory 和本轮受影响测试模块。警告为 FastAPI 重复 operation ID、已有 pytest class fixture deprecation，以及无适配器运行时提示。
- 全量 Python 在隔离 home 下：**4114 passed / 29 skipped / 1 failed / 3 warnings / 279.00s**。唯一失败为 `tests/webui/test_webui_cometa.py::TestApiKeyRoute::test_empty_key_rejected` 收到 401、期望 400；同一节点单跑为 **1 passed**。原因未确定；历史阶段也出现过顺序敏感的 Cometa/WebUI 401，故全量门禁保持 NOT GREEN。
- Dashboard：Vitest **9 files / 110 passed**；`pnpm --dir dashboard build`（包含 `vue-tsc --noEmit`）与 `sync:webui` 通过；`dashboard/dist`、`webui/dist`、`desktop/dashboard-dist` 一致。保留既有 mixed dynamic/static import 和大 chunk 警告。
- `.venv/bin/ruff check .` 通过；`.venv/bin/python scripts/generate_message_flow.py --check` 在 CN10 实现提交后复验通过，manifest `source_revision` 绑定 `a300151`；清单含 58 runtime entries、144 nodes / 142 source-resolved、9,640 closure sites、15,736 reachable symbols。
- `.venv/bin/python scripts/check_docs.py`：**119 files / 1279 local links / 577 migration anchors / 0 errors**；scenario/feature JSON parsing 与 `git diff --check` 通过。
- 暂存 GitNexus：serial `detect-changes --scope all` 为 **18 files / 41 symbols / 0 affected processes / LOW**；随后 compare `main` 为 **248 files / 1501 symbols / 150 affected processes / CRITICAL**。两项均无 partial/truncated 标记；compare 的符号列表被 CLI 截断展示，但统计覆盖全部变更。风险为整个分支相对 main 的累计风险，不豁免。
- 规划快照 verifier `docs/reports/evidence/corona-nucleus-20261023/verify_plan.py` 在 `tests/webui/test_webui_mount.py` 检出 source drift 后停止。该文件此前已被 CN06/CN07 实施修改；该 verifier 校验的是冻结的实施前规划快照。本轮未修改冻结 inventory、manifest 或 verifier。

## 未运行 / 未完成

- 当前是 Linux WSL2，不是原生 Windows 或 clean Linux VM。`cargo`、`rustc`、`rustup` 不在 PATH；Rust fmt/clippy/test/compiler 门禁未运行。Windows Job Object/native lock、干净 VM、Docker 与最终六类产品矩阵均 NOT RUN。
- 未运行真实 QQ/OneBot 服务、WebChat 在途模型/工具重启、真实模型、Cometa lease、Scheduler、真实记忆/Compact、MCP/插件/Chromium 集成或整机重启。
- legacy 默认保持不变。CN10 没有替代 CN11 的发布、灰度、回退或默认切换验收。

因此 CN10 的 Linux fake-process soak、proxy/flow 和可用本地门禁已交付；CN10 完整退出标准仍有全量 Python、Windows/native 与产品环境场景缺口，必须标记 **NOT READY**。不得据此宣布整项 CORONA-IMPL 完成。
