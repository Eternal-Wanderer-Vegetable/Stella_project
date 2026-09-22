# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Cron 方言解析、时区换算与 DST 行为的基线。

DST 用 America/New_York 2026 年的真实跳变日验证：
- 春季跳变 2026-03-08（02:00→03:00，02:30 不存在）；
- 秋季回拨 2026-11-01（02:00→01:00，01:30 出现两次）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from stella_project.plugins.bot_main.scheduling.cron import (
    CronError,
    parse_cron,
    resolve_timezone,
)

UTC = timezone.utc
NY = ZoneInfo("America/New_York")
SH = ZoneInfo("Asia/Shanghai")


def _utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


# ── 解析与校验 ───────────────────────────────────────

@pytest.mark.parametrize(
    "expr",
    [
        "* * * * *",
        "*/15 * * * *",
        "0 9 * * MON-FRI",
        "0 9-17/2 * * MON-FRI",
        "30 8 1,15 JAN,JUL *",
        "0 0 * * SUN",
        "5 3 * * MON,WED,FRI",
        "0-30/5 * * * *",
        "0 0 13 * FRI",
    ],
)
def test_valid_exprs_parse(expr):
    schedule = parse_cron(expr, "Asia/Shanghai")
    assert schedule is not None
    assert schedule.tz_name == "Asia/Shanghai"


@pytest.mark.parametrize(
    "expr",
    [
        "",                       # 空
        "* * * *",                # 4 字段
        "* * * * * *",            # 6 字段（v1 无秒/年）
        "61 * * * *",             # 分钟越界
        "* 24 * * *",             # 小时越界
        "0 0 32 * *",             # 日期越界
        "0 0 * 13 *",             # 月份越界
        "MON * * * *",            # 名称出现在分钟字段
        "0 0 * * MONBAD",         # 未知星期名称
        "0 9 * * 1",              # 数字星期（歧义）→ 拒绝
        "0 9 * * 1-5",            # 数字星期范围 → 拒绝
        "*/0 * * * *",            # 步进 0
        "5-2 * * * *",            # 倒序范围
        "5/15 * * * *",           # 步进只许配 * 或范围
        "1,,3 * * * *",           # 空片段
        "? * * * *",              # Quartz 风格占位符
    ],
)
def test_invalid_exprs_rejected(expr):
    with pytest.raises(CronError):
        parse_cron(expr, "Asia/Shanghai")


def test_numeric_weekday_rejection_message_mentions_names():
    with pytest.raises(CronError, match="MON/TUE"):
        parse_cron("0 9 * * 0", "UTC")


# ── 时区 ─────────────────────────────────────────────

def test_timezone_iana_offset_and_utc():
    assert resolve_timezone("Asia/Shanghai") == SH
    assert resolve_timezone("UTC").utcoffset(None) == timedelta(0)
    assert resolve_timezone("UTC+8").utcoffset(None) == timedelta(hours=8)
    assert resolve_timezone("GMT-05:30").utcoffset(None) == timedelta(hours=-5, minutes=-30)
    assert resolve_timezone("+8").utcoffset(None) == timedelta(hours=8)


@pytest.mark.parametrize("name", ["", "local", "system", "Mars/Phobos", "UTC+25"])
def test_timezone_rejects_invalid(name):
    with pytest.raises(CronError):
        resolve_timezone(name)


def test_timezone_conversion_to_utc():
    """上海 09:30 = UTC 01:30；2026-09-22 是周二，第一个候选就是当天。"""
    schedule = parse_cron("30 9 * * MON-FRI", "Asia/Shanghai")
    fire = schedule.next_fire(_utc(2026, 9, 22, 0, 0))
    assert fire == _utc(2026, 9, 22, 1, 30)


def test_fixed_offset_timezone_conversion():
    schedule = parse_cron("0 9 * * *", "UTC+8")
    assert schedule.next_fire(_utc(2026, 9, 22, 0, 0)) == _utc(2026, 9, 22, 1, 0)


# ── 语义：步进 / 列表 / AND 交集 ─────────────────────

def test_step_fields_every_15_minutes():
    schedule = parse_cron("*/15 * * * *", "UTC")
    fires = schedule.next_fires(_utc(2026, 9, 22, 0, 0), 3)
    assert [f.minute for f in fires] == [15, 30, 45]
    assert all(f.date() == fires[0].date() for f in fires)


def test_range_with_step_in_hour_field():
    schedule = parse_cron("0 9-17/2 * * *", "UTC")
    assert schedule.hours == frozenset({9, 11, 13, 15, 17})


def test_named_month_list():
    schedule = parse_cron("0 0 1 JAN,JUL *", "UTC")
    assert schedule.months == frozenset({1, 7})


def test_dom_and_dow_intersect_when_both_constrained():
    """13 号 + 周五 → 只在周五的 13 号触发（AND，非 vixie 的 OR）。"""
    schedule = parse_cron("0 9 13 * FRI", "Asia/Shanghai")
    fire = schedule.next_fire(_utc(2026, 9, 1, 0, 0))
    assert fire is not None
    assert fire.astimezone(SH).day == 13
    assert fire.astimezone(SH).weekday() == 4  # 周五（2026-11-13）
    assert fire == _utc(2026, 11, 13, 1, 0)


def test_star_dow_means_every_day_despite_dom():
    """星期为 * 时不受 AND 影响：13 号每到就触发。"""
    schedule = parse_cron("0 9 13 * *", "Asia/Shanghai")
    fire = schedule.next_fire(_utc(2026, 9, 1, 0, 0))
    assert fire == _utc(2026, 9, 13, 1, 0)  # 周日也照常


def test_named_weekday_range_mon_to_fri():
    schedule = parse_cron("0 9 * * MON-FRI", "UTC")
    # 2026-09-26 是周六 → 跳到周一 2026-09-28
    fire = schedule.next_fire(_utc(2026, 9, 26, 0, 0))
    assert fire == _utc(2026, 9, 28, 9, 0)
    assert fire.date().weekday() == 0


def test_star_step_one_is_unconstrained():
    """``*/1`` 与 ``*`` 同义：不参与 AND 交集判定。"""
    every_dow = parse_cron("0 9 13 * */1", "UTC")
    assert every_dow.dow_constrained is False
    star = parse_cron("0 9 13 * *", "UTC")
    assert every_dow.next_fire(_utc(2026, 9, 1)) == star.next_fire(_utc(2026, 9, 1))


def test_next_fire_is_strictly_after():
    schedule = parse_cron("*/15 * * * *", "UTC")
    boundary = _utc(2026, 9, 22, 0, 15)
    assert schedule.next_fire(boundary) == _utc(2026, 9, 22, 0, 30)


def test_unmatchable_expr_returns_none_not_hang():
    """2 月 30 日永不存在：在扫描上界内返回 None。"""
    schedule = parse_cron("0 0 30 2 *", "UTC")
    assert schedule.next_fire(_utc(2026, 1, 1)) is None


def test_naive_after_treated_as_utc():
    schedule = parse_cron("0 9 * * *", "UTC")
    fire = schedule.next_fire(datetime(2026, 9, 22, 0, 0))
    assert fire.tzinfo is not None and fire.hour == 9


# ── DST：跳过不存在的墙上时间 ────────────────────────

def test_nonexistent_wall_time_is_skipped_to_next_day():
    """2026-03-08 02:30 在纽约不存在 → 跳过当天，次日 02:30 正常。"""
    schedule = parse_cron("30 2 * * *", "America/New_York")
    after = datetime(2026, 3, 8, 0, 0, tzinfo=NY)
    fire = schedule.next_fire(after)
    assert fire is not None
    local = fire.astimezone(NY)
    assert (local.day, local.hour, local.minute) == (9, 2, 30)
    assert local.utcoffset() == timedelta(hours=-4)  # EDT


def test_yearly_cron_on_gap_day_skips_whole_year():
    """「3 月 8 日 02:30」在 2026 不存在 → 下一次是 2027-03-08（该年 DST 未开始）。"""
    schedule = parse_cron("30 2 8 3 *", "America/New_York")
    fire = schedule.next_fire(datetime(2026, 1, 1, tzinfo=UTC))
    assert fire is not None
    local = fire.astimezone(NY)
    assert (local.year, local.month, local.day, local.hour, local.minute) == (
        2027, 3, 8, 2, 30,
    )


def test_other_hour_on_gap_day_still_fires():
    """同一天配置了 2 点和 3 点：2 点缺席，3 点照常。"""
    schedule = parse_cron("0 2,3 * * *", "America/New_York")
    fire = schedule.next_fire(datetime(2026, 3, 8, 0, 0, tzinfo=NY))
    local = fire.astimezone(NY)
    assert (local.day, local.hour) == (8, 3)


# ── DST：重复的墙上时间取第一次 ──────────────────────

def test_repeated_wall_time_takes_first_occurrence():
    """2026-11-01 01:30 出现两次 → 取第一次（EDT，UTC-4 → 05:30Z）。"""
    schedule = parse_cron("30 1 * * *", "America/New_York")
    fire = schedule.next_fire(datetime(2026, 11, 1, 0, 0, tzinfo=NY))
    assert fire == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    # 下一次是次日 01:30（EST，UTC-5 → 06:30Z），不会把两次都触发
    nxt = schedule.next_fire(fire)
    assert nxt == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)


def test_preview_returns_requested_count():
    schedule = parse_cron("0 9 * * MON-FRI", "UTC")
    fires = schedule.next_fires(_utc(2026, 9, 25, 10, 0), 4)  # 周五 10 点后
    assert len(fires) == 4
    assert [f.date().isoformat() for f in fires] == [
        "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01",
    ]
