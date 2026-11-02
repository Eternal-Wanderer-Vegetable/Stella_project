# Memory reliability stack tuning runbook (MBENCH-004 validated stack rollout and rollback)

- Applies to: branches containing PR #127 (MBENCH-002..004); flags defined in `config/settings.py`
- Basis: P4 unseen-data validation (docs/reports/2026-11-02-mbench004-p4-production-validation.en.md;
  1,682-question paired run: overall 24.0%→50.6%, answerable 7.9%→39.2%, abstention 80.3%→90.4%)

## Validated improvement stack (recommended enable order)

Every item has an independent switch; **all default off** (production behavior unchanged).
Enable one at a time and observe before the next.

| # | config (.env) | value | effect | single-item gain (paired) | risk |
| --- | --- | --- | --- | --- | --- |
| 1 | `MEMORY_SCORE_W_RECENCY` | `0` | de-bias recency in ranking | answerable 2.4x; abstention −14.1pp | recent-fact questions may hit slower |
| 2 | `MEMORY_SCORE_W_SEMANTIC` | `0.45` | raise semantic weight (pairs with 1) | effective with 1 | — |
| 3 | `MEMORY_SCORE_MIN` | `0.15` | lower pack threshold + `MEMORY_LIMIT_*` (conflict tier 10) | answerable 3.1x; abstention −35.2pp | **bundle with 4** (polluted pack without abstention protection) |
| 4 | `MEMORY_SUFFICIENCY_GUARD_MODE` | `shadow` → `enforce` | content-level abstention gate (ROLE_EXTRACT judge) | enforce: answerable 20.2%, abstention 59.2%, overall 29.3% (best cell) | +1 EXTRACT call per turn; auto fail-open on budget exhaustion |
| 5 | `MEMORY_PACK_METADATA_MODE` | `full` | pack rendering adds confirmation time/attribution | temporal 2/36→34/36 (P2); +13% budget | production metadata noise dilutes gains |

> 1–3 are pure .env changes (restart to apply); 4–5 need this PR's code (merged, flags default off).

## Recommended combination (the P4-validated stack)

```dotenv
MEMORY_SCORE_W_RECENCY=0
MEMORY_SCORE_W_SEMANTIC=0.45
MEMORY_SCORE_MIN=0.15
MEMORY_SUFFICIENCY_GUARD_MODE=enforce
MEMORY_PACK_METADATA_MODE=full
```

P4 unseen-data measured (1,682 questions): overall **50.6%**, answerable **39.2%**, correct
abstention **90.4%**, prompt tokens p95 1,065 (13% of the 8,192 budget), latency p95 32.6s.

## Gray-rollout order

1. Enable 1–2 only (zero pack-size change), observe ≥3 days;
2. Set 4 to `shadow` and observe verifier verdict distribution (`ctx.memory_sufficiency` /
   memory_trace.sufficiency) for ≥3 days;
3. Switch 4 to `enforce`, enable 3 and 5;
4. On any anomaly, roll back only that step (flags are independent).

## Rollback conditions

- Answerable or correct-abstention rate regresses **>5pp** vs the pre-flag baseline
  (P4 report §P4-6) — revert the corresponding flag;
- Enforce mis-gates real users → `MEMORY_SUFFICIENCY_GUARD_MODE=shadow` (keep observing);
- Full-stack rollback = restore defaults for all five keys (delete lines 1–3, set 4–5 to `off`).

## Boundaries and known limitations

- Validation corpus is English (the LoCoMo Chinese contrast set measured 23.0% vs English 24.0% —
  equivalent, but production Chinese corpora are not gray-validated yet);
- Score gating has no discriminative power under gold injection (B2 null result) — retest only on
  realistic sparse pools;
- P1 evidence-contract expansion (21% offline recall ceiling on the write side) is not
  productionized — real write-side end-to-end (P4-3) is its follow-up acceptance item;
- The judge shares the model family with the answerer (Strata): human review list at
  `docs/reports/evidence/memory-benchmark-locomo/p4-judge-review-sample-30.jsonl` pending audit.
