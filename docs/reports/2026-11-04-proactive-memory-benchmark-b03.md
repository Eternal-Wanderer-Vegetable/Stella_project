# 主动参与与记忆 Benchmark B03 — PITCH 时机与虚拟时间

- 状态：**离线时机机制评测完成；G1 仅覆盖本文列出的有限确定性矩阵；整体行为与产品效果仍 NOT READY。**
- 分支：`codex/proactive-memory-benchmark-implementation`；PR #130。
- 数据：PITCH commit `6413b59ac9eca1e056c192a786f059076f91cb74`，MIT；JSON SHA256 `02684a4355eb3bf716fe157a66330d2241233504ebe630b8870f263e08a14471`。官方字段说明与示例见[固定版本数据说明](https://github.com/Social-Futures-Lab/pitch/blob/6413b59ac9eca1e056c192a786f059076f91cb74/data/README.md)。
- 运行报告：gitignored `memory/benchmark/_public/proactive_eval/runs/B03/pitch-window-audit.json`；SHA256 `b259f3311549b3477b91b207e88606472591f588a7c42bb04badd90b411157f1`。报告仅含公开来源 ID、turn 窗口、派生指标及合成时序，不含原对话文本或候选答案。

## PITCH 窗口口径

`proactive_eval.b03` 只把 scorer-side 时机标签与候选 ID 读入审计对象，不构造 actor 输入。全部 **384 个候选 / 35 个 conversation / 1,091 条标注**都保留在分母与逐候选结果中；无交集候选单列原因，不从报告删除。

| 范围 | 有可用时机区间 | 窗口交集 | 无区间 / 交集冲突 | 说明 |
| --- | ---: | ---: | ---: | --- |
| 全部官方 `acceptable_windows` | 384 | 329 | 0 无标注窗口 / 55 交集为空 | 每个区间按 `max(start) <= min(end)`；全体仍为 384 分母 |
| Official union span | 384 | 384 | 0 | `union_window_start/end` 与原区间最外沿逐项一致 |
| Within-group 标注 | 384 有 within-group 标注 | 345 | 10 无有效时机标注 / 29 交集为空 | 次级分母为有至少一个 within-group 时机区间的 374 项 |

1,091 条标注中有 384 条 author 与 707 条 within-group 标注。**37 项**至少含一条 `do_not_surface` 标注，共 **44 条标注**；官方聚合 `ground_truth.do_not_surface` 共识为 0 项。该子集仍单列，不将个体异议改写为共识标签。

确定性时机诊断（所有比率都有显式分母）：

| 放置诊断 | 主 intersection 结果 | 解释 |
| --- | --- | --- |
| Candidate segment start | 命中 4/329（1.22%），提前 325，过晚 0，未放置 0；另 55 项没有非空交集 | 固定元数据起点基线，不是学习策略或产品成绩 |
| Always-silent | 命中 0/329，漏掉 329；另 55 项没有非空交集 | 显示不发言不能通过窗口命中门 |
| Intersection oracle | 命中 329/329；另 55 项没有非空交集 | 使用 gold 起点的非因果诊断上界，不进入候选排名 |
| Source consensus best turn exact match | Candidate segment start 与 source consensus best turn 相同 3/384 | 原生共识点诊断；不是区间替代指标 |

Segment-start 在 union span 口径命中 **16/384**、提前 368；在 within-group intersection 口径命中 **5/345**、提前 340，另有 29 个冲突交集与 10 个无时机标注。37 个含个体 `do_not_surface` 标注的候选中，33 个有全体交集：segment-start 命中 3/33、提前 30，另 4 个交集为空。所有候选级分类均在 ignored JSON 报告中。

## 统一虚拟时间与状态矩阵

新测试驱动把现有 `VirtualClock` 的 UTC 业务时间、虚拟 monotonic 秒与 `call_later` 计时队列一起推进。推进至消息到达时刻时，先处理所有 deadline `<=` 该时刻的 timer，再由回放调用方提交消息。生产 `OpportunityManager`、`ProactiveBudgetStore` 与 `MnemeVerificationStore` 在临时 SQLite 数据库上运行；只通过既有机会 clock 注入和测试侧 UTC 适配器驱动，不修改生产代码。

| 测量 | 结果 |
| --- | --- |
| 当前时序值 | debounce 3 秒、opportunity TTL 15 秒、主动群冷却 600 秒、Mneme 求证默认 deadline 300 秒；均从源码/有效配置读取 |
| 合成密集到达 | 10 turn、1 秒间隔：1 个机会、9 次合并、安静 3 秒后 SPEAK 1 次 |
| 合成 debounce 边界 | 10 turn、3 秒间隔：10 次 timer 都在同一时刻的下一消息前触发；10 个机会、10 次 SPEAK |
| 合成长停顿 | 10 turn、10 秒间隔：10 个机会、10 次 SPEAK |
| TTL 合并 | 每秒消息合并且持续到 15 秒；原 expiry 仍是 15 秒，到期消息创建替代机会，不延长旧机会；替代机会 SPEAK 一次 |
| 预算 UTC | 空桶 R=1 在 3,599 秒仍拒绝，3,600 秒可预留一个 token，容量 1；8 线程并发预留只授予 1 次 |
| 求证 UTC / timer | ACK 时开启实际 300 秒 deadline；未绑定回复不结算；deadline timer 先结算 UNANSWERED/tombstone 并拒绝候选；同刻之后的晚到绑定回复不能复活 |
| 唯一 claim 并发 | 两个并发 attempt 争用相同 scope/subject/claim/evidence，只能有一个 active reserve |
| 生成中话题修订 | 真实 `proactive_speak_impl` 测试桩在生成期间推进 topic revision；旧输出以 `stale_output` 丢弃，发送数为 0 |
| 定时器恢复 | Opportunity 丢失 timer handle 后 `recover_group` 可重设 debounce timer；不把进程内机会恢复冒充成进程重启持久化 |

合成 1/3/10 秒仅描述工程敏感性，**没有映射或换算成 PITCH 秒级标注**。PITCH 的原始标签一直按 turn 评分。现有 Aoede/Mneme 回归另外覆盖 R0、墙钟回退/前跳、预算 settlement/UNKNOWN、发送恢复、第三方/无绑定回复、终态 tombstone、旧证据重放与幂等 CAS。

## 验证命令

- `python -m proactive_eval.b03` — exit 0；384 候选，329 个全体窗口交集，55 个空交集；生成报告与逐候选分类。
- `Draft202012Validator(pitch-window-audit-1.schema.json).validate(report)` — PASS；完整 384 条逐候选结果均符合 schema。
- `python -m pytest tests/evaluation/test_proactive_b03.py tests/aoede/test_virtual_time_opportunity.py tests/aoede/test_opportunity_timing.py tests/aoede/test_frequency_budget.py tests/aoede/test_verification_lifecycle.py -q` — 44 passed，1 条 Python 3.14 `asyncio.iscoroutinefunction` 弃用警告。
- `python -m ruff check proactive_eval/virtual_time.py proactive_eval/pitch_windows.py proactive_eval/b03.py tests/evaluation/test_proactive_b03.py tests/aoede/test_virtual_time_opportunity.py` — 通过。
- 文档检查、提交前 GitNexus all / compare main 与最终工作区证据随 closeout 状态记录补入。

## GitNexus 影响与边界

编辑前影响结果（索引 HEAD `8e6fb26441ba7b91bbf9152d156f5d54739a8544`，GitNexus 1.6.12）：`OpportunityManager` upstream LOW（10 impacted，1 direct importer）；`ProactiveBudgetStore` HIGH（101 impacted，3 direct importer）；`MnemeVerificationStore` HIGH（105 impacted，5 direct importer）；`VirtualClock` CRITICAL（图返回 181 个流程 / 20 模块，并含明显不相关流程）。未编辑这四个生产符号，未用 `riskSharedAxes` 降级或豁免风险。B03 只新增 benchmark adapter、测试时钟驱动、审计报告和隔离测试。

## 未覆盖范围

本包没有执行 actor/model、生成、记忆注入或任何平台发送；没有 QQ/WebChat、真人反馈、模型自然度、生产时机命中率或长时间 runtime 证据。合成机制通过只支持此有限矩阵，不证明任意输入下安全。B04–B08、中文标注、G2–G7及整体 benchmark 仍未完成；B08 仍须用户明确指定真实目标、参与者同意、模型/配置、窗口与回滚动作后再准入。
