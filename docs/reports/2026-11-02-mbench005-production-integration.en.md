# MBENCH-005 stage report: memory reliability stack productionization (gray integration)

- Date: 2026-11-02
- Branch: `codex/memory-benchmark` (PR #127, draft)
- Status: **integration complete; production defaults unchanged** (both flags default off; gray rollout is a user step)
- Prerequisite: MBENCH-004 P4 acceptance (conditionally approved, docs/reports/2026-11-02-mbench004-p4-production-validation.en.md)

## Deliverables

| item | implementation | production default |
| --- | --- | --- |
| T3 pack representation | `memory/prompt_builder.py`: with `MEMORY_PACK_METADATA_MODE=full`, chat-material entries gain `｜确认 YYYY-MM-DD` (data from existing memory-row columns, zero extra queries) | off (byte-compatible, pinned by tests) |
| sufficiency verifier | `memory/sufficiency_guard.py` (new module): ROLE_EXTRACT judges three states over the pack; `MEMORY_SUFFICIENCY_GUARD_MODE=off/shadow/enforce`; wired in turn_service.prepare_turn | off (the code path is not entered) |
| abstention semantics (enforce) | INSUFFICIENT hard short-circuit: fixed reply via the normal delivery chain (`delivery_source_kind=memory-sufficiency-abstention`); AMBIGUOUS appends a conservative-answering directive to the memories section | — |
| runbook | `docs/guides/memory-tuning.en.md`: the P4-6 validated .env stack, gray order, rollback conditions (revert on >5pp regression) | — |

## Reliability design (all fail-open)

Every unmet precondition releases the reply: no ROLE_EXTRACT backend, daily budget blocked
(`budget_blocked`), empty pack, call error/timeout, unparseable verdict (conservative
AMBIGUOUS → directive only). Tests cover five fail-open paths and the wiring behavior of
shadow/enforce/off (tests/test_memory_reliability_flags.py, 13 cases).

## Compatibility hard gate

With flags off, `build_v2_named_sections` output is **byte-identical** (existing
byte-compat / prefix-stability suites pass unchanged: test_multi_user_identity 15 passed,
test_prompt_cache_prefix etc., 44 passed total). The memory_eval package is untouched.

## Known items (recorded honestly)

1. **Pre-existing test-order interference (not introduced by this PR)**: running
   `tests/test_attribution_wiring.py` followed by `tests/test_memory_eval.py` in one
   process hangs on a message_flow queue thread (minimal pair reproduces; reproduces even
   with this PR's changes stashed; single files and most combinations are green).
   Reproduction command and root-cause location (flow thread stuck on queue.get) recorded;
   the fix belongs to test-infrastructure work, not this PR.
2. No production user_id→name mapping exists (explored): T3 attribution uses the existing
   `用户(uid)` convention; `conversation_identity.subject_alias` (self-introduced aliases)
   is a future enhancement.
3. The sufficiency.guard node is not registered in flow_catalog (unregistered nodes degrade
   gracefully to UI-unmapped), avoiding the manifest cascade; add later if UI presentation
   is wanted.

## Acceptance mapping (P4-6 recommendations → this PR)

- Per-item env flags ✓ (weights/gate/threshold are already .env config; the runbook lists the validated values)
- Defaults do not change production behavior ✓ (off byte-compat tests)
- Rollback conditions documented ✓ (runbook: revert the flag on >5pp regression)
- P4-2 judge human review: list ready, **NOT VERIFIED** (user step)

## Gates

tests/test_memory_reliability_flags.py 13 passed; existing regressions green in proven
groupings (44+15+32); `ruff check .` clean; `check_docs.py` 123 files / 0 errors.