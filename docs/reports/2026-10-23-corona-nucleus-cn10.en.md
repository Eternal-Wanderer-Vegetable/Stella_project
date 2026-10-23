# Corona / Nucleus CN10: Fault Injection, Cross-Process Recovery, and Resource Acceptance

Date: 2026-10-23 (Asia/Shanghai) · Base: `d010dd5` (CN09) · Branch: `codex/corona-nucleus-implementation`

Scope: engineering plan [CN10](../plans/2026-10-23-corona-nucleus-engineering-plan.md#cn10). This report records CN10 implementation and executed checks. Overall CORONA-IMPL remains **NOT READY**: the full Python suite has one order-sensitive failure, and Rust/Windows native gates were unavailable here.

## Delivered

- Added three real fake-Nucleus child-process behaviors: successful readiness, crash during startup, and crash after readiness. The Linux test runs 100 successful/failing/stopped/restarted cycles and checks exclusive writer ownership, PID reaping, FD, thread, and async-task trends. It compares cycles 41–60 and 81–100 after 40 warmup cycles, with tolerances instead of claiming perfectly constant OS counters.
- Added proxy load checks against a real Nucleus subprocess for ordinary HTTP, SSE, WebSocket, concurrent uploads, and independent control health during core restarts. Request IDs are verified as Nucleus-minted and correlatable.
- Registered five cross-process lifecycle entries in `internal_flow_catalog.py`: Corona owner start/stop, config apply, desktop/CLI IPC dispatch, and adapter proxy to Nucleus. Each entry records an explicit process boundary, contract files, and cross-process correlation fields; the catalog does not represent them as local call edges.
- Extended the message-flow generator's package roots so anchors under `corona/`, `nucleus/`, `deploy/`, `stella_bootstrap/`, and `stella_contracts/` resolve. Generated and checked the new message-flow manifest.
- Fixed test isolation and stale assertions exposed by the regression runs: proactive tests now isolate both DB constants; deploy CLI tests assert Corona live-owner behavior; the install handler loads legacy settings before direct invocation; package catalog output stays in a temporary project root. No production behavior changed.

## Measurements

Raw results are kept in [CN10 evidence](evidence/corona-nucleus-cn10/).

- Linux WSL2 / Python 3.12.14: all 100 unique child PIDs exited; exclusive writer `flock` succeeded 100/100 times; orphan children: 0. FD window medians were 15 → 15 (final max 15); threads 19 → 20 (final max 20); pending async tasks 1 → 1. Counts remained within the declared tolerances. Each generation wrote a separate log file (100 total); no in-memory log queue was used.
- For 30 ordinary proxy requests, p50/p95 was **10.606 / 15.077 ms**. The run completed 5 SSE events, 12 WebSocket round trips, and 4 concurrent 256 KiB uploads; upload p50/p95 was **61.674 / 61.848 ms**.
- During 3 core restart cycles, the control health endpoint returned 156 successful responses with zero 5xx/transport failures. Control latency p50/p95 was **3.072 / 5.181 ms**, against an initial p95 target below 500 ms. All 30 proxy requests had a valid Nucleus request ID, replacing caller-supplied values. Peak RSS was 435,344 KiB for the controller/test process and 51,032 KiB for the fake core.
- These values describe the current WSL2 fake-core workload. They are not performance commitments for Windows, containers, a real business Nucleus, QQ, or a live model.

## A01–A34 Classification

The machine-readable [CN10 scenario ledger](2026-10-23-corona-nucleus-cn10-scenarios.json) records each result, test reference, and limitation: **12 pass / 17 partial / 5 not_run**. Passing items mainly cover config/CAS/crash transactions, internal authorization, path protection, the 100-cycle Linux soak, the locked NoneBot snapshot, and the group-binding saga. Partial results retain gaps for real browsers, external platforms/models, plugins/MCP/Chromium, SIGKILL storms, PID reuse, the complete multi-instance matrix, host reboot, and final product checks. A11, A13, A14, A15, and A32 were not run.

## GitNexus Pre-Edit Impact

- `CoreSupervisor.start` was LOW: 2 direct callers / 1 Corona startup flow, with 6 receiver-typed callers unresolved. `CoreSupervisor.stop` was LOW: 3 impacted callers and 4 unresolved receiver callers.
- `OperationManager.accept` was **HIGH**: 7 impacted / 4 direct callers / 3 flows, with one caller unresolved. The change only registers this cross-process boundary in the internal flow catalog; the HIGH result is retained and not waived using `riskSharedAxes`.
- `AdapterProxyMiddleware` and `build_manifest` were LOW. `RUNTIME_ENTRY_INVENTORY` and the added test module were UNKNOWN/0; source review confirmed generator reads, pytest discovery under `tests/`, and CI execution. The index still omits entry candidates and callees, hits walk/depth limits, and lacks dynamic/cross-language edges; zero callers is not proof of no impact.

## Verification Results

- Focused Python regressions under an isolated `STELLA_HOME`: **142 passed / 4 warnings / 50.79s**, covering `tests/corona`, `tests/nucleus`, the flow inventory, and affected modules. Warnings cover duplicate FastAPI operation IDs, an existing pytest class-fixture deprecation, and a no-adapter runtime hint.
- Full Python under an isolated home: **4114 passed / 29 skipped / 1 failed / 3 warnings / 279.00s**. The sole failure was `tests/webui/test_webui_cometa.py::TestApiKeyRoute::test_empty_key_rejected`, which got 401 instead of 400. That exact node passed alone (**1 passed**). The cause remains unknown; earlier phases also saw order-sensitive Cometa/WebUI 401 failures, so the full gate remains NOT GREEN.
- Dashboard: Vitest **9 files / 110 passed**; `pnpm --dir dashboard build` (including `vue-tsc --noEmit`) and `sync:webui` passed. `dashboard/dist`, `webui/dist`, and `desktop/dashboard-dist` matched. Existing mixed dynamic/static import and large-chunk warnings remain.
- `.venv/bin/ruff check .` passed; `.venv/bin/python scripts/generate_message_flow.py --check` passed. The manifest reports 58 runtime entries, 144 nodes / 142 source-resolved, 9,640 closure sites, and 15,736 reachable symbols.
- `.venv/bin/python scripts/check_docs.py`: **119 files / 1,277 local links / 577 migration anchors / 0 errors**; scenario/feature JSON parsing and `git diff --check` passed.
- Staged GitNexus: serial `detect-changes --scope all` returned **18 files / 41 symbols / 0 affected processes / LOW**; compare against `main` then returned **248 files / 1,501 symbols / 150 affected processes / CRITICAL**. Neither result had a partial/truncated marker. The CLI capped the compare symbol listing, but its counts cover all changes. This risk is cumulative for the branch versus main and is not waived.
- The planning snapshot verifier `docs/reports/evidence/corona-nucleus-20261023/verify_plan.py` stopped after detecting source drift in `tests/webui/test_webui_mount.py`, a file already changed by CN06/CN07 implementation. That verifier checks the frozen pre-implementation planning snapshot. This work left the frozen inventory, manifest, and verifier unchanged.

## Not Run / Incomplete

- This host is Linux WSL2, not native Windows or a clean Linux VM. `cargo`, `rustc`, and `rustup` are absent from PATH; Rust fmt/clippy/test/compiler gates were not run. Windows Job Object/native locks, clean VM, Docker, and the final six-product matrix are NOT RUN.
- No live QQ/OneBot service, in-flight WebChat model/tool restart, real model, Cometa lease, Scheduler, real memory/Compact, MCP/plugin/Chromium integration, or whole-machine reboot was exercised.
- The legacy default remains unchanged. CN10 does not replace CN11's release, canary, rollback, or default-switch acceptance.

CN10's Linux fake-process soak, proxy/flow work, and available local gates are delivered. Its full exit criteria retain gaps in the full Python run, Windows/native support, and product-environment scenarios, so CN10 remains **NOT READY**. CORONA-IMPL is not complete.
