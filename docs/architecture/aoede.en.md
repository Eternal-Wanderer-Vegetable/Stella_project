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

## Stage two: unified opportunity pipeline (S2-02...S2-03 landed)

- **Opportunity/timing layer** (`aoede/opportunity.py`): one in-flight
  opportunity per conversation; each valid human message advances the
  context revision, resets the silence window and merges (original expiry
  kept); cancellable debounce (internal 3s) + TTL (internal 15s) with DROP
  at expiry. Hard preflight covers only the master switch, mute, sleep and
  wakeup grace; the old dice and 15-message gate no longer gate this path,
  while the 600s cooldown stays as an internal safety floor enforced at
  fire time. `memory=[]` is never a prerequisite: context-only
  participation proceeds normally.
- **One-shot verification** (S2-01): Mneme owns attempts + rejection
  tombstones (`mneme/verification.py`, schema24). Reservation is written
  before send; ACK sets deadline = ack+300s; binding is conservative (same
  conversation, correct subject, explicit reply to a question fragment);
  DENIED/UNCLEAR/UNANSWERED settle terminally with a tombstone and a CAS
  candidate rejection; the consolidator and the promotion gate both check
  old-source replay while legitimate new evidence may open a new
  generation; confirmations record the relation only and never
  auto-promote. User-level no_reply backoff and naturalness skips are
  social signals and never clear tombstones.
- **Persistent budget** (`aoede/budget.py`, S2-03): the single user knob
  `PROACTIVE_FREQUENCY` (0-6 per hour, default 1.0; R=0 is an absolute off
  switch for ordinary proactive participation and autonomous sleep/wakeup
  announcements). Token bucket capacity 1, starts empty, refills on UTC
  wall time; speak, verification ASK and autonomous announcements share one
  bucket per conversation; commit on ACK, release only when nothing was
  delivered, conservative consume on UNKNOWN; store outage fails closed.
  Passive replies and user-scheduled tasks never touch the bucket.
- The timer (since S2-02) only does sleep announcements, opportunity
  recovery and fair verification-ASK submission - no verification priority.

Known limits (as of 2026-11-04): UNKNOWN settlements on the announcement
and speak paths are conservative consumes without automatic retry. The local
Windows `_native.pyd` exports API 4/schema 24 and is selected by the Rust
selector; a temporary-database fullchain passed native retrieval smoke and
Python/native promotion parity (`differ=false`). An old wheel refuses schema
24 on contract mismatch and safely falls back or errors according to mode.
This local check does not certify the Release payload, a clean Windows VM, or
install/rollback acceptance. The acceptance matrix lives in plan section 8.
