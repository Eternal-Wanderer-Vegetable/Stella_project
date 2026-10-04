# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""社交学习旁表的存储层（计划 §6.2：social_deliveries / social_events 优先）。

只有存储，没有学习/结算逻辑。所有写操作都是短事务、失败不抛出（旁路纪律：
社交事实缺一条只损失一条证据，绝不能拖垮回复链路）。全部时间 UTC。

幂等语义：
- :func:`record_delivery` 按 (turn_id, part_index) 幂等——重放/补偿不会产生
  第二行；
- :func:`record_event` 按 event_id 幂等，平台消息 ID 的复合唯一索引兜底
  （两个 matcher 处理同一消息时用稳定 event_id 关联）。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from core.social.contracts import (
    DELIVERY_ACKNOWLEDGED,
    ConversationScope,
    DeliveryReceipt,
    MessageEvidence,
    utc_now_iso,
)
from memory.timeutil import log_sqlite_error

_TABLES_READY = False


def _connect() -> sqlite3.Connection:
    # 运行时属性读取（而非 from config import DB_PATH 的导入期绑定）：
    # 测试用 monkeypatch.setattr(config.settings, "DB_PATH", ...) 即可隔离
    from config import settings

    return sqlite3.connect(settings.DB_PATH, timeout=10.0)


def ensure_tables() -> None:
    """幂等建表（组件迁移的兼容入口；正式升级走 memory/social_schema.py）。"""
    global _TABLES_READY
    if _TABLES_READY:
        return
    try:
        from memory.social_schema import ensure_social_schema

        ensure_social_schema()
        _TABLES_READY = True
    except Exception as e:
        log_sqlite_error("social_store.ensure_tables", e)


# ============================================================
# social_deliveries（投递回执）
# ============================================================


def record_delivery(receipt: DeliveryReceipt) -> bool:
    """落一条投递回执；(turn_id, part_index) 冲突时**不覆盖既有事实**。

    ACK 后落库失败（库暂时不可写）由调用方记日志：发送成功但事实缺档，
    属于可接受的 unknown 降级，绝不能反向重发。

    修复计划 §6.3：scope 非空沿用既有群存档（learning_eligible 按 QQ 群
    scope 判定）；scope=None 但带规范会话身份的中立回执（私聊）落
    group_id=''、learning_eligible=0 行——可查询、不进群学习。
    """
    scope = receipt.scope
    try:
        ensure_tables()
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO social_deliveries (delivery_id, turn_id, part_index, "
                "trace_id, epoch, platform, bot_id, group_id, status, platform_message_id, "
                "acknowledged_at_utc, text, text_hash, created_at_utc, updated_at_utc, "
                "conversation_key, conversation_kind, peer_id, storage_session_id, "
                "learning_eligible) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex, receipt.turn_id, int(receipt.part_index),
                    receipt.trace_id, int(receipt.epoch),
                    scope.platform if scope else "", scope.bot_id if scope else "",
                    scope.group_id if scope else "",
                    receipt.status, receipt.platform_message_id,
                    receipt.acknowledged_at_utc or None,
                    receipt.text, receipt.text_hash,
                    receipt.created_at_utc, utc_now_iso(),
                    receipt.conversation_key or "",
                    receipt.conversation_kind or "",
                    receipt.peer_id or "",
                    None if receipt.storage_session_id is None
                    else int(receipt.storage_session_id),
                    1 if receipt.learning_eligible else 0,
                ),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("social_store.record_delivery", e)
        return False


def deliveries_for_turn(
    turn_id: str,
    *,
    platform: str | None = None,
    group_id: str | None = None,
    learning_eligible: bool | None = None,
) -> list[dict[str, Any]]:
    """一次逻辑回复的全部片段回执（按片段序）。

    修复计划 §6.3：群学习/引用归因消费方必须显式传
    ``learning_eligible=True``（可再带 platform/group_id 核对）——中立
    私聊行永远不会出现在该口径里。
    """
    try:
        ensure_tables()
        conn = _connect()
        try:
            sql = (
                "SELECT part_index, status, platform_message_id, acknowledged_at_utc, "
                "text, text_hash FROM social_deliveries WHERE turn_id = ?"
            )
            params: list[Any] = [turn_id]
            if platform is not None:
                sql += " AND platform = ?"
                params.append(platform)
            if group_id is not None:
                sql += " AND group_id = ?"
                params.append(group_id)
            if learning_eligible is not None:
                sql += " AND learning_eligible = ?"
                params.append(1 if learning_eligible else 0)
            sql += " ORDER BY part_index"
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "part_index": r[0], "status": r[1], "platform_message_id": r[2],
                    "acknowledged_at_utc": r[3], "text": r[4], "text_hash": r[5],
                }
                for r in rows
            ]
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("social_store.deliveries_for_turn", e)
        return []


def find_delivery_by_platform_id(
    platform_message_id: str, *, scope: ConversationScope | None = None
) -> dict[str, Any] | None:
    """按平台消息 ID 反查回执（引用归因的锚点）。

    修复计划 §6.3 边界收紧：
    - 不带 scope（旧仅 ID 调用）：只查学习可用群行（learning_eligible=1），
      且歧义（同 ID 命中多行）返回 None——不猜第一行；
    - 带 scope：只在匹配该群身份的行内查找。
    中立私聊行永远不会被归因反查命中。
    """
    if not platform_message_id:
        return None
    try:
        ensure_tables()
        conn = _connect()
        try:
            sql = (
                "SELECT turn_id, part_index, platform, bot_id, group_id, status, text "
                "FROM social_deliveries WHERE platform_message_id = ?"
            )
            params: list[Any] = [str(platform_message_id)]
            if scope is not None:
                sql += " AND platform = ? AND bot_id = ? AND group_id = ? AND learning_eligible = 1"
                params.extend([scope.platform, scope.bot_id, scope.group_id])
            else:
                sql += " AND learning_eligible = 1"
            rows = conn.execute(sql + " LIMIT 2", params).fetchall()
            if not rows or len(rows) > 1:
                return None
            row = rows[0]
            return {
                "turn_id": row[0], "part_index": row[1], "platform": row[2],
                "bot_id": row[3], "group_id": row[4], "status": row[5], "text": row[6],
            }
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("social_store.find_delivery_by_platform_id", e)
        return None


# ============================================================
# social_events（标准化消息证据）
# ============================================================


def record_event(evidence: MessageEvidence) -> str | None:
    """落一条标准化消息证据；event_id 冲突静默跳过（幂等）。返回 event_id。"""
    try:
        ensure_tables()
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO social_events (event_id, platform, bot_id, group_id, "
                "platform_message_id, user_id, source_kind, reply_to_id, mentioned_user_ids, "
                "text_excerpt, content_hash, received_at_utc, event_at_utc, trace_id, turn_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    evidence.event_id, *evidence.scope.row(), evidence.platform_message_id,
                    evidence.user_id, evidence.source_kind, evidence.reply_to_id,
                    json.dumps(list(evidence.mentioned_user_ids), ensure_ascii=False),
                    evidence.text_excerpt, evidence.content_hash,
                    evidence.received_at_utc, evidence.event_at_utc,
                    evidence.trace_id, evidence.turn_id,
                ),
            )
            conn.commit()
            return evidence.event_id
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("social_store.record_event", e)
        return None


def events_since(
    scope: ConversationScope,
    since_utc: str,
    *,
    until_utc: str | None = None,
    exclude_user_ids: tuple[str, ...] = (),
    exclude_source_kinds: tuple[str, ...] = ("BOT_SELF",),
    limit: int = 50,
) -> list[dict[str, Any]]:
    """取作用域内时间窗（按 received_at_utc 字典序 = 时间序）的人类消息证据。

    排序以服务接收时间为准（平台时间只用于展示）；事件乱序到达时仍按
    接收序稳定重现（计划 §8.1 时间与窗口行）。
    """
    try:
        ensure_tables()
        conn = _connect()
        try:
            sql = (
                "SELECT event_id, platform_message_id, user_id, source_kind, reply_to_id, "
                "mentioned_user_ids, text_excerpt, received_at_utc, event_at_utc "
                "FROM social_events WHERE platform = ? AND bot_id = ? AND group_id = ? "
                "AND received_at_utc >= ?"
            )
            params: list[Any] = [*scope.row(), since_utc]
            if until_utc:
                sql += " AND received_at_utc <= ?"
                params.append(until_utc)
            for uid in exclude_user_ids:
                sql += " AND user_id != ?"
                params.append(uid)
            for kind in exclude_source_kinds:
                sql += " AND source_kind != ?"
                params.append(kind)
            sql += " ORDER BY received_at_utc ASC, rowid ASC LIMIT ?"
            params.append(max(0, int(limit)))
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "event_id": r[0], "platform_message_id": r[1], "user_id": r[2],
                    "source_kind": r[3], "reply_to_id": r[4],
                    "mentioned_user_ids": json.loads(r[5] or "[]"),
                    "text_excerpt": r[6], "received_at_utc": r[7], "event_at_utc": r[8],
                }
                for r in rows
            ]
        finally:
            conn.close()
    except (sqlite3.Error, ValueError) as e:
        log_sqlite_error("social_store.events_since", e)
        return []


def acked_bot_message_ids(scope: ConversationScope, turn_id: str) -> list[str]:
    """某轮已确认送达片段的平台消息 ID（引用归因的强证据集合）。"""
    return [
        str(d["platform_message_id"])
        for d in deliveries_for_turn(turn_id)
        if d["status"] == DELIVERY_ACKNOWLEDGED and d["platform_message_id"]
    ]

def find_event_id(
    scope: "ConversationScope",
    platform_message_id: str | None,
    *,
    fallback: "MessageEvidence | None" = None,
) -> str:
    """按平台消息 ID 反查证据行 event_id；没有则用 fallback（或新建）落一行。

    两个 matcher 处理同一消息时共享同一证据行（复合唯一索引兜底）。
    """
    try:
        ensure_tables()
        conn = _connect()
        try:
            if platform_message_id:
                row = conn.execute(
                    "SELECT event_id FROM social_events WHERE platform=? AND bot_id=? "
                    "AND group_id=? AND platform_message_id=? LIMIT 1",
                    (*scope.row(), str(platform_message_id)),
                ).fetchone()
                if row:
                    return row[0]
            if fallback is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO social_events (event_id, platform, bot_id, "
                    "group_id, platform_message_id, user_id, source_kind, reply_to_id, "
                    "mentioned_user_ids, text_excerpt, content_hash, received_at_utc, "
                    "event_at_utc, trace_id, turn_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        fallback.event_id, *fallback.scope.row(), fallback.platform_message_id,
                        fallback.user_id, fallback.source_kind, fallback.reply_to_id,
                        json.dumps(list(fallback.mentioned_user_ids), ensure_ascii=False),
                        fallback.text_excerpt, fallback.content_hash,
                        fallback.received_at_utc, fallback.event_at_utc,
                        fallback.trace_id, fallback.turn_id,
                    ),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT event_id FROM social_events WHERE platform=? AND bot_id=? "
                    "AND group_id=? AND platform_message_id=? LIMIT 1",
                    (*scope.row(), str(platform_message_id or "")),
                ).fetchone() if platform_message_id else None
                return row[0] if row else fallback.event_id
            return ""
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("social_store.find_event_id", e)
        return ""
