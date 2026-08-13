# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动发言的持久化状态（proactive_state 表）。

与 memory/proactive.py 的分工：后者只做进程内的活跃度统计与概率计算（可丢失、
可重建）；本模块保存**丢了会造成用户可见错误**的状态——@ 配额计数、上次追问
的内容、连续无回应次数。重启后若这些归零，Bot 会重复追问同一个人同一件事。

所有函数都自建表、自开连接，容忍表不存在（返回保守默认值），不抛异常打断
主动发言链路。
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from nonebot import logger

from config import DB_PATH
from memory.schema import create_proactive_state_table


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    create_proactive_state_table(conn)
    return conn


def _today() -> str:
    return date.today().isoformat()


def get_state(group_id: int, user_id: int) -> dict:
    """读取该群该用户的主动发言状态；无记录时返回全零默认值。

    at_count_today 会按自然日自动归零（读时判断 at_count_date，不需要定时任务）。
    """
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT at_count_today, at_count_date, last_at_at, last_asked_topic, "
            "last_asked_candidate_id, consecutive_no_reply FROM proactive_state "
            "WHERE group_id = ? AND user_id = ?",
            (str(group_id), str(user_id)),
        ).fetchone()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [ProactiveState] 读取失败（按默认值处理）: {e}")
        row = None

    if not row:
        return {
            "at_count_today": 0,
            "last_at_at": None,
            "last_asked_topic": "",
            "last_asked_candidate_id": "",
            "consecutive_no_reply": 0,
        }

    # 跨日则视为 0（不写库，等下次真正 @ 时一并重置）
    count = int(row[0] or 0) if row[1] == _today() else 0
    return {
        "at_count_today": count,
        "last_at_at": row[2],
        "last_asked_topic": row[3] or "",
        "last_asked_candidate_id": row[4] or "",
        "consecutive_no_reply": int(row[5] or 0),
    }


def record_at(group_id: int, user_id: int, topic: str = "", candidate_id: str = "") -> None:
    """记录一次主动 @：配额 +1、刷新时间与追问内容。

    **发出即计数**，不论用户是否回应——否则无回应的追问不占配额，会导致
    对同一个人连续搭话。
    """
    try:
        conn = _connect()
        current = get_state(group_id, user_id)["at_count_today"]
        conn.execute(
            "INSERT INTO proactive_state (group_id, user_id, at_count_today, at_count_date, "
            "last_at_at, last_asked_topic, last_asked_candidate_id, updated_at) "
            "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(group_id, user_id) DO UPDATE SET "
            "at_count_today = excluded.at_count_today, "
            "at_count_date = excluded.at_count_date, "
            "last_at_at = CURRENT_TIMESTAMP, "
            "last_asked_topic = excluded.last_asked_topic, "
            "last_asked_candidate_id = excluded.last_asked_candidate_id, "
            "updated_at = CURRENT_TIMESTAMP",
            (str(group_id), str(user_id), current + 1, _today(), topic, candidate_id),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [ProactiveState] 记录主动 @ 失败: {e}")


def record_reply_result(group_id: int, user_id: int, replied: bool) -> None:
    """记录追问是否获得回应：有回应归零，无回应 +1（用于自动退避）。"""
    try:
        conn = _connect()
        if replied:
            conn.execute(
                "UPDATE proactive_state SET consecutive_no_reply = 0, "
                "updated_at = CURRENT_TIMESTAMP WHERE group_id = ? AND user_id = ?",
                (str(group_id), str(user_id)),
            )
        else:
            conn.execute(
                "UPDATE proactive_state SET consecutive_no_reply = "
                "COALESCE(consecutive_no_reply, 0) + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE group_id = ? AND user_id = ?",
                (str(group_id), str(user_id)),
            )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [ProactiveState] 记录回应结果失败: {e}")


def count_user_messages_24h(group_id: int, user_id: int) -> int:
    """该用户最近 24h 在本群的发言条数（读 group_messages，重启不丢）。

    用于 @ 配额的频率奖励。只统计用户自己的发言，AT_MENTION 与 PASSIVE 都算，
    BOT_SELF 不算（那不是用户说的）。
    """
    since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT COUNT(*) FROM group_messages WHERE group_id = ? AND user_id = ? "
            "AND source_kind != 'BOT_SELF' AND timestamp >= ?",
            (str(group_id), str(user_id), since),
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0
