# 验证门禁

[Agent 导航](README.md) · [开发导航](../development/README.md)

适用：开始任务时确认基线，结束时判断完成。来源为 CI、package manifests 和开发正文；工作流或命令变化时同步。

## Verification Commands

从项目根执行。`init.ps1` / `init.sh` 默认 `docs` 只验证文档与状态，不安装依赖、不启动 Bot、不修改生产数据。代码任务选择对应模式并追加专项检查。

```powershell
./init.ps1 docs
./init.ps1 python
./init.ps1 dashboard
```

Linux / Git Bash 用 `bash init.sh docs|python|dashboard`。安装依赖见 [环境](../development/environment.md)。

| 变化 | 必要检查 | 补充证据 |
| --- | --- | --- |
| 文档 / Agent 状态 | `python scripts/check_docs.py`、`git diff --check` | 中英文配对、旧锚点、历史哈希 |
| Python | `python -m pytest tests -q`、`ruff check .` | 模块回归；CI 3.10 / 3.11 / 3.12 矩阵 |
| Dashboard | `pnpm --dir dashboard test`、`pnpm --dir dashboard build` | UI 变化增加浏览器验收，随包副本另行同步 |
| 消息流程 / 埋点 | `python scripts/generate_message_flow.py --check` | inventory / discovered entries 与真实事件闭包；[CI](../development/ci.md) |
| 迁移 / native 合同 | 旧库回归、native cargo test、显式 native parity | 临时库 dry-run 和失败回滚；[数据库](../development/database.md)、[合同](../development/contracts.md) |
| Rust CLI | `cargo fmt --manifest-path cli/Cargo.toml --all --check`、`cargo clippy --manifest-path cli/Cargo.toml --all-targets -- -D warnings`、`cargo test --manifest-path cli/Cargo.toml` | 帮助清单冒烟；`.github/workflows/ci.yml` |
| prompt / 归属 / Router | 定向回归与正反例模型探针 / benchmark | 实际 prompt、原始输出、QQ 收发；[探针](../development/probes.md) |
| 部署 / EXE / 升级 | Windows native、包布局、manifest / SHA256、发布回读 | 干净 VM / GUI 首启；[发布](../development/release.md)、[VM 矩阵](../../release_assets/VM-MATRIX.md) |

## Evidence 与完成条件

记录目标分支/提交、command and output 摘要、退出码、夹具/后端、跳过项和证据位置。通过只能支持检查覆盖范围；模型、QQ、浏览器和干净 VM 缺口分别列出。

文档任务不需整套业务测试；新增校验器验证成功与失败路径。提交前仍需 [图变更检查](gitnexus.md)。
