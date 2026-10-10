# Message Processing Flow

[中文](message-lifecycle.md) | English · [Documentation](../README.en.md)

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
| @ reply | Group is allowlisted + Bot is @ mentioned + contains text¹ | `reply` | `""` |
| Proactive @ | Scheduled check hits and selects an active user | `reply` | `proactive_at` |
| Proactive interjection | Scheduled check hits and probability curve passes | `proactive` | `proactive_join` |
| Plugin dispatch | Group is allowlisted + not a self-echo + message is non-empty | — | — |
| Runtime toggle | Administrator @ mentions the Bot + matches a toggle keyword | — | — |
| Capability query | Group is allow-listed + @ mentioned + matches a phrasing such as “what can you do” | — | — |

The three conversation paths share one Pipeline and use `ChatContext` fields to distinguish behavior. Each group has one `asyncio.Lock`, ensuring that only one inference runs in a group at a time.

> ¹ When the `VISION` endpoint is bound (`LLM_ROLE_VISION_ENDPOINT` other than `none`), "contains text" relaxes to "contains text or an image" — an image-only @ enters the flow as a `[图片]` placeholder and a pre hook supplies the caption. When unbound, behavior matches the previous build: image-only messages neither trigger a reply nor get persisted (see `core/vision.py::vision_available()`).

The threshold for plugin dispatch is deliberately much broader than for @ replies (`astrbot_compat.pipeline.should_dispatch` makes the decision): upstream AstrBot runs plugin filters once for every message, and each filter decides whether to wake up. The threshold is “the message has a segment,” **not** “the message has plain text.” A mini-program card shared from a mobile device contains only one `json` segment; checking for plain text would block the entire message outside the plugin layer, so handlers such as `@event_message_type(ALL)`, which specifically exist for non-text messages, would never receive the event (measured on 2026-08-25).

Proactive @ and proactive interjection are **mutually exclusive**: the scheduled task first attempts a proactive @, and skips the interjection if it hits; only one message is sent per round.

Admission for proactive paths (proactive @ / proactive interjection) uniformly goes through `memory/proactive_gate.py`'s `can_speak(group_id, kind)`, which checks six items in order:

```
Master switch → per-path switch → runtime mute → sleep period → wake-up buffer → group cooldown → new-message threshold
```

The return value includes a reason string, making it possible to investigate “why did it not speak this time?” Consolidating this into a single entry point has a reason: these conditions were previously scattered across `proactive_speak_job`, `_proactive_at_user`, and `should_speak`, so every added condition required changes at three call sites.

Beyond the gate there is also a zero-token **reply-necessity gate** (`core/reply_gate.py`): hard triggers (being @ mentioned) pass straight through, while the proactive-interjection path only adds local state and cooldown constraints. The per-group runtime state it relies on lives in `core/turn_runtime.py` — it holds no chat content and makes no LLM calls.

The probability roll for topic interjections is **not inside the gate**. It is unique to the join path, so the caller rolls it after the gate passes (proactive @ has quota and user-level cooldown constraints and does not roll).

**@ replies do not go through the gate.** They are answered normally when the Bot is @ mentioned during sleep or mute periods.

> Priority relationship of the five listeners (smaller numbers execute first):
>
> | Listener | priority | block | Responsibility |
> |---|---|---|---|
> | `group_silent_listener` | 0 | No | Persistence (must be first, see above) |
> | `toggle_handler` | 1 | Yes | Runtime toggle commands |
> | `capability_handler` | 1 | Yes | Capability query (“what can you do”) |
> | `plugin_handler` | 2 | No | AstrBot plugin dispatch (see [compatibility layer](integrations.en.md#astrbot-plugin-compatibility-layer)) |
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
describe_images_hook   (60)  → ctx.image_captions: captions images into "图片内容：…" and merges them into ctx.message
                               (active only when VISION is bound; returns immediately otherwise)
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

**`describe_images_hook`** (`core/vision.py`; see [configuration.en.md · Image Recognition](../reference/configuration.en.md#image-recognition-vision-captioning)): only active when the `VISION` role is bound to an endpoint. It extracts image sources from the message (including images inside a quoted message, controlled by `VISION_INCLUDE_QUOTED`), calls a vision model through the `VISION` role's gate for a one-line caption per image, appends them as “图片内容：…” to `ctx.message`, and rewrites the persisted `[图片]` placeholder by `msg_id` with the captioned text. Images that fail, time out, or exceed the size limit degrade to the `[图片]` placeholder without blocking the reply; captions are cached in an in-process LRU so a re-sent URL is not captioned twice.

After the pre hooks and before the model call there is also a **Restricted Planner** deep path (`core/planner.py`): the vast majority of messages never enter it — it wakes only when the zero-LLM local `detect_trigger` hits one of its start conditions (historical reference, topic ambiguity, and similar), allowing a deep memory query to supplement the context, with a hard per-turn cap on LLM calls (`PLANNER_MAX_LLM_CALLS_PER_TURN`). A Planner exception only degrades to the fast path (a few supplementary memories fewer); it must never swallow the reply. When it decides “not enough information yet” (`PLANNER_PROACTIVE_WAIT_ENABLED`), the turn may skip replying and wait for subsequent messages to re-drive it.

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
> | `LOCAL` | 1 | Chat replies, session compaction, candidate extraction, Comes tool loop, Router Level 2, image captioning (when `VISION` is bound to `LOCAL`), embedding encoding (`MEMORY_EMBEDDING_GATE=auto`) |
> | `EXTRA` | 1 | Phase 1 of two-phase consolidation |
>
> Strict FIFO applies within one resource (`asyncio.Lock`'s wait queue is FIFO), while different resources can truly run concurrently. If a role is rebound to an online slot (for example, `LLM_ROLE_CHAT_ENDPOINT=ONLINE_CHAT`, with default concurrency 4), it leaves the `LOCAL` queue. This is the source of the throughput gain from going online. See [configuration.en.md · Endpoint and Role](../reference/configuration.en.md#endpoint-and-role-two-layer-configuration) for configuration.
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

After the reply is sent, `memory/expression_learning.py` settles learning asynchronously in the background (whether the user kept responding, reused Stella's phrasing, used emoji, corrected it, or ignored a proactive message): the reply path itself only calls `on_reply_sent` to register and spawn the task (microsecond-level return); learning makes zero LLM calls, and a failure affects learning only, never chat. Samples and statistics live in a separate `expression_store`, apart from the memory system (“what is known”).

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

> **Consolidation is preceded by a free local pre-screen** (`memory/cost_gates.py`, Tier 1): online endpoints charge by token while consolidation is a frequent background task; this step answers “is this batch worth spending money consolidating,” with all criteria running locally at zero cost and zero I/O.
>
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
