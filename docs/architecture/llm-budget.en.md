# LLM Cost Control

[中文](llm-budget.md) | English · [Documentation](../README.en.md)

Online endpoints charge by token, while the memory domain (consolidation / compaction / extraction) consists of frequent background tasks. **Without accounting, it is impossible to know where money is spent; without a budget, there is no upper bound.** Cost control has three layers, ordered from least expensive to most expensive:

| Layer | Method | Location |
|---|---|---|
| Structure | Increase batch size, remove overlapping windows, tighten output limits | `CONSOLIDATION_ONLINE_*` (effective only when CONSOLIDATION is assigned to an online endpoint) |
| Pre-filtering | Zero-cost pure-local pre-screening; skip the LLM entirely for sufficiently useless batches | `memory/cost_gates.py` |
| Accounting and budget | Persist daily ledger + daily limit + over-budget action | `core/llm/usage_store.py` |

### Accounting Pipeline

```
LLM backend (lm_studio / openai_client)
    ↓  Report one UsageRecord per call (token count / cache hit / truncation / failure)
core/llm/usage_sink.py            ← Reporting sink: swallows all exceptions, zero DB dependency
    ↓  attached through set_sink()
core/llm/usage_store.py           ← In-memory buffer, throttled UPSERT by row count/time
    ↓
llm_usage_daily  (date, role, slot, model)
```

**Why put a sink in the middle**: accounting must never become a failure point in the chat path. `usage_sink` is an in-memory reporting sink that knows nothing about SQLite and swallows all exceptions; `usage_store` is the sole writer, and it also makes `flush()` “never raise and return 0 if it cannot connect to the database.” In the worst case, part of the ledger is missing rather than nobody receiving a reply in the group.

**Why not write synchronously on every call**: one consolidation takes 20 seconds and one chat takes 2 seconds; inserting an fsync in the middle is pure waste, and concurrent multi-group operation would also contend for the database lock. Increments accumulate in memory and are persisted after 16 rows or 60 seconds; a snapshot read and process exit also force a flush.

**Date key rather than timer**: the key uses the local time zone's `%Y-%m-%d`, so the budget naturally rolls over at midnight. With a timer, a “daily budget” would become “24 hours after each startup,” and restarting once could refresh the allowance. At process startup, the **current day's** cumulative total is read back from the table, so a restart does not reset it. During the same read, records older than 90 days are cleaned up (the number is hard-coded and has no configuration option).

**The cache-hit-rate denominator is input tokens, not call count**: one long request hitting halfway and two short requests each hitting completely save very different amounts of money. This is the only way to verify whether a vendor's prefix cache is actually working; a persistently zero value means the prompt's fixed prefix has been broken. `tests/test_prompt_cache_prefix.py` protects prefix order, while the usage dashboard protects actual effect; both are indispensable.

### Where the Budget Takes Effect

The decision function is `usage_store.budget_blocked(role)`: `None` means allow, while a block returns a reason that can be written directly to the log. It is **explicitly written at each domain entry point**, rather than put into `registry.backend_for()`: that function has instance caching and is heavily monkeypatched by tests, so hiding policy in construction would make “why did this call not happen?” impossible to trace.

| Action | Where it blocks |
|---|---|
| `pause_memory` (default) | Before `_generate` in `consolidate_group()`, at the `_extract_candidates()` entry, and at the `compact_once()` entry |
| `pause_all` | All three locations above + before reply generation in `ai_gateway` (before `pipeline.run(ctx)`) |
| `warn_only` | Does not block any call; logs one warning per day |

The default action affects only the three memory-domain roles; the chat path is untouched. **The group can continue talking normally after the budget is exceeded**, at the cost of temporarily stale memory. `pause_all` is an explicit hard stop selected by the user: blocked messages follow NoneBot's normal “no reply” return path, **silently, without raising, sending a notice, or falling back to a local endpoint**. Fallback would make “stop everything” nominal only, and a purely online deployment may not have a local endpoint to fall back to anyway.

### Pre-filtering: Skipping Accumulates, It Does Not Discard

`memory/cost_gates.py` contains only **pure functions with no DB or I/O**: image-flood and one-character-response detection, the proportion of @ messages, and semantic novelty relative to the previous batch's summary. When vectors are available it uses `EmbeddingService`; when vectors cannot be obtained it falls back to the lexical criterion in `text_similarity`. (`MEMORY_EMBEDDING_ENABLED` is disabled by default; without this fallback, the gate would never trigger under the default configuration.)

**No skip path advances the checkpoint.** This is a hard constraint: advancing it would be another form of “messages permanently lost.” The cost is that a group containing only image floods could remain pending forever, so `consolidation_state.skip_streak` records consecutive skips. Once `CONSOLIDATION_MAX_SKIP_STREAK` is reached, one consolidation is forced and the counter is cleared. The worst case is delay, not loss.

### No Downgrade on 400

The fallback chain (P2) is meaningful only for failures that might succeed with another endpoint: authentication failure, exhausted quota, rate limiting, 5xx, connection failure, and timeout. If the request body itself is invalid (400, and 404 caused by an incorrect model name), another endpoint will fail in the same way; fallback would hide a configuration problem as “sometimes it is a little slower.”

`core/llm/registry.py`'s `fallback_worthy(exc)` is the sole enforcer of this contract: it returns `False` for 4xx errors except authentication/rate limiting. When `RoleBackend` sees `False`, it re-raises unchanged and writes an error log explicitly saying “no fallback by contract,” allowing the true cause to rise to the top of the logs. Non-HTTP exceptions are always eligible for fallback.

Fallback also distinguishes two states: `RoleBinding.describe()` reports the **configuration state** (which fallback slot is configured), while `RoleBackend.runtime_state()` reports the **runtime state** (whether the fallback chain is currently active and how many seconds remain in cooldown). The latter exists only in the Bot process's memory. `registry.fallback_states()` reads the `_backends` cache, which is necessarily empty in `deploy doctor`'s own process, so doctor obtains it from the status interface instead of calculating it locally.
