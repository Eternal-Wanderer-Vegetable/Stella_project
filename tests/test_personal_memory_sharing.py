# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""个人记忆共享权限矩阵测试（整改计划 P3，复核 F3/F4/F5/F13）。

与被复核版本的区别：临时库用 **schema.py 规范 DDL**（memories/candidates/
evidence/scope_versions/group_messages/授权表/台账/审计全量），断言走真实
SQL 行——不再用"只建授权表"的轻量库让复制路径整段跳过。
"""

from __future__ import annotations

import sqlite3

import pytest

from memory import schema, scope_versions
from memory.ownership import person_owner_key
from memory.personal_sharing import (
    create_sharing_authorization_table,
    create_sharing_copies_table,
    detect_revoke_intent,
    detect_sharing_intent,
    grant_sharing_authorization,
    promote_pending_grants_for_fact,
    revoke_sharing_authorization,
)

_BOT = "10000"
_U1 = "20001"
_U2 = "20002"
_CONV = "qq:10000:private:20001"
_FACT = "f" * 16


@pytest.fixture()
def sharing_db_path(tmp_path, monkeypatch):
    """正式 v18 形状的临时库：规范 DDL 全量建表；返回 (conn, db 路径)。"""
    db = tmp_path / "sharing.db"
    conn = sqlite3.connect(db)
    conn.execute(schema.MEMORIES_TABLE_DDL)
    conn.execute(schema.MEMORY_CANDIDATES_TABLE_DDL)
    conn.execute(schema.MEMORY_EVIDENCE_TABLE_DDL)
    conn.execute(schema.MEMORY_SCOPE_VERSIONS_TABLE_DDL)
    from memory.pre_processors import _GROUP_MESSAGES_V16_DDL

    conn.execute(_GROUP_MESSAGES_V16_DDL)
    # v17 additive 列（v18 起这些列属于规范形状；授权表新 DDL 已含 v18 列）
    conn.execute(
        "ALTER TABLE memory_candidates ADD COLUMN verification_contract_json TEXT"
    )
    create_sharing_authorization_table(conn)
    create_sharing_copies_table(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sharing_audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            grant_id INTEGER,
            bot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            fact_key TEXT,
            performed_at TEXT NOT NULL,
            details TEXT
        )
    """)
    conn.commit()
    # scope_versions.current_version 读 config.DB_PATH；指向临时库供断言
    monkeypatch.setattr(scope_versions, "DB_PATH", db)
    yield conn, db
    conn.close()


@pytest.fixture()
def sharing_db(sharing_db_path):
    conn, _db = sharing_db_path
    return conn


def _insert_source_row(conn, row_id: int, *, user_id: str = _U1, conv: str = _CONV,
                       content: str = "以后在群里也记得我们CP的关系",
                       source_kind: str = "AT_MENTION") -> None:
    conn.execute(
        "INSERT INTO group_messages (id, group_id, user_id, content, source_kind,"
        " conversation_key, bot_id) VALUES (?,?,?,?,?,?,?)",
        (row_id, "-2", user_id, content, source_kind, conv, _BOT),
    )


def _insert_private_fact(
    conn,
    *,
    table: str = "memory_candidates",
    record_id: str = "cand1",
    owner_user: str = _U1,
    fact_key: str = _FACT,
    content: str = "用户20001与Lumi是CP关系",
    status: str = "ACTIVE",
) -> None:
    """插入一条规范形状的 PERSON/PRIVATE_ONLY 原件。"""
    owner_key = person_owner_key("qq", _BOT, owner_user)
    subject_key = f"qq:{owner_user}"
    conv = f"qq:10000:private:{owner_user}"
    compat = f"personal:{owner_key}:PRIVATE_ONLY"
    if table == "memories":
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content,"
            " content_raw, importance, confidence, status, confirmation_count,"
            " last_confirmed_at, owner_type, owner_key, subject_key, audience,"
            " source_conversation_key, fact_key, policy_version)"
            " VALUES (?,?,?,'relation',?,?,0.9,0.9,?,2,"
            " '2026-10-05T09:00:00','PERSON',?,?,'PRIVATE_ONLY',?,?,'2026-10-03.0')",
            (record_id, compat, owner_user, content, content, status,
             owner_key, subject_key, conv, fact_key),
        )
    else:
        conn.execute(
            "INSERT INTO memory_candidates (id, group_shared_space, user_id, type,"
            " content, content_raw, importance, confidence, evidence, status,"
            " source_message_ids, source_kind, occurrence_count, first_seen_at,"
            " source_kinds, owner_type, owner_key, subject_key, audience,"
            " source_conversation_key, fact_key, policy_version,"
            " verification_contract_json)"
            " VALUES (?,?,?,'relation',?,?,0.9,0.9,'[]',?,'[1]','PASSIVE',1,"
            " '2026-10-05T09:00:00','[\"PASSIVE\"]','PERSON',?,?,"
            " 'PRIVATE_ONLY',?,?,'2026-10-03.0','{}')",
            (record_id, compat, owner_user, content, content, status,
             owner_key, subject_key, conv, fact_key),
        )


def _grant(conn, row_id: int = 11, user_id: str = _U1):
    conv = f"qq:10000:private:{user_id}"
    result = grant_sharing_authorization(
        conn, "qq", _BOT, user_id, _FACT, conv, row_id
    )
    conn.commit()
    return result


def _user_shared_rows(conn, table: str):
    return conn.execute(
        f"SELECT id, owner_key, subject_key, status, audience FROM {table}"
        " WHERE audience = 'USER_SHARED'"
    ).fetchall()


# ── 意图检测（复核 F4 反例） ────────────────────────────────────────────


def test_detect_sharing_intent_requires_scope_verb_and_person():
    assert detect_sharing_intent("以后在群里也记得我们CP的关系", _U1, _CONV) == (
        True, "explicit_sharing")
    assert detect_sharing_intent("这个在群里也能用", _U1, _CONV)[0] is True
    assert detect_sharing_intent("可以在群里提醒我", _U1, _CONV)[0] is True


def test_detect_sharing_intent_rejects_review_counterexamples():
    # 复核 F4 实测反例
    assert detect_sharing_intent("他说可以在群里分享这件事", _U1, _CONV) == (
        False, "third_person")
    assert detect_sharing_intent("我在群里玩游戏", _U1, _CONV)[0] is False
    assert detect_sharing_intent("别在群里说", _U1, _CONV) == (False, "negative")
    assert detect_sharing_intent("能在群里用吗？", _U1, _CONV) == (False, "question")


def test_detect_revoke_intent_marks():
    assert detect_revoke_intent("别在群里说这件事")[0] is True
    assert detect_revoke_intent("今天天气不错")[0] is False


# ── 来源核验（复核 F4） ────────────────────────────────────────────────


def test_grant_rejects_unverified_source(sharing_db):
    _insert_private_fact(sharing_db)
    # 行不存在
    ok, reason = _grant(sharing_db, row_id=999)
    assert not ok and reason == "source_row_missing"
    # 作者不是本人
    _insert_source_row(sharing_db, 12, user_id=_U2)
    ok, reason = grant_sharing_authorization(
        sharing_db, "qq", _BOT, _U1, _FACT, _CONV, 12)
    assert not ok and reason == "source_author_mismatch"
    # Bot 自己的话
    _insert_source_row(sharing_db, 13, source_kind="BOT_SELF")
    ok, reason = grant_sharing_authorization(
        sharing_db, "qq", _BOT, _U1, _FACT, _CONV, 13)
    assert not ok and reason == "source_is_bot"
    sharing_db.rollback()


# ── 复制走真实 DDL（复核 F3） ──────────────────────────────────────────


def test_replicate_candidates_copy_with_real_columns(sharing_db):
    """candidates 复制不得引用不存在的 confirmation_count（F3 的 OperationalError）。"""
    _insert_source_row(sharing_db, 11)
    _insert_private_fact(sharing_db, table="memory_candidates")
    ok, reason = _grant(sharing_db)
    assert ok and reason == "granted", reason
    rows = _user_shared_rows(sharing_db, "memory_candidates")
    assert len(rows) == 1
    copy_id, owner_key, subject_key, status, _audience = rows[0]
    assert copy_id == "cand1:s1"
    assert owner_key == person_owner_key("qq", _BOT, _U1)
    assert subject_key == f"qq:{_U1}"
    assert status == "ACTIVE"
    # 台账逐条登记
    ledger = sharing_db.execute(
        "SELECT table_name, record_id FROM personal_memory_sharing_copies"
    ).fetchall()
    assert ledger == [("memory_candidates", copy_id)]
    # 授权证据行存在
    ev = sharing_db.execute(
        "SELECT COUNT(*) FROM memory_evidence WHERE audience='USER_SHARED'"
        " AND owner_key = ?",
        (owner_key,),
    ).fetchone()[0]
    assert ev == 1


def test_replicate_memories_copy_with_confirmation_columns(sharing_db):
    _insert_source_row(sharing_db, 11)
    _insert_private_fact(sharing_db, table="memories", record_id="mem1")
    ok, reason = _grant(sharing_db)
    assert ok and reason == "granted"
    rows = _user_shared_rows(sharing_db, "memories")
    assert len(rows) == 1 and rows[0][0] == "mem1:s1"


# ── 跨用户/跨 Bot 隔离（复核 F4） ──────────────────────────────────────


def test_grant_isolated_across_users_same_fact_key(sharing_db):
    """复核 F4 探针：用户 123 授权同键事实，绝不能带出 456 的行。"""
    _insert_source_row(sharing_db, 11)
    _insert_private_fact(sharing_db, table="memory_candidates",
                         record_id="c1", owner_user=_U1)
    _insert_private_fact(sharing_db, table="memory_candidates",
                         record_id="c2", owner_user=_U2)
    _insert_source_row(sharing_db, 21, user_id=_U2,
                       conv="qq:10000:private:20002")
    ok, reason = _grant(sharing_db, row_id=11, user_id=_U1)
    assert ok and reason == "granted"
    rows = _user_shared_rows(sharing_db, "memory_candidates")
    assert len(rows) == 1, "只能出现授权者本人的 USER_SHARED 副本"
    assert rows[0][1] == person_owner_key("qq", _BOT, _U1)
    # 456 的原件保持 PRIVATE_ONLY
    other = sharing_db.execute(
        "SELECT audience, status FROM memory_candidates WHERE id='c2'"
    ).fetchone()
    assert other == ("PRIVATE_ONLY", "ACTIVE")


# ── pending 与提升（复核 F4） ──────────────────────────────────────────


def test_grant_pending_then_promote_after_consolidation(sharing_db):
    _insert_source_row(sharing_db, 11)
    ok, reason = _grant(sharing_db)  # 事实尚未整合
    assert ok and reason == "pending"
    status = sharing_db.execute(
        "SELECT status FROM personal_memory_sharing").fetchone()[0]
    assert status == "pending"
    assert _user_shared_rows(sharing_db, "memory_candidates") == []

    # 整合写入（同事务语义由调用方保证；这里验证提升结果）
    _insert_private_fact(sharing_db)
    promoted = promote_pending_grants_for_fact(
        sharing_db,
        person_owner_key("qq", _BOT, _U1),
        f"qq:{_U1}",
        _FACT,
        bot_id=_BOT,
        user_id=_U1,
    )
    sharing_db.commit()
    assert promoted == 1
    status = sharing_db.execute(
        "SELECT status FROM personal_memory_sharing").fetchone()[0]
    assert status == "active"
    assert len(_user_shared_rows(sharing_db, "memory_candidates")) == 1


# ── 撤回：台账精确 + 规范版本键（复核 F4/F5） ──────────────────────────


def test_revoke_scoped_by_ledger_and_bumps_canonical_owner_key(sharing_db):
    _insert_source_row(sharing_db, 11)
    _insert_private_fact(sharing_db)
    ok, _ = _grant(sharing_db)
    assert ok

    owner_key = person_owner_key("qq", _BOT, _U1)
    v_before = scope_versions.current_version([owner_key])
    ok, reason = revoke_sharing_authorization(
        sharing_db, "qq", _BOT, _U1, _FACT)
    sharing_db.commit()
    assert ok and reason == "revoked"

    copy = sharing_db.execute(
        "SELECT status FROM memory_candidates WHERE audience='USER_SHARED'"
    ).fetchone()[0]
    assert copy == "DEPRECATED"
    original = sharing_db.execute(
        "SELECT status, audience FROM memory_candidates WHERE id='cand1'"
    ).fetchone()
    assert original == ("ACTIVE", "PRIVATE_ONLY"), "PRIVATE_ONLY 原件必须保留"
    # 复核 F5：bump 的是规范键，不是 user:{uid}
    v_after = scope_versions.current_version([owner_key])
    assert v_after == v_before + 1
    wrong = sharing_db.execute(
        "SELECT version FROM memory_scope_versions WHERE scope_key = ?",
        (f"user:{_U1}",),
    ).fetchone()
    assert wrong is None, "禁止再写 user:{uid} 错误键"
    # 台账记录了原状态供 regrant
    prior = sharing_db.execute(
        "SELECT prior_status FROM personal_memory_sharing_copies"
    ).fetchone()[0]
    assert prior == "ACTIVE"


def test_revoke_does_not_touch_other_users_copies(sharing_db):
    _insert_source_row(sharing_db, 11)
    _insert_private_fact(sharing_db, record_id="c1", owner_user=_U1)
    _insert_private_fact(sharing_db, record_id="c2", owner_user=_U2)
    _insert_source_row(sharing_db, 21, user_id=_U2,
                       conv="qq:10000:private:20002")
    _grant(sharing_db, row_id=11, user_id=_U1)
    _grant(sharing_db, row_id=21, user_id=_U2)
    assert len(_user_shared_rows(sharing_db, "memory_candidates")) == 2

    ok, _ = revoke_sharing_authorization(sharing_db, "qq", _BOT, _U1, _FACT)
    sharing_db.commit()
    assert ok
    rows = _user_shared_rows(sharing_db, "memory_candidates")
    active = [r for r in rows if r[3] == "ACTIVE"]
    assert len(active) == 1
    assert active[0][1] == person_owner_key("qq", _BOT, _U2), "U2 的共享副本必须完好"
    u1_copy = [r for r in rows if r[1] == person_owner_key("qq", _BOT, _U1)]
    assert u1_copy and u1_copy[0][3] == "DEPRECATED"


# ── 重授权（复核 F13） ─────────────────────────────────────────────────


def test_regrant_restores_copies_and_updates_source(sharing_db):
    _insert_source_row(sharing_db, 11)
    _insert_private_fact(sharing_db)
    _grant(sharing_db, row_id=11)
    revoke_sharing_authorization(sharing_db, "qq", _BOT, _U1, _FACT)
    sharing_db.commit()
    assert _user_shared_rows(sharing_db, "memory_candidates")[0][3] == "DEPRECATED"

    # 用新授权消息重新授权
    _insert_source_row(sharing_db, 999, content="还是在群里也记着吧")
    ok, reason = _grant(sharing_db, row_id=999)
    assert ok and reason == "regranted", reason

    copy = sharing_db.execute(
        "SELECT status FROM memory_candidates WHERE audience='USER_SHARED'"
    ).fetchone()[0]
    assert copy == "ACTIVE", "regrant 必须恢复副本，而不是返回成功就完事"
    grant_row = sharing_db.execute(
        "SELECT status, source_message_row_id FROM personal_memory_sharing"
    ).fetchone()
    assert grant_row == ("active", 999), "来源必须更新为本次授权消息"
    # 台账 prior_status 复位
    prior = sharing_db.execute(
        "SELECT prior_status FROM personal_memory_sharing_copies"
    ).fetchone()[0]
    assert prior is None


def test_grant_idempotent_when_already_active(sharing_db):
    _insert_source_row(sharing_db, 11)
    _insert_private_fact(sharing_db)
    _grant(sharing_db, row_id=11)
    ok, reason = _grant(sharing_db, row_id=11)
    assert ok and reason == "already_active"
    assert len(_user_shared_rows(sharing_db, "memory_candidates")) == 1


# ── 真实检索暖缓存撤回（复核 F5 主验收） ────────────────────────────────


def test_revoke_invisible_through_real_retrieval_warm_cache(
    sharing_db_path, monkeypatch
):
    """grant→真实检索命中→revoke 提交→同进程暖缓存立即 miss。"""
    import memory.retrieval_v2 as rv2
    from memory.ownership import MemoryAccessScope

    conn, db = sharing_db_path
    monkeypatch.setattr(rv2, "DB_PATH", db)
    # conftest 全局关 v2（legacy 回退直接返回空）；本用例验收的就是 v2 检索
    monkeypatch.setattr(rv2, "MEMORY_V2_ENABLED", True)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5("
        "mem_id UNINDEXED, content, group_shared_space UNINDEXED, user_id UNINDEXED)"
    )
    _insert_source_row(conn, 11)
    # 检索只读 memories（候选未晋升不召回），且要求 status='active'（精确小写）
    _insert_private_fact(conn, table="memories", record_id="mem_cp", status="active")
    conn.commit()

    ok, reason = _grant(conn)
    assert ok and reason == "granted", reason

    scope = MemoryAccessScope(
        space_key="space:space_1",
        person_owner_key=person_owner_key("qq", _BOT, _U1),
        subject_key=f"qq:{_U1}",
        person_audiences=("USER_SHARED",),
    )

    def _copy_hits() -> list[str]:
        result = rv2.retrieve_memories(
            group_shared_space="space_1",
            user_id=20001,
            query="Lumi CP 关系",
            trigger="reply",
            access_scope=scope,
        )
        return [
            m["id"] for m in result.conversation_memories
            if str(m["id"]).endswith(":s1")
        ]

    hits = _copy_hits()
    assert hits, f"授权后共享副本必须可召回，实际 {hits}"

    ok, reason = revoke_sharing_authorization(conn, "qq", _BOT, _U1, _FACT)
    conn.commit()
    assert ok and reason == "revoked"

    # 同进程暖缓存：版本键已随 revoke 严格推进，下一次检索立即换桶
    assert _copy_hits() == [], "撤回后暖缓存必须立即不可见（复核 F5）"
