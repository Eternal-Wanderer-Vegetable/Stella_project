# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""source_kind（消息来源分级）的离线护栏。


阶段 3 只做落库与格式化，不改变 prompt 语义：被动摄入的消息必须逐字保持
原有格式。这条测试保证以后没人能悄悄给 PASSIVE 消息加上来源标记，
从而在无声中改变发给整合模型的输入。
"""
import sqlite3

from memory.consolidator import MemoryConsolidator


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


def test_passive_messages_get_no_marker(tmp_path, monkeypatch):
    """PASSIVE 消息逐字保持原格式，不得出现任何来源标记。"""
    db = tmp_path / "probe.db"
    _make_db(db, [("1", "1001", "你好", "PASSIVE"), ("1", "1002", "在吗", "PASSIVE")])
    monkeypatch.setattr("memory.consolidator.DB_PATH", db)


    text, batch_end, *_ = MemoryConsolidator()._fetch_next_messages(1, 0, 10)

    assert text.splitlines() == [
        "消息ID(1) 用户(1001): 你好",
        "消息ID(2) 用户(1002): 在吗",
    ]
    assert "[对Bot说]" not in text
    assert batch_end == 2


def test_at_mention_messages_get_marker(tmp_path, monkeypatch):
    """AT_MENTION 消息带 [对Bot说] 标记，且 at_senders 只含 @ 发送者。"""
    db = tmp_path / "probe.db"
    _make_db(db, [
        ("1", "1001", "在吗", "PASSIVE"),
        ("1", "1002", "我的显卡是5080", "AT_MENTION"),
    ])
    monkeypatch.setattr("memory.consolidator.DB_PATH", db)

    result = MemoryConsolidator()._fetch_next_messages(1, 0, 10)
    text = result[0]

    assert "消息ID(1) 用户(1001): 在吗" in text
    assert "消息ID(2) 用户(1002) [对Bot说]: 我的显卡是5080" in text
    # 第 4 个返回值为 at_senders（阶段 3 新增）
    assert result[3] == ["1002"]
