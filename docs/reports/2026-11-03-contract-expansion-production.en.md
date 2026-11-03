# P1 evidence-contract expansion productionization: acceptance family expansion and false-promotion audit (MBENCH-005b / MEMWRT-001)

- Date: 2026-11-03
- Branch: `codex/evidence-contract-expansion` (standalone PR, base main; carries the MBENCH-004 plan's "evidence contract expansion")
- Prerequisite: MBENCH-004 P1 offline contrast (docs/reports/2026-11-02-mbench004-p1-evidence-contract.en.md; 202-sample annotation set `memory_eval/annotation/locomo-contract-gold.jsonl`)
- Status: **isolated evaluation meets acceptance; extraction-model behavior change (needs a live rerun) marked NOT READY**

## Changes

`memory/evidence_contract.py` acceptance-family expansion (exactly mirroring the offline-validated A1+A2, nothing extra):

| statement_kind (new) | predicate family | candidate type | polarity |
| --- | --- | --- | --- |
| identity_state | identity.state / identity.have (+ .en variants) | FACT | positive only |
| plan_intent | plan.intend / want / will / doing (+ en going-to / want-to variants) | **PLAN** (automatically gets the 14-day observing TTL — plan temporal management) | positive only |
| ability_habit | ability.can (+ en can / play variants) | FACT | positive only |
| past_event | past.used_to (+ en used-to / went-to / had variants) | FACT | positive only |

Existing self_report (7 predicates) and explicit_preference are untouched. The kind↔type binding is now table-driven (`_KIND_TYPE_BINDINGS`; original reason names kept compatible).

A2 value filters enter the `assess_candidate` semantic section (all kinds), with new rejection reasons:
- `value_second_person`: value contains 你/您/you — prevents "我喜欢你画画"-style praise being recorded as the speaker's preference (fixes the annotation set's hard-case samples)
- `value_placeholder`: value contains the placeholder X (extraction template artifact shape)
- `value_too_short`: value under 2 characters (fragments)

`memory/extraction_prompt.py`'s contract hard-rules block adds the new family enumeration (verbatim rules per family + "extract first-person statements verbatim" guidance + the "我喜欢你的画" counter-example).

## Acceptance numbers (202-sample annotation set, shipped = production semantics called directly)

| config | accepted | MUST recall (143) | MUST_NOT false accept (19) | MAY accepted (40) | precision proxy |
| --- | --- | --- | --- | --- | --- |
| A0 pre-expansion production | 4 | 3 (2.1%) | 1 | 0 | 75.0% |
| **shipped (this PR's production semantics)** | 35 | **30 (21.0%)** | **1** | 4 | **97.1%** |

- MUST recall improves **10x** (2.1%→21.0%) while MUST_NOT false accepts stay at 1 (the pre-expansion baseline level); precision proxy 75.0%→97.1%.
- False-promotion audit: of the 19 MUST_NOT forbidden samples, 18 remain unaccepted and 1 was already mis-accepted pre-expansion (not introduced here); and **accepted ≠ promoted** — promotion still requires Gate 1 (confidence/occurrence) and quota; the P4 lifecycle safety regression (32 tests) must stay green before merge.

## Explicitly not done (consistent with the offline study)

- ASSESSMENT_VERSION is not bumped: avoids the Rust constant cascade (promotion.rs mirror) + .pyd recompile; family attribution goes through predicate_key (the claim_key hash includes the predicate; provenance is auditable per family); version-level attribution lands with the "structured candidates + span binding" redesign.
- Subject normalization (normalizing third-person subjects to first person) is not done: it needs reliable name resolution; the annotation set's 32 third-person misses are deferred to the structured redesign; the extraction prompt now teaches the model to prefer first-person verbatim extraction to mitigate.
- Extraction-model behavior change (the new prompt makes the model emit new-family candidates) **NOT READY**: needs a live consolidation rerun; this PR only guarantees that when the model emits new-family candidates the server accepts them correctly.

## Tests and gates

- tests/test_memory_evidence_contract.py: positive cases per new family (identity/plan/ability/past accepted) + A2 negative cases (value_second_person / value_placeholder / value_too_short asserted per reason)
- tests/test_extraction_prompt_contract.py: predicate enumeration expanded to 25 (superset pinned) + new kind binding phrase assertions
- Hard-gate regressions: cross_user_isolation / personal_memory_sharing / private_chat_ingress / memory_rust_promotion / memory_cas_contract / candidate_reinforcement all green (no Rust change needed: the semantic contract is Python-only and the version constants are untouched)
- Data files: `memory_eval/annotation/locomo-contract-gold.jsonl` (202-sample annotation, text not committed, sha1-anchored) and `memory_eval/contract_study.py` (A0-A3+shipped contrast harness) landed with PR #127