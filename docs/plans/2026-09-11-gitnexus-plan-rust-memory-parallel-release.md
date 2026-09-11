# GitNexus Engineering Plan

> Task: 将 Stella 记忆模块增加一个 Rust 实现，与原 Python 实现并行维护，并在同一 vX.Y.Z Release 中生成独立的 Python/Rust 引擎资产。
> Evidence verified at commit `8970ce08f73001cf970711fa65aa11d1b06eb9d4`; GitNexus index refreshed this session with `--index-only --pdg` in Docker using GitNexus 1.6.11 (37,105 nodes, 86,747 edges, 490 clusters, 470 flows); refreshed impact results are exact, while FTS graph features were unavailable in load-only mode, so source remains authoritative for FTS behavior.
> Evidence provenance schema 2; the generated plan path is excluded from the global dirty digest.

## 1. Objective

[verified] 保留现有 `memory/` Python 实现、其数据库/schema/migration、LLM 整合和所有现有调用方式；Python backend 继续是默认和最终 fallback。

[inferred] 新增一个可选的 Rust memory backend，优先承接可测量的 SQLite/FTS 候选读取、策略过滤排序、相似记忆合并和候选晋升事务等 CPU/数据库热路径；不把 embedding HTTP、LLM orchestration、scheduler 或 compressor 一并迁移。

[inferred] Rust backend 通过 `python | rust | auto | shadow | strict` 选择器逐步启用，支持只读 shadow 对比、Rust 不可用时自动回退，以及明确的 strict 失败模式。

[inferred] Rust 引擎与 Python 引擎在最终 Release 中保持独立资产，但共享同一个 `RELEASE_REF=vX.Y.Z`：Python 资产继续命名为 `Stella-vX.Y.Z-win64.zip`，Rust 资产命名为 `Stella-Rust_engine_version-vX.Y.Z-win64.zip`。两者版本号必须相同。

## 2. Current Behaviour

[verified] `memory/retrieval_v2.py:335-474` 负责 v2 记忆检索主流程，`retrieve_memories_emb` 在 `memory/retrieval_v2.py:485-541` 中调用 `EmbeddingService` 并保留 Python fallback；该路径被 `_build_user_context_v2` 使用，位于 `build_user_context` 热路径。

[verified] `memory/memory_manager.py:99-195` 负责晋升事务及提交后的 history/cache/compressor 副作用；`memory/memory_manager.py:216-256` 定义 Gate 1 规则，`342-535` 承担相似合并、建库、配额和 FTS 同步。

[verified] `memory/consolidator.py:155-185` 是 Python LLM 整合器，`700-720` 将候选写入并触发晋升；它不应在第一阶段被 Rust 替代。

[verified] `memory/schema.py:55-58` 的 schema version 为 14，`270-305` 定义 `memories` 表；第一阶段保持 schema 及 migration 归 Python 管理。

[verified] `memory/pre_processors.py:542-585` 是上下文检索入口；`stella_project/plugins/bot_main/ai_gateway.py:494-507,1812-1838` 分别触发即时和定时整合，因此 integration 必须保持现有调度、锁和调用顺序。

[verified] `.github/workflows/release.yml:89-103` 将主 release 的 Python 和 CLI 版本绑定；`:335-339` 当前生成 `Stella-${RELEASE_REF}-win64.zip`，`:480-507` 将其上传到同一个 GitHub Release。Rust 引擎应作为独立 zip 资产加入同一 Release，不能放入 `cli/`，也不能污染 Python zip 的布局。

## 3. Relevant Architecture

[inferred] Python `memory/` 保留为控制平面：负责 schema migration、EmbeddingService、LLM 提取/整合、现有 group lock、`bump_memory_history()`、compressor 等提交后副作用及 fallback。

[inferred] 新的 `memory_rust/` 是独立可安装的 Python distribution，内部包含 Python adapter/selector 和 PyO3/maturin native extension；主 Stella 代码只通过可选导入调用它，未安装时不影响 Python backend。

[inferred] 建议边界如下：

```text
Python request/context
  -> EmbeddingService (Python, unchanged)
  -> selector (python/rust/auto/shadow/strict)
  -> Rust: SQLite/FTS candidates -> policy filter/rank -> similarity merge
  -> Python: context assembly, LLM consolidation, locks, post-commit side effects
```

[inferred] Rust/Python contract 需要显式携带 backend API version、schema version 14、scope/user/group identifiers、candidate IDs、scores、ordering and error category；不允许 Rust 自己执行 migration 或隐式扩大用户可见范围。

## 4. GitNexus Findings

[graph] 刷新后的 `impact("MemoryManager", upstream, depth=3)` 返回 `risk=LOW`、`impactedCount=4`；d=1 为 `memory/consolidator.py`，d=2 为 `scripts/probe_consolidation.py` 和 `ai_gateway.py`。结论：仍不得整体替换 `MemoryManager`，只能包住可隔离的晋升热路径并保留 Python fallback。

[graph] 刷新后的 `impact("retrieve_memories_emb", upstream, depth=3)` 返回 `risk=LOW`、`impactedCount=3`；d=1 为 `_build_user_context_v2`，并影响 `build_user_context` 流程。结论：它仍是首个适合 shadow/read-path 验证的边界，但输出 parity 必须覆盖上下文热路径。

[graph] 刷新后的 `impact("MemoryConsolidator", upstream, depth=3)` 返回 `risk=LOW`、`impactedCount=3`；d=1 为 `scripts/probe_consolidation.py` 和 `ai_gateway.py`。结论：保留 Python LLM 整合器，只替换其后端候选晋升调用。

[graph] `context("_build_user_context_v2")` 返回 `risk=LOW`，直接由 `build_user_context` 调用。结论：检索 backend 切换必须不改变上下文预算、scope 和缓存行为。

[graph] 刷新后的 `impact("EmbeddingService", upstream, depth=3)` 返回 `risk=MEDIUM`、`impactedCount=24`、d=1 直接依赖 6 个模块，包括 capability router、deploy、addressing、cost gates、participation 和 retrieval。结论：不能把 EmbeddingService 整体迁移或改成 Rust 专属服务。

[graph] 相关测试包括 `tests/test_retrieval_v2_and_schema.py`、`tests/test_memory_manager*.py`、`tests/test_memory_promotion_deadlock.py`、`tests/test_cross_user_isolation.py`、`tests/test_policy.py`、`tests/test_embeddings.py` 和 `tests/test_benchmark.py`；源文件核对确认这些测试覆盖检索、晋升、FTS、隔离、策略、embedding 和 benchmark 边界。

## 5. Statement-Level PDG Findings

GitNexus index 已通过 Docker 使用 `--index-only --pdg` 刷新；本次复核未新增独立 `pdg_query` slice，因此以下顺序约束仍以当前源码和测试的 source verification 为准：

[verified] Embedding 请求必须先完成，Rust 只接收已得到的 query embedding 或候选输入；embedding 失败仍走当前 Python fallback。

[verified] 现有 group lock、candidate validation、SQLite transaction commit、`bump_memory_history()`、cache invalidation 和 compressor side effect 有先后关系；Rust promotion 只能返回已提交/未提交结果，不能自行触发 Python 提交后副作用。

[inferred] shadow 模式必须是只读且无写事务；任何 Rust exception、ABI mismatch、schema mismatch 或 parity mismatch 都应可降级到 Python，strict 模式才将其暴露为请求失败。

[inferred] Rust 事务需要保证 FTS 同步与 base-table mutation 的原子性，并在 rollback 时不产生 Python history/cache/compressor side effect。

## 6. Proposed Changes

1. **建立独立 backend contract and selector。**
   - New files: `memory_rust/__init__.py`, `memory_rust/backend.py`, `memory_rust/selector.py`, `memory_rust/python_backend.py`.
   - Responsibility: 定义检索/晋升 DTO、backend API version、`python|rust|auto|shadow|strict` 选择、能力探测、错误分类和 Python adapter。
   - Behaviour: 默认 `python`；`auto` 在 Rust 包缺失、扩展加载失败、schema/API 不兼容或运行时错误时回退；`shadow` 只对比不写库；`strict` 不回退。
   - Constraint: adapter 必须调用现有 `memory` 实现，不复制另一套 Python 记忆逻辑。

2. **新增独立 Rust package/native extension。**
   - New files: `memory_rust/native/Cargo.toml`, `memory_rust/native/pyproject.toml`, `memory_rust/native/src/lib.rs`, `retrieval.rs`, `promotion.rs`, `policy.rs`, `similarity.rs`, `schema.rs`.
   - Responsibility: 接收稳定 DTO，在现有 SQLite schema 14 上执行候选读取、FTS/vector candidate merge、policy filter/rank、相似记忆合并、晋升事务和 FTS sync。
   - Constraint: 不负责 schema migration、LLM/embedding HTTP、scheduler、Python async lock、compressor 或 proactive/session compact；所有 SQL 参数化，scope/user/group 条件在 query 层和结果层双重校验。
   - Packaging: 使用独立 distribution name `stella-memory-rust`，import namespace `memory_rust`，Rust crate version 与 Python distribution version 同步但不跟随 Stella 主版本。

3. **把检索热路径接入 selector。**
   - Files: `memory/retrieval_v2.py`, `memory/pre_processors.py`, `memory/cache_keys.py`.
   - Responsibility: 保持 `EmbeddingService` 和现有 query/context assembly，调用 selector 执行候选读取与排序；cache key 增加 backend contract/policy version，避免 Python/Rust 输出交叉污染。
   - Behaviour: Python 输出作为 parity baseline；shadow 记录 candidate IDs/order/score delta，不修改用户上下文；rust-read 只替换 retrieval data plane。

4. **把晋升事务接入 selector，同时保留 Python side effects。**
   - Files: `memory/memory_manager.py`, `memory/consolidator.py`.
   - Responsibility: 在现有 group lock 和 LLM consolidation 之后，把可序列化的 promotion input 交给 Rust；Rust 返回 transaction result；Python 在 commit 成功后继续执行 `bump_memory_history()`、cache invalidation 和 compressor side effect。
   - Behaviour: Rust 失败时 `auto` 回到原 Python promotion；strict 记录可诊断错误；不得重复写入、重复合并或重复执行 post-commit side effect。

5. **增加 rollout configuration and observability。**
   - Files: selector/config integration and memory documentation, following the repository's existing settings convention.
   - Configuration: `MEMORY_BACKEND=python|rust|auto|shadow|strict`, `MEMORY_RUST_SHADOW=false`, `MEMORY_RUST_STRICT=false`.
   - Metrics/logs: backend selected, fallback reason, candidate count, parity mismatch, Rust elapsed time, Python elapsed time, promotion commit/rollback and schema/API mismatch; 禁止记录 memory text、embedding 或跨用户数据。

6. **建立同一主 Release 中的独立 Rust 引擎资产。**
   - New file: `.github/workflows/release-memory-rust.yml`; update `.github/workflows/release.yml` only to call it or consume its artifact.
   - Trigger/version contract: use the main `vX.Y.Z` release tag and the same `RELEASE_REF`; do not create a separate `memory-rs-v*` tag or a different Rust version.
   - Build: compile/package the Windows Rust engine and produce `Stella-Rust_engine_version-${RELEASE_REF}-win64.zip`. The existing Python build remains `Stella-${RELEASE_REF}-win64.zip`.
   - Release: upload both independently named assets to the same GitHub Release, with an assertion that both filenames contain exactly the same `RELEASE_REF`; retain separate build directories and checksums.
   - Constraint: `.github/workflows/release.yml` remains responsible for the Python engine and its existing name; Rust build output must never be copied into the Python zip.



7. **Keep the two implementations independently packaged and installable.**
   - Files: `memory_rust/native/pyproject.toml`, `memory_rust/native/Cargo.toml`, main `pyproject.toml` package include/exclude rules, `tests/test_release_layout.py`.
   - Requirement: main Stella wheel/sdist contains Python `memory/` and no Rust `target/`, build cache or native artifacts; Rust wheel contains only the optional Rust backend and its metadata.
   - Compatibility: publish a small compatibility matrix covering `stella-memory-rust` version, supported Stella API version, schema version and supported Python versions.

## 7. Implementation Sequence

1. Record the current Python benchmark baseline and golden outputs for retrieval ordering, policy scores, similarity merge, promotion and FTS sync. Freeze the contract at schema 14 and define the backend API version.
2. Add the independent selector/contract/Python adapter with `python` as the only active default. Add backend choice and structured fallback reasons without changing default behaviour.
3. Implement Rust read-only candidate loading and ranking. Add Rust unit tests for scope filtering, time/source policy, ties, FTS/vector merge, deterministic ordering and similarity merge.
4. Implement `shadow` execution and parity reports. Compare IDs, order, score tolerance, filtered reasons and errors against Python; do not write or alter context in shadow mode.
5. Enable `rust-read` only after parity fixtures pass. Preserve Python embedding, context budget, cache invalidation and all user/group isolation checks.
6. Implement Rust promotion as a transaction. Keep Python group locks and LLM consolidation outside Rust; keep history/cache/compressor after commit in Python. Add rollback and duplicate-invocation tests.
7. Add `rust-promote`, `auto` and `strict` rollout modes. Default remains Python until performance, parity, concurrency and fallback gates are met; document an environment-only rollback to `MEMORY_BACKEND=python`.
8. Add independent packaging metadata and the reusable Rust release workflow. Verify that the same main `vX.Y.Z` release produces `Stella-vX.Y.Z-win64.zip` and `Stella-Rust_engine_version-vX.Y.Z-win64.zip`, while the two build directories and package contents remain separate.
9. Run the full targeted Python suite, Rust tests, benchmark comparison and release-layout checks. Only then update the recommended deployment setting from `python` to `auto`.

## 8. Test Strategy

Existing tests to preserve/update:

- `tests/test_retrieval_v2_and_schema.py`: Python/Rust retrieval parity, schema 14 compatibility, deterministic ordering and Python fallback.
- `tests/test_memory_manager.py`, `tests/test_memory_manager_v2.py`, `tests/test_memory_manager_fts_sync.py`: promotion result parity, merge/quota/FTS semantics, commit and rollback.
- `tests/test_memory_promotion_deadlock.py`: existing lock ordering with Rust promotion and no nested lock acquisition.
- `tests/test_consolidator_core.py`: LLM consolidation remains Python-owned and calls the selected promotion backend exactly once.
- `tests/test_embeddings.py`: EmbeddingService remains unchanged and is not required for Rust package import.
- `tests/test_policy.py`: policy ordering and score tolerance.
- `tests/test_benchmark.py`: benchmark command and comparison output.
- `tests/test_release_layout.py`: main artifact remains exactly `Stella-vX.Y.Z-win64.zip`; Rust artifact is separate and exactly `Stella-Rust_engine_version-vX.Y.Z-win64.zip`; both carry the same release version and the Python zip contains no Rust native outputs.

New tests:

- `tests/test_memory_rust_selector.py`: package missing, ABI/load failure, schema mismatch, runtime exception, `auto` fallback, `strict` failure, `shadow` no-write.
- `tests/test_memory_rust_parity.py`: identical candidate IDs/order within declared score tolerance; explicit mismatch diagnostics; empty/large/tie-heavy candidate sets.
- `tests/test_memory_rust_promotion.py`: merge, quota, FTS atomicity, rollback, duplicate promotion and post-commit side effects exactly once.
- `tests/test_memory_rust_isolation.py`: cross-user/group scope cannot leak through FTS, vector candidates, cache or similarity merge.
- `memory_rust/native/tests/*`: Rust-level SQL, policy, similarity, transaction and malformed-input tests.

Verification commands:

- `pytest -q tests/test_retrieval_v2_and_schema.py tests/test_memory_manager.py tests/test_memory_manager_v2.py tests/test_memory_manager_fts_sync.py tests/test_memory_promotion_deadlock.py tests/test_consolidator_core.py tests/test_embeddings.py tests/test_policy.py`
- `python -m memory.benchmark --compare`
- `cargo fmt --manifest-path memory_rust/native/Cargo.toml --check`
- `cargo test --manifest-path memory_rust/native/Cargo.toml`
- `cargo clippy --manifest-path memory_rust/native/Cargo.toml --all-targets --all-features -- -D warnings`
- CI's existing Python test command from `.github/workflows/ci.yml`, plus the new Rust matrix job.

## 9. Risk and Impact Analysis

- [graph] Refreshed `impact("MemoryManager", upstream, depth=3)` reports `risk=LOW`, `impactedCount=4`, with direct dependency `memory/consolidator.py` and depth-2 `scripts/probe_consolidation.py`/`ai_gateway.py`. Source-level transaction compatibility still requires preserving the Python class and public semantics.
- [graph] Refreshed `impact("MemoryConsolidator", upstream, depth=3)` reports `risk=LOW`, `impactedCount=3`, with direct `scripts/probe_consolidation.py` and `ai_gateway.py`; the Rust backend remains a promotion implementation detail, not a new scheduler or consolidator.
- [graph] `EmbeddingService` is MEDIUM risk and shared outside memory. Do not replace it or make Rust import force embedding dependencies.
- [inferred] Semantic drift in policy score/tie ordering can change prompts and user-visible answers; use golden fixtures and tolerance rules before enabling `rust-read`.
- [inferred] SQLite/FTS transaction errors can create base-table/index divergence or duplicate history updates; test commit/rollback and keep Python post-commit hooks outside the Rust transaction.
- [inferred] Async lock and Rust transaction interaction can deadlock; Rust must not acquire Python locks, and Python must preserve the current outer lock order.
- [inferred] Optional native wheels may be missing for a platform or Python ABI; `auto` must fall back and expose a metric/log without making the main release fail.
- [inferred] The two assets must remain separate while sharing one `RELEASE_REF`; workflow assertions must reject a Python/Rust filename or metadata version mismatch, and startup capability checks must still reject unsupported schema/API combinations.
- [inferred] Performance gains are not accepted from wall-clock anecdotes; compare p50/p95 retrieval and promotion latency, CPU time, allocations where available, and fallback rate against the Python baseline.

## 10. Files Expected to Change

| File | Symbols | Reason |
| ---- | ------- | ------ |
| `memory/retrieval_v2.py` | `retrieve_memories_emb` | Route candidate read/rank through selector while preserving embedding and Python fallback. |
| `memory/memory_manager.py` | `MemoryManager` promotion path | Delegate only the transaction hot path; preserve locks and post-commit side effects. |
| `memory/consolidator.py` | promotion call site | Keep LLM consolidation in Python and select the promotion backend once. |
| `memory/pre_processors.py` | `_build_user_context_v2` | Preserve context assembly and make backend choice observable. |
| `memory/cache_keys.py` | cache version/key helpers | Separate Python/Rust backend and policy contract cache entries. |
| `memory_rust/` | new selector/adapter package | Independent optional distribution and Python contract layer. |
| `memory_rust/native/` | new Rust crate | Native retrieval, policy, similarity and promotion implementation. |
| `pyproject.toml` | package include/exclude metadata | Keep Rust distribution out of the main Stella artifact; preserve existing user changes. |
| `.github/workflows/release-memory-rust.yml` | new workflow | Build the separate Rust zip and upload `Stella-Rust_engine_version-${RELEASE_REF}-win64.zip` to the same `vX.Y.Z` Release. |
| `tests/test_memory_rust_*.py` | new tests | Selector, parity, isolation, promotion and fallback coverage. |
| `tests/test_release_layout.py` | release layout assertions | Verify separate artifacts and absence of native build output in main release. |

## 11. Reusable Implementation Context

```json
{
  "implementation_context": {
    "task_summary": "Add an independently released optional Rust memory backend while retaining the Python memory implementation as the default and fallback.",
    "acceptance_criteria": [
      "The existing Python memory module remains available and passes its current tests.",
      "Rust retrieval/promotion can be selected without changing schema 14, embedding ownership, LLM orchestration, locks or post-commit Python side effects.",
      "shadow, auto and strict modes have deterministic behavior and tested fallback/error handling.",
      "Python and Rust outputs meet explicit parity rules before Rust is recommended.",
      "Main Stella releases use vX.Y.Z and exclude Rust native build outputs.",
      "Rust releases use the same main vX.Y.Z release version but produce the independent asset Stella-Rust_engine_version-vX.Y.Z-win64.zip alongside Stella-vX.Y.Z-win64.zip."
    ],
    "evidence_provenance": {
  "schema_version": 2,
  "head_commit": "8970ce08f73001cf970711fa65aa11d1b06eb9d4",
  "generated_plan_path": "docs/plans/2026-09-11-gitnexus-plan-rust-memory-parallel-release.md",
  "global_dirty_digest": {
    "algorithm": "sha256",
    "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
    "value": "74377abb74ce97bafba24c1ce88cb3be6ab5ea883cbc2af9e10df2b491c7b180"
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
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:72ffa0a55d11fd17d17ca884615f5ae7976f2f0487d793f90720e61f5296fa5f",
      "index_digest": "sha256:72ffa0a55d11fd17d17ca884615f5ae7976f2f0487d793f90720e61f5296fa5f",
      "worktree_digest": "sha256:23cf14adfcf4c2ae1baeb9d4cb7ed173ac12c985f0bf5ddb217a02576039fb0f",
      "untracked_digest": "absent"
    },
    {
      "path": ".github/workflows/release.yml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:8be95b11c2bc630acc4bf53a63eba1efe7c72dd66171e097340b6405edd272af",
      "index_digest": "sha256:8be95b11c2bc630acc4bf53a63eba1efe7c72dd66171e097340b6405edd272af",
      "worktree_digest": "sha256:8be95b11c2bc630acc4bf53a63eba1efe7c72dd66171e097340b6405edd272af",
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
      "path": "memory/cache_keys.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a47841fd098f0c37e4fae51473893002cd5c4792adc91bcde0767d06b720dec9",
      "index_digest": "sha256:a47841fd098f0c37e4fae51473893002cd5c4792adc91bcde0767d06b720dec9",
      "worktree_digest": "sha256:a47841fd098f0c37e4fae51473893002cd5c4792adc91bcde0767d06b720dec9",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/consolidator.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:c24e77e2e6a7c4c0fbf7e598cfa4ceb530100d4e713e0d373d365e908810f672",
      "index_digest": "sha256:c24e77e2e6a7c4c0fbf7e598cfa4ceb530100d4e713e0d373d365e908810f672",
      "worktree_digest": "sha256:c24e77e2e6a7c4c0fbf7e598cfa4ceb530100d4e713e0d373d365e908810f672",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/embeddings.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:3cc1610562879116d474b74b1a44876dffd0c9125c5126feb9820f4d1cae3226",
      "index_digest": "sha256:3cc1610562879116d474b74b1a44876dffd0c9125c5126feb9820f4d1cae3226",
      "worktree_digest": "sha256:87f1267d9dec0883325fcdca02f90a38e5ac51d8349f66de6657c5198476ee53",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/memory_manager.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:bc5473810390b5af8f0b7d3b7009aa2017fd0c48ebe4bf75dbc24d67f98e6b86",
      "index_digest": "sha256:bc5473810390b5af8f0b7d3b7009aa2017fd0c48ebe4bf75dbc24d67f98e6b86",
      "worktree_digest": "sha256:f781f7a8671d0fa22e6bae882dc88aa0c25e5f176256297e7af1bb4670c557f8",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/policy.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:97fcf832995e0eb8a11e6d16dec731bf6a910f5b2357090902807e73186df1eb",
      "index_digest": "sha256:97fcf832995e0eb8a11e6d16dec731bf6a910f5b2357090902807e73186df1eb",
      "worktree_digest": "sha256:97fcf832995e0eb8a11e6d16dec731bf6a910f5b2357090902807e73186df1eb",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/pre_processors.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:5542cee8e7c1367e1c10bcfa284af03860d0afb79c784f7b82103d9bed6518e8",
      "index_digest": "sha256:5542cee8e7c1367e1c10bcfa284af03860d0afb79c784f7b82103d9bed6518e8",
      "worktree_digest": "sha256:eb1e4fab85ef40ff3d6ab0c400a148bc4b36f1931ccbc9594bca7e18b4abc45b",
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
      "head_digest": "sha256:e146c96ba978476dd37d09885774266c70a54fc4b03960011bd078fdda31718e",
      "index_digest": "sha256:e146c96ba978476dd37d09885774266c70a54fc4b03960011bd078fdda31718e",
      "worktree_digest": "sha256:e146c96ba978476dd37d09885774266c70a54fc4b03960011bd078fdda31718e",
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
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:c61930d9eb48ebca5be36ac51fbaf6b53441475c9f6db46458aea71500430821",
      "index_digest": "sha256:c61930d9eb48ebca5be36ac51fbaf6b53441475c9f6db46458aea71500430821",
      "worktree_digest": "sha256:60e25dcb001c5c42e02923ac548ad567f7faca2f513065ae94bf5211cd3fabaf",
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
      "path": "scripts/probe_consolidation.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a0db3936a26a7017cb04e6f9046315475b8e40e1ef12d74ead38f21528e25cef",
      "index_digest": "sha256:a0db3936a26a7017cb04e6f9046315475b8e40e1ef12d74ead38f21528e25cef",
      "worktree_digest": "sha256:9e78d3f359e9af40473bf9f732b2a8c17d51320bd5b2f773a5c97e8265b8d4bd",
      "untracked_digest": "absent"
    },
    {
      "path": "stella_project/plugins/bot_main/ai_gateway.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:90e26001cf16b098ef0a80118ca2324770d43114e4228269a21c05fbbafff006",
      "index_digest": "sha256:90e26001cf16b098ef0a80118ca2324770d43114e4228269a21c05fbbafff006",
      "worktree_digest": "sha256:b3fb809144345b032aa1af72a0556cea8aa1d83cef16e3c8bd31bc7ebe89723f",
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
      "path": "tests/test_consolidator_core.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:960342ae058d0bd00f79e2cec997f678bd5bb2c616c0126c11c56a38bb3919d2",
      "index_digest": "sha256:960342ae058d0bd00f79e2cec997f678bd5bb2c616c0126c11c56a38bb3919d2",
      "worktree_digest": "sha256:960342ae058d0bd00f79e2cec997f678bd5bb2c616c0126c11c56a38bb3919d2",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_cross_user_isolation.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:5bd8e063ee3c69fafea9c107c9fb6424c286a579d7f696c9bc5f4b5a8487ea74",
      "index_digest": "sha256:5bd8e063ee3c69fafea9c107c9fb6424c286a579d7f696c9bc5f4b5a8487ea74",
      "worktree_digest": "sha256:5bd8e063ee3c69fafea9c107c9fb6424c286a579d7f696c9bc5f4b5a8487ea74",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_embeddings.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:4f7afe4ae04c44599d1988cbfd3472950342be0a5a04d8af1c5676de155b7da7",
      "index_digest": "sha256:4f7afe4ae04c44599d1988cbfd3472950342be0a5a04d8af1c5676de155b7da7",
      "worktree_digest": "sha256:4f7afe4ae04c44599d1988cbfd3472950342be0a5a04d8af1c5676de155b7da7",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_memory_manager.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a633820d4a237516f4a3c3e3cf55b0fb016f874c0f2f98df62384e0ec01963a4",
      "index_digest": "sha256:a633820d4a237516f4a3c3e3cf55b0fb016f874c0f2f98df62384e0ec01963a4",
      "worktree_digest": "sha256:d098ddb98888be02194676c7e5f1e515051f5b126c519446c7bc31cd3a40c20e",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_memory_manager_fts_sync.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:cd5a9f13b3754625994aa6a1757c7da64e9b9632df17422922c8dc076369a9d7",
      "index_digest": "sha256:cd5a9f13b3754625994aa6a1757c7da64e9b9632df17422922c8dc076369a9d7",
      "worktree_digest": "sha256:cd5a9f13b3754625994aa6a1757c7da64e9b9632df17422922c8dc076369a9d7",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_memory_manager_v2.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:e4ae5c2fdf19db0ac033b72a8a8164cf8b55e61ef351f735f757eefc1bdbadb0",
      "index_digest": "sha256:e4ae5c2fdf19db0ac033b72a8a8164cf8b55e61ef351f735f757eefc1bdbadb0",
      "worktree_digest": "sha256:e4ae5c2fdf19db0ac033b72a8a8164cf8b55e61ef351f735f757eefc1bdbadb0",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_memory_promotion_deadlock.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:165de60be40e36fcc37fe3f98fb219f2741fc101ad98ed7add571bb59e7095ca",
      "index_digest": "sha256:165de60be40e36fcc37fe3f98fb219f2741fc101ad98ed7add571bb59e7095ca",
      "worktree_digest": "sha256:165de60be40e36fcc37fe3f98fb219f2741fc101ad98ed7add571bb59e7095ca",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_migrations.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:402e33cfe610ec570c167fe717575e471f303a1560ede9b680fe109c9636f5d6",
      "index_digest": "sha256:402e33cfe610ec570c167fe717575e471f303a1560ede9b680fe109c9636f5d6",
      "worktree_digest": "sha256:402e33cfe610ec570c167fe717575e471f303a1560ede9b680fe109c9636f5d6",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_policy.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:dd4288b1ae8ef3b42e6b314aa70c16ad261f0248547b22c79dbed420e04dcaed",
      "index_digest": "sha256:dd4288b1ae8ef3b42e6b314aa70c16ad261f0248547b22c79dbed420e04dcaed",
      "worktree_digest": "sha256:dd4288b1ae8ef3b42e6b314aa70c16ad261f0248547b22c79dbed420e04dcaed",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_release_layout.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "unstaged",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:21b06c0809221a7ea426774c22d43c2d2be204138c7a4c73a13013b007126325",
      "index_digest": "sha256:21b06c0809221a7ea426774c22d43c2d2be204138c7a4c73a13013b007126325",
      "worktree_digest": "sha256:7e4e53dd6d2a7df89d24c35fbc94418c2c3f867e134fc08f1838257ffd18e051",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_retrieval_v2_and_schema.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:be5b7b7a31dcefcabc236dea0698d39b44fdb298f64d4b74e8da7c99fc4a2b4e",
      "index_digest": "sha256:be5b7b7a31dcefcabc236dea0698d39b44fdb298f64d4b74e8da7c99fc4a2b4e",
      "worktree_digest": "sha256:be5b7b7a31dcefcabc236dea0698d39b44fdb298f64d4b74e8da7c99fc4a2b4e",
      "untracked_digest": "absent"
    }
  ]
},
    "primary_symbols": [
      {
        "symbol": "MemoryManager",
        "file": "memory/memory_manager.py",
        "lines": "99-195,216-256,342-535",
        "role": "Existing promotion transaction and side-effect boundary; high-risk compatibility anchor."
      },
      {
        "symbol": "retrieve_memories_emb",
        "file": "memory/retrieval_v2.py",
        "lines": "485-541",
        "role": "Existing embedding-backed retrieval boundary and first Rust read-path candidate."
      },
      {
        "symbol": "_build_user_context_v2",
        "file": "memory/pre_processors.py",
        "lines": "542-585",
        "role": "Context hot-path caller whose budget/scope behavior must remain unchanged."
      },
      {
        "symbol": "MemoryConsolidator",
        "file": "memory/consolidator.py",
        "lines": "155-185,700-720",
        "role": "Python-owned LLM consolidation and promotion trigger."
      },
      {
        "symbol": "EmbeddingService",
        "file": "memory/embeddings.py",
        "lines": "101-168",
        "role": "Shared embedding service that must remain outside the Rust migration."
      }
    ],
    "related_symbols": [
      {
        "symbol": "memories schema",
        "relationship": "READS/WRITES",
        "relevance": "Schema version 14 and memories table are the Rust compatibility boundary."
      },
      {
        "symbol": "policy ranking",
        "relationship": "CALLS",
        "relevance": "Policy ordering and score semantics require parity fixtures."
      },
      {
        "symbol": "ai_gateway scheduled/immediate consolidation",
        "relationship": "CALLS",
        "relevance": "Both trigger paths must continue to use Python LLM consolidation and existing locks."
      },
      {
        "symbol": "memory benchmark",
        "relationship": "TESTS",
        "relevance": "Existing comparison harness supplies the performance baseline."
      }
    ],
    "execution_path": [
      "EmbeddingService produces the query embedding in Python.",
      "The selector chooses Python, Rust, shadow, auto or strict.",
      "The selected read backend loads scoped SQLite/FTS candidates and applies policy/ranking/similarity merge.",
      "Python assembles context and continues to own LLM consolidation.",
      "Promotion executes under the existing Python lock boundary; Rust may own the bounded database transaction.",
      "After a successful commit, Python performs history/cache/compressor side effects exactly once.",
      "Rust package availability and compatibility are validated independently from the main Stella release."
    ],
    "pdg_constraints": [
      {
        "description": "The PDG-enabled index was refreshed successfully; no new statement-level slice was added in this narrow release-naming update, so ordering constraints remain source-verified.",
        "affected_statements": [
          "memory/retrieval_v2.py:485-541",
          "memory/memory_manager.py:99-195",
          "memory/memory_manager.py:342-535"
        ],
        "implementation_consequence": "Keep embedding before backend invocation, keep outer Python locks, and run history/cache/compressor only after a confirmed commit."
      }
    ],
    "architectural_patterns": [
      {
        "pattern": "Python fallback around optional capability",
        "example_location": "memory/retrieval_v2.py:485-541",
        "usage_guidance": "Treat native Rust as optional and preserve the existing Python path as the compatibility baseline."
      },
      {
        "pattern": "Existing benchmark comparison",
        "example_location": "memory/benchmark.py:292-357,471-516",
        "usage_guidance": "Extend the current benchmark rather than inventing an unrelated harness."
      },
      {
        "pattern": "Release layout validation",
        "example_location": "tests/test_release_layout.py",
        "usage_guidance": "Add assertions for the main artifact and the independently built Rust artifact."
      }
    ],
    "files_to_modify": [
      {
        "file": "memory/retrieval_v2.py",
        "symbols": ["retrieve_memories_emb"],
        "intended_change": "Route retrieval candidate work through the selector with Python fallback."
      },
      {
        "file": "memory/memory_manager.py",
        "symbols": ["MemoryManager"],
        "intended_change": "Delegate only bounded promotion transaction work while preserving Python side effects."
      },
      {
        "file": "memory/consolidator.py",
        "symbols": ["MemoryConsolidator"],
        "intended_change": "Select promotion backend after Python LLM consolidation."
      },
      {
        "file": "memory/cache_keys.py",
        "symbols": [],
        "intended_change": "Include backend contract/policy version in relevant cache keys."
      },
      {
        "file": "memory_rust/",
        "symbols": [],
        "intended_change": "Add optional selector, adapter and native Rust package."
      },
      {
        "file": ".github/workflows/release-memory-rust.yml",
        "symbols": [],
        "intended_change": "Build and upload the separate Rust engine zip using the same RELEASE_REF as the Python zip."
      }
    ],
    "tests": [
      {
        "file": "tests/test_retrieval_v2_and_schema.py",
        "scenarios": ["schema 14 database -> Python/Rust read -> identical scoped ordering", "Rust unavailable -> Python result and no import failure"]
      },
      {
        "file": "tests/test_memory_manager_fts_sync.py",
        "scenarios": ["promotion -> base table and FTS remain consistent", "transaction error -> rollback and no post-commit side effect"]
      },
      {
        "file": "tests/test_memory_promotion_deadlock.py",
        "scenarios": ["existing outer group lock -> Rust promotion -> completion without nested-lock deadlock"]
      },
      {
        "file": "tests/test_policy.py",
        "scenarios": ["same candidates -> same policy ordering and score tolerance", "ties/empty candidates -> deterministic output"]
      },
      {
        "file": "tests/test_release_layout.py",
        "scenarios": ["main artifact -> no Rust target/native cache", "Rust artifact -> independent version and importable extension metadata"]
      },
      {
        "file": "tests/test_memory_rust_selector.py",
        "scenarios": ["missing/incompatible extension -> auto fallback", "strict mode -> structured failure", "shadow -> parity report with zero writes"]
      }
    ],
    "verification_commands": [
      "pytest -q tests/test_retrieval_v2_and_schema.py tests/test_memory_manager.py tests/test_memory_manager_v2.py tests/test_memory_manager_fts_sync.py tests/test_memory_promotion_deadlock.py tests/test_consolidator_core.py tests/test_embeddings.py tests/test_policy.py",
      "python -m memory.benchmark --compare",
      "cargo fmt --manifest-path memory_rust/native/Cargo.toml --check",
      "cargo test --manifest-path memory_rust/native/Cargo.toml",
      "cargo clippy --manifest-path memory_rust/native/Cargo.toml --all-targets --all-features -- -D warnings"
    ],
    "risks": [
      "Refreshed graph reports MemoryManager LOW risk with four impacted symbols; preserve public semantics and all direct consolidation/FTS/isolation consumers because source-level transaction compatibility remains sensitive.",
      "Do not migrate EmbeddingService, LLM orchestration, locks, scheduler or compressor in phase one.",
      "Prevent SQLite/FTS divergence, deadlocks, duplicate promotion and duplicate post-commit side effects.",
      "Treat native wheel/platform/schema/API incompatibility as an observable fallback condition.",
      "Accept performance only from benchmarked p50/p95 and fallback-rate comparisons."
    ],
    "assumptions": [
      "The implementation agent verifies the repository's supported Python/Rust toolchain and chooses a compatible maturin/PyO3 configuration.",
      "The exact Rust SQLite strategy is selected after portability and benchmark checks; schema semantics remain unchanged, and the Rust release asset uses the main RELEASE_REF rather than an independent version.",
      "The main release can keep Python memory as the default while the optional Rust distribution is installed separately."
    ],
    "open_questions": [
      "Whether the Rust engine zip should also be mirrored to a package index; the final GitHub Release must contain the separately named Rust zip.",
      "Which OS/Python ABI matrix is required for the first Rust release.",
      "Whether `memory_rust` wrapper code is shipped only in the Rust distribution or split into a small main-package loader.",
      "Whether score parity should use exact values or a documented tolerance for floating-point ranking."
    ],
    "avoid": [
      "Do not delete or rename the existing memory/ Python implementation.",
      "Do not make the Rust package a hard dependency of the main Stella runtime, and do not merge its files into the Python engine zip.",
      "Do not modify the cli Cargo package to host memory Rust.",
      "Do not migrate embedding HTTP, LLM orchestration, scheduler, locks, compressor or schema migration in the first phase.",
      "Do not enable Rust by default before parity, fallback, concurrency and performance gates pass.",
      "Do not overwrite the user's existing changes in cli/Cargo.toml, cli/Cargo.lock or pyproject.toml."
    ]
  }
}
```

## 12. Assumptions and Open Questions

Assumptions:

- [assumed] The project can build an optional PyO3/maturin extension on the supported release platforms; verify toolchain, minimum Rust version and Python ABI matrix before creating the workflow.
- [assumed] A separate `stella-memory-rust` package/build is acceptable, but its final Windows asset must use the main `vX.Y.Z` release version and the exact `Stella-Rust_engine_version-vX.Y.Z-win64.zip` name.
- [assumed] The Rust implementation can use schema 14 without a migration; prove this with fixtures from existing migration and isolation tests.
- [assumed] Existing uncommitted changes in `cli/Cargo.toml`, `cli/Cargo.lock` and `pyproject.toml` are unrelated; preserve and re-read them before editing `pyproject.toml`.

Open questions:

- Decide GitHub Release-only versus a separate package index for Rust artifacts.
- Decide the first supported OS/Python wheel matrix and whether source builds are supported.
- Decide whether wrapper code belongs entirely to the independent distribution or whether a minimal loader remains in the main package.
- Establish exact floating-point score tolerance and whether parity compares scores, ordering, or both.
- Re-run GitNexus analysis with a working runner before implementation if graph-based dependency accounting is required for a merge gate.

Deferred follow-ups:

- Migrating embedding HTTP/client code to Rust.
- Migrating LLM extraction/consolidation or compressor logic.
- Replacing Python async locks/scheduler/session compaction.
- Changing schema or introducing a Rust-only database format.

## 13. Definition of Done

- The original Python memory module remains importable, selectable and passing its current regression suite.
- The Rust backend is a separate optional package with an explicit API/schema compatibility check and no hard dependency from the main release.
- `python`, `rust`, `auto`, `shadow` and `strict` modes have documented and tested semantics; default remains Python until rollout approval.
- Retrieval parity covers scope, policy, similarity merge, ordering, empty/error cases and cache separation.
- Promotion parity covers merge, quota, FTS atomicity, rollback, duplicate invocation, lock ordering and exactly-once post-commit side effects.
- Rust/native tests and Python integration tests pass, and benchmark results show the target p50/p95 improvement without unacceptable fallback or memory regressions.
- Main `vX.Y.Z` releases continue to build the Python memory module and exclude Rust build outputs.
- The same `vX.Y.Z` Release independently produces `Stella-vX.Y.Z-win64.zip` and `Stella-Rust_engine_version-vX.Y.Z-win64.zip`; the two assets have separate build contents but identical version numbers.
- Rollback to `MEMORY_BACKEND=python` is a documented configuration change and does not require uninstalling the Rust package.
