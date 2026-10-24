# Stella v6.3.0

> Unreleased draft for PR #120. Do not publish until the remaining product acceptance gates are complete. This version builds on the published [v6.2.0](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/releases/tag/v6.2.0) release.

Stella 6.3.0 prepares the Corona / Nucleus dual-process runtime and strengthens Windows supervision, packaging, and container health checks. The legacy entrypoint remains the default in this branch.

## What's Changed

### Features

- Added the Corona control plane and supervised Nucleus core, with revisioned configuration, bounded readiness/restart handling, and explicit liveness versus business-readiness states.
- Added a route-catalogued HTTP/WebSocket proxy for managed platform traffic while retaining the legacy entrypoint as the default.
- Added Corona, Nucleus, bootstrap, and immutable contract packages to Standalone and OneClick release payloads; strengthened filters for secrets and runtime user data in release and Docker contexts.
- Updated the Docker health check to probe Corona liveness first and retain a legacy status fallback. Container health does not imply that a platform or model is ready.

### Bug Fixes and Reliability

- Windows managed processes now use Job Objects for process-tree ownership and validate readiness against the active job.
- Windows private data paths receive a user-only ACL, and ACL verification uses the actual SID and ACE types.
- Fixed proxy handling for encoded query bytes and a short-deadline shutdown-hook edge case.
- Increased the container stop grace period to cover the managed shutdown budget.

### Breaking Changes

- This branch adds no business-database schema migration. Memory remains schema 19 and the Rust memory contract remains API 3 / schema 19.
- The default runtime has not switched from legacy. Do not enable a managed-runtime default until its separate VM, container, platform, model, upgrade, and rollback gates pass.

## Upgrade and Compatibility

1. Back up the complete `STELLA_HOME` before upgrading. For a live SQLite database, use the SQLite backup API or copy it only after stopping the application; do not copy only the main `.db` file while WAL is active.
2. Install to a new program directory or use the OneClick installer. Preserve the existing data root.
3. Rehearse the current migration path against a copy before a production start:

   ```bash
   python -m deploy paths
   python -m deploy migrate --dry-run
   ```

4. Rust deployments must continue to use a native wheel built for API 3 / schema 19. The wheel has its own package version and is not versioned with the desktop application.

The application version is 6.3.0 on this development branch; it has not been published. The launcher, runtime-manager, native wheel, and private Dashboard keep independent component versions. The frozen v1 GUI is not part of this release.

## Downloads

| Product | Asset |
| --- | --- |
| Online installer / Python | `Stella-OneClick-Python-v6.3.0-windows-amd64.exe` |
| Online installer / Rust | `Stella-OneClick-Rust-v6.3.0-windows-amd64.exe` |
| Offline installer / Python | `Stella-OneClick-Python-Offline-v6.3.0-windows-amd64.exe` |
| Offline installer / Rust | `Stella-OneClick-Rust-Offline-v6.3.0-windows-amd64.exe` |
| Standalone / Python | `Stella-Standalone-Python-v6.3.0-windows-amd64.zip` |
| Standalone / Rust | `Stella-Standalone-Rust-v6.3.0-windows-amd64.zip` |

Additional assets include Windows/Linux CLI packages, the CPU backend, native wheel, package catalog, release manifest, and `SHA256SUMS.txt`. OneClick includes the offline WebView2 runtime; Offline also bundles Python, dependencies, components, the default embedding model, and the rendering kernel. A chat model must still be configured, and QQ still requires account login.

## Known Boundaries

- The release remains NOT READY until the Windows installer, Docker runtime, clean-VM, full product lifecycle, platform, model, upgrade, and rollback gates are recorded.
- Real QQ/OneBot acceptance is intentionally deferred until PR #120 is merged to `main`.
- Container health proves liveness only; it does not establish successful QQ delivery or model readiness.
- `VERSIONED_LAYOUT=0` remains the workflow default.

## 中文摘要

Stella 6.3.0 开发分支准备 Corona / Nucleus 双进程运行架构，并加强 Windows 监管、安装包和容器健康检查；本分支仍以 legacy 为默认入口，版本尚未发布。

- 新增 Corona 控制面与受监管的 Nucleus 核心，包括版本化配置、就绪/重启预算，以及进程存活与业务就绪状态区分。
- 新增按路由目录转发 HTTP/WebSocket 平台流量的代理；Standalone / OneClick 纳入 Corona、Nucleus、bootstrap 和合同包，并加强发布包与 Docker 上下文中的敏感数据过滤。
- Windows 托管进程使用 Job Object 管理进程树；私有目录通过用户 SID 和 ACE 类型设置、验证 ACL。修复代理编码 query 与短关闭期限边界。
- Docker 健康检查优先探测 Corona 存活端点，并兼容 legacy 状态接口；容器 healthy 不代表 QQ 或模型已就绪。
- 本分支没有业务数据库 schema 迁移，记忆库保持 schema 19，Rust memory contract 保持 API 3 / schema 19。默认入口尚未切换。

在剩余产品验收完成之前，本草案不可发布。Windows 安装器、Docker 运行、干净 VM、六类产品生命周期、模型与平台验收仍按独立门禁记录；真实 QQ/OneBot 接入留待 PR 合并至 `main` 后实测。

**Full Changelog**: https://github.com/Eternal-Wanderer-Vegetable/Stella_project/compare/v6.2.0...v6.3.0
