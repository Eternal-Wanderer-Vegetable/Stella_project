# Corona / Nucleus Implementation CN04 — Internal Protocol, Identity Forwarding, and Local Control

Date: 2026-10-23 (Asia/Shanghai) · Branch: `codex/corona-nucleus-implementation` · CN04 base: `38ceb89`

**Package status: implementation and focused acceptance complete; the full Python gate is NOT GREEN, so CORONA-IMPL remains in progress / NOT READY.** The default entry remains legacy. This package adds no public business proxy; route ownership and platform ingress proxying remain for CN06/CN07.

## GitNexus and edit risk

The GitNexus 1.6.12 / PDG index matched `38ceb89` before edits. Key upstream impacts:

| Target | Risk and impact | Handling |
| --- | --- | --- |
| `ManagedNucleusASGI` | **CRITICAL**, 404 impacted / 4 direct / 109 inferred processes / 20 modules | Private ASGI entry and managed admission boundary; only protocol checks were added to the existing lifecycle boundary. |
| `nucleus/lifecycle.py` (file) | **CRITICAL**, 390 / 4 direct / 108 processes / 20 modules | The only high-risk entry file changed; health/drain/stop use the existing identity control plane. |
| `status_api.py` (file) | **CRITICAL**, 457 / 2 direct / 108 processes / 20 modules | Unchanged; managed lifecycle health provides Nucleus identity. |
| `webui/responses.py` (file) | **CRITICAL**, 41 / 33 direct | Unchanged; the new protocol uses its own fixed-field JSON envelope. |
| `AuthContext` | **HIGH**, 23 / 19 direct | Type unchanged; Corona creates an internal actor DTO only after `require_auth` verifies the JWT. |
| `status_source.py` / `chat_ingress.py` / `routers/chat.py` | LOW, respectively 8/3, 6/2, 4/1 | These business routes remain unchanged and are reserved for the later ownership migration. |

File-level process/module axes are unavailable; process counts are inferred lower bounds, not a complete runtime-entry denominator. `ManagedNucleusASGI` call edges were exact. CRITICAL impact was disclosed before edits. Shared status and response modules were left untouched to constrain the blast radius.

The index retains its extraction limits: 34 large files skipped; 2,970 of 3,170 entry candidates not ranked into the graph; 767 callee branches skipped; 38 walks hit budget and 24 traces hit the depth cap; 317 cross-language property references and a 33-callable candidate cap. Missing edges and zero results do not prove unused code.

## Implementation

- Added the stdlib-only `stella_contracts.control` contract: independent `control_protocol_version=1`, controller/generation/revision/instance identity, trusted actor, controlled header names, and lifecycle operation IDs.
- Nucleus health now binds the protocol version and full generation identity. Drain/stop require protocol version, identity, and operation ID. `NucleusClient` checks health version and identity before readiness and validates every ACK's protocol, generation, and operation ID; stale or wrong-generation acknowledgements are rejected.
- `InternalRequestGuard` wraps managed Nucleus business ASGI. It requires a loopback peer, the current launch capability, matching protocol and four identity fields, and a valid actor/authentication pair. It places the verified actor in ASGI `scope.state` and removes all `X-Stella-*` headers before business code runs. Missing capability, wrong protocol/generation, and untrusted actors are rejected.
- `NucleusClient.forward_browser_headers()` verifies browser JWTs through the existing `require_auth`, then mints internal actor/capability/generation headers. It removes caller-supplied `X-Stella-*`, administrator Authorization, and Cookie headers; adapter Authorization is preserved for platform authentication. Redirects are disabled and upstreams must be loopback.
- Local deploy control runs on a separate loopback listener and remains available without browser WebUI or a working Nucleus. Its capability file lives under the instance ownership directory with POSIX mode `0600`; status/stop verify loopback peer, capability, protocol, instance, and controller boot. Stop returns an acceptance ACK with an operation ID, then drains Nucleus and requests Corona shutdown. The control API remains available when core startup fails.
- The public Corona app blocks `/_corona/local/*` so the control namespace cannot fall through to the static SPA. No public business proxy is enabled; WebChat/business route forwarding was not opened in CN04.

## Acceptance and verification

| Command / check | Result |
| --- | --- |
| Focused Corona/Nucleus control regressions | `STELLA_HOME=/tmp/stella-cn04-focused-20261023 .venv/bin/python -m pytest tests/nucleus/test_nucleus_lifecycle.py tests/nucleus/test_managed_process.py tests/nucleus/test_internal_api.py tests/corona/test_nucleus_client.py tests/corona/test_local_control.py tests/corona/test_corona_app.py tests/corona/test_supervisor_processes.py -q`: **29 passed / 5.21s**. Covers wrong token/protocol/generation, missing or untrusted actors, valid JWT actor, internal-header stripping, stale-ACK rejection, local control after core failure, disabled WebUI, and a real loopback client. |
| `.venv/bin/ruff check .` | Passed. |
| `compileall` for changed modules | Passed. |
| `.venv/bin/python scripts/generate_message_flow.py --check` | Passed; `message-flow.982a65f5aef2.json` matches. |
| Full Python, run 1 | **4056 passed / 29 skipped / 3 failed**. Two proactive-native tests could not open their DB because the isolated home lacked a `memory/` directory; each passed after that temporary directory was created. The WebUI config node passed alone. |
| Full Python, run 2 (temporary `$STELLA_HOME/memory` pre-created) | **4057 passed / 29 skipped / 2 failed / 249.00s**: `test_running_trace_with_dead_incarnation_interrupted` and `test_port_item_kept_in_standalone`. Both passed in isolated reruns. Different state/auth-order failures appeared in the full suite; the cause is unconfirmed, so the full result remains NOT GREEN. |
| `.venv/bin/python scripts/check_docs.py` | **119 files / 1,280 local links / 577 anchors / 0 errors** (rerun after report/state updates). |
| Staged GitNexus `detect-changes --scope all --repo Stella_project --limit 1000` | **21 files / 31–32 symbols / 420–492 affected processes / CRITICAL** across serial reruns. Output lists the first 15 symbols and 10 flows with remainder counts; no partial/truncated marker. |
| Staged GitNexus `detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | **172 files / 363–382 symbols / 509–518 affected processes / CRITICAL** across serial reruns (cumulative CN00–CN04). The first query was interrupted and marked PARTIAL, so it was discarded; subsequent serial reruns completed without partial/truncated markers and listed the first 15 symbols and 10 flows with remainder counts. |
| `git diff --check` | Passed (rerun after report/state updates). |

Tests used temporary `/tmp` `STELLA_HOME` paths and pytest `tmp_path`. No user home, production database, chat, or credentials were read or changed; no real Bot, model, QQ/WebChat, or deployment service was started. The loopback service and child-process behavior were exercised on Linux. Windows ACLs, macOS/BSD, live platforms, Docker, clean VMs, and release acceptance remain unverified.

## Next stage

CN05 implements revision CAS, a single active apply operation, and at most one configuration recovery attempt. Business forwarding remains disabled; the legacy entry stays the default until CN11.
