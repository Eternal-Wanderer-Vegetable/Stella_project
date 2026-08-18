# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""数据库时间戳的统一解析（UTC 基准）与 SQLite 异常分级日志。

前者为本模块主业，后者是被多个 memory 子模块共用的最小公共位置，放这里
避免为一行函数新建模块。

背景：SQLite 的 CURRENT_TIMESTAMP 写入的是 **UTC**，而 Python 侧此前用
datetime.now()（本地时间）与之比较，在非 UTC 时区下产生固定偏移。
后果实例（2026-08-14 由 CI 暴露）：
- PROACTIVE_AT_USER_COOLDOWN 在 UTC+8 下永远被判为「已过」，从未生效；
- count_user_messages_24h 在 UTC+8 下实际只统计 16 小时；
- 记忆年龄多算 8 小时，影响 recency 权重与配额淘汰排序。


所有「拿 Python 时间与 DB 时间戳做比较」的地方都必须走本模块。
SQL 内部的比较（julianday('now') vs julianday(col)）两侧同为 UTC，无需改动。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nonebot import logger

# SQLite CURRENT_TIMESTAMP 的格式，以及常见变体
_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")


def log_sqlite_error(where: str, e: Exception) -> None:
    """SQLite 异常分级日志：表不存在是惰性建表的正常情况，其余（尤其列名不匹配）
    必须可见——静默降级让 2026-08-17 的列名遗漏持续了数小时无人察觉。

    :param where: 调用方标识（如 "Retriever"），用于日志前缀
    :param e: 捕获到的 sqlite3.Error / Exception
    """
    msg = str(e)
    if "no such table" in msg:
        logger.debug(f"[{where}] 表尚不存在，跳过: {msg}")
    else:
        logger.warning(f"⚠️ [{where}] SQL 执行失败: {msg}")


def utc_now() -> datetime:
    """当前 UTC 时间（tz-aware），与 SQLite CURRENT_TIMESTAMP 同基准。"""
    return datetime.now(timezone.utc)


def db_timestamp_str(offset_hours: float = 0.0) -> str:
    """生成与 CURRENT_TIMESTAMP 同格式的 UTC 时间串，可带偏移（用于 since 条件）。"""
    return (utc_now() + timedelta(hours=offset_hours)).strftime("%Y-%m-%d %H:%M:%S")


def parse_db_timestamp(value) -> float | None:
    """把 DB 时间戳解析为 epoch 秒（按 UTC 解释）；无法解析返回 None。


    数值型直接视为 epoch。字符串按 _FORMATS 依次尝试，并显式标记为 UTC——
    这是与旧实现的关键区别：旧代码的 naive .timestamp() 按本地时区解释。
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, TypeError):
            continue
    try:
        dt = datetime.fromisoformat(text)
        return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).timestamp()
    except (ValueError, TypeError):
        return None


def seconds_since(value) -> float | None:
    """距该 DB 时间戳过去了多少秒；无法解析返回 None。"""
    epoch = parse_db_timestamp(value)
    return None if epoch is None else utc_now().timestamp() - epoch


def humanize_duration(seconds: float) -> str:
    """把秒数转成中文近似时长（供 prompt 里的断层标记与新鲜度标注使用）。

    刻意粗粒度：模型需要的是「久不久」的量级感，不是精确值。
    """
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return "不到一分钟"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"约 {round(minutes)} 分钟"
    hours = minutes / 60.0
    if hours < 24:
        return f"约 {hours:.1f} 小时".replace(".0", "")
    return f"约 {round(hours / 24.0)} 天"


def humanize_age(value) -> str | None:
    """DB 时间戳距今多久（人类可读）；无法解析返回 None。"""
    elapsed = seconds_since(value)
    return None if elapsed is None else humanize_duration(elapsed)
