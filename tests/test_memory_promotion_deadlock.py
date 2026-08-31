# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""晋升死锁与主动追问复读的回归护栏。

守的是 design_docs/bug_report/bug_report_2026_8_31#1.md 记录的缺陷：

1. 整合 prompt 从未定义 ``importance``，模型照抄 JSON 示例里的 ``0.0``；
   而 ``_decide_promotion`` 的**第一道**检查就是 importance 下限，于是候选
   无论 confidence 多高都晋升不了，永远卡在 OBSERVING。
2. ``proactive_state.last_asked_candidate_id`` 写了但没有任何消费方，
   verify 分支每轮都挑中同一条卡死的候选 → 对同一个人反复问同一个问题。

两个缺陷叠加成闭环：问 → 用户回答 → 强化 → 仍被 importance 门槛打回 → 再问。

这些用例存在的理由是缺陷本身没有报错：行为不符合文档，但一切"正常运行"。
原有的 test_proactive_at_flow / test_proactive_state 覆盖了配额、跨日、退避，
唯独没有断言"同一候选不会被连续追问"，缺口因此长期没被发现。
"""

import sqlite3

import pytest

from memory.consolidation_prompt import CONSOLIDATION_PROMPT
from memory.extraction_prompt import EXTRACTION_PROMPT
from memory.memory_manager import MemoryManager


# ── 1. prompt 侧：importance 必须有取值指引 ──────────────────


@pytest.mark.parametrize(
    ("name", "template"),
    [("consolidation", CONSOLIDATION_PROMPT), ("extraction", EXTRACTION_PROMPT)],
)
def test_prompt_defines_importance(name, template):
    """两个候选产出 prompt 都必须解释 importance，否则模型照抄示例里的 0.0。

    反向断言的是「字段在 JSON 示例里出现过」不等于「模型知道该填什么」——
    confidence 有整段说明所以填得好，importance 只在示例里出现过，就一直是 0。
    """
    assert "importance 表示" in template, f"{name} prompt 缺 importance 的定义"
    # 取值指引：至少要给出高/低两端的判据，只说「填个数」没有用
    assert "0.7-1.0" in template and "0.1-0.4" in template
    # 明确禁止照抄示例值——这是本缺陷的直接触发点
    assert "不要照抄" in template


def test_prompt_explains_importance_is_independent_of_confidence():
    """必须说明两者正交，否则模型倾向于让 importance 跟随 confidence。"""
    assert "与 confidence 无关" in CONSOLIDATION_PROMPT


# ── 2. 闸门侧：为什么 importance=0 是致命的 ────────────────────


def test_zero_importance_blocks_promotion_regardless_of_confidence():
    """importance=0 会在读 confidence 之前一票否决——这是死锁的机制本身。

    本用例不是要求改掉这个行为（下限本身合理），而是钉住「0 值必须永不落库」
    这条约束的理由：只要 0 进了库，这条候选就再也出不来。
    """
    candidate = {
        "confidence": 1.0,          # 满置信
        "importance": 0.0,          # 但 importance 为 0
        "occurrence_count": 99,     # 且反复复现
        "source_kinds": '["AT_MENTION"]',  # 且是最高等级证据
    }
    should_promote, reason = MemoryManager._decide_promotion(candidate)
    assert should_promote is False
    assert "重要度不足" in reason


def test_nonzero_importance_lets_confidence_decide():
    """兜底值到位后，晋升与否重新由 confidence / 证据决定（恢复设计意图）。"""
    candidate = {
        "confidence": 1.0,
        "importance": 0.5,
        "occurrence_count": 1,
        "source_kinds": '["AT_MENTION"]',
    }
    should_promote, _ = MemoryManager._decide_promotion(candidate)
    assert should_promote is True


# ── 3. 写入侧：模型给 0 时必须兜底 ─────────────────────────


@pytest.fixture
def candidate_db(tmp_path, monkeypatch):
    """一个临时候选库，供 _write_memory_candidates 落库。

    compressor 也要打桩：process_new_candidates 晋升成功后会触发
    maybe_compress，它自己 sqlite3.connect(DB_PATH)——不打桩会连到真实的
    memory/agent_memory.db 上去压缩，测试静默污染生产库。
    """
    path = tmp_path / "cand.db"
    path.touch()
    monkeypatch.setattr("memory.consolidator.DB_PATH", path)
    monkeypatch.setattr("memory.schema.DB_PATH", path)
    monkeypatch.setattr("memory.memory_manager.DB_PATH", path)
    monkeypatch.setattr("memory.compressor.DB_PATH", path)
    return path


def _write_one(importance=0.0, confidence=0.9, content="住在南方，家里种甘蔗"):
    """按 LLM 返回的形状写一条候选。importance 默认 0 —— 复现缺陷的输入。"""
    from memory.consolidator import MemoryConsolidator

    MemoryConsolidator()._write_memory_candidates(
        "space_1",
        [
            {
                "user_id": "1001",
                "type": "FACT",
                "content": content,
                "importance": importance,
                "confidence": confidence,
                "evidence": "用户直接陈述",
                "usage_tags": ["ANSWER_CONTEXT"],
                "visibility": "OPEN",
                "source_message_ids": [],
            }
        ],
        sender_ids=["1001"],
        at_senders=["1001"],
    )


def test_zero_importance_from_llm_is_backfilled(candidate_db):
    """模型返回 importance=0 时不得原样落库，否则该候选永远晋升不了。"""
    from config import MEMORY_CANDIDATE_DEFAULT_IMPORTANCE

    _write_one(importance=0.0)

    conn = sqlite3.connect(candidate_db)
    rows = conn.execute("SELECT importance FROM memory_candidates").fetchall()
    conn.close()
    assert rows, "候选没有落库，用例没测到东西"
    assert rows[0][0] == pytest.approx(MEMORY_CANDIDATE_DEFAULT_IMPORTANCE)
    assert rows[0][0] > 0


def test_model_supplied_importance_is_preserved(candidate_db):
    """反向断言：模型正常填了值就不许被兜底覆盖。

    只测兜底的话，把逻辑写成「一律改成 0.5」也能通过，模型的判断会被静默丢弃。
    """
    _write_one(importance=0.8)

    conn = sqlite3.connect(candidate_db)
    value = conn.execute("SELECT importance FROM memory_candidates").fetchone()[0]
    conn.close()
    assert value == pytest.approx(0.8)


def test_zero_importance_candidate_now_promotes(candidate_db):
    """端到端：模型给 0 的高置信候选，现在能真正走完晋升。"""
    _write_one(importance=0.0, confidence=0.95)
    MemoryManager().process_new_candidates()

    conn = sqlite3.connect(candidate_db)
    status = conn.execute("SELECT status FROM memory_candidates").fetchone()[0]
    memories = conn.execute("SELECT COUNT(*) FROM memories WHERE status='active'").fetchone()[0]
    conn.close()
    assert status == "CONFIRMED"
    assert memories == 1


# ── 4. 主动验证侧：不许重复追问同一条候选 ──────────────────


@pytest.fixture
def observing_db(tmp_path, monkeypatch):
    """建一个含两条 OBSERVING 候选的库，用于验证追问去重。"""
    path = tmp_path / "observe.db"
    monkeypatch.setattr("memory.proactive_target.DB_PATH", path)
    monkeypatch.setattr("memory.schema.DB_PATH", path)

    from memory.schema import create_memory_candidates_table

    conn = sqlite3.connect(path)
    create_memory_candidates_table(conn)
    for cid, content, conf in (
        ("cand_high", "在放假期间对知识的记忆会衰退", 0.75),
        ("cand_low", "居住地附近主要种植甘蔗", 0.65),
    ):
        conn.execute(
            "INSERT INTO memory_candidates "
            "(id, group_shared_space, user_id, type, content, importance, confidence, status) "
            "VALUES (?, ?, ?, 'FACT', ?, 0.5, ?, 'OBSERVING')",
            (cid, "space_1", "1001", content, conf),
        )
    conn.commit()
    conn.close()
    return path


def test_verify_picks_highest_confidence_candidate(observing_db):
    """基线：没有排除项时挑置信度最高的那条（最接近晋升线，收益最大）。"""
    from memory.proactive_target import _fetch_observing_candidate

    found = _fetch_observing_candidate("space_1", 1001)
    assert found is not None
    assert found[0] == "cand_high"


def test_verify_skips_last_asked_candidate(observing_db):
    """上次问过的那条必须被跳过，否则同一个问题会每轮复读。

    这是缺陷的核心：last_asked_candidate_id 一直有写入，只是没有任何读取方。
    """
    from memory.proactive_target import _fetch_observing_candidate

    found = _fetch_observing_candidate("space_1", 1001, exclude_id="cand_high")
    assert found is not None, "还有别的候选可问，不该直接放弃"
    assert found[0] == "cand_low"


def test_verify_returns_none_when_only_candidate_was_just_asked(observing_db):
    """只剩那一条问过的候选时宁可不问，也不复读。"""
    from memory.proactive_target import _fetch_observing_candidate

    conn = sqlite3.connect(observing_db)
    conn.execute("DELETE FROM memory_candidates WHERE id = 'cand_low'")
    conn.commit()
    conn.close()

    assert _fetch_observing_candidate("space_1", 1001, exclude_id="cand_high") is None


def test_empty_exclude_id_does_not_filter_anything(observing_db):
    """没问过任何人时（exclude_id 为空串）不得误伤正常候选。"""
    from memory.proactive_target import _fetch_observing_candidate

    found = _fetch_observing_candidate("space_1", 1001, exclude_id="")
    assert found is not None
    assert found[0] == "cand_high"


# ── 5. 迁移侧：存量卡死行必须被回填 ────────────────────────


def _ctx():
    """migrate_v12 不读 ctx，但 MigrationContext 的 resolver 是必填字段。"""
    from memory.migrations import MigrationContext

    return MigrationContext(resolver=lambda gid: f"space_{gid}")


def test_migration_v12_backfills_zero_importance(tmp_path):
    """prompt 与兜底只救新候选，库里已经躺着的那批要靠迁移解锁。"""
    from config import MEMORY_CANDIDATE_DEFAULT_IMPORTANCE
    from memory.migrations import migrate_v12
    from memory.schema import create_memories_table, create_memory_candidates_table

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    create_memory_candidates_table(conn)
    create_memories_table(conn)
    conn.execute(
        "INSERT INTO memory_candidates "
        "(id, group_shared_space, user_id, type, content, importance, confidence, status) "
        "VALUES ('stuck', 'space_1', '1001', 'FACT', '卡死的候选', 0.0, 0.9, 'OBSERVING')"
    )
    conn.execute(
        "INSERT INTO memory_candidates "
        "(id, group_shared_space, user_id, type, content, importance, confidence, status) "
        "VALUES ('ok', 'space_1', '1001', 'FACT', '正常的候选', 0.7, 0.9, 'OBSERVING')"
    )
    conn.commit()

    result = migrate_v12(conn, _ctx())

    rows = dict(conn.execute("SELECT id, importance FROM memory_candidates").fetchall())
    conn.close()

    assert rows["stuck"] == pytest.approx(MEMORY_CANDIDATE_DEFAULT_IMPORTANCE)
    # 反向断言：模型正常填过的值不许被迁移改写
    assert rows["ok"] == pytest.approx(0.7)
    assert result.changed_rows == 1


def test_migration_v12_is_idempotent(tmp_path):
    """重复执行不得反复改写（迁移可能因失败重跑）。"""
    from memory.migrations import migrate_v12
    from memory.schema import create_memories_table, create_memory_candidates_table

    path = tmp_path / "legacy2.db"
    conn = sqlite3.connect(path)
    create_memory_candidates_table(conn)
    create_memories_table(conn)
    conn.execute(
        "INSERT INTO memory_candidates "
        "(id, group_shared_space, user_id, type, content, importance, confidence, status) "
        "VALUES ('stuck', 'space_1', '1001', 'FACT', '卡死的候选', 0.0, 0.9, 'OBSERVING')"
    )
    conn.commit()

    assert migrate_v12(conn, _ctx()).changed_rows == 1
    assert migrate_v12(conn, _ctx()).changed_rows == 0
    conn.close()
