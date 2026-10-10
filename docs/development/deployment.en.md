# Deployment Tools

[中文](deployment.md) | English · [Documentation](../README.en.md)

`deploy/` is a deployment tool whose "all checking logic is on the Python side, with the GUI as only a renderer": doctor outputs structured JSON, the desktop installer (Tauri) calls it and renders the result, and `stellacli` uses it as the local-mode domain backend. Changing GUI frameworks does not require rewriting the logic. The current subcommands are:

| Command | Purpose |
|---|---|
| `python -m deploy doctor [--json]` | Environment self-check; `--json` outputs structured results (`id/level/title/detail/fix_hint`) for the GUI to map to icons and localized strings |
| `python -m deploy init [--answers PATH] [--force] [--dry-run]` | Interactively generates `.env` (replacing lines one by one based on `.env.example`; fetches the model list from LM Studio and selects by number); `--answers` reuses the previous `deploy.answers.toml`, allowing the same answers to be reused for reinstalling on another machine / CI smoke tests / the GUI (`save_config`) |
| `python -m deploy start [--force] [--detach]` | Runs doctor first, then starts `bot.py` if there are no blocking issues (or with `--force`); `--detach` starts it in the background and writes its PID to `logs/stella.pid` (for the GUI) |
| `python -m deploy status [--json]` | Prefers the status endpoint to determine whether the process is alive, and aggregates link health, scheduler queues, today's usage, and the capability inventory; when the endpoint is unreachable it falls back to the PID file and reads the latest JSON log |
| `python -m deploy stop` | Gracefully stops the process: write the stop sentinel -> poll and wait -> fall back to a signal -> use a hard kill as the last resort (see below); the Tauri installer and `bot.py` are in the same release directory |
| `python -m deploy config-schema --json` | Outputs the configuration schema from `settings.py` (groups, defaults, comments), which the GUI uses to generate the "Advanced options" form |
| `python -m deploy migrate [--from OLD_DIR] [--dry-run] [--fresh-runtime]` | Imports user data from an old-version installation directory and upgrades the database; reads the old directory only, returns the Markdown report, and writes it to `STELLA_HOME/migration_report.md` |
| `python -m deploy space-merge --from a,b --to c [--dry-run]` | Merges shared spaces (memory + profiles + FTS + ledger), replacing the sequence of UPDATE statements users previously had to perform manually |
| `python -m deploy plugin-check <plugin dir> [--json]` | Validates a plugin directory against the [Plugin Specification](../reference/plugin-spec.en.md): 16 checks, and zero errors is the bar. **It imports and instantiates the plugin** (the same thing startup does), and the output says so explicitly |
| `python -m deploy plugin-scaffold <plugin dir> [--endpoint SLOT] [--force] [--dry-run] [--measure]` | Generates `capability.toml.draft` for a plugin (`reviewed = false`, `keywords` left empty with candidates only in comments) and immediately computes a quantified report with the **real embedding model** (same-domain prototype separation, each example's cosine against its own capability prototype, negative-sample margin). `--measure` only recomputes the report without calling the model, for use during review. The output is a draft: both the `.draft` suffix and `reviewed = false` gate it, and it reaches the Router only after a human renames the file and sets `true`. **It also imports and instantiates the plugin** |
| `python -m deploy capabilities [--json]` | Lists the capability inventory: which capabilities chat can trigger automatically, which cannot and why, which tier each came from, and which provider is backing off. The data comes from the status endpoint (the registry is a singleton inside the Bot process); when the Bot is not running it falls back to reading the three declaration tiers from disk, which cannot answer "is it routable" — the rendering says so |
| `python -m deploy paths [--env-file]` | Outputs resolved paths such as the program directory / user data directory; `--env-file` prints only the `STELLA_HOME/.env` path (used by `start.bat`) |
| `python -m deploy manifest [--write]` | Generates the release-package manifest `.stella-manifest.json` (used during upgrades to determine whether the user changed a bundled file); called by release CI |
| `python -m deploy upgrade <SOURCE_DIR> --version X.Y.Z [--rollback] [--checksum SHA]` | Versioned upgrade: verifies the upgrade source (optionally against a tree SHA-256) and then **atomically switches** the program version; `--rollback` flips the activation record back to the retained previous version tree (bidirectional, no source needed) |
| `python -m deploy bootstrap install --profile {...}` | Installs the components and default models declared by a profile (`oneclick-python` / `oneclick-rust` / `standalone-python` / `standalone-rust`); the installer bootstrap and manual repair share this entry point |
| `python -m deploy mcp list\|test` | Lists configured MCP servers / runs a connectivity smoke test against one server |
| `python -m deploy packages ...` | Component package catalog and operations: `catalog` / `verify` / `list` / `rollback` / `napcat-status` / `napcat-install` / `napcat-uninstall` / `import-model` |
| `python -m deploy runtime status` | Inspects / validates the Runtime Contract (component inventory, endpoints, schema version, diagnostic fields) |

Layers: `probe` collects data (with side effects) -> `checks` makes decisions (pure functions, the testing focus) -> `report` renders the result.
The criteria used by check functions stay consistent with the actual behavior of ai_gateway (for example, a missing persona file is only a warning in the code, so doctor also reports a warning), avoiding "it runs fine but reports an error" situations.

**Whenever you change `checks.py` or `report.py`, re-export the mock as well** (the frontend/installer uses the real structure for previews, preventing drift between the structure and the backend):

```bash
python -m deploy doctor --json > stella-installer/src/mock/doctor-clean.json
```

`doctor-mixed.json` (the scenario with items) must be constructed manually. Keep its field structure consistent with `doctor-clean.json`, and keep `summary.ok = total - error - warn` internally consistent.

### Stop Sequence (Sentinel First)

1. **The GUI and Bot do not share a console on Windows**: the installer starts the Bot with `CREATE_NO_WINDOW(0x08000000)`, so the child process has no console at all and the `CTRL_BREAK` sent by `GenerateConsoleCtrlEvent` never reaches it (verified in practice). Any stop plan that depends on console events necessarily fails in the GUI scenario; the only reliable entry point for the stop sequence is the file sentinel (`core/stop_signal.py`, default path `.stella-stop-request` at the project root).
2. **The sentinel file has a three-party contract**: deploy writes it (`stop()` in `deploy/process.py`) -> the Bot reads it and kills itself (`ai_gateway.watch_stop_request()` triggers a graceful uvicorn shutdown after observing it) -> the Bot clears leftovers at startup (the earliest action in `_start_stop_watcher`). If any one of the three is missing, the Bot either cannot be stopped or kills itself immediately on startup.
3. **Waiting on the deploy side = grace + buffer**: `_graceful_shutdown()` on the Bot side waits for at most `SHUTDOWN_GRACE_SECONDS(30)`. The deploy-side waiting window must be strictly longer (`STOP_WAIT_BUFFER_SECONDS`, proportional to grace); otherwise it will hard-kill the Bot just as it finishes shutting down, making the wait pointless.

Design trade-off: do not use `POST /shutdown` -- status_api is read-only, and adding a write endpoint would create an unauthenticated write interface. With `HOST=0.0.0.0`, that would become a remotely triggerable shutdown from the LAN; the sentinel is naturally limited to the local user by filesystem permissions.
The sentinel file is a runtime artifact and has been added to `.gitignore`, the exclusion list in `release.yml`, and the sensitive-file checks.

**Frontend contract**: `deploy doctor --json`, `deploy config-schema --json`, and `deploy paths` are the GUI data contracts. When changing their structures, bump the `version` field of the schema and update `stella-installer/src/mock/` at the same time.
`deploy migrate` returns the original Markdown report (the same content is also written to the current `STELLA_HOME/migration_report.md`; it is generated only once so the two copies cannot diverge), and the GUI renders it directly as monospaced text.

**The GUI must not determine the user data directory itself**: `python::data_root()` asks `deploy paths`. There is only one source of criteria, `config/home.py`; maintaining two implementations would result in "one side reads the old directory while the other writes to the new directory", with symptoms such as "save succeeded but had no effect".

**Two format conventions required by the GUI**:
- Files under `config/spaces/*.toml` written by the installer start with `# Managed by Stella installer`; changing that header or its format affects the GUI's determination of whether the file is "managed by the installer".
- Section comments in `config/settings.py` (`# ---------- TITLE ----------`) determine configuration groups. Keep this format when adding configuration items so the GUI can categorize them correctly (`deploy config-schema --json` is the single source of truth for the grouping result).
