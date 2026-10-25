# AstrBot-informed multiplatform speaking and message-storage plan

[中文](2026-10-24-astrbot-multiplatform-adaptation.md) | English

Date: 2026-10-24, Asia/Shanghai. Feature: `XPLAT-ASTRBOT-RESEARCH`. Research and documentation only; no business code, configuration, database, or running service changes.

## Baseline and conclusion

Stella was synchronized to `main@3825f994cbec8e7633b2284e7f55271793c99fe5` using fetch/prune, checkout main and fast-forward. The initial worktree was clean; the former `codex/corona-nucleus-implementation@2d1eb73` was already contained in origin/main and its remote branch was deleted upstream. The final commit comparison at the research baseline was `0 0`; no history rewrite, stash application or local branch deletion was needed. New research documents and state records remain local, uncommitted and unpushed.

AstrBot sources were read through the GitHub connector at [ec77b16eec6096dc75c76292ca329af08766af14](https://github.com/AstrBotDevs/AstrBot/tree/ec77b16eec6096dc75c76292ca329af08766af14). These are source observations, not runtime acceptance. `STELLA_HOME` was unset; the read-only path resolver returned `/home/vegetable/repos/StellaData` without creating it. User configuration, credentials, chats and production databases were not opened.

Keep NoneBot, Stella's V2 identities and memory authorization. Adopt AstrBot's unified events, origin-based configuration routing, common pipeline and separation of platform history from model history. The priority is wiring non-OneBot business ingress and replacing QQ-number-only speaking/persona/session administration with trusted scene references. A framework or database replacement is unnecessary. This is an incremental follow-up to the [WP00–WP11 plan](2026-10-20-gitnexus-cross-platform-plan.md).

## How AstrBot controls speaking

[MessageSession](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/platform/message_session.py) represents an origin as `platform_id:message_type:session_id`. The platform ID is an adapter instance, not a platform type. [UmopConfigRouter](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/umop_config_router.py) matches components with empty/wildcard support and takes the first matching mapping entry. [AstrBotConfigManager](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/astrbot_config_mgr.py) selects a complete profile, falling back to default. It does not implement automatic field-by-field hierarchical merging.

[EventBus](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/event_bus.py) chooses the scheduler from the original origin, then applies member-context isolation for supported platform builders before pipeline execution. The manager's older comment says unique_session uses the default config, but the executed EventBus code uses the selected scheduler's config; source execution takes precedence.

| Concern | Observed implementation | Stella implication |
| --- | --- | --- |
| Waking | [WakingCheckStage](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/pipeline/waking_check/stage.py): prefixes, mentions, quoted Bot messages, private rules and plugin filters | Unify intent while adapters supply verified mention/reply facts |
| Access | [WhitelistCheckStage](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/pipeline/whitelist_check/stage.py): UMO or bare group ID, configurable admin exemptions, WebChat exemption | Use namespaced keys in Stella; bare IDs can collide |
| Service state | [SessionServiceManager](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/star/session_llm_manager.py): per-origin session/LLM/TTS preferences, enabled by default | Separate capture, direct replies and proactive speech |
| Rate control | [RateLimitStage](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/pipeline/rate_limit_check/stage.py): per-origin expiring queues/locks, stall/discard | Separate request and platform API limits; the implementation is not established as fixed-window by its comment |
| Active replies | [GroupChatContext](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/builtin_stars/astrbot/group_chat_context.py): group-only enablement, allowlist and probability | Keep Stella Participation and quotas; borrow common scoping |
| Output | [ResultDecorateStage](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/pipeline/result_decorate/stage.py) and [RespondStage](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/pipeline/respond/stage.py): prefix, mention, quote, segmentation, media and streaming | Resolve policy independently of transport capability |

Platform branches remain: normal segmentation excludes QQ official webhook, WeChat official accounts and DingTalk; merged forwarding is specific to aiocqhttp. Stella should use capability narrowing rather than scatter platform-name conditions. Member isolation is also limited to builders in EventBus, not universally supported.

## How AstrBot normalizes and stores information

[AstrBotMessage](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/platform/astrbot_message.py) carries string IDs, sender, component chain, plain text, timestamp and a raw platform object. Adapters create events consumed by the shared pipeline. [Telegram](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/platform/sources/telegram/tg_adapter.py#L491) includes topic IDs in the session with a General-topic exception; [Discord](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/platform/sources/discord/discord_platform_adapter.py#L287) uses channel IDs. Thread semantics remain adapter-specific.

| Layer | Storage |
| --- | --- |
| Model conversations | [ConversationV2](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/db/po.py#L72): conversation ID, platform ID, user_id carrying the origin, JSON model content, persona and token usage |
| Selection/preferences | [ConversationManager](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/conversation_mgr.py): multiple conversations per session, selected CID stored through [SharedPreferences](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/utils/shared_preferences.py), currently database-backed despite an older JSON description |
| Platform history | [PlatformMessageHistory](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/db/po.py#L246): platform/session, sender, JSON component projection and optional checkpoint, independent of model history |

[PlatformMessageHistoryManager](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/core/platform_message_history_mgr.py) stores path-free text, mentions and basic reply facts. Image/audio/video/file components become placeholders, so this is not a lossless media archive. It supports retention, pagination and deletion. The [builtin plugin](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/astrbot/builtin_stars/astrbot/main.py#L138) enables this path only for configured group history and excludes WebChat. Its Bot entry is created on the LLM-response hook, not proof of successful platform delivery. The history tool scopes queries to the current platform and origin; [tests](https://github.com/AstrBotDevs/AstrBot/blob/ec77b16eec6096dc75c76292ca329af08766af14/tests/unit/test_group_message_history.py) cover retention and safe projections.

Unified processing does not imply global user identity, merged contexts or automatic sharing of private long-term memory.

## Stella delta at the synchronized commit

Current source constants are memory schema **22**, native API **4**, verified in Python and Rust; older state text mentioning 19/3 is stale for this baseline. No deployed wheel was inspected.

| Area | Reuse | Missing integration |
| --- | --- | --- |
| Identity | [models](../../core/transport/models.py), [keys](../../core/transport/keys.py), [registry](../../memory/conversation_registry.py): c2/u2, parents/threads, aliases and internal session proxies | No production call to register_conversation_v2 found after graph and reference checks |
| Ingress | [Normalizers and AdmissionPolicy](../../core/transport/normalizers.py) | Generic normalizer is defined/exported but not wired into runtime ingress; [gateway](../../stella_project/plugins/bot_main/ai_gateway.py) handlers still use OneBot types and QQ rules; opaque scenes are conservatively rejected |
| Policy/persona | Existing mention/private controls, Participation, mute, quotas and capture gate | [spaces](../../config/spaces.py), [group management](../../webui/services/groups.py), [space management](../../webui/services/spaces.py) and background enumeration still depend on QQ IDs/qq_groups/ALLOWED_GROUPS |
| Delivery | [Outbound contracts](../../core/transport/outbound.py), target expiry, capability fallback and per-part receipts | Default exporter and [durable Bot resolution](../../stella_project/plugins/bot_main/transport_delivery.py) are OneBot-only; rate-limit fields alone do not implement an API scheduler |
| Storage | [record_message](../../memory/pre_processors.py) records namespaced identity and opaque platform IDs | No portable incoming component archive in NormalizedEvent; add safe components, attachment descriptors and cross-platform relations |
| Memory | [Ownership](../../memory/ownership.py), [sharing](../../memory/personal_sharing.py) and audience/source checks | Adapters must supply trusted subjects; shared persona/space cannot silently bind accounts or grant private access |
| Administration | Existing adapter configuration and connection status | [Conversation browsing](../../webui/services/conversations.py) still exposes mostly group ID, text and old msg_id; coordinate Corona and legacy contracts |
| Acceptance | [L0–L3 matrix](../../tests/platforms/adapter_matrix.json) | Zero of 32 rows is certified. Walle-Q/NTChat/Mail remain blocked by [policy](../../stella_bootstrap/adapter_policy.py); Heybox has a Python-version condition |

These wiring conclusions are limited to the inspected commit. Dynamic registries and future revisions require rechecking.

## Proposed contracts

The proposed `ResolvedConversationPolicy` is a future contract, not existing code. Resolve each field in this order: global defaults, platform template, connection defaults, bound profile, explicit scene overrides, expiring runtime overrides. Return the source and revision of each value. Treat false and empty collections as explicit; reject ambiguous same-level selectors. Threads inherit only declared parent defaults, never history tails or counters. Final capability/permission constraints cannot be widened by profiles, admins or personas.

Bind `policy_profile_id`, `persona_ref` and `memory_space` separately. Default persona behavior may reuse the existing space, but policy changes must not move memory, and shared personas must not merge sessions. Space sharing retains owner/subject/audience checks. Separate receive/capture, direct LLM reply, proactive speech, and actual delivery gates; keep capture denial's no-storage/no-replay behavior. New platforms start with proactive speech disabled. UI should show platform/connection/scene/thread, effective values and sources, revision conflicts and unsupported features; preserve QQ shortcuts. Do not enable wildcard platform-wide authorization by default.

Register a normalizer, ingress, capability provider, exporter, target codec and exact Bot resolver per platform. Reuse RuntimeFacade prepare/generate/finalize. The first batch should cover OneBot regression, Telegram, Discord and official QQ for representative private/group/channel/thread/window cases; verify their current protocol documentation during implementation. Generic opaque events may only use explicitly restricted event replies, with no guessed group permissions or durable routing.

Use the receiving Bot for event replies and the full persisted BotRef for background sends. Never select the first online Bot. Narrow adapter→instance→scene capabilities. Separate model/request quotas from account/target API limits; persist durable cooldowns/quotas and expire temporary reply routes. Unknown delivery is not automatically retried, and partial results retain every receipt.

Continue SQLite with existing group_messages/legacy read projections. Finalize any message_events/message_parts/message_relations DDL during implementation review; this plan assigns no schema version and runs no migration.

- Keep c2 conversation identity and u2 namespaced subjects, with display names descriptive only. Internal numeric proxies are not external IDs.
- Record event type/direction, opaque platform ID, source, UTC time, edits/retractions and ordered safe components. Never persist SDK objects, credentials or signed temporary URLs.
- Scope reply relations by connection/session/message; preserve unresolved targets and reauthorize cross-session references.
- Keep model contexts/compact watermarks and context branches separate from physical delivery destinations. Shared or per-member group contexts must not change the destination.
- Preserve SPACE/PERSON and owner/subject/audience/source checks. Unknown historical identity stays unknown; explicit reversible account linking is separate work.
- Separate generated intention, send attempt and API acceptance. Accepted is not received/read; unknown or partial failure is not successful delivery.
- Deduplicate only with trustworthy IDs and event versions, retaining edits/retractions. Missing IDs receive explicit local identities; identical text alone is not a duplicate key.
- Configure attachment availability/cache retention and quotas independently; keep history text readable after media credentials expire. Give platform history, model context and memory separate retention/deletion scopes and permissions. Model history tools cannot choose arbitrary connections.

## Implementation and acceptance

| Phase | Deliverable | Required evidence |
| --- | --- | --- |
| A | Actual WP wiring inventory and frozen transport/policy/Corona/legacy contracts | Platform levels, priorities, aliases, failure semantics and fresh upstream impact |
| B | Unified speaking policies and conversation/persona bindings | Save/readback, revision recovery, private/group/channel/thread controls, unchanged legacy QQ results |
| C | First platform normalizers/exporters/codecs/resolvers through RuntimeFacade | Real event fixtures through storage, stub generation and exact Bot/thread reply, collision negatives; then separate live runs |
| D | Safe message projection, relations, attachments, browsing and history tools | Temporary schema-22 migration dry-run/rollback/replay, Python/native parity, IDs/edits/reconnect/pagination cases |
| E | Participation/Scheduling/Cometa routing, limits and certification | Restart/offline/unknown/expiry cases, no duplicate or wrong Bot delivery, separate L0–L3 fixture/live and release evidence |

Order A→B→C→D→E, one feature at a time. C may initially use existing text storage; full multimedia/history support waits for D. Connections without proven storage isolation cannot participate in proactive memory. This research does not resume old XPLAT/CORONA tasks automatically.

Minimum scenarios include identical IDs across platforms and Bots, private/group collisions, Telegram topics, Discord channels/threads, opaque/Unicode/colon/leading-zero IDs, denied/unknown scenes, distinct capture/proactive/LLM switches, duplicate names, persona reuse with isolated memory, space reuse without private leakage, partial/unknown/expired/rate-limited sends, restart routing, unavailable media, edits/retractions and unauthorized history queries. Installation, graph reachability, fixtures, live models/platforms, QQ rollout, clean VMs and releases remain separate gates.

## Research evidence and limits

Baseline docs: `python3 scripts/check_docs.py` passed with 121 files, 1307 local links, 577 migration anchors and zero errors. GitNexus 1.6.12 `analyze --index-only --pdg --workers 1` succeeded at the synchronized source: 114602 nodes, 288471 edges, 1192 clusters, 796 flows. Ingress/policy/storage queries and generic/outbound/record contexts were inspected. A nonexistent ConversationRegistry class query was corrected to the actual module-level registry function.

Upstream impact: AdmissionPolicy.decide HIGH, 7 impacted/5 direct/3 roots; resolve_space CRITICAL, 29/13/6; record_message CRITICAL, 18/4/9, directly called by _record_bot_lines, handle_private_chat, record_group_chat and WebChat run_turn. Future implementation requires renewed warnings and analysis; riskSharedAxes does not waive risk. V2 registration UNKNOWN/0 and missing generic flows were checked against declarations, exports, handlers, assembly and references. New documents were absent/UNKNOWN with no existing references. The three state-file impacts were File LOW, referenced by AGENTS/workflow/history, with no processes; section-level fanout may still differ.

Coverage limits: 38 files above 512KB skipped; 3200/3400 candidate entries omitted, 952 callees skipped, 43 walks cut, 23 depth-capped traces, and callable candidate overflow may omit edges. No-edge and 796-flow results are not complete runtime coverage. Final docs/JSON/diff and all/compare graph results are recorded in [progress](../../progress.md).

Files: this bilingual plan and feature_list.json, progress.md, session-handoff.md. Temporary graph output is under `/tmp/stella-xplat-research-20261024` and `/tmp/stella-xplat-analyze-20261024.log`; durable conclusions, sources and commands are in the plan. No business tests, models, live platforms, QQ rollout, migrations, deployment or clean-VM acceptance were run. Research can be complete while multiplatform runtime readiness remains **NOT READY**. Next work requires a separate implementation request, beginning with A.
