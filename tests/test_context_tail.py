# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""build_context 摘要与原始尾巴并存（2026-08-13 bug）的回归护栏。

覆盖：
1. 库里有摘要 + 原始消息 → short_term 同时含摘要与「最近的对话」，且不含「近期关键发言」；
2. 有摘要但无原始消息 → 回退到 recent_exchanges（「近期关键发言」）；
3. BOT_SELF 消息渲染为「我: xxx」，不带 QQ 号；
4. 尾巴按时间正序（最早的在前）；
回归：`[BOT_SELF: 你平时用手机还是电脑, 用户: 手机]` 中「我: 你平时用手机还是电脑」
必须出现在「用户(...): 手机」之前——这正是当时缺失的那一行。
"""
import asyncio
import json
import sqlite3

import memory.pre_processors as pre_processors_mod
from core.context import ChatContext
from memory.pre_processors import build_context


def _make_db(path, messages, summary=None, exchanges=None):
    conn = sqlite3.connect(path)
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
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind) VALUES (?, ?, ?, ?)",
        messages,
    )
    if summary is not None or exchanges is not None:
        conn.execute("""
            CREATE TABLE short_term_context (
                group_id TEXT PRIMARY KEY,
                active_summary TEXT,
                pending_topic TEXT,
                recent_exchanges TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO short_term_context (group_id, active_summary, pending_topic, recent_exchanges, updated_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (
                "1",
                summary or "",
                "无",
                json.dumps(exchanges, ensure_ascii=False) if exchanges else None,
            ),
        )
    conn.commit()
    conn.close()


def _run(db_path, **monkeypatch):
    ctx = ChatContext(user_id=1000, group_id=1, msg_id=0, message="手机")
    return asyncio.run(build_context(ctx)), ctx


def test_summary_and_tail_coexist(tmp_path, monkeypatch):
    """摘要 + 原始消息 → 同时含摘要与「最近的对话」，且不含「近期关键发言」。"""
    db = tmp_path / "ctx.db"
    _make_db(
        db,
        [("1", "1000", "你平时用手机还是电脑", "BOT_SELF"), ("1", "2001", "手机", "PASSIVE")],
        summary="用户偏好手机",
    )
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="手机")))

    assert "对话摘要: 用户偏好手机" in ctx.short_term
    assert "最近的对话" in ctx.short_term
    assert "近期关键发言" not in ctx.short_term


def test_no_tail_falls_back_to_exchanges(tmp_path, monkeypatch):
    """有摘要但无原始消息 → 回退到 recent_exchanges（「近期关键发言」）。"""
    db = tmp_path / "ctx.db"
    _make_db(
        db,
        [],
        summary="用户偏好手机",
        exchanges=[{"user_id": "2001", "content": "我一直用手机"}],
    )
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="手机")))

    assert "对话摘要: 用户偏好手机" in ctx.short_term
    assert "近期关键发言" in ctx.short_term
    assert "用户(2001): 我一直用手机" in ctx.short_term
    assert "最近的对话" not in ctx.short_term


def test_bot_self_rendered_as_wo(tmp_path, monkeypatch):
    """BOT_SELF 渲染为「我: xxx」，不带 QQ 号。"""
    db = tmp_path / "ctx.db"
    _make_db(db, [("1", "1000", "我在问你问题", "BOT_SELF")])
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="")))

    assert "我: 我在问你问题" in ctx.short_term
    assert "1000" not in ctx.short_term


def test_tail_in_time_order(tmp_path, monkeypatch):
    """尾巴按时间正序：最早的在前。"""
    db = tmp_path / "ctx.db"
    _make_db(
        db,
        [
            ("1", "2001", "第一条", "PASSIVE"),
            ("1", "1000", "第二条", "BOT_SELF"),
            ("1", "2002", "第三条", "PASSIVE"),
        ],
    )
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="")))

    pos_first = ctx.short_term.index("用户(2001): 第一条")
    pos_second = ctx.short_term.index("我: 第二条")
    pos_third = ctx.short_term.index("用户(2002): 第三条")
    assert pos_first < pos_second < pos_third


def test_bot_question_precedes_user_reply(tmp_path, monkeypatch):
    """回归 2026-08-13：Bot 的提问必须出现在用户回答之前，否则模型会接错话题。"""
    db = tmp_path / "ctx.db"
    _make_db(
        db,
        [("1", "1000", "你平时是用手机玩游戏还是电脑呀", "BOT_SELF"), ("1", "1001", "手机", "PASSIVE")],
    )
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="手机")))

    st = ctx.short_term
    assert st.index("我: 你平时是用手机玩游戏还是电脑呀") < st.index("用户(1001): 手机")


# ── 时间窗过滤 / 断层标记 / 摘要新鲜度 ────────────────

def _make_ctx(group_id: int = 1, user_id: int = 1001) -> ChatContext:
    return ChatContext(user_id=user_id, group_id=group_id, msg_id=0, message="手机")


def _insert_message(conn, group_id, user_id, content, source_kind, minutes_ago):
    """插入一条指定「多少分钟前」的消息（timestamp 按 UTC 写入，与生产一致）。"""
    from datetime import timedelta

    from memory.timeutil import utc_now

    ts = (utc_now() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind, timestamp) "
        "VALUES (?, ?, ?, ?, ?)",
        (str(group_id), str(user_id), content, source_kind, ts),
    )


def test_stale_messages_excluded_from_tail(tmp_path, monkeypatch):
    """回归 2026-08-15：停机数小时后重启，旧消息不得被当成「最近的对话」。"""
    monkeypatch.setattr(pre_processors_mod, "RECENT_TAIL_MAX_AGE_MINUTES", 45.0)
    db = tmp_path / "ctx.db"
    _make_db(db, [])
    conn = sqlite3.connect(db)
    _insert_message(conn, 1, 1001, "五小时前说的话", "PASSIVE", 300)
    _insert_message(conn, 1, 1001, "刚刚说的话", "PASSIVE", 1)
    conn.commit()
    conn.close()
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)

    ctx = asyncio.run(build_context(_make_ctx(1, 1001)))
    assert "刚刚说的话" in ctx.short_term
    assert "五小时前说的话" not in ctx.short_term


def test_gap_marker_inserted_within_window(tmp_path, monkeypatch):
    """窗口内部存在时间空白时插入断层标记（不丢弃，只标注）。"""
    monkeypatch.setattr(pre_processors_mod, "RECENT_TAIL_MAX_AGE_MINUTES", 120.0)
    monkeypatch.setattr(pre_processors_mod, "RECENT_TAIL_GAP_MARK_MINUTES", 15.0)
    db = tmp_path / "ctx.db"
    _make_db(db, [])
    conn = sqlite3.connect(db)
    _insert_message(conn, 1, 1001, "早一点的话", "PASSIVE", 90)
    _insert_message(conn, 1, 1002, "现在的话", "PASSIVE", 1)
    conn.commit()
    conn.close()
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)

    st = asyncio.run(build_context(_make_ctx(1, 1001))).short_term
    assert "早一点的话" in st and "现在的话" in st
    assert "中间隔了" in st
    # 断层标记必须位于两条消息之间
    assert st.index("早一点的话") < st.index("中间隔了") < st.index("现在的话")


def test_no_gap_marker_when_continuous(tmp_path, monkeypatch):
    """连续对话不插入断层标记。"""
    monkeypatch.setattr(pre_processors_mod, "RECENT_TAIL_GAP_MARK_MINUTES", 15.0)
    db = tmp_path / "ctx.db"
    _make_db(db, [])
    conn = sqlite3.connect(db)
    _insert_message(conn, 1, 1001, "第一句", "PASSIVE", 3)
    _insert_message(conn, 1, 1002, "第二句", "PASSIVE", 2)
    conn.commit()
    conn.close()
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)

    assert "中间隔了" not in asyncio.run(build_context(_make_ctx(1, 1001))).short_term


def test_stale_summary_relabeled(tmp_path, monkeypatch):
    """过期摘要改用「之前的话题」标题并注明时长。"""
    monkeypatch.setattr(pre_processors_mod, "SHORT_TERM_SUMMARY_STALE_MINUTES", 60.0)
    from datetime import timedelta

    from memory.timeutil import utc_now

    old = (utc_now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
    db = tmp_path / "ctx.db"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE short_term_context (
            group_id TEXT PRIMARY KEY,
            active_summary TEXT,
            pending_topic TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO short_term_context (group_id, active_summary, pending_topic, updated_at) "
        "VALUES ('1', '在聊显卡', '选购建议', ?)",
        (old,),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)

    st = asyncio.run(build_context(_make_ctx(1, 1001))).short_term
    assert "之前的话题" in st and "小时前" in st
    assert "对话摘要:" not in st
    assert "之前未聊完的话题" in st


def test_fresh_summary_keeps_original_label(tmp_path, monkeypatch):
    """新鲜摘要保持原标题。"""
    db = tmp_path / "ctx.db"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE short_term_context (
            group_id TEXT PRIMARY KEY,
            active_summary TEXT,
            pending_topic TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO short_term_context (group_id, active_summary, pending_topic, updated_at) "
        "VALUES ('1', '在聊显卡', '选购建议', CURRENT_TIMESTAMP)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)

    st = asyncio.run(build_context(_make_ctx(1, 1001))).short_term
    assert "对话摘要:" in st and "进行中的话题:" in st
    assert "之前的话题" not in st


def test_timestamp_unparseable_not_filtered(tmp_path, monkeypatch):
    """时间戳无法解析时不过滤（旧库兼容），保留原有行为。"""
    monkeypatch.setattr(pre_processors_mod, "RECENT_TAIL_MAX_AGE_MINUTES", 1.0)
    db = tmp_path / "ctx.db"
    _make_db(db, [])
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind, timestamp) "
        "VALUES ('1', '1001', '无时间戳的消息', 'PASSIVE', NULL)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)

    assert "无时间戳的消息" in asyncio.run(build_context(_make_ctx(1, 1001))).short_term


def test_tail_start_id_returned(tmp_path):
    """尾巴起点 id 用于会话压缩的区间计算，必须是第一条真正进入尾巴的消息。"""
    db = tmp_path / "ctx.db"
    _make_db(db, [])
    conn = sqlite3.connect(db)
    for i in range(1, 6):
        _insert_message(conn, 1, 1001, f"第{i}句", "PASSIVE", 1)
    conn.commit()
    cursor = conn.cursor()

    from memory.pre_processors import _fetch_recent_tail

    text, start_id = _fetch_recent_tail(cursor, 1, limit=3)
    assert start_id == 3           # 取最近 3 条 → id 3,4,5
    assert "第3句" in text and "第2句" not in text
    conn.close()


def test_tail_start_id_skips_filtered_messages(tmp_path, monkeypatch):
    """被时间窗过滤掉的消息不算尾巴起点——它们应归入待压缩区间。"""
    monkeypatch.setattr("memory.pre_processors.RECENT_TAIL_MAX_AGE_MINUTES", 45.0)
    db = tmp_path / "ctx.db"
    _make_db(db, [])
    conn = sqlite3.connect(db)
    _insert_message(conn, 1, 1001, "很久以前", "PASSIVE", 300)
    _insert_message(conn, 1, 1001, "刚刚", "PASSIVE", 1)
    conn.commit()
    cursor = conn.cursor()

    from memory.pre_processors import _fetch_recent_tail

    _, start_id = _fetch_recent_tail(cursor, 1, limit=10)
    assert start_id == 2
    conn.close()


def test_session_summary_precedes_tail(tmp_path, monkeypatch):
    """会话摘要必须出现在尾巴之前（与时间顺序一致）。"""
    from memory import session_context as sc

    sc.reset_state()
    monkeypatch.setattr(sc, "SESSION_CONTEXT_ENABLED", True)

    db = tmp_path / "ctx.db"
    _make_db(db, [])
    conn = sqlite3.connect(db)
    _insert_message(conn, 1, 1001, "最近的一句", "PASSIVE", 1)
    conn.commit()
    conn.close()
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)

    sc.ensure_initialized(1, 1)
    sc.apply_summary(1, "之前聊过显卡", up_to_id=1)

    st = asyncio.run(build_context(_make_ctx(1, 1001))).short_term
    assert "本场对话较早的内容" in st
    assert st.index("之前聊过显卡") < st.index("最近的一句")
    sc.reset_state()
