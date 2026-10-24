# Corona / Nucleus Implementation CN05 — Configuration Transactions, Apply Operations, and One Recovery Attempt

Date: 2026-10-23 (Asia/Shanghai) · Branch: `codex/corona-nucleus-implementation` · CN05 base: `ff9d1bc`

**Implementation package: code and focused regressions are complete; the full Python gate is NOT GREEN, so CORONA-IMPL remains in progress / NOT READY.** The legacy entry remains the default. This package does not move business routes or migrate business databases.

## GitNexus and edit risk

GitNexus 1.6.12 was aligned with the CN04 HEAD before editing. Upstream impact for `webui/services/envfile.py:write_values` was **CRITICAL: 12 impacted / 6 direct callers / 6 processes / 2 modules**. This shared writer was left untouched; Corona's configuration transaction uses its own CAS, journal, and atomic replacement path. `webui/routers/config.py:config_update` returned UNKNOWN/0 because the route is decorator-registered; source inspection confirmed the router mount in `webui/app.py` and the `config_service.update` → `envfile.write_values` path. `build_config_revision` was UNKNOWN/0; source references confirmed use by the new config store and existing contract tests. Its new text override is only for candidate `.env` preflight and does not alter the legacy writer.

`CoreSupervisor.start` was LOW (4 visible direct graph callers; context reported six calls omitted because receiver types could not be resolved, so actual impact may be higher); `_run` was LOW / 5 impacted / 1 lifespan process. Their context was checked before editing. No HIGH/CRITICAL entry point needed editing for this package. GitNexus is a lower bound; dynamic routes, decorators, and unresolved type edges were supplemented by source inspection.

## Implementation

- Added `corona.config_store`: instance-private SQLite control metadata, revision CAS, idempotency keys, AST-derived settings schema plus explicit provider/OneBot fields, redacted sensitive values, external-edit conflict detection, immutable revision files, and a PREPARED/COMMITTED `.env` journal. Replacement uses a private unique temporary file, fsync, and atomic rename. Startup recovery handles before/after replacement, deletion, and rollback, and refuses to overwrite a later external edit.
- Candidate configuration is preflighted without touching the active file using `build_config_revision(source_text_overrides={".env": ...})`. Empty values mean inherit/delete; profile overlays and environment-source changes are conflict-checked against Corona saves.
- Added `corona.operations`: apply/restart/core start/stop share one serialized active-operation slot and persist acceptance, idempotent responses, phase events, and resumable event sequence numbers. Apply validates before draining/stopping the old generation, starts the target revision, and requires an exact ready identity/revision match. Failure attempts recovery to the last applied configuration at most once; terminal `rolled_back` is distinct from `succeeded`. Added `core_reachable` for an identity-bound health probe.
- Added `corona.recovery` and startup wiring: select the target or previous revision from persisted operation phase after a crash, avoid duplicate core startup, and finalize pending recovery only after observing the supervisor's actual startup state.
- Added authenticated Nucleus management APIs: backward-compatible flat-key `PUT /api/v1/config` with revision If-Match and Idempotency-Key; apply/restart/start/stop acceptance with operation IDs; status, schema, provider, platform/OneBot settings, and operation snapshot/SSE. Secret fields expose only whether a value is configured.
- The default launch remains legacy; CN11 owns the switch. Real-process apply tests exposed that the supervisor snapshot retained the prior revision ID for a new generation; `_run` now updates snapshot revision when startup begins, and subprocess tests cover successful target startup and failed target startup followed by recovery.

## Acceptance and verification

| Command / check | Result |
| --- | --- |
| Corona config/transaction/operation/API/recovery and Nucleus snapshot regressions | `.venv/bin/python -m pytest tests/corona tests/nucleus/test_snapshot_driver.py -q`: **40 passed / 6.43s**. Covers CAS/idempotency, inheritance deletion, external-edit conflicts, hard exits around PREPARED/replacement and restart recovery, single active operation, one-time rollback, API redaction/conflict, and real fake-core subprocess success and target-start failure. |
| `.venv/bin/ruff check corona stella_bootstrap tests/corona` | Passed. |
| `.venv/bin/python -m compileall -q corona stella_bootstrap` | Passed. |
| `.venv/bin/python scripts/generate_message_flow.py --check` | Passed; `message-flow.982a65f5aef2.json` matches. |
| `.venv/bin/python scripts/check_docs.py` | **119 files / 1,280 local links / 577 anchors / 0 errors** before this report; rerun after final state updates. |
| Full Python suite (isolated `$STELLA_HOME=/tmp/stella-cn05-full-pzQE5n`, with `memory/` pre-created) | **4072 passed / 29 skipped / 4 failed / 1 warning / 251.38s**, NOT GREEN. Failures: `test_subprocess_ack_pauses_claim_then_allows_fake_task_once`, `test_identity_mismatch_returns_no_input_not_other_bot`, `test_custom_endpoint_wire_api_chat_rejected`, and `test_usage_today_shape`. Each exact node passed alone with a fresh isolated home (**4 passed / 6.03s**); full-run ordering/shared-state cause is unknown, so these isolated passes do not turn the full suite green. |
| Data boundary | `STELLA_HOME` was unset before testing; full and focused suites used pytest temporary paths and an explicit isolated `/tmp` home. No user configuration, chat, or production database was read or changed. No real model, Bot, QQ/WebChat, or deployment service was started. Windows/macOS/BSD clean VMs, Docker, product startup/upgrade, live model/platform, and release acceptance remain NOT READY. |
| Staged GitNexus `detect-changes --scope all --repo Stella_project --limit 1000` | **17 files / 17 symbols / 13 affected processes / HIGH**. |
| Staged GitNexus `detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | **182 files / 720 symbols / 88 affected processes / CRITICAL** (cumulative CN00–CN05). |
| GitNexus output completeness | `all` and `compare` ran separately and serially; neither showed a PARTIAL/truncated marker. Symbol/flow listings have display caps, but aggregate counts and risk are complete. |
| `git diff --cached --check` | Passed. |

## Next stage

CN06: move and assign every WebUI route/service, proxy business output through Corona, and keep business database access in Nucleus. Complete the final staged graph gates and commit this package before starting CN06 from the new HEAD. The legacy launch remains the default.
