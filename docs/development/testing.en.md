# Pre-commit Checks

[中文](testing.md) | English · [Documentation](../README.en.md)

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
