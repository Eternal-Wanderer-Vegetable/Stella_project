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
    cur.execute("CREATE TABLE consolidation_state (group_id TEXT, last_processed_id INTEGER, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
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


def _insert_messages(conn: sqlite3.Connection, group_id: str, count: int) -> None:
    for i in range(count):
        conn.execute(
            "INSERT INTO group_messages (group_id, user_id, content) VALUES (?, '100', ?)",
            (group_id, "msg" + str(i)),
        )
        conn.execute(
            "INSERT INTO messages (group_id, user_id, content) VALUES (?, '100', ?)",
            (group_id, "msg" + str(i)),
        )


def _read_checkpoint(conn: sqlite3.Connection, group_id: str) -> int:
    row = conn.execute(
        "SELECT last_processed_id FROM consolidation_state WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    return row[0] if row else 0


def test_trim_aligns_checkpoint(tmp_path, monkeypatch):
    """回归 2026-08-15：清理旧消息后 checkpoint 必须对齐，否则会重复整理。"""
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)
    monkeypatch.setattr(db_cleaner, "_LAST_CLEANUP_FILE", tmp_path / ".last_message_cleanup")
    # 关闭保护以覆盖「按条数裁剪 → 对齐 checkpoint」的原路径
    monkeypatch.setattr(db_cleaner, "MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED", False)

    conn = sqlite3.connect(db_path)
    _insert_messages(conn, "2", 100)
    conn.execute("INSERT INTO consolidation_state (group_id, last_processed_id) VALUES ('2', 50)")
    conn.commit()
    conn.close()

    db_cleaner.trim_group_messages(keep_count=10)

    conn = sqlite3.connect(db_path)
    min_id = conn.execute(
        "SELECT MIN(id) FROM group_messages WHERE group_id = '2'"
    ).fetchone()[0]
    checkpoint_after = _read_checkpoint(conn, "2")
    conn.close()

    # 实际裁剪规则：cutoff = 第 keep_count 条新消息的 id（此处 91），
    # 删除 id <= 91 后剩 92~100，因此 min_id=92、checkpoint 抬到 min_id-1=91
    assert min_id == 92
    assert checkpoint_after == min_id - 1


def test_align_checkpoint_clamps_when_too_large(tmp_path, monkeypatch):
    """checkpoint 大于最大 id（清空消息 + 重置序列后）时压到最大 id，
    否则 `id > checkpoint` 永远为空，整合彻底停摆。"""
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    _insert_messages(conn, "3", 5)
    conn.execute("INSERT INTO consolidation_state (group_id, last_processed_id) VALUES ('3', 10)")
    conn.commit()

    result = db_cleaner._align_checkpoint(conn.cursor(), "3")
    conn.commit()
    checkpoint_after = _read_checkpoint(conn, "3")
    conn.close()

    assert result == 5
    assert checkpoint_after == 5


def test_align_checkpoint_zeroes_on_empty_table(tmp_path, monkeypatch):
    """消息被清空时 checkpoint 归零。"""
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO consolidation_state (group_id, last_processed_id) VALUES ('4', 20)")
    conn.commit()

    result = db_cleaner._align_checkpoint(conn.cursor(), "4")
    conn.commit()
    checkpoint_after = _read_checkpoint(conn, "4")
    conn.close()

    assert result == 0
    assert checkpoint_after == 0


def test_align_is_idempotent(tmp_path, monkeypatch):
    """已对齐的 checkpoint 不再被改动。"""
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    _insert_messages(conn, "5", 5)
    conn.execute("INSERT INTO consolidation_state (group_id, last_processed_id) VALUES ('5', 5)")
    conn.commit()

    r1 = db_cleaner._align_checkpoint(conn.cursor(), "5")
    conn.commit()
    r2 = db_cleaner._align_checkpoint(conn.cursor(), "5")
    conn.commit()
    checkpoint_after = _read_checkpoint(conn, "5")
    conn.close()

    assert r1 == 5
    assert r2 == 5
    assert checkpoint_after == 5
    # 批量对齐同样不产生任何调整
    assert db_cleaner.align_all_checkpoints() == 0


def test_align_all_checkpoints_handles_multiple_groups(tmp_path, monkeypatch):
    """多群各自独立对齐，互不影响。"""
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    _insert_messages(conn, "a", 10)
    _insert_messages(conn, "b", 10)
    conn.execute("INSERT INTO consolidation_state (group_id, last_processed_id) VALUES ('a', 3)")
    conn.execute("INSERT INTO consolidation_state (group_id, last_processed_id) VALUES ('b', 999)")
    conn.execute("INSERT INTO consolidation_state (group_id, last_processed_id) VALUES ('c', 7)")
    conn.commit()
    conn.close()

    adjusted = db_cleaner.align_all_checkpoints()

    conn = sqlite3.connect(db_path)
    checkpoint_a = _read_checkpoint(conn, "a")
    checkpoint_b = _read_checkpoint(conn, "b")
    checkpoint_c = _read_checkpoint(conn, "c")
    conn.close()

    assert adjusted == 2
    assert checkpoint_a == 3  # 范围内，未改动
    assert checkpoint_b == 20  # 过大 → 压到最大 id（b 的消息 id 为 11~20）
    assert checkpoint_c == 0  # 无消息 → 归零


def test_align_all_checkpoints_missing_db(tmp_path, monkeypatch):
    """数据库不存在时返回 0。"""
    monkeypatch.setattr(db_cleaner, "DB_PATH", tmp_path / "not_exist.db")
    assert db_cleaner.align_all_checkpoints() == 0


def test_trim_protects_unconsolidated_messages(tmp_path, monkeypatch):
    """积压超过 keep_count 时，清理边界被收紧到 checkpoint，未整合消息保留。"""
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)
    monkeypatch.setattr(db_cleaner, "_LAST_CLEANUP_FILE", tmp_path / ".last_message_cleanup")
    monkeypatch.setattr(db_cleaner, "MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED", True)

    conn = sqlite3.connect(db_path)
    _insert_messages(conn, "6", 20)
    conn.execute("INSERT INTO consolidation_state (group_id, last_processed_id) VALUES ('6', 5)")
    conn.commit()
    conn.close()

    db_cleaner.trim_group_messages(keep_count=15)

    conn = sqlite3.connect(db_path)
    min_id = conn.execute(
        "SELECT MIN(id) FROM group_messages WHERE group_id = '6'"
    ).fetchone()[0]
    remaining = conn.execute(
        "SELECT COUNT(*) FROM group_messages WHERE group_id = '6'"
    ).fetchone()[0]
    checkpoint_after = _read_checkpoint(conn, "6")
    conn.close()

    # 按条数 cutoff=6 落在未整合区间（checkpoint=5）内 → 收紧到 5，id 6~20 全部保留
    assert min_id == 6
    assert remaining == 15
    assert checkpoint_after == 5


def test_trim_without_protection_deletes_unconsolidated(tmp_path, monkeypatch):
    """MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED=False 时按原逻辑删除。"""
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)
    monkeypatch.setattr(db_cleaner, "_LAST_CLEANUP_FILE", tmp_path / ".last_message_cleanup")
    monkeypatch.setattr(db_cleaner, "MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED", False)

    conn = sqlite3.connect(db_path)
    _insert_messages(conn, "7", 20)
    conn.execute("INSERT INTO consolidation_state (group_id, last_processed_id) VALUES ('7', 5)")
    conn.commit()
    conn.close()

    db_cleaner.trim_group_messages(keep_count=15)

    conn = sqlite3.connect(db_path)
    min_id = conn.execute(
        "SELECT MIN(id) FROM group_messages WHERE group_id = '7'"
    ).fetchone()[0]
    remaining = conn.execute(
        "SELECT COUNT(*) FROM group_messages WHERE group_id = '7'"
    ).fetchone()[0]
    conn.close()

    # 原逻辑：cutoff=6，删除 id ≤ 6（含未整合的 id 6）
    assert min_id == 7
    assert remaining == 14


def test_trim_protection_keeps_boundary_when_no_backlog(tmp_path, monkeypatch):
    """checkpoint 大于按条数算出的 cutoff 时，边界不变（无需收紧）。"""
    db_path = tmp_path / "agent_memory.db"
    _create_full_db(db_path)
    monkeypatch.setattr(db_cleaner, "DB_PATH", db_path)
    monkeypatch.setattr(db_cleaner, "_LAST_CLEANUP_FILE", tmp_path / ".last_message_cleanup")
    monkeypatch.setattr(db_cleaner, "MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED", True)

    conn = sqlite3.connect(db_path)
    _insert_messages(conn, "8", 20)
    conn.execute("INSERT INTO consolidation_state (group_id, last_processed_id) VALUES ('8', 15)")
    conn.commit()
    conn.close()

    db_cleaner.trim_group_messages(keep_count=10)

    conn = sqlite3.connect(db_path)
    min_id = conn.execute(
        "SELECT MIN(id) FROM group_messages WHERE group_id = '8'"
    ).fetchone()[0]
    checkpoint_after = _read_checkpoint(conn, "8")
    conn.close()

    # cutoff=11 < checkpoint=15，无需收紧，按原规则删 id ≤ 11；checkpoint 保持 15
    assert min_id == 12
    assert checkpoint_after == 15
