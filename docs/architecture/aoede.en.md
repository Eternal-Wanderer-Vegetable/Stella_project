# Aoede: Proactive Participation Subsystem

[中文](aoede.md) | English · [Architecture map](README.en.md)

Aoede is the proactive participation subsystem ("whether, when, and to whom
to speak", 2026-11-03 plan §3): opportunity/timing/budget/one-shot
verification scheduling. It talks to the memory subsystem [Mneme](mneme.en.md)
only through the neutral ports in `stella_contracts/aoede.py`; neither side
imports the other.

## Package layout (canonical since S1-02)

| Module | Responsibility | Former location |
| --- | --- | --- |
| `aoede/controller.py` | activity, recent speech, transient skips | `memory/proactive.py` |
| `aoede/gate.py` | hard admission `can_speak` / `can_speak_for_scheduled` | `memory/proactive_gate.py` |
| `aoede/storage/legacy_state.py` | legacy quota/mute/announce state (schema23 compat) | `memory/proactive_state.py` |
| `aoede/verification/target.py` | proactive @ target selection | `memory/proactive_target.py` |
| `aoede/prompts.py` | proactive instruction prompts, SKIP marker | `memory/proactive_prompt.py` |
| `aoede/contract.py` | verification contract orchestration | `memory/proactive_contract.py` |
| `aoede/participation/` | participation scoring decision layer | `memory/participation/` |
| `aoede/host.py` | host injection surface (bot/send/observability/engine) | new |
| `aoede/service.py` | proactive speak orchestration (moved from ai_gateway) | `ai_gateway` proactive region |
| `aoede/verification/service.py` | proactive @ orchestration and contract recheck | `ai_gateway` verification region |

## Assembly and compatibility

- `ai_gateway` keeps scheduler registration, adapter discovery
  (`_sole_timer_qq_bot`) and thin delegates; the timer tick body lives in
  `aoede.service.proactive_timer_tick`.
- Host dependencies are injected explicitly via `aoede.host.ProactiveHost`;
  test-replaceable symbols (`can_speak`, `get_proactive`, `pick_target`,
  `DB_PATH`, ...) are wired as lambdas that resolve gateway module
  attributes at call time, so existing monkeypatch contracts keep working.
- `memory.proactive*` / `memory.participation` are explicit aliases to this
  package: they self-replace `sys.modules` on import so legacy and canonical
  imports resolve to the same module object (singletons, caches and
  monkeypatch targets stay unique). The compat layer is kept for at least
  one rollback release cycle; removal needs its own gate.
- Task registries: proactive background tasks register through
  `aoede.service.background_tasks` and the host `register_task` hook; the
  assembly layer drains them on shutdown. No second scheduler.

## Stage two (not implemented yet)

The context-first unified opportunity pipeline
(`ParticipationOpportunity`, debounce, SPEAK/WAIT/DROP), the one-shot
verification persistence and the `PROACTIVE_FREQUENCY` budget land in
stage two per the [plan](../plans/2026-11-03-gitnexus-plan-aoede-mneme-proactive-redesign.md)
§6.2–6.5; contract types are already frozen in `stella_contracts/aoede.py`.
