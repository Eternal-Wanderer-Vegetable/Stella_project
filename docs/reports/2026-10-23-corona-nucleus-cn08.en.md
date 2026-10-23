# Corona / Nucleus CN08: Dashboard Configuration Apply and Offline State

Date: 2026-10-23 (Asia/Shanghai) · Base: `6ba8bdd` (CN07) · Branch: `codex/corona-nucleus-implementation`
Scope: implementation plan §8.3; Corona is not yet the default runtime entry point.

## Result

- Added a Dashboard system API and Pinia store. It recognizes managed protocol v1 status, polls the control plane, and tracks desired/applied revisions, core generation, and operations. Operation SSE, event IDs, status snapshots, exponential reconnect backoff, and a sessionStorage idempotency record recover after page reconnects or a lost apply response.
- Added a signed-in global status banner showing control-plane connectivity, saved/applied revisions, core and operation phases, failure summaries, rollback results, and Corona control-plane restart scope. Core downtime does not clear the JWT or redirect the signed-in app to the whole-backend offline page. Control-plane disconnection is shown as reconnecting; polling resumes when the controller returns.
- Managed writes from Config, Providers, and Platforms include `If-Match` and idempotency keys, with one apply per form. Managed Config saves no longer append the legacy `/system/restart` request. Browser verification first exposed that extra request; after the fix, two later saves each issued only apply. Legacy save/restart behavior remains. Providers serializes the endpoint and role writes, using each returned revision for the next CAS.
- Welcome consumes Corona status. Chat and Groups mark their local business caches stale after request errors, core unavailability, or a generation change. Chat requests are never retried automatically. HTTP/SSE 401s from business proxies are returned as page errors; a 401 from the control-plane auth surface still clears an invalid session according to the existing policy.
- `pnpm --dir dashboard sync:webui` copies the same Dashboard build to the WebUI and desktop distribution directories.

## GitNexus Pre-edit Impact

- `corona/config_api.py:_operations` was **HIGH** upstream (8 impacted / 6 direct / 3 operation/status flows). This package consumes the existing apply, status, operation, and SSE APIs; it does not change Corona operation management or lifecycle code.
- `clearToken` was **CRITICAL** upstream (435 impacted / 2 direct / 124 processes / 20 modules). Axios and SSE 401 handling are its direct callers. The change preserves logout behavior for control-plane auth failures and leaves 401s from classified business-proxy routes as page errors. A local browser chat-401 case verified that the user stays signed in.
- Several Vue SFC handlers, `sseStream`, and the new system store were UNKNOWN/0 or absent from the graph. Source/template audits checked `/status`, form event bindings, all `sseStream` call sites, and the SystemBanner import/render in FullLayout. File impact for `ConfigPage.save` was UNKNOWN/0; the template's `@click="save"` was confirmed. The file-level impact for `progress.md` was **CRITICAL** (286 impacted / 3 direct / 124 processes / 20 modules). This is state-document reference propagation, not a runtime call fanout. Before editing state files, references from AGENTS, workflow, check_docs, and documentation contract tests were reviewed.

## Verification

- `pnpm --dir dashboard typecheck`: passed.
- `pnpm --dir dashboard test`: **8 files / 107 passed**.
- `pnpm --dir dashboard build`: passed; 736 modules transformed. Vite retained existing mixed dynamic/static import notices, plus bundle-size notices for ApexCharts/charts and the main entry over 500 KB.
- `pnpm --dir dashboard sync:webui`: passed. `diff -qr dashboard/dist webui/dist` and `diff -qr dashboard/dist desktop/dashboard-dist` found no differences.
- Chinese and English locale JSON parsing and `git diff --check`: passed.
- `python scripts/check_docs.py` could not start because the system has no `python` executable on PATH. Retried with the project environment, `.venv/bin/python scripts/check_docs.py`: passed, 119 files / 1,280 local links / 577 migration anchors / 0 errors.
- Browser acceptance used Vite and a temporary loopback-only mock control API; no user account, production Corona data, or real core was accessed. The flow signed in and displayed managed status; a successful config save used revision CAS and an idempotency key and issued one apply; config remained editable with the core stopped; injected startup failures displayed both successful rollback and failed recovery; controller disconnection retained the signed-in page and reconnected; a business chat SSE 401 left the signed-in Chat page open, marked the cache stale, and produced one mock request. After the controller returned, `/config` remained signed in.
- The full Python suite was not rerun this package. CN07's latest full run remains **4103 passed / 29 skipped / 1 failed / 3 warnings**. The suite-order Cometa 401 passed in its exact test and module when run separately; its cause is unconfirmed, so the full Python gate remains **NOT GREEN**.

## Final GitNexus Gate

Serial complete staged runs returned **20 files / CRITICAL** for `detect-changes --scope all` and **217 files / CRITICAL** for `compare --base-ref main` (cumulative). Symbol and affected-process counts varied between complete runs and are not stable values. One compare query was interrupted and marked PARTIAL; it was discarded and rerun alone. The complete gate outputs had no `partial` / `truncated` marker. The CLI omitted some symbol and flow names to fit its display limit.

## Acceptance Boundary

Browser scenarios verified Dashboard behavior against the expected contract shape. The temporary mock is not an end-to-end test of Corona with a real managed Nucleus core. Launcher, CLI, Tauri/runtime ownership integration is CN09; legacy remains the default. QQ rollout, real models, production databases, Windows/Linux clean VMs, Docker, and release acceptance were not run. Overall CORONA-IMPL remains NOT READY.
