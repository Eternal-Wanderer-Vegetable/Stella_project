# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""个人记忆共享 - 事实级授权与召回。

按计划 §6.3，私聊记忆默认 PRIVATE_ONLY，只有本人明确分享才允许
跨群可见（USER_SHARED）。授权必须绑定具体事实，并通过真实消息验证。
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from nonebot import logger


@dataclass
class SharingGrant:
    """共享授权记录。
    
    Attributes:
        grant_id: 授权 ID（自增主键）
        bot_id: Bot ID
        user_id: 用户 ID（授权发起者，必须是事实主体本人）
        fact_key: 事实键（memory 或 candidate 的 fact_key）
        source_conversation_key: 授权消息所在会话
        source_message_row_id: 授权消息的真实行 ID
        audience: 授权受众（USER_SHARED）
        status: 状态（pending / active / revoked）
        granted_at: 授权时间
        revoked_at: 撤回时间（若适用）
        scope_version: 权限版本（用于缓存失效）
    """
    
    grant_id: int | None = None
    bot_id: int = 0
    user_id: int = 0
    fact_key: str = ""
    source_conversation_key: str = ""
    source_message_row_id: int = 0
    audience: str = "USER_SHARED"
    status: Literal["pending", "active", "revoked"] = "pending"
    granted_at: str = ""
    revoked_at: str | None = None
    scope_version: int = 0


def detect_sharing_intent(
    message_text: str,
    sender_id: int,
    conversation_key: str,
) -> tuple[bool, str]:
    """检测用户是否明确表达分享意图。
    
    肯定分享示例：
    - "以后在群里也记得我们CP的关系"
    - "这个在群里也能用"
    - "可以在群里提醒我"
    
    不是授权：
    - 否定句："别在群里说"
    - 引用他人："他说可以分享"
    - Bot 的回复："好的我记住了"
    - 问句："能在群里用吗？"
    
    Returns:
        (is_sharing_intent, reason)
    """
    text = message_text.strip()
    
    # 否定句
    if any(neg in text for neg in ["别", "不要", "不能", "禁止", "不可以"]):
        return False, "negative"
    
    # 问句
    if "吗" in text or "?" in text or "？" in text:
        return False, "question"
    
    # 肯定分享关键词
    sharing_keywords = ["也记得", "群里也", "在群里", "可以在群"]
    if any(kw in text for kw in sharing_keywords):
        return True, "explicit_sharing"
    
    return False, "no_clear_intent"


def create_sharing_authorization_table(conn: sqlite3.Connection) -> None:
    """创建共享授权表（幂等）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS personal_memory_sharing (
            grant_id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            fact_key TEXT NOT NULL,
            source_conversation_key TEXT NOT NULL,
            source_message_row_id INTEGER NOT NULL,
            audience TEXT NOT NULL DEFAULT 'USER_SHARED',
            status TEXT NOT NULL DEFAULT 'pending',
            granted_at TEXT NOT NULL,
            revoked_at TEXT,
            scope_version INTEGER NOT NULL DEFAULT 0,
            UNIQUE(bot_id, user_id, fact_key)
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sharing_bot_user_status
        ON personal_memory_sharing(bot_id, user_id, status)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sharing_fact_key
        ON personal_memory_sharing(fact_key)
    """)


def grant_sharing_authorization(
    conn: sqlite3.Connection,
    bot_id: int,
    user_id: int,
    fact_key: str,
    source_conversation_key: str,
    source_message_row_id: int,
) -> tuple[bool, str]:
    """授予共享授权（幂等）。
    
    必须在短事务内完成：
    1. 插入或更新授权记录
    2. 复制为 USER_SHARED 副本（若事实已存在）
    3. 记录 memory_evidence
    4. 推进 scope_version
    
    Returns:
        (success, reason)
    """
    cursor = conn.cursor()
    
    # 检查是否已存在
    existing = cursor.execute(
        """
        SELECT grant_id, status FROM personal_memory_sharing
        WHERE bot_id = ? AND user_id = ? AND fact_key = ?
        """,
        (bot_id, user_id, fact_key),
    ).fetchone()
    
    now = datetime.utcnow().isoformat()
    
    if existing:
        grant_id, status = existing
        if status == "active":
            return True, "already_active"
        
        # 重新激活
        cursor.execute(
            """
            UPDATE personal_memory_sharing
            SET status = 'active', granted_at = ?, revoked_at = NULL
            WHERE grant_id = ?
            """,
            (now, grant_id),
        )
    else:
        # 新增授权
        cursor.execute(
            """
            INSERT INTO personal_memory_sharing
            (bot_id, user_id, fact_key, source_conversation_key, 
             source_message_row_id, audience, status, granted_at, scope_version)
            VALUES (?, ?, ?, ?, ?, 'USER_SHARED', 'pending', ?, 0)
            """,
            (bot_id, user_id, fact_key, source_conversation_key, 
             source_message_row_id, now),
        )
    
    # TODO: 复制为 USER_SHARED 副本（需要在整合完成后）
    # TODO: 推进 scope_version
    
    return True, "granted"


def revoke_sharing_authorization(
    conn: sqlite3.Connection,
    bot_id: int,
    user_id: int,
    fact_key: str,
) -> tuple[bool, str]:
    """撤回共享授权。
    
    只撤销该授权生成的共享副本，保留合法的 PRIVATE_ONLY 原件。
    必须在短事务内完成，且版本推进失败时整体回滚。
    
    Returns:
        (success, reason)
    """
    cursor = conn.cursor()
    
    # 检查授权是否存在
    grant = cursor.execute(
        """
        SELECT grant_id, status FROM personal_memory_sharing
        WHERE bot_id = ? AND user_id = ? AND fact_key = ?
        """,
        (bot_id, user_id, fact_key),
    ).fetchone()
    
    if not grant:
        return False, "not_found"
    
    grant_id, status = grant
    if status == "revoked":
        return True, "already_revoked"
    
    now = datetime.utcnow().isoformat()
    
    # 标记为撤回
    cursor.execute(
        """
        UPDATE personal_memory_sharing
        SET status = 'revoked', revoked_at = ?
        WHERE grant_id = ?
        """,
        (now, grant_id),
    )
    
    # TODO: 失活对应的 USER_SHARED 副本
    # TODO: 推进 scope_version（必须验证成功）
    
    return True, "revoked"


def get_user_shared_facts(
    conn: sqlite3.Connection,
    bot_id: int,
    user_id: int,
) -> list[str]:
    """获取用户已授权共享的事实键列表。"""
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT fact_key FROM personal_memory_sharing
        WHERE bot_id = ? AND user_id = ? AND status = 'active'
        ORDER BY granted_at DESC
        """,
        (bot_id, user_id),
    ).fetchall()
    
    return [row[0] for row in rows]
