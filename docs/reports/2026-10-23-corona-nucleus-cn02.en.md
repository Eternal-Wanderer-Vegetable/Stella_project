# Corona / Nucleus Implementation CN02 — Managed Entry and Bounded Lifecycle

Date: 2026-10-23 (Asia/Shanghai) · Branch: `codex/corona-nucleus-implementation` · CN02 base: `336dc78`

**Package status: CN02 code package complete. CORONA-IMPL remains in progress / NOT READY.** The default `python bot.py` entry still uses legacy startup. The Corona supervisor, full process-tree ownership, and successor control belong to CN03 and later. This package adds only an explicit managed Nucleus mode.

## GitNexus and edit risk

The 1.6.12 / PDG index was checked against CN01 HEAD `336dc78`; it covered 1,926 files. After source edits, `status` correctly showed 5 changed / 6 added. The dirty worktree was not reindexed, which would overwrite the pre-commit delta. Pre-edit upstream impacts and UNKNOWN follow-up:

| Target | Upstream risk / callers | Decision and evidence |
| --- | --- | --- |
| `bot.py` | UNKNOWN / 0 graph callers | Source audit confirmed Docker, shell, deploy CLI, smoke, desktop launcher, and release workflow string/entry references. Managed startup uses a non-`__main__` `runpy` name; legacy remains default. |
| `spawn_successor` | LOW / 2 impacted, 1 direct | Refuses successor spawning in managed mode; existing service→route chain remains. |
| `_find_uvicorn_server` | LOW / 3, 1 direct | Reads the active lifecycle server in managed mode; preserves legacy behavior. |
| `_graceful_shutdown_body` | LOW / 3, 1 direct | Shutdown hooks use the shared deadline; existing business cleanup remains. |
| `_stop_cometa` | LOW / 3, 1 direct | Existing Cometa stop hook uses the shared remaining budget. |
| `_start_scheduling`, `_start_cometa` | UNKNOWN / 0 graph edges | Dynamic `@get_driver().on_startup` decorators are omitted by the static graph. Source confirms registration; the managed bridge moves these callbacks after the ready gate without changing legacy decorators. |
| `cometa.runtime.stop` | UNKNOWN / 0 | Source `_stop_cometa()` keeps the runtime object and calls it dynamically; Cometa implementation was not changed. |

No HIGH / CRITICAL impact was found. The graph misses dynamic decorators, receivers, and some launchers; source-reference checks supplement UNKNOWN results rather than treating them as unused.

## Implementation

- Added `nucleus.bootstrap`, `nucleus.framework`, `nucleus.lifecycle`, and the `python -m nucleus` entry. Bootstrap reconstructs the business environment only from the CN01 immutable revision, validates project/instance/generation identity, loopback bind, and project cwd, then resolves the effective `DB_PATH`. The launch capability remains in lifecycle memory and is removed from the process environment.
- `BusinessRootLock` holds a POSIX `flock` or Windows `msvcrt` handle lock keyed by the canonical SQLite path. It is acquired before Bot/plugin assembly; conflicts exit with code 73 before importing the business stack.
- Managed `bot.py` skips Dashboard source builds, Corona registration/replacement, legacy `nonebot.init`, and successor side effects. `core.self_restart.spawn_successor` fails closed in managed mode. Without the managed marker, legacy startup remains unchanged.
- The NoneBot bridge requires exactly version 2.5.0 and uses explicit `Env(_env_file=None)` / `Config(_env_file=None)`. Private resolver, Driver registry, and lifespan callback access are confined to `nucleus/framework.py`. Scheduler and Cometa callbacks retain their legacy startup decorators, but managed startup defers them until after the ready gate.
- Private health/drain/stop routes require a loopback peer, Bearer capability, and matching controller/generation/revision identity. Ordinary HTTP receives structured 503 responses before ready or after drain; health responses omit the token. Repeated drain cannot extend one shutdown deadline; hooks consume its remaining budget and the watchdog forces process exit on timeout.
- Existing memory, scheduling, Cometa, and facade shutdown/delivery behavior remains in place. Nucleus does not spawn a successor.

## Acceptance and verification

| Command / check | Result |
| --- | --- |
| `STELLA_HOME=/tmp/stella-cn02-final-targeted .venv/bin/python -m pytest tests/nucleus -q` | **9 passed / 2.17s**; includes a real managed Nucleus OS process, identity health, immunity to live source edits, no token leakage, duplicate DB writer refusal, and drain/stop/exit. |
| `STELLA_HOME=/tmp/stella-cn02-final-process .venv/bin/python -m pytest tests/nucleus/test_managed_process.py -q -s` | **1 passed / 1.49s**; real process exits 0 and a second writer exits 73 while the first generation retains the lock. |
| Startup source guard + `tests/test_self_restart.py` | **7 passed / 1.27s**. |
| Repository `.venv/bin/ruff check .` | Passed. |
| `scripts/generate_message_flow.py --check` | Passed; manifest `message-flow.982a65f5aef2.json` matches source. |
| `compileall` for changed modules | Passed. |
| `python3 scripts/check_docs.py` | 119 files / 1,272 local links / 577 anchors / 0 errors. |
| `git diff --check` | Passed (will rerun after reports/state and final staging). |
| Full suite: `STELLA_HOME=/tmp/stella-cn02-final-full-20261023 .venv/bin/python -m pytest -q` | **4037 passed / 29 skipped / 1 failed / 239.71s**. The sole failure, `tests/webui/test_webui_cometa.py::TestInputs::test_respond_with_stale_revision_conflicts`, received 401 instead of 202 in the full-suite sequence. The same test passed alone (**1 passed / 0.66s**). Cause is unconfirmed; the full gate is not green. |

Tests used isolated temporary `STELLA_HOME` values and pytest `tmp_path`; no real user `.env`, production database, chat records, or credentials were read or changed. No real model, QQ/WebChat, Docker, or deployed service was started.

Process-level ready, immunity to live `.env` edits, duplicate database writer refusal, authenticated drain/stop, and normal process exit are demonstrated. Shutdown deadline and watchdog behavior are covered by lifecycle tests. CN03 still needs OS process-tree fencing and proof of descendant exit; the core lock alone does not prove this. Windows locking was not validated on Windows.

## Pre-commit GitNexus change gates

Both staged-tree gates were run serially:

| Command | Result |
| --- | --- |
| `node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project --limit 1000` | 16 files / 9 symbols / 1 affected process / **MEDIUM**; changed flow is `System_restart → Bot_entry` (`spawn_successor`). No partial / truncated indicator. |
| `node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` | 146 files / 291 symbols / 58 affected processes / **CRITICAL**, cumulative across CN00, CN01, and the inherited plan baseline. Serial output had no partial / truncated indicator; the terminal abbreviated the tail of the detailed symbols/flows list. |

All and compare ran serially. The raw CRITICAL compare is retained and is not waived by focused tests.

## Next

CN03: build the standalone Corona app and sole supervisor, core state machine, OS ownership lock, process-tree/descendant exit confirmation, startup logs, and crash backoff. Verify that Corona control remains available for core import failure, hang, crash, and foreign-PID cases.
