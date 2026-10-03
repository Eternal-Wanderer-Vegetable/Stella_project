# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""个人记忆 scope 全链路矩阵（计划 §6.4-§6.6/§8.1 tests/test_personal_memory_scope.py）。

覆盖：同 QQ USER_SHARED 跨空间可检索 / PRIVATE_ONLY 对群不可见（SQL+FTS
同授权）、无 scope 旧调用 SPACE-only、伪造 owner/来源被服务端拒绝、证据
重放不重复计数、持久缓存版本失效。
"""

from __future__ import annotations

import sqlite3

import pytest

import memory.retrieval_v2 as retrieval_v2
from core.context import ChatContext
from memory.ownership import (
    AUDIENCE_PRIVATE_ONLY,
    AUDIENCE_USER_SHARED,
    OWNER_TYPE_PERSON,
    OWNER_TYPE_SPACE,
    person_compat_space,
    person_owner,
    scope_for_conversation,
    space_only_scope,
)


@pytest.fixture()
def mem_db(tmp_path, monkeypatch):
    """schema15 形状的记忆库：群 A 空间 + 私聊 PERSON 行 + 群 B 空间。"""
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db)
    conn = sqlite3.connect(db)
    from memory.schema import MEMORIES_TABLE_DDL
    conn.execute(MEMORIES_TABLE_DDL)
    conn.execute(
        "CREATE VIRTUAL TABLE memories_fts USING fts5("
        "mem_id UNINDEXED, content, group_shared_space UNINDEXED, user_id UNINDEXED)"
    )
    conn.execute("CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER)")
    conn.execute("INSERT INTO schema_meta VALUES ('version', 15)")
    space_a = "space_a"
    space_b = "space_b"
    personal_ns = person_compat_space("person:qq:10000:20001", AUDIENCE_PRIVATE_ONLY)
    shared_ns = person_compat_space("person:qq:10000:20001", AUDIENCE_USER_SHARED)
    rows = [
        # (id, space, uid, content, owner_type, owner_key, subject, audience)
        ("g-shared-a", space_a, "20001", "用户喜欢合作游戏",
         OWNER_TYPE_SPACE, f"space:{space_a}", "", "CURRENT_SPACE"),
        ("g-shared-b", space_b, "20001", "群B的公共话题",
         OWNER_TYPE_SPACE, f"space:{space_b}", "", "CURRENT_SPACE"),
        ("p-private", personal_ns, "20001", "我的家庭住址是私密信息",
         OWNER_TYPE_PERSON, "person:qq:10000:20001", "qq:20001", AUDIENCE_PRIVATE_ONLY),
        ("p-shared", shared_ns, "20001", "希望被称呼为队长",
         OWNER_TYPE_PERSON, "person:qq:10000:20001", "qq:20001", AUDIENCE_USER_SHARED),
        ("p-other", shared_ns, "30002", "他人30002的偏好",
         OWNER_TYPE_PERSON, "person:qq:10000:30002", "qq:30002", AUDIENCE_USER_SHARED),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content,"
            " importance, confidence, status, owner_type, owner_key, subject_key, audience)"
            " VALUES (?,?,?,?, 'FACT', .8, .9, 'active', ?, ?, ?, ?)",
            r,
        )
        from memory.retriever import _segment_text

        conn.execute(
            "INSERT INTO memories_fts (mem_id, content, group_shared_space, user_id)"
            " VALUES (?,?,?,?)",
            (r[0], _segment_text(r[3]), r[1], r[2]),
        )
    conn.commit()
    conn.close()
    return db


def _fetch(db, space, user, query, scope):
    conn = sqlite3.connect(db)
    try:
        cursor = conn.cursor()
        return {
            m["id"]
            for m in retrieval_v2._fetch_candidates(
                cursor, space, user, "CASUAL_REPLY", query, 20, access_scope=scope
            )
        }
    finally:
        conn.close()


class TestAudienceMatrix:
    def test_group_a_sees_space_and_user_shared_not_private(self, mem_db):
        """同 QQ 在群 A：SPACE + USER_SHARED 命中；PRIVATE_ONLY 绝不进候选池。"""
        scope = scope_for_conversation(
            kind="group", memory_space="space_a", platform="qq",
            bot_id="10000", user_id=20001,
        )
        got = _fetch(mem_db, "space_a", 20001, "游戏 称呼", scope)
        assert "g-shared-a" in got
        assert "p-shared" in got
        assert "p-private" not in got
        assert "p-other" not in got
        assert "g-shared-b" not in got  # 其他空间照旧隔离

    def test_private_sees_private_and_shared(self, mem_db):
        scope = scope_for_conversation(
            kind="private", memory_space="private:qq:10000:20001",
            platform="qq", bot_id="10000", user_id=20001,
        )
        got = _fetch(mem_db, "private:qq:10000:20001", 20001, "住址 称呼", scope)
        assert "p-private" in got
        assert "p-shared" in got
        assert "p-other" not in got
        assert "g-shared-a" not in got  # 群空间不因私聊可见

    def test_no_scope_is_space_only(self, mem_db):
        """无 scope 的旧调用/主动发言：SPACE-only，任何 PERSON 行不可见。"""
        got = _fetch(mem_db, "space_a", 20001, "游戏", None)
        assert got == {"g-shared-a"}
        # 主动发言（user None）同法
        conn = sqlite3.connect(mem_db)
        try:
            cursor = conn.cursor()
            got = {
                m["id"]
                for m in retrieval_v2._fetch_candidates(
                    cursor, "space_a", None, "CASUAL_REPLY", "游戏", 20
                )
            }
        finally:
            conn.close()
        assert got == {"g-shared-a"}

    def test_untrusted_subject_space_only(self, mem_db):
        scope = scope_for_conversation(
            kind="private", memory_space="space_a", platform="qq",
            bot_id="10000", user_id=0,
        )
        assert not scope.has_person
        got = _fetch(mem_db, "space_a", 20001, "游戏", scope)
        assert got == {"g-shared-a"}  # SPACE-only：无任何 PERSON 行

    def test_fts_same_authorization_as_sql(self, mem_db):
        """FTS 回退路径与 SQL 主路径同授权（§8.1：没有旁路）。"""
        conn = sqlite3.connect(mem_db)
        try:
            cursor = conn.cursor()
            group_scope = scope_for_conversation(
                kind="group", memory_space="space_a", platform="qq",
                bot_id="10000", user_id=20001,
            )
            rows = retrieval_v2._query_fts(
                cursor, "space_a", 20001, "称呼", 20, "CASUAL_REPLY",
                access_scope=group_scope,
            )
            ids = {r[0] for r in rows}
            assert "p-shared" in ids
            assert "p-private" not in ids
        finally:
            conn.close()

    def test_internal_visibility_blocks_person_shared(self, mem_db):
        """visibility=INTERNAL 即使 PERSON+USER_SHARED 也不进普通 prompt。"""
        conn = sqlite3.connect(mem_db)
        conn.execute(
            "UPDATE memories SET visibility = 'INTERNAL' WHERE id = 'p-shared'"
        )
        conn.commit()
        conn.close()
        scope = scope_for_conversation(
            kind="group", memory_space="space_a", platform="qq",
            bot_id="10000", user_id=20001,
        )
        got = _fetch(mem_db, "space_a", 20001, "称呼", scope)
        assert "p-shared" not in got


class TestWriteRouting:
    def test_private_direct_routes_person(self, tmp_path, monkeypatch):
        """私聊直接对话候选 → PERSON+PRIVATE_ONLY；他人指名保持 SPACE。"""
        db = tmp_path / "w.db"
        monkeypatch.setattr("memory.consolidator.DB_PATH", db)
        from config import settings

        # 注意 config 星号导出：from config import X 读包级副本，必须 patch
        # config 包属性（settings 与 config 两处都要，见 social-loop 教训）
        monkeypatch.setattr(settings, "PERSONAL_MEMORY_WRITE_ENABLED", True)
        import config

        monkeypatch.setattr(config, "PERSONAL_MEMORY_WRITE_ENABLED", True)
        from core.conversation import qq_private_ref
        from memory.consolidator import MemoryConsolidator

        ref = qq_private_ref("10000", 20001, storage_session_id=-2)
        source_rows = [
            (11, "20001", "我叫小王，希望被叫队长", "PRIVATE_DIRECT"),
            (12, "20001", "用户30002喜欢猫", "PRIVATE_DIRECT"),
        ]
        candidates = [
            {"user_id": "20001", "type": "PREFERENCE", "content": "希望被称呼为队长",
             "confidence": 0.8, "importance": 0.6, "source_message_ids": [11]},
            {"user_id": "30002", "type": "FACT", "content": "30002喜欢猫",
             "confidence": 0.8, "importance": 0.6, "source_message_ids": [12]},
        ]
        consolidator = MemoryConsolidator.__new__(MemoryConsolidator)
        counts = consolidator._write_memory_candidates(
            "private:qq:10000:20001", candidates,
            sender_ids=["20001"], at_senders=["20001"],
            origin_group_id=-2, conversation=ref, source_rows=source_rows,
        )
        # 30002 被 sender 白名单拒绝（他人转述在既有闸口即被丢弃）
        assert counts["written"] == 1 and counts["skipped"] == 1
        conn = sqlite3.connect(db)
        try:
            rows = {
                r[0]: r[1:]
                for r in conn.execute(
                    "SELECT id, owner_type, owner_key, subject_key, audience,"
                    " group_shared_space, fact_key, source_conversation_key"
                    " FROM memory_candidates"
                )
            }
        finally:
            conn.close()
        by_fact = {}
        for _id, (ot, ok_, subj, aud, space, fk, sck) in rows.items():
            by_fact[fk] = (ot, ok_, subj, aud, space, sck)
        personal = person_owner("qq", "10000", 20001)
        me_rows = [v for v in by_fact.values() if v[2] == "qq:20001"]
        assert len(me_rows) == 1
        ot, ok_, subj, aud, space, sck = me_rows[0]
        assert ot == OWNER_TYPE_PERSON
        assert ok_ == personal.owner_key
        assert aud == AUDIENCE_PRIVATE_ONLY
        assert space == person_compat_space(ok_, aud)
        assert sck == "qq:10000:private:20001"
        # 他人指名：在既有 sender 白名单闸口即被整条丢弃（skipped=1），
        # 不落任何行——绝不写他人个人事实
        assert len(rows) == 1

    def test_flag_off_writes_space(self, tmp_path, monkeypatch):
        """PERSONAL_MEMORY_WRITE_ENABLED 关（M1/M2 默认）：私聊候选全部 SPACE。"""
        db = tmp_path / "w2.db"
        monkeypatch.setattr("memory.consolidator.DB_PATH", db)
        from config import settings

        monkeypatch.setattr(settings, "PERSONAL_MEMORY_WRITE_ENABLED", False)
        import config

        monkeypatch.setattr(config, "PERSONAL_MEMORY_WRITE_ENABLED", False)
        from core.conversation import qq_private_ref
        from memory.consolidator import MemoryConsolidator

        ref = qq_private_ref("10000", 20001, storage_session_id=-2)
        consolidator = MemoryConsolidator.__new__(MemoryConsolidator)
        consolidator._write_memory_candidates(
            "private:qq:10000:20001",
            [{"user_id": "20001", "type": "FACT", "content": "x",
              "confidence": 0.8, "importance": 0.6, "source_message_ids": [1]}],
            sender_ids=["20001"], at_senders=["20001"],
            origin_group_id=-2, conversation=ref,
            source_rows=[(1, "20001", "x", "PRIVATE_DIRECT")],
        )
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                "SELECT owner_type, owner_key, audience FROM memory_candidates"
            ).fetchall()
        finally:
            conn.close()
        assert rows == [("SPACE", "space:private:qq:10000:20001", "CURRENT_SPACE")]

    def test_evidence_replay_does_not_reinforce(self, tmp_path, monkeypatch):
        """同一来源消息行重放：不新增证据、不重复强化（计划 §6.5）。"""
        db = tmp_path / "w3.db"
        monkeypatch.setattr("memory.consolidator.DB_PATH", db)
        from config import settings

        # 注意 config 星号导出：from config import X 读包级副本，必须 patch
        # config 包属性（settings 与 config 两处都要，见 social-loop 教训）
        monkeypatch.setattr(settings, "PERSONAL_MEMORY_WRITE_ENABLED", True)
        import config

        monkeypatch.setattr(config, "PERSONAL_MEMORY_WRITE_ENABLED", True)
        from core.conversation import qq_private_ref
        from memory.consolidator import MemoryConsolidator

        ref = qq_private_ref("10000", 20001, storage_session_id=-2)
        consolidator = MemoryConsolidator.__new__(MemoryConsolidator)
        candidate = {
            "user_id": "20001", "type": "PREFERENCE", "content": "希望被称呼为队长",
            "confidence": 0.8, "importance": 0.6, "source_message_ids": [11],
        }
        source_rows = [(11, "20001", "我叫小王，希望被叫队长", "PRIVATE_DIRECT")]
        kw = {
            "sender_ids": ["20001"], "at_senders": ["20001"],
            "origin_group_id": -2, "conversation": ref,
            "source_rows": source_rows,
        }
        first = consolidator._write_memory_candidates(
            "private:qq:10000:20001", [dict(candidate)], **kw
        )
        # 同消息重放：证据唯一约束命中 → 全部跳过
        second = consolidator._write_memory_candidates(
            "private:qq:10000:20001", [dict(candidate)], **kw
        )
        assert first["written"] == 1
        assert second["written"] == 0 and second["skipped"] >= 1
        conn = sqlite3.connect(db)
        try:
            evidence = conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0]
            candidates_count = conn.execute(
                "SELECT COUNT(*), MAX(occurrence_count) FROM memory_candidates"
            ).fetchone()
        finally:
            conn.close()
        assert evidence == 1  # 单 source row 单计数
        assert candidates_count == (1, 1)  # occurrence 不翻倍


class TestScopeVersionCache:
    def test_bump_invalidates_retrieval_cache(self, tmp_path, monkeypatch):
        """持久版本变化 → 下一轮检索换桶（§8.1 删除/撤销热缓存不返回）。"""
        import memory.scope_versions as sv

        db = tmp_path / "sv.db"
        monkeypatch.setattr(sv, "DB_PATH", db)
        assert sv.current_version(["person:qq:10000:20001"]) == 0
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "CREATE TABLE memory_scope_versions (scope_key TEXT PRIMARY KEY,"
                " version INTEGER NOT NULL DEFAULT 1,"
                " updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.commit()
        finally:
            conn.close()
        sv.bump("person:qq:10000:20001")
        sv.bump("person:qq:10000:20001")
        assert sv.current_version(["person:qq:10000:20001"]) == 2


class TestContextScopeDerivation:
    def test_scope_from_chat_context_identity(self):
        """服务端 scope 只由 ctx 身份派生；主动发言无 PERSON 分支。"""
        from memory.pre_processors import (
            _build_user_context_v2,  # noqa: F401  导入不炸即可
        )

        private_ctx = ChatContext(
            user_id=20001, group_id=0, msg_id=1, message="q",
            conversation_key="qq:10000:private:20001", conversation_kind="private",
            bot_id="10000", peer_id="20001", storage_session_id=-2,
            group_shared_space="private:qq:10000:20001",
        )
        from memory.ownership import scope_for_conversation

        scope = scope_for_conversation(
            kind=private_ctx.conversation_kind,
            memory_space=private_ctx.group_shared_space,
            platform="qq", bot_id=private_ctx.bot_id, user_id=private_ctx.peer_id,
        )
        assert scope.has_person
        assert scope.person_audiences == (AUDIENCE_PRIVATE_ONLY, AUDIENCE_USER_SHARED)
        proactive_scope = space_only_scope("space_a")
        assert not proactive_scope.has_person
