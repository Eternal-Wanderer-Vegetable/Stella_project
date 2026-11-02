# MBENCH-004 P1 stage report: evidence-contract offline contrast (A0–A3)

- Date: 2026-11-01
- Branch: `codex/memory-benchmark` (PR #127, draft)
- Status: **P1 isolated evaluation complete**; no production promotion strategy modified (per plan scope)
- Prerequisite: MBENCH-003 P0 corrections (`2026-11-01-memory-benchmark-corrections-and-next-experiments.md`)

## P1-1 Manual annotation sample set (locomo-contract-gold-v1)

Stratified selection of **202 candidates** from three live-funnel databases (en-conv-26 / zh-conv-26 / zh-conv-30, 538 candidates total), annotated item by item. Protocol v1:

| field | values |
| --- | --- |
| label | MUST_CAPTURE 143 / MAY_CAPTURE 40 / MUST_NOT_CAPTURE 19 |
| category | ability_experience 56 / identity_state 39 / preference_habit 34 / plan_intent 33 / other 40 |
| subject | self / children / relationship / other:\<name\> (fact-subject attribution test points) |
| fact_time | current / past / future / unspecified (plan-vs-event, past-vs-current test points) |
| evidence_binding | exact / paraphrase / none |
| anchoring | sample_key + content_sha1 (**no text committed** — CC-BY-NC; joined at runtime from the gitignored candidate pool) |

Generator script `memory_eval/annotation/build_gold_v1.py` (reviewable, replayable). Hard cases deliberately kept: extraction template artifacts ("I am from X"), **questions extracted as candidates** ("靠什么保持动力？"), **praise-of-others misattribution** ("I'm in awe of your courage", subject=other), hypotheticals, fragments.

## P1-2 Offline contrast results (A0–A3, 202 items)

Acceptance configs (acceptance stage only; extraction fixed): A0 = production stereotyped patterns; A1 = extended pattern families (identity/plans/abilities/past events, zh+en); A2 = A1 + semantic filters (conditionals/hearsay/questions/second-person objects/placeholders/too-short values); A3 = A2 + time/subject tagging.

| config | accepted | **MUST recall (143)** | MUST_NOT false accept (19) | precision proxy |
| --- | --- | --- | --- | --- |
| A0 production | 4 | 3 (**2.1%**) | 1 | 75.0% |
| A1 extended patterns | 37 | 30 (**21.0%**) | 2 | 94.6% |
| A2 +semantic filters | 36 | 30 (21.0%) | **1** | **97.2%** |
| A3 +time/subject tags | 36 | 30 (21.0%) | 1 | 97.2% |

- A1 lifts MUST recall **10x** (2.1%→21.0%) with only +1 false accept; A2's semantic filters remove one false accept at zero recall cost (precision proxy 75%→97.2%).
- A3 changes no acceptance decisions and produces fact_time/subject tags (past events are not promoted to current facts) — feeding the promotion lifecycle's temporal fields.

### Cause analysis of the 113 A1-missed MUST items (design input for P1-3)

| cause | n | examples |
| --- | ---: | --- |
| no first-person marker (EN contractions/past tense/gerund subjects) | 43 | "Gonna continue my edu", "I painted that lake sunrise", "Painting's a fun way…" |
| 我-sentences outside A1 pattern coverage | 38 | "我对心理咨询…很感兴趣", "我昨天去了一个互助小组" |
| third-person subjects (用户/Caroline/Melanie/Gina/Jon) | 32 | "Caroline is a transgender woman…", "用户是跨性别女性" |

## P1-3 Verifiable promotion mechanism design (conclusions)

1. **Pattern-anchored acceptance has a structural recall ceiling**: even doubling the A1 families misses the long tail (contractions, past tense, gerund subjects, Chinese colloquial variants). A1's 21% is near the ceiling of the pattern approach without touching the extraction layer.
2. **Subject normalization is the next highest-leverage step**: 32 misses (28% of the misses) would match after normalizing 用户/speaker names to 我; the subject field is also the input of the attribution hard gate (Owner/Subject/Audience).
3. **Semantic filters have the best cost/benefit**: A2 removed one false accept with five rules at zero recall cost — pattern expansion must ship with equivalent filters (negation/conditional/hearsay/second-person object/questions/placeholders).
4. **Recommended P1-3 production path** (per the MBENCH-004 plan, separately scoped): the extraction layer emits structured candidates (subject/predicate/value/time) → acceptance switches from "pattern hit" to "structured-field-to-source-span binding verification" → promotion keeps the candidate-observe-confirm lifecycle with temporal fields for plans/past events. This study's A2 filters and A3 time tags are the rule seeds for that acceptance layer.
5. Scope: this study covers the acceptance stage (extraction fixed); post-promotion retrieval gains are untested; 40 MAY judgments carry subjective elements (protocol v1 defined; reviewable).

## Artifacts

- `memory_eval/annotation/build_gold_v1.py` + `locomo-contract-gold.jsonl` (annotation set, no text committed)
- `memory_eval/contract_study.py` (A0–A3 pure functions, unit-testable)
- Run result: `E:/stella/runs/memory-eval/contract-study-a0a3.json`
- Candidate pool: `memory/benchmark/_public/locomo/annotation/candidate-pool.jsonl` (gitignored, contains source message text)
