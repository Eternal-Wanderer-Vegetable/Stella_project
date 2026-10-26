# XPLAT P10 validation and closeout evidence — 2026-10-26

## Status

P10 local gates are complete, including the Python 3.10.21 / 3.11.16 / 3.12.14 full-suite matrix. During this turn, full-suite failures exposed two local edge cases and both were fixed: PyJWT rejected a correctly signed token when `iat` was a few seconds ahead of the verifier clock, and compact admission rejected a negative elapsed age after a wall-clock correction. The final full runs are green on all three Python versions. Overall XPLAT remains **NOT READY** because real platform/model acceptance is explicitly deferred until this branch is merged to `main`, and clean Windows VM/release acceptance remains open. No live account or platform validation was run. The official adapter matrix remains **0/32 certified**.

No production `STELLA_HOME`, database, credentials, chats, running service, Bot, platform account, release environment, or user configuration was accessed. Python tests used temporary `STELLA_HOME` roots. CI-style coverage also reported generated `data/plugins/stella_*_selftest` source paths after their fixtures had cleaned them up; a name-only check found no matching directories remaining, and `git status` showed no test-generated workspace changes.

## P10 commits

- `30cdf87 fix(transport): close final validation boundary gaps` — kept the Corona controller app import boundary free of product/business runtime imports until app construction; corrected the G05 denied-capture assertion for the case where the table has not yet been created.
- `cefec48 fix(observability): stabilize flow closure across Python versions` — normalized serialized string and callable-target formatting so the generated closure is stable across Python 3.12 patch versions.
- `47548f0 chore(observability): publish stable P10 message flow` — published `core/observability/flows/message-flow.462d5c256f73.json`, topology 2026.10.21, 144 nodes, 142 source-resolved nodes, 9,688 closure sites, and 15,598 reachable symbols.
- `d03d9b5 fix(memory): align native promotion evidence contract` — native evidence verification accepts legacy and current assessment versions, binds current namespaced snapshots to opaque subject and connection identity, and keeps the legacy QQ path; the fullchain fixture now seeds the current contract.
- `bc2f396 chore(observability): refresh P10 flow after native follow-up` — published `message-flow.7c3a08d0677e.json` after the native source-anchor change.
- `36b7116 docs(plan): record native P04 and P10 local evidence` — synchronized bilingual contracts, P10 report, implementation status, and the safely snapshotted generated plan.
- `6023108 fix(auth): tolerate future iat on signed webui tokens` — kept signature and expiration checks while treating signed `iat` as metadata, avoiding clock-step 401s.
- `4cdca91 fix(memory): clamp future timestamps during compact admission` — clamps a negative elapsed backlog age to zero at the compact call site and adds a deterministic regression.
- `dae99f9 chore(observability): refresh flow after local auth and compact fixes` — published the current immutable flow artifact.

The original P10 flow artifact was `message-flow.462d5c256f73.json`; `message-flow.7c3a08d0677e.json` remains an intermediate immutable snapshot. The latest source changes produced `message-flow.f34e06379153.json`, topology 2026.10.21 with 144 nodes, 142 source-resolved nodes, 9,694 closure sites, and 15,598 reachable symbols. Its `--check` passes on Python 3.10.21, 3.11.16, 3.12.3, and 3.12.14.

## Verification evidence

| Gate | Command / environment | Result |
| --- | --- | --- |
| Python 3.10.21 full suite | `env -u STELLA_TRANSPORT_SETTINGS_JSON STELLA_HOME=/tmp/stella-p10-python310-final-20261026 /tmp/stella-p10-python310/bin/python -m pytest tests -q -n 0 --tb=short` | **4,247 passed, 34 skipped, 3 warnings**, exit 0, 307.58s. |
| Python 3.11.16 full suite | `env -u STELLA_TRANSPORT_SETTINGS_JSON STELLA_HOME=/tmp/stella-p10-python311-final-20261026 /tmp/stella-p10-python311/bin/python -m pytest tests -q -n 0 --tb=short` | **4,247 passed, 34 skipped, 3 warnings**, exit 0, 294.21s. |
| Python 3.12.14 full suite | `env -u STELLA_TRANSPORT_SETTINGS_JSON STELLA_HOME=/tmp/stella-p10-python312-final-20261026 .venv/bin/python -m pytest tests -q -n 0 --tb=short` | **4,247 passed, 34 skipped, 3 warnings**, exit 0, 295.67s. |
| Focused age / auth regressions | `tests/test_session_compact.py` under Python 3.10.21, 3.11.16, and 3.12.14; `tests/webui` under Python 3.10.21 and 3.11.16 | Compact suite: **43 passed on each version**. WebUI suite: **149 passed on each version**; signed token with future `iat`: **11 auth tests passed on each version**. |
| Observability regressions | `.venv/bin/python -m pytest tests/observability -q` | **139 passed**, one existing fixture deprecation. |
| Corona/G05/WebUI policy regression | focused suites under isolated test data | **75 passed**; follow-up import-boundary subset **15 passed**; WebUI conversation/manage subset **17 passed**. |
| Ruff / Python compile | `.venv/bin/ruff check .`; `.venv/bin/python -m py_compile` on the four changed Python files | Ruff passed for the repository; changed-file compilation passed. |
| Dashboard | `pnpm --dir dashboard test` | **9 files, 110 tests passed**. |
| Dashboard build | `pnpm --dir dashboard build` | Typecheck and Vite build passed. Existing mixed static/dynamic import and large-chunk warnings remain. |
| Static asset sync | `pnpm --dir dashboard sync:webui` | Passed; synced to `webui/dist` and `desktop/dashboard-dist`. |
| Message-flow manifest | `scripts/generate_message_flow.py --check` under Python 3.10.21, 3.11.16, 3.12.3, and 3.12.14 | All passed for `message-flow.f34e06379153.json`; prior artifacts remain immutable history. |
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

For the local authentication repair, GitNexus `decode_token` context/impact was UNKNOWN/not indexed; source search found its sole production caller at `webui/auth.py:99`. `File:webui/security.py` impact was MEDIUM (34 impacted nodes, 6 direct, 3 process attributions). The code only disables `verify_iat`; signature and expiry validation stay enabled. For the compact age repair, `compact_once` was UNKNOWN/not indexed; source search found the production scheduler call in `memory/session_compact.py` and a manual evaluation caller. The exact `memory/session_compact.py` file candidate was HIGH (186 impacted nodes, 2 direct). The shared `gravitas.controller.admit_background` impact was CRITICAL/partial (324 impacted, 55 direct, process enrichment unavailable), and `memory/timeutil.py` impact was HIGH (108 impacted, 22 direct); neither shared boundary was changed. The local fix clamps only the compact call-site age. Precommit staged detection for auth touched 2 files with no indexed symbol overlap; compact touched 2 files / 3 test symbols / 349 process attributions / CRITICAL; the new flow artifact touched 1 file with no indexed symbol overlap. All/compare outputs retained cumulative CRITICAL attribution where present; no risk was waived.

The phase-level GitNexus checks also retained their full aggregate findings: auth scope all 6 files / 3 symbols / 785 processes / CRITICAL, compare-main 96 / 152 / 797 / CRITICAL; compact all 4 / 6 / 785 / CRITICAL, compare-main 96 / 184 / 786 / CRITICAL; flow all 3 / 3 / 0 / LOW, compare-main 97 / 152 / 786 / CRITICAL. These precommit `all` scopes included other modified state/report files; staged scopes isolated the files for each phase. Process listings were capped, but all commands returned exit 0 without a partial/truncated error marker.

No HIGH or CRITICAL risk was waived. At the earlier `36b7116` state closeout, GitNexus `scope=all` reported 5 files / 14 symbols / 0 processes / LOW; repeated `scope=compare --base-ref main` runs reported 90 files / 314–444 symbols / 777–797 processes / CRITICAL. Identical staged inputs varied in symbol/process attribution, and the compare display was capped. The result is cumulative and includes broad generic `user_id` attribution; retain CRITICAL without waiver. The final local-closeout state checks are recorded with the final state commit.

## Remaining acceptance work

1. The local Python 3.10.21 / 3.11.16 / 3.12.14 full-suite matrix is green. P04 local native wheel/API-schema parity and rollback/restore drill are complete using isolated toolchains and temporary data; retain Windows release/clean-VM acceptance as open.
2. After this branch is merged to `main`, obtain official adapter fixture/live and L0–L3 evidence, model acceptance, QQ/WebChat checks, and platform credentials/test windows; keep all untested rows `not_certified`.
3. Complete clean Windows VM/installer and release/CI acceptance. No CI run or artifact is claimed in this local report.

Until those gates have evidence, keep P10 and `XPLAT-PIPELINE-IMPLEMENTATION` blocked and the plan NOT READY.
