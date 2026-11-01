# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""MBENCH-004 P2：记忆包表示实验（T0–T3）——只改证据表示，不改检索。

- T0：生产渲染（``build_v2_named_sections`` 原样）——基线，复用 qamode-paired 运行。
- T1：正文 + 来源时间（记忆确认时间，回填后的会话时间）。
- T2：T1 + 规范化事件时间（解析正文中的相对时间表达，按来源时间换算为绝对日期）。
- T3：T2 + 来源说话者与事实主体（把 user_id 映射为场景说话人名）。

检索 ID 列表与顺序不变：调用方先做一次检索，四表示共用同一 ``result``。
相对时间解析器只做标注（≈前缀），不改写正文。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

# 相对时间表达 → (天数偏移, 单位)。en+zh；顺序=匹配优先级。
_RELATIVE_DAY_OFFSETS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\byesterday\b|昨天", re.IGNORECASE), -1),
    (re.compile(r"\bthe day before yesterday\b|前天", re.IGNORECASE), -2),
    (re.compile(r"\btoday\b|今天", re.IGNORECASE), 0),
    (re.compile(r"\blast week\b|上周", re.IGNORECASE), -7),
    (re.compile(r"\blast month\b|上(?:个)?月", re.IGNORECASE), -30),
    (re.compile(r"\blast year\b|去年", re.IGNORECASE), -365),
]
_RELATIVE_N_UNIT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(\d+)\s*天前|(\d+)\s*days? ago", re.IGNORECASE), "day"),
    (re.compile(r"(\d+)\s*周前|(\d+)\s*weeks? ago", re.IGNORECASE), "week"),
    (re.compile(r"(\d+)\s*个月前|(\d+)\s*months? ago", re.IGNORECASE), "month"),
    (re.compile(r"(\d+)\s*年前|(\d+)\s*years? ago", re.IGNORECASE), "year"),
    (re.compile(r"(\d+)\s*年前|about (\d+) years", re.IGNORECASE), "year"),
]
_FUTURE_MARK = re.compile(r"下(?:个)?月|下周|即将|将|planning|going to|next ", re.IGNORECASE)


def normalize_event_times(content: str, source_date: datetime) -> list[str]:
    """解析正文中的相对时间表达，换算为绝对日期；返回「≈YYYY-MM-DD」标注列表（去重）。"""
    out: list[str] = []
    for pattern, offset in _RELATIVE_DAY_OFFSETS:
        if pattern.search(content):
            d = source_date + timedelta(days=offset)
            out.append(f"≈{d.strftime('%Y-%m-%d')}")
    for pattern, unit in _RELATIVE_N_UNIT:
        for m in pattern.finditer(content):
            n = next((g for g in m.groups() if g), None)
            if not n:
                continue
            days = int(n) * {"day": 1, "week": 7, "month": 30, "year": 365}[unit]
            d = source_date - timedelta(days=days)
            out.append(f"≈{d.strftime('%Y-%m-%d')}")
    return list(dict.fromkeys(out))


def _fmt_date(value: Any) -> str:
    text = str(value or "")
    return text[:10] if len(text) >= 10 else text


def render_memory_line(
    mem: dict[str, Any],
    *,
    level: str,
    source_date: datetime | None,
    user_name: str | None,
) -> str:
    """按表示级别渲染单条记忆。level ∈ T1/T2/T3。"""
    content = str(mem.get("content") or "").replace("\n", " ")
    parts = [f"确认时间: {_fmt_date(mem.get('last_confirmed_at'))}"]
    if level in ("T2", "T3") and source_date is not None:
        event_times = normalize_event_times(content, source_date)
        if event_times:
            parts.append("事件时间: " + "、".join(event_times))
        elif _FUTURE_MARK.search(content):
            parts.append("事件时间: 计划中（未来）")
    if level == "T3":
        parts.append(f"来源: {user_name or mem.get('user_id')}")
        parts.append(f"主体: {user_name or mem.get('user_id')}")
    return f"[记忆 | {' | '.join(parts)}] {content}"


def render_pack(
    result: Any,
    *,
    level: str,
    scenario: dict[str, Any],
    db_path: Any,
) -> str:
    """把检索结果的记忆列表渲染为指定表示级别；返回记忆分节文本。"""
    user_ids = scenario.get("user_ids") or {}
    speakers = scenario.get("speakers") or {}
    id_to_name = {uid: f"{speakers.get(k, k)}" for k, uid in user_ids.items()}

    lines: list[str] = []
    conn_lines: list[tuple[str, datetime | None]] = []
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        for mem in result.conversation_memories:
            mid = mem.get("id")
            row = conn.execute(
                "SELECT last_confirmed_at, user_id FROM memories WHERE id = ?", (mid,)
            ).fetchone()
            if row and row[0]:
                ts = row[0]
                try:
                    src_date = datetime.strptime(str(ts)[:10], "%Y-%m-%d")
                except ValueError:
                    src_date = None
                mem = {**mem, "last_confirmed_at": ts}
                if not mem.get("user_id") and row[1]:
                    mem = {**mem, "user_id": row[1]}
            else:
                src_date = None
            user_name = id_to_name.get(str(mem.get("user_id") or ""))
            lines.append(render_memory_line(
                mem, level=level, source_date=src_date, user_name=user_name))
            conn_lines.append((str(mid), src_date))
    finally:
        conn.close()
    if not lines:
        return ""
    header = {
        "T1": "以下长期记忆按相关度排序，括号内为记忆确认时间：",
        "T2": "以下长期记忆按相关度排序，括号内为确认时间与换算后的事件时间（≈ 为估算）：",
        "T3": ("以下长期记忆按相关度排序，括号内为确认时间、换算事件时间、该记忆的来源说话者"
               "与事实主体（用于区分是谁的经历）："),
    }[level]
    return header + "\n" + "\n".join(lines)
