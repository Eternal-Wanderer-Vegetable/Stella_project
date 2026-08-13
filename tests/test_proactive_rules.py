# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动发言规则的回归测试。

覆盖新规则：
1. 消息频率过低（平均间隔 >= PROACTIVE_LOW_FREQ_INTERVAL，或消息不足两条）
   时不主动发言（概率为 0），避免在冷清群自言自语；
2. 消息频率足够（平均间隔更小）时复用上一版概率换算；
3. 与最近一次主动/回复高度相似的内容会被去重跳过，防止刷屏。

全程不触网，也不导入 ai_gateway（避免拉起 NoneBot 事件监听）。
"""

from memory import proactive
from memory.proactive import ProactiveController, _ngrams


def _reset_config(monkeypatch):
    """把关键配置收紧/固定，让断言不依赖 .env 里的真实值。"""
    monkeypatch.setattr(proactive, "PROACTIVE_COOLDOWN", 0)
    monkeypatch.setattr(proactive, "PROACTIVE_FREQ_WINDOW", 10)
    monkeypatch.setattr(proactive, "PROACTIVE_HIGH_FREQ_INTERVAL", 20.0)
    monkeypatch.setattr(proactive, "PROACTIVE_LOW_FREQ_INTERVAL", 180.0)
    monkeypatch.setattr(proactive, "PROACTIVE_MAX_PROB", 0.5)
    monkeypatch.setattr(proactive, "PROACTIVE_MIN_PROB", 0.05)


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
    """平均间隔超过 PROACTIVE_LOW_FREQ_INTERVAL（冷清群）时概率为 0。"""
    _reset_config(monkeypatch)
    c = ProactiveController()
    # 两条消息相隔 200s > 180s → 频率过低
    monkeypatch.setattr(c, "average_interval", lambda _gid: 200.0)
    assert c.speak_probability(1) == 0.0
    assert c.should_speak(1) is False


def test_active_group_reuses_previous_logic(monkeypatch):
    """消息频率高于阈值（平均间隔 < PROACTIVE_LOW_FREQ_INTERVAL）时复用旧概率。

    - 平均间隔 <= PROACTIVE_HIGH_FREQ_INTERVAL → MIN_PROB；
    - 平均间隔介于 HIGH 与 LOW 之间 → MIN→MAX 线性插值。
    """
    _reset_config(monkeypatch)
    c = ProactiveController()
    monkeypatch.setattr(c, "average_interval", lambda _gid: 10.0)  # 高频
    assert c.speak_probability(1) == proactive.PROACTIVE_MIN_PROB

    monkeypatch.setattr(c, "average_interval", lambda _gid: 100.0)  # 中频
    p = c.speak_probability(1)
    assert proactive.PROACTIVE_MIN_PROB < p < proactive.PROACTIVE_MAX_PROB


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
