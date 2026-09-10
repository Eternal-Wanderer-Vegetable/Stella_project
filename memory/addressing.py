# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""用户个性化称呼偏好。

称呼是用户明确设置的关系偏好，不属于 ``user_profiles.nickname`` 或普通记忆。
本模块只负责规范化、校验和持久化；自然语言识别与权限判断由上层完成。
"""

from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import DB_PATH
from memory.schema import create_user_address_preferences_table

MAX_ADDRESS_TERM_LENGTH = 32
DEFAULT_SOURCE = "natural_language"


@dataclass(frozen=True)
class AddressPreference:
    """一条共享空间/用户范围内的称呼偏好。"""

    group_shared_space: str
    user_id: str
    address_term: str
    source: str
    updated_by_user_id: str
    updated_at: str | None = None


def normalize_address_term(value: str) -> str:
    """规范并校验称呼文本，拒绝可能污染 SQL/Prompt 结构的输入。"""
    term = (value or "").strip()
    if not term:
        raise ValueError("称呼不能为空")
    if len(term) > MAX_ADDRESS_TERM_LENGTH:
        raise ValueError(f"称呼不能超过 {MAX_ADDRESS_TERM_LENGTH} 个字符")
    for char in term:
        if char in "\r\n" or unicodedata.category(char) == "Cc":
            raise ValueError("称呼不能包含控制字符或换行")
    if any(marker in term for marker in ("```", "【", "】")):
        raise ValueError("称呼包含不支持的格式标记")
    return term


def _scope(group_shared_space: Any, user_id: Any) -> tuple[str, str]:
    space = str(group_shared_space or "").strip()
    uid = str(user_id or "").strip()
    if not space:
        raise ValueError("共享空间不能为空")
    if not uid:
        raise ValueError("用户 ID 不能为空")
    return space, uid


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DB_PATH)
    create_user_address_preferences_table(conn)
    return conn


def _from_row(row: tuple[Any, ...]) -> AddressPreference:
    return AddressPreference(
        group_shared_space=str(row[0]),
        user_id=str(row[1]),
        address_term=str(row[2]),
        source=str(row[3] or DEFAULT_SOURCE),
        updated_by_user_id=str(row[4] or ""),
        updated_at=str(row[5]) if row[5] is not None else None,
    )


def get_preference(
    group_shared_space: Any,
    user_id: Any,
    *,
    db_path: Path | None = None,
) -> AddressPreference | None:
    """读取指定共享空间/用户的称呼偏好。"""
    space, uid = _scope(group_shared_space, user_id)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT group_shared_space, user_id, address_term, source, "
            "updated_by_user_id, updated_at FROM user_address_preferences "
            "WHERE group_shared_space = ? AND user_id = ?",
            (space, uid),
        ).fetchone()
        return _from_row(row) if row else None
    finally:
        conn.close()


def set_preference(
    group_shared_space: Any,
    user_id: Any,
    address_term: str,
    *,
    source: str = DEFAULT_SOURCE,
    updated_by_user_id: Any = "",
    db_path: Path | None = None,
) -> AddressPreference:
    """设置或覆盖称呼偏好，返回写入后的记录。"""
    space, uid = _scope(group_shared_space, user_id)
    term = normalize_address_term(address_term)
    source_value = str(source or DEFAULT_SOURCE).strip()[:64] or DEFAULT_SOURCE
    operator = str(updated_by_user_id or "").strip()
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO user_address_preferences "
            "(group_shared_space, user_id, address_term, source, updated_by_user_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(group_shared_space, user_id) DO UPDATE SET "
            "address_term = excluded.address_term, "
            "source = excluded.source, "
            "updated_by_user_id = excluded.updated_by_user_id, "
            "updated_at = CURRENT_TIMESTAMP",
            (space, uid, term, source_value, operator),
        )
        conn.commit()
        row = conn.execute(
            "SELECT group_shared_space, user_id, address_term, source, "
            "updated_by_user_id, updated_at FROM user_address_preferences "
            "WHERE group_shared_space = ? AND user_id = ?",
            (space, uid),
        ).fetchone()
        if row is None:
            raise RuntimeError("称呼偏好写入后无法读取")
        return _from_row(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def clear_preference(
    group_shared_space: Any,
    user_id: Any,
    *,
    db_path: Path | None = None,
) -> bool:
    """清除称呼偏好，返回是否删除了已有记录。"""
    space, uid = _scope(group_shared_space, user_id)
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN")
        cursor = conn.execute(
            "DELETE FROM user_address_preferences "
            "WHERE group_shared_space = ? AND user_id = ?",
            (space, uid),
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
