# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""五字段 Cron 方言（Stella scheduling v1）与 next-fire 计算。

方言（**严格校验、显式拒绝**，全部错误在创建/编辑任务时报给用户，绝不静默
改写语义）：

- 五字段：``分 时 日 月 周``，空白分隔；语法支持 ``*``、单值、范围 ``a-b``、
  步进 ``*/n`` 与 ``a-b/n``、列表 ``a,b,c``（可混合）；
- 月份可用名称（``JAN``–``DEC``，大小写不敏感）；**星期只收名称**
  （``MON``–``SUN``）——数字星期在不同实现里 0/7 既可能是周日也可能是周一，
  属于已知的移植陷阱，v1 一律拒绝（计划 §6.2「reject ambiguous numeric-weekday」）；
- **日 + 星期同时约束时取交集（AND）**：``0 9 13 * FRI`` 只在「13 号且是周五」
  触发。这与 APScheduler 3.x CronTrigger 的行为一致，但与 vixie cron 的
  OR 语义**不同**——文档必须写清（计划 §1「documented dialect」）；
- 时区必填且必须可解析（IANA 名称如 ``Asia/Shanghai``，或固定偏移
  ``UTC+8`` / ``GMT+5:30`` / ``+8``）。不接受空值与 ``local``：调度是持久
  承诺，服务器搬个家不该改语义。

夏令时（DST）规则（计划 §6.2）：

- **不存在的墙上时间**（春季跳变缺口内）：该次触发**跳过**，不推迟到缺口后
  补发——「2:30 提醒我」在 3:30 响是错的。当天的下一次候选时间照常评估
  （``0 2,3 * * *`` 在跳变日 2 点缺席、3 点照常）；
- **重复的墙上时间**（秋季回拨）：取**第一次**出现（fold=0）。

next-fire 采用按字段跳跃的结构化搜索（月 → 日 → 时 → 分），任何字段值集
为空、表达式无法匹配任何时刻（如 ``0 0 30 2 *``）时返回 None 而不是死循环。
覆盖整个值域的字段（``*``、``*/1``）在「日 + 星期 AND」判定中视为未约束。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc

# 结构化搜索的天数上界。月份与日期值集都非空时 5 年内必有匹配；值集组合
# 永远无匹配（如 2 月 30 日）时由这个上界兜底返回 None。
_MAX_DAY_SCAN = 366 * 5

_MONTH_NAMES = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
# 内部编号用 ISO 口径（周一=0 … 周日=6），与 datetime.weekday() 对齐，
# 消除「0 是周日还是周一」这一歧义的最后一处藏身点。
_DOW_NAMES = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
}

_FIELD_SPECS = (
    ("minute", 0, 59, None),
    ("hour", 0, 23, None),
    ("day_of_month", 1, 31, None),
    ("month", 1, 12, _MONTH_NAMES),
    ("day_of_week", 0, 6, _DOW_NAMES),
)

# 固定偏移写法：与 proactive_gate._resolve_zone 同一口径（UTC+8 / GMT-05:30 /
# +8），但这里失败是**拒绝**而不是回退本地时区——理由见模块 docstring。
_OFFSET_FORMAT = re.compile(r"^(?:UTC|GMT)?([+-])(\d{1,2})(?::?(\d{2}))?$", re.IGNORECASE)


class CronError(ValueError):
    """Cron 表达式或时区非法。message 面向用户，可直接回帖。"""


def resolve_timezone(name: str) -> timezone | ZoneInfo:
    """解析任务时区（严格）：IANA 名称或固定偏移；失败抛 :class:`CronError`。"""
    name = (name or "").strip()
    if not name or name.lower() in ("local", "system"):
        raise CronError("时区必须显式指定（IANA 名称如 Asia/Shanghai，或 UTC+8 这类固定偏移）")
    if name.upper() == "UTC":
        return timezone.utc
    offset = _OFFSET_FORMAT.match(name)
    if offset is not None:
        sign = 1 if offset.group(1) == "+" else -1
        hours, minutes = int(offset.group(2)), int(offset.group(3) or 0)
        if minutes < 60 and abs(hours) < 24:
            return timezone(sign * timedelta(hours=hours, minutes=minutes))
        raise CronError(f"固定偏移时区非法: {name!r}（示例：UTC+8、GMT-05:30）")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as e:
        raise CronError(f"时区 {name!r} 无法解析（Windows 部署需安装 tzdata 依赖）: {e}") from e


def _resolve_number(token: str, names: dict[str, int] | None, field_name: str,
                    lo: int, hi: int) -> int:
    """单个值 token → 数字。星期字段拒收数字（歧义），名称只在其字段允许。"""
    token = token.strip()
    if not token:
        raise CronError(f"{field_name} 字段有空片段")
    if names is not None:
        upper = token.upper()
        if upper in names:
            return names[upper]
        if field_name == "day_of_week":
            raise CronError(
                f"星期字段不接受数字 {token!r}（不同实现里 0 可能是周一也可能是周日）；"
                "请使用 MON/TUE/WED/THU/FRI/SAT/SUN"
            )
    if not token.isdigit():
        raise CronError(f"{field_name} 字段值 {token!r} 非法")
    value = int(token)
    if not lo <= value <= hi:
        raise CronError(f"{field_name} 字段值 {value} 超出范围 {lo}-{hi}")
    return value


def _parse_field(spec: tuple[str, int, int, dict[str, int] | None], raw: str) -> frozenset[int]:
    """解析单个字段为值集合（严格；任何含糊直接抛 :class:`CronError`）。"""
    field_name, lo, hi, names = spec
    raw = raw.strip()
    if not raw:
        raise CronError(f"{field_name} 字段为空")
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"{field_name} 字段有空片段: {raw!r}")
        base, slash, step_raw = part.partition("/")
        if slash and not step_raw.strip().isdigit():
            raise CronError(f"{field_name} 字段步进 {step_raw!r} 非法")
        step = int(step_raw) if slash else 1
        if slash and step < 1:
            raise CronError(f"{field_name} 字段步进必须 ≥ 1")
        base = base.strip()
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            start_raw, _, end_raw = base.partition("-")
            start = _resolve_number(start_raw, names, field_name, lo, hi)
            end = _resolve_number(end_raw, names, field_name, lo, hi)
            if start > end:
                raise CronError(f"{field_name} 字段范围 {base!r} 起点大于终点")
        else:
            if slash:
                raise CronError(
                    f"{field_name} 字段步进只能与 * 或范围连用（{part!r}）"
                )
            values.add(_resolve_number(base, names, field_name, lo, hi))
            continue
        values.update(range(start, end + 1, step))
    if not values:
        raise CronError(f"{field_name} 字段没有产生任何合法值: {raw!r}")
    return frozenset(values)


@dataclass(frozen=True, slots=True)
class CronSchedule:
    """一次解析后的 Cron 计划。值集永不为空（解析期保证），因此 next_fire
    要么命中要么在扫描上界内返回 None，不会死循环。"""

    expr: str
    tz_name: str
    tz: timezone | ZoneInfo
    minutes: frozenset[int]
    hours: frozenset[int]
    months: frozenset[int]
    days_of_month: frozenset[int]
    days_of_week: frozenset[int]
    # 值集覆盖全值域的「日 / 星期」视为未约束（不参与 AND 交集判定）
    dom_constrained: bool
    dow_constrained: bool

    def _day_matches(self, day: date) -> bool:
        dom_ok = not self.dom_constrained or day.day in self.days_of_month
        dow_ok = not self.dow_constrained or day.weekday() in self.days_of_week
        return dom_ok and dow_ok

    def next_fire(self, after: datetime) -> datetime | None:
        """``after``（aware；naive 按 UTC 解释）之后的下一次触发（UTC aware）。

        不存在的墙上时间跳过（见模块 docstring 的 DST 规则）；重复的墙上时间
        取第一次出现。无匹配返回 None（如值集组合永不相交）。
        """
        if after.tzinfo is None:
            after = after.replace(tzinfo=UTC)
        after_utc = after.astimezone(UTC)
        local_cursor = after_utc.astimezone(self.tz)
        start_day = local_cursor.date()
        for offset in range(_MAX_DAY_SCAN):
            day = start_day + timedelta(days=offset)
            if day.month not in self.months or not self._day_matches(day):
                continue
            fire = self._next_instant_on_day(day, local_cursor, after_utc)
            if fire is not None:
                return fire
        return None

    def next_fires(self, after: datetime, count: int) -> list[datetime]:
        """之后 ``count`` 次触发（预览用；不足时截断）。"""
        fires: list[datetime] = []
        cursor = after
        for _ in range(max(int(count), 0)):
            fire = self.next_fire(cursor)
            if fire is None:
                break
            fires.append(fire)
            cursor = fire
        return fires

    def _next_instant_on_day(
        self, day: date, local_cursor: datetime, after_utc: datetime
    ) -> datetime | None:
        """在 day 上找第一个可解析且严格晚于 after_utc 的候选时刻。"""
        same_day = day == local_cursor.date()
        start_hour = local_cursor.hour if same_day else -1
        start_minute = local_cursor.minute if same_day else -1
        for hour in sorted(self.hours):
            if hour < start_hour:
                continue
            for minute in sorted(self.minutes):
                if hour == start_hour and minute <= start_minute:
                    continue
                naive = datetime.combine(day, dtime(hour, minute))
                resolved = self._resolve_wall_time(naive)
                if resolved is None:
                    continue  # 不存在的墙上时间（DST 缺口）：跳过该候选
                if resolved <= after_utc:
                    continue
                return resolved
        return None

    def _resolve_wall_time(self, naive: datetime) -> datetime | None:
        """本地墙上时间 → UTC 时刻。

        - 缺口内（round-trip 后墙上时刻变了）→ None；
        - 回拨重复 → fold=0（第一次出现）。
        """
        first = naive.replace(tzinfo=self.tz, fold=0)
        utc_first = first.astimezone(UTC)
        if utc_first.astimezone(self.tz).replace(tzinfo=None) != naive:
            return None
        return utc_first


def parse_cron(expr: str, timezone_name: str) -> CronSchedule:
    """解析并校验五字段 Cron 表达式 + 时区；任何问题抛 :class:`CronError`。"""
    if not expr or not expr.strip():
        raise CronError("Cron 表达式为空")
    fields = expr.split()
    if len(fields) != 5:
        raise CronError(
            f"Cron 表达式必须是 5 个字段（分 时 日 月 周），收到 {len(fields)} 个: {expr!r}"
        )
    parsed = [
        _parse_field(spec, raw) for spec, raw in zip(_FIELD_SPECS, fields, strict=True)
    ]
    minutes, hours, days_of_month, months, days_of_week = parsed
    tz = resolve_timezone(timezone_name)
    return CronSchedule(
        expr=" ".join(fields),
        tz_name=timezone_name.strip(),
        tz=tz,
        minutes=minutes,
        hours=hours,
        months=months,
        days_of_month=days_of_month,
        days_of_week=days_of_week,
        dom_constrained=len(days_of_month) < 31,
        dow_constrained=len(days_of_week) < 7,
    )


__all__ = ["CronError", "CronSchedule", "parse_cron", "resolve_timezone"]
