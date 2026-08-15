# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.timeutil 单元测试：DB 时间戳统一按 UTC 解析。

回归钉死 2026-08-14 CI 暴露的时区混用缺陷：SQLite CURRENT_TIMESTAMP 写入的
是 **UTC**，而旧代码用 datetime.now() / naive .timestamp()（本地时区）与之
比较，在非 UTC 时区下偏移数小时（如 UTC+8 下 elapse 恒多 8 小时）。
"""
from datetime import datetime, timezone

from memory.timeutil import (
    db_timestamp_str,
    humanize_duration,
    parse_db_timestamp,
    seconds_since,
    utc_now,
)


def test_parse_current_timestamp_format_is_utc():
    """CURRENT_TIMESTAMP 的标准格式串必须按 UTC 解释，而非本地时区。"""
    ts = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)
    text = ts.strftime("%Y-%m-%d %H:%M:%S")
    assert parse_db_timestamp(text) == ts.timestamp()


def test_parse_microsecond_and_iso_variants():
    """带微秒 / ISO 格式同样按 UTC 解释。"""
    ts = datetime(2026, 8, 14, 12, 0, 0, 123456, tzinfo=timezone.utc)
    assert parse_db_timestamp(ts.strftime("%Y-%m-%d %H:%M:%S.%f")) == ts.timestamp()
    assert parse_db_timestamp(ts.isoformat()) == ts.timestamp()


def test_parse_dirty_data_returns_none():
    """空值 / 空白 / 无法解析的脏数据 → None（与旧实现猛抛或按 0 处理不同）。"""
    assert parse_db_timestamp(None) is None
    assert parse_db_timestamp("") is None
    assert parse_db_timestamp("   ") is None
    assert parse_db_timestamp("@@不是时间@@") is None


def test_parse_numeric_passthrough():
    """数值型直接透传为 epoch 秒。"""
    assert parse_db_timestamp(1723644000) == 1723644000.0
    assert parse_db_timestamp(1723644000.5) == 1723644000.5


def test_seconds_since_fresh_is_near_zero():
    """刚生成的 DB 时间串 → 距现在接近 0 秒（非负且极小）。"""
    elapsed = seconds_since(db_timestamp_str())
    assert elapsed is not None
    assert 0.0 <= elapsed < 5.0


def test_utc_now_is_aware_utc():
    """utc_now 返回 tz-aware 的 UTC 时间，与 CURRENT_TIMESTAMP 同基准。"""
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(None)


def test_humanize_duration_edges():
    """humanize_duration 的粗粒度量级边界。"""
    assert humanize_duration(30) == "不到一分钟"
    assert humanize_duration(90) == "约 2 分钟"
    assert "小时" in humanize_duration(5400)  # 1.5 小时
    assert humanize_duration(172800) == "约 2 天"
