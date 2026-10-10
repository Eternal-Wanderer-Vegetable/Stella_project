# Documentation

[中文](README.md) | English

This index routes by task. Read one entry, then follow the relevant topic. Current branch facts come from source and CI; release notes and acceptance remain dated evidence.

| Task | Start here |
| --- | --- |
| Install, deploy, operate WebUI or optional features | [Usage guides](guides/README.en.md) |
| Understand modules, message flow, memory and identity | [Architecture](architecture/README.en.md) |
| Look up settings, plugin contracts or migration template | [Reference](reference/README.en.md) |
| Develop, test, migrate data, troubleshoot or release | [Development](development/README.en.md) |
| Work as a coding agent, choose gates or resume a session | [Agent workflow](agent/README.md) |
| Find plans, incident investigations or acceptance evidence | [Archives](history/README.en.md) |
| Write an AstrBot-compatible plugin | [Example plugin](examples/astrbot_plugin_stella_template/README.en.md) |

## Document layout

`guides/`, `architecture/`, `reference/`, and `development/` contain paired Chinese/English maintained pages. `agent/` contains concise project workflow rules. Old top-level paths remain section navigation only; new links go directly to the maintained text. [The map](documentation-map.json) records redirects and old section anchors.

`plans/`, `reports/`, `reports/evidence/`, `migration/cortico/` and the root `design_docs/` preserve their original dated conclusions. Consult [archive navigation](history/README.en.md) and follow later evidence; a plan is not proof of delivery.

## Current source and acceptance boundaries

The application version comes from `pyproject.toml`; current branch memory/native compatibility is documented in [Source contracts](development/contracts.en.md). The published 6.1.0 snapshot and subsequent branch work must be distinguished. Older schema/API values in reports describe the tested snapshot.

Real QQ attribution rollout, Rust ordering parity, and clean-VM/GUI-first-launch acceptance require their own evidence. Reorganizing documentation does not close those gaps. The dated [P8 report](reports/2026-10-05-dialogue-attribution-p8-acceptance.md) and [QQ checklist](reports/2026-10-05-qq-gray-rollout-checklist.md) retain their conclusions.

Maintenance rules: [Document ownership and link checks](agent/documentation.md).
