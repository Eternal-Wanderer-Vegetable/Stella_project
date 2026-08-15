# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动发言规则的回归测试。

覆盖：
1. 消息不足两条（无法估算频率）时不主动发言（概率为 0）；
2. 双锚点插值曲线（FAST/SLOW 两锚点 + GAMMA 整形）：区间端点取值、中点插值、
   GAMMA 对概率的压缩方向、锚点异常不抛异常；
3. 与最近一次主动/回复高度相似的内容会被去重跳过，防止刷屏；
4. 按用户追踪活跃度：群级间隔聚合、active_users 时间窗过滤与倒序、用户级间隔。

全程不触网，也不导入 ai_gateway（避免拉起 NoneBot 事件监听）。
"""

import pytest

from memory import proactive
from memory.proactive import ProactiveController, _ngrams


def _reset_config(monkeypatch):
    """把关键配置收紧/固定，让断言不依赖 .env 里的真实值。"""
    monkeypatch.setattr(proactive, "PROACTIVE_COOLDOWN", 0)
    monkeypatch.setattr(proactive, "PROACTIVE_FREQ_WINDOW", 10)
    # 双锚点插值曲线参数（旧 MIN/MAX/HIGH/LOW 已废弃，仅保留定义兼容 .env）
    monkeypatch.setattr(proactive, "PROACTIVE_INTERVAL_FAST", 20.0)
    monkeypatch.setattr(proactive, "PROACTIVE_INTERVAL_SLOW", 180.0)
    monkeypatch.setattr(proactive, "PROACTIVE_PROB_AT_FAST", 0.35)
    monkeypatch.setattr(proactive, "PROACTIVE_PROB_AT_SLOW", 0.0)
    monkeypatch.setattr(proactive, "PROACTIVE_PROB_GAMMA", 1.0)


def _faketicks():
    """注入可控的递增 time.monotonic，让「最近发言排序」可确定地断言。"""
    tick = [100.0]

    def _next() -> float:
        v = tick[0]
        tick[0] += 1.0
        return v

    return _next


def test_silent_group_never_speaks(monkeypatch):
    """消息不足两条（interval 为 None）时概率必须为 0。"""
    _reset_config(monkeypatch)
    c = ProactiveController()
    c.record_message(1)  # 只有一条消息，不足以估算频率
    assert c.average_interval(1) is None
    assert c.speak_probability(1) == 0.0
    assert c.should_speak(1) is False


def test_too_low_frequency_never_speaks(monkeypatch):
    """平均间隔超过 SLOW 锚点（冷清群）时概率回到慢端锚点（默认 0，不主动发言）。"""
    _reset_config(monkeypatch)
    c = ProactiveController()
    # 两条消息相隔 200s > SLOW(180) → 概率为慢端锚点
    monkeypatch.setattr(c, "average_interval", lambda _gid: 200.0)
    assert c.speak_probability(1) == proactive.PROACTIVE_PROB_AT_SLOW
    assert c.should_speak(1) is False


def test_previous_logic_still_respects_cooldown(monkeypatch):
    """冷却期内即使概率命中也不发言。"""
    _reset_config(monkeypatch)
    c = ProactiveController()
    monkeypatch.setattr(c, "average_interval", lambda _gid: 10.0)
    monkeypatch.setattr(proactive, "PROACTIVE_COOLDOWN", 99999)
    c.mark_spoke(1)
    assert c.should_speak(1) is False


def test_recently_spoken_dedup(monkeypatch):
    """新台词与上次发言高度相似时应判定为重复（防刷屏）。"""
    _reset_config(monkeypatch)
    c = ProactiveController()
    first = ["8个西瓜也太多了吧"]
    c.record_spoken(1, first)
    assert c.recently_spoken(1, ["8个西瓜也太多了吧"]) is True
    assert c.recently_spoken(1, ["西瓜也太多了"]) is True
    assert c.recently_spoken(1, ["快分我一个嘛"]) is False
    assert c.recently_spoken(1, []) is False
    assert c.recently_spoken(1, None) is False


def test_ngrams_is_reasonable():
    """_ngrams 应切出相邻字符片段，且无空白夹带着。"""
    segs = _ngrams("好想吃西瓜", 4)
    assert "好吃西瓜" in segs or "好想吃西" in segs
    assert all(" " not in s for s in segs)


# ── 按用户追踪活跃度（D1-②） ────────────────────────────

def test_group_interval_aggregated_across_users(monkeypatch):
    """record_message 带 user_id 后，群级平均间隔由各用户时间戳聚合，行为不变。"""
    _reset_config(monkeypatch)
    c = ProactiveController()
    c.record_message(1, 1001)
    c.record_message(1, 1002)
    c.record_message(1, 1003)
    interval = c.average_interval(1)
    assert interval is not None
    assert interval >= 0.0
    # 每用户各只有一条 → 用户级间隔不足两条，返回 None
    assert c.user_average_interval(1, 1001) is None


def test_active_users_filters_window_and_sorts_desc(monkeypatch):
    """active_users 只返回窗口内发过言的用户，按最近发言倒序，排除伪用户 0。"""
    _reset_config(monkeypatch)
    # Windows 的 time.monotonic 在一个时钟片内可能返回相同值，注入可控时间保证排序可断言
    import time as _time

    monkeypatch.setattr(_time, "monotonic", _faketicks())
    c = ProactiveController()
    c.record_message(1, 1001)  # t=100
    c.record_message(1, 1002)  # t=101，最近 → 排前面
    c.record_message(1)        # t=102，伪用户 0（旧调用兜底）
    c.record_message(2, 1001)  # t=103，另一个群，不影响群 1

    users = c.active_users(1, within_seconds=3600)
    assert 0 not in users
    assert users == [1002, 1001]
    # 窗口收紧到 0 → 无人在窗口内
    assert c.active_users(1, within_seconds=0) == []


def test_user_average_interval_requires_two(monkeypatch):
    """user_average_interval 不足两条返回 None。"""
    _reset_config(monkeypatch)
    c = ProactiveController()
    c.record_message(1, 1001)
    assert c.user_average_interval(1, 1001) is None
    assert c.user_average_interval(1, 9999) is None
    c.record_message(1, 1001)
    assert c.user_average_interval(1, 1001) is not None


# ── 双锚点插值曲线（D2a） ────────────────────────────────

def _reset_curve(monkeypatch):
    """把双锚点曲线参数固定，让断言不依赖 .env 里的真实值。"""
    monkeypatch.setattr(proactive, "PROACTIVE_INTERVAL_FAST", 20.0)
    monkeypatch.setattr(proactive, "PROACTIVE_INTERVAL_SLOW", 180.0)
    monkeypatch.setattr(proactive, "PROACTIVE_PROB_AT_FAST", 0.35)
    monkeypatch.setattr(proactive, "PROACTIVE_PROB_AT_SLOW", 0.0)
    monkeypatch.setattr(proactive, "PROACTIVE_PROB_GAMMA", 1.0)


def test_curve_at_fast_anchor(monkeypatch):
    """interval <= FAST → PROB_AT_FAST。"""
    _reset_curve(monkeypatch)
    c = ProactiveController()
    monkeypatch.setattr(c, "average_interval", lambda _gid: 5.0)
    assert c.speak_probability(1) == proactive.PROACTIVE_PROB_AT_FAST


def test_curve_at_slow_anchor(monkeypatch):
    """interval >= SLOW → PROB_AT_SLOW。"""
    _reset_curve(monkeypatch)
    c = ProactiveController()
    monkeypatch.setattr(c, "average_interval", lambda _gid: 300.0)
    assert c.speak_probability(1) == proactive.PROACTIVE_PROB_AT_SLOW


def test_curve_midpoint_between_anchors(monkeypatch):
    """区间中点（GAMMA=1）落在两个锚点之间。"""
    _reset_curve(monkeypatch)
    c = ProactiveController()
    mid_interval = (proactive.PROACTIVE_INTERVAL_FAST + proactive.PROACTIVE_INTERVAL_SLOW) / 2
    monkeypatch.setattr(c, "average_interval", lambda _gid: mid_interval)
    p = c.speak_probability(1)
    low, high = sorted([proactive.PROACTIVE_PROB_AT_FAST, proactive.PROACTIVE_PROB_AT_SLOW])
    assert low <= p <= high
    # GAMMA=1 时 t=0.5 → p_slow + (p_fast-p_slow)*0.5 = 两锚点均值
    assert p == pytest.approx((proactive.PROACTIVE_PROB_AT_FAST + proactive.PROACTIVE_PROB_AT_SLOW) / 2)


def test_curve_gamma_2_lower_than_gamma_1(monkeypatch):
    """同一间隔下 GAMMA=2 的概率低于 GAMMA=1（更保守地倾向活跃端）。"""
    _reset_curve(monkeypatch)
    c1 = ProactiveController()
    monkeypatch.setattr(c1, "average_interval", lambda _gid: 100.0)
    monkeypatch.setattr(proactive, "PROACTIVE_PROB_GAMMA", 1.0)
    p1 = c1.speak_probability(1)
    monkeypatch.setattr(proactive, "PROACTIVE_PROB_GAMMA", 2.0)
    p2 = c1.speak_probability(1)
    assert p2 < p1


def test_curve_bad_anchor_no_error(monkeypatch):
    """锚点异常（SLOW <= FAST）不抛异常，退化到慢端概率或插值。"""
    _reset_curve(monkeypatch)
    monkeypatch.setattr(proactive, "PROACTIVE_INTERVAL_SLOW", 10.0)  # <= FAST(20)
    c = ProactiveController()
    monkeypatch.setattr(c, "average_interval", lambda _gid: 50.0)
    p = c.speak_probability(1)
    assert 0.0 <= p <= 1.0


# ── 消息数门槛（A-1：新消息足够才开口） ──────────────────

def test_messages_since_spoke_counts_resets(monkeypatch):
    """record_message 三次后计数为 3；mark_spoke 快照后归零；再收两条为 2。"""
    _reset_config(monkeypatch)
    c = ProactiveController()
    c.record_message(1)
    c.record_message(1)
    c.record_message(1)
    assert c.messages_since_spoke(1) == 3
    c.mark_spoke(1)
    assert c.messages_since_spoke(1) == 0
    c.record_message(1)
    c.record_message(1)
    assert c.messages_since_spoke(1) == 2


def test_has_enough_new_messages_threshold(monkeypatch):
    """门槛设 5：4 条时 False，5 条时 True。"""
    _reset_config(monkeypatch)
    monkeypatch.setattr(proactive, "PROACTIVE_MIN_MESSAGES_SINCE_SPOKE", 5)
    c = ProactiveController()
    for _ in range(4):
        c.record_message(1)
    assert c.has_enough_new_messages(1) is False
    c.record_message(1)
    assert c.has_enough_new_messages(1) is True


def test_has_enough_new_messages_zero_threshold(monkeypatch):
    """门槛设 0 → 恒为 True（不限制）。"""
    _reset_config(monkeypatch)
    monkeypatch.setattr(proactive, "PROACTIVE_MIN_MESSAGES_SINCE_SPOKE", 0)
    c = ProactiveController()
    assert c.has_enough_new_messages(1) is True
    c.record_message(1)
    assert c.has_enough_new_messages(1) is True


def test_no_snapshot_does_not_block_forever(monkeypatch):
    """未 mark_spoke 过（模拟重启）：快照缺失时差值等于累计数，不会永久 False。"""
    _reset_config(monkeypatch)
    monkeypatch.setattr(proactive, "PROACTIVE_MIN_MESSAGES_SINCE_SPOKE", 5)
    c = ProactiveController()
    for _ in range(4):
        c.record_message(1)
    assert c.messages_since_spoke(1) == 4
    assert c.has_enough_new_messages(1) is False
    c.record_message(1)
    assert c.has_enough_new_messages(1) is True
