# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动发言的持久化状态（proactive_state 表）。

与 memory/proactive.py 的分工：后者只做进程内的活跃度统计与概率计算（可丢失、
可重建）；本模块保存**丢了会造成用户可见错误**的状态——@ 配额计数、上次追问
的内容、连续无回应次数。重启后若这些归零，Bot 会重复追问同一个人同一件事。

所有函数都自建表、自开连接，容忍表不存在（返回保守默认值），不抛异常打断
主动发言链路。

本模块还保存群级运行时状态（group_runtime_state）：管理员的静音开关与
睡眠/苏醒播报的每日去重锚点。二者同样属于「丢了会造成用户可见错误」的状态——
静音开关丢失会让 Bot 在管理员关闭后重启时又开始主动说话；播报锚点丢失会导致
睡眠期内重启时重复播报「我去睡了」。
"""
from __future__ import annotations

import sqlite3
from datetime import date

from nonebot import logger

from config import DB_PATH
from memory.schema import create_group_runtime_state_table, create_proactive_state_table


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


def reset_no_reply(group_id: int, user_id: int) -> None:
    """把该用户的连续无回应计数归零。

    两个调用方：确认获得回应时（record_reply_result），以及该用户任意一次
    「对 Bot 说话」时（AT_MENTION 入库路径）。

    后者是退避的自愈阀门。回应判定改为只认 @ / 回复 Bot 之后，一个习惯用纯文本
    接话的人会连续攒够 PROACTIVE_MAX_NO_REPLY 而被永久排除——而 consecutive_no_reply
    此前没有任何按时间的自然衰减，一旦攒满就再无归零机会。既然「主动 @ 是主要的
    记忆来源」，把人永久踢出验证池的代价远高于多问一次。
    """
    try:
        conn = _connect()
        conn.execute(
            "UPDATE proactive_state SET consecutive_no_reply = 0, "
            "updated_at = CURRENT_TIMESTAMP WHERE group_id = ? AND user_id = ?",
            (str(group_id), str(user_id)),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [ProactiveState] 归零无回应计数失败: {e}")


def record_reply_result(group_id: int, user_id: int, replied: bool) -> None:
    """记录追问是否获得回应：有回应归零，无回应 +1（用于自动退避）。"""
    if replied:
        reset_no_reply(group_id, user_id)
        return
    try:
        conn = _connect()
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
    from memory.timeutil import db_timestamp_str

    since = db_timestamp_str(offset_hours=-24)
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


# ── 群级运行时状态（运行时静音开关 / 播报去重） ──────────────

def _connect_runtime() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    create_group_runtime_state_table(conn)
    return conn


def get_runtime_state(group_id: int) -> dict:
    """读取群级运行时状态；无记录时返回默认值（未静音、无播报记录）。"""
    try:
        conn = _connect_runtime()
        row = conn.execute(
            "SELECT proactive_muted, muted_by, muted_at, last_sleep_announce_date, "
            "last_wakeup_announce_date FROM group_runtime_state WHERE group_id = ?",
            (str(group_id),),
        ).fetchone()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [ProactiveState] 读取群运行时状态失败（按默认值处理）: {e}")
        row = None

    if not row:
        return {
            "proactive_muted": False,
            "muted_by": "",
            "muted_at": None,
            "last_sleep_announce_date": "",
            "last_wakeup_announce_date": "",
        }
    return {
        "proactive_muted": bool(row[0]),
        "muted_by": row[1] or "",
        "muted_at": row[2],
        "last_sleep_announce_date": row[3] or "",
        "last_wakeup_announce_date": row[4] or "",
    }


def set_proactive_muted(group_id: int, muted: bool, operator_id: int = 0) -> None:
    """设置群级主动发言静音开关（持久化，重启后仍生效）。

    静音只影响主动发言（话题插话 + 主动 @）；被 @ 时仍照常回复。
    """
    try:
        conn = _connect_runtime()
        conn.execute(
            "INSERT INTO group_runtime_state (group_id, proactive_muted, muted_by, muted_at, updated_at) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT(group_id) DO UPDATE SET "
            "proactive_muted = excluded.proactive_muted, "
            "muted_by = excluded.muted_by, "
            "muted_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP",
            (str(group_id), 1 if muted else 0, str(operator_id) if operator_id else ""),
        )
        conn.commit()
        conn.close()
        logger.info(
            f"{'🔇' if muted else '🔊'} [ProactiveState] 群 {group_id} 主动发言"
            f"{'已静音' if muted else '已恢复'}（操作者 {operator_id or '未知'}）"
        )
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [ProactiveState] 设置静音开关失败: {e}")


def mark_announced(group_id: int, kind: str, date_str: str) -> None:
    """记录某类播报（``sleep`` / ``wakeup``）已在 date_str 当日完成。

    kind 是代码内枚举值，不是外部输入，因此列名可安全参与 SQL 拼接。
    """
    column = "last_sleep_announce_date" if kind == "sleep" else "last_wakeup_announce_date"
    try:
        conn = _connect_runtime()
        conn.execute(
            f"INSERT INTO group_runtime_state (group_id, {column}, updated_at) "
            f"VALUES (?, ?, CURRENT_TIMESTAMP) "
            f"ON CONFLICT(group_id) DO UPDATE SET "
            f"{column} = excluded.{column}, updated_at = CURRENT_TIMESTAMP",
            (str(group_id), date_str),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [ProactiveState] 记录播报失败: {e}")
