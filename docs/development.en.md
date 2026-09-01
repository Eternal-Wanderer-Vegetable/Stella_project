# Development Guide

[中文](development.md) | English

> Note: This version of the document was translated from the Chinese version by GPT-5.6 luna.

This document covers testing, probe scripts, CI, and the contribution workflow. See the [architecture guide](architecture.en.md) for architecture and the [configuration reference](configuration.en.md) for configuration.

## Environment Setup

```bash
git clone https://github.com/Eternal-Wanderer-Vegetable/Stella_project.git
cd Stella_project
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

`requirements-dev.txt` contains development dependencies such as pytest, ruff, and numpy. numpy is used only for vector calculations in the embedding fixture; when it is missing, the relevant tests are skipped rather than failing.

### Developer machine user data lives in `StellaData/`

The `StellaData/` directory under the repository root (globally gitignored) is the local **user data directory** (`STELLA_HOME`):

```text
Stella_project/
  StellaData/          <- your .env, memory database, space configuration, persona, plugin data, and logs
    .env  deploy.answers.toml
    memory/  config/spaces/  system_prompts/  data/  logs/
  bot.py  config/  deploy/  memory/  ...   <- code
```

Rule 4 in `config/home.py` (portable mode) matches it, so the **relative layouts of the repository, release package, and runtime are the same**
they all put data in `StellaData/`; the only difference is which level this directory is attached to.

Existing old working copies (with data scattered at the repository root) are unaffected: Rule 3 in `config/home.py` recognizes the **legacy layout** and uses it in place.
To migrate, move `.env`, `deploy.answers.toml`, `memory/`, `config/spaces/`, `system_prompts/`,
`data/`, and `logs/` into `StellaData/`. All path constants follow `STELLA_HOME`, so no code changes are needed.
`python -m deploy paths` tells you where the current resolution points and which rule was used.

**Do not commit the data directory to the repository**: `.gitignore` contains `StellaData/`, the exclusion list in `release.yml` contains it as well, and `scripts/check_release_layout.py` adds another safeguard before release. All three layers are intentional:
this directory contains the real `.env` and chat history, and once they leave with a release package, they cannot be recovered.

## Deployment Tools

`deploy/` is a deployment tool whose "all checking logic is on the Python side, with the GUI as only a renderer": doctor outputs structured JSON, and the desktop installer (Tauri) calls it and renders the result, so changing GUI frameworks does not require rewriting the logic. It has six subcommands:

| Command | Purpose |
|---|---|
| `python -m deploy doctor [--json]` | Environment self-check; `--json` outputs structured results (`id/level/title/detail/fix_hint`) for the GUI to map to icons and localized strings |
| `python -m deploy init [--answers PATH] [--force] [--dry-run]` | Interactively generates `.env` (replacing lines one by one based on `.env.example`; fetches the model list from LM Studio and selects by number); `--answers` reuses the previous `deploy.answers.toml`, allowing the same answers to be reused for reinstalling on another machine / CI smoke tests / the GUI (`save_config`) |
| `python -m deploy start [--force] [--detach]` | Runs doctor first, then starts `bot.py` if there are no blocking issues (or with `--force`); `--detach` starts it in the background and writes its PID to `logs/stella.pid` (for the GUI) |
| `python -m deploy status [--json]` | Reads the PID file to report whether the process is alive, and infers the latest status from the tail of the JSON log (`link_status` exists inside the Bot process and cannot be read externally) |
| `python -m deploy stop` | Gracefully stops the process: write the stop sentinel -> poll and wait -> fall back to a signal -> use a hard kill as the last resort (see below); the Tauri installer and `bot.py` are in the same release directory |
| `python -m deploy config-schema --json` | Outputs the configuration schema from `settings.py` (groups, defaults, comments), which the GUI uses to generate the "Advanced options" form |
| `python -m deploy migrate [--from OLD_DIR] [--dry-run] [--fresh-runtime]` | Imports user data from an old-version installation directory and upgrades the database; reads the old directory only and writes the report to `migration_report.md` |
| `python -m deploy space-merge --from a,b --to c [--dry-run]` | Merges shared spaces (memory + profiles + FTS + ledger), replacing the sequence of UPDATE statements users previously had to perform manually |
| `python -m deploy paths [--env-file]` | Outputs resolved paths such as the program directory / user data directory; `--env-file` prints only the `.env` path (used by `start.bat`) |
| `python -m deploy manifest [--write]` | Generates the release-package manifest `.stella-manifest.json` (used during upgrades to determine whether the user changed a bundled file); called by release CI |

Layers: `probe` collects data (with side effects) -> `checks` makes decisions (pure functions, the testing focus) -> `report` renders the result.
The criteria used by check functions stay consistent with the actual behavior of ai_gateway (for example, a missing persona file is only a warning in the code, so doctor also reports a warning), avoiding "it runs fine but reports an error" situations.

**Whenever you change `checks.py` or `report.py`, re-export the mock as well** (the frontend/installer uses the real structure for previews, preventing drift between the structure and the backend):

```bash
python -m deploy doctor --json > stella-installer/src/mock/doctor-clean.json
```

`doctor-mixed.json` (the scenario with items) must be constructed manually. Keep its field structure consistent with `doctor-clean.json`, and keep `summary.ok = total - error - warn` internally consistent.

### Stop Sequence (Sentinel First)

1. **The GUI and Bot do not share a console on Windows**: the installer starts the Bot with `CREATE_NO_WINDOW(0x08000000)`, so the child process has no console at all and the `CTRL_BREAK` sent by `GenerateConsoleCtrlEvent` never reaches it (verified in practice). Any stop plan that depends on console events necessarily fails in the GUI scenario; the only reliable entry point for the stop sequence is the file sentinel (`core/stop_signal.py`, default path `.stella-stop-request` at the project root).
2. **The sentinel file has a three-party contract**: deploy writes it (`stop()` in `deploy/process.py`) -> the Bot reads it and kills itself (`ai_gateway.watch_stop_request()` triggers a graceful uvicorn shutdown after observing it) -> the Bot clears leftovers at startup (the earliest action in `_start_stop_watcher`). If any one of the three is missing, the Bot either cannot be stopped or kills itself immediately on startup.
3. **Waiting on the deploy side = grace + buffer**: `_graceful_shutdown()` on the Bot side waits for at most `SHUTDOWN_GRACE_SECONDS(30)`. The deploy-side waiting window must be strictly longer (`STOP_WAIT_BUFFER_SECONDS`, proportional to grace); otherwise it will hard-kill the Bot just as it finishes shutting down, making the wait pointless.

Design trade-off: do not use `POST /shutdown` -- status_api is read-only, and adding a write endpoint would create an unauthenticated write interface. With `HOST=0.0.0.0`, that would become a remotely triggerable shutdown from the LAN; the sentinel is naturally limited to the local user by filesystem permissions.
The sentinel file is a runtime artifact and has been added to `.gitignore`, the exclusion list in `release.yml`, and the sensitive-file checks.

**Frontend contract**: `deploy doctor --json`, `deploy config-schema --json`, and `deploy paths` are the GUI data contracts. When changing their structures, bump the `version` field of the schema and update `stella-installer/src/mock/` at the same time.
`deploy migrate` returns the original Markdown report (the same content is also written to `migration_report.md`; it is generated only once so the two copies cannot diverge), and the GUI renders it directly as monospaced text.

**The GUI must not determine the user data directory itself**: `python::data_root()` asks `deploy paths`. There is only one source of criteria, `config/home.py`; maintaining two implementations would result in "one side reads the old directory while the other writes to the new directory", with symptoms such as "save succeeded but had no effect".

**Two format conventions required by the GUI**:
- Files under `config/spaces/*.toml` written by the installer start with `# Managed by Stella installer`; changing that header or its format affects the GUI's determination of whether the file is "managed by the installer".
- Section comments in `config/settings.py` (`# ---------- TITLE ----------`) determine configuration groups. Keep this format when adding configuration items so the GUI can categorize them correctly (`deploy config-schema --json` is the single source of truth for the grouping result).

## Pre-commit Checks

```bash
python -m pytest tests -q
ruff check .
```

Both must pass. CI runs the same checks, plus on versions 3.10/3.11/3.12.

## Testing

### Running Tests

```bash
# All tests
python -m pytest tests -q

# Single file / single case
python -m pytest tests/test_memory_manager.py -v
python -m pytest tests/test_candidate_reinforcement.py::test_gate1_high_confidence_promotes_immediately -v

# Coverage
python -m pytest tests --cov=core --cov=memory --cov-branch --cov-report=term -q

# Parallel (used by CI)
python -m pytest tests -n auto --dist loadgroup
```

All tests use temporary databases and a fake LLM backend; they **do not depend on a real bot, network, or LM Studio service**.

### Test Inventory

| File | Coverage |
|---|---|
| `test_memory_manager.py` | Basic candidate promotion and observation behavior |
| `test_memory_manager_v2.py` | Conflict detection and persistence of v2 metadata fields |
| `test_memory_manager_fts_sync.py` | Synchronization between the FTS index and the `memories` table; automatic rebuilding of stale indexes |
| `test_candidate_reinforcement.py` | Candidate reinforcement (accumulated evidence), the three Gate 1 tiers, expiration eviction, and quota competition |
| `test_cross_user_isolation.py` | None of the three merge paths may cross users (including reverse cases) |
| `test_consolidator_core.py` | Internal consolidation flow, isolation of unauthorized candidates, and tolerant JSON parsing |
| `test_consolidation_prompt.py` | Anti-fabrication guardrails in the consolidation prompt |
| `test_source_kind.py` | Persistence of source levels and source annotations in prompts |
| `test_bot_self_source.py` | Correct `BOT_SELF` annotation and exclusion from the candidate allowlist |
| `test_context_tail.py` | Short-term context: summary and raw tail coexist, in chronological order |
| `test_short_term_attribution.py` | Speaker attribution for short-term memories |
| `test_policy.py` | Mode detection, three-layer filtering, ranking, and candidate validation |
| `test_retrieval_v2_and_schema.py` | v2 retrieval and schema migration |
| `test_migrations.py` | Regression tests for old-database migrations: the two real starting points, v5 (2.2.0) and v9 (3.0.0), must remain green; add one starting-point case here for every increment of `SCHEMA_VERSION` |
| `test_space_merge.py` | Space merging: every ownership table is rewritten, the more active side wins profile conflicts, `origin_group_id` is retained for undo, and FTS is rebuilt |
| `test_retriever.py` | Retrieval ranking and fallback |
| `test_rag_switches.py` | Combined behavior of RAG switches |
| `test_embeddings.py` | Embedding client, semantic injection, and failure fallback |
| `test_prompt_builder_v2.py` | Partitioned injection and token budget |
| `test_pipeline_compose.py` | Prompt assembly order (instructional intent first, tool-result paragraph position) |
| `test_proactive_rules.py` | Activity statistics and probability curves |
| `test_proactive_state.py` | Quota counting, cross-day reset, and backoff |
| `test_proactive_target.py` | Target selection, quota algorithm, and cooldown checks |
| `test_proactive_at_flow.py` | Accounting and backoff for proactive @ mentions |
| `test_proactive_prompt.py` | Guardrails for proactive @ instructions |
| `test_text_similarity.py` | Behavioral baseline for content similarity and merging |
| `test_compressor.py` | Deduplication and merging, atomization, archiving, and throttling |
| `test_timeutil.py` | Parsing DB timestamps as UTC |
| `test_trace.py` | Decision tracing and statistics |
| `test_benchmark.py` / `test_benchmark_and_log.py` | Benchmark runner and consolidation logs |
| `test_db_cleaner.py` | Dirty-data cleanup and message trimming |
| `test_lm_studio.py` | LM Studio client (retry, abandoning on 4xx, empty replies) |
| `test_llm_registry.py` | Endpoint x role registry: four-slot parsing, three-tier model parsing, gate ownership, and ensuring `describe()` never exposes the API key |
| `test_openai_contract.py` | **Vendor-neutral contract**: the default request body contains only the minimum compliant fields (one extra causes the stub endpoint to return 400), and adaptive retry occurs at most once without consuming the normal retry budget |
| `test_llm_compat.py` | Parameter-difference adaptation matches **error-message keywords**, contains no vendor names (degrading into a vendor allowlist is a failure), and covers the path with `\uXXXX` escaped bodies |
| `test_scheduler_concurrency.py` | Gate concurrency: `1` is textually equivalent to the pre-change `asyncio.Lock`, different endpoint slots run truly in parallel, and unparseable values always fall back to `1` |
| `test_full_workflow.py` | End to end: message persistence -> context -> Pipeline -> output -> consolidation -> promotion + FTS |
| `test_spaces.py` | Space resolution: explicit configuration, persistence of implicit assignments, and conflict handling |
| `test_session_compact.py` / `test_session_context.py` | Non-overlapping ranges during session compaction, and distinct handling of empty results versus failures |
| `test_link_monitor.py` | Link monitoring: heartbeat liveness, active probes, and alert throttling |
| `test_deploy_checks.py` | Doctor decision layer: all checks in a healthy snapshot are ok, every non-ok result has a fix_hint, and `run_all` ordering |
| `test_deploy_init.py` | Wizard validation and rendering (including regression coverage for "preserve template comments verbatim") |
| `test_deploy_process.py` | PID file read/write, process liveness checks, and stop boundaries (using a short-lived child process) |
| `test_logging_sink.py` | Structured JSON logs: valid JSON on every line, complete fields, and truncation of overlong messages |
| `test_graceful_shutdown.py` | Graceful stopping: wait for shutdown, abandon on timeout, and cancellation of the response-check task |
| `test_log_paths.py` | Unified log locations: everything under `LOG_DIR`, the same configuration shared by readers and writers, and deprecated keys still called out by doctor |
| `test_deploy_probe.py` | Doctor collection layer: probe failures never raise, and backend probing after rendering |
| `test_deploy_cli.py` | Output structure of each `python -m deploy` subcommand (the GUI data contract) |
| `test_deploy_migrate.py` | Installer upgrade: `.env` is merged rather than overwritten, the database reaches the current schema, user-modified bundled files are preserved unchanged, and runtime reuse plus marker cleanup |
| `test_stella_home.py` | Data-directory resolution: environment variable takes priority, legacy layout stays in place (database files count too), default is the `data` directory next to the installation directory and is not created in advance |
| `test_release_layout.py` | Release layout: exclusion parsing has no extra quotes, **no user data path may enter the package**, `data/` is excluded everywhere, and including it fails the check |
| `test_env_schema.py` | Grouping and defaults in the GUI configuration form schema generated from `settings.py` |
| `test_env_inherit.py` | Inherited configuration items: `KEY=` (empty value) must fall back to the parent key, while `_env` must not change with it -- the empty value of `LM_STUDIO_API_KEY=` is meaningful |
| `test_env_merge.py` | `.env` merging: `SUPERSEDED` conversion (`LLM_SCHEDULER_GATE_EMBEDDING` -> `MEMORY_EMBEDDING_GATE`), precedence, and idempotence of duplicate merging |
| `test_prompt_cache_prefix.py` | Prefix-cache guard: mutable placeholders in the three memory-chain templates must come after all fixed instructions |
| `test_usage_accounting.py` | Usage accounting and budgets: idempotent UPSERT, rollover of date keys across days, boundary and overage criteria, `pause_memory` pauses only the memory domain while chat remains unaffected, `pause_all` returns silently without raising, `warn_only` never blocks, zero database writes when accounting is disabled, and **the sink also never raises when the database does not exist** |
| `test_cost_gates.py` | Pre-filtering: skipped paths **never advance the checkpoint**, @ slices retain context, lexical criteria cover unavailable vectors, consecutive skips up to the limit force one consolidation, and online/local key selection is correct |
| `test_status_api.py` | Local status interface: loopback checks and payload assembly |
| `test_stop_signal.py` | Writing/clearing the stop sentinel and cleaning up leftovers |
| `test_proactive_gate.py` | The six admission-gate conditions for proactive speech and their reason strings |

Capability layer (`tests/capability/`):

| File | Coverage |
|---|---|
| `test_tasks.py` | Task / Result protocol, errors for cycles and dangling dependencies in TaskGraph, and topological layering |
| `test_registry.py` | Registry merging (no overwriting), first-come-first-served tool ownership, version invalidation, and ensuring the singleton is not shadowed by the package entry point |
| `test_capability_loader.py` | Parsing and fault tolerance for `config/capabilities/*.toml` (a bad file only skips itself) |
| `test_router_rules.py` | Level 0: keywords recognize only explicit declarations, greetings require full-sentence matching, and tool intent does not mean the capability is already determined |
| `test_router_semantic.py` | Level 1: prototypes use the mean, invalidation by registry version/model, and distinction between None and a low score |
| `test_router_cascade.py` | Three-level cascade and fallback: timeout/exception/empty registry all fall back to chat+memory |
| `test_router_benchmark.py` | Regression of the built-in case set, separate counts for four error types, and Provider health backoff |
| `test_comes_summarizer.py` | Summary compression: failed and "no return value" items stay out of the summary, and the budget is divided among multiple tools |
| `test_comes_executor.py` | **Context isolation** (only tools matching a capability enter the request), status determination, direct calls without arguments, and health accounting |
| `test_astrbot_adapter.py` | Automatic derivation, explicit declaration takes priority, and bootstrap order is not interchangeable |
| `test_capability_hooks.py` | Memory gating, two branches running in parallel without impeding each other, and never raising |

AstrBot compatibility layer (`tests/astrbot_compat/`):

| File | Coverage |
|---|---|
| `test_loader.py` | Plugin discovery and loading, metadata parsing, and a bad plugin only skipping itself |
| `test_shim_modules.py` / `test_shim_llm.py` | The fake `astrbot.*` module tree can be imported, and unimplemented parts raise NotSupported |
| `test_filters.py` | Determination of `@command` / `@regex` / permissions / wake-up prefixes |
| `test_events.py` | OneBot events -> AstrMessageEvent, wake-up and administrator checks |
| `test_components.py` | Bidirectional message-segment conversion (including `Json` cards and merged forwards) |
| `test_dispatch.py` | Wake-up model, handler execution, **`should_dispatch`** (cards without plain text must also enter the pipeline, and self-echoes are blocked) |
| `test_render.py` | HTML -> image: options mapping, artifact-directory limit, channel fallback, on-demand installation runs only once and has cooldown, and failures always return None |
| `test_base.py` | Star base class, KV storage, and returning an empty string rather than raising when the rendering entry point is unavailable |
| `test_llm_provider.py` / `test_llm_tools.py` / `test_llm_hooks.py` / `test_llm_budget.py` | Plugin-side LLM: Provider, function-tool loop, lifecycle hooks, and budget trimming |
| `test_request_llm.py` / `test_conversation.py` / `test_config.py` | `event.request_llm()`, conversation history, and plugin configuration schema |

> **Rendering tests stub the browser throughout** (`_FakeBrowser`) and do not start real Chromium -- the CI environment has no engine, and what needs testing is orchestration and fallback, not Chromium screenshot quality. Real image output is verified manually; see `design_docs/test_checklist/`.

### Two Testing Conventions

**Use `monkeypatch`, not `.env`.** Tests must not depend on environment configuration:

```python
monkeypatch.setattr("memory.memory_manager.MEMORY_QUOTA_ENFORCE", True)
monkeypatch.setattr("memory.memory_manager.DB_PATH", tmp_path / "test.db")
```

> Configuration in the capability and astrbot compatibility layers must patch attributes on **`config.settings`**, not `config.X`: `config/__init__.py` is `from .settings import *`, so names are bound at import time. Accordingly, these modules always use `_settings().X` to read values at call time rather than `from config import X`.
>
> The basename of every test file must be unique across the repository (`tests/` has no `__init__.py`); otherwise pytest reports a module-name conflict during collection. This is why the capability-layer loading test is named `test_capability_loader.py` rather than `test_loader.py`.

**Constraint tests must have reverse cases.** Testing only that "something that should not happen did not happen" is insufficient: a condition written as always false would also pass, and the feature would silently stop working. Every "must not merge across users" case in `test_cross_user_isolation.py` is paired with a "must still merge for the same user" case.

## Probe Scripts

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

## Database

```bash
python -m memory.schema --dry-run    # Preview pending migrations
python -m memory.schema              # Run migrations
python -m memory.schema --backup     # Back up only
```

**Migration principle: Additive Migration** -- only add fields and indexes; never delete data. Every `ALTER` is preceded by a `PRAGMA table_info` check and is idempotent and rerunnable. Before the first migration, an automatic backup is created as `stella_memory_backup.db`.

### Correct Way to Add a Column

1. Increment `SCHEMA_VERSION` in `memory/schema.py` by 1
2. Append `(table name, column name, ALTER statement)` to `_ADDITIVE_COLUMNS`
3. Append required indexes to `_INDEXES`
4. **Synchronously update every hand-written `CREATE TABLE` for that table**

Step 4 is a historical pitfall: the `memories` table creation statement once existed separately in `schema.py` / `consolidator.py` / `memory_manager.py` / `compressor.py`, and the `compressor` copy was missed when `source_kind` was added. All code now uses `schema.create_memories_table(conn)`; new tables should follow the same practice.

SQLite's `ALTER TABLE ADD COLUMN` **does not accept a non-constant default**. `DEFAULT CURRENT_TIMESTAMP` fails, so leave the value empty and have the code write it.

### How to Change a Column Name / Primary Key

**New rule (2026-08-27): every increment of `SCHEMA_VERSION` must also include a `migrate_vN` in `memory/migrations.py` and a regression test using an old-database fixture. Never again use "no data migration in this release; archive the old database and rebuild".**

Previously, v7 (profile grouping) and v8 (changing the memory table to use space ownership) both declared that they would not migrate, on the grounds that "the amount of data in the database is small".
However, every publicly released 2.x version used schema v2/v5 (with a `group_id` column), so upgrading existing users meant telling them that all their memories would be lost. This was the most expensive decision mistake in this project. v5 -> the latest version is now fully automatic.

Division of responsibility:

| Module | Responsibility |
|---|---|
| `_migrate()` in `memory/schema.py` | Add columns + create tables + create indexes. Idempotent and independent of the version number; runs as the final step of every migration |
| `memory/migrations.py` | Change structure + transform data. One function and one transaction per version; advance `schema_meta.version` only after success |

Three things you must know when writing a migration:

1. **Determine ownership table by table**. The semantic change in v8 was that the ownership column's value changed from the "real QQ group number" to the "space name", so do not write a script that says "rename every `group_id`". The three table categories are defined by constants at the top of `migrations.py: 4 tables whose names and values change (`memories` / `memory_candidates` / `atomic_facts` / `user_profiles`, plus `memories_fts`, which cannot be ALTERed and must be dropped and rebuilt); `long_term_memories`, whose value changes but whose name does not (the column is still called `group_id`, while its value has long been a space name); and 6 tables whose real-group ownership must not be changed at all.
2. **Space names must match the runtime**. Names written by the migration must equal the value returned for that group by `config.spaces.resolve_space()`. Otherwise retrieval asks `WHERE group_shared_space='casual'` while the row contains `'space_1'` -- no results, no error, and no exception. The only valid criterion is the one reused from `config/space_map.py`.
3. **The transaction must really roll back DDL**. Python `sqlite3` implicitly starts a transaction only before DML by default, while DDL uses autocommit; therefore `run_migrations` sets `isolation_level` to None and manages BEGIN/COMMIT itself.

Changing a primary key still means "create a new table -> copy the data -> rename it". Take the DDL from the canonical constants in `schema.py` (such as `USER_PROFILES_TABLE_DDL`); do not copy it by hand.

### Space Merging

After a user assigns two groups to the same toml, historical memories are still attached to the old space names. **Do not make users type UPDATE statements by hand**:

```bash
python -m deploy space-merge --from space_1,space_2 --to casual --dry-run
python -m deploy space-merge --from space_1,space_2 --to casual
```

It rewrites all tables owned by space, rebuilds FTS, updates the ledger, and handles `user_profiles` primary-key collisions (keeps the copy with the larger `interaction_count`; conflicts go into the report). Merging is **irreversible**; the `origin_group_id` provenance column and the backup made before the operation are the fallback.

### Time Handling

`CURRENT_TIMESTAMP` writes **UTC**. Every place that compares a Python time with a DB timestamp must use `memory/timeutil.py`:

```python
from memory.timeutil import parse_db_timestamp, seconds_since, db_timestamp_str
```

Comparing a DB timestamp directly with `datetime.now()` produces a fixed offset outside the UTC time zone. This bug once made `PROACTIVE_AT_USER_COOLDOWN` completely ineffective in UTC+8 (it was always judged to have passed its cooldown), and it surfaced only in CI's UTC environment.

Comparisons inside SQL (`julianday('now')` versus `julianday(col)`) use UTC on both sides and need no handling.

### Archived Records

After each major refactor, the runtime database is archived to `_deprecated/` (gitignored):

| File | Description |
|---|---|
| `legacy_agent_memory.db` | Early-version runtime database |
| `legacy_agent_memory_2026.db` | Before the v2 schema upgrade |
| `legacy_agent_memory_pre_v4.db` | Before the two-layer filtering refactor (three Gate 1 tiers / candidate reinforcement / quota) |

At startup, a new database is automatically rebuilt under `memory/` using the current schema.

> When archiving an old database, **move `stella_memory_backup.db` along with it**. `backup_database()` skips the backup when one already exists; leaving it behind means a future migration of the new database will not create a new backup -- a state that looks backed up but is backed up incorrectly.
>
> Every versioned migration also writes `agent_memory.db.pre-vN-<timestamp>.bak` (`schema.backup_snapshot`); that is the "state before this migration". `stella_memory_backup.db` is the "first original database ever".

## CI

`.github/workflows/ci.yml` defines four jobs:

| Job | Contents |
|---|---|
| `lint` | `ruff check .` (Python 3.11) |
| `security` | `pip-audit -r requirements.txt` (blocking) + `bandit` (non-blocking; report uploaded as an artifact) |
| `test` | 3.10 / 3.11 / 3.12 version matrix, `pytest tests/ --cov=. --cov-branch -n auto`, and coverage report uploaded as an artifact |
| `notify` | PRs only: summarize status and comment |

`test` depends on `lint` and `security` passing; `fail-fast: false` ensures the other versions continue when one fails. Older workflows on the same branch are cancelled automatically.

**Reproduce the CI environment locally**:

```bash
pip install -r requirements.txt -r requirements-dev.txt pytest pytest-cov pytest-xdist
ruff check .
pytest tests/ --cov=. --cov-branch -n auto --dist loadgroup
```

`pip-audit` is blocking, so CI goes red when an upstream dependency exposes a CVE. If you determine that an upstream issue cannot be fixed immediately, you may temporarily add `|| true` to that step, but record the reason.

**When only 3.10 is red and every test is a collect error, suspect a transitive dependency first.** The direct dependencies in `requirements.txt` are mostly lower bounds (`>=`) and transitive ones are not pinned at all, so any upstream release that supports 3.11+ only turns `test (3.10)` completely red while 3.11 / 3.12 and the dev machine stay green. The 2026-09-01 instance: `pygtrie` 2.6.0 used `typing.Self` (3.11+) at module top level, so `import nonebot` raised `AttributeError: module 'typing' has no attribute 'Self'` and all 622 tests errored. Triage by reading **only the first traceback in the `==== ERRORS ====` section** (the tens of thousands of log lines are all copies of the same one); the fix is to pin that transitive dependency explicitly in `requirements.txt` with the reason written down.

## Release Process

After a tag is pushed, CI (`.github/workflows/release.yml`) automatically packages and publishes `Stella-vX.Y.Z-win64.zip`.

### Checklist Before Tagging

1. `python -m pytest tests -q` is fully green
2. `ruff check .` reports no warnings
3. The version in `pyproject.toml` has been updated (CI compares it with the tag and fails immediately if they differ)
4. If configuration items changed, `.env.example` and `docs/configuration.en.md` are synchronized
5. `release_assets/RELEASE_NOTES_TEMPLATE.md` has been updated with this version's notes, and **breaking changes are listed explicitly** (for example, deprecating all `NAPCAT_*` configuration). Note that "make the user lose data" is no longer a valid upgrade strategy: every increment of the schema must include an automatic migration
6. The Release exclusion list is maintained independently of `.gitignore` (see the comments in `release.yml`); when adding runtime artifacts or configuration files, update both the exclusion list and the sensitive-file-check regex
7. **For every new top-level directory, determine whether it belongs in the Release**: development tools (such as `stella-installer/`, the independently distributed Tauri installer) and tool scripts must not be included in the user installation package. Add them to the rsync exclusion list in `release.yml` and the regex for "checking development directories", then run a manual packaging verification
8. `release_assets/start.bat` hard-codes the Python version and SHA256; when upgrading the Python patch version, update both locations, and for a major/minor version change also check the handling of `python*._pth`

Then:

```bash
git tag v0.x.0
git push origin v0.x.0
```

CI automatically: validates the version -> constructs the release directory (excluding `tests/`, `design_docs/`, `scripts/`, `_deprecated/`, `.github/`, `memory/benchmark/`, etc.) -> copies the four files from `release_assets/` and converts bat/txt files to CRLF -> creates the zip -> creates a GitHub Release.

### Notes on Upgrading Embedded Python

`release_assets/start.bat` **hard-codes**:

- `PY_VER` (such as `3.12.10`)
- `PY_ZIP` (the embed-amd64 package filename, which changes with `PY_VER`)
- `PY_SHA256` (the official checksum from the python.org download page; a wrong value makes installation fail forever)
- The `python*._pth` wildcard in section 6 (`312` in `python312._pth` corresponds to the major/minor version; if the filename no longer matches when changing Python, update it as well)

When upgrading Python, update all four locations together and run `start.bat` completely once locally to verify it (this creates a `runtime/` directory, which is in `.gitignore`).

> **Note**: The Tauri installer's first-install logic in `stella-installer/src-tauri/src/python.rs` (`runtime_bootstrap`) reimplements the same process in pure Rust. `PY_VER` / `PY_SHA256` / download-mirror constants must be changed together with `start.bat`; the installer does not depend on `start.bat`, which is only a fallback manual installation method.

> **Encoding convention**: `.bat` files under `release_assets/` use pure ASCII, with internal comments and output uniformly in English. They are still uniformly converted to CRLF at release time to ensure stable parsing by Windows `cmd`. The user-facing `README-快速开始.txt` may continue to use UTF-8 with BOM.

### Three Required Changes for Embedded Python

The Release package uses the Python Embeddable Package as its runtime. It behaves differently from regular Python in three ways, and both bootstrap paths (command-line `start.bat` and GUI `stella-installer/src-tauri/src/python.rs`) must handle them:

1. **`import site` is commented out by default** (in `python3xx._pth`). Unless it is uncommented, dependencies installed into `Lib\site-packages` cannot be imported at all;
2. **When `._pth` exists, Python builds `sys.path` only from that file**, equivalent to using `-E -s`; relative paths in it are resolved **relative to the directory containing `python.exe`**. The default `.` points to `runtime\` rather than the project root, so `runtime\python.exe -m deploy` reports `No module named deploy` (verified on 2026-08-18). A line `..` must be added;
3. **It contains only the standard library, with no `setuptools` / `wheel`**, and the current `get-pip.py` installs only pip (`setuptools`/`wheel` were removed from its defaults long ago). As a result, any dependency that ships **only an sdist and no wheel** cannot be installed -- pip must import `setuptools.build_meta` to build it, reports `BackendUnavailable: Cannot import 'setuptools.build_meta'`, and the entire dependency installation exits with code 2. `pip install setuptools wheel` must run **before** installing `requirements.txt`.

The first two are handled in the "enable site-packages" section, using the `python*._pth` wildcard to match the filename and avoid missing an update when changing the Python major/minor version. The third is handled by the `Installing build tools` section of `start.bat` and `ensure_build_tools()` in `python.rs`; `tests::both_bootstrap_paths_install_build_tools` pins the two paths together so they cannot drift.

> The third issue was a real incident in the 2026-08-26 v3.0.0 pre-release: `qrcode_terminal` has only a source package on PyPI, so installing dependencies in a freshly unpacked release package inevitably failed. **It cannot be reproduced on a development machine** because its `runtime/` acquired `setuptools` from an old version of `get-pip.py` years ago and has continued to reuse it.

**CI cannot catch this class of issue**: import checks on the Ubuntu runner can verify only directory completeness. `._pth` path behavior and the absence of `setuptools` appear only in the real Windows embedded runtime. Therefore, after every change to `start.bat` or `python.rs`, test it once in a **freshly unpacked directory** (do not reuse an already-installed directory; its `._pth` may have been corrected by a previous run and its `site-packages` may already contain setuptools, both of which hide the problem).

> To reproduce a "fresh runtime" on a development machine: temporarily rename `setuptools*`, `wheel*`, `_distutils_hack`, and `distutils-precedence.pth` under `runtime\Lib\site-packages`, then run dependency installation once more.

## Code Conventions

**Lint / formatting**: ruff (configured in `pyproject.toml`). black is not used -- do not introduce black formatting, as it creates large amounts of meaningless diff.

**Type checking**: pyright (`pyrightconfig.json`). CI does not run type checking, but new code should include type annotations.

**Comments should explain "why", not "what".** Many comments in the project record the empirical basis for a threshold, why an order is necessary, or the cause of a bug. Once removed, that information cannot be inferred from the code. For example:

```python
# The confidence / importance weights are deliberately reduced to 0.05: they describe
# whether the memory itself is reliable/important and have little to do with "whether
# it should be used now", so they are suitable only as tie-breakers. Otherwise a
# high-quality decoy with conf~=0.98 could cheat on "whether it should be used".
```

**Do not keep a second copy of logic.** The existence of `memory/text_similarity.py` is itself a consequence of similarity checks once existing in three modules; the cross-user merge bug then had to be fixed three times and was missed twice.

**Silent fallback must leave a trace.** The project contains many `except sqlite3.OperationalError` clauses to tolerate "the table does not exist yet" (lazy table creation), and that design is correct. But it also swallows fatal errors such as "column name mismatch" -- both incidents on 2026-08-17 (a missing memory-table column and @ messages not entering the database) remained unnoticed for hours for this reason.

Convention: classify SQLite exceptions by message content when catching them.

```python
if "no such table" in str(e):
    logger.debug(...)   # Normal case for lazy table creation
else:
    logger.warning(...)  # Especially no such column; it must be visible
```

Likewise, every path that "returns an empty result on failure and continues" must leave a warning. A feature that fails silently is much harder to diagnose than a crash.

**Prompt changes need guardrails.** `tests/test_consolidation_prompt.py` and `tests/test_proactive_prompt.py` use string assertions for key clauses, including reverse assertions (confirming that removed clauses have not been written back). After such a clause is removed, the feature still "works" but its quality immediately degrades; only assertions can lock this down.

## Troubleshooting

**All runtime logs are in `logs/`** (determined by `LOG_DIR`; see [configuration reference](configuration.en.md#logs)). Troubleshooting is essentially searching this directory.

| Symptom | Check |
|---|---|
| Incorrect reply content | `logs/stella_thought_logs.md` (complete prompt / raw output / internal reasoning) |
| Plugin not loaded / capability not registered | `logs/boot_debug.log` (cleared and rewritten at every startup; reflects only the most recent startup) |
| Memory not generated | `logs/memory_consolidation_log.md` (raw output and candidate count for each consolidation batch) |
| Memory deleted incorrectly | `logs/memory_compressor_log.md` + `compressor_stats` table |
| Wrong memory selected during retrieval | `memory_traces` table (candidate / filtered / final / rejected), or `python -m memory.benchmark --verbose` |
| Abnormal proactive speech | `🎯 [proactive@]` / `🔇 no response` in the logs; `proactive_state` table |
| Link disconnected / messages not received | `[LinkMonitor]` alerts in the logs (including troubleshooting steps); NapCatQQ Desktop logs to confirm whether the account disconnected |
| Consolidation output truncated | `finish_reason=length` alert in the logs |
| @ conversations learn nothing at all | `SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind`; `AT_MENTION` at 0 means the persistence listener was intercepted by `block=True` (`priority` must be 0) |
| Proactive @ always uses cold start | `mode=coldstart` remains constant in the logs, or `[ProactiveTarget] failed to read candidates`; indicates that the space column name in the candidate query does not match |
| A model has severe queueing / replies are slow | Wait/hold/queue-depth alerts under `[Scheduler]` in the logs; `core.llm.snapshot()` exports cumulative statistics |
| Memory reads/writes silently do nothing | Check for a v8 old-database warning in the startup log; check whether `PRAGMA table_info(memories)` contains `group_shared_space` |
| GUI cannot display link status | Check `STELLA_STATUS_API_ENABLED`, and verify directly with `curl http://127.0.0.1:8080/stella/status`; if the process is running but the endpoint returns 403, the route was incorrectly exposed or restricted; if it cannot connect, uvicorn did not start |

### Common SQL

```sql
-- Candidate queue status distribution
SELECT status, COUNT(*), AVG(confidence), AVG(occurrence_count)
FROM memory_candidates GROUP BY status;

-- Candidates stuck in the observation area (repeatedly mentioned but unable to be promoted)
SELECT user_id, content, confidence, occurrence_count, source_kinds, first_seen_at
FROM memory_candidates WHERE status = 'OBSERVING' ORDER BY occurrence_count DESC;

-- Memory count per user (quota observation)
SELECT group_shared_space, user_id, COUNT(*) FROM memories
WHERE status = 'active' GROUP BY group_shared_space, user_id ORDER BY 3 DESC;

-- Memory source distribution (audit: which path produced them)
SELECT source_kind, COUNT(*) FROM memories WHERE status = 'active' GROUP BY source_kind;

-- Message source distribution
SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind;

-- Consolidation progress
SELECT * FROM consolidation_state;

-- Schema version
SELECT * FROM schema_meta;

-- Message source distribution (AT_MENTION at 0 while BOT_SELF > 0 means persistence was intercepted)
SELECT group_id, source_kind, COUNT(*) FROM group_messages
GROUP BY group_id, source_kind;

-- Candidate source composition (a single AT_MENTION source should be enough for promotion)
SELECT source_kind, source_kinds, status, COUNT(*) FROM memory_candidates
GROUP BY source_kind, source_kinds, status;

-- Verify space ownership: tables at QQ-group granularity should contain group numbers;
-- memory-granularity tables should contain space names
SELECT DISTINCT 'consolidation_state' AS t, group_id AS id FROM consolidation_state
UNION ALL SELECT DISTINCT 'memories', group_shared_space FROM memories;

-- Decision tracing: inspect the triggering group and retrieval space together
SELECT group_id, group_shared_space, mode, trigger, ts FROM memory_traces
ORDER BY ts DESC LIMIT 20;
```

## Commits and Contributions

**Commit messages** should briefly describe the substance of the change in English or Chinese. Avoid information-free descriptions such as "fix bug" or "update".

**Before a PR**:

- `python -m pytest tests -q` is fully green
- `ruff check .` reports no warnings
- If a prompt changed, the two-way gate was run (positive regression + real windows)
- If the schema changed, `python -m memory.schema --dry-run` output is as expected
- If configuration items changed, `.env.example` is synchronized (`deploy init` renders from it; if it is missed, the new configuration item will not appear in the generated `.env`), and `docs/configuration.en.md` is synchronized
- If listener priority changed or a handler with `block=True` was added, confirm that the persistence listener remains the highest priority and send one @ message to verify that `AT_MENTION` is persisted
- If memory-table SQL changed, confirm that it uses `group_shared_space` rather than `group_id` (the two ownership layers are described in architecture.en.md)
- If Router rules / capability declarations changed, `python -m capability.router.benchmark --rules-only` still reports 0 memory false negatives and 0 tool false positives
- Before enabling `ROUTER_GATE_MEMORY`, run the full-pipeline benchmark (requires an embedding service) and confirm exit code 0; this is the only way to verify that it will not silently lose memories
- When adding a new capability Provider type (MCP / API / native), implement its branch in `capability/comes/executor.py::resolve_tools`; do not let it silently fall into `missing`

**Explain the reason in the PR description when the change involves any of the following**:

- Thresholds or decision logic for memory promotion
- Anti-fabrication clauses in prompts
- Ownership filtering in the three merge paths
- Link-monitor liveness / alert logic (heartbeat + active probe, alert only and no restart)
- Listener priority and block relationships
- The division between the two ownership layers (QQ group / shared space)

All of these areas have empirical evidence (recorded in `design_docs/check_point/` and `bug_report/`); before changing them, reading the relevant records is recommended.

## Design Records

`design_docs/` is an archive of the design process for developers:

| Directory/File | Contents |
|---|---|
| `Memory *Specification v1.0.md` | Original memory-system specification (Schema / Consolidation / Retrieval / Policy Matrix / Evaluation & Debug) |
| `Migration & Implementation Plan.md` | v1 -> v2 migration plan |
| `Memory Verification Loop.md` | Design of the proactive acquisition loop |
| `check_point/` | Key decision points: problems, diagnostic process, disproven hypotheses, and empirical data |
| `bug_report/` | Defect analysis |
| `logs/` | Archives of terminal output and runtime logs |

Difference from `docs/`: `docs/` contains finished documentation for users, while `design_docs/` contains process records, including disproven hypotheses and failed attempts. That information is important for understanding "why things are the way they are now", but is not suitable for user documentation.
