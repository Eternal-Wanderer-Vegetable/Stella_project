# Corona / Nucleus Implementation CN06 — WebUI Route Split, Business Proxy, and Group-Binding Coordination

Date: 2026-10-23 (Asia/Shanghai) · Branch: `codex/corona-nucleus-implementation` · CN06 base: `5ae639b`

**Package status: code and focused local regressions are complete; the full Python gate is NOT GREEN, so CORONA-IMPL remains in progress / NOT READY.** The default launcher remains legacy; CN11 owns the switch. No business database was migrated.

## GitNexus and edit risk

The GitNexus 1.6.12/PDG index matched CN05 HEAD `5ae639b` before this package. Upstream impact for `webui.auth.require_auth` was **CRITICAL (145 impacted / 2 direct / 67 processes / 20 modules)**; this risk was reported before editing. To support signed identities from the managed core, the change creates a managed admin context only when `InternalRequestGuard` has marked the request after validating capability, protocol, identity, and an explicit `admin+jwt` actor. Ordinary JWT behavior is unchanged. `webui.app.create_webui_app` was MEDIUM, `webui.mount.mount_webui` MEDIUM, and `ManagedNucleusASGI` MEDIUM; `setup_webui` and Nucleus main were LOW. Context was checked; only the managed mount branch selects the filtered business app, while legacy remains the default.

`OperationManager.accept` was LOW (5 impacted / 3 direct / 2 processes); `_operation_api_error` was LOW (5 / 3 / 2). They now block ordinary apply during an unresolved group saga and return 409. `ConfigStore.save` was CRITICAL (117 impacted) and was not modified. The new coordinator class, queried by unique UID, was LOW (one direct import by `corona.app`, then startup from `corona.__main__`). The new Nucleus store file was LOW; its direct edge is `nucleus.routes`, followed by the WebUI mount to `bot.py`.

The method name `execute` is common across the repository; an undisambiguated GitNexus query returned a misleading CRITICAL 281 result and reported 15 receiver-typing omissions. It was not treated as impact for this coordinator method. File/class UID queries and `context GroupBindingsCoordinator` confirmed assembly through Corona app; source inspection supplemented decorator routes, private Nucleus endpoints, and the business router tuple. Index refresh limits: 34 large files skipped; at least one Python callable-flow candidate set exceeded 32 and emitted no partial CALLS; process extraction omitted 3,119 of 3,319 candidate entry points, cut 42 walks by budget and 23 traces by depth, and skipped 960 callees; 324 cross-language field sites were not inferred. GitNexus remains a lower bound.

## Implementation

- Added `corona.routes`, a frozen ownership contract for all 133 planned `(method,path,owner)` keys: 21 Corona, 111 Nucleus, and one `split-config-and-business`. Unknown APIs return 404; an unplanned method on a catalogued path returns 405. The business proxy only accepts registered Nucleus paths under `/api/v1/` and is installed before the SPA/static fallback.
- Added `webui.app.webui_route_routers()` to expose routers in their original order. The managed Nucleus app clones only the 111 business `APIRoute`s and checks for missing, extra, or duplicate routes. Corona retains control APIs. With `WEBUI_SERVE_DIST=true`, a business GET still reaches the proxy and returns an explicit 503 when Nucleus is down.
- Added an HTTP proxy to the ready Nucleus client bound to the current generation. It forwards raw path/query/body and duplicate application request headers, while removing browser JWTs, cookies, forged control headers, hop-by-hop headers, and headers nominated by `Connection`. Responses preserve status, repeated `Set-Cookie`, and raw body bytes; hop-by-hop headers are removed and HEAD/204/304 bodies are suppressed. Core unavailability maps to 503 and protocol errors to 502. Clients cannot choose an upstream URL.
- The internal guard marks a request trusted only after validating capability, protocol, identity, and actor. `require_auth` accepts only a trusted `admin+jwt` actor as managed identity; legacy JWT authentication remains. The Corona import fence loads no business DB, model, memory, Cometa, knowledge-base, or Bot module.
- Corona coordinates the legacy mixed group-binding PUT with a durable saga: validate the Nucleus space snapshot, persist the request and steps, CAS-save `ALLOWED_GROUPS`, idempotently apply the Nucleus space files by operation ID and reload its cache, then apply the revision when needed. Failures attempt conditional `.env` and space compensation. External edits or failed compensation leave `needs_reconcile` and block later apply. A separate Nucleus journal stores exact before/after snapshots; crash recovery marks unexpected content as `CONFLICT` without overwriting external edits. The mixed endpoint rejects requests while Nucleus is offline while standalone control APIs remain available.

## Acceptance and verification

| Command / check | Result |
| --- | --- |
| Focused CN06 routes/group bindings/client/mount regression | `.venv/bin/python -m pytest tests/corona/test_group_bindings.py tests/corona/test_nucleus_client.py tests/webui/test_webui_mount.py -q`: **25 passed / 12.42s / 2 OpenAPI duplicate-operation-ID warnings**. Covers the exact 21/111/1 contract, exact Nucleus assembly, offline/static fallback, guard identity, private routes, raw HTTP proxying, saga success, failed compensation blocking apply, and crash recovery refusing to overwrite an external edit. |
| Corona/WebUI and personal-memory regressions | `STELLA_HOME=/tmp/stella-cn06-related-final-20261023-7e81ad .venv/bin/python -m pytest tests/corona tests/webui tests/test_webui_personal_memory.py -q`: **192 passed / 29.24s / 2 OpenAPI duplicate-operation-ID warnings**. |
| Ruff | `.venv/bin/ruff check corona nucleus webui tests/corona/test_group_bindings.py tests/webui/test_webui_mount.py`: passed. |
| compileall | `.venv/bin/python -m compileall -q corona nucleus webui`: passed. |
| Message-flow manifest | `.venv/bin/python scripts/generate_message_flow.py --check`: passed; `message-flow.982a65f5aef2.json` matches. |
| Docs links/anchors | `.venv/bin/python scripts/check_docs.py`: **119 files / 1,275 local links / 577 anchors / 0 errors**. |
| Full Python suite (isolated `STELLA_HOME=/tmp/stella-cn06-full-final-20261023-7e81ad`, with `memory/` pre-created) | **4,087 passed / 29 skipped / 1 failed / 3 warnings / 256.16s**, NOT GREEN. Failure: `tests/webui/test_message_flow_api.py::TestSegmentsTruncationHonesty::test_command_full_text_via_receipt_path`; context data was empty in the full run. The exact node passed alone (**1 passed / 0.59s**) and the full `tests/webui/test_message_flow_api.py` module passed in an isolated home (**24 passed / 2.90s**). The suite-order/shared-state cause is unknown; these reruns do not make the full suite green. |
| Data boundary and external acceptance | Focused and full tests used explicit `/tmp` `STELLA_HOME` values and pytest temporary directories; no user config, chat, or production DB was read or changed. No real model, Bot, QQ/WebChat, or deployment service was started. Windows/macOS/BSD clean VMs, Docker, live platform/model, and release acceptance were not run. |
| Staged GitNexus `detect-changes --scope all --repo Stella_project --limit 1000` | **21 files / 51 symbols / 745 affected processes / CRITICAL**. |
| Regression review `detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | **193 files / 442 symbols / 745 affected processes / CRITICAL** (cumulative CN00–CN06). |
| GitNexus output completeness | Commands ran serially; neither output showed a PARTIAL or truncated marker. The flow listing is capped, but aggregate counts are reported. |
| `git diff --cached --check` | Passed. |

## Next stage

CN07 adds a generation-bound adapter route catalog, stable HTTP/SSE/WS entry points, and the original-peer loopback check for `/stella/status`. CN06 only provides registered `/api/v1/` business HTTP proxying; it does not provide platform adapter or SSE/WS proxy entry points. The default launcher remains legacy.
