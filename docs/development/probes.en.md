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

The evaluation dataset for the retrieval layer is in `memory/benchmark/`:

```bash
python -m memory.benchmark                        # rule-only
python -m memory.benchmark --verbose              # Per-case details + score breakdown
python -m memory.benchmark --embedding-fixture memory/benchmark/_fixtures/embeddings_xxx.json
python -m memory.benchmark --compare              # rule-only vs embedding comparison
```

Core metrics: Memory Precision, Recall, Forbidden Activation (target approximately 0), Pollution Rate, Mode detection accuracy, and Behavior Guard Hit.

See the existing JSON files for the case format. `_fixtures/` stores vector data and consolidation positive-case baselines and is not loaded as retrieval cases.

```bash
python scripts/build_embedding_fixture.py    # Build the vector fixture (requires an embedding service)
python scripts/probe_embedding.py            # Probe embedding service availability
```

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
