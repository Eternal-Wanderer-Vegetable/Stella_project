# 记忆可靠性栈调优 runbook（MBENCH-004 验证栈的灰度与回退）

- 适用版本：分支含 PR #127（MBENCH-002..004）；生效配置见 `config/settings.py`
- 依据：P4 未见数据验证（docs/reports/2026-11-02-mbench004-p4-production-validation.md，
  1,682 题配对：overall 24.0%→50.6%、可回答题 7.9%→39.2%、弃答 80.3%→90.4%）

## 验证过的改进栈（按建议启用顺序）

以下每项都有独立开关；**默认全部关闭**（生产现状不变）。逐项开启、每项观察后再开下一项。

| 序 | 配置（.env） | 值 | 作用 | 单项收益（配对实验） | 风险 |
| --- | --- | --- | --- | --- | --- |
| 1 | `MEMORY_SCORE_W_RECENCY` | `0` | 排序去近期偏好 | 可回答题 2.4x；弃答 −14.1pp | 近期事实类问题可能变慢命中 |
| 2 | `MEMORY_SCORE_W_SEMANTIC` | `0.45` | 语义权重上调（与 1 搭配） | 与 1 联合生效 | — |
| 3 | `MEMORY_SCORE_MIN` | `0.15` | 入包阈值下调 + `MEMORY_LIMIT_*`（conflict 档 10） | 可回答题 3.1x；弃答 −35.2pp | **必须与 4 捆绑**（无弃答保护时污染包） |
| 4 | `MEMORY_SUFFICIENCY_GUARD_MODE` | `shadow` → `enforce` | 内容级弃答保护（ROLE_EXTRACT 判定） | enforce：可回答 20.2%、弃答 59.2%、overall 29.3%（组合格最优） | 每轮 +1 次 EXTRACT 调用；预算耗尽自动 fail-open |
| 5 | `MEMORY_PACK_METADATA_MODE` | `full` | 记忆包渲染追加确认时间/归属 | temporal 类 2/36→34/36（P2）；预算 +13% | 生产记忆元数据噪声会稀释收益 |

> 1–3 是纯 .env 改动（重启生效）；4–5 需本 PR 的代码（已合入，旗标默认 off）。

## 推荐组合（P4 验证的栈）

```dotenv
MEMORY_SCORE_W_RECENCY=0
MEMORY_SCORE_W_SEMANTIC=0.45
MEMORY_SCORE_MIN=0.15
MEMORY_SUFFICIENCY_GUARD_MODE=enforce
MEMORY_PACK_METADATA_MODE=full
```

P4 未见数据实测（1,682 题）：overall **50.6%**、可回答题 **39.2%**、正确弃答 **90.4%**、
prompt tokens p95 1,065（8,192 预算的 13%）、延迟 p95 32.6s。

## 灰度顺序

1. 只开 1–2（零包大小变化）观察 ≥3 天；
2. 开 4 的 `shadow` 观察验证器判定分布（`ctx.memory_sufficiency` / memory_trace.sufficiency）≥3 天；
3. 4 切 `enforce`、开 3 与 5；
4. 任一步骤异常，只回退该步骤（旗标逐一独立）。

## 回退条件

- 可回答率或正确弃答率相对开旗标前基线**退化 >5pp**（P4 报告 §P4-6）——回退对应旗标；
- enforce 误伤明显（真实用户被弃答）→ `MEMORY_SUFFICIENCY_GUARD_MODE=shadow` 保留观察；
- 全栈回退 = 五个键恢复缺省（1–3 删除行，4–5 置 `off`）。

## 边界与已知限制

- 验证语料为英文（LoCoMo 中文对照集 23.0% vs 英文 24.0% 已测等价，但生产中文语料未灰度实测）；
- gold 注入设定下检索分数门控无判别力（B2 零结果）——分数门控只在真实稀疏池复测；
- P1 证据合同扩展（写侧召回 21% 离线上限）未生产化——真实写侧端到端（P4-3）是其后续验收项；
- judge 与作答同源（Strata）：人工复核清单 `docs/reports/evidence/memory-benchmark-locomo/p4-judge-review-sample-30.jsonl` 待抽查。
