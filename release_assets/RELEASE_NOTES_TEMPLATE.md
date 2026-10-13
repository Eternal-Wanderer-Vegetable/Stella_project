# Stella v6.2.0

Stella 6.2.0 strengthens memory provenance, dialogue attribution, and context compaction. It is based on the published [v6.1.0](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/releases/tag/v6.1.0) release.

## What's Changed

### Features

- Memory evidence now carries auditable source and claim-lineage contracts. Existing evidence is explicitly migrated as `legacy_unverified`; migration does not silently promote it to accepted evidence.
- Dialogue replies use typed reply envelopes and source-evidence checks to make attribution and final-delivery decisions verifiable.
- Context compaction uses bounded batches and retains verifiable source packets under a unified reply protocol.

### Bug Fixes and Reliability

- Restored dialogue-attribution and delivery regression coverage, including untyped legacy replies and source-backed final delivery.
- Expanded message-flow source closure to cover ingress helpers beyond the previous traversal cap, refreshed the generated flow manifest, and isolated Python 3.10 flow tests.
- Increased the timeout only for the Dashboard's 100,000-event functional probe; its assertions and dedicated performance budget remain unchanged.

### Documentation

- Reorganized bilingual architecture, development, deployment, and agent documentation, and added explicit verification and release gates.

### Breaking Changes

- The memory database advances from schema 18 to 19, and the Rust backend contract advances from API 2 to API 3. Use the native wheel built for this release; the v6.1.0 wheel is incompatible and must not be reused.
- Schema 19 adds provenance fields and claim-lineage storage. Older evidence is labeled `legacy_unverified`; it is not automatically considered accepted. Back up the complete data root before upgrading and rehearse with a copy.

## Upgrade and Compatibility

1. Stop Stella and back up the complete `STELLA_HOME`. For a live SQLite database, use the SQLite backup API or copy it only after stopping the application; do not copy only the main `.db` file while WAL is active.
2. Install the OneClick release or extract Standalone to a new directory. Keep the existing data root.
3. Before the first production start, rehearse migration on a copy:

   ```bash
   python -m deploy paths
   python -m deploy migrate --dry-run
   python -m deploy migrate
   ```

4. Rust deployments must use this release's native wheel and validate API 3 / schema 19. The wheel's independent package version remains `0.1.0`; that package version alone does not establish compatibility.
5. Existing evidence with no accepted provenance remains `legacy_unverified`. Review and verify it through the normal evidence workflow before relying on it for attribution or memory repair.

The application version is 6.2.0. The launcher, runtime-manager, native wheel, and private Dashboard keep independent component versions. The frozen v1 GUI is not part of this release.

## Downloads

| Product | Asset |
| --- | --- |
| Online installer / Python | `Stella-OneClick-Python-v6.2.0-windows-amd64.exe` |
| Online installer / Rust | `Stella-OneClick-Rust-v6.2.0-windows-amd64.exe` |
| Offline installer / Python | `Stella-OneClick-Python-Offline-v6.2.0-windows-amd64.exe` |
| Offline installer / Rust | `Stella-OneClick-Rust-Offline-v6.2.0-windows-amd64.exe` |
| Standalone / Python | `Stella-Standalone-Python-v6.2.0-windows-amd64.zip` |
| Standalone / Rust | `Stella-Standalone-Rust-v6.2.0-windows-amd64.zip` |

Additional assets include Windows/Linux CLI packages, the CPU backend, native wheel, package catalog, release manifest, and `SHA256SUMS.txt`. OneClick includes the offline WebView2 runtime; Offline also bundles Python, dependencies, components, the default embedding model, and the rendering kernel. A chat model must still be configured, and QQ still requires account login.

## Known Boundaries

- Real QQ rollout and production behavior are not established by offline tests; complete the separate rollout checklist before enabling guarded memory writes or sharing in production.
- The latest recorded Rust retrieval benchmark reported 21/24 exact matches, with three conversation-order differences. Use Python when exact ordering is required until a newer parity report closes this gap.
- `delivery_unknown` means delivery may already have occurred; it is not proof of success and must not trigger a blind resend.
- Hosted Windows installer checks and post-publication hash verification do not replace the clean-VM matrix or GUI first-launch acceptance. `VERSIONED_LAYOUT=0` remains the workflow default.

## 中文摘要

Stella 6.2.0 加强记忆来源证据、对话归属与上下文压缩。记忆 schema 升至 19，Rust backend API 升至 3。旧 evidence 会自动迁移为 `legacy_unverified`，不会被静默提升为已接受证据；Rust 用户必须使用本版本构建的 native wheel。升级前备份完整 `STELLA_HOME`，并先在副本上演练迁移。

本版本还增加 typed reply envelope 与来源证据校验、有界压缩批次和可验证来源包，修复消息流程闭包覆盖与 Python 3.10 隔离测试，并重整双语开发与验收文档。真实 QQ 灰度、Rust 检索顺序一致性、干净 VM 和 GUI 首启仍按各自流程单独验收。

**Full Changelog**: https://github.com/Eternal-Wanderer-Vegetable/Stella_project/compare/v6.1.0...v6.2.0
