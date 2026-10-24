# Corona / Nucleus CN00 Implementation Record

Date: 2026-10-23 (Asia/Shanghai). Status: **CN00 complete; CN01 next; CORONA-IMPL remains NOT READY.**

## Scope and graph impact

The implementation branch is `codex/corona-nucleus-implementation`; this package is bound to GitNexus at `864c08f`. That commit archives the plan and its evidence from the original worktree. CN00 did not change `bot.py`, `config/settings.py`, deploy, or business runtime code.

- `config/settings.py` upstream impact is **CRITICAL**: 278 affected symbols and 76 direct dependants. The file was not edited.
- `bot.py` is **UNKNOWN / 0 graph callers**. Source-reference inspection confirms that `entrypoint.sh`, `deploy/process.py`, and `deploy/__main__.py` launch it; desktop and installer code also use it as a project-root anchor. Zero graph edges are not treated as proof of no callers.
- `register_enabled_adapters` is LOW with one direct caller: `bot.py`.
- GitNexus 1.6.12 was force-rebuilt and bound to `864c08f`; status is up to date. The graph contains 105,886 nodes, 264,173 edges, 1,126 clusters, and 814 bounded flows. Analysis still omits 34 files larger than 512 KiB and reports 2,892 entry-point candidates, 804 callee branches, 41 walk-budget cuts, and 21 trace-depth caps, plus cross-language field boundaries. The initial FTS build failed; `analyze --repair-fts` also failed, then `analyze --force` rebuilt successfully. These limits do not prove that omitted paths are unused.
- Pre-commit `detect-changes --scope all --repo Stella_project --limit 1000` on the staged CN00 deliverables completed with 9 files / 27 symbols / 0 affected processes / LOW. `detect-changes --scope compare --base-ref main --repo Stella_project --limit 1000` completed with 112 files / 141 symbols / 0 affected processes / LOW. A parallel compare was interrupted and returned PARTIAL; it was discarded and rerun alone. The standalone accepted result had no partial/truncated marker. Compare includes inherited staged work from earlier phases on this branch.

## Frozen contracts

- **Configuration and framework:** The current CI lock, `requirements-platform.lock`, pins `nonebot2==2.5.0`; the new regression only establishes this version. In NoneBot 2.5.0, `nonebot.init(_env_file=None)` still reads the working-directory dotenv through its default `Env()`. The implementation must centralize `Env(_env_file=None)`, `Config(_env_file=None, ...)`, and the `_resolve_combine_expr` / global Driver registration bridge in `nucleus/framework.py`, guarded by a version check. Private calls must not spread through modules, and `init(None)` must not be treated as disabling dotenv. Current `pyproject.toml` and `requirements.txt` retain `>=2.5.0`; versions without the same initialization contract do not gain managed-bridge compatibility claims.
- **Paths:** Nucleus keeps `PROJECT_ROOT` as its working directory and receives `STELLA_HOME` explicitly in its run environment. Plugin and `pyproject.toml` relative paths resolve from there. Snapshot loading must not use a global `chdir` to bypass dotenv.
- **Identity and operations:** The internal protocol has its own v1 version. Identity includes stable `instance_id`, `controller_boot_id`, `generation_id`, launch token, PID plus creation identity, program root, canonical data root, and configuration revision. Every accepted management operation receives an `operation_id`; its persistent snapshot records phase, target/applied revision, generation, terminal status, redacted error, and whether configuration recovery ran. Keep the `{status,message,data}` envelope and stable error `code`; do not return secrets or raw exception stacks. Pass generation capabilities only through the protected bootstrap channel, never URL or argv.
- **Shutdown and locks:** One monotonic deadline covers the full drain. The initial contract is 45 seconds graceful, 10 seconds force/reap, and at least 65 seconds for the host; CN10 will calibrate it from measurements. The lock choice is an OS region lock held by a live process handle: POSIX `fcntl.flock(LOCK_EX | LOCK_NB)` and Windows `msvcrt.locking(LK_NBLCK, 1)`. Keep lock files stable; file existence alone does not mean a lock is held. Key the instance lock by instance ID and writer locks by **canonical actual database paths**, not only `STELLA_HOME`. CN03/CN10 will implement path registration and verify both platforms. References: [Python fcntl](https://docs.python.org/3.10/library/fcntl.html#fcntl.flock), [Python msvcrt](https://docs.python.org/3.10/library/msvcrt.html#msvcrt.locking).
- **Recovery:** Configuration-revision recovery stays separate from program/database rollback. Never start the next generation until the prior writer is confirmed exited and its database lock released.

## Acceptance evidence

| Check | Result |
| --- | --- |
| Eight existing lifecycle, deploy, and WebUI baseline files with isolated `STELLA_HOME` | **83 passed / 35.75s** |
| `tests/corona/test_config_source_snapshot.py`, `tests/nucleus/test_snapshot_driver.py` | **3 passed / 0.86s** |
| Ruff on new tests | Passed |
| `verify_plan.py` and current source fingerprints/contracts | 12 packages; 199 fingerprints; 133 routes (21 control / 111 business / 1 split); 426 configuration keys; 34 acceptance scenarios; 30 archive links and 77 evidence hashes passed |
| Adapter/dynamic-entry audit | Default adapter is OneBot V11; `STELLA_ADAPTER_MODULES` is dynamically assembled by `parse_adapter_modules` / `register_enabled_adapters`; the WebUI routes match the reviewed static list. Candidate counts are not treated as behavior coverage. |
| Configuration source ordering | Inherited process keeps 11; a fresh process reads 22; deletion falls back to 90; external environment overrides to 44; `.env.prod` overrides to 33 |
| NoneBot Driver spike | In an isolated child, first reproduces `init(None)` reading a synthetic cwd `.env`, then creates a real FastAPI Driver with explicit no-file `Env/Config`; port 19001 stays stable and cwd is unchanged. No Bot/server is started. |
| Entry order contract | Static assertion for token → source Dashboard build / fail-fast → legacy takeover → `nonebot.init` → adapter/plugins → WebUI; no real Bot is started |
| User-data boundary | Tests use `tmp_path` / temporary directories; no host `.env` contents or production DB were read, and no model, QQ, or WebChat connection was opened |
| Documentation links | `python3 scripts/check_docs.py`: 119 files / 1266 local links / 577 anchors / 0 errors; `git diff --check` passed |
| GitNexus pre-commit change detection | all: 9 files / 27 symbols / 0 processes / LOW; compare main: 112 files / 141 symbols / 0 processes / LOW. First parallel compare was PARTIAL and discarded; standalone rerun completed |

The entry-order regression is a source contract check, not a substitute for real process startup/shutdown acceptance. OS locks are not implemented on Linux; Windows lock behavior, fault recovery, full Python/Dashboard/Rust checks, live platforms, clean VMs, Docker, and release products remain for later packages. The product remains NOT READY.

## Next

Proceed to CN01: implement the pure bootstrap package and immutable configuration revisions, covering dotenv positive/negative cases, unknown plugin keys, permissions, two-revision isolation, and the legacy configuration baseline. Before CN02, move this Driver spike into the centralized framework adapter.
