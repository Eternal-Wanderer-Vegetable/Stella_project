# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""历史回填 CLI 测试（计划 §6.9/§8.2 tests/test_personal_memory_backfill.py）。

覆盖：preview 不改原库、不明来源 skip、apply 幂等、撤回恢复、原 SPACE 行
不丢失、审计批次可查。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools import backfill_personal_memory as backfill


@pytest.fixture()
def legacy_db(tmp_path):
    """一个 v15 库：已注册群会话 + SPACE 记忆 + 真实来源消息行。"""
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    from memory.schema import MEMORIES_TABLE_DDL, _set_schema_version

    conn.execute(MEMORIES_TABLE_DDL)
    conn.execute(
        "CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " group_id TEXT, user_id TEXT, content TEXT,"
        " source_kind TEXT DEFAULT 'PASSIVE')"
    )
    conn.execute(
        "CREATE TABLE conversation_registry ("
        " conversation_key TEXT PRIMARY KEY, platform TEXT, bot_id TEXT, kind TEXT,"
        " peer_id TEXT, storage_session_id INTEGER UNIQUE, runtime_key TEXT UNIQUE,"
        " memory_space TEXT, legacy_binding TEXT DEFAULT '', created_at DATETIME"
        " DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        " UNIQUE(platform, bot_id, kind, peer_id))"
    )
    conn.execute(
        "CREATE TABLE memory_scope_versions (scope_key TEXT PRIMARY KEY,"
        " version INTEGER NOT NULL DEFAULT 1, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO conversation_registry (conversation_key, platform, bot_id, kind,"
        " peer_id, storage_session_id, runtime_key, memory_space)"
        " VALUES ('qq:10000:group:123', 'qq', '10000', 'group', '123', 123,"
        " 'qq:123', 'space_1')"
    )
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind)"
        " VALUES (?,?,?,?)",
        [
            ("123", "20001", "我喜欢用 Python 写后端", "AT_MENTION"),
            ("123", "30002", "30002 没说过这话", "PASSIVE"),
        ],
    )
    conn.execute(
        "INSERT INTO memories (id, group_shared_space, user_id, type, content,"
        " importance, confidence, status, owner_type, owner_key, audience, fact_key)"
        " VALUES ('m1', 'space_1', '20001', 'PREFERENCE', '喜欢用 Python 写后端',"
        " 0.8, 0.9, 'active', 'SPACE', 'space:space_1', 'CURRENT_SPACE', '')"
    )
    conn.execute(
        "INSERT INTO memories (id, group_shared_space, user_id, type, content,"
        " importance, confidence, status, owner_type, owner_key, audience, fact_key)"
        " VALUES ('m2', 'space_1', '30002', 'FACT', '30002 的群内关系事实',"
        " 0.8, 0.9, 'active', 'SPACE', 'space:space_1', 'CURRENT_SPACE', '')"
    )
    _set_schema_version(conn, 15)
    conn.commit()
    conn.close()
    return db


def _manifest(**overrides):
    m = {
        "bot_id": "10000",
        "types": ["PREFERENCE", "RELATION"],
        "entries": [
            {
                "memory_id": "m1",
                "user_id": "20001",
                "source_conversation_key": "qq:10000:group:123",
                "source_row_id": 1,
            }
        ],
    }
    m.update(overrides)
    return m


class TestPreview:
    def test_preview_reports_copy_without_touching_db(self, legacy_db):
        report = backfill.preview(_manifest(), db_path=legacy_db)
        assert report.entries[0].action == "copy"
        # preview 不改原库（§8.1）
        conn = sqlite3.connect(legacy_db)
        try:
            n_person = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE owner_type = 'PERSON'"
            ).fetchone()[0]
            audit = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE '%backfill%'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert n_person == 0
        assert audit == 0

    def test_unknown_source_skips(self, legacy_db):
        m = _manifest(entries=[{
            "memory_id": "m1", "user_id": "20001",
            "source_conversation_key": "qq:10000:group:123",
            "source_row_id": 999,  # 不存在的消息行
        }])
        report = backfill.preview(m, db_path=legacy_db)
        assert report.entries[0].action == "skip"
        assert report.entries[0].reason == "source_row_not_in_conversation"

    def test_sender_mismatch_and_bot_mismatch_and_type_gate(self, legacy_db):
        # sender 不等于 subject（m1 是 PREFERENCE，类型闸通过后到来源行校验）
        r1 = backfill.preview(_manifest(entries=[{
            "memory_id": "m1", "user_id": "20001",
            "source_conversation_key": "qq:10000:group:123", "source_row_id": 2,
        }]), db_path=legacy_db)
        assert r1.entries[0].reason == "source_row_sender_mismatch"
        # 会话不属于 manifest 声明的 Bot
        r2 = backfill.preview(_manifest(bot_id="99999"), db_path=legacy_db)
        assert r2.entries[0].reason == "conversation_key_not_bound_to_manifest_bot"
        # 类型不在白名单（FACT 不在默认清单）
        r3 = backfill.preview(_manifest(entries=[{
            "memory_id": "m2", "user_id": "30002",
            "source_conversation_key": "qq:10000:group:123", "source_row_id": 2,
        }]), db_path=legacy_db)
        assert r3.entries[0].action == "skip"
        assert "type_not_shareable" in r3.entries[0].reason


class TestApplyAndRevoke:
    def test_apply_copies_and_is_idempotent(self, legacy_db):
        first = backfill.apply_manifest(_manifest(), batch_id="b1", db_path=legacy_db)
        assert first.entries[0].action == "copy"
        second = backfill.apply_manifest(_manifest(), batch_id="b1", db_path=legacy_db)
        assert second.entries[0].action == "skip"
        assert "already_backfilled" in second.entries[0].reason

        conn = sqlite3.connect(legacy_db)
        try:
            originals = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE id = 'm1' AND"
                " owner_type = 'SPACE'"
            ).fetchone()[0]
            copies = conn.execute(
                "SELECT owner_type, audience, subject_key, source_conversation_key"
                " FROM memories WHERE fact_key = 'm1'"
            ).fetchall()
        finally:
            conn.close()
        assert originals == 1  # 原 SPACE 行不丢失
        assert copies == [("PERSON", "USER_SHARED", "qq:20001", "qq:10000:group:123")]

    def test_revoke_removes_copy_keeps_original(self, legacy_db):
        backfill.apply_manifest(_manifest(), batch_id="b1", db_path=legacy_db)
        report = backfill.revoke("b1", db_path=legacy_db)
        assert report.entries[0].reason == "revoked"
        # 再撤回幂等
        again = backfill.revoke("b1", db_path=legacy_db)
        assert again.entries[0].reason == "already_revoked"
        conn = sqlite3.connect(legacy_db)
        try:
            person_left = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE owner_type = 'PERSON'"
            ).fetchone()[0]
            original = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE id = 'm1'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert person_left == 0
        assert original == 1  # 原行仍在

    def test_apply_bumps_persistent_scope_version(self, legacy_db):
        conn = sqlite3.connect(legacy_db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS memory_scope_versions (scope_key TEXT"
            " PRIMARY KEY, version INTEGER NOT NULL DEFAULT 1, updated_at DATETIME"
            " DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.commit()
        conn.close()
        before = _version(legacy_db, "person:qq:10000:20001")
        backfill.apply_manifest(_manifest(), batch_id="b1", db_path=legacy_db)
        assert _version(legacy_db, "person:qq:10000:20001") == before + 1


def _version(db: Path, scope_key: str) -> int:
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT version FROM memory_scope_versions WHERE scope_key = ?",
            (scope_key,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0
