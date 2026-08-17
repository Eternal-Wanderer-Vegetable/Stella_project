# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.memory_manager 候选记忆处理流程的测试。

每个用例用 tmp_path 建临时库，并把 memory_manager.DB_PATH 指过去；
get_compressor 用 Dummy 对象替换（吞掉 maybe_compress 副作用）。
通过 monkeypatch 配置确认阈值来验证：
- 低价值候选应进入 OBSERVING；
- 高价值候选应转为 CONFIRMED 并写入 memories 表。
"""

import sqlite3
from pathlib import Path

import memory.memory_manager as memory_manager


def _create_temp_db(tmp_path: Path):
    """在 tmp_path 下创建一个空数据库文件（建表由 MemoryManager 自己完成），返回库路径。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    return db_path


def test_low_value_candidate_goes_to_observing(tmp_path, monkeypatch):
    """重要性/置信度低于阈值的候选应进入 OBSERVING，而不是直接成为正式记忆。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(memory_manager, "DB_PATH", db_path)
    monkeypatch.setattr(memory_manager, "get_compressor", lambda: type("Dummy", (), {"maybe_compress": lambda self, reason: None})())
    monkeypatch.setattr(memory_manager, "MEMORY_OBSERVE_LOW_CONFIDENCE", 0.7)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_candidates (
            id TEXT PRIMARY KEY,
            group_shared_space TEXT,
            user_id TEXT,
            type TEXT,
            content TEXT,
            importance REAL,
            confidence REAL,
            evidence TEXT,
            status TEXT,
            source_message_ids TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    cursor.execute(
        "INSERT INTO memory_candidates (id, group_shared_space, user_id, type, content, importance, confidence, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("c1", "1", "100", "FACT", "测试候选", 0.5, 0.6, "NEW"),
    )
    conn.commit()
    conn.close()

    manager = memory_manager.MemoryManager()
    manager.process_new_candidates()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM memory_candidates WHERE id = ?", ("c1",))
    status = cursor.fetchone()[0]
    conn.close()

    assert status == "OBSERVING"


def test_high_value_candidate_becomes_confirmed_memory(tmp_path, monkeypatch):
    """重要性/置信度达标的候选应转为 CONFIRMED，并写入 memories 表成为正式记忆。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(memory_manager, "DB_PATH", db_path)
    monkeypatch.setattr(memory_manager, "get_compressor", lambda: type("Dummy", (), {"maybe_compress": lambda self, reason: None})())
    monkeypatch.setattr(memory_manager, "MEMORY_CONFIRM_HIGH_CONFIDENCE", 0.5)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_candidates (
            id TEXT PRIMARY KEY,
            group_shared_space TEXT,
            user_id TEXT,
            type TEXT,
            content TEXT,
            importance REAL,
            confidence REAL,
            evidence TEXT,
            status TEXT,
            source_message_ids TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    cursor.execute(
        "INSERT INTO memory_candidates (id, group_shared_space, user_id, type, content, importance, confidence, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("c2", "1", "200", "FACT", "高质量候选", 0.8, 0.9, "NEW"),
    )
    conn.commit()
    conn.close()

    manager = memory_manager.MemoryManager()
    manager.process_new_candidates()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM memory_candidates WHERE id = ?", ("c2",))
    candidate_status = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM memories WHERE content = ?", ("高质量候选",))
    memory_count = cursor.fetchone()[0]
    conn.close()

    assert candidate_status == "CONFIRMED"
    assert memory_count == 1
