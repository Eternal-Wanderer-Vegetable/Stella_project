# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Regression tests for server-owned memory evidence binding."""

import sqlite3

import pytest

from memory.evidence_contract import assess_candidate, source_digest, verify_source_snapshot


def _database(tmp_path, *, source_kind="AT_MENTION", author="111", bot_id="bot-a"):
    conn = sqlite3.connect(tmp_path / "evidence.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE group_messages ("
        "id INTEGER PRIMARY KEY, group_id TEXT, user_id TEXT, content TEXT, "
        "source_kind TEXT, timestamp TEXT, conversation_key TEXT, bot_id TEXT)"
    )
    conn.execute(
        "INSERT INTO group_messages VALUES (1, '1001', ?, ?, ?, '2026-10-09T00:00:00', ?, ?)" ,
        (author, "我住在上海", source_kind, "qq:bot-a:group:1001", bot_id),
    )
    conn.commit()
    return conn


def _candidate(
    *,
    content="我住在上海",
    value="上海",
    predicate="profile.residence",
    polarity="positive",
    statement_kind="self_report",
    user_id="111",
    source_ids=None,
):
    return {
        "user_id": user_id,
        "type": "PREFERENCE" if statement_kind == "explicit_preference" else "FACT",
        "content": content,
        "source_message_ids": source_ids or [1],
        "owner_key": "space:1001",
        "audience": "CURRENT_SPACE",
        "verification_contract": {
            "fact_subject_user_id": user_id,
            "predicate_key": predicate,
            "canonical_value": value,
            "polarity": polarity,
            "statement_kind": statement_kind,
            "temporal_qualifiers": [],
            "context_qualifiers": [],
            "supports": [{"source_message_id": 1, "exact_support_span": content}],
        },
    }


def _assess(conn, candidate, *, allowed=(1,), conversation="qq:bot-a:group:1001", bot="bot-a"):
    return assess_candidate(
        conn,
        candidate,
        group_id=1001,
        allowed_batch_ids=set(allowed),
        expected_conversation_key=conversation,
        expected_bot_id=bot,
    )


def test_exact_self_report_binds_subject_predicate_value_and_source(tmp_path):
    conn = _database(tmp_path)
    result = _assess(conn, _candidate())
    conn.close()

    assert result["status"] == "accepted"
    assert result["fact_subject_key"] == "qq:111"
    assert result["sources"][0]["verification_status"] == "accepted"
    snapshot = result["sources"][0]["snapshot"]
    digest = result["sources"][0]["source_digest"]
    assert source_digest(snapshot) == digest
    assert verify_source_snapshot(snapshot, digest)
    assert not verify_source_snapshot({**snapshot, "content": "改过的来源"}, digest)


def test_explicit_negative_preference_is_bound_to_negative_value(tmp_path):
    conn = _database(tmp_path)
    conn.execute("UPDATE group_messages SET content = '我不喜欢香菜' WHERE id = 1")
    candidate = _candidate(
        content="我不喜欢香菜",
        value="香菜",
        predicate="preference.general",
        polarity="negative",
        statement_kind="explicit_preference",
    )
    result = _assess(conn, candidate)
    conn.close()
    assert result["status"] == "accepted"


@pytest.mark.parametrize(
    ("content", "predicate", "value", "polarity", "statement_kind"),
    [
        ("如果我住在上海", "profile.residence", "上海", "positive", "self_report"),
        ("他说‘我住在上海’", "profile.residence", "上海", "positive", "self_report"),
        ("我住在上海吗？", "profile.residence", "上海", "positive", "self_report"),
        ("我住在上海", "profile.favorite_color", "上海", "positive", "self_report"),
        ("我不喜欢香菜", "preference.general", "香菜", "positive", "explicit_preference"),
    ],
)
def test_ambiguous_or_mismatched_semantics_never_accept(
    tmp_path, content, predicate, value, polarity, statement_kind
):
    conn = _database(tmp_path)
    if content != "我住在上海":
        conn.execute("UPDATE group_messages SET content = ? WHERE id = 1", (content,))
    candidate = _candidate(
        content=content,
        value=value,
        predicate=predicate,
        polarity=polarity,
        statement_kind=statement_kind,
    )
    result = _assess(conn, candidate)
    conn.close()
    assert result["status"] != "accepted"


def test_wrong_author_and_bot_speech_cannot_be_personal_evidence(tmp_path):
    conn = _database(tmp_path, author="222")
    assert _assess(conn, _candidate())["status"] == "unknown"
    conn.execute("UPDATE group_messages SET source_kind = 'BOT_SELF', user_id = '111' WHERE id = 1")
    assert _assess(conn, _candidate())["status"] == "rejected"
    conn.close()


def test_unknown_source_kind_and_missing_bot_binding_fail_closed(tmp_path):
    conn = _database(tmp_path, source_kind="UNREGISTERED")
    assert _assess(conn, _candidate())["status"] == "unknown"
    conn.execute("UPDATE group_messages SET source_kind = 'AT_MENTION', bot_id = '' WHERE id = 1")
    assert _assess(conn, _candidate())["status"] == "unknown"
    conn.close()


def test_source_must_be_in_exact_batch_and_current_conversation(tmp_path):
    conn = _database(tmp_path)
    assert _assess(conn, _candidate(), allowed=())["status"] == "rejected"
    assert _assess(conn, _candidate(), conversation="qq:other:group:1001")["status"] == "rejected"
    conn.close()
