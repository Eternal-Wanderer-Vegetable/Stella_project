# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.expression_learning（设计阶段六的异步学习）的测试。

重点钉住两条不变量：
1. 学习不阻塞主回复路径：on_reply_sent 立即返回，结算在后台；
2. 学习零 LLM、坏不掉主链路：所有异常都被吞成 debug 日志。
"""

import asyncio
import sqlite3

import memory.expression_learning as learning
import memory.expression_store as store
from memory.expression_learning import (
    _extract_expression_candidates,
    _extract_jargon_terms,
    classify_response,
)


def _setup(monkeypatch, tmp_path):
    db = tmp_path / "learn.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    monkeypatch.setattr(learning, "DB_PATH", db)
    monkeypatch.setattr(learning, "_tables_ready", True)
    learning._jargon.clear()
    store.ensure_tables()
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT,
            user_id TEXT,
            content TEXT,
            source_kind TEXT DEFAULT 'PASSIVE',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    return db


def _add_message(db, group_id, user_id, content, minutes_ago=0.0):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind, timestamp) "
        "VALUES (?, ?, ?, 'PASSIVE', datetime('now', ?))",
        (str(group_id), str(user_id), content, f"-{int(minutes_ago)} minutes"),
    )
    conn.commit()
    conn.close()


# ============================================================
# 回复效果分类（纯函数）
# ============================================================


def test_classify_priority_corrected_beats_reuse():
    msgs = ["不对，你说错了，但这个梗真好笑"]
    assert classify_response(["这个梗真好笑"], msgs) == "corrected"


def test_classify_reused_expression():
    # 用户复用了 Stella 台词里的 ≥4 字片段
    assert classify_response(["今天也是元气满满的一天"], ["元气满满的一天！"]) == "reused_expression"


def test_classify_emoji_usage():
    assert classify_response(["好的"], ["收到😄"]) == "emoji"


def test_classify_plain_response_and_ignored():
    assert classify_response(["好的"], ["行吧那就这样"]) == "responded"
    assert classify_response(["好的"], []) == "ignored"


def test_short_overlap_is_not_reuse():
    # <4 字的重合几乎全是常用词，不算复用
    assert classify_response(["我觉得还行"], ["还行吧"]) == "responded"


# ============================================================
# 表达样本提取
# ============================================================


def test_expression_candidates_split_and_filter():
    out = _extract_expression_candidates("救命，这也太好笑了吧哈哈哈哈，我先笑为敬😄")
    phrases = [t for t, k in out if k == "phrase"]
    assert any("好笑" in p for p in phrases)
    assert ("😄", "emoji") in out
    # 过短的碎片不进样本
    assert all(len(t) >= 4 for t, k in out if k == "phrase")


# ============================================================
# 黑话提取与入册
# ============================================================


def test_jargon_terms_latin_and_quoted():
    terms = _extract_jargon_terms('这把yyds，简直是「绝绝子」，thanks!')
    assert "yyds" in terms and "绝绝子" in terms
    # 英文常用词不算黑话
    assert "thanks" not in terms


def test_jargon_threshold_flushes_to_db(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(learning, "JARGON_HIT_THRESHOLD", 3)
    monkeypatch.setattr(learning, "JARGON_CONFIRM_THRESHOLD", 6)

    for _ in range(3):
        learning.note_passive_message("sp1", 100, "这把yyds")
    rows = store.list_jargon("sp1")
    assert len(rows) == 1 and rows[0]["term"] == "yyds"
    assert rows[0]["hit_count"] == 3 and rows[0]["status"] == "candidate"

    # 再来 3 次：累计 6 → 转正
    for _ in range(3):
        learning.note_passive_message("sp1", 200, "yyds！")
    rows = store.list_jargon("sp1")
    assert rows[0]["hit_count"] == 6 and rows[0]["status"] == "confirmed"


def test_jargon_below_threshold_stays_in_memory(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(learning, "JARGON_HIT_THRESHOLD", 5)
    learning.note_passive_message("sp1", 100, "这把xswl")
    learning.note_passive_message("sp1", 100, "xswl笑死")
    assert store.list_jargon("sp1") == []  # 未到门槛不碰库
    assert ("sp1", "xswl") in learning._jargon


# ============================================================
# 端到端：登记 → 延迟结算 → 行为聚合
# ============================================================


def test_on_reply_sent_resolves_and_aggregates(monkeypatch, tmp_path):
    db = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(learning, "REPLY_EFFECT_WINDOW_SECONDS", 0.05)
    monkeypatch.setattr(learning, "EXPRESSION_LEARNING_ENABLED", True)
    monkeypatch.setattr(learning, "EXPRESSION_HARVEST_PER_MESSAGE", 2)

    async def _run():
        learning.on_reply_sent(
            group_id=1, group_shared_space="sp1", user_id=100,
            message="救命，这也太好笑了吧", lines=["哈哈确实很好笑"],
            trigger="reply",
        )
        assert learning.pending_tasks(), "登记后应派生后台任务"
        # 同步部分立即返回：效果行尚未结算
        await asyncio.sleep(0.3)  # 等待窗口（0.05s）+ 后台结算

    asyncio.run(_run())

    rows = store.list_expression_examples("sp1")
    assert rows and any("好笑" in r["text"] for r in rows)

    conn = sqlite3.connect(db)
    resolved, outcome = conn.execute(
        "SELECT resolved, outcome FROM reply_effects"
    ).fetchone()
    conn.close()
    assert resolved == 1
    # 用户在窗口内没有新消息 → ignored
    assert outcome == "ignored"
    pat = store.get_pattern("sp1", 100, "reply_interactions")
    assert pat == {"total": 1.0, "ignored": 1.0}


def test_on_reply_sent_sees_response_after_reply(monkeypatch, tmp_path):
    db = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(learning, "REPLY_EFFECT_WINDOW_SECONDS", 0.05)
    monkeypatch.setattr(learning, "EXPRESSION_LEARNING_ENABLED", True)

    async def _run():
        learning.on_reply_sent(
            group_id=1, group_shared_space="sp1", user_id=100,
            message="在吗", lines=["在的，怎么了呢"],
            trigger="reply",
        )
        # 结算窗口内用户回应（复用了「怎么了呢」这个 4 字片段）
        await asyncio.sleep(0.02)
        _add_message(db, 1, 100, "怎么了呢，没什么大事")
        await asyncio.sleep(0.3)

    asyncio.run(_run())
    conn = sqlite3.connect(db)
    outcome = conn.execute("SELECT outcome FROM reply_effects").fetchone()[0]
    conn.close()
    assert outcome == "reused_expression"


def test_sweep_resolves_stale_rows(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(learning, "EXPRESSION_LEARNING_ENABLED", True)
    # asked_at_mono=0 表示很久以前（monotonic 不会回退）
    effect_id = store.add_reply_effect(
        group_shared_space="sp1", group_id=1, user_id=100,
        trigger="proactive", reply_excerpt="有人在吗", asked_at_mono=0.0,
    )
    assert store.get_reply_effect(effect_id)["resolved"] is False

    swept = learning.sweep_pending_effects()
    assert swept == 1
    assert store.get_reply_effect(effect_id)["resolved"] is True


def test_learning_never_raises(monkeypatch, tmp_path):
    """坏库/坏输入下学习层必须静默：绝不能拖垮主回复路径。

    on_reply_sent 在生产里只会在异步 handler（有事件循环）中被调用，
    这里对齐该前提；存储抛错时登记失败、后台任务照常排空。
    """
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(learning, "EXPRESSION_LEARNING_ENABLED", True)
    monkeypatch.setattr(
        store, "add_reply_effect", lambda **kw: (_ for _ in ()).throw(RuntimeError("db broken"))
    )

    async def _run():
        learning.on_reply_sent(
            group_id=1, group_shared_space="sp1", user_id=1,
            message="hello", lines=["hi"], trigger="reply",
        )
        await asyncio.sleep(0.05)

    asyncio.run(_run())  # 不应抛异常
