# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""``deploy space-merge`` 的单元测试（memory/space_merge.py）。

这条命令替代的是过去要用户手搓的六条 UPDATE + 重建 FTS。所以测试重点是
「一个都不能漏」：每张按空间归属的表、FTS 索引、账本，以及画像撞主键时的取舍。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from config import space_map
from memory import schema, space_merge


def _build_db(path: Path) -> None:
    """搭一个当前 schema 的库：两个自动空间，各有记忆、候选、事实与画像。"""
    conn = sqlite3.connect(path)
    try:
        conn.execute(schema.MEMORIES_TABLE_DDL)
        conn.execute(schema.MEMORY_CANDIDATES_TABLE_DDL)
        conn.execute(schema.ATOMIC_FACTS_TABLE_DDL)
        conn.execute(schema.USER_PROFILES_TABLE_DDL)
        conn.execute(
            "CREATE TABLE long_term_memories (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " group_id TEXT, user_id TEXT, summary TEXT)"
        )
        conn.executemany(
            "INSERT INTO memories (id, group_shared_space, user_id, content, status,"
            " origin_group_id) VALUES (?,?,?,?,?,?)",
            [
                ("m1", "space_1", "u1", "喜欢猫", "active", "1001"),
                ("m2", "space_2", "u1", "在做后端", "active", "2002"),
                ("m3", "space_9", "u2", "别的空间，不该被动", "active", "3003"),
            ],
        )
        conn.execute(
            "INSERT INTO memory_candidates (id, group_shared_space, user_id, content, status)"
            " VALUES ('c1','space_1','u1','候选','NEW')"
        )
        conn.execute(
            "INSERT INTO atomic_facts (id, memory_id, group_shared_space, subject, predicate,"
            " object) VALUES ('f1','m1','space_2','u1','喜欢','猫')"
        )
        conn.executemany(
            "INSERT INTO user_profiles (group_shared_space, user_id, nickname,"
            " personality_traits, interaction_count) VALUES (?,?,?,?,?)",
            [
                ("space_1", "u1", "阿一", "话多", 30),
                ("space_2", "u1", "阿一", "在技术群很安静", 5),
                ("space_2", "u2", "阿二", "只在这个空间", 7),
            ],
        )
        conn.execute(
            "INSERT INTO long_term_memories (group_id, user_id, summary)"
            " VALUES ('space_1','u1','旧式长期记忆')"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "agent_memory.db"
    _build_db(path)
    ledger = tmp_path / space_map.LEDGER_FILENAME
    ledger.write_text(json.dumps({"1001": "space_1", "2002": "space_2"}), encoding="utf-8")
    return path


def _rows(path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_every_owned_table_is_rewritten(db):
    """六张按空间归属的表一个都不能漏——漏一张就是静默丢记忆。"""
    report = space_merge.merge_spaces(["space_1", "space_2"], "casual", db_path=db)

    assert report.error is None
    assert set(_rows(db, "SELECT DISTINCT group_shared_space FROM memories")) == {
        ("casual",),
        ("space_9",),  # 不在 --from 里的空间不受影响
    }
    assert _rows(db, "SELECT group_shared_space FROM memory_candidates") == [("casual",)]
    assert _rows(db, "SELECT group_shared_space FROM atomic_facts") == [("casual",)]
    # long_term_memories 列名仍是 group_id，但值也要跟着改
    assert _rows(db, "SELECT group_id FROM long_term_memories") == [("casual",)]
    assert set(report.moved) >= {
        "memories",
        "memory_candidates",
        "atomic_facts",
        "user_profiles",
        "long_term_memories",
    }


def test_profile_conflict_keeps_more_interactive_one(db):
    """同一个人在两个源空间都有画像 → 保留互动次数多的那份，并写进报告。"""
    report = space_merge.merge_spaces(["space_1", "space_2"], "casual", db_path=db)

    rows = _rows(db, "SELECT user_id, personality_traits, interaction_count FROM user_profiles")
    profiles = {r[0]: (r[1], r[2]) for r in rows}
    assert profiles["u1"] == ("话多", 30)  # space_1 那份（互动 30 次）胜出
    assert profiles["u2"][0] == "只在这个空间"  # 没冲突的照常搬
    assert any("用户 u1" in c and "space_1" in c for c in report.conflicts)
    assert "不可逆" in report.to_markdown()


def test_ledger_follows_the_merge(db, tmp_path):
    """账本必须跟着改，否则下次启动 resolve_space 又把群解析回旧空间名。"""
    space_merge.merge_spaces(["space_1", "space_2"], "casual", db_path=db)

    ledger = json.loads((tmp_path / space_map.LEDGER_FILENAME).read_text(encoding="utf-8"))
    assert ledger == {"1001": "casual", "2002": "casual"}


def test_origin_group_id_survives_so_merge_can_be_undone(db):
    """合并不可逆，但溯源列要留住——那是唯一能拆回来的依据。"""
    space_merge.merge_spaces(["space_1", "space_2"], "casual", db_path=db)

    origins = dict(_rows(db, "SELECT id, origin_group_id FROM memories"))
    assert origins["m1"] == "1001"
    assert origins["m2"] == "2002"


def test_fts_index_rebuilt(db):
    """FTS 索引跟着重建：行数与 active 记忆对齐，空间名也换成新的。"""
    space_merge.merge_spaces(["space_1", "space_2"], "casual", db_path=db)

    indexed = _rows(db, "SELECT COUNT(*) FROM memories_fts")[0][0]
    active = _rows(db, "SELECT COUNT(*) FROM memories WHERE status='active'")[0][0]
    assert indexed == active
    assert _rows(db, "SELECT group_shared_space FROM memories_fts WHERE mem_id='m1'") == [
        ("casual",)
    ]


def test_dry_run_changes_nothing(db, tmp_path):
    """预演跑的是真逻辑再回滚，所以行数准确、但库与账本一个字都不动。"""
    before = db.read_bytes()

    report = space_merge.merge_spaces(
        ["space_1", "space_2"], "casual", db_path=db, dry_run=True
    )

    assert report.error is None
    assert report.moved["memories"] == 2  # 预览里就能看到会改几行
    assert db.read_bytes() == before
    ledger = json.loads((tmp_path / space_map.LEDGER_FILENAME).read_text(encoding="utf-8"))
    assert ledger == {"1001": "space_1", "2002": "space_2"}


def test_target_cannot_be_a_source(db):
    """--to 出现在 --from 里是明显的手误，直接拒绝。"""
    report = space_merge.merge_spaces(["space_1", "casual"], "casual", db_path=db)
    assert report.error is not None and "不能同时出现" in report.error


def test_backup_is_taken_before_merge(db):
    """合并前必须备份：这是唯一能核对「丢掉的那份画像写了什么」的东西。"""
    report = space_merge.merge_spaces(["space_1"], "casual", db_path=db)
    assert report.backup_path is not None
    assert report.backup_path.is_file()
    assert "pre-merge" in report.backup_path.name

