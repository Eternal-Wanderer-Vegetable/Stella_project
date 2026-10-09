# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""检索缓存的持久 scope 版本（计划 §6.6）。

进程内的 ``memory_history_version`` 只覆盖本进程写入；共享撤销/删除/回填
必须让**其他进程**的热缓存也失效——个人/空间版本落 SQLite
（``memory_scope_versions``），写入路径在成功事务后 bump，检索路径把它编进
缓存 key。DB 不可用时回退 0（进程内版本仍兜底），绝不抛异常拖垮检索。
"""

from __future__ import annotations

import contextlib
import sqlite3

from config import DB_PATH
from memory.cache_keys import POLICY_VERSION

_TABLE = "memory_scope_versions"


def current_version(scope_keys: list[str] | tuple[str, ...]) -> int:
    """给定 owner 键集合的持久版本（不存在的键按 0 计）。"""
    if not scope_keys:
        return 0
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            placeholders = ",".join("?" * len(scope_keys))
            row = conn.execute(
                f"SELECT COALESCE(SUM(version), 0) FROM {_TABLE} "
                f"WHERE scope_key IN ({placeholders})",
                tuple(scope_keys),
            ).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def current_versions_strict(scope_keys: list[str] | tuple[str, ...]) -> dict[str, int]:
    """严格读取 owner 版本；数据库不可用时抛错，供授权边界 fail-closed 使用。

    与缓存检索使用的 :func:`current_version` 分开，避免为了投递一致性改变
    现有检索降级语义。表缺失、数据库不可读或值损坏都代表版本未知，调用方
    必须停止受保护动作。
    """
    keys = list(dict.fromkeys(str(key) for key in scope_keys if key))
    if not keys:
        return {}
    from config import settings

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(settings.DB_PATH, timeout=5.0)
        placeholders = ",".join("?" * len(keys))
        rows = conn.execute(
            f"SELECT scope_key, version FROM {_TABLE} "
            f"WHERE scope_key IN ({placeholders})",
            tuple(keys),
        ).fetchall()
        versions = {str(key): int(version) for key, version in rows}
        return {key: versions.get(key, 0) for key in keys}
    except (sqlite3.Error, TypeError, ValueError) as e:
        raise RuntimeError("Persistent scope versions are unavailable") from e
    finally:
        if conn is not None:
            with contextlib.suppress(sqlite3.Error):
                conn.close()


def bump(scope_key: str, conn: sqlite3.Connection | None = None, *, strict: bool = False) -> None:
    """推进某 owner 的持久版本（幂等 upsert）。传入 conn 时在调用方事务内。

    R3修复（计划 §6.3）：
    - strict=True 时失败抛异常（授权/撤回路径必须成功，否则缓存会脏读）
    - strict=False 时静默跳过（默认行为，不拖垮业务写入）
    """
    own = conn is None
    if own:
        try:
            conn = sqlite3.connect(DB_PATH)
        except sqlite3.Error as e:
            if strict:
                raise RuntimeError(f"Failed to connect for scope version bump: {e}") from e
            return
    assert conn is not None
    try:
        conn.execute(
            f"INSERT INTO {_TABLE} (scope_key, version, updated_at) "
            f"VALUES (?, 1, CURRENT_TIMESTAMP) "
            f"ON CONFLICT(scope_key) DO UPDATE SET "
            f"version = version + 1, updated_at = CURRENT_TIMESTAMP",
            (scope_key,),
        )
        if own:
            conn.commit()
    except sqlite3.Error as e:
        if strict:
            raise RuntimeError(f"Failed to bump scope version: {e}") from e
        # 非严格模式：版本推进失败只损失缓存及时性，不拖垮业务写入
    finally:
        if own:
            with contextlib.suppress(Exception):
                conn.close()


__all__ = ["POLICY_VERSION", "bump", "current_version", "current_versions_strict"]
