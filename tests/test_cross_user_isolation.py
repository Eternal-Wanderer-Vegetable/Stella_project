# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""跨用户记忆隔离的回归护栏。


三条合并路径（候选晋升 / 周度压缩 / v2 检索）历史上都只比 type + 内容相似度，
不比 user_id，会把用户 A 的事实并进 B 的记忆。其中前两条会写库且不可恢复。
这三个用例保证以后不能再退回去。
"""
import sqlite3

import pytest

from memory.compressor import MemoryCompressor
from memory.memory_manager import MemoryManager
from memory.retrieval_v2 import _merge_similar

# 两个用户内容完全相同的记忆：任何只看内容的相似度判定都会把它们判为同一条
SAME_CONTENT = "喜欢玩合作类游戏"


def _insert_memory(conn, mem_id, group_id, user_id, content, mem_type="PREFERENCE"):
    conn.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, "
        "importance, confidence, status, confirmation_count, last_accessed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 0.6, 0.8, 'active', 1, '2026-08-12 10:00:00')",
        (mem_id, str(group_id), str(user_id), mem_type, content, content),
    )


@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    """把 memory_manager 与 compressor 的 DB_PATH 指向临时库。


    两个模块都要 patch：MemoryManager 在晋升后会调 get_compressor()，
    而 MemoryCompressor.__init__ 会连接自己模块的 DB_PATH，不 patch 会碰到真实库。
    """
    db = tmp_path / "isolation.db"
    monkeypatch.setattr("memory.memory_manager.DB_PATH", db)
    monkeypatch.setattr("memory.compressor.DB_PATH", db)
    return db


def test_candidate_promotion_does_not_merge_across_users(patched_db):
    """A1：候选晋升时只在同群同用户内找相似记忆。"""
    manager = MemoryManager()  # 构造时建表
    conn = sqlite3.connect(patched_db)
    _insert_memory(conn, "mem-user-1001", 1, 1001, SAME_CONTENT)
    conn.commit()
    cursor = conn.cursor()


    other_user = {
        "group_id": "1",
        "user_id": "1002",
        "type": "PREFERENCE",
        "content": SAME_CONTENT,
    }
    assert manager._find_similar_memory(cursor, other_user) is None, (
        "不同用户的相同内容被判为同一条记忆，会造成归属污染"
    )


    same_user = dict(other_user, user_id="1001")
    assert manager._find_similar_memory(cursor, same_user) == "mem-user-1001"


    other_group = dict(other_user, user_id="1001", group_id="2")
    assert manager._find_similar_memory(cursor, other_group) is None


    conn.close()


def test_compressor_does_not_merge_across_users(patched_db):
    """A2：周度压缩不得跨用户合并（会把一方置 archived，不可恢复）。"""
    compressor = MemoryCompressor()  # 构造时建表
    conn = sqlite3.connect(patched_db)
    _insert_memory(conn, "mem-a", 1, 1001, SAME_CONTENT)
    _insert_memory(conn, "mem-b", 1, 1002, SAME_CONTENT)
    conn.commit()
    cursor = conn.cursor()


    rows = cursor.execute(
        "SELECT id, group_id, user_id, type, content, importance, confidence, "
        "confirmation_count, compressed_at, is_atomized FROM memories "
        "WHERE status = 'active' ORDER BY last_accessed_at DESC"
    ).fetchall()


    assert compressor._merge_duplicate_memories(cursor, rows) == 0
    conn.commit()


    statuses = dict(cursor.execute("SELECT id, status FROM memories").fetchall())
    assert statuses == {"mem-a": "active", "mem-b": "active"}, (
        "跨用户合并把其中一条归档了，数据不可恢复"
    )


    conn.close()


def test_compressor_still_merges_same_user(patched_db):
    """A2 反向：同用户的重复记忆仍然要被合并，避免过度收紧导致去重失效。"""
    compressor = MemoryCompressor()
    conn = sqlite3.connect(patched_db)
    _insert_memory(conn, "mem-a", 1, 1001, SAME_CONTENT)
    _insert_memory(conn, "mem-dup", 1, 1001, SAME_CONTENT)
    conn.commit()
    cursor = conn.cursor()


    rows = cursor.execute(
        "SELECT id, group_id, user_id, type, content, importance, confidence, "
        "confirmation_count, compressed_at, is_atomized FROM memories "
        "WHERE status = 'active' ORDER BY last_accessed_at DESC"
    ).fetchall()


    assert compressor._merge_duplicate_memories(cursor, rows) == 1
    conn.commit()


    archived = cursor.execute(
        "SELECT COUNT(*) FROM memories WHERE status = 'archived'"
    ).fetchone()[0]
    assert archived == 1


    conn.close()


def test_retrieval_merge_similar_keeps_users_separate():
    """A3：v2 检索的同类合并不得跨用户（主动发言取全群记忆，会张冠李戴）。"""
    memories = [
        {"id": "m1", "user_id": "1001", "type": "PREFERENCE", "content": SAME_CONTENT},
        {"id": "m2", "user_id": "1002", "type": "PREFERENCE", "content": SAME_CONTENT},
    ]
    merged = _merge_similar(memories)
    assert len(merged) == 2
    assert {m["user_id"] for m in merged} == {"1001", "1002"}


def test_retrieval_merge_similar_still_merges_same_user():
    """A3 反向：同用户同类型的重复记忆仍然合并。"""
    memories = [
        {"id": "m1", "user_id": "1001", "type": "PREFERENCE", "content": SAME_CONTENT},
        {"id": "m2", "user_id": "1001", "type": "PREFERENCE", "content": SAME_CONTENT},
    ]
    assert len(_merge_similar(memories)) == 1
