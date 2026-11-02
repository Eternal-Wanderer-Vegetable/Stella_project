# MBENCH-004 P1 阶段报告：证据合同扩展的离线对照（A0–A3）

- 日期：2026-11-01
- 分支：`codex/memory-benchmark`（PR #127，draft）
- 状态：**P1 隔离评测完成**；未修改任何生产晋升策略（按计划边界）
- 前置：MBENCH-003 P0 勘误与指标口径（`2026-11-01-memory-benchmark-corrections-and-next-experiments.md`）

## P1-1 人工标注样本（locomo-contract-gold-v1）

从三份 live 漏斗库（en-conv-26 / zh-conv-26 / zh-conv-30，共 538 条候选）分层抽取 **202 条**逐条标注。标注协议 v1：

| 字段 | 取值 |
| --- | --- |
| label | MUST_CAPTURE 143 / MAY_CAPTURE 40 / MUST_NOT_CAPTURE 19 |
| category | ability_experience 56 / identity_state 39 / preference_habit 34 / plan_intent 33 / other 40 |
| subject | self / children / relationship / other:\<名\>（事实主体≠说话者的归属测试点） |
| fact_time | current / past / future / unspecified（计划-事件、过去-现在测试点） |
| evidence_binding | exact / paraphrase / none |
| 锚定 | sample_key + content_sha1（**文本不入库**，遵守 CC-BY-NC；运行时从 gitignored 候选池连接） |

标注器生成脚本 `memory_eval/annotation/build_gold_v1.py`（可复核、可重放）；难点样本专门保留：抽取模板残留（"I am from X"）、**问句被抽成候选**（"靠什么保持动力？"）、**夸赞他人的评价句**（"I'm in awe of your courage"，subject=other）、假设语气、碎片句。

## P1-2 离线对照结果（A0–A3，202 条）

验收配置（只作用于验收阶段；抽取固定）：A0=生产刻板句型；A1=扩展句型（身份/计划/能力/过去事件，中英）；A2=A1+语义过滤（条件/传闻/问句/第二人称宾语/占位符/过短值）；A3=A2+时间/主体标注。

| 配置 | 验收数 | **MUST 召回（143）** | MUST_NOT 误收（19） | 精度代理 |
| --- | --- | --- | --- | --- |
| A0 生产现状 | 4 | 3（**2.1%**） | 1 | 75.0% |
| A1 扩展句型 | 37 | 30（**21.0%**） | 2 | 94.6% |
| A2 +语义过滤 | 36 | 30（21.0%） | **1** | **97.2%** |
| A3 +时间/主体标注 | 36 | 30（21.0%） | 1 | 97.2% |

- A1 把 MUST 召回提高 **10 倍**（2.1%→21.0%）而 MUST_NOT 误收仅 +1；A2 的语义过滤在不损失召回的情况下清掉 1 例误收（精度代理 75%→97.2%）。
- A3 不改变验收数，产出 fact_time/subject 标注（过去事件不升格为当前事实）——为晋升生命周期提供时效字段。

### A1 未命中的 113 条 MUST 归因（P1-3 的设计依据）

| 原因 | n | 例 |
| --- | ---: | --- |
| 无第一人称标记（EN 缩略/过去式/动名词主语） | 43 | "Gonna continue my edu"、"I painted that lake sunrise"、"Painting's a fun way…" |
| 我字句但句型未覆盖 | 38 | "我对心理咨询…很感兴趣"、"我昨天去了一个互助小组" |
| 三人称主语（用户/Caroline/Melanie/Gina/Jon 开头） | 32 | "Caroline is a transgender woman…"、"用户是跨性别女性" |

## P1-3 可验证晋升机制设计（结论）

1. **句型锚定有结构性召回上限**：即使 A1 家族再扩一倍，长尾表达（缩略、过去式、动名词主语、中文口语变体）仍会漏。A1 的 21% 是「不修改抽取层」前提下的模式法天花板附近。
2. **主体归一化是下一个最高杠杆**：32 条（占未命中 28%）只需把 用户/说话者人名 归一化为「我」再匹配即可命中；且 subject 字段是归属硬门禁（Owner/Subject/Audience）的输入。
3. **语义过滤性价比最高**：A2 用 5 条规则零召回成本清掉误收——扩展句型时必须捆绑等价过滤（否定/条件/传闻/第二人称宾语/问句/占位符）。
4. **建议的 P1-3 生产化路径**（按 MBENCH-004 计划，需单独立项）：抽取层输出结构化候选（subject/predicate/value/time）→ 验收层从「句型命中」改为「结构化字段与源消息 span 的绑定验证」→ 晋升沿用候选-观察-确认生命周期并为 plan/历史事件加时效字段。本研究的 A2/A3 过滤器与时间标注可直接作为该验收层的规则种子。
5. 边界：本研究作用域=验收阶段（抽取固定）；未验证晋升后检索增益；标注 202 条中 MAY 40 条的判定含主观成分（标注协议 v1 已定义，可复核）。

## 证据与产物

- `memory_eval/annotation/build_gold_v1.py` + `locomo-contract-gold.jsonl`（标注集，文本不入库）
- `memory_eval/contract_study.py`（A0–A3 纯函数，可单测）
- 运行结果：`E:/stella/runs/memory-eval/contract-study-a0a3.json`
- 候选池：`memory/benchmark/_public/locomo/annotation/candidate-pool.jsonl`（gitignored，含源消息文本）
