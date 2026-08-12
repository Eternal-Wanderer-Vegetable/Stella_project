# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""候选强化（交叉验证）的行为基线。


同一事实被反复观察到时必须累积证据而不是重复插入——否则每条都以新 uuid
落库、各自卡在 OBSERVING，「暂存 → 交叉验证 → 逐步强化」永远不成立。
"""
import json
import sqlite3

import pytest

from memory.consolidator import MemoryConsolidator

CANDIDATE = {
    "user_id": "1001",
    "type": "FACT",
    "content": "使用RTX5080显卡",
    "confidence": 0.5,
    "importance": 0.5,
    "evidence": "用户自述",
    "source_message_ids": ["1"],
}


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "cand.db"
    path.touch()
    monkeypatch.setattr("memory.consolidator.DB_PATH", path)
    monkeypatch.setattr("memory.memory_manager.DB_PATH", path)
    monkeypatch.setattr("memory.compressor.DB_PATH", path)
    return path


def _rows(db):
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT id, user_id, content, confidence, occurrence_count, source_kinds, status, "
        "first_seen_at FROM memory_candidates ORDER BY rowid"
    ).fetchall()
    conn.close()
    return rows


def test_same_fact_accumulates_instead_of_duplicating(db):
    """同一事实写两次 → 一行、occurrence_count=2、confidence 提升。"""
    c = MemoryConsolidator()
    c._write_memory_candidates(1, [dict(CANDIDATE)], sender_ids=["1001"])
    c._write_memory_candidates(1, [dict(CANDIDATE)], sender_ids=["1001"])


    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][4] == 2                      # occurrence_count
    assert rows[0][3] > 0.5                     # confidence 获得加成
    assert rows[0][6] == "NEW"                  # 重新参与晋升评估


def test_similar_wording_counts_as_same_fact(db):
    """措辞不同但内容相似 → 视为同一事实（复现），不新增行。"""
    c = MemoryConsolidator()
    c._write_memory_candidates(1, [dict(CANDIDATE)], sender_ids=["1001"])
    c._write_memory_candidates(
        1, [dict(CANDIDATE, content="使用RTX5080显卡，跑27B模型吃力")], sender_ids=["1001"]
    )

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][4] == 2
    # 内容取更完整的一方
    assert "27B" in rows[0][2]


def test_unrelated_facts_stay_separate(db):
    """内容无关的候选各自独立成行。"""
    c = MemoryConsolidator()
    c._write_memory_candidates(1, [dict(CANDIDATE)], sender_ids=["1001"])
    c._write_memory_candidates(
        1, [dict(CANDIDATE, content="在杭州做后端开发")], sender_ids=["1001"]
    )

    assert len(_rows(db)) == 2


def test_same_content_different_users_stay_separate(db):
    """不同用户说了同一句话 → 两条独立候选（归属不可混同）。"""
    c = MemoryConsolidator()
    c._write_memory_candidates(1, [dict(CANDIDATE)], sender_ids=["1001"])
    c._write_memory_candidates(
        1, [dict(CANDIDATE, user_id="1002")], sender_ids=["1002"]
    )

    rows = _rows(db)
    assert len(rows) == 2
    assert {r[1] for r in rows} == {"1001", "1002"}


def test_source_kinds_accumulate_across_observations(db):
    """先 PASSIVE 后 AT_MENTION → source_kinds 保留两者（晋升判定要看历次证据）。"""
    c = MemoryConsolidator()
    c._write_memory_candidates(1, [dict(CANDIDATE)], sender_ids=["1001"])
    c._write_memory_candidates(
        1, [dict(CANDIDATE)], sender_ids=["1001"], at_senders=["1001"]
    )

    rows = _rows(db)
    assert len(rows) == 1
    assert set(json.loads(rows[0][5])) == {"PASSIVE", "AT_MENTION"}


def test_first_seen_at_not_refreshed_on_reoccurrence(db):
    """first_seen_at 是超期淘汰的锚点，复现时不得被刷新。"""
    c = MemoryConsolidator()
    c._write_memory_candidates(1, [dict(CANDIDATE)], sender_ids=["1001"])
    first = _rows(db)[0][7]
    assert first is not None


    c._write_memory_candidates(1, [dict(CANDIDATE)], sender_ids=["1001"])
    assert _rows(db)[0][7] == first


def test_confidence_capped_at_one(db):
    """反复复现不得让 confidence 越过 1.0。"""
    c = MemoryConsolidator()
    for _ in range(8):
        c._write_memory_candidates(
            1, [dict(CANDIDATE, confidence=0.9)], sender_ids=["1001"]
        )

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][3] <= 1.0
