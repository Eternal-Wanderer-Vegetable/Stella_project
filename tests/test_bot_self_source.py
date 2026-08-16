# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Bot 自我发言（BOT_SELF）来源的离线护栏。

覆盖 D1-①：
1. record_message 落库 BOT_SELF；
2. 整合器 _fetch_next_messages 对 BOT_SELF 用「不属于任何用户」标注（不带用户号），
   且该 uid 被排除出 senders 白名单（防止把 Bot 自己的话记成用户属性）；
3. 混合窗口三种来源各自正确标注，at_senders 只含 AT_MENTION 用户；
4. _write_memory_candidates 里 user_id 为 Bot QQ 号、sender_ids 不含它的候选被丢弃。
"""
import asyncio
import sqlite3

import memory.consolidator as consolidator_mod
import memory.pre_processors as pre_processors_mod
from core.context import ChatContext
from memory.consolidator import MemoryConsolidator
from memory.pre_processors import record_message


def _make_db(path, rows):
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
        rows,
    )
    conn.commit()
    conn.close()


def _make_consolidator() -> MemoryConsolidator:
    return MemoryConsolidator.__new__(MemoryConsolidator)


def test_record_message_persists_bot_self(tmp_path, monkeypatch):
    """record_message 传 source_kind=BOT_SELF → 正确落库。"""
    db = tmp_path / "bot_self.db"
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = ChatContext(
        user_id=1000,
        group_id=1,
        msg_id=0,
        message="我在问你问题",
        source_kind="BOT_SELF",
    )
    asyncio.run(record_message(ctx))

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT user_id, content, source_kind FROM group_messages"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "1000"
    assert row[1] == "我在问你问题"
    assert row[2] == "BOT_SELF"


def test_fetch_next_messages_bot_self_marked_and_excluded(tmp_path, monkeypatch):
    """BOT_SELF 行输出「不属于任何用户」（不含用户号），且 uid 不在 senders 白名单。"""
    db = tmp_path / "probe.db"
    _make_db(db, [
        ("1", "1000", "我在问你问题", "BOT_SELF"),
        ("1", "2001", "对", "PASSIVE"),
    ])
    monkeypatch.setattr(consolidator_mod, "DB_PATH", db)
    monkeypatch.setattr(consolidator_mod, "MEMORY_SOURCE_KIND_ENABLED", True)
    monkeypatch.setattr(consolidator_mod, "CONSOLIDATION_OVERLAP", 15)

    text, batch_end, senders, at_senders = _make_consolidator()._fetch_next_messages(1, 0, 10)

    assert batch_end == 2
    assert "消息ID(1) [这是机器人自己发送的消息，不属于任何用户]: 我在问你问题" in text
    assert "用户(1000)" not in text
    assert "消息ID(2) 用户(2001): 对" in text
    assert senders == ["2001"]
    assert at_senders == []


def test_mixed_window_three_markers(tmp_path, monkeypatch):
    """混合窗口：BOT_SELF / AT_MENTION / PASSIVE 三种标注各自正确。"""
    db = tmp_path / "probe.db"
    _make_db(db, [
        ("1", "2001", "我显卡是5080", "AT_MENTION"),
        ("1", "1000", "我在问你", "BOT_SELF"),
        ("1", "2002", "普通发言", "PASSIVE"),
    ])
    monkeypatch.setattr(consolidator_mod, "DB_PATH", db)
    monkeypatch.setattr(consolidator_mod, "MEMORY_SOURCE_KIND_ENABLED", True)
    monkeypatch.setattr(consolidator_mod, "CONSOLIDATION_OVERLAP", 15)

    text, _, senders, at_senders = _make_consolidator()._fetch_next_messages(1, 0, 10)

    assert "消息ID(1) 用户(2001) [对Bot说]: 我显卡是5080" in text
    assert "消息ID(2) [这是机器人自己发送的消息，不属于任何用户]: 我在问你" in text
    assert "消息ID(3) 用户(2002): 普通发言" in text
    assert senders == ["2001", "2002"]
    assert at_senders == ["2001"]


def test_write_memory_candidates_drops_bot_self_candidate(tmp_path, monkeypatch):
    """候选 user_id 为 Bot QQ 号、sender_ids 不含它 → 候选被丢弃。"""
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator_mod, "DB_PATH", db)
    cons = _make_consolidator()
    conn = sqlite3.connect(db)
    cons._ensure_common_tables(conn)
    conn.close()

    cons._write_memory_candidates(
        1001,
        [
            {
                "user_id": "1000",  # Bot 自己的 QQ 号
                "type": "FACT",
                "content": "我自己说的爱好",
                "importance": 0.9,
                "confidence": 0.9,
            },
        ],
        sender_ids=["2001", "2002"],
    )

    conn = sqlite3.connect(db)
    count = conn.execute("SELECT COUNT(*) FROM memory_candidates").fetchone()[0]
    conn.close()
    assert count == 0
