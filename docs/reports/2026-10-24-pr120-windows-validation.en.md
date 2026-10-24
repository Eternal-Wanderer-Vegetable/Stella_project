# PR #120 Windows Validation and Fixes

Date: 2026-10-24 (Asia/Shanghai) · Validation baseline: `2d1eb736d65a993136b5215d15b1a00403547ea2` · Branch: `codex/corona-nucleus-implementation`

Scope: Run the PR #120 Python, Windows-native, Rust/Tauri, and Dashboard checks on a Windows host, and fix cross-platform issues found locally. Tests used temporary data directories and locked dependencies. No user configuration, production database, QQ session, or live-platform data was read or written.

## Fixes

- `corona.process_tree` no longer evaluates POSIX-only `signal.SIGKILL` while importing on Windows. The Windows wrapper starts and waits for the core child while both remain in the Job Object. Readiness no longer relies on Windows `getppid()`; it verifies that the reported PID belongs to the managed Job and records the core PID in the supervisor snapshot.
- Windows ignores the POSIX `0o600` mode passed to `os.open`, so the managed log directory now receives a protected DACL for the current user's SID. ACL validation inspects the actual SID and ACE type instead of localized `icacls` account-name text. Tests cover acceptance of the current-user ACL and rejection of a foreign SID.
- HTTP and WebSocket forwarding now separates query bytes from `raw_path` before encoded-slash checks and upstream URL construction. This fixes incorrect rejection when the query contains `%2F` or UTF-8 percent-encoded bytes.
- At the 50ms shutdown boundary, Windows asyncio timeout and system monotonic deadline reads could briefly disagree. Once a hook wait times out, the shared shutdown budget is now explicitly exhausted and later hooks are skipped.
- Stabilized Windows checks: child-process tests preserve `SYSTEMROOT`; fake-core failures use a generation marker written only after the parent observes readiness; the 30ms scheduling window was removed; tests skip symlink creation when the current Windows account lacks that privilege; and the Tauri test module now imports its missing helper.

## GitNexus Impact and Source Checks

- After the Windows code and test changes, GitNexus 1.6.12 was refreshed against the PR worktree by absolute path (current runner identity, `incompleteReasons=[]`). `_set_windows_private_acl` was HIGH (15 impacted nodes, 3 direct callers, 3 affected processes, 4 modules); `_check_windows_private_acl` was CRITICAL (11 nodes, 1 direct caller, 9 affected processes, 3 modules). The concrete DACL call paths were checked against source and config/process tests; no `riskSharedAxes` exemption was used.
- `_kill_process_group` was LOW (3 direct callers, 6 nodes); `CoreSupervisor._await_ready` was LOW (4 nodes, 1 lifespan flow). The Windows process-tree factory call was UNKNOWN because of a dynamic receiver, so `CoreSupervisor._spawn` and `process_tree_factory` were checked in source.
- HTTP, WebSocket, and unsafe-path proxy symbols were LOW. Middleware registration and Nucleus proxy call sites were verified in source. Test-file graph relations were UNKNOWN/0, so pytest discovery and references were checked separately.
- Shutdown budget: `run_shutdown_callback` was LOW (1 direct caller); `remaining_shutdown_seconds` was LOW (7 impacted nodes, 3 direct callers, Nucleus module).

## Validation Results

- Full Windows Python suite on Python 3.11.16: `pytest tests/ -q -n 4 --dist loadgroup --timeout=120 --timeout-method=thread` → **4117 passed / 32 skipped / 6 warnings / 126.37s**. Locked dependencies were used. A temporary `.pth` loaded the test site-packages so subprocesses that sanitize environment variables could still import dependencies; the hook was removed after the run.
- Windows-specific suite: `pytest tests/windows -q -rs --timeout=120 --timeout-method=thread` → **10 passed / 1 skipped / 1.60s**. The only skip was `test_nsis_installation`, because `STELLA_INSTALL_TEST_EXE` was not set. Final installer EXE acceptance still requires the install-test job or an explicitly supplied isolated test environment. Windows Job membership, private ACL, and real `makensis` hook compilation passed.
- The only failure from the first full run—the 50ms shared shutdown-budget test—passed **10 consecutive runs** after the fix. The 14 process/config/NoneBot reproductions from that run passed with the correct dependency environment.
- Ruff for changed Python files, `compileall`, and `git diff --check` passed. `python scripts/generate_message_flow.py --check` passed; the archive is `message-flow.bf4b1dd6f688.json` (144 nodes / 142 source-resolved / 9646 closure sites / 15736 reachable symbols).
- Windows Rust: CLI `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, CLI tests (**22 passed**), runtime-manager tests (**9 passed**), and Tauri desktop tests (**25 passed**). The release CLI build succeeded; `stellacli.exe --version` returned `6.2.0` and `--help` worked.
- The desktop-wide `cargo fmt --all --check` still fails on existing formatting differences across `commands.rs`, `python.rs`, and `main.rs`. These unrelated lines were not mass-formatted; the new test import itself follows rustfmt layout.
- Dashboard Vitest (**110 passed**), production build, and `sync:webui` passed; Dashboard, WebUI, and Tauri static assets match. Docker Compose static configuration validation passed; no container was started and no application image build completed.

## GitNexus Change Gates

- Refreshed graph snapshots contained **114,606 nodes / 1,192 clusters / 796 flows**. Repeated `detect-changes --scope all` runs on report/state-document edits varied: observed outputs included **5 files / 10 symbols / 0 processes / LOW**, **5 files / 1 symbol / 783 processes / CRITICAL** with a generic `Section ?` mapping, and **5 files / 8 symbols / 0 processes / LOW**. Comparisons also varied: against Windows follow-up baseline `2d1eb736`, **22 files / 10–27 symbols / 782–790 processes / CRITICAL**; against `main`, **282 files / 488–833 symbols / 784–791 processes / CRITICAL**. These comparisons did not print a partial/truncated marker. Changed paths cover DACL, Job/PID readiness, proxy, and test code. The output also fans generic `__call__` symbols into Get_config and Cometa flows; literal searches across the changed code/test files found no corresponding `Get_config`, `install_signal_handlers`, `Sha256_hex`, or `Cometa_auth_api_key` names. These flow attributions are not closed by source evidence, so all CRITICAL results remain and none are waived. After indexing the final commit, `scope=all` returned no changes because the working tree had no uncommitted diff; this is not a zero-impact claim.
- The `main` samples are cumulative branch risk, not the local Windows diff.
- The graph still omits 3200/3400 candidate entry points, skips 952 callees, cuts 43 walks, and depth-caps 23 traces. Thirty-eight files over 512KB were skipped, including the 3.9MB flow manifest. Missing graph edges are not evidence of no impact.

## Acceptance Still Open

This Windows host is not a clean VM. Final installer EXE install/upgrade/rollback, clean Windows/Linux VMs, Docker application build and runtime, real QQ/OneBot, WebChat, model acceptance, and the final six-product lifecycle matrix were not run. Keep the PR in Draft, preserve the legacy default, and leave `CORONA-IMPL` `in_progress` / **NOT READY**.
