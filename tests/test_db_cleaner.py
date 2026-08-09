# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.db_cleaner 数据库清理工具的测试。

把 db_cleaner.DB_PATH / _LAST_CLEANUP_FILE 指向 tmp_path 下的临时库，
验证 clean_db / trim_group_messages / needs_cleanup / print_summary 等行为。
"""

import sqlite3
import time
from pathlib import Path

import memory.db_cleaner as db_cleaner


def _create_full_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE short_term_context (group_id TEXT, active_summary TEXT)")
    cur.execute("CREATE TABLE long_term_memories (group_id TEXT, user_id TEXT, summary TEXT)")
    cur.execute("CREATE TABLE memory_candidates (id TEXT)")
    cur.execute("CREATE TABLE memories (id TEXT, content TEXT)")
    cur.execute("CREATE TABLE atomic_facts (id TEXT)")
    cur.execute("CREATE TABLE memory_traces (id INTEGER)")
    cur.execute("CREATE TABLE consolidation_state (group_id TEXT, last_processed_id INTEGER)")
    cur.execute("CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT)")
    cur.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT)")
    conn.commit()
    return conn


def test_clean_db_clears_tables_and_resets_seq(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO short_term_context VALUES ('1', '摘要')")
    conn.execute("INSERT INTO group_messages (group_id, user_id, content) VALUES ('1', '100', '你好')")
    conn.commit()
    conn.close()

    results = db_cleaner.clean_db(clear_messages=True)
    assert results["short_term_context"] == 1
    assert results["group_messages"] == 1


def test_clean_db_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(db_cleaner, "DB_PATH", tmp_path / "not_exist.db")
    import pytest
    with pytest.raises(FileNotFoundError):
        db_cleaner.clean_db()


def test_trim_group_messages_keeps_recent(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)
    monkeypatch.setattr(db_cleaner, "_LAST_CLEANUP_FILE", tmp_path / ".last_message_cleanup")

    conn = sqlite3.connect(db_path)
    for i in range(5):
        conn.execute(
            "INSERT INTO group_messages (group_id, user_id, content) VALUES ('2', '100', ?)",
            ("msg" + str(i),),
        )
        conn.execute(
            "INSERT INTO messages (group_id, user_id, content) VALUES ('2', '100', ?)",
            ("msg" + str(i),),
        )
    conn.commit()
    conn.close()

    result = db_cleaner.trim_group_messages(keep_count=2)
    assert result["groups"] == 1
    assert result["deleted"] >= 6

    remaining = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM group_messages").fetchone()[0]
    assert remaining == 1
    assert (tmp_path / ".last_message_cleanup").exists()


def test_trim_group_messages_missing_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_cleaner, "DB_PATH", tmp_path / "not_exist.db")
    assert db_cleaner.trim_group_messages() == {"deleted": 0, "groups": 0}


def test_needs_cleanup_logic(tmp_path, monkeypatch):
    marker = tmp_path / ".last_message_cleanup"
    monkeypatch.setattr(db_cleaner, "_LAST_CLEANUP_FILE", marker)
    assert db_cleaner.needs_cleanup() is True
    marker.write_text(str(time.time()))
    assert db_cleaner.needs_cleanup() is False
    old_timestamp = str(time.time() - 10 * 3600)
    marker.write_text(old_timestamp)
    assert db_cleaner.needs_cleanup(max_age_hours=0.0) is True
    marker.write_text("not-a-number")
    assert db_cleaner.needs_cleanup() is True


def test_print_summary_runs(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)
    db_cleaner.print_summary()
    captured = capsys.readouterr()
    assert "[DB]" in captured.out


def test_mark_cleanup_done_handles_error(tmp_path, monkeypatch):
    marker = tmp_path / "no_dir" / "x"
    monkeypatch.setattr(db_cleaner, "_LAST_CLEANUP_FILE", marker)
    db_cleaner._mark_cleanup_done()