# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""会话注册表（计划 §6.1）：规范会话键 ↔ 存储/运行时身份的唯一映射。

职责边界：

- **注册**：可信入口（QQ matcher / WebChat ingress）拿到真实事件后调用，
  得到 :class:`~core.conversation.ConversationRef`；重复注册幂等返回既有行。
- **分配**：私聊（以及多 Bot 存储冲突的新 Bot 群）的 ``storage_session_id``
  从专用负整数序列分配——``BEGIN IMMEDIATE`` 短事务内扫描历史消息、
  checkpoint/摘要与已注册会话的占用值，取小于全部已占用负值的起点，
  唯一约束兜底。**禁止** ``-user_id`` 捷径（会与「恰好同号的历史负值/未来
  分配」冲突），也不能从正负号反推 kind。
- **兼容**：群历史按 Bot 绑定沿用原正整数群号与 ``qq:<群号>`` runtime 别名；
  WebChat 保留存储 ``-1`` 与 ``webchat:<user>`` 键，永不被私聊复用。

初始化只在迁移（migrate_v15 / schema._migrate）或首次可信入口发生；
本模块 import 时不写任何库、不触发 resolve_space 的账本分配。
"""

from __future__ import annotations

import sqlite3
import time

from nonebot import logger

from core.conversation import (
    KIND_GROUP,
    KIND_PRIVATE,
    KIND_WEBCHAT,
    ConversationRef,
    conversation_key,
    qq_group_ref,
    qq_private_ref,
    webchat_ref,
)
from memory.schema import create_conversation_registry_table

_TABLE = "conversation_registry"

# 分配负整数存储 ID 前扫描占用的 (表, 列)。全是按真实 QQ 群归属的表
# （migrations.GROUP_SCOPED_TABLES 的口径）+ trace 表；缺失的表跳过。
# WebChat 的 -1 恒占用（硬编码在保留集合里，不依赖扫描）。
_OCCUPANCY_SCANS: tuple[tuple[str, str], ...] = (
    ("group_messages", "group_id"),
    ("messages", "group_id"),
    ("consolidation_state", "group_id"),
    ("short_term_context", "group_id"),
    ("proactive_state", "group_id"),
    ("group_runtime_state", "group_id"),
    ("participation_topics", "group_id"),
    ("participation_log", "group_id"),
    ("memory_traces", "group_id"),
)

# BEGIN IMMEDIATE 的有界重试（多进程并发注册；沿用统一 SQLite 策略量级）
_ALLOC_RETRIES = 3
_ALLOC_RETRY_DELAY = 0.2

# WebChat 的固定保留存储 ID（与 webui.chat_ingress.WEBCHAT_GROUP_ID 同值；
# core/memory 不反向 import webui，这里独立声明并用测试锁定一致）
WEBCHAT_RESERVED_STORAGE_ID = -1


def ensure_registry(conn: sqlite3.Connection) -> None:
    """确保注册表存在（幂等）。迁移与首次注册都会走到这里。"""
    create_conversation_registry_table(conn)


def ref_from_row(row: sqlite3.Row | tuple) -> ConversationRef:
    """注册表行 → ConversationRef（列序见 DDL）。"""
    return ConversationRef(
        platform=row["platform"],
        bot_id=row["bot_id"],
        kind=row["kind"],
        peer_id=row["peer_id"],
        storage_session_id=int(row["storage_session_id"]),
        runtime_key=row["runtime_key"],
        memory_space=row["memory_space"],
    )


def _query_row(conn: sqlite3.Connection, sql: str, params: tuple) -> sqlite3.Row | None:
    """以 Row 形式取单行（保存/恢复调用方的 row_factory，不长期改写连接）。"""
    previous = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.row_factory = previous


def lookup(conn: sqlite3.Connection, conv_key: str) -> ConversationRef | None:
    """按规范会话键查找；未注册返回 None（调用方决定是否注册）。"""
    ensure_registry(conn)
    row = _query_row(conn, f"SELECT * FROM {_TABLE} WHERE conversation_key = ?", (conv_key,))
    return ref_from_row(row) if row else None


def lookup_by_identity(
    conn: sqlite3.Connection, platform: str, bot_id: str, kind: str, peer_id: str
) -> ConversationRef | None:
    return lookup(conn, conversation_key(platform, bot_id, kind, peer_id))


def all_registered(conn: sqlite3.Connection) -> list[ConversationRef]:
    """全部已注册会话（后台整合 drain 遍历用，覆盖私聊）。"""
    ensure_registry(conn)
    previous = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {_TABLE} ORDER BY conversation_key").fetchall()
    finally:
        conn.row_factory = previous
    return [ref_from_row(row) for row in rows]


# ── 群会话 ───────────────────────────────────────────────


def get_or_register_group(conn: sqlite3.Connection, bot_id: str, group_id: int) -> ConversationRef:
    """群会话注册（幂等）。多 Bot 存储冲突时为新 Bot 分配独立存储。"""
    ensure_registry(conn)
    conv_key = conversation_key("qq", str(bot_id), KIND_GROUP, str(group_id))
    existing = lookup(conn, conv_key)
    if existing:
        return existing
    # 存储冲突检测：该群号已被其他 Bot 的会话占用（legacy 绑定）→ 本 Bot
    # 拿独立负存储 ID，不共享历史；冲突行的归属维持原样等待显式绑定。
    row = conn.execute(
        f"SELECT bot_id FROM {_TABLE} WHERE storage_session_id = ?", (int(group_id),)
    ).fetchone()
    conflict_bot = str(row[0]) if row else ""
    if conflict_bot and conflict_bot != str(bot_id):
        logger.warning(
            f"⚠️ [Registry] 群 {group_id} 历史已绑定 Bot {conflict_bot}，"
            f"Bot {bot_id} 将获得独立存储会话（不盲绑旧记录）"
        )
        return _register_with_allocated_storage(
            conn, bot_id="qq", platform_bot=str(bot_id), kind=KIND_GROUP, peer_id=str(group_id)
        )
    ref = qq_group_ref(bot_id, group_id)
    conn.execute(
        f"INSERT OR IGNORE INTO {_TABLE} ("
        "conversation_key, platform, bot_id, kind, peer_id, storage_session_id,"
        " runtime_key, memory_space, legacy_binding) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            ref.conversation_key,
            ref.platform,
            ref.bot_id,
            ref.kind,
            ref.peer_id,
            ref.storage_session_id,
            ref.runtime_key,
            ref.memory_space,
            str(bot_id),  # legacy_binding：该群历史归属本 Bot（单 Bot 默认）
        ),
    )
    conn.commit()
    return lookup(conn, conv_key) or ref


# ── WebChat ──────────────────────────────────────────────


def get_or_register_webchat(conn: sqlite3.Connection, user_id: int) -> ConversationRef:
    """WebChat 注册（幂等）：保留 -1 存储与 webchat:<uid> 键。"""
    ensure_registry(conn)
    conv_key = conversation_key("webchat", "", KIND_WEBCHAT, str(user_id))
    existing = lookup(conn, conv_key)
    if existing:
        return existing
    ref = webchat_ref(user_id=user_id)
    conn.execute(
        f"INSERT OR IGNORE INTO {_TABLE} ("
        "conversation_key, platform, bot_id, kind, peer_id, storage_session_id,"
        " runtime_key, memory_space, legacy_binding) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            ref.conversation_key,
            ref.platform,
            ref.bot_id,
            ref.kind,
            ref.peer_id,
            ref.storage_session_id,
            ref.runtime_key,
            ref.memory_space,
            "",
        ),
    )
    conn.commit()
    return lookup(conn, conv_key) or ref


# ── 私聊（负整数分配） ────────────────────────────────────


def get_or_register_private(conn: sqlite3.Connection, bot_id: str, user_id: int) -> ConversationRef:
    """私聊注册（幂等）：并发安全地分配/复用负整数存储 ID。"""
    ensure_registry(conn)
    conv_key = conversation_key("qq", str(bot_id), KIND_PRIVATE, str(user_id))
    existing = lookup(conn, conv_key)
    if existing:
        return existing
    last_error: Exception | None = None
    for attempt in range(_ALLOC_RETRIES):
        try:
            return _register_private_once(conn, str(bot_id), int(user_id), conv_key)
        except sqlite3.IntegrityError as e:
            # 并发同会话注册：唯一约束兜底后重读既有行
            existing = lookup(conn, conv_key)
            if existing:
                return existing
            last_error = e
        except sqlite3.OperationalError as e:  # database is locked 等
            last_error = e
            time.sleep(_ALLOC_RETRY_DELAY * (attempt + 1))
    raise RuntimeError(f"私聊会话注册失败（{conv_key}）: {last_error!r}") from last_error


def _register_private_once(
    conn: sqlite3.Connection, bot_id: str, user_id: int, conv_key: str
) -> ConversationRef:
    conn.commit()  # 关掉隐式事务再 BEGIN IMMEDIATE
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _query_row(conn, f"SELECT * FROM {_TABLE} WHERE conversation_key = ?", (conv_key,))
        if row:
            conn.execute("COMMIT")
            return ref_from_row(row)
        storage_id = _allocate_negative_storage(conn)
        ref = qq_private_ref(bot_id, user_id, storage_session_id=storage_id)
        conn.execute(
            f"INSERT INTO {_TABLE} ("
            "conversation_key, platform, bot_id, kind, peer_id, storage_session_id,"
            " runtime_key, memory_space, legacy_binding) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                ref.conversation_key,
                ref.platform,
                ref.bot_id,
                ref.kind,
                ref.peer_id,
                ref.storage_session_id,
                ref.runtime_key,
                ref.memory_space,
                "",
            ),
        )
        conn.execute("COMMIT")
        return ref
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _register_with_allocated_storage(
    conn: sqlite3.Connection, *, bot_id: str, platform_bot: str, kind: str, peer_id: str
) -> ConversationRef:
    """群会话的存储冲突路径：为当前 Bot 分配独立负存储 ID。"""
    last_error: Exception | None = None
    for attempt in range(_ALLOC_RETRIES):
        try:
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = _query_row(
                    conn,
                    f"SELECT * FROM {_TABLE} WHERE conversation_key = ?",
                    (conversation_key("qq", platform_bot, kind, peer_id),),
                )
                if row:
                    conn.execute("COMMIT")
                    return ref_from_row(row)
                storage_id = _allocate_negative_storage(conn)

                ref = qq_group_ref(
                    platform_bot,
                    int(peer_id),
                    storage_session_id=storage_id,
                    runtime_key=conversation_key("qq", platform_bot, kind, peer_id),
                )
                conn.execute(
                    f"INSERT INTO {_TABLE} ("
                    "conversation_key, platform, bot_id, kind, peer_id,"
                    " storage_session_id, runtime_key, memory_space, legacy_binding)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        ref.conversation_key,
                        ref.platform,
                        ref.bot_id,
                        ref.kind,
                        ref.peer_id,
                        ref.storage_session_id,
                        ref.runtime_key,
                        ref.memory_space,
                        f"unbound:{storage_id}",
                    ),
                )
                conn.execute("COMMIT")
                return ref
            except Exception:
                conn.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as e:
            last_error = e
            time.sleep(_ALLOC_RETRY_DELAY * (attempt + 1))
    raise RuntimeError(f"群会话独立存储分配失败: {last_error!r}") from last_error


def _allocate_negative_storage(conn: sqlite3.Connection) -> int:
    """在**已持有的 IMMEDIATE 事务内**分配下一个可用负存储 ID。

    占用集合 = WebChat 保留 -1 ∪ 各群表中的历史负值 ∪ 注册表已分配值。
    起点 = min(占用) - 1，严格小于全部已占用负值；唯一约束兜底并发窗口。
    """
    occupied = {WEBCHAT_RESERVED_STORAGE_ID}
    for table, column in _OCCUPANCY_SCANS:
        try:
            row = conn.execute(
                f"SELECT MIN(CAST({column} AS INTEGER)) FROM {table} "
                f"WHERE CAST({column} AS INTEGER) < 0"
            ).fetchone()
        except sqlite3.OperationalError:
            continue  # 表未建（业务模块惰性建表）
        if row and row[0] is not None:
            occupied.add(int(row[0]))
    row = conn.execute(
        f"SELECT MIN(storage_session_id) FROM {_TABLE} WHERE storage_session_id < 0"
    ).fetchone()
    if row and row[0] is not None:
        occupied.add(int(row[0]))
    return min(occupied) - 1
