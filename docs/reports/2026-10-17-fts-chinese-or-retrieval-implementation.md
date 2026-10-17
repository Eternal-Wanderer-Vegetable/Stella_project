# 2026-10-17 FTS 中文检索修复（分词去整段 token + MATCH OR + 存量重灌）：实施报告

本次结论：**RAG 的 FTS5 候选路径中文恒 0 命中已修复并有基准实证。根因是 `_segment_text` 的 `\w+` 补词把整段连续中文当成一个 token，而两个查询点把 token 空格连进 MATCH（FTS5 空格 = 隐式 AND），文档不可能含全部 token → 恒 0 行，bm25 从未生效。实施为四个提交：分词重构 + OR 表达式（`80da1b0`）、migrate_v20 存量索引重灌 + native 合同同步升 20（`d042c04`）、flow manifest 重生成（`a180636`）、FTS 命中不窄化候选池 + 基准空间缺陷修复（本报告 §4）。fts 模式基准从 101 例 0 行召回变为 65 行真实命中，全部硬零保持，rule/embedding/hybrid 逐位不回退。**

计划：[2026-10-17-gitnexus-plan-fts-chinese-or-retrieval.md](../plans/2026-10-17-gitnexus-plan-fts-chinese-or-retrieval.md)。证据：[evidence/fts-chinese-retrieval-20261017/](evidence/fts-chinese-retrieval-20261017/)（fts-report/report.json + mode-matrix.json）。

## 1. 实施内容与计划的偏差

| # | 计划原文 | 实际实施 | 偏差原因 |
| --- | --- | --- | --- |
| 1 | 新增 `migrate_v17` | `migrate_v20`（SCHEMA_VERSION 19→20） | 计划编号过时：v17–v19 已在 HEAD 存在（共享授权/副本台账/evidence lineage），新迁移顺延为 v20 |
| 2 | 「native 检索不实现 FTS，parity 不受影响」 | native 查询侧同步修复（`match_expression`）+ 合同号升 20 + .pyd 重编译 | 两处计划断言不成立，见 §3/§4.3 |
| 3 | 「OR 噪声由 bm25 排序 + LIMIT + 下游 Selection 兜底」 | 新增「FTS 命中不窄化候选池」并集语义（Python 双路径 + native 镜像） | 既有兜底不足：FTS 池窄化让旧值/干扰项因竞争者变少穿过 LIMIT/阈值，forbidden 硬零 0→9.1%（§4.1 实证） |
| 4 | （未预见） | 基准 harness 空间缺陷修复：`_populate_fts_index` 的 FTS 行空间默认 `""` 与 memories 行默认 `group_id` 不一致 | 旧代码 AND 恒假时该缺陷被完全掩盖；查询侧修好后显形为 101 例仅 1 行命中 |

计划内事项全部落地：`retriever._tokenize`（中文滑窗 + 非 CJK `\w` 词，保序去重）、`_segment_text` 保持空格连接的索引侧接口、`_match_expression`（引号化防保留字 + OR 连接 + 过滤空段）、两个查询点切换、migrate_v20 沿 v8 的 `rebuild_fts` 手法（失败只降级 warning）、bm25 保持默认列权（rank 指标裁决通过，未调权）。

## 2. 提交分解

1. `80da1b0` fix(memory)：分词重构 + `_match_expression` + 两查询点切换 + `tests/test_fts_chinese_retrieval.py`（分词/MATCH 单元 + 内存 FTS5 双路径中文召回/降级边界）。
2. `d042c04` feat(memory)：`migrate_v20` + SCHEMA_VERSION 20 + `tests/test_migrations.py` v19→v20 夹具回归；native 合同 `MEMORY_SCHEMA_VERSION` 19→20（backend.py + schema.rs + Rust 夹具 stamp）+ `load_fts_candidates` 查询侧 OR 表达式；`benchmark.write_case_db` 的 native 标记改打 `MEMORY_SCHEMA_VERSION`（此前错打 `memory.schema.SCHEMA_VERSION`，两者同为 19 时碰巧不炸）。
3. `a180636` chore(observability)：message-flow manifest 重生成（检索源码体变化，141 节点/拓扑不变）。
4. 本轮第 4 提交：并集语义（`retriever._query_rag_results` / `retrieval_v2._fetch_candidates` / native `load_candidates` 三处）+ 基准空间修复 + 测试更新 + manifest 再重生成。

## 3. native 合同连带升级（计划未预见）

`memory_rust/native/src/schema.rs::ensure_supported` 对库的 `schema_meta.version` **严格相等**放行。SQLite schema 升 20 后旧 .pyd 会拒读新库（auto 模式回退 python 并告警，strict rust 直接拒载），因此：

- `memory_rust/backend.py` 与 schema.rs 的 `MEMORY_SCHEMA_VERSION` 同步 19→20（语义是两套版本号：native 读库门禁 vs SQLite 结构版本，有意数值同步、不可互相替代）；
- 本机 `maturin build --release` 重编译 `_native.pyd` 并验证导出 20（.pyd 为 gitignore 的本地构建产物；发布 wheel 由 release.yml 重编）；
- Rust 侧三个测试夹具 stamp 19→20；`cargo test --release` 22/22。

**勘误**：计划称「native 检索不实现 FTS」。实际 `load_fts_candidates` 存在且查询侧直接绑**原始查询串**——中文整串被 unicode61 当一个 term，与滑窗写入的索引永不相等，native 的 FTS 通道同样长期空转（基准两侧都走新鲜度回退，所以 parity 恰好一直绿）。本批修复 native 查询侧为同语义 OR 表达式（复用写入侧 `fts_text` 分词），否则 Python OR 召回 vs native 原始 MATCH 必然 parity 分叉。

## 4. 并集语义：OR 噪声的实证与兜底修正

### 4.1 只切 OR 表达式不够（实测）

首轮 fts 基准（union 前，空间缺陷已修）：FTS 真实召回 65 行，但 **forbidden 激活 0.0% → 9.1%（4 例），通过率 99.0% → 92.1%（8 例失败）**。失败形态全部同源：FTS 池里只有「恰与查询共享分词片段」的记忆（temporal/conflict 用例的 R_old/V_old 旧值），竞争者变少后穿过 mode_limit 截断与 `MEMORY_SCORE_MIN` 门槛被激活。 Selection 无法按内容区分同文的 R_new/R_old，只能靠候选池里保留完整竞争者把它挤出 limit——这正是 FTS 未命中路径原本会走的池。

### 4.2 修复：「FTS 命中不窄化候选池」

三个实现点同语义：FTS 命中行排前（bm25 序），再并入同一过滤条件下的新鲜度头部（按 id 去重）；池严格成为「修复前生产实际运行的池」的超集，FTS 只增不减。过渡安全性：修复前生产 FTS 恒 0 行 → 实际跑的就是纯新鲜度池，并集后行为是它的严格超集。

### 4.3 修复后基准（101 例）

| 模式 | 通过 | forbidden 激活 | precision | recall | parity（python↔rust） |
| --- | --- | --- | --- | --- | --- |
| rule | 100/101（rank-casual-001，基线记录的既有失败） | 0.0% | 44.3 | 99.0 | 101/101 |
| embedding | 101/101 | 0.0% | 44.7 | 100.0 | 101/101 |
| fts | **100/101，`retrieval_path` 65 行/101 查询（修复前 0 行）** | 0.0% | 44.3 | 99.0 | python 单边（native 无 FTS 评测路径，与旧矩阵同口径） |
| hybrid | 101/101 | 0.0% | 44.7 | 100.0 | python 单边（同上） |

对照冻结基线逐指标零容差（rule 模式）：不漂移（rule 不走 FTS，`MODE_FLAGS` 下 RAG 关闭）。四模式逐位对齐 2026-10-16 旧矩阵，唯一变化是 fts 的命中计量从 0 → 65。bm25 默认列权按计划由 rank 指标裁决：通过，未调权。

## 5. 验收证据

- `python -m pytest tests -q`：**3763 passed / 17 skipped**（并集提交前 3763/17 + 1 flow manifest 门禁失败，随 `d6d20e1` 换 manifest 恢复；冻结基线逐指标零容差门禁在列且通过）。迁移链/native/基准相关 8 文件单独复跑 157 passed。
- `cargo test --release`（memory_rust/native）：22 passed（新增 `match_expression_or_joins_quoted_terms`、`fts_hits_lead_pool_and_do_not_narrow_it`）。
- `python -m ruff check`（改动文件）：通过；`python scripts/check_docs.py`：0 errors。
- flow manifest：随检索源码体变化重生成（`message-flow.dcb0696583be.json`，141 节点/拓扑 2026.10.04 不变），`generate_message_flow.py --check` 过。
- 隔离验证：migrate_v20 用临时库夹具（旧分词索引行 → 迁移后 OR 查询命中 → 幂等 no-op）；生产库（StellaData）未接触。
- `gitnexus impact _segment_text`：risk MEDIUM（与本计划 §4 记录一致）；提交前 `detect_changes --scope all` 结果见提交留痕。

## 6. 已知限制与延后（不在本批修）

- **native `fts_text` 与 Python `_tokenize` 的既有分词分歧**：≤4 字中文段 Python 整体保留、Rust 全滑窗；>8 字段 Python 按 `{2,8}` 非重叠分块、Rust 整段滑窗。跨侧写入的索引行在「查询恰为 ≤4 字段」的角落数字会互有得失（本批修复前两侧各有一套盲区；基准索引固定由 Python 侧写入，矩阵口径不受影响）。对齐留给后续小课题。
- `knowledge/fts.py::segment_text` 仍含整段 CJK token（同款旧分词），但其查询侧本就 OR（`build_match_query`），整段 token 只是无害冗余，检索不受影响。
- 计划 §12 既有延后项不变：>8 字滑窗块间不重叠、单字 CJK 丢弃、FTS 表 `tokenize=` 选项。
- 存量生产库（StellaData）的 v20 重灌随下次启动迁移自动执行（`schema._migrate`），无需手动脚本；**升级期间旧 .pyd + 新库 → native 拒读并回退 python（auto 模式）**，发布 wheel 后恢复——发布说明需带「native wheel 须 ≥ schema 20 合同」。
