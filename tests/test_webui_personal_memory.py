# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""个人记忆管理服务测试（计划 §6.9）：服务端只认 PERSON 行、删除推进缓存版本。"""

from __future__ import annotations

import sqlite3

import pytest

from webui.services import personal_memory as service


@pytest.fixture()
def mem_db(tmp_path, monkeypatch):
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(service, "DB_PATH", db)
    conn = sqlite3.connect(db)
    from memory.schema import MEMORIES_TABLE_DDL

    conn.execute(MEMORIES_TABLE_DDL)
    conn.execute(
        "CREATE TABLE memory_scope_versions (scope_key TEXT PRIMARY KEY,"
        " version INTEGER NOT NULL DEFAULT 1, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.executemany(
        "INSERT INTO memories (id, group_shared_space, user_id, type, content,"
        " importance, confidence, status, owner_type, owner_key, subject_key,"
        " audience, source_conversation_key, fact_key)"
        " VALUES (?,?,?,?,?,?,?, 'active', ?,?,?,?,?,'')",
        [
            ("p1", "personal:x", "20001", "PREFERENCE", "称呼偏好", 0.8, 0.9,
             "PERSON", "person:qq:10000:20001", "qq:20001",
             "PRIVATE_ONLY", "qq:10000:private:20001"),
            ("p2", "personal:y", "20001", "PREFERENCE", "共享偏好", 0.8, 0.9,
             "PERSON", "person:qq:10000:20001", "qq:20001",
             "USER_SHARED", "qq:10000:group:123"),
            ("g1", "space_1", "20001", "FACT", "群空间记忆", 0.8, 0.9,
             "SPACE", "space:space_1", "", "CURRENT_SPACE", ""),
        ],
    )
    conn.commit()
    conn.close()
    return db


def test_list_only_person_rows(mem_db):
    data = service.list_personal_memories()
    ids = {i["id"] for i in data["items"]}
    assert ids == {"p1", "p2"}
    assert data["total"] == 2
    # 默认不返回正文（隐私最小化）
    assert all(i["content"] == "" for i in data["items"])
    with_content = service.list_personal_memories(include_content=True)
    assert any(i["content"] for i in with_content["items"])


def test_list_filters(mem_db):
    data = service.list_personal_memories(audience="PRIVATE_ONLY")
    assert [i["id"] for i in data["items"]] == ["p1"]
    data = service.list_personal_memories(source_conversation_key="qq:10000:group:123")
    assert [i["id"] for i in data["items"]] == ["p2"]


def test_delete_person_only_and_bumps_version(mem_db):
    assert service.delete_personal_memory("g1") is False  # SPACE 行不可经此删除
    assert service.delete_personal_memory("p1") is True
    conn = sqlite3.connect(mem_db)
    try:
        left = {r[0] for r in conn.execute("SELECT id FROM memories")}
        versions = conn.execute(
            "SELECT scope_key, version FROM memory_scope_versions"
        ).fetchall()
    finally:
        conn.close()
    assert left == {"p2", "g1"}
    assert ("person:qq:10000:20001", 1) in versions
