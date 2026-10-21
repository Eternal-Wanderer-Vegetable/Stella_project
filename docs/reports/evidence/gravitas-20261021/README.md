# Gravitas 规划研究证据（2026-10-21）

目标基线 `2b694026c4e4fc84ad721c26893ad5c68c7accb5`；仓库 `Stella_project`，工作区 `/home/vegetable/repos/Stella`。本目录支持[工程方案](../../../plans/2026-10-21-gravitas-engineering-plan.md)与[机器清单](../../../plans/2026-10-21-gravitas-inventory.json)，不表示业务实施或真实恢复已通过。

## 有效证据与复现

- GitNexus CLI 1.6.12、Node v24.19.0；[固定 runner 身份与索引元数据](index-metadata.json)、[重建后状态](baseline-status.json)、[命令及退出码](commands.json)。每条 `id` 对应同名 JSON（可解析结果）及 TXT（stdout/stderr 原件）。
- 原索引 content current 但 Function 身份字段为空，关键符号查不到，部分 impact 异常膨胀；[重建日志](analyze.log)执行 `analyze --index-only --force --no-parse-cache --workers 1 --pdg --name Stella_project --default-branch main`，42.9s，未开启 embedding 或注入 Agent 指令。原因尚未归因到具体工具缺陷，不把“新鲜”当“语义完整”。
- 重建快照：1,423 File、99,449 全部图节点（其中 74,164 BasicBlock）、246,820 edges、823 推断 Process；CLI 元数据 1,040 clusters 与实际 985 Community 节点分别记录。[节点计数](graph-counts.json)、[边计数](graph-edges.json)。
- 八类 `query-*`、十六组 `context-*` / `impact-*`。`impact-provider.json` 与 `impact-claim.json` 的首次 partial 均已用同名 `-retry.json` 成功重跑；机器清单只引用最终有效结果。
- `process-page-0.json` 到 `process-page-800.json` 共九页，合计 823 Process，无重复；[核心流程交集](graph-core-processes.json)为 58 个流程步骤记录，不等于 58 条独立流程。
- [50 入口清单](runtime-inventory.json)及机器清单中逐入口的 V1/V2/保留边界处置；[41 个源码调用点](source-call-sites.json)、[UNKNOWN 与动态接线补证](source-complements.txt)。73 个候选文件的 SHA-256 与 AST 定位在机器清单；它们经过结构扫描和定点阅读，不等于全部做过安全审计。

```bash
# 仓库根；若 shell 找不到 node，只向当前 shell 的 PATH 加入已安装运行时
export PATH=/home/vegetable/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH
node .gitnexus/run.cjs status --json
node .gitnexus/run.cjs context acquire --file core/llm/scheduler.py --repo Stella_project
node .gitnexus/run.cjs impact acquire --file core/llm/scheduler.py --direction upstream --repo Stella_project --summary-only
# 对大输出直接重定向文件，检查 JSON 完整性；经管道抓取曾在约 64KiB 处截断
```

## 风险、调用者与流程

均为重建后的原始 risk；File 与 symbol 的尺度不同，不使用 riskSharedAxes 豁免。

| 锚点 | direct / impacted / 流程摘要数 | risk | 调用 / 流程与约束 |
| --- | --- | --- | --- |
| scheduler.acquire | 11 / 28 / 6 | CRITICAL，context lower-bound | Planner、Router fallback、vision、embedding、Compact、整合/提取、旧 TurnService、AstrBot provider、锁兼容别名；推断路径含 maybe_plan、text_chat_stream、consolidation_drain_job 与评测入口 |
| compact_once | 2 / 9 / 3 | HIGH | schedule_compact 的 spawned `_run`、compact evaluation；群聊、私聊和评测路径 |
| deliver_lines | 6 / 10 / 3 | HIGH | 群聊/私聊、主动路径和 Cometa ack 闭包；处理片段发送的真实结果 |
| CaptureGate | 5 / 15 / 0 | MEDIUM | 启动、探针、状态与测试导入；无推断流程不表示未运行 |
| RoleBackend | 13 / 64 / 0 | MEDIUM，lower-bound | 导入与接口动态分派；真实模型尝试范围由源码和调用清单补齐 |
| OutboundService | 11 / 71 / 0 | MEDIUM | 平台装配、发送与测试；精确目标和未知结果不能放宽 |
| _pipeline_provider | 1 / 1 / 0 | LOW（retry） | submit_turn 直接调用；资源门缺口由两会话隔离探针证明 |
| submit_turn / CometaWorker / activate_capabilities | 各 0 图 impact | UNKNOWN | 分别由 gateway/WebChat、worker main、register_pre_hook 的实际源码引用补证；绝不按零风险处理 |
| trim_group_messages | 2 / 6 / 1 | LOW | timer trim_messages_job 与测试；风险数字不能取代零水位负例 |

完整上下游与名字在 `context-*`、`impact-full-scheduler.json`、`impact-full-compact.json`、`impact-full-delivery.json`。实际实施前须在目标 HEAD 重跑 HIGH/CRITICAL 门禁。

## 隔离验证结果

1. [定向现有测试](baseline-tests.txt)：83 passed / 2 warnings（12.46s）。覆盖 scheduler、CaptureGate、Facade、Cometa delivery/worker、outbound、虚拟时钟与参与决策回放。warnings 为 fake 环境未初始化 NoneBot/未发现 adapter，未启动平台。
2. [清理器现有测试](cleaner-tests.txt)：16 passed（0.68s），与上组文件不重叠。它没有覆盖本轮构造的零水位保护负例。
3. [默认 provider / waiter 探针](probe_baseline.py)与[结果](probe-baseline.json)：显式临时 STELLA_HOME；两合成会话峰值 2、scheduler snapshot 空；取消 waiter 后 waiting=1、holding=0。探针确认当前缺口，不是测试失败后绕过。
4. [清理器探针](probe_cleanup.py)与[结构化结果](probe-cleanup.json)、[原始输出](probe-cleanup-output.txt)：临时 SQLite 5 行，checkpoint=0、protect=true，删除 4 行；无用户数据。

```bash
STELLA_HOME=/tmp/stella-gravitas-probe-check .venv/bin/python docs/reports/evidence/gravitas-20261021/probe_baseline.py
STELLA_HOME=/tmp/stella-gravitas-probe-check .venv/bin/python docs/reports/evidence/gravitas-20261021/probe_cleanup.py
```

探针断言针对基线缺陷，修复后应更新为正式测试中的相反正确性断言；不要把本目录的缺陷复现脚本作为未来 CI 成功标准。

## 限制与被替代的证据

- `pre-refresh/` 是重建前诊断，命令原件保留，但风险与调用结果全部被本目录重建后结果替代；不可用于工程影响数字。
- 初次大 impact/PDG 抓取输出不完整，保留 TXT；后续 `--summary-only` 或直接文件 stdout 重跑，不能从截断 JSON 补猜统计。
- [PDG 重跑](pdg-scheduler-retry.json)虽完整且无 truncated，但 acquire 第 160 行返回 `pdg-no-block-at-line` / blockCount=0。其跨函数 callgraph bridge 不是语句级取消路径证明，F02 依赖源码与隔离探针。
- 823 推断流程仍受抽取入口、深度、分支预算限制；callable-value-flow 有 32 候选上限，源码注册与跨语言边界另查。图像新鲜度与业务正确性分别验证。
- 本轮没有全量 Python/真实模型/QQ/WebChat 灰度/跨进程 live/clean VM/发布验收；本轮没有实现 G00 修复。新配置、指标预算、命令和接口属于方案。
- 文档检查不扫描 plans/reports 正文，所以新增[规划验证脚本](validate_plan.py)逐条验证档案本地链接、源码指纹、工作包 DAG、50 入口、场景/不变量、有效图结果与证据哈希。最终命令/结果见 `validation-results.json`；完整文件摘要见 `SHA256SUMS.json`。

## 变更门禁与展示上限

最终 `detect_changes(scope=all)` 为本轮 5 个已跟踪文件 / 10 symbols / LOW，compare/main 为累计分支 354 文件 / 1,201 symbols / 117 流程 / CRITICAL；该累计比较包括既有跨平台实施，不代表本轮修改了业务源码。新增未跟踪方案与证据由档案验证器单独覆盖。

CLI detect-changes 输出人类可读摘要，参数 limit 只截取客户端显示，底层仍固定最多列 1,000 symbols。原生 structured compare 连续三次重跑均带 truncated，不能按通过处理。随后用[可复核临时 harness](uncapped_changes.mjs)把**临时模块副本的展示常量**从 1,000 提高为 20,000（[来源与摘要](expanded-listing-provenance.json)），算法、统计、风险和已安装工具均不改；最终完整重跑列出 1,201/1,201，摘要与原生结果逐字段一致，无 partial/truncated。完整结果为 `detect-all-complete.json` / `detect-compare-complete.json`。

最终文档状态调整后已再次运行同样门禁；原生 compare 的第三次重试另有 partial，完整重跑已恢复至原始 CRITICAL/117 流程统计，无 partial/truncated。结果以 `validation-results.json` 及最终 complete 记录为准。SHA256SUMS 排除自身和滚动的 validation-results.json，其他证据全部校验。

最终文档树重建快照（见 `final-analyze.log` / `final-index-metadata.json` / `final-status.json`）：99,993 节点、247,640 edges、1,044 metadata clusters、821 推断流程。它包含本轮证据/文档；前文 823 分页与 16 组源码研究对应较早的源码基线快照，两者不混用。新增档案使有预算的流程排名变化，821/823 都不是运行入口全集。最终状态记录之后只整理了证据原件和探针格式，业务源文件指纹再次核验；没有业务源码变更。

新增三个 Python 证据脚本已通过 Ruff；格式整理后的两个缺陷探针再次复现（`probe-baseline-final.json` / `probe-cleanup-final.txt`）。验证器对循环依赖和错误源码指纹的负例都明确拒绝（`validator-negative.json`）。
