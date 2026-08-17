读完了。M2 需要修订，我先给出**完整的影响清单**——这是 M3 的前置（M2.5），必须先做完再动配置系统。

# M2.5：引入 `group_shared_space`

## 术语与默认规则

- **`qq_group_id`**：真实 QQ 群号。当下这场对话的状态按它归属。
- **`group_shared_space`**（下称 space）：共享空间标识。画像、记忆、人格、群级配置按它归属。
- **默认规则**：未被任何空间收录的 QQ 群，自动获得隐式空间 `space = str(qq_group_id)`。单群部署零配置，行为与现在完全一致。

## 表的归属划分（你已确认）

| 表 | 列名 | 归属 |
|---|---|---|
`group_messages` | `group_id` | QQ 群（不改） |
`consolidation_state` | `group_id` | QQ 群（不改） |
`short_term_context` | `group_id` | QQ 群（不改） |
`group_runtime_state` | `group_id` | QQ 群（不改，静音按群） |
`proactive_state` | `group_id` | QQ 群（不改） |
会话压缩状态 | — | QQ 群（不改） |
**`user_profiles`** | `group_id` → **`group_shared_space`** | space |
**`memories`** | `group_id` → **`group_shared_space`** | space |
**`memory_candidates`** | `group_id` → **`group_shared_space`** | space |
**`atomic_facts`** | `group_id` → **`group_shared_space`** | space |
**`memories_fts`** | `group_id` → **`group_shared_space`** | space |
**`memory_traces`** | 保留 `group_id`（QQ 群）+ **新增 `group_shared_space`** | 两者都要——排查时既要知道哪个群触发，也要知道从哪个空间检索 |

## 需要改的文件（12 个）

### 1. 新建 `config/spaces.py`（空间解析）

只读 TOML，放 `config/spaces/*.toml`（你要求配置统一在 config 下）。

- 启动时扫描 `config/spaces/` 下所有 `.toml`，每个文件一个空间，空间名取文件名（不含扩展名）
- 每个文件读 `qq_groups = [...]` 建立 `qq_group_id → space` 的反向映射
- `resolve_space(qq_group_id) -> str`：命中映射返回空间名；否则返回 `str(qq_group_id)`（隐式空间）
- **冲突检测**：同一个 QQ 群出现在多个空间文件里 → error 日志 + 取第一个（按文件名排序，保证确定性）。必须报错，否则记忆会随机落到不同空间
- `list_spaces()` / `qq_groups_of(space)`：供 M5 定时任务遍历用
- 目录不存在或为空时正常工作（全部隐式空间）

### 2. `memory/schema.py`

- `SCHEMA_VERSION = 8`
- docstring 加 v8 说明：为什么区分 QQ 群与 space（当下对话状态 vs 长期认知），以及**为什么不做数据迁移**（同 v7：库是空的，直接重建）
- `MEMORIES_TABLE_DDL`：`group_id` → `group_shared_space`
- `USER_PROFILES_TABLE_DDL`：`group_id` → `group_shared_space`，主键 `(group_shared_space, user_id)`
- `atomic_facts` 的 DDL（在 consolidator 里，见下）同步
- `_INDEXES` 里所有 `memories` / `memory_candidates` / `long_term_memories` 的索引：`group_id` → `group_shared_space`，索引名也相应改（如 `idx_memories_space_user_status`）
- **旧库检测扩展**：`_migrate` 里现有的 `user_profiles` 检测改为「检测 `memories` 或 `user_profiles` 是否仍有 `group_id` 列」，命中则 error 提示重建库

### 3. `memory/consolidator.py`

- `_ensure_common_tables`：`memory_candidates` / `memories` / `atomic_facts` 三个内联 DDL 的列名改掉；索引同步。**建议顺手把 `memories` 的内联 DDL 换成 `create_memories_table(conn)`**，消除手抄两份的漂移（schema.py 的注释本就这么要求）
- `_write_memory_candidates(space, ...)`：签名改为接收 space，所有 SQL 的 `group_id = ?` → `group_shared_space = ?`
- `_write_user_profiles(space, ...)`：同上
- `_write_long_term_memories(space, ...)`：同上
- `consolidate_group(qq_group_id, ...)`：函数入口处 `space = resolve_space(qq_group_id)`，之后：
  - checkpoint / 取消息 / 短期上下文 → 继续用 `qq_group_id`
  - 写候选 / 画像 / 长期记忆 → 传 `space`
- 日志里同时打两个标识（`群 X（空间 Y）`），否则多群共享空间时无法排查

### 4. `memory/memory_manager.py`

- `_ensure_tables` 的两个内联 DDL + 索引改列名（或改为复用 `create_memories_table`）
- `process_new_candidates`：候选行里读的 `row[1]` 从 `group_id` 变 `group_shared_space`，`candidate` dict 的键名同步改
- `_find_similar_memory` / `_resolve_conflicts` / `_enforce_user_quota` / `_create_memory` / `_merge_into_memory`：全部 SQL 与参数改
- **`_enforce_user_quota` 的语义变化要注意**：`MEMORY_USER_QUOTA=25` 现在是「每空间每用户 25 条」，不再是「每 QQ 群 25 条」。多群共享空间时配额实际收紧了。这是符合设计的（同一个人在同一空间就是一份认知），但要在 docstring 里写明

### 5. `memory/retriever.py`

- `_ensure_fts_table`：FTS 虚拟表的 `group_id` 列 → `group_shared_space`
- `_rebuild_fts_index` / `_upsert_fts_record` / `_query_rag_results`：列名与 SQL 改
- `get_group_memories` / `get_user_memories` / `get_related_memories`：**参数名改为 `space`**（这三个是对外入口，改名能让调用方在类型检查时暴露遗漏）
- **FTS 表结构变了，旧索引必须重建**。`_query_rag_results` 里已有「行数不一致就重建」的逻辑，但列名变了会走到 `sqlite3.OperationalError` 分支静默返回空。新库无此问题；为稳妥，`_ensure_fts_table` 可加一次列名探测，发现旧结构就 `DROP TABLE memories_fts` 再建

### 6. `memory/retrieval_v2.py`

- `_row_to_memory` / `_select_columns` / `_fetch_candidates` / `_fetch_candidates_legacy` / `_query_fts`：列名与 SQL 改
- `retrieve_memories(space, user_id, ...)` / `retrieve_memories_emb(...)`：参数改名
- **缓存 key** 里的 `group_id` → space（否则同空间的两个 QQ 群不共享缓存，白跑检索）

### 7. `memory/compressor.py`

- `_ensure_tables` 的 `memories` DDL 改（或复用 `create_memories_table`）
- `run_weekly` / `maybe_compress` 的 SELECT 列表里 `group_id` → `group_shared_space`
- `_merge_duplicate_memories`：合并条件里的 `memory["group_id"]` 改键名
- `_atomize_long_memories` / `_store_atomic_facts`：`atomic_facts` 的写入列改；`subject` 拼接里的 `f"群{group_id}"` 改为空间描述

### 8. `memory/pre_processors.py`

- `_read_stable_profile(space, user_id)`：参数与 SQL 改
- `_build_user_context_v2`：`space = resolve_space(ctx.group_id)`，传给 `_read_stable_profile` 与 `retrieve_memories(_emb)`
- `build_user_context`（v1 回退路径）：画像 SELECT 与三个 retriever 调用都传 space
- `record_message` / `build_context` / `_fetch_recent_tail`：**不改**，继续用 `ctx.group_id`

### 9. `memory/trace.py`

- `_ensure_table` 加 `group_shared_space TEXT` 列
- `record_trace` 增 `space` 关键字参数并写入
- `pipeline.py` 的 `record_trace(...)` 调用处传 space

### 10. `memory/db_cleaner.py`

- `clean_db` 删表列表不变（DELETE 全表，无列名依赖）
- `print_summary` 不变
- `_align_checkpoint` / `trim_group_messages` / `align_all_checkpoints`：**不改**（只碰 `group_messages` 与 `consolidation_state`，都是 QQ 群维度）

### 11. `core/context.py`

`ChatContext` 加一个 `group_shared_space: str = ""` 字段，在 pre-hook 早期填好（`ai_gateway` 构造 ctx 处，或 `record_message` 里）。这样下游不必各自调 `resolve_space`，也便于日志统一带上。

### 12. `scripts/probe_consolidation.py` 与 benchmark

probe 里 `MemoryConsolidator` 的调用与 `_normalize_candidate` 不涉及列名，应该不用改。但 `memory/benchmark/` 下若有构造 `memories` 表的 fixture，列名要同步——这个我没读过，需要你确认或让我读。

---

## 分段建议

改动面大，建议分 4 个 commit：

- **M2.5-1**：`config/spaces.py` + `schema.py` v8 + `core/context.py` 字段（纯新增，不破坏现有行为）
- **M2.5-2**：写入侧 —— `consolidator.py` + `memory_manager.py` + `compressor.py`
- **M2.5-3**：读取侧 —— `retriever.py` + `retrieval_v2.py` + `pre_processors.py` + `trace.py` + `pipeline.py`
- **M2.5-4**：清库重建 + 跑一次 `probe_consolidation.py --positive --two-stage` 确认链路没坏

M2.5-2 和 M2.5-3 之间会有短暂的不一致（写入用新列名、读取还是旧的），所以**这两段之间不要重启跑真实群**。或者你也可以把 2、3 合成一个 commit，代价是单次改动较大。你决定。

---

在动手前有两个待确认：

1. **`spaces/*.toml` 的文件名即空间名**，还是文件内写 `name = "casual"`？我倾向文件名（少一处不一致的可能）
答复：文件名即空间名。
2. **`memory/benchmark/` 下有没有直接建 `memories` 表的 fixture**？如果有我需要读一下，否则 benchmark 会在 M2.5 后失效
答复：未知，需要核查。