# XPLAT P10 validation and closeout evidence — 2026-10-26

## Status

P10 local gates remain **blocked** on the Python 3.10/3.11 full-suite matrix; Python 3.12, Dashboard, docs, Rust/native wheel, local parity, and restore drill have local evidence. Latest post-flow-refresh sequential full suites remain variable: Python 3.10.21 had two failures; Python 3.11.16 had one auth failure. Every observed failure passed an isolated rerun, but that does not establish a green full-suite matrix. Overall XPLAT remains **NOT READY**. Per user direction, true platform/model validation is deferred until this branch is merged to `main`; no live account or platform validation was run in this turn. Official adapter matrix remains **0/32 certified**; clean Windows VM and release acceptance remain open.

No production `STELLA_HOME`, database, credentials, chats, running service, Bot, platform account, release environment, or user configuration was accessed. Python tests used temporary `STELLA_HOME` roots. CI-style coverage also reported generated `data/plugins/stella_*_selftest` source paths after their fixtures had cleaned them up; a name-only check found no matching directories remaining, and `git status` showed no test-generated workspace changes.

## P10 commits

- `30cdf87 fix(transport): close final validation boundary gaps` — kept the Corona controller app import boundary free of product/business runtime imports until app construction; corrected the G05 denied-capture assertion for the case where the table has not yet been created.
- `cefec48 fix(observability): stabilize flow closure across Python versions` — normalized serialized string and callable-target formatting so the generated closure is stable across Python 3.12 patch versions.
- `47548f0 chore(observability): publish stable P10 message flow` — published `core/observability/flows/message-flow.462d5c256f73.json`, topology 2026.10.21, 144 nodes, 142 source-resolved nodes, 9,688 closure sites, and 15,598 reachable symbols.
- `d03d9b5 fix(memory): align native promotion evidence contract` — native evidence verification accepts legacy and current assessment versions, binds current namespaced snapshots to opaque subject and connection identity, and keeps the legacy QQ path; the fullchain fixture now seeds the current contract.

The original P10 flow artifact was `message-flow.462d5c256f73.json`. The native helper follow-up changed source anchors, so the final local refresh is now `message-flow.7c3a08d0677e.json`, still topology 2026.10.21 with 144 nodes, 142 source-resolved nodes, 9,688 closure sites, and 15,598 reachable symbols. The historical artifact remains as an immutable snapshot. The refreshed manifest check passes on Python 3.10.21, 3.11.16, 3.12.10, and 3.12.14.

## Verification evidence

| Gate | Command / environment | Result |
| --- | --- | --- |
| Full Python suite | `env -u STELLA_TRANSPORT_SETTINGS_JSON STELLA_HOME=/tmp/stella-p10-full-final-20261026 .venv/bin/python -m pytest tests -q` (locked Python 3.12.14) | **4,245 passed, 34 skipped, 3 warnings**, exit 0, 292.74s. Two existing duplicate FastAPI operation-ID warnings and one existing pytest class-scoped fixture deprecation. |
| Python 3.10/3.11 full matrix | Python 3.10.21 and 3.11.16, `requirements-platform.lock` + `requirements-dev.txt`, isolated `STELLA_HOME`, CI-style pytest-xdist/coverage/timeout (2 workers) and sequential post-flow refresh reruns | Not green after repeated runs. Python 3.10: sequential runs **4,243 passed / 34 skipped / 2 failed** before and after flow refresh; two CI-style runs **4,242/34/3 failed** and **4,243/34/2 failed**. Latest failures were `TestInputs.test_respond_with_stale_revision_conflicts` (401 vs 200) and `test_participation_stream` (no data); both exact tests passed in isolated reruns. Python 3.11: two CI-style runs each **4,244 passed / 34 skipped / 1 failed**; pre-refresh sequential **4,243/34/2 failed** (manifest drift plus auth assertion); after manifest refresh **4,244/34/1 failed** on `TestSubmit.test_submit_empty_objective_rejected` (401 vs 422), which passed in isolated rerun. Treat suite-order/isolation cause as unresolved; isolated reruns do not count as a green matrix. |
| Observability regressions | `.venv/bin/python -m pytest tests/observability -q` | **139 passed**, one existing fixture deprecation. |
| Corona/G05/WebUI policy regression | focused suites under isolated test data | **75 passed**; follow-up import-boundary subset **15 passed**; WebUI conversation/manage subset **17 passed**. |
| Ruff | `.venv/bin/ruff check .` | Passed after final source changes. |
| Dashboard | `pnpm --dir dashboard test` | **9 files, 110 tests passed**. |
| Dashboard build | `pnpm --dir dashboard build` | Typecheck and Vite build passed. Existing mixed static/dynamic import and large-chunk warnings remain. |
| Static asset sync | `pnpm --dir dashboard sync:webui` | Passed; synced to `webui/dist` and `desktop/dashboard-dist`. |
| Message-flow manifest | `scripts/generate_message_flow.py --check` under Python 3.10.21, 3.11.16, 3.12.10, and 3.12.14 | All passed for `message-flow.7c3a08d0677e.json`; the prior `462d5c256f73` artifact remains a historical immutable snapshot. |
| Documentation | `python3 scripts/check_docs.py` | Final check passed after report/state/plan edits: **121 files / 1,327 local links / 577 migration anchors / 0 errors**. |
| Native/Rust | Isolated `/tmp` Rust 1.99.1, Python 3.12.10, maturin 1.15.0; target dir `/tmp/stella-p10-native-target` | `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, and `cargo test` passed (**26 passed**). Built and installed abi3 wheel `/tmp/stella-p10-native-wheel-final/stella_memory_rust-0.1.0-cp310-abi3-manylinux_2_34_x86_64.whl`; exported API 4/schema 23 matched Python source. `scripts/validate_rust_fullchain.py` against the installed wheel passed end-to-end: retrieval smoke, strong candidate promotion, weak conflicting candidate remains OBSERVING, parity `differ: false`, backend/commit and flow integrity checks. |
| Restore drill | Isolated temporary SQLite database and `restore-drill.json` under `/tmp/stella-p10-restore-drill-_o3d9d7p` | **PASS**: schema 22 backup, migration to 23, integrity checks, restore exact pre-migration snapshot to 22, then re-migrate to 23; legacy row and message tables preserved. Three integrity checks passed. |
| Platform/release | Live accounts, clean Windows VM and release runner | Not run. Real QQ/WebChat/platform and model checks are explicitly deferred until this branch is merged to `main`; no live or release certification is inferred from fixtures. Clean VM and release acceptance remain open. |

## GitNexus evidence and limits

Before source edits, `create_corona_app` upstream impact was MEDIUM (18 impacted nodes, 9 direct, one main process); the FastAPI `lifespan=lifespan` callback was also source-checked. `memory.pre_processors.record_message` was UNKNOWN with zero indexed callers and three receiver-typed call sites omitted; source search was used, and the P10 edit changed only the G05 negative assertion. `platform_conversation_settings_put` was UNKNOWN/zero and source-audited as a FastAPI-decorated route; no route change was made. The generator file impact was LOW (four direct imports across three modules); the script was inspected directly.

At the P10 source closeout, staged GitNexus detections reported:

- Corona app/G05 changes: **HIGH** (3 files, 4 symbols, 6 flows).
- Generator stabilization: **CRITICAL** (2 files, 1 indexed symbol, 753 affected flows). The indexed `counts` property attribution is broad and includes unrelated symbols/processes; CRITICAL is retained without waiver.
- Final flow JSON: one changed file with no indexed symbol overlap. This is unresolved graph coverage, not a clean result; the large generated artifact is outside indexed symbol extraction and was independently checked by both Python flow commands and 139 observability tests.
- Cumulative compare-to-main stayed **CRITICAL**; the indexed process/symbol attribution is lower-bound and output lists are capped. The refreshed 1.6.12 PDG index still omits 40 large files, has 3,324 of 3,524 entry candidates unranked, drops 931 callees, cuts 46 walks, depth-caps 23 traces, and leaves 364 cross-language property sites unresolved.

For the native follow-up, `impact verify_candidate_evidence --direction upstream` was **CRITICAL** (11 impacted nodes, about 183 process attributions across 20 modules); the warning was retained before editing. `process_new_candidates` file impact was also CRITICAL/partial, so that production path was not edited. The Rust test helper was LOW and confined to the test cluster. `scripts/validate_rust_fullchain.py` impact was UNKNOWN/zero; source audit found no executable consumers and treated the script as manual validation only. Precommit graph checks including the follow-up reported scope all **4 files / 12 symbols / 770 processes / CRITICAL** and compare-to-main **91 files / 319 symbols / 789 processes / CRITICAL**; broad `db_path` / `user_id` attribution is retained, with no waiver. Neither run marked partial/truncated; process listings were capped.

No HIGH or CRITICAL risk was waived. Final staged state-file detection: `detect-changes --scope all` reported 5 files / 14 symbols / 0 processes / LOW. Repeated `detect-changes --scope compare --base-ref main` runs reported 90 files / 314–444 symbols / 777–797 processes / CRITICAL; all completed outputs retained CRITICAL. Identical staged inputs produced varying symbol/process attribution. Neither scope marked partial/truncated. The compare display is capped (the latest output hid 787 additional affected flows). The result is cumulative and includes broad generic `user_id` attribution; retain CRITICAL without waiver.

## Remaining acceptance work

1. Resolve the non-reproducible Python 3.10/3.11 full-suite WebUI/CAS/auth/trace failures and obtain green full matrix runs. Python 3.12.14 full suite is green. Python 3.12.3/3.12.14 agreement applies to message-flow serialization, not the entire test suite.
2. P04 local native wheel/API-schema parity and rollback/restore drill are complete using isolated toolchains and temporary data; retain Windows release/clean-VM acceptance as open.
3. After this branch is merged to `main`, obtain the official adapter fixture/live and L0–L3 evidence, model acceptance, QQ/WebChat checks, and platform credentials/test windows; keep all untested rows `not_certified`.
4. Complete clean Windows VM/installer and release/CI acceptance. No CI run or artifact is claimed in this local report.

Until those gates have evidence, keep P10 and `XPLAT-PIPELINE-IMPLEMENTATION` blocked and the plan NOT READY.
