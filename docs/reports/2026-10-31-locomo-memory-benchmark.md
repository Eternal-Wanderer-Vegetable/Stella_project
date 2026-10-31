# Stella 记忆系统公开数据集基准评测（MBENCH-002）

- 日期：2026-10-31
- 分支：`codex/memory-benchmark`（基于 cf63061）
- 状态：基线测量完成；全量 QA 复跑与中文对照集列入 Next
- 计划：`docs/plans/2026-10-31-memory-benchmark-public-datasets.md`
- 来源：ChatGPT 对话「研究Hy记忆」中的 SMB 评测讨论结论（share 6ad2301c）

## Status

**DONE（基线测量）**：`memory_eval` 评测包 + LoCoMo 端到端上界（10 段 / 196 QA）+ PersonaMem-v2 全量检索层对照（5000 例 × 4 模式）+ live 整合漏斗 + 三组分解实验。单测 12 passed；`ruff check .` 全清；`check_docs.py` 通过；`detect-changes --scope all` 的 CRITICAL 来自出站会话既有未提交改动（不豁免，见 GitNexus 段）。**NOT READY / 未做**：live 写侧的端到端全量 QA（写侧瓶颈使其实际信息量低于上界配置，且耗时数小时）、中文翻译对照集。

## 评测设计（摘要）

评测对象是「原始群聊 → 真实摄入 → 真实检索 → 记忆包 → 短答 → LLM judge」全链路，全部在隔离 STELLA_HOME/临时库中进行，生产库零接触。三个配置：

| 配置 | 写侧 | 回答的问题 |
| --- | --- | --- |
| **live 漏斗** | 生产整合+提取 LLM（Strata 8081） | 真实写侧能产出多少可晋升记忆 |
| **oracle+gold 上界** | 机械抽取合同句型（oracle）+ QA 证据轮直接注入（gold） | 写侧完美时，检索+生成能到多少 |
| **分解实验** | 同上 + 单变量改检索配置 | 失败卡在阈值、limit 还是排序 |

判分：LoCoMo 五类 QA，LLM-as-judge（LoCoMo 协议，prompt 版本 `locomo-judge-v1` 固定入库），answer/judge 均为 `qwen3.8-flash-next-iq2_xs @ 127.0.0.1:8081`（温度 0）。数据版本固定：LoCoMo @ `3eb6f2c5`（CC BY-NC 4.0）、PersonaMem-v2 @ `ed956de`（CC-BY-4.0），sha256 入 manifest。

## 结果一：检索层外部对照（PersonaMem-v2 全量）

`python -m memory.benchmark --dir memory/benchmark/_public/personamem/adapted-full --matrix --embedding-fixture <fullset>`（11,115 向量 fixture，现场重建于本地 embedding 端点）：

| 模式 | 通过 | Precision | Recall | Pollution | Forbidden | Mode 检测 |
| --- | --- | --- | --- | --- | --- | --- |
| rule | 5000/5000 | 33.4% | 100.0% | 66.6% | **0 次** | 98.1% |
| embedding | 5000/5000 | 33.4% | 100.0% | 66.6% | **0 次** | 98.1% |
| fts | 5000/5000 | 33.4% | 100.0% | 66.6% | **0 次** | 98.1% |
| hybrid | 5000/5000 | 33.4% | 100.0% | 66.6% | **0 次** | 98.1% |

结论：检索层在「每例 3 条期望记忆 / 9 干扰」语料上是**高召回低精度**工作点（每例召回全部期望、同时带出约 2 倍干扰）；forbidden 硬零保持。四个模式几乎无差异——在池子 20 候选的规模下 embedding 语义分不改变进出（Separation Margin 在 embedding/hybrid 下略变差 −0.1011）。

## 结果二：LoCoMo 端到端上界（oracle 写侧 + gold 注入）

10 段对话、5,882 条消息、金标准记忆 1,425 条注入、每类抽样 4 题（seed 20261031），共 196 QA：

| 类别 | n | J-accuracy |
| --- | --- | --- |
| adversarial（应弃答） | 40 | **70.0%** |
| single_hop | 40 | 2.5% |
| multi_hop | 40 | 2.5% |
| temporal_reasoning | 36 | 0.0% |
| open_domain_knowledge | 40 | 17.5% |
| **总体** | **196** | **18.9%** |

- 记忆包均值 2.37 条 / 466 字符；检索证据覆盖（n-gram 代理）1.495。
- 分场景 accuracy 10%–35%（conv-48 最高 35%，conv-26/49 最低 10%）。
- 读数方式：这是**写侧完美假设下的检索+生成上界**，不是端到端成绩。单跳/多跳只有 2.5%——诊断（结果四）表明瓶颈在检索排序，不在生成（模型在证据入包时能答对，如 smoke 中直接可见）。
- adversarial 70% 弃答正确说明「拒答行为」本身健康；但它同时被可回答题目的普遍弃答稀释——上界配置下 single_hop 的 2.5% 与 adversarial 的 70% 是同一枚硬币的两面。
- 与公开数字（Mem0 等 ≈ 60–70%）不可直接对比：judge 模型、适配方式、注入范围均不同；本报告只做**自我基线**。

## 结果三：写侧漏斗（live 整合，conv-26 全量回放）

真实走 整合（CONSOLIDATION）→ 提取（EXTRACT，两阶段齐全）→ 证据合同 → 晋升，`CONSOLIDATION_LOCAL_MAX_TOKENS=4096` / `MEMORY_EXTRACT_MAX_TOKENS=4096`（reasoning 模型预算调整，已记录）：

```
419 条消息 → 188 条候选（用户A 103 / 用户B 85）→ 0 条 accepted 证据 → 0 条晋升 → 0 条可检索
```

- 提取本身很活跃（188 候选 / 419 消息 ≈ 45%），**全部卡死在证据合同的窄句型验收**：全语料 5,882 条消息中仅 17 条（0.29%）命中 `_SELF_REPORT_PATTERNS` / `_PREFERENCE_*` 的刻板句（自然英语几乎不说「I live in X」「I like X」的完整句式）。
- `_decide_promotion` 的 `verification_status != "accepted"` 一票否决把非句型候选全部挡在晋升之外——这是当前架构的**设计选择**（宁可缺不可错），benchmark 的职责是量化它的代价：在自然会话语料上写侧产出趋近于零。

## 结果四：分解实验（失败卡在哪一环）

以 smoke 集（2 段 / 18 QA / gold 注入）做单变量对照，证据轮进入检索包的比例：

| 配置 | 证据入包 | 可回答题正确 |
| --- | --- | --- |
| 生产配置（auto 模式，hybrid） | 2/14 | 0/14 |
| `--pack-mode conflict`（limit 3→10） | 2/14 | 0/14 |
| `MEMORY_SCORE_MIN=0.15`（0.40→0.15） | 2/14 | 0/14 |

- limit 不是约束（conflict 模式无变化）；阈值也不是单独约束（0.15 无变化）。**排序本身**把近期寒暄记忆排在证据记忆之前：探针显示目标证据行在 39 行候选池内、FTS(OR 语义) 正常、embedding 正常，但 score 0.2607——`sem`（0.35 权重）的区分度不足以抵消 `recency`+`ctx` 对近端会话的加成；阈值与 limit 只是在排序之后继续收窄。
- 推论：QA 型查询需要的是排序校准/查询感知模式（例如问答场景提高 sem 权重或换 QA 头），调阈值/limit 不解决问题。

## 工程交付物

- `memory_eval/` 包：`isolation.py`（隔离回放：临时 DB + 模块 DB_PATH patch + 逐会话批次控制）、`oracle.py`（机械抽取后端，与证据合同共享同源正则）、`inject.py`（gold 上界注入）、`answer.py`/`judge.py`/`metrics.py`/`report.py`/`runner.py`/`__main__.py`。CLI：`python -m memory_eval --workdir ... --stage all --mode hybrid --consolidation live|oracle [--inject-gold] [--pack-mode auto|conflict]`，checkpoint/续跑。
- `scripts/fetch_locomo.py`（pin+sha256+NOTICE，CC BY-NC 4.0 数据不入库）+ `scripts/adapt_locomo.py`。
- `tests/test_memory_eval.py`：12 用例全绿（假后端零网络）。
- 证据与原始报告：`docs/reports/evidence/memory-benchmark-locomo/`（manifest + 各运行 report.json + matrix 文本）。

## 回放方法论备忘（踩坑记录）

- `memory_candidates.first_seen_at` 必须保持墙钟：晋升 TTL 用 `julianday('now')` 比较，回填会让全部候选被判超期 REJECTED（首轮 live 运行 7 条被误杀后修正）。
- 注入记忆按证据所在会话回填时间戳：全部同刻会让 freshness 候选池（LIMIT 20）在同分并列里退化为抽签。
- 逐会话回放需 `env.set_batch_size(len(session))`：阈值检查对 force 同样生效。
- reasoning 模型（gemma-4-e、qwen3.8-flash）max_tokens 必须覆盖隐藏思考，否则 content 为空（`reasoning_content` 承载思考）。
- oracle 候选仅取批内行：整合 prompt 的 overlap 上下文行不在批内，其 span 的证据绑定会被正确拒绝（conv-43 的 1 条 OBSERVING 即此形态）。

## GitNexus evidence and limits

- 编辑前对 `consolidate_group` / `retrieve_memories` 跑 impact 均 UNKNOWN（索引未解析方法名），按门禁以源码清点补证（调用方：ai_gateway.py:1700/2286/4883/5266/5285、pre_processors.py:1139 链等）；本轮零生产代码改动，纯增量。
- `detect-changes --scope all`：7 files / 1 symbol / 800 flows / **CRITICAL**——全部来自出站会话（codex/outbound-send-logging）既有未提交改动（corona/config_api.py、deployment docs 等）的共享 fanout，与既往会话记录一致；基准文件均为新增未跟踪文件，不在图差异内。CRITICAL 保留不豁免，随出站会话收口。

## 已知局限

- LoCoMo gold 约 6% 已知噪声（Penfield Labs 独立审计，2026）；judge 与 answer 同源自评偏差；196 为分类别抽样而非全量 1,986 题。
- 英文域评测：证据合同中文句型覆盖未测；中文翻译对照集列入 Next。
- 回放把数月压成小时级；TTL/recency 与生产存在结构性差异（已按上文备忘缓解）。
- 上界配置的 1,425 条注入记忆规模（每空间 75–182 条）接近生产配额上限（MEMORY_USER_QUOTA=25 的 3–7 倍），检索池压力高于真实生产；这使 18.9% 偏保守。

## Next

1. 全量 1,986 QA 复跑（实测 ~40min/196 题，全量约 6–7h，可过夜）。
2. LoCoMo 中文翻译对照集（固定翻译模型+版本，验证中文句型覆盖）。
3. 检索排序校准实验：QA 查询感知的 sem 权重/模式（结果四的直接后续）。
4. 证据合同句型覆盖扩展评估（对应 Hy-Memory 讨论的 P1 方向，另立课题）。
5. PersonaMem 中文对照集与 32k/128k 聊天历史行（MBENCH-001 延后项）。
