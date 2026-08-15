# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""proactive_state（主动发言持久化状态）的单元测试。

覆盖 D1-③：配额计数递增、跨日归零、consecutive_no_reply 增减、
count_user_messages_24h 排除 BOT_SELF、表不存在时返回默认值不抛异常。
全部用临时库，不触网。
"""
import sqlite3

import pytest

from memory import proactive_state
from memory.proactive_state import (
    get_runtime_state,
    mark_announced,
    set_proactive_muted,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """临时库：把 proactive_state 与 schema 的 DB_PATH 一起指向它。"""
    path = tmp_path / "runtime.db"
    monkeypatch.setattr(proactive_state, "DB_PATH", path)
    import memory.schema as schema

    monkeypatch.setattr(schema, "DB_PATH", path)
    return path


def test_at_count_increments(tmp_path, monkeypatch):
    """record_at 每次 +1，last_asked_topic 与 candidate_id 同步刷新。"""
    db = tmp_path / "ps.db"
    monkeypatch.setattr(proactive_state, "DB_PATH", db)

    proactive_state.record_at(1, 2001, topic="上次聊过什么", candidate_id="abc")
    proactive_state.record_at(1, 2001, topic="又聊一次")

    state = proactive_state.get_state(1, 2001)
    assert state["at_count_today"] == 2
    assert state["last_asked_topic"] == "又聊一次"
    assert state["last_asked_candidate_id"] == ""

    # 不同用户独立计数
    assert proactive_state.get_state(1, 2002)["at_count_today"] == 0


def test_cross_day_resets_count(tmp_path, monkeypatch):
    """跨自然日后 at_count_today 读时归零（不依赖定时任务）。"""
    db = tmp_path / "ps.db"
    monkeypatch.setattr(proactive_state, "DB_PATH", db)

    proactive_state.record_at(1, 2001)
    assert proactive_state.get_state(1, 2001)["at_count_today"] == 1

    # 模拟跨日：_today 指向另一天，读取时计数归零
    monkeypatch.setattr(proactive_state, "_today", lambda: "2099-01-01")
    assert proactive_state.get_state(1, 2001)["at_count_today"] == 0


def test_consecutive_no_reply_increment_and_reset(tmp_path, monkeypatch):
    """无回应 +1，有回应归零。先 record_at 建行（真实链路：先问才谈回应）。"""
    db = tmp_path / "ps.db"
    monkeypatch.setattr(proactive_state, "DB_PATH", db)

    proactive_state.record_at(1, 2001)
    proactive_state.record_reply_result(1, 2001, replied=False)
    proactive_state.record_reply_result(1, 2001, replied=False)
    assert proactive_state.get_state(1, 2001)["consecutive_no_reply"] == 2

    proactive_state.record_reply_result(1, 2001, replied=True)
    assert proactive_state.get_state(1, 2001)["consecutive_no_reply"] == 0


def test_count_user_messages_24h_excludes_bot_self(tmp_path, monkeypatch):
    """24h 计数只算用户发言，BOT_SELF 不计入。"""
    db = tmp_path / "count.db"
    monkeypatch.setattr(proactive_state, "DB_PATH", db)
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
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind) VALUES (?, ?, ?, ?)",
        [
            ("1", "2001", "用户发言一", "PASSIVE"),
            ("1", "2001", "用户@发言", "AT_MENTION"),
            ("1", "2001", "Bot 自己的话", "BOT_SELF"),
            ("1", "2002", "别的用户", "PASSIVE"),
        ],
    )
    conn.commit()
    conn.close()

    assert proactive_state.count_user_messages_24h(1, 2001) == 2
    assert proactive_state.count_user_messages_24h(1, 2002) == 1


def test_missing_table_returns_defaults_without_error(tmp_path, monkeypatch):
    """空库（无 proactive_state / group_messages 表）时返回保守默认值，不抛异常。"""
    db = tmp_path / "empty.db"
    monkeypatch.setattr(proactive_state, "DB_PATH", db)

    state = proactive_state.get_state(1, 2001)
    assert state["at_count_today"] == 0
    assert state["consecutive_no_reply"] == 0
    assert state["last_asked_topic"] == ""
    # count_user_messages_24h 读表缺失 → 0，不打断主动发言链路
    assert proactive_state.count_user_messages_24h(1, 2001) == 0


# ── 群级运行时状态（静音开关 / 播报去重） ──────────────

def test_runtime_state_defaults_without_record(db):
    """无记录时返回默认值：未静音、无播报记录。"""
    state = get_runtime_state(1)
    assert state["proactive_muted"] is False
    assert state["last_sleep_announce_date"] == ""
    assert state["last_wakeup_announce_date"] == ""


def test_set_proactive_muted_persists(db):
    """静音开关落库，可跨调用读取；恢复后写回 False。"""
    set_proactive_muted(1, True, operator_id=1001)
    state = get_runtime_state(1)
    assert state["proactive_muted"] is True
    assert state["muted_by"] == "1001"
    assert state["muted_at"] is not None

    set_proactive_muted(1, False, operator_id=1001)
    assert get_runtime_state(1)["proactive_muted"] is False


def test_muted_is_per_group(db):
    """静音按群独立，不互相影响。"""
    set_proactive_muted(1, True)
    assert get_runtime_state(1)["proactive_muted"] is True
    assert get_runtime_state(2)["proactive_muted"] is False


def test_mark_announced_writes_matching_column(db):
    """sleep / wakeup 分别写入各自的列，互不覆盖。"""
    mark_announced(1, "sleep", "2026-08-15")
    state = get_runtime_state(1)
    assert state["last_sleep_announce_date"] == "2026-08-15"
    assert state["last_wakeup_announce_date"] == ""

    mark_announced(1, "wakeup", "2026-08-16")
    state = get_runtime_state(1)
    assert state["last_sleep_announce_date"] == "2026-08-15"
    assert state["last_wakeup_announce_date"] == "2026-08-16"


def test_runtime_state_survives_missing_table(tmp_path, monkeypatch):
    """DB 文件不存在时不抛异常，返回默认值。"""
    monkeypatch.setattr("memory.proactive_state.DB_PATH", tmp_path / "nonexistent.db")
    assert get_runtime_state(1)["proactive_muted"] is False
