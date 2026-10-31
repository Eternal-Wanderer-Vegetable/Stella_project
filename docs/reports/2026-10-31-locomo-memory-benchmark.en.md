# Stella Memory System Public-Dataset Benchmark (MBENCH-002)

- Date: 2026-10-31
- Branch: `codex/memory-benchmark` (based on cf63061)
- Status: baseline measurement complete; full-QA rerun and a Chinese translated variant listed under Next
- Plan: `docs/plans/2026-10-31-memory-benchmark-public-datasets.md`
- Source: the SMB evaluation discussion in the ChatGPT conversation "研究Hy记忆" (share 6ad2301c)

## Status

**DONE (baseline)**: the `memory_eval` harness + LoCoMo end-to-end upper bound (10 conversations / 196 QA) + PersonaMem-v2 full retrieval-layer contrast (5000 cases × 4 modes) + live consolidation funnel + three decomposition experiments. Unit tests 12 passed; `ruff check .` clean; `check_docs.py` passed; the `detect-changes --scope all` CRITICAL originates from the outbound session's pre-existing uncommitted changes (retained without waiver, see GitNexus section). **NOT READY / not done**: full-QA run on the live write side (the write-side bottleneck makes it less informative than the upper-bound configuration and it costs hours), and a Chinese translated contrast set.

## Design (summary)

The system under test is the full chain "raw chat → real ingestion → real retrieval → memory pack → short answer → LLM judge", always inside an isolated STELLA_HOME / temp database; the production database is never touched. Three configurations:

| Configuration | Write side | Question answered |
| --- | --- | --- |
| **live funnel** | production consolidation + extraction LLM (Strata 8081) | how many promotable memories the real write side yields |
| **oracle + gold upper bound** | mechanical contract-pattern extraction (oracle) + direct injection of QA evidence turns (gold) | given a perfect write side, how far do retrieval + generation get |
| **decomposition** | same, one retrieval knob changed at a time | is the failure threshold, limit, or ranking |

Scoring: LoCoMo five QA categories via LLM-as-judge (LoCoMo protocol, prompt version `locomo-judge-v1` pinned in the repo); answer/judge model `qwen3.8-flash-next-iq2_xs @ 127.0.0.1:8081` (temperature 0). Dataset versions pinned: LoCoMo @ `3eb6f2c5` (CC BY-NC 4.0), PersonaMem-v2 @ `ed956de` (CC-BY-4.0); sha256 recorded in the manifest.

## Result 1: retrieval-layer external contrast (PersonaMem-v2 full)

`python -m memory.benchmark --dir memory/benchmark/_public/personamem/adapted-full --matrix --embedding-fixture <fullset>` (11,115-vector fixture rebuilt against the local embedding endpoint):

| Mode | Pass | Precision | Recall | Pollution | Forbidden | Mode detection |
| --- | --- | --- | --- | --- | --- | --- |
| rule | 5000/5000 | 33.4% | 100.0% | 66.6% | **0** | 98.1% |
| embedding | 5000/5000 | 33.4% | 100.0% | 66.6% | **0** | 98.1% |
| fts | 5000/5000 | 33.4% | 100.0% | 66.6% | **0** | 98.1% |
| hybrid | 5000/5000 | 33.4% | 100.0% | 66.6% | **0** | 98.1% |

Reading: on this corpus (3 expected memories per case out of 9 candidates) the retrieval layer operates at **high recall / low precision** (all expected memories recalled, ~2x noise carried along); the forbidden hard-zero holds. The four modes are nearly identical — at a 20-candidate pool the embedding channel does not change membership (Separation Margin slightly worse in embedding/hybrid: −0.1011).

## Result 2: LoCoMo end-to-end upper bound (oracle write side + gold injection)

10 conversations, 5,882 messages, 1,425 injected gold memories, 4 sampled questions per category (seed 20261031), 196 QA total:

| Category | n | J-accuracy |
| --- | --- | --- |
| adversarial (should abstain) | 40 | **70.0%** |
| single_hop | 40 | 2.5% |
| multi_hop | 40 | 2.5% |
| temporal_reasoning | 36 | 0.0% |
| open_domain_knowledge | 40 | 17.5% |
| **overall** | **196** | **18.9%** |

- Pack averages 2.37 memories / 466 chars; retrieval evidence coverage (n-gram proxy) 1.495.
- Per-conversation accuracy 10%–35% (conv-48 highest at 35%, conv-26/49 lowest at 10%).
- Interpretation: this is the **retrieval + generation upper bound under a perfect-write-side assumption**, not an end-to-end score. single/multi-hop at 2.5% is a retrieval-ranking bottleneck, not generation (the model answers correctly when evidence enters the pack — visible in the smoke runs).
- The 70% adversarial abstention shows refusal behavior is healthy; it is the same coin as the pervasive abstention on answerable questions under this configuration.
- Not directly comparable with published numbers (Mem0 et al. ≈ 60–70%): judge model, adaptation, and injection scope all differ; treat this as a **self-baseline** only.

## Result 3: write-side funnel (live consolidation, full conv-26 replay)

Real path: consolidation → extraction (both stages) → evidence contract → promotion, with `CONSOLIDATION_LOCAL_MAX_TOKENS=4096` / `MEMORY_EXTRACT_MAX_TOKENS=4096` (reasoning-model budget adjustment, recorded):

```
419 messages → 188 candidates (user A 103 / user B 85) → 0 accepted evidence → 0 promoted → 0 retrievable
```

- Extraction is active (188 candidates from 419 messages ≈ 45%), yet **everything dies at the evidence contract's narrow-pattern acceptance**: only 17 of 5,882 corpus messages (0.29%) match `_SELF_REPORT_PATTERNS` / `_PREFERENCE_*` stereotyped forms (natural English almost never produces the full "I live in X" / "I like X" sentence shapes).
- The `verification_status != "accepted"` hard precondition in `_decide_promotion` keeps every non-pattern candidate out of promotion — a deliberate **precision-first design choice**; the benchmark's job is to price it: near-zero write-side yield on natural conversational corpora.

## Result 4: decomposition (where does the failure bind)

Single-variable contrasts on the smoke set (2 conversations / 18 QA / gold injected); metric = evidence turns entering the retrieval pack:

| Configuration | Evidence in pack | Answerable correct |
| --- | --- | --- |
| production (auto mode, hybrid) | 2/14 | 0/14 |
| `--pack-mode conflict` (limit 3→10) | 2/14 | 0/14 |
| `MEMORY_SCORE_MIN=0.15` (from 0.40) | 2/14 | 0/14 |

- Neither the limit nor the threshold binds: **the ranking itself** places recent small-talk memories above evidence memories. A probe shows the target evidence row inside the 39-row candidate pool with FTS (OR semantics) and embeddings working, but scoring 0.2607 — the `sem` weight (0.35) cannot overcome `recency`+`ctx` boosts for recent sessions; threshold and limit only narrow further after ranking.
- Implication: QA-style queries need ranking calibration / query-aware modes (e.g., higher semantic weight for Q&A); lowering thresholds or raising limits does not help.

## Engineering deliverables

- `memory_eval/` package: `isolation.py` (isolated replay: temp DB + module DB_PATH patches + per-session batch control), `oracle.py` (mechanical extraction backend sharing regexes with the evidence contract), `inject.py` (gold upper-bound injection), `answer.py` / `judge.py` / `metrics.py` / `report.py` / `runner.py` / `__main__.py`. CLI: `python -m memory_eval --workdir ... --stage all --mode hybrid --consolidation live|oracle [--inject-gold] [--pack-mode auto|conflict]`, with checkpoint/resume.
- `scripts/fetch_locomo.py` (pin + sha256 + NOTICE; CC BY-NC 4.0 data never committed) and `scripts/adapt_locomo.py`.
- `tests/test_memory_eval.py`: 12 cases green (fake backends, zero network).
- Evidence and raw reports: `docs/reports/evidence/memory-benchmark-locomo/` (manifest + per-run report.json + matrix text).

## Replay methodology notes (pitfalls)

- `memory_candidates.first_seen_at` must stay wall-clock: promotion TTL compares against `julianday('now')`; backdating makes every candidate look stale and REJECTED (first live run mis-killed 7 candidates before the fix).
- Injected memories are backdated to their evidence session: identical timestamps turn the freshness pool (LIMIT 20) into a lottery among ties.
- Per-session replay requires `env.set_batch_size(len(session))`: the threshold check applies to force as well.
- Reasoning models (gemma-4-e, qwen3.8-flash) need max_tokens that cover hidden thinking, otherwise content comes back empty (thinking lands in `reasoning_content`).
- Oracle candidates are taken from in-batch rows only: overlap-context lines in the consolidation prompt are outside the batch, so their evidence binding is (correctly) rejected (conv-43's single OBSERVING candidate).

## GitNexus evidence and limits

- Pre-edit impact on `consolidate_group` / `retrieve_memories` returned UNKNOWN (index could not resolve the method names); per the gate this was compensated by a source census (callers: ai_gateway.py:1700/2286/4883/5266/5285, pre_processors.py:1139 chain, etc.). This change set touches zero production code — purely additive.
- `detect-changes --scope all`: 7 files / 1 symbol / 800 flows / **CRITICAL** — entirely from the outbound session's (codex/outbound-send-logging) pre-existing uncommitted changes and their shared fanout, consistent with earlier session records; benchmark files are new untracked files outside the graph diff. CRITICAL retained without waiver; it closes with the outbound session.

## Known limitations

- LoCoMo gold carries ~6% known noise (independent Penfield Labs audit, 2026); judge and answer share the same model (self-judging bias); 196 QA are sampled per category, not the full 1,986.
- English-domain evaluation: the contract's Chinese patterns are untested here; a Chinese translated contrast set is listed under Next.
- Replay compresses months into hours; TTL/recency differ structurally from production (mitigated as described above).
- The upper-bound configuration injects 1,425 memories (75–182 per space), 3–7x the production quota (MEMORY_USER_QUOTA=25); pool pressure exceeds real production, making 18.9% conservative.

## Next

1. Full 1,986-QA rerun (measured ≈ 40 min per 196 QA; full ≈ 6–7 h, can run overnight).
2. LoCoMo Chinese translated contrast set (pinned translation model + version) to test Chinese pattern coverage.
3. Retrieval ranking calibration for QA-style queries (direct follow-up to Result 4).
4. Evidence-contract pattern coverage expansion assessment (the P1 direction from the Hy-Memory discussion; separate topic).
5. PersonaMem Chinese contrast set and the 32k/128k chat-history rows (deferred from MBENCH-001).

---

## Addendum (same day): Next-3 ranking calibration study completed

New `memory_eval/ranking_study.py` reconstructs unweighted features from the weighted score parts in `trace.ranked_all` (`sem_parts / 0.35` etc.) and re-ranks the same candidate pools under five weight hypotheses **without touching production code**. Scope: all 302 answerable questions of conv-26+30 (gold-injected DBs); the embedding channel was live throughout (10,700/10,700 rows carried sem parts, no fallback). Evidence: `ranking-study-302q.json`.

| Weight hypothesis | top3 | top5 | top10 | mean best-evidence rank |
| --- | --- | --- | --- | --- |
| production (ctx.25/usg.20/sem.35/rec.10) | 16.9% | 24.5% | 40.1% | 11.68 |
| qa_sem_heavy (sem .70) | 33.1% | 44.4% | 61.9% | 6.40 |
| **no_recency (rec→0, sem .45)** | **38.4%** | **48.0%** | **66.2%** | **5.61** |
| no_ctx (ctx→0) | 26.5% | 34.4% | 53.3% | 8.22 |
| sem_only | 38.4% | 48.0% | 66.2% | 5.61 |

Conclusions (quantified answer to Result 4):

1. **The semantic channel carries signal that the weight mix buries**: sem-dominant weights (qa_sem_heavy) double top3 from 16.9% to 33.1% and halve the mean best-evidence rank (11.68 → 6.40).
2. **Recency is a net harm for QA retrieval**: zeroing rec alone yields the best of all hypotheses (top3 38.4%, +21.5pp).
3. **ctx carries real signal** (removing it drops to 26.5%); no_recency and sem_only being identical shows that on this corpus ctx/usg/conf/imp contribute nothing to *ordering* (injected rows share conf/imp; ctx behaves as a query-level constant) — the effective dimensions are sem and rec only.
4. **Rank-only ceiling**: even the best re-weighting reaches 66.2% at top10, and the production pack (threshold+limit) stays 44/302 (14.6%) because the pack is effectively top-3. Converting top5/top10 recall into usable packs requires **both** a QA-aware mode (sem-dominant, rec→0) **and** a larger limit / lower threshold — the productionization direction for a "QA retrieval mode", to be validated end-to-end.

---

## Addendum (late same day): full 1,986-QA run complete + Chinese contrast set milestone 1

This section **supersedes** the "Next-1 / Next-2 not done" statements above (the original 196-question sampled record is kept as process evidence).

### Full 1,986 QA (oracle write side + gold injection upper bound)

Three parallel workers (`--conversations-from` range split, shared workdir, per-scenario isolation) finished in ~3.5 hours with zero errors:

| Category | n | J-accuracy |
| --- | --- | --- |
| adversarial (should abstain) | 446 | **80.9%** |
| open_domain_knowledge | 841 | 12.7% |
| multi_hop | 321 | 0.9% |
| single_hop | 282 | 2.1% |
| temporal_reasoning | 96 | 0.0% |
| **overall** | **1,986** | **24.0%** |

- 15 unparseable / 0 errors; per-conversation accuracy 19.4%–30.6%; pack averages 2.28 memories / 440 chars.
- The full-population number is 5.1pp above the 196-question sample (18.9%), mainly from open_domain (12.7%) and adversarial (80.9%) regressing with larger samples.
- The judging protocol was uniform throughout (thinking judge, temperature 0); the `/no_think` soft switch proved ineffective on this model (latency unchanged) but verdict agreement was 18/18 — kept as a future speedup option.

### Chinese contrast set milestone 1 (`scripts/adapt_locomo_zh.py`, protocol locomo-zh-v1)

conv-26 + conv-30 session-by-session translation (788 messages, cache resumable per dia_id), live consolidation funnel:

| | English (same conversations) | Chinese |
| --- | --- | --- |
| messages | 788 | 788 |
| candidates | same order of magnitude (188+161) | **350** (extraction rate 44%, matching English) |
| accepted evidence | 0 | 0 (1 CONFIRMED by status) |
| **promoted memories** | **0** | **1** ("我喜欢古典音乐", a genuine preference) |
| contract pattern coverage | 17/5,882 (0.29%) | **15/788 (1.9%)** |

Conclusion: **the evidence contract's narrow-pattern bottleneck is language-independent** — natural Chinese likewise almost never produces complete stereotyped "我住在X / 我喜欢X" forms. Two noteworthy details: ① Chinese coverage (1.9%) is ~6x the English rate (0.29%) but the samples include **semantic false positives** (e.g., "我喜欢**你**用艺术讲述自己的故事" praises the other person, mechanically matched by the pattern); ② the single promoted Chinese memory is a genuine preference. This is direct evidence that pattern expansion must introduce semantic constraints at the same time.

### Implications for the next phase

- Retrieval side: ranking calibration (previous section) + a QA mode (sem-dominant, rec→0, larger limit) is the shortest path from the 24% upper bound upward.
- Write side: the pattern-expansion assessment (Next-4) now has a **bilingual baseline**: EN 0.29% / ZH 1.9%, with the comparison protocol ready.
- Chinese end-to-end (milestone 2: QA translation + full chain) data is ready (`adapted-zh` scenarios + conv-30 funnel); the next session can continue directly.
