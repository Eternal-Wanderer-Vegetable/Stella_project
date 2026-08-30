# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""旧库迁移的回归测试（memory/migrations.py）。

夹具是**按 2.2.0 真实形状**手工搭出来的 schema v5 库：``group_id`` 列、
``user_profiles`` 主键是 ``user_id`` 单列、``memories_fts`` 是旧结构。
公开发布过的版本只有 schema v5（2.2.0）与 v9（3.0.0），所以这两条起点必须常绿。

新规矩（见 memory/schema.py 模块 docstring）：``SCHEMA_VERSION`` 每 +1 都要在这里
加一个起点用例，禁止再出现「本版不做数据迁移」。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from memory import migrations, schema

# 2.2.0 的表形状（只保留迁移关心的列，其余由 additive 步骤补齐）
_LEGACY_DDL = (
    "CREATE TABLE memories (id TEXT PRIMARY KEY, group_id TEXT, user_id TEXT, type TEXT,"
    " content TEXT, importance REAL, confidence REAL, status TEXT,"
    " created_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE memory_candidates (id TEXT PRIMARY KEY, group_id TEXT, user_id TEXT,"
    " type TEXT, content TEXT, status TEXT)",
    "CREATE TABLE atomic_facts (id TEXT PRIMARY KEY, memory_id TEXT, group_id TEXT,"
    " subject TEXT, predicate TEXT, object TEXT, confidence REAL)",
    # 旧的全局画像：主键只有 user_id，没有任何群/空间维度
    "CREATE TABLE user_profiles (user_id TEXT PRIMARY KEY, nickname TEXT,"
    " personality_traits TEXT, agent_attitude TEXT, interaction_count INTEGER DEFAULT 0,"
    " updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE long_term_memories (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT,"
    " user_id TEXT, summary TEXT, importance REAL, access_count INTEGER DEFAULT 0,"
    " last_accessed_at DATETIME)",
    "CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT,"
    " user_id TEXT, content TEXT, source_kind TEXT DEFAULT 'PASSIVE',"
    " timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE consolidation_state (group_id TEXT PRIMARY KEY, last_message_id INTEGER)",
    "CREATE TABLE memory_traces (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT,"
    " user_id TEXT, message TEXT)",
    "CREATE VIRTUAL TABLE memories_fts USING fts5(mem_id UNINDEXED, content,"
    " group_id UNINDEXED, user_id UNINDEXED)",
)

# 群 1001 与 2002 是「已知群」；9999 模拟用户已退群（孤儿行）
KNOWN_GROUPS = (1001, 2002)


def build_legacy_v5_db(path: Path) -> None:
    """搭一个 schema v5 的旧库，带足以验证每条迁移规则的数据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        for ddl in _LEGACY_DDL:
            conn.execute(ddl)
        conn.executemany(
            "INSERT INTO memories (id, group_id, user_id, type, content, status) VALUES (?,?,?,?,?,?)",
            [
                ("m1", "1001", "u1", "FACT", "喜欢猫", "active"),
                ("m2", "1001", "u2", "FACT", "住在杭州", "active"),
                ("m3", "2002", "u1", "FACT", "在做后端", "active"),
                ("m4", "9999", "u3", "FACT", "退群用户的记忆", "active"),
                ("m5", None, "u3", "FACT", "归属为空的记忆", "active"),
            ],
        )
        conn.executemany(
            "INSERT INTO memory_candidates (id, group_id, user_id, type, content, status) VALUES (?,?,?,?,?,?)",
            [("c1", "1001", "u1", "FACT", "候选一", "PENDING")],
        )
        conn.executemany(
            "INSERT INTO atomic_facts (id, memory_id, group_id, subject, predicate, object) VALUES (?,?,?,?,?,?)",
            [("f1", "m1", "1001", "u1", "喜欢", "猫")],
        )
        conn.executemany(
            "INSERT INTO user_profiles (user_id, nickname, personality_traits, interaction_count)"
            " VALUES (?,?,?,?)",
            [("u1", "阿一", "话多", 12), ("u2", "阿二", "安静", 3), ("u404", "幽灵", "无消息", 1)],
        )
        conn.executemany(
            "INSERT INTO long_term_memories (group_id, user_id, summary, importance) VALUES (?,?,?,?)",
            [("1001", "u1", "旧式长期记忆", 0.5)],
        )
        # u1 在 1001 有 3 条、在 2002 有 1 条 → 主空间是 1001 对应的空间
        conn.executemany(
            "INSERT INTO group_messages (group_id, user_id, content) VALUES (?,?,?)",
            [
                ("1001", "u1", "a"),
                ("1001", "u1", "b"),
                ("1001", "u1", "c"),
                ("2002", "u1", "d"),
                ("2002", "u2", "e"),
            ],
        )
        conn.execute("INSERT INTO consolidation_state (group_id, last_message_id) VALUES ('1001', 5)")
        conn.execute("INSERT INTO memory_traces (group_id, user_id, message) VALUES ('1001','u1','t')")
        conn.execute(
            "INSERT INTO memories_fts (mem_id, content, group_id, user_id) VALUES ('m1','喜欢 猫','1001','u1')"
        )
        conn.execute(
            "CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER,"
            " updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute("INSERT INTO schema_meta (k, version) VALUES ('version', 5)")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def legacy_db(tmp_path):
    """旧库 + 指向临时目录的迁移上下文（不碰仓库真实配置）。"""
    path = tmp_path / "agent_memory.db"
    build_legacy_v5_db(path)
    ctx = migrations.context_from_paths(
        tmp_path / "spaces", tmp_path / ".space_assignments.json", KNOWN_GROUPS
    )
    return path, ctx


def _columns(path: Path, table: str) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    finally:
        conn.close()


def _rows(path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_v5_to_latest_renames_and_rewrites_values(legacy_db):
    """v5 → 最新：归属列改名 + 值从群号重写为空间名，校验全部通过。"""
    path, ctx = legacy_db
    report = schema.migrate_to_latest(path, ctx)

    assert report.error is None
    assert report.problems == [], report.problems
    assert report.from_version == 5
    assert report.to_version == schema.SCHEMA_VERSION

    for table in ("memories", "memory_candidates", "atomic_facts", "user_profiles"):
        cols = _columns(path, table)
        assert "group_shared_space" in cols, table
        assert "group_id" not in cols, table
    # 群号 → space_N（1001 先出现，拿 space_1）
    assert _rows(path, "SELECT group_shared_space FROM memories WHERE id='m1'") == [("space_1",)]
    assert _rows(path, "SELECT group_shared_space FROM memories WHERE id='m3'") == [("space_2",)]


def test_orphan_rows_go_to_legacy_space(legacy_db):
    """已退群 / 归属为空的行进 legacy_* 空间，永不删除。"""
    path, ctx = legacy_db
    schema.migrate_to_latest(path, ctx)
    assert _rows(path, "SELECT group_shared_space FROM memories WHERE id='m4'") == [
        ("legacy_9999",)
    ]
    assert _rows(path, "SELECT group_shared_space FROM memories WHERE id='m5'") == [
        ("legacy_unknown",)
    ]
    # 5 条记忆一条不少
    assert _rows(path, "SELECT COUNT(*) FROM memories") == [(5,)]


def test_group_scoped_tables_untouched(legacy_db):
    """按真实 QQ 群归属的表一个字都不动——混群会让 Bot 在 A 群回应 B 群。"""
    path, ctx = legacy_db
    schema.migrate_to_latest(path, ctx)
    for table in ("group_messages", "consolidation_state"):
        cols = _columns(path, table)
        assert "group_id" in cols, table
        assert "group_shared_space" not in cols, table
    assert _rows(path, "SELECT DISTINCT group_id FROM group_messages ORDER BY group_id") == [
        ("1001",),
        ("2002",),
    ]


def test_long_term_memories_value_only(legacy_db):
    """long_term_memories 的列名保持 group_id（值才是空间名），改名会写坏它。"""
    path, ctx = legacy_db
    schema.migrate_to_latest(path, ctx)
    cols = _columns(path, "long_term_memories")
    assert "group_id" in cols
    assert "group_shared_space" not in cols
    assert _rows(path, "SELECT group_id FROM long_term_memories") == [("space_1",)]


def test_legacy_global_profile_assigned_to_dominant_space(legacy_db):
    """旧的全局画像按 C3 归入消息量最大的空间；查不到消息的归 legacy_unknown。"""
    path, ctx = legacy_db
    report = schema.migrate_to_latest(path, ctx)

    rows = dict(_rows(path, "SELECT user_id, group_shared_space FROM user_profiles"))
    assert rows["u1"] == "space_1"  # 1001 有 3 条 > 2002 的 1 条
    assert rows["u2"] == "space_2"  # 只在 2002 说过话
    assert rows["u404"] == "legacy_unknown"  # 没有任何消息
    # 主键已改为 (group_shared_space, user_id)
    pk = [
        r[5]
        for r in _rows(path, "PRAGMA table_info(user_profiles)")
        if r[1] in ("group_shared_space", "user_id")
    ]
    assert sorted(pk) == [1, 2]
    assert any("归入 space_1" in note for step in report.steps for note in step.notes)


def test_origin_group_id_backfilled(legacy_db):
    """溯源列回填真实群号——合并空间之后还能拆回来。"""
    path, ctx = legacy_db
    schema.migrate_to_latest(path, ctx)
    rows = dict(_rows(path, "SELECT id, origin_group_id FROM memories"))
    assert rows["m1"] == "1001"
    assert rows["m3"] == "2002"
    assert rows["m4"] == "9999"  # 退群的群号也要留着
    assert rows["m5"] is None  # 本来就没有归属，无从回填
    assert _rows(path, "SELECT origin_group_id FROM atomic_facts") == [("1001",)]


def test_fts_rebuilt_with_new_column(legacy_db):
    """memories_fts 不能 ALTER，只能 DROP 重建；重建后列名与行数都要对上。"""
    path, ctx = legacy_db
    schema.migrate_to_latest(path, ctx)
    cols = _columns(path, "memories_fts")
    assert "group_shared_space" in cols
    assert "group_id" not in cols
    indexed = _rows(path, "SELECT COUNT(*) FROM memories_fts")[0][0]
    active = _rows(path, "SELECT COUNT(*) FROM memories WHERE status='active'")[0][0]
    assert indexed == active
    # 空间名跟着记忆一起进索引，否则按空间过滤会漏召回
    assert _rows(path, "SELECT group_shared_space FROM memories_fts WHERE mem_id='m1'") == [
        ("space_1",)
    ]


def test_ledger_written_together_with_db(legacy_db, tmp_path):
    """账本必须与 DB 一起写成，否则下次启动重新编号、记忆全挂在旧名下。"""
    path, ctx = legacy_db
    schema.migrate_to_latest(path, ctx)
    ledger = tmp_path / ".space_assignments.json"
    assert ledger.exists()
    import json

    assert json.loads(ledger.read_text(encoding="utf-8")) == {
        "1001": "space_1",
        "2002": "space_2",
    }


def test_migration_is_idempotent(legacy_db):
    """再跑一次不改任何东西（版本已到位），也不该报校验问题。"""
    path, ctx = legacy_db
    schema.migrate_to_latest(path, ctx)
    before = _rows(path, "SELECT id, group_shared_space, origin_group_id FROM memories ORDER BY id")

    second = schema.migrate_to_latest(path, ctx)
    assert second.from_version == schema.SCHEMA_VERSION
    assert second.steps == []
    assert second.problems == []
    assert (
        _rows(path, "SELECT id, group_shared_space, origin_group_id FROM memories ORDER BY id")
        == before
    )


def test_ensure_v2_schema_migrates_legacy_db_on_startup(legacy_db, monkeypatch):
    """运行时入口也会自动迁移旧库——用户不再需要手工归档重建。"""
    path, ctx = legacy_db
    monkeypatch.setattr(migrations, "runtime_context", lambda: ctx)
    assert schema.ensure_v2_schema(path) is True
    assert "group_shared_space" in _columns(path, "memories")
    assert schema.ensure_v2_schema(path) is False  # 第二次没有变更


def test_dry_run_leaves_original_untouched(legacy_db, tmp_path):
    """--dry-run 在库的副本上真跑一遍（含校验），原库与账本一个字都不动。"""
    path, _ = legacy_db
    ctx = migrations.context_from_paths(
        tmp_path / "spaces", tmp_path / ".space_assignments.json", KNOWN_GROUPS, persist=False
    )
    before = path.read_bytes()

    report = schema.migrate_to_latest(path, ctx, dry_run=True)

    assert report.dry_run is True
    assert report.error is None
    assert report.problems == []
    assert report.changed_rows > 0  # 预览里能看到会改多少行
    assert path.read_bytes() == before
    assert not (tmp_path / ".space_assignments.json").exists()
    assert "group_id" in _columns(path, "memories")


def test_failed_step_rolls_back_whole_level(legacy_db, monkeypatch):
    """某一级失败 → 整级回滚，库停留在迁移前，且报告里说清原因。"""
    path, ctx = legacy_db

    def boom(conn, ctx):
        conn.execute("UPDATE memories SET content = 'ruined'")
        raise RuntimeError("模拟迁移中途失败")

    monkeypatch.setitem(migrations.MIGRATIONS, 8, boom)
    report = schema.migrate_to_latest(path, ctx)

    assert report.error is not None
    assert "模拟迁移中途失败" in report.error
    # 失败那一级整级回滚，数据没被写坏；已成功的低版本保持提交（各级独立有效）
    assert _rows(path, "SELECT content FROM memories WHERE id='m1'") == [("喜欢猫",)]
    assert "group_id" in _columns(path, "memories")
    conn = sqlite3.connect(path)
    try:
        version = conn.execute("SELECT version FROM schema_meta WHERE k='version'").fetchone()[0]
    finally:
        conn.close()
    assert version == 7  # v7 成功并提交，v8 回滚，不会留下「改了一半又标成最新」的库
    # 迁移前的备份仍在（用户可以自己拿回去）
    assert list(path.parent.glob("*.pre-v*.bak"))


def test_v9_db_only_gains_origin_column(tmp_path):
    """3.0.0 用户（schema v9）升级：只加溯源列，不动数据。"""
    path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(schema.MEMORIES_TABLE_DDL.replace("origin_group_id TEXT,", ""))
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, content, status)"
            " VALUES ('m1','casual','u1','已经是空间名','active')"
        )
        conn.execute(
            "CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER,"
            " updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute("INSERT INTO schema_meta (k, version) VALUES ('version', 9)")
        conn.commit()
    finally:
        conn.close()
    spaces_dir = tmp_path / "spaces"
    spaces_dir.mkdir()
    (spaces_dir / "casual.toml").write_text("qq_groups = [1001]\n", encoding="utf-8")
    ctx = migrations.context_from_paths(spaces_dir, tmp_path / "ledger.json", (1001,))

    report = schema.migrate_to_latest(path, ctx)

    assert report.error is None
    assert report.problems == []
    assert "origin_group_id" in _columns(path, "memories")
    # 已经是空间名的值不会被再映射一次
    assert _rows(path, "SELECT group_shared_space FROM memories") == [("casual",)]


def test_unknown_space_name_is_reported(tmp_path):
    """库里的空间名在配置/账本里都找不到 → 校验报出来（否则运行时静默查不到）。"""
    path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(schema.MEMORIES_TABLE_DDL)
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, content, status)"
            " VALUES ('m1','已删除的空间','u1','孤儿','active')"
        )
        conn.commit()
    finally:
        conn.close()
    ctx = migrations.context_from_paths(tmp_path / "spaces", tmp_path / "ledger.json", ())

    report = schema.migrate_to_latest(path, ctx)

    assert any("已删除的空间" in problem for problem in report.problems)








def test_v10_db_only_gains_the_usage_table(tmp_path):
    """schema v10 旧库升级：只多出 ``llm_usage_daily``，记忆数据一行不动。

    ``SCHEMA_VERSION`` 每 +1 都要配一个旧库夹具回归测试（memory/schema.py 的硬规矩）——
    v11 加的是新表，最容易出的错是「顺手动了别的表」或「行数不守恒」。
    """
    path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute(schema.MEMORIES_TABLE_DDL)
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, content, status)"
            " VALUES ('m1','casual','u1','喜欢猫','active')"
        )
        conn.execute(
            "CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER,"
            " updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute("INSERT INTO schema_meta (k, version) VALUES ('version', 10)")
        conn.commit()
    finally:
        conn.close()
    spaces_dir = tmp_path / "spaces"
    spaces_dir.mkdir()
    (spaces_dir / "casual.toml").write_text("qq_groups = [1001]\n", encoding="utf-8")
    ctx = migrations.context_from_paths(spaces_dir, tmp_path / "ledger.json", (1001,))

    report = schema.migrate_to_latest(path, ctx)

    assert report.error is None
    assert report.problems == []
    assert report.to_version == schema.SCHEMA_VERSION == 11
    # 记忆数据原样保留
    assert _rows(path, "SELECT content, group_shared_space FROM memories") == [
        ("喜欢猫", "casual")
    ]
    # 新表建好了，且是空的（历史用量无从追溯）
    assert _rows(path, "SELECT COUNT(*) FROM llm_usage_daily") == [(0,)]
    cols = _columns(path, "llm_usage_daily")
    for col in ("date", "role", "slot", "model", "kind", "calls", "failures",
                "truncated", "prompt_tokens", "completion_tokens", "cached_tokens"):
        assert col in cols


def test_v11_usage_table_upserts_on_its_composite_key(tmp_path):
    """回归：(date, role, slot, model) 必须是主键，否则日账会插出重复行。"""
    path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(path)
    try:
        schema.create_llm_usage_daily_table(conn)
        for _ in range(2):
            conn.execute(
                "INSERT INTO llm_usage_daily (date, role, slot, model, kind, calls) "
                "VALUES ('2026-08-30','CONSOLIDATION','ONLINE_MEMORY','m','online',1) "
                "ON CONFLICT(date, role, slot, model) DO UPDATE SET calls = calls + 1"
            )
        conn.commit()
    finally:
        conn.close()
    assert _rows(path, "SELECT calls FROM llm_usage_daily") == [(2,)]
