# Corona / Nucleus CN07: Stable Platform Ingress and HTTP/SSE/WS Proxy

Date: 2026-10-23 (Asia/Shanghai)
Base: `eb7f889` (CN06)
Branch: `codex/corona-nucleus-implementation`
Scope: implementation plan §8.1–§8.2 and CN07. Legacy remains the default launcher.

## Result

- Added a shared route-catalog contract bound to the control protocol, instance/controller/generation/revision identity, and a SHA-256 digest. Validation rejects reserved paths, dynamic-template collisions, duplicate method routes, root/path catch-alls, unsafe separators, and unsupported methods. Nucleus exports only HTTP/WebSocket routes from the active FastAPI Driver whose names belong to registered adapters. Other adapter shapes are omitted and are not certified.
- Nucleus serves `GET /_nucleus/v1/routes` behind the existing loopback and per-generation capability boundary. Corona verifies health identity first, then fetches and validates the catalog. Catalog and ready state are stored in one immutable snapshot. An ingress request obtains a client only while that exact catalog object remains in the current ready snapshot, preventing an old generation's paths from being reused against a new generation.
- Added Corona ingress middleware ahead of static/SPA handling. HTTP uses the fixed loopback endpoint for the selected generation, streams the original request body, and preserves method, encoded path, query, platform Authorization/Cookie/signature headers, status, and duplicate response headers. Caller `X-Stella-*` and forwarded headers are stripped, unsafe paths are rejected, redirects aren't followed, and private Nucleus origins in `Location` are rewritten. SSE uses the same bounded async stream; response cancellation closes the upstream.
- WebSockets use a no-redirect websockets connector. Origin, subprotocols, platform credentials/signatures, and text/binary messages are forwarded. Both directions await sends for backpressure. Message size is capped at 4 MiB, queue length at 4 messages, and write buffer at 32 KiB. Upstream close code/reason is preserved; messages are not replayed and the proxy does not reconnect automatically. Platform clients reconnect themselves.
- FastAPI trailing-slash behavior is preserved with a 307 to the public relative path. Corona checks the raw ASGI peer for `/stella/status` and forwards only loopback requests with a system actor. The public Uvicorn listener sets `proxy_headers=False`, so X-Forwarded-For cannot bypass the check. `/_nucleus` and unregistered `/_corona` paths are blocked before SPA handling.

## GitNexus Pre-edit Impact

After refreshing the index from CN06 HEAD `eb7f889`, exact UID/context and source-registration checks reported:

| Target | Upstream result | Handling |
| --- | --- | --- |
| `ManagedNucleusASGI` | **CRITICAL**, 17 impacted / 4 direct / 124 processes / 20 modules | Extended the planned private ASGI control surface while retaining existing admission and lifecycle behavior. |
| `NucleusClient.proxy_http` | **CRITICAL**, 300 / 1 direct / 130 processes / 20 modules | Existing business forwarding keeps its defaults; platform credential preservation and Location rewriting use a new adapter-specific path. |
| `create_corona_app` | **CRITICAL**, 301 / 2 direct / 130 processes / 20 modules | Added only the ingress middleware; control API, WebUI, and business API assembly order remains intact. |
| `NucleusClient` class | **HIGH**, 7 / 3 direct / 3 modules | Added private catalog fetch and adapter proxy methods without changing browser actor semantics. |
| `CoreSnapshot` | LOW, 2 direct | Catalog remains a private immutable field and is excluded from public status. |
| `nucleus.__main__.main` | LOW, 1 direct / Tests module | Builds the catalog after Driver assembly and injects it into the managed ASGI wrapper. |
| `corona.__main__.main` | LOW, 1 direct | Disables forwarded-proxy header trust on the public Uvicorn listener. |
| `core/transport/adapter_loader.py` | Function query UNKNOWN/0; file candidate included CRITICAL 514 / 2 direct | Left unchanged. The catalog is built from the registered Driver adapter registry and actual FastAPI route table, backed by a real OneBot V11 registration test. |

Graph-RAG's large fanout for `create_corona_app` / `proxy_http` represents existing business-proxy flows. Process candidates and call closure have budget limits; CRITICAL lower bounds and UNKNOWN/0 were supplemented with source and dynamic-registration audits. The index skipped 34 files larger than 512 KB; flow extraction also has a 32-callable cap, cross-language property-call gaps, unranked entry candidates, and budget/depth-capped walks. These limits are retained rather than treated as proof of no impact.

## Verification

- `.venv/bin/python -m ruff check .` (repository-wide): passed.
- `.venv/bin/python -m compileall -q corona nucleus stella_contracts`: passed.
- CN07 focused regressions (contract, real OneBot Driver registration, real child-process HTTP/SSE/download/WS, close codes, slash handling, reconnect, XFF/raw-peer, Supervisor, and Nucleus lifecycle): **42 passed / 5.86s**. The final HTTP reconnect assertion was rerun separately: **1 passed / 2.09s**.
- Corona/Nucleus/WebUI group: first **210 passed / 2 failed** because two old fake-core fixtures lacked the CN07 route-catalog handshake. After fixture updates: **211 passed / 1 failed / 2 warnings / 37.26s**. `TestFlowMessagesApi.test_list_and_detail` returned 401; the exact node passed (**1 / 0.73s**) and its module passed (**24 / 3.19s**). The ordering/auth-state cause is unknown.
- Full Python: `STELLA_HOME=/tmp/stella-cn07-full-20261023 .venv/bin/python -m pytest -q` yielded **4103 passed / 29 skipped / 1 failed / 3 warnings / 278.93s**. `TestAuthStatusAndCustomEndpoint.test_status_none_when_unconfigured` returned 401 in suite order; the exact node passed (**1 / 0.44s**) and `tests/webui/test_webui_cometa.py` passed (**29 / 4.81s**). Root cause is unconfirmed, so the full gate is **NOT GREEN**. The test home, child DBs, and snapshots were isolated under `/tmp`.
- A real NoneBot OneBot V11 Driver subprocess confirmed HTTP `POST /onebot/v11/`, `/http`, `/http/` and WS `/onebot/v11/`, `/ws`, `/ws/`. A Supervisor-managed local Uvicorn fake Nucleus also verified HTTP upload/signature bytes, SSE, download, WS subprotocol/Origin/platform credentials/close code, explicit 503 during downtime, generation restart, and client reconnect.
- `.venv/bin/python scripts/check_docs.py`: `ok=true`, 119 files / 1,278 local links / 577 migration anchors / 0 errors.
- `.venv/bin/python scripts/generate_message_flow.py --check`: passed; `message-flow.982a65f5aef2.json` matches current source.
- `git diff --check`: passed. Final focused rerun: 42 passed / 5.61s.

## Acceptance Boundary

OneBot V11 Driver route shape plus local fake-process traffic/reconnect passed. This does not certify a live OneBot server, QQ rollout, browser/reverse-proxy chain, or other adapters. Unknown/non-standard adapters are not certified; the 32-platform matrix retains its existing statuses. No user production database, chat, configuration, real model, or platform account was accessed. CN07 did not change the default launcher; CN08 is next.

## Final Gate Addendum

The two staged GitNexus commands were run serially; output contained no `partial` / `truncated` markers: `all` **20 files / 39 symbols / 12 processes / HIGH**; the latest complete `compare --base-ref main` was **200 files / 553 symbols / 605 processes / CRITICAL** (cumulative regression scope). Repeated compare runs varied slightly in symbol/process counts; this records the latest complete output.
