# XPLAT P10 validation and closeout evidence — 2026-10-26

## Status

P10 source changes, Python 3.12.14 full suite, Dashboard, documentation, and immutable message-flow gates are complete. Python 3.10.21 and 3.11.16 full-suite runs were attempted with CI dependencies and scheduling; both versions had changing, non-reproducible WebUI/CAS/auth failures, so the Python matrix is **not green**. P10 remains **blocked**, and the overall XPLAT plan remains **NOT READY**, also pending Rust/native, live adapter/model, restore-drill, and clean Windows VM/release evidence. The official adapter matrix remains **0/32 certified**. P04 native wheel/API parity and restore drill remain open.

No production `STELLA_HOME`, database, credentials, chats, running service, Bot, platform account, release environment, or user configuration was accessed. Python tests used temporary `STELLA_HOME` roots. CI-style coverage also reported generated `data/plugins/stella_*_selftest` source paths after their fixtures had cleaned them up; a name-only check found no matching directories remaining, and `git status` showed no test-generated workspace changes.

## P10 commits

- `30cdf87 fix(transport): close final validation boundary gaps` — kept the Corona controller app import boundary free of product/business runtime imports until app construction; corrected the G05 denied-capture assertion for the case where the table has not yet been created.
- `cefec48 fix(observability): stabilize flow closure across Python versions` — normalized serialized string and callable-target formatting so the generated closure is stable across Python 3.12 patch versions.
- `47548f0 chore(observability): publish stable P10 message flow` — published `core/observability/flows/message-flow.462d5c256f73.json`, topology 2026.10.21, 144 nodes, 142 source-resolved nodes, 9,688 closure sites, and 15,598 reachable symbols.

The first generated artifact `message-flow.3bf7…` was removed before final publication: Python 3.12.3 and 3.12.14 had different AST unparse formatting for callable arguments. The generator change was validated by matching the complete manifest hash across both interpreters; only the final `462d5c256f73` artifact remains.

## Verification evidence

| Gate | Command / environment | Result |
| --- | --- | --- |
| Full Python suite | `env -u STELLA_TRANSPORT_SETTINGS_JSON STELLA_HOME=/tmp/stella-p10-full-final-20261026 .venv/bin/python -m pytest tests -q` (locked Python 3.12.14) | **4,245 passed, 34 skipped, 3 warnings**, exit 0, 292.74s. Two existing duplicate FastAPI operation-ID warnings and one existing pytest class-scoped fixture deprecation. |
| Python 3.10/3.11 full matrix | Python 3.10.21 and 3.11.16, `requirements-platform.lock` + `requirements-dev.txt`, isolated `STELLA_HOME`, CI-style pytest-xdist/coverage/timeout (2 workers) | Not green after repeated runs. Python 3.10: sequential **4,243 passed / 34 skipped / 2 failed**; two CI-style runs **4,242/34/3 failed** and **4,243/34/2 failed**. Python 3.11: two CI-style runs each **4,244 passed / 34 skipped / 1 failed**. The failing WebUI/CAS/auth/trace cases varied; targeted reruns of the observed failures passed individually. Treat suite-order/isolation cause as unresolved, not as a passing matrix. |
| Observability regressions | `.venv/bin/python -m pytest tests/observability -q` | **139 passed**, one existing fixture deprecation. |
| Corona/G05/WebUI policy regression | focused suites under isolated test data | **75 passed**; follow-up import-boundary subset **15 passed**; WebUI conversation/manage subset **17 passed**. |
| Ruff | `.venv/bin/ruff check .` | Passed after final source changes. |
| Dashboard | `pnpm --dir dashboard test` | **9 files, 110 tests passed**. |
| Dashboard build | `pnpm --dir dashboard build` | Typecheck and Vite build passed. Existing mixed static/dynamic import and large-chunk warnings remain. |
| Static asset sync | `pnpm --dir dashboard sync:webui` | Passed; synced to `webui/dist` and `desktop/dashboard-dist`. |
| Message-flow manifest | `python3 scripts/generate_message_flow.py --check` and `.venv/bin/python scripts/generate_message_flow.py --check` | Both passed for `message-flow.462d5c256f73.json`; complete generated content hash matches across Python 3.12.3 and 3.12.14. |
| Documentation | `python3 scripts/check_docs.py` | Passed after report and state edits: **121 files / 1,325 local links / 577 migration anchors / 0 errors**. |
| Native/Rust | cargo/rustc/rustup/maturin availability | Not available on PATH; native build, wheel, API parity, schema parity and restore drill not run. |
| Platform/release | live accounts, clean Windows VM and release runner | Not available; no live or release certification is inferred from fixtures. |

## GitNexus evidence and limits

Before source edits, `create_corona_app` upstream impact was MEDIUM (18 impacted nodes, 9 direct, one main process); the FastAPI `lifespan=lifespan` callback was also source-checked. `memory.pre_processors.record_message` was UNKNOWN with zero indexed callers and three receiver-typed call sites omitted; source search was used, and the P10 edit changed only the G05 negative assertion. `platform_conversation_settings_put` was UNKNOWN/zero and source-audited as a FastAPI-decorated route; no route change was made. The generator file impact was LOW (four direct imports across three modules); the script was inspected directly.

At the P10 source closeout, staged GitNexus detections reported:

- Corona app/G05 changes: **HIGH** (3 files, 4 symbols, 6 flows).
- Generator stabilization: **CRITICAL** (2 files, 1 indexed symbol, 753 affected flows). The indexed `counts` property attribution is broad and includes unrelated symbols/processes; CRITICAL is retained without waiver.
- Final flow JSON: one changed file with no indexed symbol overlap. This is unresolved graph coverage, not a clean result; the large generated artifact is outside indexed symbol extraction and was independently checked by both Python flow commands and 139 observability tests.
- Cumulative compare-to-main stayed **CRITICAL**; the indexed process/symbol attribution is lower-bound and output lists are capped. The refreshed 1.6.12 PDG index still omits 40 large files, has 3,324 of 3,524 entry candidates unranked, drops 931 callees, cuts 46 walks, depth-caps 23 traces, and leaves 364 cross-language property sites unresolved.

No HIGH or CRITICAL risk was waived. Final staged state-file detection: `detect-changes --scope all` reported 5 files / 14 symbols / 0 processes / LOW. Repeated `detect-changes --scope compare --base-ref main` runs reported 90 files / 314–444 symbols / 777–797 processes / CRITICAL; all completed outputs retained CRITICAL. Identical staged inputs produced varying symbol/process attribution. Neither scope marked partial/truncated. The compare display is capped (the latest output hid 787 additional affected flows). The result is cumulative and includes broad generic `user_id` attribution; retain CRITICAL without waiver.

## Remaining acceptance work

1. Resolve the non-reproducible Python 3.10/3.11 full-suite WebUI/CAS/auth/trace failures and obtain green full matrix runs. Python 3.12.14 full suite is green. Python 3.12.3/3.12.14 agreement applies to message-flow serialization, not the entire test suite.
2. Provision an isolated Rust/maturin toolchain and perform the P04 native wheel/API-schema parity and rollback/restore drill using temporary data.
3. Obtain the official adapter fixture/live and L0–L3 evidence, model acceptance, QQ/WebChat checks, and platform credentials/test windows; keep all untested rows `not_certified`.
4. Run clean Windows VM/installer and release/CI acceptance. No CI run or artifact is claimed in this local report.

Until those gates have evidence, keep P10 and `XPLAT-PIPELINE-IMPLEMENTATION` blocked and the plan NOT READY.
