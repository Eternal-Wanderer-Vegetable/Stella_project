# Corona / Nucleus CN01 Implementation Record

Date: 2026-10-23 (Asia/Shanghai). Status: **CN01 complete, CN02 next; CORONA-IMPL remains NOT READY.**

## Scope and graph impact

Branch: `codex/corona-nucleus-implementation`; CN01 is based on `f9d6920` (CN00 completion). Before implementation, GitNexus 1.6.12 with PDG was bound to that HEAD. Its known file-size, entry-candidate, branch-budget and cross-language limits remain relevant; UNKNOWN or missing flows are not evidence of no callers.

| Target | Upstream impact before edits | Direct impact |
| --- | --- | --- |
| `config/__init__.py` | CRITICAL, 205 affected / 69 direct | bot, capability and core entry points |
| `config/home.py` | CRITICAL, 236 / 5 | cometa/config, settings, deploy and release-layout checks |
| `config/instance.py` | CRITICAL, 218 / 2 | settings and deploy process |
| `config/settings.py` | CRITICAL, 278 / 76 | AstrBot compatibility, bot, capability, core and WebUI; high risk was disclosed before editing |
| adapter/env parsers, schema and envfile | LOW: 4/2, 11/3, 15/3 and 10/4 | adapter setup, deploy config merge/schema and several WebUI config flows |
| `scripts/build_release_package.py` | UNKNOWN / 0 graph callers | source audit found `.github/workflows/release.yml`, evaluation script and test references; new packages had to enter the common payload |
| new test file and new packages | no graph nodes for new files; existing fixture files UNKNOWN / 0 | supplemented by import fence, release layout and focused regressions |

The indexed `resolve` call set omitted many sites due to unknown receiver types. Dynamic adapter/config flows also have entry truncation. Source and regression evidence supplements these gaps; LOW risk does not waive missed callers. Both new packages are now included in release `COMMON_DIRS` and the standalone/OneClick fixtures.

## Implementation

- Added `stella_bootstrap/` for home, identity, adapter-name, dotenv/raw-env parsing, AST schema reading, and config revision build/load. Existing `config.home`, `config.instance`, `deploy.env_schema`, and adapter parser paths remain compatibility exports.
- Added immutable `stella_contracts.ConfigRevision` with strict revision/source validation, read-only mappings, and redacted public metadata. Unknown plugin keys are retained. Revisions have opaque IDs, per-source digests, and write-once files.
- Config building uses explicit pure inputs and preserves defaults < base `.env` < captured external environment < selected profile overlay. `ENVIRONMENT` selection comes from base/external values and cannot be reselected by the overlay. Control identity keys, OS variables and the revision marker are excluded from business config. Parsing reuses python-dotenv syntax and variable expansion with synthetic inputs; it does not read the user home.
- POSIX revision files/directories use 0600/0700 and reject broad modes, symlinks and mismatched storage paths. Writes use a temporary file, file fsync, atomic replace and directory fsync. Windows configures an `icacls` ACL for the current SID, but Windows behavior was not tested on this host.
- `STELLA_CONFIG_REVISION_FILE` is an explicit opt-in. Managed `config.settings` reads only that revision, checks the project root, skips both dotenv layers and does not let stale inherited business values override the snapshot. Without the marker, the legacy dotenv path remains active. `PROJECT_ROOT` stays the cwd; there is no `chdir`.
- The WebUI `envfile` service imports settings lazily to avoid loading business configuration merely by importing the leaf service.
- Release `COMMON_DIRS` and standalone/OneClick fixtures include both packages so source-only tests cannot conceal a missing runtime payload.

## Verification evidence

| Check | Result |
| --- | --- |
| CN01 revision/dotenv/home/identity/schema/merge/adapter/WebUI/release tests plus CN00 contracts | **148 passed / 3.12s**, isolated `STELLA_HOME=/tmp/stella-cn01-isolated-home-20261023` |
| Ruff on changed modules and tests | Passed |
| Repository Ruff (`ruff check .`) | Passed |
| `compileall` for new bootstrap/contracts and related changed modules | Passed |
| Revision data and permissions | Synthetic regressions cover consecutive-process isolation, external precedence, empty/inherit/delete semantics, unknown-key retention, invalid known types, read-only values, redacted metadata, and file/parent permission rejection |
| Import fence / cwd | New subprocess import avoids fenced legacy business modules; synthetic cwd remains unchanged and external dotenv files do not contaminate revision config |
| Legacy configuration baseline | Existing home, identity, env merge/schema, adapter and WebUI settings tests are included; absence of the managed marker preserves the legacy branch |
| Documentation state | `python3 scripts/check_docs.py`: 119 files / 1269 local links / 577 anchors / 0 errors; `git diff --check` passed |
| User data boundary | Temporary STELLA_HOME and synthetic dotenv only; no host `.env`, real chats, production DB or credentials read; no Bot/model/platform started |

The full Python suite was not fully green in either run: first **4027 passed / 29 skipped / 2 failed / 238.99s**; second **4028 passed / 29 skipped / 1 failed / 243.96s**. The first run's Cometa worker-policy ACK and WebUI trace-detail failures, and the second run's Cometa unknown-session failure, each passed when rerun alone. The failure sets differed; no shared root cause or causal link to CN01 was established. Individual reruns are not reported as a full-suite pass; this remains a regression-stability gap.

## GitNexus commit gates

The final forced 1.6.12 / PDG rebuild succeeded: 106,344 nodes / 265,516 edges / 1,115 clusters / 823 inferred flows. `status` reports matching content for all 1,926 covered files and an up-to-date index. Analysis still skips 34 large files and reports 2,910/3,110 entry candidates unranked, 807 dropped callee branches, 42 walk-budget cuts, 25 trace-depth caps, and 317 cross-language field sites; attribute flow also hit a cap of 32 for 33 candidates. The graph is a bounded approximation and cannot prove omitted paths absent.

Pre-commit commands ran serially:

| Command | Result |
| --- | --- |
| `node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project --limit 1000` | 28 files / 154 symbols / 57 affected processes / **CRITICAL** |
| `node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | 135 files / 287 symbols / 57 affected processes / **CRITICAL**, including inherited plan/CN00 work |

Neither output reported partial/truncated; all and compare ran serially. CRITICAL reflects the cumulative impact of the existing broad settings/config call graph. Focused regressions do not waive the broader full-suite and external acceptance work.

This host did not run the Windows ACL branch, the complete Python suite, a real managed Nucleus process, QQ/WebChat, Docker or a clean VM. Windows ACL behavior still needs Windows validation. Product remains **NOT READY**.

## Next

Proceed to CN02: implement the Nucleus framework adapter, startup order and bounded lifecycle on top of the snapshot Driver spike and controlled config source. Keep managed framework internals inside `nucleus/framework.py`; separately verify child-process ready/drain/exit, immunity to later source changes, dual-core rejection and timeout failure semantics.
