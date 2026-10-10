# CI

[中文](ci.md) | English · [Documentation](../README.en.md)

`.github/workflows/ci.yml` defines these jobs:

| Job | Contents |
|---|---|
| `lint` | `ruff check .` (Python 3.11) |
| `security` | `pip-audit -r requirements.txt` (blocking) + `bandit` (non-blocking; report uploaded as an artifact) |
| `test` | 3.10 / 3.11 / 3.12 version matrix, `pytest tests/ --cov=. --cov-branch -n auto`, and coverage report uploaded as an artifact |
| `cli` | The Rust CLI (`cli/`): `cargo fmt --check` + `clippy -- -D warnings` + `cargo test`, plus a help-text smoke test over the subcommand list (doctor/init/start/stop/restart/status/logs/upgrade/migrate/plugin/capabilities/manifest/compose) so refactors cannot silently drop commands |
| `windows-native` | Runs `pytest tests/windows` on windows-latest — the native matrix for process trees, upgrades, and installation reliability (sentinels/PIDs/activation records depend on real Windows semantics) |
| `documentation` | Stdlib link/anchor, language-pair, redirect, state checks and six positive/negative contract tests |
| `flow-manifest` | Source anchor and generated message-flow drift gate |
| `flow-closure` | GitNexus index plus inventory/discovered-entry reconciliation |
| `notify` | PRs only: summarize status and comment (depends on test/lint/security/cli/flow-manifest/flow-closure/documentation) |

`test` depends on `lint` and `security` passing; `fail-fast: false` ensures the other versions continue when one fails. Older workflows on the same branch are cancelled automatically.

**Reproduce the CI environment locally**:

```bash
pip install -r requirements.txt -r requirements-dev.txt pytest pytest-cov pytest-xdist
ruff check .
pytest tests/ --cov=. --cov-branch -n auto --dist loadgroup
```

`pip-audit` is blocking, so CI goes red when an upstream dependency exposes a CVE. If you determine that an upstream issue cannot be fixed immediately, you may temporarily add `|| true` to that step, but record the reason.

**When only 3.10 is red and every test is a collect error, suspect a transitive dependency first.** The direct dependencies in `requirements.txt` are mostly lower bounds (`>=`) and transitive ones are not pinned at all, so any upstream release that supports 3.11+ only turns `test (3.10)` completely red while 3.11 / 3.12 and the dev machine stay green. The 2026-09-01 instance: `pygtrie` 2.6.0 used `typing.Self` (3.11+) at module top level, so `import nonebot` raised `AttributeError: module 'typing' has no attribute 'Self'` and all 622 tests errored. Triage by reading **only the first traceback in the `==== ERRORS ====` section** (the tens of thousands of log lines are all copies of the same one); the fix is to pin that transitive dependency explicitly in `requirements.txt` with the reason written down.

Dashboard tests/build are defined separately in `.github/workflows/dashboard_ci.yml`. Agent bootstrap modes and additional gates are in [verification](../agent/verification.md).
