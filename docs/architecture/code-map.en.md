# Directory Structure

[中文](code-map.md) | English · [Documentation](../README.en.md)

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
│   ├── capabilities/       # Capability declarations (filename is the domain, optional; see *.example)
│   └── participation/      # External scoring tables for proactive interjection
│
├── core/                           # Business-independent orchestration skeleton
│   ├── context.py                  # ChatContext: runtime carrier for one processing operation
│   ├── tasks.py                    # Task / Result / TaskGraph protocol (shared by four modules)
│   ├── pipeline.py                  # Pipeline orchestrator + prompt assembly order
│   ├── context_budget.py           # Chat context budget: hard bounds for input/output/estimation error within the 8192 working window
│   ├── planner.py                  # Restricted Planner: deep-reply-path orchestrator (trigger detection costs zero LLM calls)
│   ├── reply_gate.py               # Zero-token reply-necessity gate (proactive interjection only adds local state and cooldown)
│   ├── turn_runtime.py             # Lightweight session runtime: per-group state needed by gates (holds no chat content)
│   ├── logging_sink.py             # Structured JSON logs (stella.jsonl, consumed by the GUI)
│   ├── shutdown.py                 # Graceful shutdown: wait for in-flight background tasks (its own module for testability)
│   ├── stop_signal.py              # Stop sentinel: deploy writes, Bot reads and exits (deploy can import it standalone)
│   ├── vision.py                   # Image captioning: extract image sources → caption via the VISION role → merge into message text (optional, off by default)
│   ├── llm/
│       ├── base.py                 # Abstract LLM backend interface
│       ├── registry.py             # Endpoint × role registry: the only backend construction entry point in the project
│       ├── compat.py               # Parameter-difference adaptation for OpenAI-compatible endpoints (no vendor allowlist)
│       ├── lm_studio.py            # LM Studio backend (including retries and truncation warnings)
│       ├── openai_client.py        # Full chat-completions client (tools / images / streaming)
│       ├── usage_sink.py           # Usage reporting sink (truncation signals / token aggregation / cache hit rate)
│       ├── usage_store.py          # Daily ledger + daily budget decision (`llm_usage_daily`'s sole writer)
│       └── scheduler.py    # Model-level resource gate (FIFO serialization + queue observability)
│   └── runtime/                    # Unified facade runtime: the sole execution engine since §R.5 (pure Python, no cross-process bridge / no Node dependency)
│       ├── facade.py               # RuntimeFacade: unified entry owner and turn execution (the legacy STELLA_RUNTIME dual-path switch is retired; migration records in docs/migration/cortico/)
│       └── turn_service.py         # Per-turn execution service: evidence injection and prompt assembly (the knowledge-evidence section renders here)
│
├── capability/                     # Capability layer (see docs/capability-system.en.md)
│   ├── registry.py                 # Capability / Provider / registry singleton + health-based backoff
│   ├── loader.py                   # config/capabilities/*.toml → registry
│   ├── hooks.py                    # activate_capabilities pre-hook (pipeline integration point)
│   ├── inventory.py                # Structured capability snapshot for status/deploy capabilities
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
│       ├── astrbot.py              # Automatic llm_tools → Provider derivation + bootstrap
│       ├── knowledge.py            # knowledge.search capability wiring (when KNOWLEDGE_ENABLED)
│       └── mcp.py                  # MCP Manager start/stop + Provider Runtime wiring
│
├── knowledge/                      # Standalone knowledge-base subsystem (see docs/knowledge-base.md)
│   ├── domain.py                   # Domain model: libraries/documents/versions/grants + citation value objects
│   ├── acl.py                      # The single ACL decision entry (user/group/space tri-state subjects)
│   ├── lifecycle.py                # Document lifecycle state machine (draft→review→published→archived)
│   ├── schema.py                   # Standalone knowledge.db schema (zero overlap with agent_memory.db)
│   ├── store.py                    # Sole storage read/write entry + atomic version activation
│   ├── parsers.py                  # Markdown/TXT/PDF/DOCX/URL import parsing (with locators)
│   ├── chunking.py                 # Paragraph-atomic chunking (locator inheritance)
│   ├── ingest.py                   # Ingestion pipeline: parse→chunk→encode→index-ready (worker thread)
│   ├── fts.py                      # FTS5 tokenization (shared by write and query sides)
│   ├── embedding.py                # KB vector encoding + fingerprint locking (reuses the memory embedding service)
│   ├── retrieval.py                # BM25+dense dual channel → RRF fusion → bounded evidence
│   ├── service.py                  # Facade: role APIs / publication flow / ACL-enforced retrieval / status surface
│   └── isolation.py                # Memory isolation guard (evidence must never become a memory candidate)
│
├── skills/                         # Anthropic-style task skill layer (SKILL.md; see docs/skills.md, SKILLS_ENABLED off by default)
│   ├── catalog.py                  # Skill catalog: discovery / quarantine / plugin-scoped refresh
│   ├── orchestrator.py             # Selection and invocation orchestration (budgets / timeouts / output truncation)
│   ├── runtime.py                  # Runtime assembly (wired during bot.py startup)
│   ├── audit.py                    # Audit events (logs/skills_audit.jsonl)
│   └── runners/                    # Controlled execution backends (docker sandbox runner)
│
├── memory/                         # Memory system core
│   ├── SYSTEM.md                   # Bot system prompt
│   ├── schema.py                   # Schema migrations (versioned, currently v19) + source enum
│   ├── migrations.py               # Versioned structural and data migrations
│   ├── space_merge.py              # Space merging: fold several spaces' memories/profiles into one (deploy space-merge)
│   ├── timeutil.py                 # Parse DB timestamps uniformly as UTC
│   ├── text_similarity.py          # Content similarity and merging (single source of truth)
│   ├── cache_keys.py               # Single source of cache keys (shared by session-context / retrieval layers, no circular deps)
│   │
│   ├── pre_processors.py           # Message persistence, short-term context, user-context assembly
│   ├── session_context.py          # Session-compaction state and decisions (pure logic)
│   ├── session_compact.py          # Session-compaction execution (fetch messages, call LLM, write back)
│   ├── post_processors.py          # Output parsing, composure-break filtering, line splitting, thought logging
│   ├── prompt_builder.py           # Memory and context → partitioned Prompt
│   │
│   ├── cost_gates.py               # Cost gates: free local pre-screening before consolidation (Tier 1, pure functions, zero I/O)
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
│   ├── addressing.py               # User addressing preferences: normalization, validation, persistence (v14 table)
│   ├── addressing_intent.py        # Addressing-intent recognition: rule pre-screening + embedding semantics (returns structured requests only)
│   ├── expression_learning.py      # Expression and interjection-outcome learning: async settlement after a reply is sent (zero LLM)
│   ├── expression_store.py         # Separate storage for expression learning (“how to say it well”, apart from the memory system)
│   ├── participation/              # Proactive interjection Participation Decision Layer
│   │   ├── decision.py             # Participation decisions and modes
│   │   ├── signals.py              # Group-chat signal extraction
│   │   ├── scorer.py               # Participation scoring
│   │   ├── state.py                # Topic and group state
│   │   ├── tables.py               # External TOML scoring-table loader
│   │   └── observability.py        # Decision logs and observability
│   │
│   ├── trace.py                    # Memory decision tracing
│   ├── benchmark.py                # Memory Benchmark runner
│   ├── benchmark/                  # Retrieval-layer cases + _fixtures (including positive consolidation benchmarks)
│   └── db_cleaner.py               # Dirty-data cleanup + scheduled message-table pruning
│
├── memory_rust/                    # Rust retrieval backend for MEMORY_BACKEND=rust (published as a separate wheel, see docs/memory-rust-backend.md)
│   ├── backend.py                  # Python-side wrapper (BACKEND_API_VERSION negotiation)
│   ├── selector.py                 # Engine selection (wheel probing + legacy shadow/strict switch compatibility)
│   └── native/                     # PyO3/maturin sources (schema.rs embeds the SQL)
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
│   ├── init_wizard.py              # Configuration wizard and answer files
│   ├── migrate.py                  # Old-install import and database upgrade
│   ├── plugin_check.py             # Plugin specification checks
│   ├── plugin_scaffold.py          # Capability draft and embedding measurement
│   ├── capability_view.py          # Capability inventory query and rendering
│   ├── manifest.py                 # Release-package manifest
│   ├── env_schema.py               # settings.py → GUI configuration form schema
│   └── __main__.py                 # Subcommand orchestration; domain logic stays in modules
│
├── stella_project/plugins/bot_main/
│   ├── ai_gateway.py               # QQ event listener, Pipeline assembly, proactive-speaking scheduling
│   ├── status_api.py               # Local status interface (loopback, for deploy status / GUI)
│   └── config.py                   # Plugin configuration (pydantic)
│
├── cli/                            # stellacli: local / Docker orchestration and rendering layer
│   └── src/                        # Rust CLI; delegates domain logic to deploy / Compose
│
├── runtime-manager/                # Rust "Stella Runtime Contract" component supervisor (schemas/ contract + src/, optional runtime)
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
├── scripts/                        # Development tools, generators and CI gates
│   ├── probe_consolidation.py      # Consolidation probe / positive-case regression benchmark
│   ├── sample_windows.py           # Stratified sampling of message windows from the real database
│   ├── probe_embedding.py          # Embedding service probe
│   └── build_embedding_fixture.py  # Build benchmark vector fixture
│
├── release_assets/                 # Release artifact templates and release verification (quick-start READMEs, release-notes template, SHA256SUMS/manifest semantics, VM validation matrix)
│
├── stella-installer/               # v1 desktop installer (Tauri 2 + Rust, native HTML/JS; frozen at tag gui-v1-final)
├── dashboard/                      # v2 control-plane frontend (Vue 3 + Vuetify 3 + TS; shared by browser and desktop shell)
├── webui/                          # v2 control-plane backend (FastAPI sub-app on the same NoneBot port; serves dashboard/dist)
├── desktop/                        # v2 desktop shell (Tauri 2; embeds the panel + narrow-contract start/doctor)
├── openspec/                       # WebUI API contract (openapi-v1.yaml)
├── tests/                          # pytest tests
├── docs/                           # Task-oriented documentation
│   ├── agent/                      # On-demand coding-agent rules
│   ├── guides/                     # Deployment and usage
│   ├── architecture/               # Modules, flows, data boundaries
│   ├── reference/                  # Settings and plugin contracts
│   ├── development/                # Tests, migration, release, debugging
│   ├── history/                    # Archive navigation
│   └── plans/ reports/ migration/  # Original dated evidence
├── design_docs/                    # Design process records (specifications/checkpoints/defect reports/logs/test checklists)
└── _deprecated/                    # Deprecated code and old database archive (gitignored)
```
