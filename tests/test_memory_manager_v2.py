# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""MemoryManager v2：冲突解决（Conflict Resolution）与元字段持久化测试。"""

import sqlite3
from pathlib import Path

import memory.memory_manager as memory_manager
from memory.memory_manager import MemoryManager


def _create_temp_db(tmp_path: Path):
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    return db_path


def test_detect_contradiction():
    """启发式矛盾检测：喜欢 vs 不喜欢 同一对象 → 判定为矛盾。"""
    assert MemoryManager._detect_contradiction("用户喜欢Helldivers2", "用户不喜欢Helldivers2") is True
    assert MemoryManager._detect_contradiction("用户喜欢Helldivers2", "用户也喜欢原神") is False


def test_conflict_marks_old_memory(tmp_path, monkeypatch):
    """新候选与旧记忆矛盾且置信度更高时，旧记忆标记为 conflict，新记忆晋升。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(memory_manager, "DB_PATH", db_path)
    monkeypatch.setattr(memory_manager, "get_compressor", lambda: type("Dummy", (), {"maybe_compress": lambda self, reason: None})())
    monkeypatch.setattr(memory_manager, "MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE", 0.5)
    monkeypatch.setattr(memory_manager, "MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE", 0.5)

    manager = MemoryManager()
    # 先插入旧记忆
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, importance, confidence, status) "
        "VALUES ('old1', '1', '100', 'PREFERENCE', '用户喜欢Helldivers2', 0.8, 0.7, 'active')"
    )
    conn.commit()
    conn.close()

    # 新候选：不喜欢同一对象，置信度更高 → 触发冲突解决
    cursor = conn.cursor() if False else None
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO memory_candidates (id, group_id, user_id, type, content, importance, confidence, status, usage_tags, visibility, behavior_rule) "
        "VALUES ('c1', '1', '100', 'PREFERENCE', '用户不喜欢Helldivers2', 0.9, 0.9, 'NEW', '[]', 'OPEN', '')"
    )
    conn.commit()
    conn.close()

    manager.process_new_candidates()

    conn = sqlite3.connect(db_path)
    old_status = conn.execute("SELECT status FROM memories WHERE id='old1'").fetchone()[0]
    new_content = conn.execute("SELECT content FROM memories WHERE content='用户不喜欢Helldivers2'").fetchone()
    conn.close()
    assert old_status == "conflict"
    assert new_content is not None


def test_candidate_meta_fields_persisted(tmp_path, monkeypatch):
    """候选的 usage_tags / visibility / behavior_rule 晋升后写入 memories 表。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(memory_manager, "DB_PATH", db_path)
    monkeypatch.setattr(memory_manager, "get_compressor", lambda: type("Dummy", (), {"maybe_compress": lambda self, reason: None})())
    monkeypatch.setattr(memory_manager, "MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE", 0.5)
    monkeypatch.setattr(memory_manager, "MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE", 0.5)

    manager = MemoryManager()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO memory_candidates (id, group_id, user_id, type, content, importance, confidence, status, usage_tags, visibility, behavior_rule) "
        "VALUES ('c1', '1', '100', 'PREFERENCE', '用户喜欢合作游戏', 0.9, 0.9, 'NEW', "
        " '[\"RECOMMEND\"]', 'RESTRICTED', '避免推荐单机游戏')"
    )
    conn.commit()
    conn.close()

    manager.process_new_candidates()

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT usage_tags, visibility, behavior_rule FROM memories WHERE content='用户喜欢合作游戏'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert '"RECOMMEND"' in row[0]
    assert row[1] == "RESTRICTED"
    assert row[2] == "避免推荐单机游戏"
