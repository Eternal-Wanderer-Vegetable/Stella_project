# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动 @ 配额与选人策略（memory.proactive_target）的单元测试。

覆盖 D2a：at_quota 配额插值、can_at_user 排除规则、_cooldown_elapsed 解析、
pick_target 的 verify / coldstart 两种选人路径与 exclude 过滤。
覆盖 D2b：_topic_covered 关键词避让、ProactiveTarget.nickname 默认值。
全部纯逻辑，不触网。
"""
import sqlite3
from datetime import datetime, timedelta

import memory.proactive as proactive
import memory.proactive_target as pt
from config.spaces import resolve_space
from memory import proactive_state
from memory.proactive_target import (
    ProactiveTarget,
    _cooldown_elapsed,
    _fetch_observing_candidate,
    _topic_covered,
    at_quota,
    can_at_user,
    pick_target,
)


def _faketicks():
    """注入可控递增的 time.monotonic，让「最近发言排序/活跃窗」可确定地断言。"""
    tick = [100.0]

    def _next() -> float:
        v = tick[0]
        tick[0] += 1.0
        return v

    return _next


def _provision_candidates(db, rows):
    """建最小 memory_candidates 表（供 _fetch_observing_candidate 查询）并插入行。

    候选按共享空间归属：行首的归属列是 ``group_shared_space``（用 resolve_space 得到），
    不再用 ``group_id``——否则 ``WHERE group_shared_space = ?`` 会因缺列被吞成空结果。
    """
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_candidates (
            id TEXT PRIMARY KEY,
            group_shared_space TEXT,
            user_id TEXT,
            type TEXT,
            content TEXT,
            confidence REAL,
            status TEXT
        )
    """)
    conn.executemany(
        "INSERT OR REPLACE INTO memory_candidates "
        "(id, group_shared_space, user_id, type, content, confidence, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


# ── at_quota ─────────────────────────────────────────────

def test_at_quota_interpolation(monkeypatch):
    """24h 发言 0/20/60/100/200 → 配额 2/2/3/4/4（BASE=2, BONUS_MAX=2, LOW=20, HIGH=100）。"""
    monkeypatch.setattr(pt, "PROACTIVE_AT_QUOTA_BASE", 2)
    monkeypatch.setattr(pt, "PROACTIVE_AT_QUOTA_BONUS_MAX", 2)
    monkeypatch.setattr(pt, "PROACTIVE_AT_BONUS_MSGS_LOW", 20)
    monkeypatch.setattr(pt, "PROACTIVE_AT_BONUS_MSGS_HIGH", 100)
    counts = {0: 0, 1: 20, 2: 60, 3: 100, 4: 200}
    monkeypatch.setattr(pt, "count_user_messages_24h", lambda g, u: counts[u])
    expected = {0: 2, 1: 2, 2: 3, 3: 4, 4: 4}
    for uid, want in expected.items():
        assert at_quota(1, uid) == want, f"uid={uid}"


def test_at_quota_bad_bounds_no_error(monkeypatch):
    """BONUS_MSGS_HIGH <= LOW 时不抛异常（退化为分段函数）。"""
    monkeypatch.setattr(pt, "PROACTIVE_AT_BONUS_MSGS_LOW", 20)
    monkeypatch.setattr(pt, "PROACTIVE_AT_BONUS_MSGS_HIGH", 10)
    monkeypatch.setattr(pt, "count_user_messages_24h", lambda g, u: 999)
    assert at_quota(1, 1) == pt.PROACTIVE_AT_QUOTA_BASE + pt.PROACTIVE_AT_QUOTA_BONUS_MAX
    monkeypatch.setattr(pt, "count_user_messages_24h", lambda g, u: 0)
    assert at_quota(1, 1) == pt.PROACTIVE_AT_QUOTA_BASE


# ── _cooldown_elapsed ────────────────────────────────────

def test_cooldown_elapsed_variants(monkeypatch):
    """None → True；刚 @ 过 → False；超过冷却 → True；脏字符串 → True。"""
    monkeypatch.setattr(pt, "PROACTIVE_AT_USER_COOLDOWN", 7200.0)
    assert _cooldown_elapsed(None) is True
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    assert _cooldown_elapsed(now_str) is False
    long_ago = (datetime.now() - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
    assert _cooldown_elapsed(long_ago) is True
    assert _cooldown_elapsed("@@不是时间@@") is True
    # 带微秒格式也兼容
    frac = (datetime.now() - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S.%f")
    assert _cooldown_elapsed(frac) is True


# ── can_at_user ──────────────────────────────────────────

def _setup_db(monkeypatch, tmp_path) -> None:
    db = tmp_path / "ps.db"
    monkeypatch.setattr(proactive_state, "DB_PATH", db)
    monkeypatch.setattr(pt, "DB_PATH", db)


def test_can_at_user_quota_full(tmp_path, monkeypatch):
    """当日配额已满 → 拒绝。"""
    _setup_db(monkeypatch, tmp_path)
    for _ in range(pt.PROACTIVE_AT_QUOTA_BASE):
        proactive_state.record_at(1, 2001)
    ok, reason = can_at_user(1, 2001)
    assert ok is False
    assert "配额已满" in reason


def test_can_at_user_quota_with_record_at_flow(tmp_path, monkeypatch):
    """D2a 判定与 D2c 记账串起来：record_at 两次达配额后 can_at_user 拒绝。

    把 24h 发言 monkeypatch 成 0 使配额固定为 BASE=2，然后按真实链路
    record_at 两次（发出即计数）——此时该用户当日配额已满，不能再 @。
    """
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(pt, "PROACTIVE_AT_QUOTA_BASE", 2)
    monkeypatch.setattr(pt, "PROACTIVE_AT_QUOTA_BONUS_MAX", 2)
    monkeypatch.setattr(pt, "count_user_messages_24h", lambda g, u: 0)

    # 配额未满时允许
    ok, reason = can_at_user(1, 2001)
    assert ok is True

    proactive_state.record_at(1, 2001)
    proactive_state.record_at(1, 2001)
    ok, reason = can_at_user(1, 2001)
    assert ok is False
    assert "配额已满" in reason
    # 第二个用户不受影响
    ok, _ = can_at_user(1, 2002)
    assert ok is True


def test_can_at_user_no_reply_backoff(tmp_path, monkeypatch):
    """连续无回应达上限 → 拒绝且理由含「退避」。"""
    _setup_db(monkeypatch, tmp_path)
    proactive_state.record_at(1, 2001)
    for _ in range(pt.PROACTIVE_MAX_NO_REPLY):
        proactive_state.record_reply_result(1, 2001, replied=False)
    ok, reason = can_at_user(1, 2001)
    assert ok is False
    assert "退避" in reason


def test_can_at_user_right_after_record_at_is_cooldown(tmp_path, monkeypatch):
    """record_at 之后立刻 can_at_user 必须拒绝（冷却未过），且理由含「冷却」。

    关键回归（2026-08-14）：last_at_at 由 SQLite CURRENT_TIMESTAMP 写入（UTC），
    冷却判定必须按 UTC 解析——旧代码用 datetime.now()（本地时间）比较，在
    UTC+8 下 elapsed 恒 > 7200s，冷却形同虚设，本用例直接失败。
    该断言在任何运行环境时区下都应成立。
    """
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(pt, "count_user_messages_24h", lambda g, u: 0)
    proactive_state.record_at(1, 2001)
    ok, reason = can_at_user(1, 2001)
    assert ok is False
    assert "冷却" in reason


def test_can_at_user_disabled(monkeypatch):
    """PROACTIVE_AT_ENABLED=False → 一律拒绝。"""
    monkeypatch.setattr(pt, "PROACTIVE_AT_ENABLED", False)
    monkeypatch.setattr(pt, "count_user_messages_24h", lambda g, u: 0)
    ok, reason = can_at_user(1, 2001)
    assert ok is False
    assert "已关闭" in reason


# ── pick_target ──────────────────────────────────────────

def test_pick_target_no_active_users(monkeypatch):
    """无活跃用户 → None。"""
    monkeypatch.setattr(proactive.time, "monotonic", _faketicks())
    assert pick_target(1) is None


def test_pick_target_verify_mode(tmp_path, monkeypatch):
    """有 OBSERVING 候选的活跃用户 → mode=verify 且 candidate_id 正确。"""
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(proactive.time, "monotonic", _faketicks())
    c = proactive.ProactiveController()
    monkeypatch.setattr(pt, "get_proactive", lambda: c)
    c.record_message(1, 2001)
    _provision_candidates(tmp_path / "ps.db", [
        ("cand-1", resolve_space(1), "2001", "FACT", "他的显卡是5080", 0.8, "OBSERVING"),
    ])

    target = pick_target(1)
    assert target is not None
    assert isinstance(target, ProactiveTarget)
    assert target.mode == "verify"
    assert target.user_id == 2001
    assert target.candidate_id == "cand-1"
    assert "候选" in target.reason


def test_pick_target_verify_prefers_highest_confidence(tmp_path, monkeypatch):
    """多个用户有候选 → 选 confidence 最高的那个。"""
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(proactive.time, "monotonic", _faketicks())
    c = proactive.ProactiveController()
    monkeypatch.setattr(pt, "get_proactive", lambda: c)
    c.record_message(1, 2001)  # t=100
    c.record_message(1, 2002)  # t=101
    _provision_candidates(tmp_path / "ps.db", [
        ("cand-low", resolve_space(1), "2001", "FACT", "低置信候选", 0.65, "OBSERVING"),
        ("cand-high", resolve_space(1), "2002", "FACT", "高置信候选", 0.8, "OBSERVING"),
    ])

    target = pick_target(1)
    assert target is not None
    assert target.user_id == 2002
    assert target.candidate_id == "cand-high"


def test_pick_target_coldstart_avoids_last_topic(tmp_path, monkeypatch):
    """无候选 → mode=coldstart，且 topic 不等于 last_asked_topic。

    注意：record_at 会把 last_at_at 写成 CURRENT_TIMESTAMP（UTC），立即处于
    PROACTIVE_AT_USER_COOLDOWN 冷却内（这正是 2026-08-14 修复后的正确行为，
    旧代码在 UTC+8 下因时区偏差恒判「已过」）。本用例只测冷启动避让逻辑，
    因此把冷却压到 0 让用户可被选中；冷却判定本身由
    test_can_at_user_right_after_record_at_is_cooldown 单独覆盖。
    """
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(pt, "PROACTIVE_COLDSTART_TOPICS", ["游戏话题", "美食话题"])
    monkeypatch.setattr(pt, "PROACTIVE_AT_USER_COOLDOWN", 0.0)
    monkeypatch.setattr(proactive.time, "monotonic", _faketicks())
    c = proactive.ProactiveController()
    monkeypatch.setattr(pt, "get_proactive", lambda: c)
    c.record_message(1, 2001)
    proactive_state.record_at(1, 2001, topic="游戏话题")

    target = pick_target(1)
    assert target is not None
    assert target.mode == "coldstart"
    assert target.topic != "游戏话题"
    assert target.topic == "美食话题"


def test_pick_target_exclude_user_ids(tmp_path, monkeypatch):
    """exclude_user_ids 生效：被排除的活跃用户不再被选中。"""
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(proactive.time, "monotonic", _faketicks())
    c = proactive.ProactiveController()
    monkeypatch.setattr(pt, "get_proactive", lambda: c)
    c.record_message(1, 2001)  # t=100
    c.record_message(1, 2002)  # t=101
    _provision_candidates(tmp_path / "ps.db", [
        ("cand-1", resolve_space(1), "2001", "FACT", "候选一", 0.7, "OBSERVING"),
        ("cand-2", resolve_space(1), "2002", "FACT", "候选二", 0.8, "OBSERVING"),
    ])

    # 不排除时选最高置信的 2002
    assert pick_target(1).user_id == 2002
    # 排除 2002 后只剩 2001
    target = pick_target(1, exclude_user_ids={2002})
    assert target is not None
    assert target.user_id == 2001
    assert target.candidate_id == "cand-1"


def test_pick_target_exclude_users_config(tmp_path, monkeypatch):
    """PROACTIVE_AT_EXCLUDE_USERS 生效：配置名单里的活跃用户不被选中，
    名单外的用户仍可被选中。"""
    _setup_db(monkeypatch, tmp_path)
    monkeypatch.setattr(proactive.time, "monotonic", _faketicks())
    c = proactive.ProactiveController()
    monkeypatch.setattr(pt, "get_proactive", lambda: c)
    c.record_message(1, 2001)  # t=100
    c.record_message(1, 2002)  # t=101
    _provision_candidates(tmp_path / "ps.db", [
        ("cand-1", resolve_space(1), "2001", "FACT", "候选一", 0.7, "OBSERVING"),
        ("cand-2", resolve_space(1), "2002", "FACT", "候选二", 0.8, "OBSERVING"),
    ])

    # 不排除时选最高置信的 2002
    assert pick_target(1).user_id == 2002
    # 配置排除 2002 后只剩 2001 可选
    monkeypatch.setattr(pt, "PROACTIVE_AT_EXCLUDE_USERS", {2002})
    target = pick_target(1)
    assert target is not None
    assert target.user_id == 2001
    assert target.candidate_id == "cand-1"
    # 名单外的用户仍可被选中：两个都排除则无目标
    monkeypatch.setattr(pt, "PROACTIVE_AT_EXCLUDE_USERS", {2001, 2002})
    assert pick_target(1) is None


def test_fetch_observing_candidate_window(tmp_path, monkeypatch):
    """OBSERVING 候选按 confidence 区间筛选：过低/已达标/其他状态不取。"""
    db = tmp_path / "ps.db"
    monkeypatch.setattr(pt, "DB_PATH", db)
    space = resolve_space(1)
    _provision_candidates(db, [
        ("too-low", space, "2001", "FACT", "太低的", 0.2, "OBSERVING"),
        ("too-high", space, "2001", "FACT", "已达标", 0.95, "OBSERVING"),
        ("rejected", space, "2001", "FACT", "已拒绝", 0.7, "REJECTED"),
        ("right", space, "2001", "FACT", "可验证", 0.7, "OBSERVING"),
    ])
    found = _fetch_observing_candidate(space, 2001)
    assert found is not None
    assert found[0] == "right"


# ── D2b：冷启动关键词避让与昵称 ──────────────────────────

def test_topic_covered_variants():
    """_topic_covered：空 known → False；全部词元命中 → True；部分命中 → False。"""
    assert _topic_covered("RTX5080", "") is False
    assert _topic_covered("RTX5080", "他有一张 RTX5080 显卡") is True
    assert _topic_covered("RTX5080", "他有一张 4090 显卡") is False
    # 要求全部关键词都命中——部分命中不算已知（宁可多问一次）
    assert _topic_covered("RTX5080 显卡", "他有一张 RTX5080") is False
    assert _topic_covered("RTX5080 显卡", "他有一张 RTX5080 显卡") is True


def test_target_nickname_default():
    """ProactiveTarget.nickname 默认值为「对方」。"""
    t = ProactiveTarget(user_id=2001, mode="coldstart")
    assert t.nickname == "对方"
    # 可变 dataclass：ai_gateway 拿到 target 后可直接赋值
    t.nickname = "小明"
    assert t.nickname == "小明"
