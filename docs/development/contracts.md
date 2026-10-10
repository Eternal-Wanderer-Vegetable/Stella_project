# 当前分支合同与发布边界

中文 | [English](contracts.en.md) · [文档总览](../README.md)

<a id="610-的源码合同与发布门禁"></a>

2026-10-10 按分支源码核对（基线 952007e）。应用版本仍为 6.1.0，但当前源码合同是 schema 19/API 3；已发布 6.1.0 与 P8 报告对应 schema 18/API 2。旧 native 资产不能混用到新分支。

| 来源 | 当前常量 |
| --- | --- |
| [Python schema](../../memory/schema.py) | SCHEMA_VERSION = 19 |
| [Python/native 合同](../../memory_rust/backend.py) | BACKEND_API_VERSION = 3; MEMORY_SCHEMA_VERSION = 19 |
| [Rust schema](../../memory_rust/native/src/schema.rs) | BACKEND_API_VERSION = 3; MEMORY_SCHEMA_VERSION = 19 |

这些常量只证明源码的兼容要求，不证明某份 wheel 已构建、加载或验收。切换分支时重新核对。

- 记忆 schema 19 / backend API 3：`memory/schema.py`、`memory_rust/backend.py` 与 `memory_rust/native/src/schema.rs` 必须一致。原生包版本不能替代导出常量校验。
- 消息流程：`python scripts/generate_message_flow.py --check` 检查源码锚点、闭包与 manifest；源码变化后按生成器更新归档，不能把静态可达性当作实际执行。
- 前端：`pnpm --dir dashboard test`、`pnpm --dir dashboard build`；本地随包快照用 `pnpm --dir dashboard sync:webui` 同步。
- 隔离评估：`python scripts/run_flow_evaluation.py --mode isolated_pipeline --dataset <dataset_dir> --workdir <isolated_dir> --json`；还有 trace_playback / decision_recompute / model_validation 模式。workdir 与 dataset 必填，不能默认回落生产库。
- 归属重放：`python scripts/evaluate_dialogue_attribution.py --help` 查看冻结夹具、协议 prompt 与 `--guard`；离线重放不替代身份登记落库和真实 QQ 灰度。
- 发布版本：`pyproject.toml`、`cli/Cargo.toml`、`desktop/src-tauri/Cargo.toml`、Tauri 配置与对应 lockfile 同步。原生 wheel、launcher、runtime-manager 与私有 Dashboard 包保留独立组件版本。
- tag 发布依次构建面板、CPU backend 候选通道、离线负载、wheel、CLI 与四个安装器；每个 EXE 在 Windows runner 上验收后才进入发布 job。发布清单绑定大小/SHA-256，发布后回读校验。
- `VERSIONED_LAYOUT=0` 是当前工作流默认值；版本化 launcher 搬移路径尚未默认开启。hosted Windows 安装检查不是干净 VM/GUI 首启验收；完整 VM 矩阵见 `release_assets/VM-MATRIX.md`。

测试现状以目标提交 CI 为准；旧文档中的测试数字是有日期的快照。归属灰度与 Rust 排序差异见 [文档索引](../README.md)。
