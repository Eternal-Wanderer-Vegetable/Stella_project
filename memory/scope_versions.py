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


def bump(scope_key: str, conn: sqlite3.Connection | None = None) -> None:
    """推进某 owner 的持久版本（幂等 upsert）。传入 conn 时在调用方事务内。"""
    own = conn is None
    if own:
        try:
            conn = sqlite3.connect(DB_PATH)
        except sqlite3.Error:
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
    except sqlite3.Error:
        pass  # 版本推进失败只损失缓存及时性，不拖垮业务写入
    finally:
        if own:
            with contextlib.suppress(Exception):
                conn.close()


__all__ = ["POLICY_VERSION", "bump", "current_version"]
