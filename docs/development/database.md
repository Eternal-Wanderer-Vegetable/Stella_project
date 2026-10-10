# 数据库

中文 | [English](database.en.md) · [文档总览](../README.md)

```bash
python -m memory.schema --dry-run    # 预览待执行的迁移
python -m memory.schema              # 执行迁移
python -m memory.schema --backup     # 仅备份
```

**迁移原则：Additive Migration** —— 只加字段与索引，绝不删数据。所有 `ALTER` 都经过 `PRAGMA table_info` 探测，幂等可重跑。首次迁移前自动备份为 `stella_memory_backup.db`。

### 加字段的正确做法

1. `memory/schema.py` 的 `SCHEMA_VERSION` +1
2. `_ADDITIVE_COLUMNS` 追加 `(表名, 列名, ALTER 语句)`
3. `_INDEXES` 追加需要的索引
4. **同步更新所有手写该表的 `CREATE TABLE`**

第 4 步是历史踩坑点：`memories` 表的建表语句曾在 `schema.py` / `consolidator.py` / `memory_manager.py` / `compressor.py` 四处各有一份，加 `source_kind` 时漏了 compressor 那份。现在统一走 `schema.create_memories_table(conn)`，新增表也应照此办理。

SQLite 的 `ALTER TABLE ADD COLUMN` **不接受非常量默认值**，`DEFAULT CURRENT_TIMESTAMP` 会失败，需留空由代码写入。

### 改列名/主键的做法

**新规矩（2026-08-27）：`SCHEMA_VERSION` 每 +1，必须同时提交 `memory/migrations.py` 里的
`migrate_vN` 与一个旧库夹具回归测试。禁止再出现「本版不做数据迁移、归档旧库重建」。**

此前 v7（画像分群）与 v8（记忆表改按空间归属）都声明不迁移，理由是「库内数据量很小」。
但公开发布过的 2.x 全是 schema v2/v5（带 `group_id` 列），于是所有存量用户升级即被告知
丢掉全部记忆——这是本项目最贵的一次决策失误。现在 v5 → 最新版全自动。

分工：

| 模块 | 负责 |
|---|---|
| `memory/schema.py` 的 `_migrate()` | 加列 + 建表 + 建索引。幂等、与版本号无关，作为每次迁移的收尾步骤 |
| `memory/migrations.py` | 改结构 + 改数据。每版一个函数、一个事务，成功后才推进 `schema_meta.version` |

写迁移时必须知道的三件事：

1. **逐表判定归属**。v8 的语义变化是归属列的值从「真实 QQ 群号」变成「空间名」，所以
   不能写「凡是 `group_id` 就改名」的脚本。三类表见 `migrations.py` 顶部的常量：
   改名 + 改值的 4 张（`memories` / `memory_candidates` / `atomic_facts` / `user_profiles`，
   外加不能 ALTER、只能 DROP 重建的 `memories_fts`）；**只改值不改名**的
   `long_term_memories`（列名至今仍叫 `group_id`，值早已是空间名）；一个字都不能动的
   6 张按真实群归属的表。
2. **空间名必须与运行时一致**。迁移写进去的名字必须等于 `config.spaces.resolve_space()`
   对该群返回的值，否则检索 `WHERE group_shared_space='casual'` 而行里存着 `'space_1'`
   ——查不到、不报错、不抛异常。判据只能复用 `config/space_map.py`。
3. **事务要真的能回滚 DDL**。Python `sqlite3` 默认只在 DML 前隐式开事务，DDL 走
   autocommit；`run_migrations` 因此把 `isolation_level` 设为 None 自己管 BEGIN/COMMIT。

改主键仍是「建新表 → 拷数据 → 换名」，DDL 从 `schema.py` 的规范常量取（如
`USER_PROFILES_TABLE_DDL`），不要手抄。

### 空间合并

用户把两个群划进同一个 toml 之后，历史记忆还挂在旧空间名下。**不要让用户手搓 UPDATE**：

```bash
python -m deploy space-merge --from space_1,space_2 --to casual --dry-run
python -m deploy space-merge --from space_1,space_2 --to casual
```

它会改写全部按空间归属的表、重建 FTS、更新账本，并处理 `user_profiles` 撞主键
（保留 `interaction_count` 大的那份，冲突进报告）。合并**不可逆**，靠 `origin_group_id`
溯源列与操作前备份兜底。

### 时间处理

`CURRENT_TIMESTAMP` 写入 **UTC**。所有「拿 Python 时间与 DB 时间戳比较」的地方必须走 `memory/timeutil.py`：

```python
from memory.timeutil import parse_db_timestamp, seconds_since, db_timestamp_str
```

直接用 `datetime.now()` 与 DB 时间戳比较会在非 UTC 时区产生固定偏移。这个 bug 曾让 `PROACTIVE_AT_USER_COOLDOWN` 在 UTC+8 下完全失效（永远被判为已过冷却），且只在 CI 的 UTC 环境下才暴露。

SQL 内部的比较（`julianday('now')` vs `julianday(col)`）两侧同为 UTC，无需处理。

### 归档记录

以下是早期重构留下的历史归档（`_deprecated/` 已 gitignore），不是当前升级步骤：

| 文件 | 说明 |
|---|---|
| `legacy_agent_memory.db` | 早期版运行库 |
| `legacy_agent_memory_2026.db` | v2 schema 升级前 |
| `legacy_agent_memory_pre_v4.db` | 两层过滤重构（Gate 1 三档 / 候选强化 / 配额）之前 |

当前升级通过版本化迁移保留已有数据；仅在数据根确实没有库时才初始化新库。
实际库路径是 `STELLA_HOME/memory/agent_memory.db`，不要为升级删除或搬走生产库。

> 封存旧库时**连 `stella_memory_backup.db` 一起移走**。`backup_database()` 见备份已存在即跳过，留着它会导致新库将来迁移时不生成新备份——一个看起来有备份、实际备份错了的状态。
>
> 每次版本化迁移另外会写一份 `agent_memory.db.pre-vN-<时间戳>.bak`（`schema.backup_snapshot`），
> 它才是「这次迁移前的状态」；`stella_memory_backup.db` 是「有史以来第一份原始库」。
