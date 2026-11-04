# 主动参与与记忆 Benchmark — B00 协议和数据冻结

- 日期：2026-11-04
- 工作包：B00；证据等级：L0 合同冻结 + L1 既有检索回归
- 状态：协议/来源冻结完成；完整基线 **PARTIAL**；G0 运行器门禁尚未完成；benchmark 与产品验收仍 **NOT READY**。
- 计划：[主计划](../plans/2026-11-04-proactive-memory-benchmark-plan.md)

## 交付

- [评测合同](../../proactive_eval/README.md) 定义 actor/scorer 边界、原生数据单位、可见性和产物规则。
- [数据 registry](../../proactive_eval/dataset-registry.json) 固定来源 revision、许可证证据、下载文件 SHA256、样本数、单位、状态和限制；[NOTICE](../../proactive_eval/NOTICE.md) 记录归属与再分发要求。
- [协议锁](../../proactive_eval/protocol-lock.json) 冻结三张独立成绩面板、主要终点与分母、G0–G7 目标、统计方法、中文标注规模、频率条件和模型调用预算。门槛标记为预登记目标，未据此声称达到。
- [baseline lock](../../proactive_eval/baseline-lock.json) 记录源码锚点、隔离环境、当前可复跑 PersonaMem 检索模式及未运行项目。
- [JSON Schemas](../../proactive_eval/schemas/) 定义 registry、actor-only scenario、scorer-only gold、通用报告、主动参与报告和记忆报告 v2 合同。

原始数据、逐样本结果和依赖环境留在 gitignored 的 `memory/benchmark/_public/` 或系统临时目录；仓库只纳入来源元数据和聚合结果。验证未读取 Stella 用户配置、生产数据库或聊天记录，没有探测/启动模型、Bot、服务、QQ/WebChat，也未做发布 VM 验收。

## 冻结口径

主要终点分别报告 Aoede 参与意愿、Mneme 记忆链路和联合行为，不计算单一加权总分。每项包含分子/分母、覆盖率和状态；空分母不能 PASS。SPEAK/SILENT 的源标签、Stella 人格裁决、机会动作、生成、投递回执和预算记账分开记录。公开源回放使用 open-loop，actor 输入不含未来话语、未来确认、答案或 scorer gold；gold 仅由 scorer 读取。

统计冻结为按 conversation/session/speaker profile 聚类的配对 bootstrap，2,000 次、seed `20261104`、95% 区间。开发最多选定一个候选，holdout 只在冻结后评分一次。中文集合为 12 类×20 段（dev 120、holdout 120），需两名独立标注员和一名裁决员；目前没有标注员排期，状态 `BLOCKED_ANNOTATION_NO_ANNOTATORS_ASSIGNED`。G0–G7 数值均是预登记目标，不是已验证的通过标准结果；G7 需用户指定平台和范围并授权至少 7 天观察，现未运行。

默认单实验上限 200 次模型调用、30 分钟、并发 1；联合诊断上限按 120 个机会×4 条件、回答与裁判各一次估算 960 次调用。令牌示例估值 1.68M，价格未核实所以不报价。长数据集运行须单独预算。

PITCH 固定在 Git commit `6413b59ac9eca1e056c192a786f059076f91cb74` 与 MIT LICENSE。按官方 `ground_truth.acceptable_windows` 对全部标注窗口取交集，即 `max(start_turn) <= min(end_turn)`，得到 329/384 个非空窗口；此前计划中的 296/384 本次未复现。主分母保留 384，并将 55 个无非空交集样本单列原因；`within_group` 单独口径为 345/374。数据以对话轮次计窗，不换算成秒。

## 基线结果

原样代码锚点为 `cbcd6f9d3b725f73aee02a4e4c4ca7f5280d52bd`；运行时 HEAD `6de893fb39c71784cd46e0c4ea4d129d32afc780` 相对锚点只增加计划与状态文档。使用隔离 Python 3.12.14 环境、锁定依赖，并令 `STELLA_HOME` 指向临时空目录。PersonaMem-v2 revision `ed956dea41521fc4499acbc63f966e0fd3c053ba`，5,000 个测试 case，规则与 FTS 各运行一次：

| 检索模式 | Case pass | Memory precision | Recall | Pollution | Mode accuracy | Forbidden activation | 检索 P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rule | 5000/5000 | 33.4% | 100.0% | 66.6% | 98.1% | 0/1558 | 43.8295 ms |
| FTS | 5000/5000 | 33.4% | 100.0% | 66.6% | 98.1% | 0/1558 | 30.5386 ms |

这里的 100% 是现有 PersonaMem runner 的用例通过率，不是 memory precision，也不证明从对话到晋升记忆的端到端召回。Rule/FTS 是不同检索消融，不能混并。两份隔离原始 JSON 的 SHA256、run fingerprint 与完整可用指标见 baseline lock；原始逐条结果不提交。

完整四模式基线**未完成**：历史报告引用的 11,115 向量 fixture 不在当前工作区，embedding/hybrid 标记 `NOT RUN`；未探测或启动 embedding 端点。LoCoMo 本地缓存 `--check` 通过，PersonaMem 缓存 `--check` 通过，但本包未启动 LoCoMo 模型/judge 回归；历史结果仍是历史参考。

## 合同校验和手算

- Python 3.12.14 + `jsonschema 4.26.0` 检查全部 6 个 Draft 2020-12 schema，且 registry 的 14 条目验证通过。
- actor-only 正例通过；在顶层注入 `gold` 或 `source_label` 均被关闭对象 schema 拒绝。有效指标通过；`status=scored` 且分母为零被拒绝；`not_run` 带理由通过。
- 手算混淆矩阵：gold `[SILENT,SILENT,SPEAK,SPEAK,SILENT,SPEAK]`、prediction `[SILENT,SPEAK,SPEAK,SILENT,SPEAK,SILENT]`，得 TP=1、FP=2、FN=2、TN=1，SPEAK F1=1/3、SILENT F1=1/3、Macro-F1=1/3、FIR=2/3、MIR=2/3。
- 窗口例：候选 A 的窗口 [3,4] 且首次呈现 turn 3 为命中；候选 B 窗口 [3,4]、首次 turn 2 为过早；候选 C 窗口 [3,4]、首次 turn 5 为过晚。三候选均计入分母 3，hit=1/3，early=1/3，late=1/3。

## 命令和结果

- `python scripts/fetch_locomo.py --check` — exit 0；缓存 SHA256 与 registry 一致。
- `python scripts/fetch_personamem.py --check` — exit 0；缓存 SHA256 与 registry 一致。
- PersonaMem rule 与 FTS 原样运行 — 两者均 exit 0；5000 个用例完成，报告哈希见 baseline lock。Python 输出有 `runpy` 已导入模块警告，不影响退出结果；报告内未记录总墙钟时间。
- JSON Schema/registry/actor隔离/空分母验证 — exit 0。
- `python scripts/check_docs.py` — exit 0；127 files / 1361 local links / 577 anchors / 0 errors。
- `git diff --check` — exit 0。
- 提交前 GitNexus `detect-changes --scope all` — 3 tracked files / 3 symbols / 0 processes / LOW。`scope=compare --base-ref main` — 312 files / 2637 symbols / 113 processes / CRITICAL；这是累计分支风险，未豁免。GitNexus 的 diff 索引不含尚未跟踪的新合同文件；本包没有改动业务代码。

G0 的双 fixture 逐事件回放、坏哈希/异指纹续跑/零样本拒绝、计数守恒须由 B01 runner 完成；本包只冻结这些要求，不把 schema 校验误报为 G0 通过。B01 继续接入适配器和隔离 CLI。
