# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.expression_store（设计阶段六的独立存储）的测试。"""

import sqlite3

import memory.expression_store as store


def _setup(monkeypatch, tmp_path):
    db = tmp_path / "expr.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    store.ensure_tables()
    # 让模块内的「已建表」缓存跟随新库（learning 模块持有同名标志）
    import memory.expression_learning as learning

    monkeypatch.setattr(learning, "_tables_ready", True)
    return db


# ============================================================
# expression_examples
# ============================================================


def test_expression_example_roundtrip(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert store.add_expression_example("sp1", 100, "救命这也太好笑了", kind="phrase")
    assert store.add_expression_example("sp1", 100, "😄", kind="emoji")
    # 空串与超长文本直接拒绝
    assert not store.add_expression_example("sp1", 100, "  ")
    assert not store.add_expression_example("sp1", 100, "长" * 61)

    rows = store.list_expression_examples("sp1")
    assert len(rows) == 2
    kinds = {r["kind"] for r in rows}
    assert kinds == {"phrase", "emoji"}
    # 空间隔离
    assert store.list_expression_examples("other") == []


# ============================================================
# jargon_glossary
# ============================================================


def test_jargon_accumulates_and_promotes(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    # 第一批 5 次：入册为候选
    assert store.upsert_jargon("sp1", "yyds", 5, confirm_threshold=12)
    row = store.list_jargon("sp1")[0]
    assert row["hit_count"] == 5 and row["status"] == "candidate"
    # 第二批 7 次：累计 12 → 转正
    store.upsert_jargon("sp1", "yyds", 7, confirm_threshold=12)
    row = store.list_jargon("sp1")[0]
    assert row["hit_count"] == 12 and row["status"] == "confirmed"
    # 已转正不会被后续批次打回候选
    store.upsert_jargon("sp1", "yyds", 1, confirm_threshold=12)
    row = store.list_jargon("sp1")[0]
    assert row["status"] == "confirmed"
    # 无效输入
    assert not store.upsert_jargon("sp1", "", 5, 12)
    assert not store.upsert_jargon("sp1", "x" * 33, 5, 12)


# ============================================================
# behavior_patterns
# ============================================================


def test_pattern_merge_accumulates(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    store.merge_pattern("sp1", 100, "reply_interactions", {"total": 1, "responded": 1})
    store.merge_pattern("sp1", 100, "reply_interactions", {"total": 1, "ignored": 1})
    pat = store.get_pattern("sp1", 100, "reply_interactions")
    assert pat == {"total": 2.0, "responded": 1.0, "ignored": 1.0}
    # 不同用户互不干扰
    assert store.get_pattern("sp1", 200, "reply_interactions") == {}


# ============================================================
# reply_effects
# ============================================================


def test_reply_effect_lifecycle(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    effect_id = store.add_reply_effect(
        group_shared_space="sp1", group_id=1, user_id=100,
        trigger="reply", reply_excerpt="今天也辛苦啦", asked_at_mono=123.456,
    )
    assert effect_id

    row = store.get_reply_effect(effect_id)
    assert row["resolved"] is False and row["outcome"] == ""
    assert row["asked_at_mono"] == 123.456
    assert row["asked_at"]  # 结算要用的时间戳已落库

    assert store.resolve_reply_effect(effect_id, "responded")
    row = store.get_reply_effect(effect_id)
    assert row["resolved"] is True and row["outcome"] == "responded"
    # 重复结算无效
    assert not store.resolve_reply_effect(effect_id, "ignored")

    # 超窗扫描只看未结算行
    eid2 = store.add_reply_effect(
        group_shared_space="sp1", group_id=1, user_id=100,
        trigger="proactive", reply_excerpt="有人在吗", asked_at_mono=0.0,
    )
    stale = store.stale_reply_effects(older_than_mono=100.0)
    assert [r["id"] for r in stale] == [eid2]


def test_prune_respects_keep_days(monkeypatch, tmp_path):
    db = _setup(monkeypatch, tmp_path)
    store.add_expression_example("sp1", 100, "一句话")
    store.resolve_reply_effect(
        store.add_reply_effect(
            group_shared_space="sp1", group_id=1, user_id=100,
            trigger="reply", reply_excerpt="x", asked_at_mono=1.0,
        ),
        "responded",
    )
    # 把时间戳改到很久以前（当前是 2026-09，改到 2026-05 即超 100 天）
    conn = sqlite3.connect(db)
    conn.execute("UPDATE expression_examples SET created_at = '2026-05-01 00:00:00'")
    conn.execute("UPDATE reply_effects SET asked_at = '2026-05-01 00:00:00'")
    conn.commit()
    conn.close()

    out = store.prune(examples_keep_days=30.0, effects_keep_days=60.0)
    assert out["expression_examples"] == 1
    assert out["reply_effects"] == 1
    assert store.list_expression_examples("sp1") == []
