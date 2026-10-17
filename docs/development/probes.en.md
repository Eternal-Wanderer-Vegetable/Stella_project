# Probe Scripts

[中文](probes.md) | English · [Documentation](../README.en.md)

Model-side validation does not use pytest (it requires a real local model); use the probes under `scripts/`. **They run the production pipeline**: the same prompt templates, the same parsing logic, and the same candidate validation.

### Consolidation Probe

```bash
# Positive regression baseline: verify that facts are retained when they should be remembered
python scripts/probe_consolidation.py --positive --repeat 3

# Observe real windows
python scripts/probe_consolidation.py --limit 20

# Print only the prompt; do not call the model (offline comparison to check whether formatting changed)
python scripts/probe_consolidation.py --positive --print-prompt

# Observe single-window stability
python scripts/probe_consolidation.py --window-index 3 --repeat 3

# Cover sampling temperature
python scripts/probe_consolidation.py --positive --repeat 3 --temperature 0.0

# Two-stage pipeline (production behavior): stage 1 produces has_self_disclosure, stage 2 extracts candidates
python scripts/probe_consolidation.py --positive --two-stage

# Single-stage comparison (legacy behavior, used to confirm the gain from two stages)
python scripts/probe_consolidation.py --positive
```

**After changing `memory/consolidation_prompt.py`, you must run the two-way gate**:

```bash
python scripts/probe_consolidation.py --positive --repeat 3   # Positive cases must all pass
python scripts/probe_consolidation.py --limit 20              # Fabrication rate must be approximately 0
```

Both must pass for the change to count as successful. Looking at only one side misses regression on the other: loosening capture improves positive cases but may start fabricating, while tightening it can reduce fabrication to zero but miss legitimate facts.

> **Discriminating test for the two-stage pipeline.** The `insomnia_breakfast_noisy` case buries the same self-disclosure information among Bot greetings, a flood of hemerocallis messages, and one-character acknowledgements, reproducing the production failure condition:
>
> | Path | Result |
> |---|---|
> | Single stage (consolidation model) | ❌ 1/2 (misses "insomnia") |
> | Two stages (consolidation model -> main chat model) | ✅ 2/2 |
>
> The other 4 clean cases pass through both paths -- **only the noisy case is discriminating**. After changing `extraction_prompt.py` or adjusting the stage 2 model, this case must remain 2/2; otherwise the two-stage pipeline was pointless.
>
> These two lines in the output are key to failure attribution:
>
> ```
> Stage 1 has_self_disclosure=True/False; stage 2 called/not called
> ↳ The information appeared in the raw output but did not enter the candidate (the model actively discarded it, not that it failed to notice it)
> ```
>
> The first line distinguishes "the small model got the boolean wrong" (stage 2 was never awakened -> change `consolidation_prompt.py`) from "the large model failed to extract" (it was awakened but did not extract it -> change `extraction_prompt.py`). The second distinguishes "not seen" from "seen but actively discarded"; the fixes are entirely different.

### Plugin LLM Probe

The `astrbot_compat` LLM integration surface (plugins calling models, function tools, and multi-turn conversations) uses a stubbed `chat_completion` in pytest. **Only this probe can answer "can it really reach the model" and "will the small model really call a tool":**

```bash
python scripts/probe_astrbot_llm.py                     # All sections
python scripts/probe_astrbot_llm.py chat tools          # Only the specified sections
```

| Section | What it verifies |
|---|---|
| `chat` | `provider.text_chat()` receives a non-empty reply and prints usage |
| `persona` | Three persona states: use the plugin persona when the plugin provides one; inject a plugin-specific persona when it does not; do not send a system message when the configured value is an empty string |
| `stream` | `text_chat_stream()` yields fragments midway and the final yield is the complete text |
| `tools` | Whether `run_tool_loop()` really triggers a function call and repeats the result to the user |
| `budget` | Over-budget context removes the earliest messages in pairs rather than being rejected by the server |
| `conversation` | `ConversationManager` persistence round trip (does not require a model) |

It runs the production pipeline: the gate for the PLUGIN role's endpoint slot in `core/llm/scheduler` (purely local by default, `LOCAL`) -> `core/llm/openai_client.py` -> `StellaChatProvider` -> `run_tool_loop`. Conversation and preference reads/writes point to a temporary database and **do not touch the real database corresponding to `DB_PATH`**.

When the `tools` section fails, first distinguish a pipeline problem from a model-capability problem: a log line such as `Estimated N tokens for request (x messages, 1 tool)` means the tool was sent with the request. If the model still does not call it, the local small model lacks sufficient function-calling capability; try a larger model.

### Sampling Real Windows

```bash
python scripts/sample_windows.py     # Produces windows_raw.json (contains real data and is gitignored)
```

**Beware sampling bias**: the script sorts by `signal_score` (number of long sentences - number of images) in descending order and takes "the first 12 high-signal + 8 medium-signal from the middle + the last 10 flood messages". Therefore `--limit 20` actually runs only the high-signal and medium layers, and **its yield cannot be extrapolated to production**. Use `--stratum` to make the stratum explicit.

This once caused a false diagnosis: the probe produced 3 candidates from 20 windows (10%), while production produced 0 candidates from 985 messages, and this was initially treated as a defect; in reality, the input distributions differed.

### Benchmark

The evaluation dataset for the retrieval layer is in `memory/benchmark/` (hand-written
cases grouped by category directories; `generated/` holds deterministic output from
`scripts/generate_benchmark_cases.py`, byte-identical for the same seed):

```bash
python -m memory.benchmark                        # rule mode
python -m memory.benchmark --verbose              # Per-case details + score breakdown
python -m memory.benchmark --retrieval-mode fts   # Retrieval mode matrix: rule/embedding/fts/hybrid
python -m memory.benchmark --matrix               # Full four-mode matrix (embedding needs a fixture)
python -m memory.benchmark --embedding-fixture memory/benchmark/_fixtures/embeddings_xxx.json
python -m memory.benchmark --compare              # rule-only vs embedding comparison
python -m memory.benchmark --gate                 # Quality gate: non-zero exit on case failure or hard-zero violation
```

Core metrics: Memory Precision, Recall, Forbidden Activation (hard-zero gate), Pollution
Rate, Mode detection accuracy, Behavior Guard Hit; dimension families `dimensions`:
temporal_accuracy, supersede_accuracy, abstain_correct_rate,
**cross_scope_leak_rate (hard-zero gate)**, lineage_completeness; cost section `cost`
(latency percentiles / db size — machine-dependent, observed but never gated).

Report contract and baseline (the basis of the CI quality gate):

```bash
python -m memory.benchmark --report docs/reports/evidence/<dir>   # report + manifest
python -m memory.benchmark --compare-baseline memory/benchmark/_fixtures/baselines/2026-10-16.json
```

- Frozen baselines live in `memory/benchmark/_fixtures/baselines/`: per-metric
  zero-tolerance comparison (hard-zero metrics are forced to zero tolerance; new
  metrics are marked `new` and do not count as drift). After an intentional dataset
  or scoring change, regenerate the baseline and review it;
- `tests/test_benchmark.py::test_baseline_gate_per_metric_zero_tolerance` is the CI gate.

Case format v2 (all optional): `last_accessed_at_offset_minutes` /
`last_confirmed_at_offset_minutes` (relative to the clock anchor), memory `status`
(superseded/archived), `evidence` (lineage declaration); case-level `expect_empty`
(abstain), `expect_evidence` (lineage assertion), `topic` (per-topic aggregation).
Underscore-prefixed path segments (`_fixtures/`, `_public/`, `_replay/`,
`_baselines/`) are never loaded as cases.

```bash
python scripts/build_embedding_fixture.py    # Build the vector fixture (requires an embedding service)
python scripts/probe_embedding.py            # Probe embedding service availability
python scripts/generate_benchmark_cases.py --check   # Frozen-output check for generated cases
```

> **Two empirical findings of the retrieval mode matrix** (2026-10-16, measured with
> zero edits to `memory/retrieval_v2.py`):
> (1) The FTS candidate path never matches natural Chinese queries — `_segment_text`
> turns the whole query string plus sliding-window fragments into MATCH tokens; FTS5's
> implicit AND semantics require the document to contain every token, so retrieval
> always falls back to the freshness path (verify via `retrieval_path.candidate_rows`).
> (2) embedding/hybrid modes only evaluate fixture-covered cases (a case counts as
> covered when its query vector exists); uncovered cases are explicitly skipped and
> accounted. Running them would produce a third semantics ("embedding weights + rule
> semantic fallback") that distorts metrics. The fixture was rebuilt on 2026-10-17
> (259 vectors covering 101/101 cases); rebuilding requires the embedding service
> (`python scripts/build_embedding_fixture.py`; note the local system proxy hijacks
> 127.0.0.1 — set `NO_PROXY=127.0.0.1,localhost`).
> (3) Case offset fields must set `last_confirmed_at_offset_minutes` (ranking reads
> the confirmed column) — offsetting only `last_accessed_at` leaves recency inert;
> rule mode passes on conf/imp margins alone while real embeddings let the semantic
> gap cancel them and activate stale facts (observed in the 2026-10-17 first real
> model acceptance: 7 hard-zero violations, fixed afterwards).

### Rust parity and write-path replay

```bash
python -m memory_rust.benchmark --compare          # Per-case Python vs native comparison
python -m memory_rust.benchmark --matrix           # Four-mode matrix (fts/hybrid are Python-only)
python scripts/eval_memory_replay.py               # Write-path replay (recorded, CI-runnable)
python scripts/eval_memory_replay.py --live --record recorded/new.json   # Offline real model + recording
```

- The parity baseline is **101/101 hard matches** (since 2026-10-16; the old 21/24
  figure is void). Closing it took two steps — the harness fidelity fix
  (`semantic_scores=None` is no longer folded into `{}`; before that both
  implementations ran different scoring semantics) and adding the native-consistent
  canonical tie-break on the Python side (score desc → memory id asc).
  `tests/test_memory_rust_benchmark.py::test_parity_gate_full_dataset` is the gate:
  when the native backend loads, hard mismatches must be 0 with no allowed_diffs;
  a missing native backend skips explicitly instead of faking green.
- The write-path replay runs the production chain (message batching → recorded-clip
  generation → evidence assessment → candidates → promotion → retrieval QA) with
  metrics extraction_hit_rate, fabrication_rate (4-gram source-overlap rule),
  promotion_correctness, qa_accuracy, and memory_delta (with/without memory). The
  gate requires all green plus memory_delta > 0. Suite: `memory/benchmark/_replay/daily-life/`.
  `--live` uses the real assembly (stage 2 resolved from current config); the live
  recording lives at `recorded/live-20261017.json`. **Findings of the 2026-10-17
  real-model acceptance (corrected)**: all three production slots (CHAT/MEMORY/
  VISION) point at Strata :8081 and EXTRACT→CHAT — one model, two roles — is
  configured correctly and stage 2 does run (the earlier "no EXTRACT endpoint"
  warning was an artifact of the evaluation runner hardcoding stage-2 off; fixed).
  The real cause of promotion=0% is a mismatch between stage-2 contract output and
  the narrow acceptance contract: all 4 qwen3.8-flash candidates came back unknown —
  (1) spans carry trailing clauses ("我叫小艾，以后多指教" as the whole content
  fails the rigid-pattern fullmatch), (2) statement_kind/type mismatches (a nickname
  self-report typed PREFERENCE instead of FACT), (3) some contracts unassessed on
  shape. acceptance is the precondition of every promotion path, so with the current
  model ordinary memories never promote; the low-risk fix is prompt-side: require
  minimal rigid-pattern spans without trailing punctuation and FACT typing for
  self-reports, with counter-examples. The fabrication rule (4-gram overlap)
  conservatively misreports paraphrases — read it as a proxy for "no textual
  grounding".

### PersonaMem public dataset (English-domain external reference)

```bash
python scripts/fetch_personamem.py       # HF revision pin + sha256 manifest + NOTICE
python scripts/adapt_personamem.py       # Fixed-seed sampling → retrieval cases (200 rows by default)
python -m memory.benchmark --dir memory/benchmark/_public/personamem/adapted --gate
```

Data (CC-BY-4.0, GPT-5 generated) lands in `memory/benchmark/_public/` (gitignored,
never committed). **Scope limit**: an English-domain external reference; do not
extrapolate to Chinese QQ group-chat retrieval quality. The CI job
`memory-benchmark-public` runs the fixed-seed subset gate; download failures fail or
skip loudly, never silently green.

### Probe Blind Spots

> Probes **directly concatenate window messages into text and feed them to the model**; they do not pass through `record_message` / `group_messages`. Therefore they can verify "whether the model can extract information from messages", **but cannot verify "whether messages were recorded in the database"**.
>
> The defect on 2026-08-17 fell exactly in this blind spot: @ messages were intercepted by a `block=True` listener because of listener priority and never entered the database. All 5 positive probe cases passed, but production had no `AT_MENTION` entries at all, so the content of @ conversations could not be learned.
>
> The persistence path can only be verified in two ways:
>
> ```sql
> -- Startup logs also output this distribution
> SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind;
> ```
>
> And after a real conversation, check for `AT_MENTION source N messages` in the consolidation log. If `AT_MENTION` remains 0 while `BOT_SELF` is greater than 0, persistence has been intercepted.
