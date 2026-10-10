# Current architecture additions in 6.1.0

[中文](overview.md) | English · [Documentation](../README.en.md)

## Current architecture additions in 6.1.0

- **Trusted ingress:** `core/conversation.py` defines `ConversationRef` for QQ group/private and WebChat; `memory/conversation_registry.py` allocates storage IDs. Runtime ownership, cancellation, traces, deduplication, and Cometa delivery use canonical conversation identity.
- **Personal memory:** `memory/ownership.py` defines SPACE/PERSON and audiences. Private facts default to PRIVATE_ONLY. `memory/personal_sharing.py` binds authorization to the owner, source message, and specific fact, using a copies ledger and cache revisions for revocation. Writing/sharing remain disabled by default.
- **Attribution:** envelopes retain author, recipient, reply/quote relations, signed platform IDs, and logical turns. `memory/conversation_projection.py` serves both tails and compaction; `memory/conversation_identity.py` stores source-bound local claims. `core/dialogue_attribution.py` validates structured reply plans and evidence.
- **Long tasks:** `cometa/` persists admission, leases, workers, workspaces, artifacts, and notifications. `capability/delegation.py` delegates outside the synchronous tool loop. Codex authentication is read from each managed backend home and configured on WebUI Providers.
- **Flow observation:** `core/observability/` records roots, spans, transitions, message I/O, lifecycle, and loss accounting. `webui/routers/flow.py` and Dashboard FlowPage provide queries, SSE, topology, and replay. Source-manifest reachability and recorded execution are presented separately.

The current branch uses memory schema **19** and Python/Rust backend API **3**. Migrations v15-v18 introduced conversation and personal ownership; v19 extends provenance review and derived-claim links. See [source contracts](../development/contracts.en.md); this describes branch source, not published artifacts or field acceptance. Knowledge, scheduling, Cometa, and observation databases version independently. Real QQ rollout and Rust ranking differences remain documented in the [index](../README.en.md).
## Layered Overview

```
QQ group messages / QQ private chat / WebChat
    ↓  OneBot V11 / NapCat
stella_project/plugins/bot_main/ai_gateway.py     ← Event ingress layer
    ↓
core/runtime/facade.py                           ← Ingress ownership and turn execution
    ↓
core/runtime/turn_service.py                     ← prepare → generate → finalize
core/pipeline.py                                 ← Hook registration and compatibility facade
     ↓
capability/*                                      ← Capability layer (Router decisions / Comes tool execution)
memory/*                                          ← Memory layer (write / promotion / retrieval / compaction)
     ↓
SQLite (STELLA_HOME/memory/agent_memory.db)
```

The five layers are independent: the ingress layer only adapts protocols and dispatches, the orchestration layer contains no business logic, the capability layer is unaware of personality and memory content, the memory layer is unaware of QQ, and the storage layer has migrations centrally managed by `memory/schema.py`.

The capability and memory layers are **parallel** branches. Both are activated by the same pre-hook in the orchestration layer, and communicate with each other only through `ChatContext`; they do not call each other.

`astrbot_compat/*` is a sixth component alongside them: it connects the AstrBot plugin ecosystem, providing tool execution for the capability layer (Comes → `llm_tools`) while also following an independent dispatch path (`plugin_handler`) to respond to plugin commands. It **does not participate** in memory or personality; see the [AstrBot Plugin Compatibility Layer](integrations.en.md#astrbot-plugin-compatibility-layer) section below.

> Conversation, user, and space identities are separate. Group storage IDs remain real group IDs; private IDs are allocated negative values, and WebChat reserves `-1`. Never derive conversation kind from the sign. Memory additionally enforces owner, subject, and audience.

Proactive interjection also has a **Participation Decision Layer** beside the memory layer: it extracts
recent group-chat signals, scores topic opportunity, relevance, and interruption risk locally, then
produces an `IGNORE` / `OBSERVE` / `CANDIDATE` / `ALLOW_LLM` decision and decides whether to pass
evidence to the generator. It does not replace the hard
gate in `proactive_gate.py` and does not call an LLM. External weights live in `config/participation/`;
decision logs go to runtime logs and the v13 `participation_log` table.

Addressing preferences form another small branch beside the memory layer: `memory/addressing.py` stores user-defined addressing preferences (the v14 `user_address_preferences` table, kept separate from `user_profiles.nickname` and ordinary memories), while `memory/addressing_intent.py` recognizes intents such as “call me X” from natural language — rules do the cheap pre-screening, an embedding decides semantics, and the module only returns structured requests; model output is never treated as an executable command.
