# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""时效型候选的处置：短 TTL + 不主动追问。

守的是 design_docs/bug_report/bug_report_2026_8_31#1.md 的现象 2 —— 群里有人说
「听到地震预警」，此后几天 Stella 反复就此追问同一个人。

那条链路上有两个位置对「时效性」完全无感：

1. 候选 TTL 对所有类型统一 30 天，一条一次性事件会在候选池里躺满一个月；
2. ``_fetch_observing_candidate`` 不按 type 过滤，这条 EVENT 与一条稳定 FACT
   一样有资格被「主动验证」——而验证一件已经过去的事在语义上就是错的，还会把
   每人每天 2 次的稀缺配额花在「确认下来即过期」的信息上。

本文件的用例大多成对出现：一条断言时效型被压下去，一条反向断言稳定型没有被
连带压下去。只测前者的话，「一律不追问」「TTL 一律 3 天」也能通过，而那会把
FACT 的采集一起毁掉。
"""

import sqlite3

import pytest

from memory.memory_manager import MemoryManager

# 全局 TTL 被钉成这个值（见 _pin_global_ttl）：本文件测的是「分档相对全局更短」，
# 不该因为某台机器的 .env 把 MEMORY_CANDIDATE_MAX_OBSERVING_DAYS 改小就变红。
GLOBAL_TTL = 30.0

# 默认应被排除出主动验证的类型。行为用例一律显式钉住这套值，
# 只有 test_shipped_default_excludes_the_time_sensitive_types 去校验发布默认值。
TIME_SENSITIVE = frozenset({"EVENT", "PLAN", "GROUP_CONTEXT"})


@pytest.fixture(autouse=True)
def _pin_global_ttl(monkeypatch):
    monkeypatch.setattr(
        "memory.memory_manager.MEMORY_CANDIDATE_MAX_OBSERVING_DAYS", GLOBAL_TTL
    )


# ── 1. TTL 分档本身 ───────────────────────────────────────


@pytest.mark.parametrize("mem_type", sorted(TIME_SENSITIVE))
def test_time_sensitive_types_get_a_shorter_ttl(mem_type):
    assert MemoryManager._observing_ttl_days(mem_type) < GLOBAL_TTL


@pytest.mark.parametrize("mem_type", ["FACT", "PREFERENCE", "STYLE", "RELATION"])
def test_stable_types_keep_the_global_ttl(mem_type):
    """反向断言：稳定类型不许被顺手一起缩短——那等于停止收集长期记忆。"""
    assert MemoryManager._observing_ttl_days(mem_type) == GLOBAL_TTL


def test_ttl_lookup_is_case_insensitive():
    """大写归一化是写入侧的约定，查表时不能把它当作前提。"""
    assert MemoryManager._observing_ttl_days("event") == MemoryManager._observing_ttl_days(
        "EVENT"
    )


@pytest.mark.parametrize("mem_type", ["", "   ", None, "NOT_A_TYPE"])
def test_dirty_type_falls_back_to_the_global_ttl(mem_type):
    """脏 type 宁可多等几天：拼错一个类型名不该让候选被提前丢掉。"""
    assert MemoryManager._observing_ttl_days(mem_type) == GLOBAL_TTL


# ── 2. 超期淘汰按分档执行 ─────────────────────────────────


@pytest.fixture
def db(tmp_path, monkeypatch):
    """一个只含候选表的临时库。

    compressor 也要打桩：_reject_stale_candidates 本身不碰它，但 MemoryManager()
    的建表流程会走 ensure_v2_schema，打桩后整条链路都不会碰到生产库。
    """
    path = tmp_path / "cand.db"
    monkeypatch.setattr("memory.memory_manager.DB_PATH", path)
    monkeypatch.setattr("memory.schema.DB_PATH", path)
    monkeypatch.setattr("memory.compressor.DB_PATH", path)
    MemoryManager()  # 建表
    return path


def _seed(path, rows, status="OBSERVING"):
    """按 (id, type, 距今天数) 写入候选。天数可为小数，直接进 SQLite 的时间修饰符。"""
    conn = sqlite3.connect(path)
    for cid, mem_type, days_ago in rows:
        conn.execute(
            "INSERT INTO memory_candidates "
            "(id, group_shared_space, user_id, type, content, importance, confidence, "
            "status, first_seen_at) "
            "VALUES (?, 'space_1', '1001', ?, '某条内容', 0.5, 0.7, ?, "
            "datetime('now', ?))",
            (cid, mem_type, status, f"-{days_ago:g} days"),
        )
    conn.commit()
    conn.close()


def _sweep(path):
    """跑一次超期淘汰，返回 (标记行数, {id: status})。"""
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    rejected = MemoryManager()._reject_stale_candidates(cursor)
    conn.commit()
    statuses = dict(conn.execute("SELECT id, status FROM memory_candidates").fetchall())
    conn.close()
    return rejected, statuses


def test_stale_event_is_rejected_while_a_same_age_fact_survives(db):
    """同龄的两条候选：EVENT 该淘汰，FACT 还在等复现。缺陷正体现在这个对照上。"""
    age = MemoryManager._observing_ttl_days("EVENT") + 1
    _seed(db, [("ev", "EVENT", age), ("fact", "FACT", age)])

    rejected, statuses = _sweep(db)
    assert statuses["ev"] == "REJECTED"
    assert statuses["fact"] == "OBSERVING"
    assert rejected == 1


def test_each_time_sensitive_type_uses_its_own_ttl(db):
    """三个分档各自生效：天数从配置推，不写死在用例里。"""
    rows, expected = [], {}
    for mem_type in sorted(TIME_SENSITIVE):
        ttl = MemoryManager._observing_ttl_days(mem_type)
        rows += [(f"{mem_type}_old", mem_type, ttl + 1), (f"{mem_type}_young", mem_type, ttl - 1)]
        expected[f"{mem_type}_old"] = "REJECTED"
        expected[f"{mem_type}_young"] = "OBSERVING"
    _seed(db, rows)

    assert _sweep(db)[1] == expected


def test_stored_type_case_does_not_defeat_the_sweep(db):
    """库里存成小写也要命中分档。"""
    _seed(db, [("ev", "event", MemoryManager._observing_ttl_days("EVENT") + 1)])
    assert _sweep(db)[1]["ev"] == "REJECTED"


def test_missing_type_uses_the_global_ttl_and_is_not_exempt(db):
    """type 为 NULL 时按 FACT 处理：既不提前淘汰，也不因为「不属于任何分档」永久豁免。"""
    _seed(db, [("young", None, GLOBAL_TTL - 1), ("old", None, GLOBAL_TTL + 1)])

    statuses = _sweep(db)[1]
    assert statuses["young"] == "OBSERVING"
    assert statuses["old"] == "REJECTED"


def test_new_candidates_are_never_swept(db):
    """NEW 还没被评估过，不能被 TTL 顺手淘汰（锚点是 first_seen_at，不是「有没有排过队」）。"""
    _seed(db, [("ev", "EVENT", GLOBAL_TTL + 99)], status="NEW")

    rejected, statuses = _sweep(db)
    assert rejected == 0
    assert statuses["ev"] == "NEW"


def test_empty_by_type_config_still_sweeps_with_the_global_ttl(db, monkeypatch):
    """分档表清空时不得退化成 `NOT IN ()`（SQLite 语法错误），而是全部走全局 TTL。"""
    monkeypatch.setattr(
        "memory.memory_manager.MEMORY_CANDIDATE_MAX_OBSERVING_DAYS_BY_TYPE", {}
    )
    _seed(db, [("ev", "EVENT", 5), ("fact", "FACT", GLOBAL_TTL + 1)])

    statuses = _sweep(db)[1]
    assert statuses["ev"] == "OBSERVING", "分档没了，EVENT 应回到全局 30 天"
    assert statuses["fact"] == "REJECTED"


# ── 3. 主动验证不取时效型候选 ─────────────────────────────


@pytest.fixture
def observing_db(tmp_path, monkeypatch):
    """两条 OBSERVING 候选：EVENT 的 confidence **更高**。

    这个高低关系就是复现输入——没有类型过滤时它必然以「最接近晋升线」胜出，
    于是每一轮都挑中它去问同一个人同一件事。
    """
    path = tmp_path / "observe.db"
    monkeypatch.setattr("memory.proactive_target.DB_PATH", path)
    monkeypatch.setattr("memory.schema.DB_PATH", path)
    monkeypatch.setattr(
        "memory.proactive_target.PROACTIVE_VERIFY_EXCLUDE_TYPES", set(TIME_SENSITIVE)
    )

    from memory.schema import create_memory_candidates_table

    conn = sqlite3.connect(path)
    create_memory_candidates_table(conn)
    for cid, mem_type, content, conf in (
        ("ev", "EVENT", "听到地震预警", 0.8),
        ("fact", "FACT", "居住地附近主要种植甘蔗", 0.65),
    ):
        conn.execute(
            "INSERT INTO memory_candidates "
            "(id, group_shared_space, user_id, type, content, importance, confidence, status) "
            "VALUES (?, 'space_1', '1001', ?, ?, 0.5, ?, 'OBSERVING')",
            (cid, mem_type, content, conf),
        )
    conn.commit()
    conn.close()
    return path


def _drop(path, cid):
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM memory_candidates WHERE id = ?", (cid,))
    conn.commit()
    conn.close()


def test_event_is_skipped_even_when_it_has_the_highest_confidence(observing_db):
    """跳过 EVENT 后要**退到下一条**，而不是干脆放弃这一轮验证。"""
    from memory.proactive_target import _fetch_observing_candidate

    found = _fetch_observing_candidate("space_1", 1001)
    assert found is not None, "还有一条 FACT 可问，不该返回 None"
    assert found[0] == "fact"


def test_returns_none_when_every_candidate_is_time_sensitive(observing_db):
    """只剩时效型候选时宁可不问——上层会退到冷启动话题。"""
    from memory.proactive_target import _fetch_observing_candidate

    _drop(observing_db, "fact")
    assert _fetch_observing_candidate("space_1", 1001) is None


def test_stored_type_case_does_not_defeat_the_filter(observing_db):
    """库里存成小写也要被过滤掉。"""
    from memory.proactive_target import _fetch_observing_candidate

    _drop(observing_db, "fact")
    conn = sqlite3.connect(observing_db)
    conn.execute("UPDATE memory_candidates SET type = 'event' WHERE id = 'ev'")
    conn.commit()
    conn.close()

    assert _fetch_observing_candidate("space_1", 1001) is None


def test_empty_exclude_config_allows_every_type(observing_db, monkeypatch):
    """留空的语义是「所有类型都可验证」，不能顺手保留一个默认排除项。"""
    from memory.proactive_target import _fetch_observing_candidate

    monkeypatch.setattr("memory.proactive_target.PROACTIVE_VERIFY_EXCLUDE_TYPES", set())

    found = _fetch_observing_candidate("space_1", 1001)
    assert found is not None
    assert found[0] == "ev"


def test_type_filter_and_last_asked_exclusion_apply_together(observing_db):
    """两层排除叠加：EVENT 被类型挡掉，FACT 又是上次刚问过的 → 这一轮不问。"""
    from memory.proactive_target import _fetch_observing_candidate

    assert _fetch_observing_candidate("space_1", 1001, exclude_id="fact") is None


def test_unknown_type_is_still_verifiable(observing_db):
    """排除表是白名单之外的黑名单：没登记的类型（含脏值）仍应可验证。

    反过来实现成「只允许 FACT」会静默丢掉 PREFERENCE / STYLE 等的验证机会。
    """
    from memory.proactive_target import _fetch_observing_candidate

    _drop(observing_db, "ev")
    conn = sqlite3.connect(observing_db)
    conn.execute("UPDATE memory_candidates SET type = 'PREFERENCE' WHERE id = 'fact'")
    conn.commit()
    conn.close()

    found = _fetch_observing_candidate("space_1", 1001)
    assert found is not None
    assert found[0] == "fact"


def test_shipped_default_excludes_the_time_sensitive_types():
    """发布默认值的守卫：三个时效型必须在排除表里，稳定型必须不在。"""
    from config import PROACTIVE_VERIFY_EXCLUDE_TYPES

    assert TIME_SENSITIVE <= PROACTIVE_VERIFY_EXCLUDE_TYPES
    assert not PROACTIVE_VERIFY_EXCLUDE_TYPES & {"FACT", "PREFERENCE", "STYLE", "RELATION"}
