# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""虚拟时钟验收（计划 §6.7.3 时钟合同）。

覆盖：advance 跨午夜、UTC+8 时区映射、TTL/冷却语义、monotonic 与虚拟时间
独立、naive 时间与倒退拒绝。
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from core.evaluation.clock import Clock, SystemClock, VirtualClock


def test_virtual_clock_starts_and_advances():
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    clock = VirtualClock(start=start)
    assert clock.now() == start
    clock.advance(90)
    assert clock.now() == datetime(2026, 1, 1, 12, 1, 30, tzinfo=timezone.utc)


def test_advance_crosses_midnight():
    clock = VirtualClock(start=datetime(2026, 3, 14, 23, 59, 30, tzinfo=timezone.utc))
    clock.advance(45)
    assert clock.now() == datetime(2026, 3, 15, 0, 0, 15, tzinfo=timezone.utc)
    # 再推一天：日期跃迁保持 aware UTC 语义
    clock.advance(24 * 3600)
    assert clock.now() == datetime(2026, 3, 16, 0, 0, 15, tzinfo=timezone.utc)


def test_utc8_timezone_mapping_and_midnight_in_plus8():
    shanghai = ZoneInfo("Asia/Shanghai")
    clock = VirtualClock(start=datetime(2026, 1, 1, 8, 0, 0, tzinfo=shanghai))
    # 起点即 UTC 2026-01-01 00:00：aware 语义换算一致
    assert clock.now().astimezone(timezone.utc) == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    # 推进 16 小时：上海刚跨午夜（1 月 2 日 0 点），UTC 是 1 月 1 日 16 点
    clock.advance(16 * 3600)
    assert clock.now().astimezone(shanghai) == datetime(2026, 1, 2, 0, 0, 0, tzinfo=shanghai)
    assert clock.now().astimezone(timezone.utc) == datetime(2026, 1, 1, 16, 0, 0, tzinfo=timezone.utc)
    assert clock.now().astimezone(timezone.utc).day == 1


def test_ttl_and_cooldown_judge_by_virtual_time():
    clock = VirtualClock(start=datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc))
    first_seen = clock.now()
    ttl_seconds = 3600
    clock.advance(ttl_seconds - 1)
    assert (clock.now() - first_seen).total_seconds() < ttl_seconds  # 冷却未到
    clock.advance(2)
    assert (clock.now() - first_seen).total_seconds() >= ttl_seconds  # TTL 到期判定成立
    # 冷却窗口内的第二次判定：虚拟时间不再前进，窗口恒成立
    frozen = clock.now()
    clock.advance(0)
    assert clock.now() == frozen


def test_monotonic_is_independent_of_virtual_time():
    clock = VirtualClock()
    monotonic_before = clock.monotonic()
    clock.advance(100_000)  # 虚拟业务时间跳过一天多
    elapsed_real = clock.monotonic() - monotonic_before
    assert 0 <= elapsed_real < 5  # 真实 monotonic 只走了真实的一瞬，与 advance 无关
    assert (clock.now() - datetime(2026, 1, 1, tzinfo=timezone.utc)).total_seconds() >= 100_000


def test_rejects_naive_start_and_backward_advance():
    with pytest.raises(ValueError):
        VirtualClock(start=datetime(2026, 1, 1, 0, 0, 0))  # naive：拒绝主机时区渗入
    clock = VirtualClock()
    with pytest.raises(ValueError):
        clock.advance(-1)  # 业务时间倒退会让 TTL/冷却出现幻觉


def test_advance_to_is_forward_only():
    clock = VirtualClock(start=datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc))
    clock.advance_to(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc))  # 更早：截停
    assert clock.now() == datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
    clock.advance_to(datetime(2026, 1, 3, 12, 0, 0, tzinfo=timezone.utc))
    assert clock.now() == datetime(2026, 1, 3, 12, 0, 0, tzinfo=timezone.utc)


def test_clock_protocol_contract():
    """两个实现都满足同一 Clock 协议：now 恒 aware UTC、monotonic 恒真实。"""
    for clock in (SystemClock(), VirtualClock()):
        assert isinstance(clock, Clock)
        assert clock.now().tzinfo is not None
        now_utc = clock.now().astimezone(timezone.utc)
        assert now_utc.tzinfo == timezone.utc
        m1 = clock.monotonic()
        m2 = clock.monotonic()
        assert m2 >= m1
