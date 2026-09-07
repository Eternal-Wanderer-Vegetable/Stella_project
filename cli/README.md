# stellacli

Stella 跨平台命令行控制台（Windows / Linux 统一入口）。方案与设计决策见
[`design_docs/跨平台 CLI 控制台方案 v1.0.md`](../design_docs/跨平台%20CLI%20控制台方案%20v1.0.md)。

**定位**：面向没有 WebView 的设备的备选入口，独立于 Windows GUI 主包分发。
**架构铁律**：本工具只是编排层与渲染层——领域逻辑（doctor 探测、配置向导、
优雅停机的哨兵协议、数据迁移）一律透传 Python `deploy` 模块（GUI 与 CLI
共用同一套 `--json` 契约），绝不双实现。

## 命令一览

```
stellacli doctor    [--json]   环境自检（彩色渲染 / 原始 JSON）
stellacli init      [--answers PATH] [--force] [--dry-run]
                                配置向导（交互式）
stellacli start / stop / restart
                                生命周期（本地=deploy start/stop；docker=compose）
stellacli status    [--json]   运行状态面板（docker 形态聚合容器健康+容器内接口）
stellacli logs      [-f] [--boot|--thought] [--file PATH] [--compose]
                                日志（默认结构化 stella.jsonl，级别着色）
stellacli upgrade              升级（docker=拉取/构建+重建；本地=发布包指引）
stellacli migrate [...]        数据迁移（参数透传 deploy）
stellacli plugin check <目录> [--json] / plugin scaffold [...]
stellacli capabilities [--json]
stellacli manifest  [--write]
stellacli compose   <任意参数> docker 形态逃生舱（透传 docker compose）
```

形态自动检测（`--mode local|docker` 或环境变量 `STELLA_MODE` 可显式指定）：
带 `runtime/python.exe` 的发布目录 → 本地；有 `docker-compose.yml` 且 docker
可用 → docker。退出码：领域命令透传 deploy 的退出码（doctor 有阻塞=1），
stellacli 自身编排错误 = 2。

## 本地构建与测试

```bash
cd cli
cargo fmt --all --check
cargo clippy --all-targets -- -D warnings
cargo test
cargo build --release     # 产物 target/release/stellacli[.exe]，约 1MB
```

CI：`.github/workflows/ci.yml` 的 `cli` job 跑同一套门禁；
发布：`.github/workflows/release.yml` 在打 `v*` tag 时产出
`Stella-CLI-version-v{ver}-linux-amd64.tar.gz`（musl 静态）与
`Stella-CLI-version-v{ver}-windows-amd64.zip`，挂到 Release 的独立 assets。

版本号（Cargo.toml）必须与 pyproject.toml 一致，release CI 有校验。
