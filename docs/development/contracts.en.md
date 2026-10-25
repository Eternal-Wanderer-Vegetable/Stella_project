# Current branch contracts and release boundaries

[中文](contracts.md) | English · [Documentation](../README.en.md)

<a id="source-contracts-and-release-gates-in-610"></a>

P04 advanced the memory source contract to schema 23/API 4 on 2026-10-25, adding append-only transport message event, part, and relation tables. The social side-table contract is schema 5, Scheduling SQL is schema 2, and Cometa Origin JSON is v3. Released assets retain their own build contracts; an older native wheel must not load a schema 23 database. Source constants are aligned, but a deployed wheel was not verified in this stage.

| Source | Current constant |
| --- | --- |
| [Python schema](../../memory/schema.py) | SCHEMA_VERSION = 23 |
| [Python/native contract](../../memory_rust/backend.py) | BACKEND_API_VERSION = 4; MEMORY_SCHEMA_VERSION = 23 |
| [Rust schema](../../memory_rust/native/src/schema.rs) | BACKEND_API_VERSION = 4; MEMORY_SCHEMA_VERSION = 23 |
| [Social schema](../../memory/social_schema.py) | SOCIAL_SCHEMA_VERSION = 5 |
| [Scheduling SQL schema](../../stella_project/plugins/bot_main/scheduling/migrations.py) | SCHEMA_VERSION = 2 |
| [Cometa Origin JSON](../../cometa/models.py) | schema_version = 3 |

The values describe source compatibility, not proof that a particular wheel was built, loaded, or accepted. Recheck constants when changing branches.

- Memory schema 23/API 4 must agree in `memory/schema.py`, `memory_rust/backend.py`, and `memory_rust/native/src/schema.rs`. Validate exported constants, not just the wheel package version. v23 appends transport event/parts/relations and retains the legacy integer `msg_id` for the explicit QQ compatibility path.
- Social schema 5 stores every opaque platform message ID returned for a physical delivery part in `social_deliveries.platform_message_ids_json`. The v4→v5 migration wraps the existing primary ID in a one-item list without reinterpreting it. WP06 retains the singular compatibility field while adding complete per-part receipts.
- Scheduling schema 2 stores verifiable DeliveryTarget, subject, and scope on tasks/runs/audit/quota. Legacy QQ tasks become sendable only when the Bot/group destination can be bound unambiguously; other rows stay unroutable, and old quota is preserved in an isolated legacy scope. Sending resolves the persisted BotRef exactly; unknown results are not retried automatically.
- Cometa Origin v3 stores BotRef and DeliveryTarget together and validates that they agree. v1/v2 compatibility is limited to known legacy OneBot QQ semantics; records whose target identity cannot be proven fail closed. The Cometa SQL table remains schema 1.
- `python scripts/generate_message_flow.py --check` validates source anchors, closure, and manifest. Regenerate archived topology after source changes; static reachability is not observed execution.
- Frontend checks: `pnpm --dir dashboard test` and `pnpm --dir dashboard build`. Synchronize the local bundle with `pnpm --dir dashboard sync:webui`.
- Isolated evaluation: `python scripts/run_flow_evaluation.py --mode isolated_pipeline --dataset <dataset_dir> --workdir <isolated_dir> --json`. Other modes are trace_playback, decision_recompute, and model_validation. Dataset/workdir are required; production is never a fallback database.
- `python scripts/evaluate_dialogue_attribution.py --help` describes frozen fixtures, protocol prompts, and `--guard`. Replay does not substitute for persisted identity checks or real QQ rollout.
- Synchronize the application version across `pyproject.toml`, `cli/Cargo.toml`, `desktop/src-tauri/Cargo.toml`, Tauri configuration, and corresponding locks. The native wheel, launcher, runtime-manager, and private Dashboard package retain independent component versions.
- Tag release builds the dashboard, candidate CPU backend, offline payload, wheel, CLI, and four installers. Each final EXE is validated on a Windows runner before publication. Manifests bind size/SHA-256 and published assets are read back for verification.
- The workflow defaults to `VERSIONED_LAYOUT=0`; launcher-based installer relocation is not enabled by default. Hosted Windows installation checks do not equal clean-VM/GUI-first-launch acceptance; see `release_assets/VM-MATRIX.md`.

Use the target commit's CI as current test evidence. Older counts are dated snapshots. See the [index](../README.en.md) for QQ rollout and Rust ranking boundaries.
