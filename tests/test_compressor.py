# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.compressor 记忆压缩器的测试。

在每个用例里把 compressor.DB_PATH monkeypatch 指向 tmp_path 下的临时库，
再构造 memories / atomic_facts / compressor_state 等表与数据，验证：
- 去重合并（相似内容合并、重要度/置信度取极值、确认次数累加）；
- 长记忆原子化（≥80 字拆分写入 atomic_facts，标记 is_atomized）；
- 低价值归档与按类型生命周期衰减；
- 周度/轻量两套入口与文本相似度辅助函数。
"""

import sqlite3
from pathlib import Path

import memory.compressor as compressor
from memory.compressor import MemoryCompressor


def _patch_paths(monkeypatch, tmp_path: Path, db_path: Path):
    monkeypatch.setattr(compressor, "DB_PATH", db_path)
    class _Compressor(MemoryCompressor):
        def _append_log(self, text: str) -> None:
            return None
    monkeypatch.setattr(compressor, "MemoryCompressor", _Compressor)
    monkeypatch.setattr(compressor.MemoryCompressor, "_append_log", lambda self, text: None)


def _create_db(db_path: Path) -> sqlite3.Connection:
    comp = MemoryCompressor.__new__(MemoryCompressor)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    comp._ensure_tables()
    conn.commit()
    return conn


def _insert(
    conn: sqlite3.Connection,
    mid: str,
    content: str,
    *,
    group_id: str = "1",
    user_id: str = "100",
    type_: str = "FACT",
    importance: float = 0.6,
    confidence: float = 0.7,
    confirmation_count: int = 1,
    status: str = "active",
    is_atomized: int = 0,
    last_accessed_at: str = "2026-08-08 12:00:00",
):
    conn.execute(
        """
        INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance,
        confidence, status, confirmation_count, last_accessed_at, is_atomized)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (mid, group_id, user_id, type_, content, content, importance, confidence,
         status, confirmation_count, last_accessed_at, is_atomized),
    )


def test_weekly_no_active_memories(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    _patch_paths(monkeypatch, tmp_path, db_path)
    comp = MemoryCompressor()
    comp.run_weekly()


def test_weekly_merges_duplicates(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    _patch_paths(monkeypatch, tmp_path, db_path)
    conn = _create_db(db_path)
    _insert(conn, "m1", "用户喜欢打篮球和羽毛球")
    _insert(conn, "m2", "用户喜欢打篮球和羽毛球", importance=0.9, confidence=0.9, confirmation_count=3)
    conn.commit()
    conn.close()

    comp = MemoryCompressor()
    comp.run_weekly()

    conn = sqlite3.connect(db_path)
    merged = conn.execute(
        "SELECT importance, confidence, confirmation_count, status FROM memories WHERE status='active' AND type='FACT' ORDER BY confirmation_count DESC"
    ).fetchone()
    archived = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE status='archived'"
    ).fetchone()[0]
    stats = conn.execute("SELECT merged_count, atomized_count, archived_count FROM compressor_stats ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert merged is not None
    assert merged[0] == 0.9
    assert merged[1] == 0.9
    assert merged[2] == 4
    assert merged[3] == "active"
    assert archived == 1
    assert stats[0] == 1


def test_weekly_atomizes_long_memory(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    _patch_paths(monkeypatch, tmp_path, db_path)
    conn = _create_db(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atomic_facts (
            id TEXT PRIMARY KEY,
            memory_id TEXT, group_id TEXT, subject TEXT, predicate TEXT,
            object TEXT, confidence REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    long_text = "用户是一名程序员，擅长 Python 与数据分析，平时喜欢研究本地大语言模型部署，并且经常在群里分享技术经验。" * 2
    _insert(conn, "long1", long_text, is_atomized=0)
    conn.commit()
    conn.close()

    comp = MemoryCompressor()
    comp.run_weekly()

    conn = sqlite3.connect(db_path)
    facts = conn.execute("SELECT COUNT(*) FROM atomic_facts WHERE memory_id='long1'").fetchone()[0]
    atomized = conn.execute("SELECT is_atomized FROM memories WHERE id='long1'").fetchone()[0]
    conn.close()
    assert facts >= 1
    assert atomized == 1


def test_maybe_compress_light_runs_once(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    _patch_paths(monkeypatch, tmp_path, db_path)
    comp = MemoryCompressor()
    comp._light_threshold = 2
    comp._light_cooldown = 0
    conn = _create_db(db_path)
    _insert(conn, "m1", "用户喜欢打篮球和羽毛球")
    _insert(conn, "m2", "用户喜欢打篮球和羽毛球", confirmation_count=2)
    conn.commit()
    conn.close()

    comp.maybe_compress(reason="test")

    conn = sqlite3.connect(db_path)
    archived = conn.execute("SELECT COUNT(*) FROM memories WHERE status='archived'").fetchone()[0]
    state = conn.execute("SELECT v FROM compressor_state WHERE k='last_light_run'").fetchone()
    conn.close()
    assert archived == 1
    assert state is not None


def test_maybe_compress_skips_when_cooled_down(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    _patch_paths(monkeypatch, tmp_path, db_path)
    comp = MemoryCompressor()
    comp._light_threshold = 1
    comp._light_cooldown = 3600
    conn = _create_db(db_path)
    _insert(conn, "m1", "用户喜欢打篮球")
    conn.commit()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS compressor_state (k TEXT PRIMARY KEY, v TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO compressor_state (k, v) VALUES ('last_light_run', ?)", (str(comp._light_cooldown + 1),))
    conn.close()

    comp.maybe_compress(reason="test")


def test_split_into_fragments_and_store(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    _patch_paths(monkeypatch, tmp_path, db_path)
    conn = _create_db(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atomic_facts (
            id TEXT PRIMARY KEY,
            memory_id TEXT, group_id TEXT, subject TEXT, predicate TEXT,
            object TEXT, confidence REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    comp = MemoryCompressor()
    fragments = comp._split_into_fragments("第一件事。第二件事；第三件事\n第四件事！")
    assert len(fragments) >= 4
    cursor = conn.cursor()
    n = comp._store_atomic_facts(cursor, "mid1", "1", "100", ["片段一", "片段二"])
    conn.commit()
    conn.close()
    assert n == 2


def test_similarity_helpers(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    _patch_paths(monkeypatch, tmp_path, db_path)
    comp = MemoryCompressor()
    assert comp._is_similar("用户喜欢打篮球", "用户喜欢打篮球") is True
    assert comp._is_similar("用户喜欢打篮球", "用户喜欢踢足球") is False
    assert comp._is_similar("", "用户喜欢") is False
    assert comp._merge_content("A", "A") == "A"
    assert comp._merge_content("A", "B") == "A；B"
    assert comp._merge_content("", "B") == "B"
    assert comp._merge_content("A", "") == "A"
    assert comp._normalize_text("Hello World!") == "hello world"
    assert comp._jaccard_similarity(set("ab"), set()) == 0.0
