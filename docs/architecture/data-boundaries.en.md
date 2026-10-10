# Key Data Structures

[中文](data-boundaries.md) | English · [Documentation](../README.en.md)

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
| Task scheduling | `route` `task_results` `tool_summaries` `knowledge_evidence` |
| Platform handles | `raw_event` `bot` |

`group_id` is always the actual QQ group number; `group_shared_space` is automatically populated by `config.spaces.resolve_space()` and identifies the ownership of memories and profiles. They must not be conflated.

`raw_event` / `bot` are **opaque handles**: when Comes calls an AstrBot tool, the tool handler internally uses `event.send()` / `event.bot.call_action()`, so these must be the real objects and cannot be replaced by equivalent substitutes. `core` does not interpret their types or call any methods; it only passes them from the ingress layer to the capability layer. Both are marked `repr=False`: the `repr` of a OneBot event expands the entire message and sender, so repr-ing `ChatContext` would flood the logs.

The type annotation for `route` is `Any` rather than `Route`: `core` is a “business-independent orchestration skeleton” and should not import `capability`; a reverse dependency would create a cycle.

### Main Data Tables

**Conversation and memory ownership are separate**. The tables below retain historical group-field names; message, short-context, and consolidation storage also supports private/WebChat conversations. SPACE memory can be shared across configured groups; PERSON memory additionally requires matching owner, subject, and audience. Shared spaces never merge conversation tails.

| Table | Ownership | Purpose |
|---|---|---|
| `group_messages` | Conversation | Raw group messages (including `source_kind`) |
| `short_term_context` | Conversation | Per-group topic summary and key messages |
| `consolidation_state` | Conversation | Per-group consolidation checkpoint |
| `proactive_state` | QQ group | Proactive @ quota, cooldown, and backoff state |
| `group_runtime_state` | QQ group | Mute switch and sleep/wake announcement deduplication |
| `participation_topics` | QQ group | Topic lifecycle and current participation state |
| `participation_log` | QQ group | Per-decision Participation scores and outcomes |
| `memory_candidates` | **SPACE/PERSON** | Memory candidates (including `occurrence_count` / `source_kinds` / `first_seen_at`) |
| `memories` | **SPACE/PERSON** | Long-term memories (including `usage_tags` / `visibility` / `behavior_rule`) |
| `memories_fts` | **SPACE/PERSON** | FTS5 full-text index (synchronized with `memories` by `mem_id`) |
| `user_profiles` | **Space** | Stable user profiles, primary key `(group_shared_space, user_id)` |
| `user_address_preferences` | **Space** | User addressing preferences (v14), primary key `(group_shared_space, user_id)` |
| `atomic_facts` | **Space** | Atomic facts split from long-term memories |
| `memory_traces` | Both | Memory decision traces (`group_id` records the trigger source; `group_shared_space` records the retrieval space) |
| `expression_examples` / `jargon_glossary` / `behavior_patterns` / `reply_effects` | **Space** | Expression and interjection-outcome learning (tables created independently by `expression_store`, outside schema migrations; `reply_effects` also records `group_id`) |
| `compressor_stats` / `compressor_state` | Global | Compaction statistics and throttling state |
| `llm_usage_daily` | Global | Daily LLM usage, primary key `(date, role, slot, model)` |
| `schema_meta` | Global | Schema version |

Schema uses **versioned migrations**: additive fields/indexes for simple changes, transactional rebuilds and validation for structural changes, preserving business data and backing up before migration. Run independently:

```bash
python -m memory.schema --dry-run   # Preview
python -m memory.schema             # Execute
python -m memory.schema --backup    # Backup only
```

> **Structural changes and data changes live in another module**: `memory/migrations.py` registers migrations by version (`migrate_v7` / `v8` / …), with one function and one transaction per version; only after success does it advance `schema_meta.version`. The add-column/create-table work in `schema._migrate()` is the final step of each migration. The current `SCHEMA_VERSION` is **18**; v7 (profile grouping), v8 (memory tables changed to space ownership), v13 (Participation topic/decision logs), and v14 (addressing-preference table) are registered in `memory/migrations.py`. v5 → the current version is fully automatic: rename columns + rewrite values as space names + rebuild profile primary keys + rebuild FTS + create Participation tables + validate, with a full-level rollback on failure. **New rule: every increment of `SCHEMA_VERSION` must be committed together with `migrate_vN` and a legacy-database fixture test.**
>
> Each migration writes `agent_memory.db.pre-vN-<timestamp>.bak` (the state before that migration). `stella_memory_backup.db` is “the first original database ever”; it skips creation when a backup already exists. When archiving the old database, move it together with that file, or the system will be left in a state that “looks backed up but is actually the wrong backup.”
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
