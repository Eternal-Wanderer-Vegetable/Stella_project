# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""MemoryManager v2：冲突解决（Conflict Resolution）与元字段持久化测试。"""

import sqlite3
from pathlib import Path

import memory.consolidator as consolidator
import memory.memory_manager as memory_manager
from memory.consolidator import MemoryConsolidator
from memory.memory_manager import MemoryManager


def _create_temp_db(tmp_path: Path):
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    return db_path


def _seed_candidate_with_evidence(
    db_path: Path, monkeypatch, *, content: str, user_id: str = "100", group_id: int = 1001,
    confidence: float = 0.9, importance: float = 0.9, extra: dict | None = None,
) -> str:
    """Write one model proposal through the production source/evidence contract."""
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE group_messages (
            id INTEGER PRIMARY KEY, group_id TEXT, user_id TEXT, content TEXT,
            source_kind TEXT, timestamp TEXT, msg_id TEXT, conversation_key TEXT,
            bot_id TEXT, reply_to_msg_id TEXT, reply_target_user_id TEXT,
            mentioned_user_ids_json TEXT, logical_message_id TEXT, part_index INTEGER,
            origin_msg_id TEXT, reply_recipient_user_id TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO group_messages (
            id, group_id, user_id, content, source_kind, msg_id, conversation_key, bot_id
        ) VALUES (1, ?, ?, ?, 'AT_MENTION', 'platform-1', 'test-conversation', 'test-bot')""",
        (str(group_id), user_id, content),
    )
    conn.commit()
    conn.close()

    proposal = {
        "user_id": user_id,
        "type": "PREFERENCE",
        "content": content,
        "importance": importance,
        "confidence": confidence,
        "source_message_ids": [1],
        "verification_contract": {
            "fact_subject_user_id": user_id,
            "predicate_key": "preference.general",
            "canonical_value": content.removeprefix("我喜欢").removeprefix("我不喜欢"),
            "polarity": "negative" if content.startswith("我不喜欢") else "positive",
            "statement_kind": "explicit_preference",
            "temporal_qualifiers": [],
            "context_qualifiers": [],
            "supports": [
                {"source_message_id": 1, "exact_support_span": content}
            ],
        },
        **(extra or {}),
    }
    writer = MemoryConsolidator.__new__(MemoryConsolidator)
    writer._write_memory_candidates(
        str(group_id),
        [proposal],
        sender_ids=[user_id],
        at_senders=[user_id],
        origin_group_id=group_id,
        source_rows=[(1, user_id, content, "AT_MENTION")],
    )
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id FROM memory_candidates WHERE user_id = ? AND content = ?",
        (user_id, content),
    ).fetchone()
    conn.close()
    assert row is not None
    return str(row[0])


def test_detect_contradiction():
    """启发式矛盾检测：喜欢 vs 不喜欢 同一对象 → 判定为矛盾。"""
    assert MemoryManager._detect_contradiction("用户喜欢Helldivers2", "用户不喜欢Helldivers2") is True
    assert MemoryManager._detect_contradiction("用户喜欢Helldivers2", "用户也喜欢原神") is False


def test_conflict_marks_old_memory(tmp_path, monkeypatch):
    """新候选与旧记忆矛盾且置信度更高时，旧记忆标记为 conflict，新记忆晋升。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(memory_manager, "DB_PATH", db_path)
    monkeypatch.setattr(memory_manager, "get_compressor", lambda: type("Dummy", (), {"maybe_compress": lambda self, reason: None})())
    monkeypatch.setattr(memory_manager, "MEMORY_CONFIRM_HIGH_CONFIDENCE", 0.5)

    manager = MemoryManager()
    # 先插入旧记忆
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO memories (id, group_shared_space, user_id, type, content, importance, confidence, status) "
        "VALUES ('old1', '1', '100', 'PREFERENCE', '用户喜欢Helldivers2', 0.8, 0.7, 'active')"
    )
    conn.commit()
    conn.close()

    # 新候选：不喜欢同一对象，置信度更高 → 触发冲突解决
    _seed_candidate_with_evidence(
        db_path, monkeypatch, content="我不喜欢Helldivers2", user_id="100",
        group_id=1, confidence=0.9, importance=0.9,
    )

    manager._process_new_candidates_python()

    conn = sqlite3.connect(db_path)
    old_status = conn.execute("SELECT status FROM memories WHERE id='old1'").fetchone()[0]
    new_content = conn.execute("SELECT content FROM memories WHERE content='我不喜欢Helldivers2'").fetchone()
    conn.close()
    assert old_status == "conflict"
    assert new_content is not None


def test_candidate_meta_fields_persisted(tmp_path, monkeypatch):
    """候选的 usage_tags / visibility / behavior_rule 晋升后写入 memories 表。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(memory_manager, "DB_PATH", db_path)
    monkeypatch.setattr(memory_manager, "get_compressor", lambda: type("Dummy", (), {"maybe_compress": lambda self, reason: None})())
    monkeypatch.setattr(memory_manager, "MEMORY_CONFIRM_HIGH_CONFIDENCE", 0.5)

    manager = MemoryManager()
    conn = sqlite3.connect(db_path)
    conn.close()
    _seed_candidate_with_evidence(
        db_path,
        monkeypatch,
        content="我喜欢合作游戏",
        user_id="100",
        group_id=1,
        confidence=0.9,
        importance=0.9,
        extra={"usage_tags": ["RECOMMEND"], "visibility": "RESTRICTED", "behavior_rule": "避免推荐单机游戏"},
    )

    manager._process_new_candidates_python()

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT usage_tags, visibility, behavior_rule FROM memories WHERE content='我喜欢合作游戏'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert '"RECOMMEND"' in row[0]
    assert row[1] == "RESTRICTED"
    assert row[2] == "避免推荐单机游戏"


def test_python_promotion_writes_memory_lineage_and_scope_versions(tmp_path, monkeypatch):
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(memory_manager, "DB_PATH", db_path)
    monkeypatch.setattr(
        memory_manager,
        "get_compressor",
        lambda: type("Dummy", (), {"maybe_compress": lambda self, reason: None})(),
    )
    monkeypatch.setattr(memory_manager, "MEMORY_CONFIRM_HIGH_CONFIDENCE", 0.5)
    candidate_id = _seed_candidate_with_evidence(
        db_path,
        monkeypatch,
        content="我喜欢桌游",
        user_id="100",
        group_id=1001,
    )

    MemoryManager()._process_new_candidates_python()

    conn = sqlite3.connect(db_path)
    lineage = conn.execute(
        "SELECT COUNT(*) FROM memory_claim_links "
        "WHERE entity_type = 'memory' AND claim_key = "
        "(SELECT fact_key FROM memory_candidates WHERE id = ?)",
        (candidate_id,),
    ).fetchone()[0]
    owner_key = conn.execute(
        "SELECT owner_key FROM memory_candidates WHERE id = ?", (candidate_id,)
    ).fetchone()[0]
    versions = dict(
        conn.execute(
            "SELECT scope_key, version FROM memory_scope_versions "
            "WHERE scope_key IN (?, 'global')",
            (owner_key,),
        ).fetchall()
    )
    conn.close()
    assert lineage == 1
    assert versions[owner_key] == 1
    assert versions["global"] == 1
