# 主动参与与记忆 Benchmark — B02 公开决策基线

- 日期：2026-11-04
- 工作包：B02；证据等级：L1 公开数据、确定性本地决策
- 状态：两套公开 holdout 的适配与三种无记忆基线全部完成；整体 benchmark、生产行为和平台验收仍 **NOT READY**。
- 计划：[主计划](../plans/2026-11-04-proactive-memory-benchmark-plan.md)；前置：[B00 报告](2026-11-04-proactive-memory-benchmark-b00.md)、[B01 报告](2026-11-04-proactive-memory-benchmark-b01.md)

## 数据与隔离

| 数据集 | 固定 revision / 文件 SHA-256 | 原始单位 | 决策样本 | Gold 标签 |
| --- | --- | ---: | ---: | --- |
| When2Speak token test | `092e40995896b0c278a1e32954297ef125b70112` / `72304bf61f588cffee8e0620e12778b215d6ae6c1815cd3204ab3e0425258db7` | 21,687 token 行 | 21,687 | SILENT 18,892；SPEAK 2,795 |
| Social AI Ambient test | `5efda0b267d6bd5ecae74cbe1141a66f64495661` / `44d477ab5874cdc3e082d95787cb78f26e0a894e8a0056b56caca74058f66cd1` | 1,212 scenes | 16,222 标注轮次 | SILENT 15,793；SPEAK 429 |

When2Speak adapter 把末尾 assistant token 留在 scorer-only gold，actor scenario 仅含该 token 之前的 user context。Social AI adapter 为每个带标签的目标轮生成一个 scenario，actor 只能看到截至当前轮的对话前缀；source category/description 仅留在 report-side mapping，供分层统计。两套原生 `SPEAK`/`SILENT` 标签与 Stella 中文 persona 标签分开；本包没有中文 persona 标注，数量为 0。

运行命令：

```powershell
$attemptHome = Join-Path $env:TEMP 'stella-proactive-eval\B02-2026-11-04-attempt-2'
python -m proactive_eval.b02 --resume --home-root $attemptHome
```

环境为 Python 3.14.6。六组 actor/scorer 均在 B01 的隔离进程合同内运行；临时 `STELLA_HOME` 位于系统临时目录，报告、原始文本、逐案例结果和错误明细位于 gitignored 的 `memory/benchmark/_public/proactive_eval/runs/B02-2026-11-04/`。B02 summary SHA-256：`6136ef8456fd1a7d3f5fb6e1045930250c5af4f06e326d6dc6f8a9a99f7bf905`。六份 `report.json` 均通过 `validate_proactive_report`。

## 无记忆基线结果

`FIR = false interruptions / gold SILENT`；`MIR = missed interventions / gold SPEAK`。F1 为两类 Macro-F1。表中的 errors 保留逐案例 JSONL 与每种错误的计数。

| 数据集 | 基线 | Scored | Macro-F1 | FIR | MIR | 误判 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| When2Speak | Always silent | 21,687 / 21,687 | 0.4656 | 0.0000 | 1.0000 | missed intervention 2,795 |
| When2Speak | Always speak | 21,687 / 21,687 | 0.1142 | 1.0000 | 0.0000 | false interruption 18,892 |
| When2Speak | Last explicit question | 21,687 / 21,687 | 0.5037 | 0.0261 | 0.9470 | false interruption 494；missed intervention 2,647 |
| Social AI Ambient | Always silent | 16,222 / 16,222 | 0.4933 | 0.0000 | 1.0000 | missed intervention 429 |
| Social AI Ambient | Always speak | 16,222 / 16,222 | 0.0258 | 1.0000 | 0.0000 | false interruption 15,793 |
| Social AI Ambient | Last explicit question | 16,222 / 16,222 | 0.5184 | 0.0740 | 0.8322 | false interruption 1,168；missed intervention 357 |

三个 actor 都是无记忆规则：始终 DROP、始终 SPEAK、或仅当当前消息以 ASCII/全角问号结尾时 SPEAK。没有模型调用、生成输出或 memory input。六组 actor 与 scorer 的失败数均为 0，coverage 均为 100%。

这些结果是公开数据源标签上的原样基线。Always-silent 的零 FIR 伴随 100% MIR；always-speak 的零 MIR 伴随 100% FIR。问号规则在这两个 holdout 上仍漏掉 94.7% 与 83.2% 的正例，因此不支持宣称 Stella 产品决策有效，也不据此调整生产阈值或频率表。

## 运行证据与限制

- `python -m pytest tests/evaluation/test_proactive_b02.py -q`：**9 passed**；依赖 `async_asgi_testclient` 发出一条 Python 3.14 异步弃用警告。
- `python -m ruff check proactive_eval/b02.py proactive_eval/source_adapters.py proactive_eval/b02_plugins.py tests/evaluation/test_proactive_b02.py`：**PASS**。
- `python -m proactive_eval.b02 --help`：**PASS**；六份 report schema 校验：**PASS**。
- `python scripts/check_docs.py`：**127 files / 1,360 local links / 577 anchors / 0 errors**；`git diff --check`：**PASS**。
- GitNexus `detect-changes --scope all` repeated snapshots：**9 files / 3–25 symbols / 792 affected processes / CRITICAL**；`scope=compare --base-ref main`：**344 files / 364–1,158 symbols / 791–792 processes / CRITICAL**（分支累计；部分 changed-symbol 列表被截短，但 counts/risk 完整）。最近流列表甚至把计划文档标题映射到配置/部署流程。源码审计确认本包的可执行改动只在 `proactive_eval/` 与其测试；报告列出的 `Get_config → Sha256_hex/Run_command`、`Run → _manifest_with_installed_embedding` 等流程未被本包导入或修改。`dataset_id` 的文件限定 impact 错落到 Cometa 符号，说明此处图映射存在同名碰撞；保留 CRITICAL，不将其解释为安全豁免。
- `source_adapters.py` 文件级 upstream impact 一次为 HIGH（156 impacted / 181 processes / 20 modules），`--summary-only` 重查为 MEDIUM（40 impacted，但仍报 181 processes / 20 modules）。对应的 exact context 只显示两个 incoming imports（B02 runner、B02 tests）和一个 outgoing import（`proactive_eval.adapters`）；adapter 函数级 UID 未被索引解析。保留文件级 HIGH/CRITICAL 作为未消除的图风险，不以这项源码审计降低风险等级。
- 首个 When2Speak/always-silent 的 actor 与 scorer 已在前次启动中完成；随后仅从完成 checkpoint 恢复汇总，因此该报告的 `wall_time_ms` 为 `null`。另外五组报告记录了各自 runner wall time；不把缺失值补估为运行时间。
- 第一轮尝试曾因 B02 汇总解包缺陷停止；修复后恢复完整首组。第二轮发现总任务 `--resume` 被错误传给尚无 checkpoint 的新基线；修正后新基线不带 `--resume` 启动。失败尝试只留下隔离标记和缓存，不计入结果。当前 summary 的六组均为 completed。
- 数据类别极度不平衡，且数据集源标签不等于 Stella persona 标注。B02 没有评估 ParticipationManager、OpportunityManager 时机窗口、Mneme 写入/检索、生成质量或真人接受度；这些由后续工作包处理。
- 未使用真实聊天、生产数据库/配置、Bot、模型或平台服务。原始数据和逐案例错误内容不进入提交。

## 恢复点

B02 源码、定向测试、状态更新与本报告按一个工作包独立提交；B02 的数据产物保留在上述 gitignored run directory。下一包为 B03：用 PITCH 可用轮次窗口驱动正式 OpportunityManager、预算与 Mneme 求证状态，并单独记录发现的产品缺陷，不与本报告的无记忆基线混合。
