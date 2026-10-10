# Current branch contracts and release boundaries

[中文](contracts.md) | English · [Documentation](../README.en.md)

<a id="source-contracts-and-release-gates-in-610"></a>

Verified against branch source on 2026-10-10 (baseline 952007e). Application version remains 6.1.0, while current source compatibility is schema 19/API 3. The published 6.1.0/P8 snapshot used schema 18/API 2; do not mix old native assets with the newer branch.

| Source | Current constant |
| --- | --- |
| [Python schema](../../memory/schema.py) | SCHEMA_VERSION = 19 |
| [Python/native contract](../../memory_rust/backend.py) | BACKEND_API_VERSION = 3; MEMORY_SCHEMA_VERSION = 19 |
| [Rust schema](../../memory_rust/native/src/schema.rs) | BACKEND_API_VERSION = 3; MEMORY_SCHEMA_VERSION = 19 |

The values describe source compatibility, not proof that a particular wheel was built, loaded, or accepted. Recheck constants when changing branches.

- Memory schema 19/API 3 must agree in `memory/schema.py`, `memory_rust/backend.py`, and `memory_rust/native/src/schema.rs`. Validate exported constants, not just the wheel package version.
- `python scripts/generate_message_flow.py --check` validates source anchors, closure, and manifest. Regenerate archived topology after source changes; static reachability is not observed execution.
- Frontend checks: `pnpm --dir dashboard test` and `pnpm --dir dashboard build`. Synchronize the local bundle with `pnpm --dir dashboard sync:webui`.
- Isolated evaluation: `python scripts/run_flow_evaluation.py --mode isolated_pipeline --dataset <dataset_dir> --workdir <isolated_dir> --json`. Other modes are trace_playback, decision_recompute, and model_validation. Dataset/workdir are required; production is never a fallback database.
- `python scripts/evaluate_dialogue_attribution.py --help` describes frozen fixtures, protocol prompts, and `--guard`. Replay does not substitute for persisted identity checks or real QQ rollout.
- Synchronize the application version across `pyproject.toml`, `cli/Cargo.toml`, `desktop/src-tauri/Cargo.toml`, Tauri configuration, and corresponding locks. The native wheel, launcher, runtime-manager, and private Dashboard package retain independent component versions.
- Tag release builds the dashboard, candidate CPU backend, offline payload, wheel, CLI, and four installers. Each final EXE is validated on a Windows runner before publication. Manifests bind size/SHA-256 and published assets are read back for verification.
- The workflow defaults to `VERSIONED_LAYOUT=0`; launcher-based installer relocation is not enabled by default. Hosted Windows installation checks do not equal clean-VM/GUI-first-launch acceptance; see `release_assets/VM-MATRIX.md`.

Use the target commit's CI as current test evidence. Older counts are dated snapshots. See the [index](../README.en.md) for QQ rollout and Rust ranking boundaries.
