# Database

[中文](database.md) | English · [Documentation](../README.en.md)

```bash
python -m memory.schema --dry-run    # Preview pending migrations
python -m memory.schema              # Run migrations
python -m memory.schema --backup     # Back up only
```

**Migration principle: Additive Migration** -- only add fields and indexes; never delete data. Every `ALTER` is preceded by a `PRAGMA table_info` check and is idempotent and rerunnable. Before the first migration, an automatic backup is created as `stella_memory_backup.db`.

### Correct Way to Add a Column

1. Increment `SCHEMA_VERSION` in `memory/schema.py` by 1
2. Append `(table name, column name, ALTER statement)` to `_ADDITIVE_COLUMNS`
3. Append required indexes to `_INDEXES`
4. **Synchronously update every hand-written `CREATE TABLE` for that table**

Step 4 is a historical pitfall: the `memories` table creation statement once existed separately in `schema.py` / `consolidator.py` / `memory_manager.py` / `compressor.py`, and the `compressor` copy was missed when `source_kind` was added. All code now uses `schema.create_memories_table(conn)`; new tables should follow the same practice.

SQLite's `ALTER TABLE ADD COLUMN` **does not accept a non-constant default**. `DEFAULT CURRENT_TIMESTAMP` fails, so leave the value empty and have the code write it.

### How to Change a Column Name / Primary Key

**New rule (2026-08-27): every increment of `SCHEMA_VERSION` must also include a `migrate_vN` in `memory/migrations.py` and a regression test using an old-database fixture. Never again use "no data migration in this release; archive the old database and rebuild".**

Previously, v7 (profile grouping) and v8 (changing the memory table to use space ownership) both declared that they would not migrate, on the grounds that "the amount of data in the database is small".
However, every publicly released 2.x version used schema v2/v5 (with a `group_id` column), so upgrading existing users meant telling them that all their memories would be lost. This was the most expensive decision mistake in this project. v5 -> the latest version is now fully automatic.

Division of responsibility:

| Module | Responsibility |
|---|---|
| `_migrate()` in `memory/schema.py` | Add columns + create tables + create indexes. Idempotent and independent of the version number; runs as the final step of every migration |
| `memory/migrations.py` | Change structure + transform data. One function and one transaction per version; advance `schema_meta.version` only after success |

Three things you must know when writing a migration:

1. **Determine ownership table by table**. The semantic change in v8 was that the ownership column's value changed from the "real QQ group number" to the "space name", so do not write a script that says "rename every `group_id`". The three table categories are defined by constants at the top of `migrations.py: 4 tables whose names and values change (`memories` / `memory_candidates` / `atomic_facts` / `user_profiles`, plus `memories_fts`, which cannot be ALTERed and must be dropped and rebuilt); `long_term_memories`, whose value changes but whose name does not (the column is still called `group_id`, while its value has long been a space name); and 6 tables whose real-group ownership must not be changed at all.
2. **Space names must match the runtime**. Names written by the migration must equal the value returned for that group by `config.spaces.resolve_space()`. Otherwise retrieval asks `WHERE group_shared_space='casual'` while the row contains `'space_1'` -- no results, no error, and no exception. The only valid criterion is the one reused from `config/space_map.py`.
3. **The transaction must really roll back DDL**. Python `sqlite3` implicitly starts a transaction only before DML by default, while DDL uses autocommit; therefore `run_migrations` sets `isolation_level` to None and manages BEGIN/COMMIT itself.

Changing a primary key still means "create a new table -> copy the data -> rename it". Take the DDL from the canonical constants in `schema.py` (such as `USER_PROFILES_TABLE_DDL`); do not copy it by hand.

### Space Merging

After a user assigns two groups to the same toml, historical memories are still attached to the old space names. **Do not make users type UPDATE statements by hand**:

```bash
python -m deploy space-merge --from space_1,space_2 --to casual --dry-run
python -m deploy space-merge --from space_1,space_2 --to casual
```

It rewrites all tables owned by space, rebuilds FTS, updates the ledger, and handles `user_profiles` primary-key collisions (keeps the copy with the larger `interaction_count`; conflicts go into the report). Merging is **irreversible**; the `origin_group_id` provenance column and the backup made before the operation are the fallback.

### Time Handling

`CURRENT_TIMESTAMP` writes **UTC**. Every place that compares a Python time with a DB timestamp must use `memory/timeutil.py`:

```python
from memory.timeutil import parse_db_timestamp, seconds_since, db_timestamp_str
```

Comparing a DB timestamp directly with `datetime.now()` produces a fixed offset outside the UTC time zone. This bug once made `PROACTIVE_AT_USER_COOLDOWN` completely ineffective in UTC+8 (it was always judged to have passed its cooldown), and it surfaced only in CI's UTC environment.

Comparisons inside SQL (`julianday('now')` versus `julianday(col)`) use UTC on both sides and need no handling.

### Archived Records

These archives in `_deprecated/` (gitignored) record early refactors; they are not current upgrade instructions:

| File | Description |
|---|---|
| `legacy_agent_memory.db` | Early-version runtime database |
| `legacy_agent_memory_2026.db` | Before the v2 schema upgrade |
| `legacy_agent_memory_pre_v4.db` | Before the two-layer filtering refactor (three Gate 1 tiers / candidate reinforcement / quota) |

Current upgrades preserve existing data through versioned migrations; a new database is initialized only when none exists. The database is `STELLA_HOME/memory/agent_memory.db`. Do not delete or move production data to upgrade.

> When archiving an old database, **move `stella_memory_backup.db` along with it**. `backup_database()` skips the backup when one already exists; leaving it behind means a future migration of the new database will not create a new backup -- a state that looks backed up but is backed up incorrectly.
>
> Every versioned migration also writes `agent_memory.db.pre-vN-<timestamp>.bak` (`schema.backup_snapshot`); that is the "state before this migration". `stella_memory_backup.db` is the "first original database ever".
