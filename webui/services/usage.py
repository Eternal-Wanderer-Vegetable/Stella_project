# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""用量统计取数（方案 §6.9 统计页 / §7.6 usage 域）。

today 走 ``usage_store.usage_snapshot()``（v1 状态接口同源，脱敏契约由它
保证）；daily 基于 ``usage_store.query_daily()`` 在服务端做时间序列与
排行聚合，前端图表直接吃现成形状。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from core.llm import usage_store

# 图表聚合口径：总量之外按这三个维度排行（方案 §6.9）
_BREAKDOWNS = ("role", "slot", "model")


def _fallback_states() -> dict:
    try:
        from core.llm import fallback_states

        return fallback_states()
    except Exception:
        return {}


def today() -> dict:
    """今日快照 + 预算 + 正在降级的角色（welcome 状态卡与统计页共用）。"""
    payload = usage_store.usage_snapshot()
    payload["fallback_states"] = _fallback_states()
    return payload


def _empty_daily(days: int) -> dict:
    return {"days": days, "accounting": usage_store.accounting_enabled(),
            "series": [], "by_role": [], "by_slot": [], "by_model": []}


def daily(days: int) -> dict:
    """近 N 天序列与排行。series 按日期补零，图表不用自己插值。"""
    rows = usage_store.query_daily(days)
    if not rows:
        return _empty_daily(days)

    per_day: dict[str, dict] = {}
    by_breakdown: dict[str, defaultdict] = {k: defaultdict(dict) for k in _BREAKDOWNS}
    for row in rows:
        day = per_day.setdefault(
            row["date"],
            {"date": row["date"], "calls": 0, "failures": 0,
             "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0},
        )
        day["calls"] += row["calls"]
        day["failures"] += row["failures"]
        day["prompt_tokens"] += row["prompt_tokens"]
        day["completion_tokens"] += row["completion_tokens"]
        day["cached_tokens"] += row["cached_tokens"]
        for key in _BREAKDOWNS:
            bucket = by_breakdown[key][row[key]]
            bucket.setdefault("name", row[key])
            for metric in ("calls", "prompt_tokens", "completion_tokens", "cached_tokens"):
                bucket[metric] = bucket.get(metric, 0) + row[metric]

    # 日期补零：完整铺满 N 天窗口（数据更早则从最早有账处起），图表不用自己插值
    all_dates = sorted(per_day)
    start = date.fromisoformat(all_dates[0])
    today = date.today()
    earliest = today - timedelta(days=max(0, int(days) - 1))
    series: list[dict] = []
    cursor = min(start, earliest)
    while cursor <= today:
        key = cursor.isoformat()
        series.append(
            per_day.get(key)
            or {"date": key, "calls": 0, "failures": 0, "prompt_tokens": 0,
                "completion_tokens": 0, "cached_tokens": 0}
        )
        cursor += timedelta(days=1)

    def _ranking(buckets: dict) -> list[dict]:
        items = sorted(
            buckets.values(), key=lambda b: b["prompt_tokens"] + b["completion_tokens"],
            reverse=True,
        )
        for item in items:
            item["total_tokens"] = item["prompt_tokens"] + item["completion_tokens"]
        return items

    return {
        "days": days,
        "accounting": usage_store.accounting_enabled(),
        "series": series,
        "by_role": _ranking(by_breakdown["role"]),
        "by_slot": _ranking(by_breakdown["slot"]),
        "by_model": _ranking(by_breakdown["model"]),
    }
