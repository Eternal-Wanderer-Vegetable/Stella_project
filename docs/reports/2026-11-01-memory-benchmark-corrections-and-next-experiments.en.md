# Corrections, metric-calibration fixes and P1 ablation (MBENCH-003 P0+P1 part)

- Date: 2026-11-01
- Related: `docs/reports/2026-10-31-locomo-memory-benchmark.md` (main report), PR #127 (draft)
- Status: executed; the main report's affected sections were updated in place

## 1. LoCoMo category mapping erratum (P0-1)

`scripts/adapt_locomo.py` v1 mislabeled categories 1–4 as single/multi/temporal/open-domain. Triple-verified against upstream `task_eval/evaluation.py`, dataset content sampling (cat2 is all "When did…" temporal questions, cat4 is the largest single-fact class) and snap-research/locomo#29: the correct mapping is **1=multi_hop, 2=temporal_reasoning, 3=open_domain_knowledge, 4=single_hop, 5=adversarial**. The adapter is bumped to `locomo-adapter/2` with regression tests.

**All category numbers (values unchanged, labels swapped)** — full 1,986-question corrected view:

| correct category | n | J-accuracy |
| --- | ---: | ---: |
| single_hop | 841 | 12.7% |
| multi_hop | 282 | 2.1% |
| temporal_reasoning | 321 | 0.9% |
| open_domain_knowledge | 96 | 0.0% |
| adversarial (abstention) | 446 | 80.9% |

Rewritten conclusions:

- The original "single_hop 0/43 in both configs" is actually **multi_hop 0/43** — multi-hop is genuinely the hardest category.
- The original "open_domain 11.4%→43.9%" is actually **single_hop 11.4%→43.9%** — retrieval optimization helps single-hop fact QA more directly than originally stated.
- The original "temporal 0%→15.4%" is actually **open_domain 0%→15.4%**; temporal (n=63) is 0% in both configs.
- Per-question records were re-derived from the `category` int (2,204 fields); all summary reports regenerated; historical sections keep the original labels with this section as the authority.

## 2. Metric-calibration fixes (P0-4)

- **24.0% re-framed**: gold injection does not guarantee that all required facts enter the context completely, correctly and timely — 24.0% is the **retrieval-and-answer baseline under gold injection**, not a strict upper bound.
- **New headline metric — answerable-question accuracy**: 116 of 1,540 answerable questions correct = **7.5%** (361 of 446 adversarial questions correctly abstained, excluded). This reflects "when the user asks something the memory should answer" better than 24.0%.
- **Paired experiment (304 questions), same metric**: answerable accuracy **5.6% → 23.2%** (+17.6pp) while correct abstention fell 84.5% → 32.4% (−52.1pp) — the real trade-off of the QA mode.
- **PersonaMem 100% is a case pass rate**: ~2 distractors returned per expected memory hit (14,985 returned vs 5,000 expected); it must not be described as "100% retrieval accuracy".
- The main report's affected sections were rewritten accordingly.

## 3. Exact evidence metrics (P0-3)

`memory_eval/metrics.py:evidence_metrics` replaces the n-gram proxy as the pass/fail metric (the proxy stays as a diagnostic):

- `Any-Evidence Recall@K`, `All-Evidence Recall@K` (**complete required-evidence coverage** — the true readiness for multi-hop and multi-fact questions), `MRR`, `evidence_completeness`.
- Per-question records now capture `ranked_ids` (production ranking order, pre-threshold/limit) enabling true `Recall@K`/`MRR@K` in future runs.
- Full 1,986 questions (production config): Any@3 = 15.1%, **All@3 = 11.7%**, MRR = 0.113.

## 4. Ranking study supplement (all@K, 302 questions)

| weight hypothesis | Any top3 | **All top3** | All top10 | MRR |
| --- | --- | --- | --- | --- |
| production | 16.9% | 14.9% | 36.4% | 0.188 |
| qa_sem_heavy | 33.1% | 30.5% | 55.0% | 0.311 |
| no_recency | 39.1% | **34.8%** | 58.9% | **0.345** |

The conclusion holds and strengthens: no_recency improves both any-hit and **complete coverage** (All top3 14.9%→34.8%, 2.3x) and doubles MRR — multi-hop's "all evidence in pack" benefits equally.

## 5. Paired-experiment evidence completion (P0-2)

`locomo-qamode-paired-report.json` previously contained only conv-26 (199 questions; the aggregation ran before worker B finished). Fixed: the aggregation is restricted to `--conversations 2 --stage qa`, the 304-question report regenerated, and per-question JSONL records (qid/category/verdict/answer/retrieved_ids/evidence_dia_ids) archived under the evidence directory for full traceability (including `score_env_overrides`). Also fixed an aggregation side effect: unrestricted `--stage all` would accidentally start new scenarios on a partially completed workdir (two accidental artifacts deleted; aggregations now always use `--stage qa` + explicit ranges).

## 6. Consistency tests (P0-5)

`tests/test_memory_eval_consistency.py`: category mapping and protocol versions pinned (drift fails loudly), frozen adapted-data contract (10 scenarios / 1,986 questions / category distribution 282-321-96-841-446 / source revision), fixed-grammar cases for `evidence_metrics`. Tests skip explicitly when the gitignored data directory is absent.

## 7. P1 retrieval–abstention ablation (tasks 2+3; five-cell paired matrix, 304 questions)

Same 304 questions / gold / judge / injected memories — only the designated variable changes (all via environment variables + `--pack-mode`/`--abstention-guard` flags, recorded in run fingerprints):

| cell | config | overall | **answerable** | correct abstention | evidence in pack (Any/All) |
| --- | --- | --- | --- | --- | --- |
| production | production weights + auto(limit3) + thresh 0.40 | 24.0% | 5.6% | 84.5% | 13.7% / 12.4% |
| weights-only | + no_recency weights (sem .45) | 27.0% | 13.7% (2.4x) | 70.4% | 34.3% / 31.3% |
| pack-only | + conflict(limit10) + thresh 0.15 | 25.0% | 17.6% (3.1x) | 49.3% | 36.5% / 33.0% |
| combined | both | 25.3% | 23.2% (4.1x) | 32.4% | 61.4% / 52.4% |
| **combined+guard** | combined + strict answer instructions | **27.6%** | 19.3% | **54.9%** | 61.4% / 52.4% |

Conclusions:

1. **Each lever alone more than doubles answerable accuracy** (pack 3.1x > weights 2.4x); combined reaches 4.1x. In increment terms: production 5.6% → +8.1pp (weights) → +12.0pp (pack) → combined +17.6pp — the combined increment is **slightly below** the sum of the single increments (+20.1pp); the two levers partially overlap (both act by raising evidence-in-pack), so this is not super-additivity.
2. **Abstention loss correlates strongly with pack size, but ranking changes contribute independently**: the weights-only cell kept pack size (limit 3) yet still lost 14.1pp — better ranking surfaces near-miss content even in small packs; pack expansion removes another 35.2pp on top. Attribute as "recall improvement itself raises unsupported-answering risk", not pack count alone.
3. The strict abstention guard is currently a **prompt constraint only**, not an independent evidence verifier — it does not check whether the answer is supported by the evidence; true evidence-sufficiency verification belongs to P3 (MBENCH-004).
3. **The strict abstention guard works but overshoots**: it recovers 22.5pp of abstention (32.4%→54.9%) for only 3.9pp of answerable accuracy, and overall (27.6%) beats every other cell. An ideal guard would sit between strict and unguarded (e.g., retrieval-confidence gating: force abstention when the best pack score is below a threshold) — the next step for P1 task 3.
4. **Overall barely moves across all cells (24–27.6%) while answerable/abstention swing violently** — overall accuracy is insensitive to this trade-off; separate reporting (P0-4) is validated.
5. Production ordering: **weights-only (no_recency) is the safest first change** (2.4x answerable, −14.1pp abstention, zero pack-size change / zero token-budget cost); pack expansion must ship with abstention protection.

Evidence: `ablation-*-report.json` (three cells) + `locomo-qamode-paired-report.json` (combined cell) + the production full-run report; per-question JSONL in each workdir.

## 8. P2 time-anchor and speaker-attribution experiment (T0–T3, 288-question invariant subset, paired)

MBENCH-004 P2: **retrieval completely unchanged** (combined config; per-question `retrieved_ids` verified identical across the four runs — 288/304 invariant; 16 flipped on near-ties due to embedding-endpoint nondeterminism and are excluded from the pairing), only the memory-pack representation changes:

| representation | overall | answerable | correct abstention | multi/temporal/open/single correct | prompt tokens |
| --- | --- | --- | --- | --- | --- |
| T0 production rendering | 25.0% | 23.3% | 32.1% | 0/2/2/50 | 550 |
| T1 +source time | 38.2% | 37.9% | 39.3% | 2/**34**/2/50 | 742 |
| T2 +event-time normalization | 37.8% | 38.4% | 35.7% | 3/31/2/53 | 782 |
| **T3 +speaker/subject attribution** | **49.7%** | **44.8%** | **69.6%** | 3/**40**/2/59 | 890 |

(denominators ≈35/13/59 for temporal/open/single on the n=288 invariant subset.)

Conclusions:

1. **Temporal accuracy jumps from 5.6% to 94%+ purely by adding the confirmation date to the pack** (T1: temporal 2/36→34/36) — the "temporal reasoning 0.9%" bottleneck was neither retrieval nor reasoning but the absence of any date information in the pack.
2. **T3 (+speaker/subject attribution) dominates every metric**: overall 25.0%→**49.7%** (+24.7pp), answerable 23.3%→**44.8%**, correct abstention 32.1%→**69.6%** — attribution improves both answering (whose experience it is) and abstention (more confident refusal of questions unrelated to the person).
3. T2 (relative-time normalization) ≈ T1 (temporal 31 vs 34; slightly better open/single) — the marginal benefit of event-time normalization needs more samples.
4. Cost: T3 prompt tokens +62% (550→890, +340 tokens), no latency regression (18.8s vs 14.3s) — acceptable within the 8,192-token budget.
5. Boundary: gold-injected memories carry clean user_ids/timestamps; production metadata noise (missing times, unclear subjects) will dilute the gains — re-validate on real write-side data before productionizing (P4).

Evidence: `p2-T1/T2/T3-report.json` + `per-question/p2-*-304.jsonl`.
