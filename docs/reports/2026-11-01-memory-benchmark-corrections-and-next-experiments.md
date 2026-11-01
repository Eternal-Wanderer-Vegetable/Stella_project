# 勘误与指标口径修正（MBENCH-003 P0）

- 日期：2026-11-01
- 关联：`docs/reports/2026-10-31-locomo-memory-benchmark.md`（主报告）、PR #127（draft）
- 状态：已执行；主报告相关段落已同步修正

## 1. LoCoMo 类别映射勘误（P0-1）

`scripts/adapt_locomo.py` v1 把类别 1–4 错标为 single/multi/temporal/open-domain。经上游 `task_eval/evaluation.py`、数据内容抽查（cat2 全为 "When did…" 时间题、cat4 为最大单事实类）与 snap-research/locomo#29 三重核实，正确映射为 **1=multi_hop、2=temporal_reasoning、3=open_domain_knowledge、4=single_hop、5=adversarial**。适配器已升级 `locomo-adapter/2` 并加回归测试钉死。

**受影响的所有分类数字（数值不变，标签互换）**——全量 1,986 题的正确口径：

| 正确类别 | n | J-accuracy |
| --- | ---: | ---: |
| single_hop（单跳） | 841 | 12.7% |
| multi_hop（多跳） | 282 | 2.1% |
| temporal_reasoning（时间） | 321 | 0.9% |
| open_domain_knowledge（开放域） | 96 | 0.0% |
| adversarial（对抗弃答） | 446 | 80.9% |

受影响结论的改写：

- 原文「single_hop 双配置 0/43」实为**多跳 0/43（两配置皆零）**——多跳确实是最难类别。
- 原文「open_domain 11.4%→43.9%」实为**单跳 11.4%→43.9%**——检索优化对单跳事实问答的提升比原表述更直接。
- 原文「temporal 0%→15.4%」实为**开放域 0%→15.4%**；时间推理（n=63）在两配置下均为 0%。
- 逐题记录按 `category` 整数重导出 `category_name`（2,204 行），汇总报告全部重新生成；历史段落保留原标签并以本节为准。

## 2. 指标口径修正（P0-4）

- **总体 24.0% 重新定性**：gold 注入不保证必需事实完整、正确、适时地进入上下文，故 24.0% 是 **「gold 注入条件下的检索与回答基线」**，不是严格性能上界。
- **新增头条指标——可回答题正确率**：1,540 道可回答题中正确 116 道 = **7.5%**（对抗题 446 道中 361 道正确弃答不计入）。这比 24.0% 更能反映「用户真问到该答的问题时」的表现。
- **配对实验（304 题）同口径**：可回答题正确率 **5.6% → 23.2%**（+17.6pp），同时正确弃答 84.5% → 32.4%（−52.1pp）——QA 模式的真实权衡。
- **PersonaMem 100% 为用例通过率**：每命中 1 条期望记忆平均带出约 2 条干扰（14,985 返回 vs 5,000 期望），不得表述为「检索准确率 100%」。
- 主报告的相应段落已同步改写。

## 3. 精确证据指标（P0-3）

`memory_eval/metrics.py:evidence_metrics` 取代 n-gram 代理成为合格判定（n-gram 保留为诊断）：

- `Any-Evidence Recall@K`（命中任一 gold 证据）、`All-Evidence Recall@K`（**全部必需证据覆盖**——多跳与多事实问题的真实就绪度）、`MRR`、`evidence_completeness`。
- 逐题记录新增 `ranked_ids`（生产排序次序，阈值/limit 前），后续运行可计算真 `Recall@K`/`MRR@K`。
- 全量 1,986 题（production 配置）：Any@3 = 15.1%、**All@3 = 11.7%**、MRR = 0.113。

## 4. 排序研究补充（all@K 口径，302 题）

| 权重假设 | Any top3 | **All top3** | All top10 | MRR |
| --- | --- | --- | --- | --- |
| production | 16.9% | 14.9% | 36.4% | 0.188 |
| qa_sem_heavy | 33.1% | 30.5% | 55.0% | 0.311 |
| no_recency | 39.1% | **34.8%** | 58.9% | **0.345** |

结论不变且更强：no_recency 同时改善任意命中与**完整覆盖**（All top3 14.9%→34.8%，2.3 倍），MRR 翻倍——多跳所需的「证据齐进包」同样受益。

## 5. 配对实验逐题证据补齐（P0-2）

`locomo-qamode-paired-report.json` 此前仅含 conv-26（199 题；聚合命令在 worker B 完成前执行所致）。已修复：聚合命令限定 `--conversations 2 --stage qa`，重生成 304 题报告；逐题 JSONL（qid/category/verdict/answer/retrieved_ids/evidence_dia_ids）归档入 evidence 目录，可完整追溯检索配置（`score_env_overrides`）与判分。另修复聚合命令的副作用：不带范围限定的 `--stage all` 会对部分完成的 workdir 意外开启新场景（已删除两处意外产物；聚合一律 `--stage qa` + 显式范围，并写入操作备忘）。

## 6. 一致性测试（P0-5）

`tests/test_memory_eval_consistency.py`：类别映射与协议版本钉死（漂移即红）、适配产物冻结契约（10 场景 / 1,986 题 / 类别分布 282-321-96-841-446 / 源 revision）、`evidence_metrics` 固定口径用例。数据目录缺失时测试显式 skip（gitignored 数据不入 CI）。
