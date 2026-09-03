# Architecture Overview

[中文](architecture.md) | English

> Note: This version of the document was translated from the Chinese version by GPT-5.6 luna.

This document describes Stella's directory structure, module responsibilities, and the complete processing flow for a message. The design rationale for the memory system is in [Memory System](memory-system.en.md), capability routing and tool execution are in [Capability System](capability-system.en.md), and configuration options are in [Configuration Reference](configuration.en.md).

## Layered Overview

```
QQ group message
    ↓  OneBot V11 / NapCat
stella_project/plugins/bot_main/ai_gateway.py     ← Event ingress layer
    ↓
core/pipeline.py                                  ← Orchestration layer (pre hooks → LLM → post hooks)
     ↓
capability/*                                      ← Capability layer (Router decisions / Comes tool execution)
memory/*                                          ← Memory layer (write / promotion / retrieval / compaction)
     ↓
SQLite (memory/agent_memory.db)
```

The five layers are independent: the ingress layer only adapts protocols and dispatches, the orchestration layer contains no business logic, the capability layer is unaware of personality and memory content, the memory layer is unaware of QQ, and the storage layer has migrations centrally managed by `memory/schema.py`.

The capability and memory layers are **parallel** branches. Both are activated by the same pre-hook in the orchestration layer, and communicate with each other only through `ChatContext`; they do not call each other.

`astrbot_compat/*` is a sixth component alongside them: it connects the AstrBot plugin ecosystem, providing tool execution for the capability layer (Comes → `llm_tools`) while also following an independent dispatch path (`plugin_handler`) to respond to plugin commands. It **does not participate** in memory or personality; see the [AstrBot Plugin Compatibility Layer](#astrbot-plugin-compatibility-layer) section below.

> The storage layer has **two ownership dimensions**: `group_id` is the real QQ group, while `group_shared_space` is the shared group space. The former carries “the state of this current conversation,” and the latter carries “long-term knowledge about people.” See “Main Data Tables” below.

## Directory Structure

```text
Stella_project/
├── bot.py                          # NoneBot startup entry point
├── pyproject.toml                  # Dependencies, NoneBot configuration, ruff/pytest rules
├── pyrightconfig.json              # Type-checking configuration
│
├── config/
│   ├── settings.py         # Centralized configuration: reads .env and exports module-level constants
│   ├── spaces.py           # Shared group space resolution (config/spaces/*.toml)
│   ├── spaces/             # Space configuration (filename is the space name; not in .env)
│   └── capabilities/       # Capability declarations (filename is the domain, optional; see *.example)
│
├── core/                           # Business-independent orchestration skeleton
│   ├── context.py                  # ChatContext: runtime carrier for one processing operation
│   ├── tasks.py                    # Task / Result / TaskGraph protocol (shared by four modules)
│   ├── pipeline.py                  # Pipeline orchestrator + prompt assembly order
│   └── llm/
│       ├── base.py                 # Abstract LLM backend interface
│       ├── registry.py             # Endpoint × role registry: the only backend construction entry point in the project
│       ├── compat.py               # Parameter-difference adaptation for OpenAI-compatible endpoints (no vendor allowlist)
│       ├── lm_studio.py            # LM Studio backend (including retries and truncation warnings)
│       ├── openai_client.py        # Full chat-completions client (tools / images / streaming)
│       ├── usage_sink.py           # Usage reporting sink (truncation signals / token aggregation / cache hit rate)
│       ├── usage_store.py          # Daily ledger + daily budget decision (`llm_usage_daily`'s sole writer)
│       └── scheduler.py    # Model-level resource gate (FIFO serialization + queue observability)
│
├── capability/                     # Capability layer (see docs/capability-system.en.md)
│   ├── registry.py                 # Capability / Provider / registry singleton + health-based backoff
│   ├── loader.py                   # config/capabilities/*.toml → registry
│   ├── hooks.py                    # activate_capabilities pre-hook (pipeline integration point)
│   ├── router/                     # Three-level routing
│   │   ├── types.py                # Route / CapabilityHit
│   │   ├── rules.py                # Level 0: keyword rules (zero latency)
│   │   ├── semantic.py             # Level 1: Embedding prototype matching
│   │   ├── fallback.py             # Level 2: stronger-model fallback (disabled by default)
│   │   └── benchmark.py            # Routing accuracy benchmark (determines whether memory gating can be enabled)
│   ├── comes/                      # Tool execution layer
│   │   ├── executor.py             # Capability → Provider → Tool → Result
│   │   └── summarizer.py           # Result.data → Result.summary
│   └── adapters/
│       └── astrbot.py              # Automatic llm_tools → Provider derivation + bootstrap
│
├── memory/                         # Memory system core
│   ├── SYSTEM.md                   # Bot system prompt
│   ├── schema.py                   # Schema migrations (Additive, currently v8) + source enum
│   ├── timeutil.py                 # Parse DB timestamps uniformly as UTC
│   ├── text_similarity.py          # Content similarity and merging (single source of truth)
│   │
│   ├── pre_processors.py           # Message persistence, short-term context, user-context assembly
│   ├── session_context.py          # Session-compaction state and decisions (pure logic)
│   ├── session_compact.py          # Session-compaction execution (fetch messages, call LLM, write back)
│   ├── post_processors.py          # Output parsing, composure-break filtering, line splitting, thought logging
│   ├── prompt_builder.py           # Memory and context → partitioned Prompt
│   │
│   ├── consolidator.py             # Consolidation: messages → summary/profile/candidates (including candidate reinforcement)
│   ├── consolidation_prompt.py     # JSON output template for consolidation tasks
│   ├── extraction_prompt.py        # Prompt template for Phase 2 candidate extraction
│   ├── consolidation_log.py        # Consolidation process log
│   ├── memory_manager.py           # Promotion: three Gate 1 tiers, quota eviction, FTS synchronization
│   ├── policy.py                   # Policy: Mode detection, three-layer filtering, ranking, candidate validation
│   ├── compressor.py               # Compaction: deduplication and merging, atomization, archiving, decay
│   │
│   ├── retrieval_v2.py             # v2 retrieval (Context-aware Memory Activation)
│   ├── retriever.py                # FTS5 retrieval + weighted fallback ranking
│   ├── embeddings.py               # Local embedding client (optional semantic scoring)
│   │
│   ├── proactive.py                # Activity statistics and speaking-probability curve
│   ├── proactive_state.py          # Persistent proactive-speaking state (quota/cooldown/backoff)
│   ├── proactive_gate.py           # Unified proactive-speaking admission gate (six conditions)
│   ├── proactive_target.py         # Target selection and quota decisions for proactive @ mentions
│   ├── proactive_prompt.py         # Task instruction template for proactive @ mentions
│   │
│   ├── trace.py                    # Memory decision tracing
│   ├── benchmark.py                # Memory Benchmark runner
│   ├── benchmark/                  # Retrieval-layer cases + _fixtures (including positive consolidation benchmarks)
│   └── db_cleaner.py               # Dirty-data cleanup + scheduled message-table pruning
│
├── extensions/                     # Automatically loaded extensions (scan setup(pipeline))
│   ├── __init__.py                 # Extension loader
│   └── link_monitor/               # OneBot link monitoring (heartbeat + active probing, alerts only)
│
├── astrbot_compat/                 # AstrBot plugin compatibility layer (see below)
│   ├── shim.py                     # Fakes the astrbot.* module tree so plugins can import successfully
│   ├── loader.py                   # Discovers and loads plugins under data/plugins/*
│   ├── base.py                     # Star base class / StarTools (including html_render entry point)
│   ├── registry.py                 # Plugin and handler registry (module-level singleton)
│   ├── filters.py                  # @command / @regex / @event_message_type and other decorators
│   ├── events.py                   # OneBot events → AstrMessageEvent, including wake-up checks
│   ├── components.py               # Bidirectional conversion of message segments (Plain/Image/Json/Node…)
│   ├── pipeline.py                 # should_dispatch + wake-up check + handler execution
│   ├── render.py                   # HTML → image (local Chromium, see below)
│   └── llm/                        # Plugin-side LLM: Provider / ToolSet / tool loop
│
├── deploy/                         # Deployment CLI (python -m deploy ...)
│   ├── probe.py                    # doctor collection layer (probes only, no decisions)
│   ├── checks.py                   # doctor decision layer (pure functions, one per check)
│   ├── process.py                  # start --detach / status / stop
│   ├── init.py                     # Configuration wizard
│   └── env_schema.py               # settings.py → GUI configuration form schema
│
├── stella_project/plugins/bot_main/
│   ├── ai_gateway.py               # QQ event listener, Pipeline assembly, proactive-speaking scheduling
│   ├── status_api.py               # Local status interface (loopback, for deploy status / GUI)
│   └── config.py                   # Plugin configuration (pydantic)
│
├── data/                           # Runtime data (all gitignored)
│   ├── plugins/                    # Third-party AstrBot plugins
│   ├── plugin_data/                # Plugins' own KV / data directories
│   └── render_cache/               # HTML rendering artifacts (images to send, not logs)
│
├── logs/                           # All runtime logs (LOG_DIR, gitignored)
│   ├── stella.jsonl                # Structured logs (consumed by GUI, 10MB rotation, retain 5 files)
│   ├── stella_thought_logs.md      # Thought/decision log
│   ├── memory_consolidation_log.md # Consolidation log
│   ├── memory_compressor_log.md    # Compaction log
│   ├── boot_debug.log              # Startup diagnostics (cleared and rewritten on each startup)
│   └── stella.pid                  # Process ID (not a log, but in the same directory)
│
├── scripts/                        # Development-time tools (not in CI)
│   ├── probe_consolidation.py      # Consolidation probe / positive-case regression benchmark
│   ├── sample_windows.py           # Stratified sampling of message windows from the real database
│   ├── probe_embedding.py          # Embedding service probe
│   └── build_embedding_fixture.py  # Build benchmark vector fixture
│
├── stella-installer/               # Desktop installer (Tauri 2 + Rust, native HTML/JS)
├── tests/                          # pytest tests
├── docs/                           # User documentation
├── design_docs/                    # Design process records (specifications/checkpoints/defect reports/logs/test checklists)
└── _deprecated/                    # Deprecated code and old database archive (gitignored)
```

## Message Processing Flow

### 1. Ingress and Persistence

```
Group message → group_silent_listener (priority 0, block=False)
              → pre_processors.record_message() → group_messages table
              → proactive.record_message() → activity timestamp (in memory)
              → session_context.touch() → session activity timestamp (in memory)
```

The silent listener processes **every** group message, including messages that do not @ the bot. Messages are tagged by source tier when persisted:

| `source_kind` | Meaning | Weight in the memory system |
|---|---|---|
| `AT_MENTION` | User speaks directly to the Bot | High-density evidence; a single occurrence can be promoted |
| `PASSIVE` | Passively ingested group chat | Must recur before promotion |
| `BOT_SELF` | The Bot's own message | **Context only; never produces candidates** |

`BOT_SELF` is required: without it, when a user gives a short response such as “yes” or “phone,” the consolidation model cannot see what the Bot asked and can only give up or invent the context.

Link monitoring refreshes the heartbeat through an **independent** `event_preprocessor` (any OneBot event counts, including heartbeat meta-events from the protocol endpoint); this is not the responsibility of `group_silent_listener`.

> **The persistence listener must have the highest priority (0)** and must come before all `block=True` handlers.
>
> In NoneBot, `block=True` prevents an event from propagating to handlers with lower priority. If the persistence listener is placed after `chat_handler`, **messages @ mentioning the Bot are intercepted and never persisted**: ordinary group chat is recorded normally, but the most valuable @ conversations are all lost.
>
> Measured on 2026-08-17: with the persistence listener at `priority 99`, 13 consolidation batches consumed 270 messages, and the `AT_MENTION` count was **zero throughout**. @ conversations are the only consistently reliable source of user information by design (see `design_docs/check_point/`), so this loop had never run; consequently `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT`, `MEMORY_AT_MENTION_CONFIDENCE_BONUS`, and the candidate-validation mode for proactive @ mentions (`mode=verify`) all spun without effect.
>
> The responsibility order is “persist first, then decide whether to reply.” When adding any `block=True` handler, its priority must be greater than 0.
>
> Side effect of persisting first: the current message also appears at the end of its own context and under the “【Now user (X) says to you】” marker. This duplication is acceptable: repeating the same sentence reinforces rather than confuses, while the explicit marker for the current input remains (the fix for the wrong-topic response defect on 2026-08-16).

### 2. Trigger Paths

| Path | Trigger condition | `trigger` | `intent` |
|---|---|---|---|
| @ reply | Group is allowlisted + Bot is @ mentioned + contains text | `reply` | `""` |
| Proactive @ | Scheduled check hits and selects an active user | `reply` | `proactive_at` |
| Proactive interjection | Scheduled check hits and probability curve passes | `proactive` | `proactive_join` |
| Plugin dispatch | Group is allowlisted + not a self-echo + message is non-empty | — | — |
| Runtime toggle | Administrator @ mentions the Bot + matches a toggle keyword | — | — |
| Capability query | Group is allow-listed + @ mentioned + matches a phrasing such as “what can you do” | — | — |

The three conversation paths share one Pipeline and use `ChatContext` fields to distinguish behavior. Each group has one `asyncio.Lock`, ensuring that only one inference runs in a group at a time.

The threshold for plugin dispatch is deliberately much broader than for @ replies (`astrbot_compat.pipeline.should_dispatch` makes the decision): upstream AstrBot runs plugin filters once for every message, and each filter decides whether to wake up. The threshold is “the message has a segment,” **not** “the message has plain text.” A mini-program card shared from a mobile device contains only one `json` segment; checking for plain text would block the entire message outside the plugin layer, so handlers such as `@event_message_type(ALL)`, which specifically exist for non-text messages, would never receive the event (measured on 2026-08-25).

Proactive @ and proactive interjection are **mutually exclusive**: the scheduled task first attempts a proactive @, and skips the interjection if it hits; only one message is sent per round.

Admission for proactive paths (proactive @ / proactive interjection) uniformly goes through `memory/proactive_gate.py`'s `can_speak(group_id, kind)`, which checks six items in order:

```
Master switch → per-path switch → runtime mute → sleep period → wake-up buffer → group cooldown → new-message threshold
```

The return value includes a reason string, making it possible to investigate “why did it not speak this time?” Consolidating this into a single entry point has a reason: these conditions were previously scattered across `proactive_speak_job`, `_proactive_at_user`, and `should_speak`, so every added condition required changes at three call sites.

The probability roll for topic interjections is **not inside the gate**. It is unique to the join path, so the caller rolls it after the gate passes (proactive @ has quota and user-level cooldown constraints and does not roll).

**@ replies do not go through the gate.** They are answered normally when the Bot is @ mentioned during sleep or mute periods.

> Priority relationship of the five listeners (smaller numbers execute first):
>
> | Listener | priority | block | Responsibility |
> |---|---|---|---|
> | `group_silent_listener` | 0 | No | Persistence (must be first, see above) |
> | `toggle_handler` | 1 | Yes | Runtime toggle commands |
> | `capability_handler` | 1 | Yes | Capability query (“what can you do”) |
> | `plugin_handler` | 2 | No | AstrBot plugin dispatch (see [compatibility layer](#astrbot-plugin-compatibility-layer)) |
> | `chat_handler` | 3 | Yes | Main @ reply flow |
>
> `toggle_handler` must precede `chat_handler`; otherwise a command such as “quiet” is treated as ordinary conversation and handed to the LLM. The same applies to `capability_handler`: unless it precedes `chat_handler`, “what can you do” is handed to the LLM, which answers with what it **guesses** its capabilities are rather than what the registry actually holds.
>
> `toggle_handler` and `capability_handler` share a priority and are both `block=True`, and NoneBot runs same-priority matchers together, so their rules must be **mechanically disjoint**: `is_query_text()` always returns False when the text matches the runtime toggle keyword lists, and `_assert_capability_rule_disjoint()` pins this at startup by brute-forcing every concatenation of the two lists. This does not rely on “the two lists happen not to overlap” — whoever adds a word will not check the other list, and a sentence matching both would fire one handler that **changes group settings**.
>
> `plugin_handler` uses `block=False`: when no plugin matches, the event must continue to `chat_handler`. When a plugin matches, it records the `message_id` in `_plugin_handled_msgs`, and `chat_handler` skips it itself. Using block would also block cases where a plugin merely records something and does not reply.

### 3. Context Construction (pre hooks)

Pipeline pre-hooks execute in **descending** priority order:

```
build_context          (50)  → ctx.short_term
activate_capabilities  (45)  → ctx.route, concurrently activates {long-term memory retrieval, Comes tool execution}
```

**`build_context`** assembles three coexisting layers of short-term context:

- **Topic summary**: `short_term_context.active_summary` / `pending_topic`, produced by the consolidator and intentionally delayed; when it has not been updated for more than `SHORT_TERM_SUMMARY_STALE_MINUTES`, the title changes to “Previous topic” and includes the duration
- **Raw tail**: the most recent `RECENT_TAIL_LIMIT` raw messages, including the Bot's own messages (rendered as “I”). Older messages outside the `RECENT_TAIL_MAX_AGE_MINUTES` time window are filtered (fixed on 2026-08-15); when the gap between adjacent messages inside the window exceeds `RECENT_TAIL_GAP_MARK_MINUTES`, a gap marker “(… X in between …)” is inserted
- **Session summary**: earlier content from the current conversation that has rolled out of the tail window, asynchronously compacted by `session_compact` after each reply

The three layers are partitioned by message ID and **never overlap**:

```
Session summary: summarized_up_to_id → tail start (older portion, already compacted)
Raw tail: most recent RECENT_TAIL_LIMIT messages (original text)
Topic summary: cross-session background produced by the consolidator
```

Overlap would cause the same conversation segment to appear in two versions, causing the model to follow the summary and switch to the wrong topic (the cause of the defect on 2026-08-13). The tail start (`ctx.tail_start_id`) is the ID of “the first message that actually enters the tail”; messages filtered by the time window belong to the pending-compaction interval and are not lost.

All three layers are required. The summary is updated only after accumulating to a threshold; relying on it alone would hide the latest rounds of conversation, causing the Bot to connect a user's short response to the previous topic.

**`activate_capabilities`** does two things: it first uses the Router to determine which capabilities are needed for this request, then **concurrently** activates memory retrieval and tool execution (see [Capability System](capability-system.en.md)).

```
capability.router.route(message)              ← three-level cascade: rules → Embedding → model fallback
  → ctx.route (decision snapshot, written to thought log and decision trace)
  ↓
asyncio.gather(
    build_user_context(ctx),               ← long-term memory retrieval (below)
    run_comes(ctx, route),                 ← tool execution, only when route.tool
)
```

`build_user_context` is **no longer registered as a separate hook**; it is now handled by this hook: Memory and Comes must run concurrently, whereas two independent hooks would run serially.

`build_context` always executes unconditionally: short-term context is conversation material and is unrelated to “whether long-term memory should be retrieved.”

> **Memory gating is disabled by default** (`ROUTER_GATE_MEMORY=false`): the Router still makes and records its decision, but memory retrieval still executes unconditionally. A false `memory=False` decision would cause Stella to silently lose long-term memory for that turn: no exception is raised and the reply is unaffected, but “it suddenly no longer remembers you,” the same type of defect as the all-zero `AT_MENTION` incident on 2026-08-17. Before enabling it, run `python -m capability.router.benchmark` and confirm that memory false negatives are zero.

**`build_user_context`** uses v2 retrieval (`MEMORY_V2_ENABLED`):

Profiles and memories are retrieved by **shared space** (`resolve_space(ctx.group_id)`), not by QQ group.

```
detect_mode(message, trigger method)                   ← determine behavior mode
  → SQL visibility pre-filter                          ← first decide what is eligible to be found
  → FTS5 / weighted fallback candidate pool
  → Usage-layer filtering + Ranking (Policy takes priority over similarity)
  → Merge same-category items (by user, never across ownership)
  → Separate chat material / behavioral constraints
  → Score threshold + per-mode item limit
```

### 4. LLM Calls

`core/pipeline.py` combines the context, tool results, and message into the final prompt. The **assembly order depends on `intent`**:

| intent | Order | Reason |
|---|---|---|
| Ordinary | Context → tool results → user message | The user's input is last, so the model naturally responds to it |
| `proactive_at` | **Task instruction → tool results → context** | `ctx.message` is an instruction, not user input; if placed last, the model will continue the conversation at the end of the context instead of executing the instruction |

The tool-results paragraph consumes only `ctx.tool_summaries` (one sentence after compression); **`Result.data` never enters the prompt**. A single search can return thousands of characters, and inserting it as-is would push the memory and conversation context out of the window. It sits between the context and current input: tool results are “evidence for answering this sentence” and must be close to the current input, while “please respond to this sentence” must remain the final line.

> Calls are serialized through the resource gate in `core/llm/scheduler.py`. **LM Studio does not limit concurrency**; sending multiple requests to the same model at once causes concurrent inference and slows them all down, so the application layer must provide a gate for every shared model.
>
> **The gate resource name is the endpoint slot name**: `acquire(gate_of(role))`, with concurrency set by `LLM_ENDPOINT_<slot>_CONCURRENCY`. Therefore, “which calls queue behind each other” is determined by which slot each role is bound to. With the pure-local default configuration:
>
> | Gate (slot) | Concurrency | Users |
> |---|---|---|
> | `LOCAL` | 1 | Chat replies, session compaction, candidate extraction, Comes tool loop, Router Level 2, embedding encoding (`MEMORY_EMBEDDING_GATE=auto`) |
> | `EXTRA` | 1 | Phase 1 of two-phase consolidation |
>
> Strict FIFO applies within one resource (`asyncio.Lock`'s wait queue is FIFO), while different resources can truly run concurrently. If a role is rebound to an online slot (for example, `LLM_ROLE_CHAT_ENDPOINT=ONLINE_CHAT`, with default concurrency 4), it leaves the `LOCAL` queue. This is the source of the throughput gain from going online. See [configuration.en.md · Endpoint and Role](configuration.en.md#endpoint-and-role-two-layer-configuration) for configuration.
>
> This is also the boundary of “Memory and Comes run concurrently”: in a pure-local setup, their **model calls** still serialize FIFO through the same `LOCAL` gate. `gather` overlaps Memory's SQL/FTS queries with Comes's HTTP wait. This is not fake concurrency, but it is not two GPUs either; only moving the PLUGIN role to an online slot makes this serialization truly disappear.
>
> `RESOURCE_CHAT` / `RESOURCE_CONSOLIDATION` in `scheduler.py` are legacy resource-name constants with no remaining call sites in the project; they are retained only to avoid breaking external imports. Acquiring them creates an independent gate corresponding to no endpoint and therefore provides no serialization protection.
>
> **A caller must never hold two gates simultaneously**: if it holds `EXTRA` and then waits for `LOCAL` (or vice versa), cross-endpoint head-of-line blocking occurs. One resource may be idle while waiting for the head task in the other resource to release, blocking both queues. This is why `consolidate_group` uses an independent group-level lock and splits Phase 1 and Phase 2 into two non-nested holding windows.
>
> Every acquisition records wait duration, hold duration, and queue depth, and warns when thresholds are exceeded; `core.llm.snapshot()` can export cumulative statistics for each resource. In a multi-group deployment, this is the only way to determine “which resource caused the latency and who is queued.”

> Timeouts and exceptions both have fallback replies. Diagnostic information (backend, model, elapsed time, complete prompt) is written to `ctx` and persisted by `log_thought`.

### 5. Output Processing (post hooks)

In descending priority order:

```
parse_output      (100)  → parse thought / action / reply
bad_phrase_filter  (80)  → composure-break phrase fallback
split_lines        (60)  → split into multiple lines that can be sent individually
log_thought        (40)  → write logs/stella_thought_logs.md
```

Before sending, the Bot's own line is written to `group_messages` (`BOT_SELF`). **It must happen before sending**: the final line calls `finish()`, which raises `FinishedException`; code after it does not execute.

### 6. Memory Writing and Promotion

This happens asynchronously and does not block replies:

```
Message accumulation → maybe_consolidate() (@ trigger / before proactive speaking / scheduled drain / session end)
                    → Phase 1 (consolidation model, CPU)
                    │    Outputs short-term summary + user profile + has_self_disclosure boolean
                    ↓ only when has_self_disclosure is true
                    → Phase 2 (main chat model, GPU)
                    │    Precisely extracts memory_candidates; result replaces Phase 1 (including an empty array)
                    → Candidate reinforcement: accumulate evidence for the same fact instead of inserting duplicates
                    → MemoryManager.process_new_candidates()
                      ├─ Expired OBSERVING → REJECTED
                      ├─ Gate 1 three-tier decision → promote / continue observing
                      ├─ Conflict detection → mark old memory CONFLICT
                      ├─ Merge similar items (same space, user, and type) or create new
                      └─ Per-user quota eviction (by space)
                    → FTS5 index synchronization
                    → Lightweight compaction (throttled trigger)
```

> **Why split into two phases**: the small model can summarize topics, but in noisy environments it systematically returns an empty candidate extraction. In a measurement on 2026-08-16, all 7 consolidation batches returned empty candidates even though the information was clearly present in its own `active_summary`: it “read it but actively discarded it.” Candidate extraction is a high-precision extraction task, so it is delegated to the main chat model.
>
> Phase 2 is controlled by a soft threshold (Phase 1's Boolean decision) and is awakened only when there is genuine user self-disclosure; routine message floods and small talk do not consume GPU. When Phase 2 succeeds, its candidates **replace** Phase 1's candidates, **including when it returns an empty array**: that means the large model's review found none and correctly fixes the small model's false positive. If the call or parsing fails, Phase 1's candidates are used as a fallback.
>
> Each phase holds the gate for its corresponding resource, and **never holds both simultaneously** (see above). Group-level serialization for consolidation is guaranteed by a module-level group lock inside `consolidator`, separate from the model gates.
>
> Consolidation has four trigger points: before an @ trigger (force, small batch), before proactive speaking (force), scheduled drain (`CONSOLIDATION_SCHEDULE_INTERVAL`), and session idle end. Scheduled draining is required: when passive ingestion is faster than consolidation, unprocessed messages accumulate without bound and are cleaned up and discarded after `MESSAGE_CLEANUP_KEEP_COUNT` is exceeded.

### 7. Scheduled Tasks

| Task | Interval | Purpose |
|---|---|---|
| Proactive-speaking check | `PROACTIVE_CHECK_INTERVAL` | Sleep/wake announcements → attempt proactive @ → attempt proactive interjection |
| Link monitoring | `LINK_MONITOR_CHECK_INTERVAL` | Probe actively after an event timeout; alert on failure (do not restart) |
| Message-table pruning | At `MESSAGE_CLEANUP_HOUR` daily | Retain the most recent N messages per group and clean up expired traces |
| Weekly compaction | Every 7 days | Full deduplication, atomization, archiving, and decay |
| Scheduled consolidation drain | `CONSOLIDATION_SCHEDULE_INTERVAL` | Consume each group's consolidation backlog in batches |
| Session idle check | `SESSION_IDLE_CHECK_INTERVAL` | Clear compaction state after an idle timeout and trigger one full consolidation |

## Key Data Structures

### ChatContext

The runtime carrier for one processing operation and the only channel through which modules pass data.

| Group | Fields |
|---|---|
| Input identifiers | `user_id` `group_id` `group_shared_space` `msg_id` `message` `source_kind` |
| Processing outputs | `raw_output` `thought` `action` `reply` `lines` |
| Diagnostics | `trigger` `intent` `intent_detail` `llm_backend` `llm_model` `llm_elapsed` `prompt_log` |
| Structured context | `short_term` `user_profile` `memories_for_prompt` `tail_start_id` |
| Memory v2 | `memory_mode` `conversation_memories` `behavior_constraints` `memory_trace` |
| Task scheduling | `route` `task_results` `tool_summaries` |
| Platform handles | `raw_event` `bot` |

`group_id` is always the actual QQ group number; `group_shared_space` is automatically populated by `config.spaces.resolve_space()` and identifies the ownership of memories and profiles. They must not be conflated.

`raw_event` / `bot` are **opaque handles**: when Comes calls an AstrBot tool, the tool handler internally uses `event.send()` / `event.bot.call_action()`, so these must be the real objects and cannot be replaced by equivalent substitutes. `core` does not interpret their types or call any methods; it only passes them from the ingress layer to the capability layer. Both are marked `repr=False`: the `repr` of a OneBot event expands the entire message and sender, so repr-ing `ChatContext` would flood the logs.

The type annotation for `route` is `Any` rather than `Route`: `core` is a “business-independent orchestration skeleton” and should not import `capability`; a reverse dependency would create a cycle.

### Main Data Tables

**Two levels of ownership**. `group_id` carries “the state of this current conversation,” while `group_shared_space` carries “long-term knowledge and identity about people.” Multiple QQ groups can belong to the same space and share knowledge, but never the reverse: mixing messages from two groups into one tail would cause the Bot to answer a conversation from group B in group A.

| Table | Ownership | Purpose |
|---|---|---|
| `group_messages` | QQ group | Raw group messages (including `source_kind`) |
| `short_term_context` | QQ group | Per-group topic summary and key messages |
| `consolidation_state` | QQ group | Per-group consolidation checkpoint |
| `proactive_state` | QQ group | Proactive @ quota, cooldown, and backoff state |
| `group_runtime_state` | QQ group | Mute switch and sleep/wake announcement deduplication |
| `memory_candidates` | **Space** | Memory candidates (including `occurrence_count` / `source_kinds` / `first_seen_at`) |
| `memories` | **Space** | Long-term memories (including `usage_tags` / `visibility` / `behavior_rule`) |
| `memories_fts` | **Space** | FTS5 full-text index (synchronized with `memories` by `mem_id`) |
| `user_profiles` | **Space** | Stable user profiles, primary key `(group_shared_space, user_id)` |
| `atomic_facts` | **Space** | Atomic facts split from long-term memories |
| `memory_traces` | Both | Memory decision traces (`group_id` records the trigger source; `group_shared_space` records the retrieval space) |
| `compressor_stats` / `compressor_state` | Global | Compaction statistics and throttling state |
| `llm_usage_daily` | Global | Daily LLM usage, primary key `(date, role, slot, model)` |
| `schema_meta` | Global | Schema version |

Schema migrations use **Additive Migration**: only fields and indexes are added, and data is never deleted; an automatic backup is made before the first migration. Run independently:

```bash
python -m memory.schema --dry-run   # Preview
python -m memory.schema             # Execute
python -m memory.schema --backup    # Backup only
```

> **Structural changes and data changes live in another module**: `memory/migrations.py` registers migrations by version (`migrate_v7` / `v8` / …), with one function and one transaction per version; only after success does it advance `schema_meta.version`. The add-column/create-table work in `schema._migrate()` is the final step of each migration. The data migrations for v7 (profile grouping) and v8 (memory tables changed to space ownership) were completed on 2026-08-27. v5 → latest is fully automatic: rename columns + rewrite values as space names + rebuild profile primary keys + rebuild FTS + validate, with a full-level rollback on failure. **New rule: every increment of `SCHEMA_VERSION` must be committed together with `migrate_vN` and a legacy-database fixture test.**
>
> Each migration writes `agent_memory.db.pre-vN-<timestamp>.bak` (the state before that migration). `stella_memory_backup.db` is “the first original database ever”; it skips creation when a backup already exists. When archiving the old database, move it together with that file, or the system will be left in a state that “looks backed up but is actually the wrong backup.”

## LLM Cost Control

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

## AstrBot Plugin Compatibility Layer

`astrbot_compat/` lets plugins from the [AstrBot](https://github.com/AstrBotDevs/AstrBot) ecosystem run in Stella **without source changes**. `shim.py` fakes an entire `astrbot.*` module tree and redirects the plugins' `import` statements to the compatibility layer's real implementations. Plugins placed in `data/plugins/` are discovered and loaded automatically.

It has two independent paths; do not conflate them:

| Path | Entry point | Purpose |
|---|---|---|
| **Command dispatch** | `plugin_handler` (priority 2) | Scenarios where plugins respond themselves through `@command` / `@regex` / `@event_message_type` |
| **Tool execution** | Comes → `llm_tools` | Function tools registered by plugins with `@llm_tool`, called on demand by the capability layer |

The dispatch path's wake-up check follows upstream `WakingCheckStage`: every message runs through each handler's filters once, and the filter decides whether to wake up. `should_dispatch()` decides whether the message enters the pipeline (group allowlist + block self-echoes + message is non-empty).

**The compatibility layer does not participate in personality or memory.** Plugins cannot access Stella's system prompt or memory; conversely, plugin tool results are compressed by Comes into one `summary` before entering Stella's prompt. The rationale is the same as the capability layer's context isolation; see [Capability System](capability-system.en.md).

Unsupported upstream capabilities always raise `StellaCompatNotSupported` (rather than silently returning a false value), so a plugin error directly identifies which interface is missing.

**The tool-execution path has one extra step**: registering an `@llm_tool` successfully does not make it reachable from chat — the routing candidate set comes from `registry.routable()`, which needs a capability declaration. Declarations live in three tiers (user `STELLA_HOME/config/capabilities/` > factory `<project root>/config/capabilities/` > shipped with the plugin at `<plugin dir>/capability.toml`) with one identical format; once a higher tier claims a tool, the lower tier's entry is skipped entirely. The plugin tier is gated by `ASTRBOT_PLUGIN_CAPABILITIES_ENABLED` (default `true`) and only scans plugins that loaded successfully. For the full rules on writing a plugin see [Plugin Integration Specification](plugin-spec.en.md); for the tiers and routing details see [Capability System](capability-system.en.md#four-registration-tiers).

**Hot reload** (`ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED`, default off; once on, an in-group admin triggers it with "@Stella 重载插件 &lt;name&gt;") is a debugging convenience rather than a restart: it can reclaim handlers, tools, capability declarations, the modules in `sys.modules` and the `__pycache__` directories on disk, but not tasks started with a bare `asyncio.create_task()`, threads a plugin started, monkeypatches, or references to the old instance already held elsewhere. That is why the specification requires background tasks to go through `context.register_task` — only registered tasks carry an owner tag, which is what lets a reload cancel just that one plugin's tasks.

### Load Timing and Directory Names

**Plugins are loaded in the event loop** through the `on_startup` hook `_bootstrap_astrbot_plugins()` in `bot.py` (loading + `initialize_plugins()`). This is intentional: upstream AstrBot's entire plugin-loading chain is asynchronous, so starting background tasks with `asyncio.create_task(...)` in `__init__` is a **standard pattern in official plugins** (`astrbot_plugin_bilibili` does exactly this). Loading synchronously during import would make such plugins fail with `RuntimeError: no running event loop`, leaving users with the only option of changing plugin source, exactly contrary to “run without source changes.” Do not break either constraint: the hook must be `async def` (NoneBot sends a synchronous hook to a thread pool, which likewise has no running loop), and it must be registered before `_bootstrap_capabilities` (startup hooks execute **serially** in registration order).

**Directory names do not have to be valid Python module names**. When `data/plugins/<directory>` cannot be installed as `import data.plugins.<directory>.main` (the `-master` / `-main` suffix produced by GitHub “Download ZIP” is the common case; upstream `git clone` installations do not encounter it), `loader.py` normalizes the directory to a valid module name and mounts it as a package by file path (`__path__` points back to the real directory), so the plugin's `from .x` / `from ..y` imports resolve normally. If two directories normalize to the same name, a short digest suffix distinguishes the second; they are never allowed to replace each other. When `ASTRBOT_PLUGINS_DIR` points outside the project, the same mounting path is used.

The metadata's `root_dir_name` is always the actual directory name on disk, while the plugin data directory follows the metadata `name`, so renaming `xxx-master` to `xxx` afterward does not lose subscription data.

### HTML → Image Rendering

Many plugins create result cards from Jinja2 templates + CSS and render images through `Star.html_render`. The implementation is in `astrbot_compat/render.py`, backed by **local Chromium** (playwright).

**Why not use a remote service**: upstream AstrBot sends HTML to a remote t2i service by default. Templates contain group-member nicknames, dynamic text, and avatar URLs, all of which are chat content. In a fully local deployment, every other component runs locally, so rendering has no reason to be the one component that sends data outside the machine. The same applies to deployments using online models: the outbound recipient is a provider the user selected and pays for; there is no reason to add another rendering service they did not choose.

**Why a browser engine is required**: plugin templates commonly use flexbox, linear gradients, border-radius, and box-shadow (one plugin was measured at 350–460 lines of CSS in each of three templates). Tools such as weasyprint lack complete flex support and produce broken layouts. A broken layout is worse than a fallback because it appears to have “succeeded.”

Dependencies have two layers: the `playwright` pip package is included in `requirements.txt` (a few MB); the browser engine is about 270MB and is downloaded in the background **the first time rendering is actually needed**. During the download, plugins fall back to plain text as usual; once installed, rendering takes effect automatically without a restart. Installing only the headless shell is deliberate: the system only ever takes screenshots and does not need a headed browser.

When rendering is unavailable, it returns **an empty string rather than raising**: plugins generally branch on `if img_path:` to fall back (the upstream remote service can also fail), while raising would only be swallowed by their `except` and retried.

The browser is reused as a single instance (a cold start takes 1–2 seconds, and this is synchronous waiting on the main path); `bot.py` registers `on_shutdown` to close it. Playwright starts independent node + chromium child processes, which Python exit does not take down.

See [Configuration Reference](configuration.en.md#html-to-image-rendering-plugin-cards) for configuration options.

## Local Status Interface

`deploy status` and the desktop GUI need to read process-internal state (`link_status()` and scheduler queue depth), which external processes cannot access.

**Why HTTP instead of a state file**: state files can become stale. After the Bot crashes, the file remains and reports a false “running” state. An HTTP endpoint naturally means “unreachable means not running,” and also covers the intermediate state where the process is running but its HTTP service is not yet up (`api_reachable=false`; the GUI uses this to display “Starting…”).

**Why not add a port**: NoneBot already runs FastAPI/uvicorn, and its reverse WS endpoint `/onebot/v11/ws` is provided by that server. The status route is mounted on the same app (`GET /stella/status`), so Stella still has only one listening port (`PORT`).

**Implementation**: `stella_project/plugins/bot_main/status_api.py`. `setup_status_api()` is called in ai_gateway's startup section (after extension loading); `build_payload()` aggregates `link_status()`, `core.llm.snapshot()`, `usage_store.usage_snapshot()`, `capability.inventory.snapshot()`, and version/process information, returning `{version, pid, uptime_seconds, allowed_group_count, link, scheduler, usage, capabilities}`. Consumers are `_fetch_live_status()` in `deploy/process.py` (loopback query, 1-second timeout) and the GUI.

**Security constraints**: `HOST` may be `0.0.0.0` (required when NapCat is on another machine), in which case the route is exposed to the LAN. There are two protections: 1. accept only requests from loopback addresses and return 403 for others; 2. keep credentials and group-chat content out of the response. `allowed_group_count` provides a count, not group numbers, and `usage` contains only counts and ratios (token count, call count, cache hit rate, slot name, and model ID), never prompts or model output. `capabilities` contains structured fields only (capability id, domain, source tier, whether it is routable, provider tool names and health, `examples` count), without the `description` and `examples` free text from the declarations — those two fields are the only place that could smuggle in a URL or a key, and keeping them out of the response body means no extra guard is needed for them. `tests/test_status_api.py` locks this constraint in as an assertion: it serializes the real output of `usage_snapshot()` and fails if `api_key` / `Bearer` / `http://` appears.

## Extension Mechanism

Every module/package under `extensions/` that provides `setup(pipeline)` is loaded automatically at startup. Extensions can register Hooks, inject implementations, and start their own scheduled tasks.

`link_monitor` is the reference implementation: at import time it registers an `event_preprocessor` (refresh heartbeat for any OneBot event), two driver hooks (`on_bot_connect` / `on_bot_disconnect`), and its own scheduled task (actively probe after an event timeout, alert on probe failure without restarting). An extension can be integrated without changing the main business program.

## Time-Handling Conventions

SQLite writes `CURRENT_TIMESTAMP` in **UTC**. Every place that “compares a Python time with a DB timestamp” **must** use `memory/timeutil.py`; otherwise a fixed offset appears in non-UTC time zones.

Comparisons inside SQL (`julianday('now')` vs `julianday(col)`) use UTC on both sides and require no handling.

## Boundary Between the Two Ownership Levels

“Group” has two meanings in this project, and conflating them produces hard-to-diagnose confusion.

**QQ-group-owned** (the state of this current conversation):
- Message tail, consolidation checkpoint, short-term topic, session-compaction state
- Mute switch, proactive @ quota and cooldown, activity statistics

**Shared-space-owned** (long-term knowledge and identity about people):
- User profiles, long-term memories, atomic facts, FTS index
- Personality (system prompt), speaking strategy

**Boundary rule**: if sharing data between two groups could cause “the wrong response,” it must be owned by the QQ group; if sharing it between two groups means “the same knowledge of the same person,” it should be owned by the space.

The convention in code is that function parameters use `group_id: int` for QQ groups and `group_shared_space: str` for spaces. `resolve_space(qq_group_id)` is the only conversion entry point.

One legacy ambiguity remains: the `long_term_memories` (deprecated compatibility table) column is still named `group_id`, but **both writes and queries use the space identifier**. Renaming the column of a table that is about to be retired is not worthwhile, but this inconsistency must be known.
