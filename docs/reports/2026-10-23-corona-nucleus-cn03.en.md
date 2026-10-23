# Corona / Nucleus Implementation CN03 — Independent Control Plane and Single-Core Supervisor

Date: 2026-10-23 (Asia/Shanghai) · Branch: `codex/corona-nucleus-implementation` · CN03 base: `73d7c60`

**Package status: CN03 implementation and local acceptance complete; CORONA-IMPL remains in progress / NOT READY.** The default `python bot.py` entry remains legacy. This package adds a separately launchable `python -m corona` control app, but launchers have not been switched; Windows and live-platform acceptance remain incomplete.

## GitNexus and edit risk

Before edits, the 1.6.12 / PDG index matched CN02 HEAD `73d7c60`; after source edits it reported 7 changed / 11 added. The dirty tree was not re-analyzed. Pre-edit upstream impacts:

| Target | Risk and impact | Notes |
| --- | --- | --- |
| `webui/app.py` | LOW, 3 impacted / 2 direct | Independent dev app and mount assembly; unchanged in this package. |
| `webui/auth.py` | **HIGH**, 20 / 17 | Configuration loading is deferred to `rate_limit_capacity()`; established auth/JWT contracts are preserved. |
| `webui/security.py`, `auth_file` | File LOW 22 / 4; symbol **CRITICAL** 15 / 4 / 5 flows | Removed import-time configuration binding; supports injected Corona home/TTL and lazy legacy settings. |
| `create_token`, `desktop_session_secret` | **HIGH** 5 impacted; LOW 4 / 2 | Token format remains compatible; desktop capability is excluded from Nucleus. |
| `webui.audit._append` | File MEDIUM 8 / 5; symbol **CRITICAL** 30 / 1 / 26 processes / 3 modules | Not modified or reused; Corona writes a separate password-free audit file. |
| `webui/static.py`, `source_build.py`, `config/instance.py`, `webui/mount.py` | LOW: 4/1, 1, 15/1, 1 | Static paths use explicit injection; source build accepts plain path arguments; identity path contract remains. |
| `NucleusLifecycle`, `_make_server`, `prepare_managed_environment` | LOW: 8/3, 2/1, 2/1 | Adds managed process-tree cleanup and owner-loss handling while preserving legacy mode and the shared shutdown deadline. |
| `get_current_instance_id`, `_force_shutdown_exit` | Missing / UNKNOWN in graph | Source and test references were checked; empty results were not treated as zero callers. |

The HIGH `webui.auth.py`, CRITICAL `webui.security.auth_file` / `create_token`, and audit `_append` impacts were disclosed before edits. The audit module was not changed. CN02 graph limits still apply: large-file skips; entry-candidate, callee, walk, and depth caps; and missing dynamic receiver / cross-language edges. New modules had no prior graph nodes, so tests supplement zero-caller results.

## Implementation

- Added independent Corona bootstrap, ASGI app, CLI, and a per-instance OS handle lock. Corona auth, control health, and core status do not depend on Nucleus availability. With browser management disabled, a loopback-only Corona health endpoint remains.
- `CoreSupervisor` manages one generation through desired/phase state and controller/generation/revision identity. Each launch gets a distinct capability; health must match identity and PID. Startup logs use mode 0600, errors are redacted, and failed generations use bounded crash retry. A failed core leaves Corona auth/static available.
- `ManagedProcessTree` uses a fresh POSIX session/process group, parent/child gate, Linux `PR_SET_PDEATHSIG`, and a cross-POSIX owner-watch pipe. Windows uses a kill-on-close Job Object; business startup is not released if assignment fails. POSIX uses `waitid(WNOWAIT)` to preserve group-leader identity until non-zombie descendants are confirmed gone, avoiding a PID/PGID reuse window.
- Nucleus starts its owner watcher before business assembly. Owner loss requests a bounded drain when a server exists; otherwise it kills the generation group immediately. Shutdown clears same-group descendants within the existing lifecycle deadline. It does not kill processes by name or target external services.
- WebUI auth/security/static/source-build now use lazy legacy configuration or explicit injection. Corona reuses the auth.json/JWT contract, with a separate audit log that does not contain passwords or tokens. The desktop-session capability is removed from the revision-derived environment sent to Nucleus.
- Restored temporary `social.db` isolation, schema setup, and cache cleanup in `tests/observability/test_message_flow_runtime.py::flow_db`. The first full run exposed that this fixture isolated only the trace DB while three delivery-fact tests wrote into the shared `STELLA_HOME`; this test-only change does not alter production social storage.

## Acceptance and verification

| Command / check | Result |
| --- | --- |
| `STELLA_HOME=/tmp/stella-cn03-final-targeted .venv/bin/python -m pytest tests/corona tests/nucleus tests/webui/test_webui_auth.py tests/webui/test_webui_mount.py -q` | **44 passed / 6.10s**; covers real fake-core success, import failure, hang, crash, foreign PID, crash after ready/retry, cross-process Corona lock refusal, owner-loss pipe, descendant cleanup, import fence, auth/static/loopback health, and existing Nucleus behavior. |
| `STELLA_HOME=/tmp/stella-cn03-flow-final .venv/bin/python -m pytest tests/observability/test_message_flow_runtime.py -q` | **16 passed / 1.80s**; isolates the social-store schema/cache and trace DB in each pytest `tmp_path`. |
| `.venv/bin/ruff check .` | Passed. |
| `.venv/bin/python -m compileall -q corona nucleus webui/auth.py webui/security.py webui/static.py webui/source_build.py` | Passed. |
| `.venv/bin/python scripts/generate_message_flow.py --check` | Passed; `message-flow.982a65f5aef2.json` matches source. |
| `.venv/bin/python scripts/check_docs.py` | 119 files / 1,275 local links / 577 anchors / 0 errors (rerun after report/state edits). |
| Full `STELLA_HOME=/tmp/stella-cn03-final-full .venv/bin/python -m pytest tests -q` | **4050 passed / 29 skipped / 2 failed / 251.81s**. Failures: `tests/webui/test_message_flow_api.py::TestFlowMessagesApi::test_running_trace_with_live_process_stays_running` (list `data` was null) and `tests/webui/test_webui_cometa.py::TestQueryAndControl::test_cancel_then_state` (401 vs 202). Each exact node passed when rerun alone. Isolated whole-module runs surfaced different trace-data / Cometa-auth failures; cause remains unknown, so the full suite is NOT GREEN. |
| `git diff --check` | Passed after report/state edits. |
| `node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project --limit 1000` | 24 files / 36 symbols / 7 affected processes / **HIGH**. Summary counts are complete; CLI prints the first 15 symbols and first 7 flows plus remainder counts; no partial/truncated marker appeared. |
| `node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | 163 files / 423 symbols / 65 affected processes / **CRITICAL** cumulative across CN00–CN03. Summary counts are complete; CLI prints the first 15 symbols and first 10 flows plus remainder counts; no partial/truncated marker appeared. |

Tests use only `/tmp` `STELLA_HOME` and pytest `tmp_path`; no user configuration, production DB, chat records or credentials were read or changed. No Bot, model, QQ/WebChat or deployed service was started. POSIX owner-loss and Linux real-process scenarios passed on this Linux host. Windows Job/ACL, macOS/BSD, Docker, clean VM and platform acceptance were not run, so cross-platform and product release remain NOT READY.

## Next

CN04: extend the versioned private Nucleus protocol, implement internal capability / actor identity forwarding, and add the local deploy control interface and health/error contracts without exposing business APIs through an unauthenticated path.
