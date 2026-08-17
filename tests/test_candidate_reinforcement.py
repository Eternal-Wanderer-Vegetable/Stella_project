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
from memory.memory_manager import MemoryManager

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
    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])
    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])


    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][4] == 2                      # occurrence_count
    assert rows[0][3] > 0.5                     # confidence 获得加成
    assert rows[0][6] == "NEW"                  # 重新参与晋升评估


def test_similar_wording_counts_as_same_fact(db):
    """措辞不同但内容相似 → 视为同一事实（复现），不新增行。"""
    c = MemoryConsolidator()
    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])
    c._write_memory_candidates(
        "1", [dict(CANDIDATE, content="使用RTX5080显卡，跑27B模型吃力")], sender_ids=["1001"]
    )

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][4] == 2
    # 内容取更完整的一方
    assert "27B" in rows[0][2]


def test_unrelated_facts_stay_separate(db):
    """内容无关的候选各自独立成行。"""
    c = MemoryConsolidator()
    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])
    c._write_memory_candidates(
        "1", [dict(CANDIDATE, content="在杭州做后端开发")], sender_ids=["1001"]
    )

    assert len(_rows(db)) == 2


def test_same_content_different_users_stay_separate(db):
    """不同用户说了同一句话 → 两条独立候选（归属不可混同）。"""
    c = MemoryConsolidator()
    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])
    c._write_memory_candidates(
        "1", [dict(CANDIDATE, user_id="1002")], sender_ids=["1002"]
    )

    rows = _rows(db)
    assert len(rows) == 2
    assert {r[1] for r in rows} == {"1001", "1002"}


def test_source_kinds_accumulate_across_observations(db):
    """先 PASSIVE 后 AT_MENTION → source_kinds 保留两者（晋升判定要看历次证据）。"""
    c = MemoryConsolidator()
    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])
    c._write_memory_candidates(
        "1", [dict(CANDIDATE)], sender_ids=["1001"], at_senders=["1001"]
    )

    rows = _rows(db)
    assert len(rows) == 1
    assert set(json.loads(rows[0][5])) == {"PASSIVE", "AT_MENTION"}


def test_first_seen_at_not_refreshed_on_reoccurrence(db):
    """first_seen_at 是超期淘汰的锚点，复现时不得被刷新。"""
    c = MemoryConsolidator()
    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])
    first = _rows(db)[0][7]
    assert first is not None


    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])
    assert _rows(db)[0][7] == first


def test_confidence_capped_at_one(db):
    """反复复现不得让 confidence 越过 1.0。"""
    c = MemoryConsolidator()
    for _ in range(8):
        c._write_memory_candidates(
            "1", [dict(CANDIDATE, confidence=0.9)], sender_ids=["1001"]
        )

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][3] <= 1.0


def _cand(**kw):
    base = {
        "confidence": 0.5,
        "importance": 0.5,
        "occurrence_count": 1,
        "source_kinds": '["PASSIVE"]',
    }
    base.update(kw)
    return base


def test_gate1_high_confidence_promotes_immediately():
    ok, reason = MemoryManager._decide_promotion(_cand(confidence=0.9))
    assert ok and "高置信" in reason


def test_gate1_mid_confidence_passive_single_observation_waits():
    """置信中等 + 纯被动 + 仅一次观察 → 等复现。"""
    ok, reason = MemoryManager._decide_promotion(_cand(confidence=0.7))
    assert not ok and "证据不足" in reason


def test_gate1_mid_confidence_promotes_after_reoccurrence():
    ok, reason = MemoryManager._decide_promotion(
        _cand(confidence=0.7, occurrence_count=2)
    )
    assert ok and "交叉验证" in reason


def test_gate1_at_mention_promotes_single_shot():
    ok, reason = MemoryManager._decide_promotion(
        _cand(confidence=0.7, source_kinds='["PASSIVE", "AT_MENTION"]')
    )
    assert ok and "AT_MENTION" in reason


def test_gate1_low_confidence_never_promotes_even_with_at_mention():
    """置信度不足时，来源等级也救不了——先要证据可信，再谈来源。"""
    ok, _ = MemoryManager._decide_promotion(
        _cand(confidence=0.4, occurrence_count=5, source_kinds='["AT_MENTION"]'),
    )
    assert not ok


def test_gate1_importance_alone_does_not_promote():
    """回归：旧逻辑下 imp=0.6/conf=0.3 会直接晋升，现在必须被拦住。"""
    ok, reason = MemoryManager._decide_promotion(
        _cand(confidence=0.3, importance=0.6)
    )
    assert not ok and "置信度不足" in reason


def test_gate1_trivial_importance_blocked():
    ok, reason = MemoryManager._decide_promotion(
        _cand(confidence=0.95, importance=0.1)
    )
    assert not ok and "重要度不足" in reason


def test_has_at_mention_tolerates_garbage():
    assert not MemoryManager._has_at_mention("not json")
    assert not MemoryManager._has_at_mention("")
    assert not MemoryManager._has_at_mention(None)
    assert MemoryManager._has_at_mention('["at_mention"]')  # 大小写不敏感


def test_reoccurrence_eventually_promotes_end_to_end(db):
    """端到端：conf 0.5 的候选写两次 → 加成后跨过 0.6 且 occurrence=2 → 晋升。"""
    c = MemoryConsolidator()
    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])

    manager = MemoryManager()
    manager.process_new_candidates()
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 0
    assert conn.execute(
        "SELECT status FROM memory_candidates"
    ).fetchone()[0] == "OBSERVING"
    conn.close()

    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])
    manager.process_new_candidates()

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
    assert conn.execute("SELECT status FROM memory_candidates").fetchone()[0] == "CONFIRMED"
    conn.close()


def test_stale_observing_candidate_rejected(db):
    """超期未获新证据的 OBSERVING 候选被标记 REJECTED。"""
    c = MemoryConsolidator()
    c._write_memory_candidates("1", [dict(CANDIDATE)], sender_ids=["1001"])

    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE memory_candidates SET status = 'OBSERVING', first_seen_at = '2020-01-01 00:00:00'"
    )
    conn.commit()
    conn.close()

    MemoryManager().process_new_candidates()

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT status FROM memory_candidates").fetchone()[0] == "REJECTED"
    conn.close()


def test_quota_score_prefers_confirmed_and_recent():
    """配额分：被反复确认 + 近期访问 > 高重要度但从未确认/久未访问。"""
    strong = MemoryManager._quota_score(0.5, 3, "2026-08-12 10:00:00")
    weak = MemoryManager._quota_score(0.9, 0, "2020-01-01 00:00:00")
    assert strong > weak


def test_quota_score_handles_garbage():
    """脏数据不得抛异常，且按最弱处理（优先淘汰）。"""
    assert MemoryManager._quota_score(None, None, None) == 0.0
    assert MemoryManager._quota_score("bad", "bad", "not-a-date") == 0.0


def test_quota_dry_run_does_not_archive(db, monkeypatch):
    """MEMORY_QUOTA_ENFORCE=False 时只记日志、不改数据。"""
    monkeypatch.setattr("memory.memory_manager.MEMORY_QUOTA_ENFORCE", False)
    monkeypatch.setattr("memory.memory_manager.MEMORY_USER_QUOTA", 3)

    manager = MemoryManager()
    conn = sqlite3.connect(db)
    for i in range(5):
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content, importance, "
            "confidence, status, confirmation_count, last_accessed_at) "
            "VALUES (?, '1', '1001', 'FACT', ?, 0.5, 0.8, 'active', 1, '2026-08-12 10:00:00')",
            (f"m{i}", f"事实{i}"),
        )
    conn.commit()
    cursor = conn.cursor()

    assert manager._enforce_user_quota(cursor, "1", "1001") == 0
    conn.commit()
    assert conn.execute(
        "SELECT COUNT(*) FROM memories WHERE status = 'active'"
    ).fetchone()[0] == 5
    conn.close()


def test_quota_enforce_archives_weakest(db, monkeypatch):
    """开启后淘汰最弱的那条，总数回到配额上限。"""
    monkeypatch.setattr("memory.memory_manager.MEMORY_QUOTA_ENFORCE", True)
    monkeypatch.setattr("memory.memory_manager.MEMORY_USER_QUOTA", 2)

    manager = MemoryManager()
    conn = sqlite3.connect(db)
    # m-weak：从未确认、久未访问 → 应被淘汰
    conn.execute(
        "INSERT INTO memories (id, group_shared_space, user_id, type, content, importance, confidence, "
        "status, confirmation_count, last_accessed_at) VALUES "
        "('m-weak', '1', '1001', 'FACT', '弱记忆', 0.3, 0, 'active', 0, '2020-01-01 00:00:00')"
    )
    for i in range(2):
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content, importance, confidence, "
            "status, confirmation_count, last_accessed_at) VALUES "
            f"('m-strong{i}', '1', '1001', 'FACT', '强记忆{i}', 0.8, 0.9, 'active', 3, '2026-08-12 10:00:00')"
        )
    conn.commit()
    cursor = conn.cursor()

    assert manager._enforce_user_quota(cursor, "1", "1001") == 1
    conn.commit()

    statuses = dict(conn.execute("SELECT id, status FROM memories").fetchall())
    assert statuses["m-weak"] == "archived"
    assert statuses["m-strong0"] == "active"
    assert statuses["m-strong1"] == "active"
    conn.close()


def test_quota_is_per_user_and_per_group(db, monkeypatch):
    """配额按 (群, 用户) 独立计算，不能因为别人记忆多就淘汰自己的。"""
    monkeypatch.setattr("memory.memory_manager.MEMORY_QUOTA_ENFORCE", True)
    monkeypatch.setattr("memory.memory_manager.MEMORY_USER_QUOTA", 2)

    manager = MemoryManager()
    conn = sqlite3.connect(db)
    for i in range(3):
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content, importance, confidence, "
            "status, confirmation_count, last_accessed_at) VALUES "
            f"('other{i}', '1', '1002', 'FACT', '别人的{i}', 0.5, 0.8, 'active', 1, '2026-08-12 10:00:00')"
        )
    conn.execute(
        "INSERT INTO memories (id, group_shared_space, user_id, type, content, importance, confidence, "
        "status, confirmation_count, last_accessed_at) VALUES "
        "('mine', '1', '1001', 'FACT', '我的', 0.5, 0.8, 'active', 1, '2026-08-12 10:00:00')"
    )
    conn.commit()
    cursor = conn.cursor()

    assert manager._enforce_user_quota(cursor, "1", "1001") == 0
    conn.commit()
    assert conn.execute(
        "SELECT status FROM memories WHERE id = 'mine'"
    ).fetchone()[0] == "active"
    conn.close()
