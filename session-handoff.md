# Session Handoff

## Current Objective

- FTS 中文检索修复（计划 `docs/plans/2026-10-17-gitnexus-plan-fts-chinese-or-retrieval.md`）已全量实施并验收：分支 `feat/memory-benchmark-suite`，HEAD `88eadeb`，本会话 5 提交 `80da1b0`→`88eadeb`（未推送，待用户审阅合并）。
- 实施报告：[docs/reports/2026-10-17-fts-chinese-or-retrieval-implementation.md](docs/reports/2026-10-17-fts-chinese-or-retrieval-implementation.md)；证据：`docs/reports/evidence/fts-chinese-retrieval-20261017/`（fts-report + mode-matrix）。

## Completed This Session

- `80da1b0`：`retriever._tokenize` 核心分词（去 `\w+` 整段 CJK token）+ `_match_expression`（引号化 + OR 连接 + 过滤空段）+ `_query_rag_results`/`retrieval_v2._query_fts` 两查询点切换 + `tests/test_fts_chinese_retrieval.py`。
- `d042c04`：migrate_v20（调 rebuild_fts 重灌存量索引，v8 既定手法）+ SCHEMA_VERSION 20 + v19→v20 迁移夹具回归；native 合同 `MEMORY_SCHEMA_VERSION` 19→20（backend.py/schema.rs/Rust 夹具）+ native 查询侧 `match_expression`（原直绑原始查询串，FTS 通道同样恒空转）+ 基准 native 标记改打 `MEMORY_SCHEMA_VERSION`。
- `a180636` / `d6d20e1`：flow manifest 两次重生成（cabac92ea347 → dcb0696583be，检索源码体变化，拓扑不变）。
- `d6d20e1`：「FTS 命中不窄化候选池」并集语义（`retriever._query_rag_results`、`retrieval_v2._fetch_candidates`、native `load_candidates` 三处同源）+ 基准 `_populate_fts_index` 空间默认修复（原写空串 vs memories 行 group_id）。
- `88eadeb`：实施报告 + 基准证据落盘。

## Verification Evidence

- fts 模式基准：100/101（唯一失败 = 基线记录的既有 rank-casual-001）、forbidden 激活 0.0%、`retrieval_path` 65 行/101 查询（修复前恒 0 行）。
- 四模式矩阵：rule 100/101（同上既有失败）、embedding 101/101、hybrid 101/101；rule/embedding parity 101/101；逐位对齐 2026-10-16 旧矩阵；冻结基线零容差门禁通过；bm25 默认列权保留（rank 裁决通过）。
- 全量 `python -m pytest tests -q`：**3763 passed / 17 skipped**（Windows Python 3.14）。
- `cargo test --release`（memory_rust/native）：22 passed。
- ruff（改动文件）、`check_docs.py`（0 errors）、`generate_message_flow.py --check` 全过。
- GitNexus：`impact _segment_text` risk MEDIUM（与计划一致）；detect_changes scope=all 代码符号零重叠；`analyze --index-only` 已刷新到 `88eadeb`。

## Blockers / Inherited State

- **工作树遗留（非本会话产物）**：`memory/benchmark/_replay/daily-life/recorded/live-20261017.json` 有未提交修改——上一会话 live 第二轮重录件（progress.md「两轮 live 候选数 7→4」实录），回放门禁测试对其通过（4 passed）；是否提交由用户决定。
- 本机 `memory_rust/_native.pyd` 已重编译到合同 20（gitignore 产物，不随提交）；`_native.pyd.v19.bak` 为升版前备份。

## Next Steps

1. 用户审阅合并 `feat/memory-benchmark-suite`（本批 5 提交 + 分支既有 9 提交）；推送后 hosted CI 应全绿（flow-manifest 已同步）。
2. 生产库 StellaData 下次启动自动跑 v20 迁移重灌 FTS 存量索引；**过渡期注意**：旧 .pyd + schema 20 库 → native 拒读回退 python（auto 模式），发布 wheel 重编后恢复——发布说明需带「native wheel 须 ≥ schema 20 合同」。
3. QQ 真机灰度观察检索命中（中文句子查询应不再恒走新鲜度回退）。
4. 后续小课题候选：native `fts_text` 与 Python `_tokenize` 的既有分词分歧（≤4 字段整体保留 vs 全滑窗、`{2,8}` 分块）对齐；`knowledge/fts.py::segment_text` 同款旧词法清理（其 OR 查询侧使其无害）。
