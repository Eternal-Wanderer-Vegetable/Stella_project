# GitNexus Engineering Plan

> Task: 为 Rust 记忆检索引擎建立与现有 Python memory benchmark 对齐的正确性、parity 与性能 benchmark。
> Evidence verified at commit `88b55399f6cf2ec9858ca32b83c2ac5c6edbe673`; GitNexus index content points to the same commit, but Docker GitNexus 1.6.11 reports `runnerIdentityStatus: stale-or-unknown`, and the MCP service reports an older index. Graph/PDG claims are auxiliary; current source and tests are authoritative.
> Evidence provenance schema 2; global dirty digest and cited-path manifest are embedded in §11; exact generated plan path excluded.

## 1. Objective

[verified] 新增独立的 Rust benchmark 入口，复用 `memory/benchmark/` 的 JSON 用例和 embedding fixture，对 Rust retrieval 做三类可审计验证：与 Python 相同的 correctness 指标、逐用例 parity 诊断、可重复的 warmup/iteration 延迟统计。现有 `python -m memory.benchmark` 默认行为保持不变。

[inferred] 首版只覆盖 retrieval，因为现有参照 benchmark 的入口和指标都围绕 retrieval；promotion 是写事务，若混入会改变数据库状态并污染 retrieval 对比，列为后续独立 benchmark。

## 2. Current Behaviour

[verified] `memory.benchmark.load_cases` 递归读取 `memory/benchmark/**/*.json`，跳过 `_fixtures`，并拒绝缺失或重复 id（`memory/benchmark.py:51-77`）。

[verified] Python runner 为每个 case 建立临时 schema 记忆表，关闭 RAG/FTS 以保证可复现，清理 retrieval cache，调用生产 Python v2 入口，再计算 expected/behavior/forbidden/over-recall 和 ranked diagnostics（`memory/benchmark.py:94-148`, `151-289`）。

[verified] 聚合指标包括 cases ok rate、precision、recall、pollution、mode accuracy、behavior guard、forbidden activation 和 separation margin；CLI 当前支持 rule-only、embedding fixture、compare、verbose（`memory/benchmark.py:292-360`, `470-519`）。

[verified] Rust 适配器通过 `RetrievalRequest` 调用 PyO3 native contract；native retrieval 读取 schema 14 数据库，做 scope/visibility 候选过滤、ranking、merge、behavior split、conversation limit，并返回 trace（`memory_rust/backend.py:31-42`, `89-116`; `memory_rust/native/src/retrieval.rs:191-227`）。Rust native 会要求 `schema_meta.version == 14`，而当前 Python benchmark 临时库只保证 `memories` DDL，因此 Rust runner 必须显式初始化 schema metadata（`memory_rust/native/src/schema.rs:6-35`; `memory/schema.py:270-304`）。

## 3. Relevant Architecture

[verified] backend-neutral contract 的 API version 为 1、memory schema 为 14；Python backend 通过 `_bypass_backend=True` 复用现有 Python retrieval，Rust backend 由 selector 延迟加载并校验 contract（`memory_rust/backend.py:12-28`, `63-74`; `memory_rust/python_backend.py:18-49`; `memory_rust/selector.py:65-116`）。

[verified] 生产 Rust 路径先在 Python 侧解析 mode 并计算 `pool_limit`，再把已解析 request 交给 native；`auto/shadow` 会 fallback，`rust/strict` 会暴露 native 错误（`memory/retrieval_v2.py:390-464`）。Benchmark 必须直接使用 `strict`，避免 native 缺失、schema mismatch 或 runtime error 被静默当成通过。

[verified] Rust distribution 独立为 `stella-memory-rust`，安装到 `memory_rust` namespace；当前 release workflow 已把 Rust asset 与主 Release 分开上传，且不改变主 Python asset 命名（`memory_rust/native/pyproject.toml:5-18`; `docs/memory-rust-backend.md:46-62`; `.github/workflows/release-memory-rust.yml:27-40`, `64-118`）。本计划不修改 release 命名或发布流程。

## 4. GitNexus Findings

[graph] Docker GitNexus `impact(target="run_benchmark", direction="upstream")` 报 `MEDIUM`，覆盖 14 个 symbols、9 个 direct callers，主要是 `memory/benchmark.py:main` 与现有 benchmark tests；`evaluate_case` upstream 也为 `MEDIUM`，覆盖 15 个 symbols、5 个 direct callers。结论：不要改变现有 runner 的默认 contract；新增入口更适合隔离 blast radius。

[graph] Docker GitNexus `impact(target="memory_rust/native/src/retrieval.rs:retrieve", direction="upstream")` 报 `LOW`，直接关系主要是 PyO3 wrapper 和 Rust test；结果标记为 lower-bound，存在 receiver typing 缺口，不能把空 caller 集合当作完整证明。

[graph] Docker GitNexus `impact(target="memory_rust/native/src/promotion.rs:promote", direction="upstream")` 报 `CRITICAL`，直接关系包含 promotion tests 和 PyO3 wrapper。该高风险写路径不进入首版 retrieval benchmark；后续若纳入，必须单独隔离数据库并做事务回滚/状态重置。

[graph] `pdg_query` 对 Python benchmark 的辅助结果显示 `load_cases -> results -> aggregate` 数据流，以及 `evaluate_case` 对全局 DB_PATH、feature flags、cache 的临时切换与 finally 恢复；由于 MCP 索引陈旧，这些只用于导航，行为以 `memory/benchmark.py:166-205`, `287-289` 当前源码复核。

[verified] 已定位的回归测试是 `tests/test_benchmark.py:43-107`、`tests/test_benchmark_and_log.py:12-127`、`tests/test_memory_rust_selector.py:34-195` 和 `tests/test_memory_rust_promotion.py`；当前没有专门的 Rust retrieval benchmark test 文件。

## 5. Statement-Level PDG Findings

[graph] MCP PDG 层可查询，但索引 provenance 不满足 strict freshness；本计划不把 stale PDG 边作为实现前提，也不声称已获得当前提交的完整 statement slice。

[verified] Python evaluation 的关键顺序是：写临时 DB -> 保存并覆盖 retrieval 全局状态 -> 清 cache -> 调 retrieval -> finally 恢复状态 -> 计算 case 结果；Rust runner 必须保持“fixture 建库、backend 调用、结果归一化、评分”顺序，并为 Python/Rust parity 使用两份同内容临时 DB，避免 Python `_touch_accessed` 改变 Rust 的候选排序（`memory/benchmark.py:166-205`, `207-285`; `memory/retrieval_v2.py:527-536`, `603-610`）。

[verified] 性能路径包含临时 SQLite 读、候选查询、ranking、merge、behavior split 和 limit；Rust retrieval 是只读连接，Python retrieval 可能写访问时间。性能计时只覆盖 backend call，不覆盖 case JSON 解析和临时数据库建库，并在每个 backend/case 前恢复同一 fixture 状态。

[inferred] Rust trace 的 `ranked_all` 目前提供 id/score/parts，而 Python trace 还带 `cut` 原因（`memory/retrieval_v2.py:583-601`; `memory_rust/native/src/retrieval.rs:205-220`）。adapter 应把两者归一为共同诊断格式；缺失的 Rust cut 标记不能被误报为 parity failure。

## 6. Proposed Changes

[verified] `memory/benchmark.py`：在不改变 `run_benchmark` 默认结果的前提下，抽出可供两种 backend 共用的 case-result 评分/归一化边界；保留现有 Python 入口和 rule-only/embedding 行为。共享 DB fixture helper 只负责复用 schema 14 DDL，并允许 Rust case DB 写入 `schema_meta` 版本行。

[verified] `memory_rust/backend.py`、`memory_rust/python_backend.py`、`memory_rust/selector.py`：复用已有 `RetrievalRequest`、Python backend 与 `strict` selection，不新增 fallback 语义；必要时只补充 benchmark 所需的明确错误/结果适配接口。

[assumed] `memory_rust/benchmark.py`：新增独立 CLI。默认运行 Rust correctness；`--compare` 对同一 case 分别运行 Python 与 Rust；`--performance` 加 warmup/iterations；`--embedding-fixture`、`--dir`、`--verbose` 与现有 benchmark 语义对齐；`--json` 输出机器可读报告。请求 mode 和 pool limit 按生产 adapter 规则预解析，native backend 使用 `strict`。

[assumed] `memory_rust/benchmark.py`：每个 case 为 Python/Rust 各建立一份 schema 14 临时 DB，写入 `schema_meta` version 14 和规范 `memories` DDL；默认关闭 RAG/FTS，语义分直接复用现有 fixture 计算结果。所有 native unavailable、contract mismatch、schema mismatch、SQLite/runtime exception 都进入 errors 并使命令以非零状态结束。

[assumed] `memory_rust/benchmark.py`：报告包含 dataset/case 数、与 Python benchmark 相同的 correctness metrics、逐 case final/behavior/order/score delta、mismatch reasons，以及每 backend 的 warmup、iterations、min/mean/p50/p95/max、吞吐和错误计数。性能数值只作报告，不写入 correctness gate。

[assumed] `tests/test_memory_rust_benchmark.py`：覆盖 fixture schema 初始化、strict native failure、contract/schema mismatch、runtime error 显式失败、Rust/Python parity mismatch diagnostics、重复运行确定性、百分位统计和 JSON schema。真实 native 集成测试在未安装 wheel 时明确 skip，不得 fallback 成通过。

[assumed] 不修改 `.github/workflows/ci.yml`、`.github/workflows/release-memory-rust.yml`、Rust retrieval/promotion 算法或发布资产命名；首版 benchmark 作为可手动运行的工程工具，后续再决定是否加入独立 CI 性能 job。

## 7. Implementation Sequence

1. 先对 `memory/benchmark.py` 的共享评分/fixture 边界做最小重构，运行现有 benchmark tests，确认 Python 指标和默认 CLI 无变化。
2. 实现 `memory_rust/benchmark.py` 的 case DB 初始化和 strict Rust retrieval adapter；先支持 rule-only correctness，失败不得 fallback。
3. 加入 embedding fixture、共同结果归一化和 `--compare` parity 报告；固定 mode/pool_limit、排序比较和浮点 score tolerance，并输出 mismatch case/id。
4. 加入 `--performance` 的 warmup/iteration 计时和 JSON 报告；每个 backend 使用独立同内容 DB，计时区间不含建库/加载 fixture。
5. 添加 benchmark tests，先运行单测与 native package tests，再运行真实 Rust benchmark；只在最终阶段生成一次示例/基线报告（若需要），不把机器相关延迟硬编码进 correctness 测试。

## 8. Test Strategy

[verified] 保持现有回归：`python -m pytest tests/test_benchmark.py tests/test_benchmark_and_log.py tests/test_memory_rust_selector.py -q`、`python -m memory.benchmark --compare`、`cargo test --manifest-path memory_rust/native/Cargo.toml`。

[assumed] 新测试场景：同一 case 的 Python/Rust 结果使用相同 final ids、behavior ids 和 mode；Rust trace 缺 cut 时不误报；分数按明确 tolerance 比较并报告最大 delta；case 顺序和重复运行的 correctness JSON 稳定；p50/p95 对固定样本正确；空目录、缺失 fixture、坏 JSON、重复 id、缺少 schema_meta、schema 13、native 缺失和 runtime error 都得到明确结果。

[assumed] 真实集成验收命令：`python -m memory_rust.benchmark --compare --performance --json <report.json>`，以及 `python -m memory_rust.benchmark --embedding-fixture <fixture.json> --performance`。这些命令在实现后验证；当前入口尚不存在，不能把它们伪装成当前已验证命令。

## 9. Risk and Impact Analysis

[graph] `run_benchmark`/`evaluate_case` 的 direct callers 必须保持兼容；这也是选择独立 runner、共享后处理而不重写现有 CLI 的原因。

[verified] Rust native contract 只接受 schema 14，临时库漏写 `schema_meta` 会全部失败；这是首个必须在测试中锁住的 integration risk。

[inferred] Python global DB_PATH、RAG_ENABLED、MEMORY_V2_ENABLED 和 cache 使并行 benchmark 有串库/串结果风险；实现应串行执行或为每次调用隔离状态，不使用 pytest xdist 直接并行同一 process 内的 backend call。

[inferred] score/order parity 可能因 Rust/Python 浮点、时间戳解析、merge 和 trace 字段差异而出现非语义差异；报告应区分 hard mismatch（final/behavior/mode）与 diagnostic mismatch（score delta/trace shape）。

[verified] `promotion.rs:promote` 为 CRITICAL graph risk，且是写事务；首版不调用它，避免 benchmark 改变 fixture 状态。promotion benchmark 后续需要单独临时 DB、事务失败路径和 FTS 状态校验。

[verified] 工作区已有未提交修改 `cli/Cargo.toml`、`cli/Cargo.lock`、`pyproject.toml`，内容是版本号从 3.9.0 到 3.10.0 的用户变更；执行时不得修改、暂存、提交或回滚它们。

## 10. Files Expected to Change

| File | Symbols | Reason |
| ---- | ------- | ------ |
| `memory/benchmark.py` | `evaluate_case`, `run_benchmark` | 最小抽取共享评分/fixture 边界，保持 Python 默认兼容 |
| `memory_rust/benchmark.py` | new benchmark entrypoint | Rust correctness、parity、performance runner 与 CLI |
| `tests/test_memory_rust_benchmark.py` | new tests | runner contract、failure、parity、determinism、percentiles |
| `tests/test_benchmark.py` | existing benchmark tests | 锁定 Python 默认行为未回归 |
| `tests/test_benchmark_and_log.py` | existing helper tests | 锁定共享评分/fixture 边界的空目录和坏输入行为 |

## 11. Reusable Implementation Context

```yaml
implementation_context:
  task_summary: "建立与 Python memory.benchmark 对齐的 Rust retrieval benchmark，提供 correctness、Python/Rust parity、性能统计和显式 native failure；保持 Python runner 默认行为不变。"
  acceptance_criteria:
    - "现有 python -m memory.benchmark 及其测试行为不变。"
    - "Rust benchmark 使用同一 memory/benchmark JSON 用例和 embedding fixture。"
    - "Rust benchmark 使用 strict contract，native 缺失/不兼容/运行错误不得静默 fallback。"
    - "报告同时包含 correctness、逐 case parity 和 warmup/iteration latency percentile。"
    - "首版不纳入 promotion，不修改 release asset 命名或用户已有 dirty files。"
  evidence_provenance:
{
  "schema_version": 2,
  "head_commit": "88b55399f6cf2ec9858ca32b83c2ac5c6edbe673",
  "generated_plan_path": "docs/plans/2026-09-11-gitnexus-plan-rust-memory-benchmark.md",
  "global_dirty_digest": {
    "algorithm": "sha256",
    "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
    "value": "b4f0e66fc6f7edfff0a717059a9399bf5e7f96990c393b1a97ef75cffaf25f95"
  },
  "cited_path_manifest": [
    {
      "path": ".github/workflows/ci.yml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:72ffa0a55d11fd17d17ca884615f5ae7976f2f0487d793f90720e61f5296fa5f",
      "index_digest": "sha256:72ffa0a55d11fd17d17ca884615f5ae7976f2f0487d793f90720e61f5296fa5f",
      "worktree_digest": "sha256:23cf14adfcf4c2ae1baeb9d4cb7ed173ac12c985f0bf5ddb217a02576039fb0f",
      "untracked_digest": "absent"
    },
    {
      "path": ".github/workflows/release-memory-rust.yml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:ae21eff2412813f4260db82f29117b79c1c5f847dab809234fa7cfaf3bdefe58",
      "index_digest": "sha256:ae21eff2412813f4260db82f29117b79c1c5f847dab809234fa7cfaf3bdefe58",
      "worktree_digest": "sha256:ae21eff2412813f4260db82f29117b79c1c5f847dab809234fa7cfaf3bdefe58",
      "untracked_digest": "absent"
    },
    {
      "path": "cli/Cargo.lock",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:5bbabac510e55c5e1bf1557a5ded28cce75c6d2d5a0c2b7ac5acbad478404585",
      "index_digest": "sha256:5bbabac510e55c5e1bf1557a5ded28cce75c6d2d5a0c2b7ac5acbad478404585",
      "worktree_digest": "sha256:9ee260744f75bab9615683e936e32d48ca5ddda15edf5e9e05e0cc52d8309a15",
      "untracked_digest": "absent"
    },
    {
      "path": "cli/Cargo.toml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:c523ccf0695de8554d9c162c4402dd6a9142604111395832674f49e5353120d8",
      "index_digest": "sha256:c523ccf0695de8554d9c162c4402dd6a9142604111395832674f49e5353120d8",
      "worktree_digest": "sha256:d5e6d06061401fb0cb74fdaa24c24972890f5bc5c11bc78d99fede6c98cdb942",
      "untracked_digest": "absent"
    },
    {
      "path": "docs/memory-rust-backend.md",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:91b946600cfe584b1b4641234f06cc33dca0cc250688b4b11a3a5c5b44edeebb",
      "index_digest": "sha256:91b946600cfe584b1b4641234f06cc33dca0cc250688b4b11a3a5c5b44edeebb",
      "worktree_digest": "sha256:91b946600cfe584b1b4641234f06cc33dca0cc250688b4b11a3a5c5b44edeebb",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/benchmark.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:0915ca1f7a2cd4c428419213c68624aca2301619e66b0c9ba8dee9bd3b03bf23",
      "index_digest": "sha256:0915ca1f7a2cd4c428419213c68624aca2301619e66b0c9ba8dee9bd3b03bf23",
      "worktree_digest": "sha256:0915ca1f7a2cd4c428419213c68624aca2301619e66b0c9ba8dee9bd3b03bf23",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/retrieval_v2.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:11a7e5a6ca2466ef729b3f3087937d878aadbeaedadea4b4ec58027c6dc04952",
      "index_digest": "sha256:11a7e5a6ca2466ef729b3f3087937d878aadbeaedadea4b4ec58027c6dc04952",
      "worktree_digest": "sha256:11a7e5a6ca2466ef729b3f3087937d878aadbeaedadea4b4ec58027c6dc04952",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/schema.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:c61930d9eb48ebca5be36ac51fbaf6b53441475c9f6db46458aea71500430821",
      "index_digest": "sha256:c61930d9eb48ebca5be36ac51fbaf6b53441475c9f6db46458aea71500430821",
      "worktree_digest": "sha256:60e25dcb001c5c42e02923ac548ad567f7faca2f513065ae94bf5211cd3fabaf",
      "untracked_digest": "absent"
    },
    {
      "path": "memory_rust/backend.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a5b8982ef0f457b683d3b2b7b128d359e151ad65b9613fc49de244056caeb7ec",
      "index_digest": "sha256:a5b8982ef0f457b683d3b2b7b128d359e151ad65b9613fc49de244056caeb7ec",
      "worktree_digest": "sha256:a5b8982ef0f457b683d3b2b7b128d359e151ad65b9613fc49de244056caeb7ec",
      "untracked_digest": "absent"
    },
    {
      "path": "memory_rust/native/Cargo.toml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:e7bfbb381cfa15304e4b46187922031f0eb339266091e619f78dc4e22ed08703",
      "index_digest": "sha256:e7bfbb381cfa15304e4b46187922031f0eb339266091e619f78dc4e22ed08703",
      "worktree_digest": "sha256:e7bfbb381cfa15304e4b46187922031f0eb339266091e619f78dc4e22ed08703",
      "untracked_digest": "absent"
    },
    {
      "path": "memory_rust/native/pyproject.toml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a7bd8449c7c6c97472bb6cbf871299ae8d5743e69a8fbd2563a141d9bf4df9c6",
      "index_digest": "sha256:a7bd8449c7c6c97472bb6cbf871299ae8d5743e69a8fbd2563a141d9bf4df9c6",
      "worktree_digest": "sha256:a7bd8449c7c6c97472bb6cbf871299ae8d5743e69a8fbd2563a141d9bf4df9c6",
      "untracked_digest": "absent"
    },
    {
      "path": "memory_rust/native/src/lib.rs",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:39030695b7c31ea448d74ebc31098a3a72480f9afc89d199b7b7077303fa6246",
      "index_digest": "sha256:39030695b7c31ea448d74ebc31098a3a72480f9afc89d199b7b7077303fa6246",
      "worktree_digest": "sha256:39030695b7c31ea448d74ebc31098a3a72480f9afc89d199b7b7077303fa6246",
      "untracked_digest": "absent"
    },
    {
      "path": "memory_rust/native/src/promotion.rs",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:493599face26ef26ec46cb491cca21084e5e036bbca55f564c41d34516f7f4de",
      "index_digest": "sha256:493599face26ef26ec46cb491cca21084e5e036bbca55f564c41d34516f7f4de",
      "worktree_digest": "sha256:493599face26ef26ec46cb491cca21084e5e036bbca55f564c41d34516f7f4de",
      "untracked_digest": "absent"
    },
    {
      "path": "memory_rust/native/src/retrieval.rs",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:bdfe5ec947459d4e2364c084f2cf3b4a33a2aa75fd42bbed8f3600beb19cb4d4",
      "index_digest": "sha256:bdfe5ec947459d4e2364c084f2cf3b4a33a2aa75fd42bbed8f3600beb19cb4d4",
      "worktree_digest": "sha256:bdfe5ec947459d4e2364c084f2cf3b4a33a2aa75fd42bbed8f3600beb19cb4d4",
      "untracked_digest": "absent"
    },
    {
      "path": "memory_rust/python_backend.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:ed6f73a8ad358bad868e06c48a4d9eaa4c88b959ce5e592d6c4647a0019216df",
      "index_digest": "sha256:ed6f73a8ad358bad868e06c48a4d9eaa4c88b959ce5e592d6c4647a0019216df",
      "worktree_digest": "sha256:ed6f73a8ad358bad868e06c48a4d9eaa4c88b959ce5e592d6c4647a0019216df",
      "untracked_digest": "absent"
    },
    {
      "path": "memory_rust/selector.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:d21f3f8625fb20fa8d047c348e28244db64077b40d1f468321f00daaf518ead8",
      "index_digest": "sha256:d21f3f8625fb20fa8d047c348e28244db64077b40d1f468321f00daaf518ead8",
      "worktree_digest": "sha256:d21f3f8625fb20fa8d047c348e28244db64077b40d1f468321f00daaf518ead8",
      "untracked_digest": "absent"
    },
    {
      "path": "pyproject.toml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:fcba17a80adf3fe48c2a4076a19ee6cdab093efa325bc91a0466cf299105dd16",
      "index_digest": "sha256:fcba17a80adf3fe48c2a4076a19ee6cdab093efa325bc91a0466cf299105dd16",
      "worktree_digest": "sha256:c127d408ca2b09267d3101086628cb446f801d2954779d510326c296d963ed66",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_benchmark.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:2a666053a79c19bdcf75905a65ad8249ef463a1a02b577d24c5fa984b1d55626",
      "index_digest": "sha256:2a666053a79c19bdcf75905a65ad8249ef463a1a02b577d24c5fa984b1d55626",
      "worktree_digest": "sha256:2a666053a79c19bdcf75905a65ad8249ef463a1a02b577d24c5fa984b1d55626",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_benchmark_and_log.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:96b55070e25390040ee5a1b5f69594a1a4604e4a810786ddc7f36a13e97f43e8",
      "index_digest": "sha256:96b55070e25390040ee5a1b5f69594a1a4604e4a810786ddc7f36a13e97f43e8",
      "worktree_digest": "sha256:96b55070e25390040ee5a1b5f69594a1a4604e4a810786ddc7f36a13e97f43e8",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_memory_rust_promotion.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:9d4202785baeebcb029856bc541110eea8fd71490d00b9615f39784b172de4ff",
      "index_digest": "sha256:9d4202785baeebcb029856bc541110eea8fd71490d00b9615f39784b172de4ff",
      "worktree_digest": "sha256:9d4202785baeebcb029856bc541110eea8fd71490d00b9615f39784b172de4ff",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_memory_rust_selector.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a558a5eeba893e1c8766d561c9b178b6ca41d2b4852ce9c543cfe3f62c2b6611",
      "index_digest": "sha256:a558a5eeba893e1c8766d561c9b178b6ca41d2b4852ce9c543cfe3f62c2b6611",
      "worktree_digest": "sha256:a558a5eeba893e1c8766d561c9b178b6ca41d2b4852ce9c543cfe3f62c2b6611",
      "untracked_digest": "absent"
    }
  ]
}
  primary_symbols:
    - symbol: "load_cases"
      file: "memory/benchmark.py"
      lines: "51-77"
      role: "共享 benchmark case loader"
    - symbol: "evaluate_case"
      file: "memory/benchmark.py"
      lines: "151-289"
      role: "Python case evaluation and state restoration"
    - symbol: "run_benchmark"
      file: "memory/benchmark.py"
      lines: "292-360"
      role: "Python metric aggregation"
    - symbol: "retrieve_memories"
      file: "memory/retrieval_v2.py"
      lines: "467-610"
      role: "production Python retrieval contract and adapter boundary"
    - symbol: "RustMemoryBackend.retrieve"
      file: "memory_rust/selector.py"
      lines: "89-116"
      role: "PyO3 retrieval adapter"
    - symbol: "retrieve"
      file: "memory_rust/native/src/retrieval.rs"
      lines: "191-227"
      role: "Rust retrieval hot path"
  related_symbols:
    - symbol: "_write_case_db"
      relationship: "CALLS"
      relevance: "canonical benchmark memories fixture writer"
    - symbol: "RetrievalRequest"
      relationship: "CONTRACT"
      relevance: "backend-neutral request fields"
    - symbol: "PythonMemoryBackend.retrieve"
      relationship: "IMPLEMENTS"
      relevance: "Python comparison backend"
    - symbol: "ensure_supported"
      relationship: "CALLS"
      relevance: "schema 14 precondition for Rust database access"
    - symbol: "promote"
      relationship: "DEFERRED / high-risk"
      relevance: "write transaction intentionally excluded from retrieval benchmark"
  execution_path:
    - "Load cases and optional embedding fixture."
    - "For each case, create isolated schema 14 DB; Rust copy also contains schema_meta version 14."
    - "Resolve mode and pool limit using production adapter rules."
    - "Run Python and/or strict Rust backend against independent identical DB copies."
    - "Normalize result fields, score correctness, then compute parity diagnostics."
    - "When performance is requested, time backend calls only after warmup and emit JSON report."
  pdg_constraints:
    - description: "Current MCP PDG is stale-provenance auxiliary evidence only."
      affected_statements: ["memory/benchmark.py:166-205", "memory/benchmark.py:287-289"]
      implementation_consequence: "Preserve state restoration and cache isolation based on source; do not rely on unverified graph completeness."
    - description: "Python retrieval mutates access timestamps after producing the result."
      affected_statements: ["memory/retrieval_v2.py:603-606"]
      implementation_consequence: "Use independent DB copies for Python/Rust parity and repeated performance runs."
  architectural_patterns:
    - pattern: "Python-safe optional backend selection"
      example_location: "memory_rust/selector.py:143-198"
      usage_guidance: "Use strict selection in benchmark so failures are observable; do not use auto/shadow as the measured Rust path."
    - pattern: "Canonical schema DDL for temporary memory stores"
      example_location: "memory/schema.py:270-304"
      usage_guidance: "Use the canonical memories DDL and add schema_meta version 14 for native compatibility."
    - pattern: "Fixture-based deterministic embedding scores"
      example_location: "memory/benchmark.py:364-403"
      usage_guidance: "Reuse fixture semantics; no network or live model calls in benchmark."
  files_to_modify:
    - file: "memory/benchmark.py"
      symbols: ["evaluate_case", "run_benchmark"]
      intended_change: "Extract shared result scoring/fixture boundary without changing default Python output."
    - file: "memory_rust/benchmark.py"
      symbols: []
      intended_change: "Add independent Rust correctness/parity/performance runner and CLI."
    - file: "tests/test_memory_rust_benchmark.py"
      symbols: []
      intended_change: "Add runner and report contract tests."
    - file: "tests/test_benchmark.py"
      symbols: []
      intended_change: "Preserve Python benchmark regression coverage."
    - file: "tests/test_benchmark_and_log.py"
      symbols: []
      intended_change: "Preserve shared benchmark helper edge-case coverage."
  tests:
    - file: "tests/test_memory_rust_benchmark.py"
      scenarios:
        - "valid case -> Rust fixture DB -> schema_meta=14 and expected result evaluation"
        - "native unavailable -> strict runner raises/reports error and exits nonzero"
        - "schema/API mismatch -> explicit contract error, never Python pass"
        - "native runtime error -> case/backend error with diagnostic context"
        - "fake parity difference -> hard vs diagnostic mismatch fields are separated"
        - "fixed latency samples -> correct p50/p95 and deterministic summary"
    - file: "tests/test_benchmark.py"
      scenarios:
        - "existing Python dataset -> same loader/metrics/default CLI behavior"
    - file: "tests/test_benchmark_and_log.py"
      scenarios:
        - "empty/malformed/duplicate fixture inputs -> existing behavior remains explicit"
  verification_commands:
    - "python -m pytest tests/test_benchmark.py tests/test_benchmark_and_log.py tests/test_memory_rust_selector.py -q"
    - "python -m memory.benchmark --compare"
    - "cargo test --manifest-path memory_rust/native/Cargo.toml"
  risks:
    - "Stale GitNexus runner provenance limits graph completeness; source verification is authoritative."
    - "schema_meta omission makes Rust native reject every temporary DB."
    - "Python global DB_PATH/cache and access timestamp writes can contaminate parity/performance."
    - "Rust promotion is high-risk and intentionally deferred."
  assumptions:
    - "The native wheel can be installed or built for real integration runs; unit tests can inject a fake strict backend when it cannot."
    - "The existing case JSON schema remains the source of truth for both backends."
  open_questions:
    - "Whether to add a separate CI performance job after the first benchmark report exists."
    - "Whether a later promotion benchmark should share the report schema or use a transaction-specific suite."
  avoid:
    - "Do not change Python benchmark default behavior or remove its entrypoint."
    - "Do not use auto/shadow fallback as the measured Rust result."
    - "Do not treat native unavailable, contract mismatch, schema mismatch, or runtime error as a passing case."
    - "Do not modify, stage, commit, or revert cli/Cargo.toml, cli/Cargo.lock, or pyproject.toml."
    - "Do not include promotion writes in the retrieval performance loop."
    - "Do not repeat full repository discovery; re-verify only the cited assumptions before implementation."
```

## 12. Assumptions and Open Questions

Assumptions:
- [assumed] A new `memory_rust/benchmark.py` module is acceptable as the public benchmark entrypoint and can import the existing Stella `memory` package in the normal repository/release environment.
- [assumed] The native integration test may be skipped when the optional wheel is unavailable, but the benchmark command itself must fail loudly rather than fallback.
- [assumed] Score tolerance will be chosen from observed parity data in implementation, not guessed before the first report; final/behavior/mode mismatches remain hard failures.

Open questions:
- Should performance output be a committed golden artifact or only JSON emitted by the command? Recommendation: emitted JSON only until machine variance is characterized.
- Should the benchmark be wired into CI? Recommendation: not in this first implementation; keep correctness in tests and performance manual until the Rust wheel build cost is settled.
- Promotion benchmark, FTS-enabled benchmark, and live embedding/network benchmark are explicitly deferred.

Evidence limitation:
- Docker index content matches the pinned commit, but its runner identity is `stale-or-unknown`; the host runner install failed because the environment could not spawn `C:\windows\system32\cmd.exe`. The MCP service also reports an older index. No graph-derived conclusion above should override current source.
- The three existing dirty version files are outside this task and must remain untouched.

## 13. Definition of Done

- [ ] `memory_rust.benchmark` exists with a documented CLI and no change to Python benchmark defaults.
- [ ] The Rust runner consumes the same case JSON and embedding fixture format and initializes schema 14 plus `schema_meta` correctly.
- [ ] Strict native failures are explicit, contextual, nonzero, and never counted as correctness passes.
- [ ] Correctness metrics match the Python benchmark schema; parity distinguishes hard result mismatches from diagnostic score/trace differences.
- [ ] Performance mode reports warmup, iteration count, min/mean/p50/p95/max, throughput, and errors in JSON.
- [ ] New tests cover failure paths, parity diagnostics, deterministic correctness, and percentile math.
- [ ] Existing benchmark tests, selector tests, and native Cargo tests pass.
- [ ] No changes are made to `cli/Cargo.toml`, `cli/Cargo.lock`, `pyproject.toml`, release naming, or promotion behavior.
