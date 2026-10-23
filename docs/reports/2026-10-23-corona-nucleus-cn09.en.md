# Corona / Nucleus CN09: Launcher, CLI, Desktop, and Runtime Ownership

Date: 2026-10-23 (Asia/Shanghai) · Base: `6050bae` (CN08) · Branch: `codex/corona-nucleus-implementation`
Scope: engineering plan §8.4. This commit records implementation; missing Rust and Windows acceptance keeps CN09 / CORONA-IMPL NOT READY.

## Result

- Added stdlib-only `stella_contracts.local_control` and `deploy.control_client`. `python -m deploy start/status/stop` locates the live Corona owner before loading `config`/business settings or consulting a mutable `.env` port. It uses the private ownership record, protocol/instance/boot identity, loopback capability, and OS-held owner lock. Protocol errors, unreachable owners, or unknown lock state fail closed; the client does not kill by port/PID or start a second legacy core. Start builds an immutable config revision; `--force` cannot bypass owner/protocol checks.
- Corona's local status includes controller PID and public listener address. Deploy status separates Corona availability from Nucleus readiness/backoff. Runtime schema-v1 `stella` mapping retains optional `llama`/`onebot` state; Python validation and a Rust round-trip fixture cover the compatible shape without `null` PIDs. Stop requests shutdown through the authenticated API, then waits for both endpoint loss and OS ownership lock release.
- CLI lifecycle/status does not fall back to legacy deploy or port probing when the Runtime command fails or its response is invalid. Tauri readiness follows the Corona control plane and actual public URL; the desktop management surface remains available while the core is not ready. Window close uses the same deploy live-owner path. A table-driven Rust test covers start arguments for all six release profiles.
- Tauri passes its random desktop session capability only through `start --detach` to Corona. The config revision does not persist the secret and the Nucleus child environment filters it. The Dashboard exchanges it for a JWT only in Tauri when the control plane is reachable, setup is complete, and there is no existing JWT. Exchange failure preserves the ordinary login flow. Browsers and setup do not request the capability.
- Managed routes already map through `corona/routes.py` to the Corona operation manager. The legacy-only `webui.services.system.restart` was left unchanged; its high-risk graph flow is outside managed startup.

## GitNexus Pre-edit Impact

- `deploy/process.py:start_detached` was **CRITICAL** (reported 358 impacted / 103 direct / 25 processes / 12 modules); `deploy/process.stop` was **CRITICAL/partial**, with dropped receiver callers in the graph; `deploy/runtime.py` and `corona.local_control.create_local_control_app` were **CRITICAL** at file/symbol scope. Source audits covered callers, deploy parser dispatch, Corona startup, Tauri command registration, and window-close calls. The old PID/port path remains for legacy but is no longer called by the new managed CLI commands.
- `webui.services.system.restart` was **CRITICAL** (783 impacted / 315 direct / 38 flows / 20 modules, partial). Source inspection confirmed that managed `POST /api/v1/system/restart` maps to Corona in `corona/routes.py`, so the legacy WebUI service was not modified.
- `stella_bootstrap.config.build_config_revision` and `nucleus.bootstrap.prepare_managed_environment` were each **CRITICAL** (560 impacted / 163 direct / 25 processes / 15 modules). Before editing, revision creation and child-environment boundaries were inspected; regressions were added for secret non-persistence and exclusion from Nucleus.
- The Dashboard auth store file was **CRITICAL** (238 impacted / 6 direct / 181 processes / 20 modules). The change adds only a narrowly gated Tauri exchange; failure retains the login route. `dashboard/src/api/tauri.ts:tauriBridge` was **UNKNOWN/0**. Text audit confirmed existing imports in `BackendOfflinePage.vue` and this change's new auth-store import; the graph does not resolve all Vue/Rust IPC edges.
- Several Rust/Vue symbols were UNKNOWN/0. Route registries, IPC handler registration, source call sites, and frontend imports were audited; the cross-language graph is not treated as proof. High risks are retained as reported and not waived based on shared axes or test counts.

## Verification

- Targeted control-plane tests under temporary `STELLA_HOME` and `STELLA_INSTANCE_ID=cn09-isolated`: **34 passed / 1.47s**, including fake Corona endpoint/owner-lock cases, protocol mismatch, Runtime schema mapping, local control API, Nucleus secret filtering, and config-revision secret exclusion.
- `python -m py_compile` on changed Python sources/tests and `.venv/bin/ruff check .`: passed.
- Dashboard: `pnpm --dir dashboard test -- tests/auth-store.spec.ts` (Vitest configuration runs the full suite): **9 files / 110 passed**; `pnpm --dir dashboard build` passed; `pnpm --dir dashboard sync:webui` passed; both `diff -qr dashboard/dist webui/dist` and `diff -qr dashboard/dist desktop/dashboard-dist` were empty. Build retains existing mixed dynamic/static import and >500 KB chunk warnings.
- `.venv/bin/python scripts/check_docs.py`: **119 files / 1,277 local links / 577 anchors / 0 errors**. `.venv/bin/python scripts/generate_message_flow.py --check`, repository Ruff, and `git diff --check`: passed.
- Full Python was not rerun this package. CN07's latest full run remains **4103 passed / 29 skipped / 1 failed / 3 warnings**. A Cometa auth 401 failed in suite order while its exact node and module passed separately; cause unknown, so the full gate remains NOT GREEN.
- `cargo fmt`/`cargo test`/`cargo clippy` were not run: this host has no `cargo`, `rustc`, or `rustup`. CN09 Windows-native ownership/Job Object acceptance was also not run because the current host is not Windows. The new Rust tests and serialization changes have no compiler validation; this is an explicit exit-criteria gap.

## Final GitNexus Gate and Acceptance Boundary

After staging, serial `node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project` returned **26 changed files / CRITICAL**; then `node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo Stella_project` returned **236 changed files / CRITICAL**. Symbol and affected-process totals varied across complete repeated runs. No partial/truncated marker appeared; the CLI omitted additional symbol and flow names at its display limit. The risks remain explicit and are not waived.

Fake local-controller coverage validates Python owner discovery and protocol shape, not a packaged Tauri/CLI/Corona real-process lifecycle. Foreground/background CLI, desktop close, Rust schema, Windows native locks/process tree, six final assets, real Nucleus, and live platform paths are not fully accepted. The legacy default is unchanged; CN11 owns the switch. The CN09 implementation commit does not mean all exit criteria passed; overall readiness remains NOT READY.
