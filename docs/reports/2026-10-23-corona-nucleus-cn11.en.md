# Corona / Nucleus CN11: Release Payload and Default-Switch Gate

Date: 2026-10-23 (Asia/Shanghai) · Baseline: `28744fa` (CN10 evidence binding) · Branch: `codex/corona-nucleus-implementation`

Scope: engineering plan [CN11](../plans/2026-10-23-corona-nucleus-engineering-plan.md#cn11). This phase updates release and installer allowlists, runtime-data exclusions, Docker liveness and shutdown budget, bilingual deployment/architecture/release documentation, and a suite-order auth-isolation regression. The default entrypoint remains legacy; CN11 is **NOT READY**, and no default switch or release was performed.

## Delivered

- Added `corona/`, `nucleus/`, `stella_bootstrap/`, and `stella_contracts/` to `COMMON_DIRS` / `INSTALLER_DIRS`; retained the version-matched `webui/dist/`. Checked real Standalone zip and OneClick installer staging output.
- Filtered `.stella/` controller state, control-client/ownership files, `.env` variants and deploy answers, SQLite databases and WAL/SHM/journal sidecars, logs, and model/NapCat runtime directories from release and Docker contexts. Synthetic markers covered root and nested paths; `.env.example` remains included.
- Docker Healthcheck now probes Corona `/_corona/v1/health` first and falls back to legacy `/stella/status`. Documentation separates Corona liveness, Nucleus `core_phase`, and business readiness. Compose grace increased from 15 to 65 seconds.
- Fixed suite-order auth leakage by resetting Corona's process-global auth runtime override before and after each legacy WebUI test.
- No business SQLite schema was changed, and no existing production data was read or written. `bot.py` and the Compose default still launch legacy.

## GitNexus pre-edit impact

- `COMMON_DIRS` and `FORBIDDEN_PARTS` were UNKNOWN/0. Source audit confirmed `INSTALLER_DIRS = COMMON_DIRS`; Standalone/OneClick and staging iterate these directories, and `_ignore_release_entries` / `_assert_clean` consume the denylist.
- `build_standalone` LOW (2 impacted, direct caller `main`); `stage_installer_resources` LOW (2 impacted); `_assert_clean` LOW (3 impacted); `_ignore_release_entries` LOW (1 caller).
- Dockerfile, compose, and `.dockerignore` graph relationships were UNKNOWN/0. Source audit confirmed the image copies from the root Docker context and compose controls health checks and shutdown time.
- `tests/webui/conftest.py` UNKNOWN/0. Pytest discovers `tests/`; this conftest is auto-loaded for the `tests/webui` subtree. The fixture only clears the process-global auth override between WebUI tests.
- Bilingual architecture pages MEDIUM (53–57 document-link nodes); bilingual release pages MEDIUM (56–69 document-link nodes). `progress.md` LOW/26, `session-handoff.md` LOW/19, and `feature_list.json` LOW/19. These are documentation-reference edges, not runtime callers. No HIGH/CRITICAL target was edited.

## Verification

- Cometa and WebUI config test files with the new isolation fixture: **43 passed / 5.59s**.
- Installer-contract and release-asset targeted tests: **60 passed / 1.01s** and the full Python regression passed under the same isolated-home approach.
- `.venv/bin/ruff check .` and `git diff --check` passed.
- Standalone Python zip `Stella-Standalone-Python-v6.2.0-windows-amd64.zip`: 561 members; Corona, Nucleus, bootstrap/contracts packages, and `webui/dist/index.html` are present; `scripts/check_release_archive.py` passed; an additional scan found zero forbidden runtime-data/secret matches.
- OneClick installer staging: all 5 required assets present; `.env.example` present; zero forbidden runtime-data/secret files.
- A Docker scratch build with 15 synthetic data markers retained `.env.example` and both program entrypoints while filtering `.stella`, secrets, control/ownership, deploy answers, SQLite sidecars, logs, models, and NapCat; zero forbidden hits.
- `dashboard/dist`, `webui/dist`, and `desktop/dashboard-dist` match exactly. PyYAML 6.0.3 parsed compose successfully and confirmed `init: true` and `stop_grace_period: 65s`.
- A real Docker application image build did not complete: Docker 29.1.3 client/server are available, but pulling `node:24-slim` hit a Docker Hub TLS handshake timeout. This host lacks the `docker compose` plugin, so Compose config/up were not run; the scratch build only validates build-context filtering.
- The full Python suite under isolated `STELLA_HOME` finished with **4115 passed / 29 skipped / 3 warnings / 281.94s**. The earlier suite-order Cometa/WebUI 401 failures disappeared after resetting the auth runtime around each test. The machine-readable summary is [here](evidence/corona-nucleus-cn11/summary.json); GitNexus commit gates will be added in the evidence follow-up.

## Not run / incomplete

Clean Windows/Linux VMs; the six final products' cold start/restart/failure recovery/upgrade/rollback; a real Docker startup; live QQ/OneBot, WebChat, and model acceptance were not run. Rust tooling is unavailable. There is no proof yet that the whole process tree exits, the data lock is released, and code/schema are compatible before legacy rollback.

CN11 therefore delivers local packaging and container-configuration preparation only; it does not meet the default-switch criteria. Keep `CORONA-IMPL` `in_progress` / **NOT READY** and keep legacy as default. Execute a separate switch only after all required VM, live, container, and rollback evidence is complete.
