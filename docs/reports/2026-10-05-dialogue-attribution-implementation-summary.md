# Dialogue Attribution Recurrence Repair - Implementation Summary

**Branch**: `feat/dialogue-attribution-role-repair`
**Date**: 2026-10-05 (revised after review)
**Status**: Review findings F1-F13 rework **code-complete** (P0-P7); P8 acceptance (model replay, native parity, QQ gray) **pending user execution**

> 更正说明（2026-10-05 复核后）：本文件旧版宣称 "All phases R0-R8 completed"，
> 与复核报告 [2026-10-05-dialogue-attribution-plan-execution-review.md](2026-10-05-dialogue-attribution-plan-execution-review.md)
> 的 NOT READY 判定不符——旧版把"模块存在/单元测试通过"当成了"计划完成"，
> 且把模型采样/QQ 灰度/native parity 从完成定义里剔除（它们是原计划 R8 出口的
> 一部分，不由实施方单方面宣布豁免）。本版按复核结论重写；整改计划见
> [2026-10-05-dialogue-attribution-review-findings-repair-plan.md](../plans/2026-10-05-dialogue-attribution-review-findings-repair-plan.md)。

## What the original batch (f752538) actually delivered

Per the review: schema v17 structure, the private-chat immediate-ref entry,
some identity negatives, and helper modules — but **not wired into the live
chain** (zero consumers for all three switches), with real defects in sharing
SQL/ownership binding, data repair, and a placeholder reply-plan parser.
25 tests (not "30+"), mostly local-helper positives on simplified DDL.

## Rework commits (this branch, P0-P8 plan)

| Phase | Commit | Findings fixed |
| --- | --- | --- |
| P0 scene fixtures + standalone oracle + prod baseline | plan(attribution): P0 | R0 evidence gap |
| P1 compound self-correction | fix(identity): P1 | F2 |
| P2 idle finalize registered ref | fix(consolidation): P2 | F10 |
| P3 sharing rewrite + schema v18 | feat(sharing): P3 | F3/F4/F5/F13 |
| P4 real plan parser + typed evidence + target-bound bridge | feat(contracts): P4 | F11/F12 |
| P5 runtime wiring (guard hook, proactive contract, sharing entry, projection v5) | feat(runtime): P5 | F1 |
| P6 source-driven data repair with column CAS | feat(repair): P6 | F6/F7/F8/F9 |
| P7 acceptance tests (warm-cache revocation via real retrieval, scene oracle tests, wiring matrix, evaluate --guard) | test(attribution): P7 | review §4 gaps |

## What is still NOT done (user-controlled, required before "completed")

1. **Production-condition model replay** (≥260 final-condition samples, 0
   critical misattribution / 0 unauthorized share / 0 phantom accounting;
   original-error/block/leak rates reported). `scripts/evaluate_dialogue_attribution.py
   --guard` now replays sampled outputs through the enforce-mode guard with
   fixture-derived evidence; production prepare-chain replay uses the frozen
   baseline in `docs/reports/2026-10-05-dialogue-attribution-prod-baseline.md`.
2. **Native parity on schema v18** (cargo test → maturin wheel → explicit
   native-parity run). Python/Rust constants are synced to 18; the wheel is
   NOT built in this batch.
3. **Production data repair** on a backup copy with reviewed previews
   (private_owner_repair → identity_claim_recheck → verified share_grant_apply).
4. **QQ gray release** ≥48h / 200 turns / 20 legitimate proactive
   opportunities.

All three feature switches remain default-off; enabling them before the above
is exactly the anti-pattern the review rejected.
