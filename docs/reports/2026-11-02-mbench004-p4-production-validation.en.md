# MBENCH-004 P4 stage report: unseen-data validation and production-admission assessment

- Date: 2026-11-02
- Branch: `codex/memory-benchmark` (PR #127, draft)
- Status: **P4 evaluation complete; production admission = conditionally approved** (conditions in §5; P4-3 is the open prerequisite)
- Prerequisites: MBENCH-004 P0-P3

## P4-1 Unseen validation set (8 conversations, 1,682 questions)

The full improvement stack (no_recency weights + conflict pack expansion + threshold 0.15 + **T3 pack representation** + **sufficiency verifier**) paired question-by-question against the production baseline (same questions/gold/judge/injected memories, only the config stack changes). These 8 conversations participated in no P1-P3 tuning decision:

| metric | production | P4 stack | change |
| --- | --- | --- | --- |
| **overall** | 24.0% | **50.6%** | +26.6pp (2.1x) |
| **answerable accuracy** (n=1,307) | 7.9% | **39.2%** | **5.0x** |
| **correct abstention** (n=375) | 80.3% | **90.4%** | **+10.1pp (improves too)** |
| evidence in pack | 15.3% | 63.0% | 4.1x |
| paired flips | — | **484 up / 37 down (13:1)** | — |

By category (P4 stack): single_hop 366/727 (50.3%), temporal 99/258 (38.4%), multi_hop 40/239 (16.7%), open_domain 7/83 (8.4%), adversarial 339/375 (90.4%).

**Core conclusion: the improvements hold on unseen data, and all three headline metrics improve simultaneously** — the "recall up / abstention down" trade-off observed in isolation (MBENCH-003) is resolved by the combined stack (attribution metadata in the representation + content-level abstention gating) on the full set. This is not overfitting to one conversation: the paired flip ratio is 13:1 over 1,682 questions.

## P4-2 Same-family judge sampling — sample ready, human review NOT VERIFIED

A balanced 30-question review list (10 correct / 10 wrong / 5 adversarial correct abstentions / 5 boundary) is generated: `p4-judge-review-sample-30.jsonl` (with empty review_label fields). The structural bias of the judge sharing the model family with the answerer is still not quantified by human audit — **this is the only manual step the user needs to complete before merging PR #127**.

## P4-3 Real write-side end-to-end — NOT READY (open prerequisite)

This validation keeps gold injection (the write side is replaced by oracle/gold). P1's conclusion is that extended patterns reach 21% recall at the acceptance stage with semantic filters preserving precision, but **the production promotion strategy is unchanged** (plan scope). Real write-side end-to-end is the first acceptance item after P1 productionization lands (structured candidates + span binding verification, separate PR).

## P4-4 Lifecycle safety regression — PASS

Cross-user isolation / evidence contract / personal memory sharing suites: **32 passed** (zero-tolerance items at zero failures).

## P4-5 Token budget and latency — PASS

Full P4 stack: answer prompt tokens **mean 689 / p95 1,065** (13% of the 8,192 budget); latency **p50 7.9s / p95 32.6s**. The extra costs of the T3 representation and the verifier (+340 per verification call) are included — comfortably within budget.

## P4-6 Production configuration recommendation (for decision; production defaults unchanged)

| item | recommendation | basis |
| --- | --- | --- |
| ranking weights | `MEMORY_SCORE_W_RECENCY=0`, `W_SEMANTIC=0.45` (or query-aware: apply to QA-class queries only) | weights-only alone 2.4x; re-validated in P4 |
| retrieval gate | conflict (limit 10) + `MEMORY_SCORE_MIN=0.15` | alone 3.1x; **must ship with abstention protection** |
| pack representation | **T3 (time + attribution metadata rendering)** | P2: temporal 2/36→34/36; re-validated in P4 |
| abstention mechanism | **sufficiency verifier (B3)**, without strict on top | B3 dominates B1/B4 on all three metrics |
| rollout switches | one independent env flag per item (all already exist), enabled in the order above | clean ablation attribution |
| rollback condition | revert if answerable or abstention regresses >5pp vs baseline | per-question records allow localization |

## Acceptance mapping (plan §P4)

- P4-1 reproducible improvement on unseen data ✓ (overall 2.1x, answerable 5x, abstention +10.1pp same-direction, paired 13:1)
- P4-2 judge sampling: sample ready, human review NOT VERIFIED (user step)
- P4-3 real write-side end-to-end: NOT READY (prerequisite = P1 productionization, separate PR)
- P4-4 isolation/revocation/lineage/failure recovery ✓ (32 tests; **long-run soak and live QQ gray rollout not done**)
- P4-5 token budget and latency ✓
- P4-6 production config and rollback conditions ✓ (this report §P4-6; production defaults unchanged)

## Evidence

`p4-validation-report.json` (merged three-segment aggregation), `per-question/p4-validation-1682.jsonl` (per-question), `analyze_p4.py` (recomputation script), `p4-judge-review-sample-30.jsonl` (human review list). Run directory `E:/stella/runs/memory-eval/p4-validation` (checkpoint-resumable).
