# Stella 6.1.0 Documentation

[中文](README.md) | English

Top-level documents are maintained usage and development guides. Synchronization
date: October 8, 2026. `pyproject.toml` defines the application version; the memory
contract is schema 18 / backend API 2.

| Guide | Scope |
| --- | --- |
| [Architecture](architecture.en.md) | Ingress, RuntimeFacade, modules, data boundaries |
| [Configuration](configuration.en.md) | Environment variables, endpoints/roles, optional defaults |
| [Memory](memory-system.en.md) | Capture, promotion, isolation, personal memory, attribution |
| [Rust memory backend](memory-rust-backend.en.md) | Modes, contracts, assets, ranking differences |
| [Capabilities](capability-system.en.md) | Router, Comes, providers, long-task delegation |
| [Cometa](cometa.en.md) | Agent installation, authentication, authorization, delivery |
| [Knowledge base](knowledge-base.en.md) | Imports, ACLs, retrieval, WebUI administration |
| [Scheduling](scheduling.en.md) | Group cron, permissions, bounded agents, delivery |
| [Skills](skills.en.md) | Progressive disclosure, sources, controlled sandboxes |
| [WebUI](webui.en.md) | Management pages, message flow, desktop shell |
| [Docker deployment](deployment-docker.en.md) | Configuration, persistence, upgrades, backups |
| [Development](development.en.md) | Tests, manifests, evaluations, release workflow |
| [Plugin specification](plugin-spec.en.md) | Integration, declarations, failure contracts |
| [Migration report template](migration-report-template.en.md) | Configuration and data import records |
| [Template plugin](examples/astrbot_plugin_stella_template/README.en.md) | Executable plugin example |

Each guide has a Chinese and English counterpart. `plans/`, `reports/`,
`migration/cortico/`, and `reports/evidence/` preserve dated planning, investigation,
and acceptance evidence. Their older versions, conclusions, and test counts describe
the recorded state and are not rewritten as current results. Consult later reports
for follow-up work; a plan is not evidence of a shipped feature. Earlier designs
also live in `design_docs/`.

Release boundaries: real QQ attribution rollout remains incomplete; three Rust
retrieval ranking benchmark differences remain open. Reply attribution guards,
proactive verification contracts, and personal-memory writing/sharing retain their
disabled defaults. See the dated [P8 report](reports/2026-10-05-dialogue-attribution-p8-acceptance.md)
and [QQ rollout checklist](reports/2026-10-05-qq-gray-rollout-checklist.md).
