# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""SharedPreferences（`astrbot.api.sp`）。

插件用它存会话级 / 插件级 / 全局的小状态。落在 `astrbot_preferences` 表，
与 Stella 的记忆系统隔离。

**注意同步版与异步版的参数顺序不同**，这是上游的历史包袱，必须照抄：
    同步  sp.get(key, default, scope, scope_id)
    异步  sp.get_async(scope, scope_id, key, default)
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from config import DB_PATH

logger = logging.getLogger("astrbot_compat.preferences")

SCOPE_UMO = "umo"
SCOPE_PLUGIN = "plugin"
SCOPE_GLOBAL = "global"


@dataclass
class Preference:
    """一条偏好记录（上游 `range_get` 返回的就是它的列表）。"""

    scope: str
    scope_id: str
    key: str
    value: Any
    updated_at: int = 0


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    from memory.schema import create_astrbot_preferences_table

    create_astrbot_preferences_table(conn)
    return conn


class SharedPreferences:
    """键值存储。三段主键 (scope, scope_id, key)。"""

    def __init__(self) -> None:
        # 进程内缓存，写穿；读未命中再落库查
        self._cache: dict[tuple[str, str, str], Any] = {}
        self.temporary_cache: dict[str, dict] = {}

    # ---------- 内部 ----------

    @staticmethod
    def _norm(scope: str | None, scope_id: str | None, key: str | None) -> tuple[str, str, str]:
        if key is None:
            raise ValueError("key 不能为 None")
        if scope_id is None:
            raise ValueError("scope_id 不能为 None")
        return (scope or "unknown", scope_id or "unknown", key)

    def _read(self, scope: str, scope_id: str, key: str, default: Any) -> Any:
        ck = (scope, scope_id, key)
        if ck in self._cache:
            return deepcopy(self._cache[ck])
        try:
            with contextlib.closing(_connect()) as conn:
                row = conn.execute(
                    "SELECT value FROM astrbot_preferences "
                    "WHERE scope=? AND scope_id=? AND key=?",
                    (scope, scope_id, key),
                ).fetchone()
        except sqlite3.Error as e:
            logger.warning(f"[astrbot_compat] 偏好读取失败 {scope}/{scope_id}/{key}: {e}")
            return default
        if row is None:
            return default
        try:
            value = json.loads(row[0])
        except (ValueError, TypeError):
            return default
        self._cache[ck] = value
        return deepcopy(value)

    def _write(self, scope: str, scope_id: str, key: str, value: Any) -> None:
        self._cache[(scope, scope_id, key)] = deepcopy(value)
        try:
            with contextlib.closing(_connect()) as conn:
                conn.execute(
                    "INSERT INTO astrbot_preferences "
                    "(scope, scope_id, key, value, updated_at) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(scope, scope_id, key) DO UPDATE SET "
                    "value=excluded.value, updated_at=excluded.updated_at",
                    (scope, scope_id, key, json.dumps(value, ensure_ascii=False), int(time.time())),
                )
                conn.commit()
        except (sqlite3.Error, TypeError) as e:
            logger.warning(f"[astrbot_compat] 偏好写入失败 {scope}/{scope_id}/{key}: {e}")

    def _delete(self, scope: str, scope_id: str, key: str) -> None:
        self._cache.pop((scope, scope_id, key), None)
        try:
            with contextlib.closing(_connect()) as conn:
                conn.execute(
                    "DELETE FROM astrbot_preferences WHERE scope=? AND scope_id=? AND key=?",
                    (scope, scope_id, key),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"[astrbot_compat] 偏好删除失败 {scope}/{scope_id}/{key}: {e}")

    def _range(self, scope: str, scope_id: str | None, key: str | None) -> list[Preference]:
        sql = "SELECT scope, scope_id, key, value, updated_at FROM astrbot_preferences WHERE scope=?"
        params: list[Any] = [scope]
        if scope_id is not None:
            sql += " AND scope_id=?"
            params.append(scope_id)
        if key is not None:
            sql += " AND key=?"
            params.append(key)
        try:
            with contextlib.closing(_connect()) as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as e:
            logger.warning(f"[astrbot_compat] 偏好范围查询失败 {scope}: {e}")
            return []
        out: list[Preference] = []
        for s, sid, k, v, ts in rows:
            try:
                value = json.loads(v)
            except (ValueError, TypeError):
                value = None
            out.append(Preference(scope=s, scope_id=sid, key=k, value=value, updated_at=ts or 0))
        return out

    # ---------- 异步 API（当前推荐） ----------

    async def initialize(self) -> None:
        """建表。上游是异步初始化，这里保留形状。"""
        with contextlib.suppress(sqlite3.Error), contextlib.closing(_connect()):
            pass

    async def flush(self) -> None:
        """本实现是同步写穿，无需 flush。"""

    async def close(self) -> None:
        self._cache.clear()

    async def get_async(self, scope: str, scope_id: str, key: str, default: Any = None) -> Any:
        s, sid, k = self._norm(scope, scope_id, key)
        return self._read(s, sid, k, default)

    async def put_async(self, scope: str, scope_id: str, key: str, value: Any) -> None:
        s, sid, k = self._norm(scope, scope_id, key)
        self._write(s, sid, k, value)

    async def remove_async(self, scope: str, scope_id: str, key: str) -> None:
        s, sid, k = self._norm(scope, scope_id, key)
        self._delete(s, sid, k)

    async def clear_async(self, scope: str, scope_id: str) -> None:
        for pref in self._range(scope, scope_id, None):
            self._delete(pref.scope, pref.scope_id, pref.key)

    async def range_get_async(
        self,
        scope: str,
        scope_id: str | None = None,
        key: str | None = None,
    ) -> list[Preference]:
        return self._range(scope, scope_id, key)

    async def session_get(
        self,
        umo: str | None,
        key: str | None = None,
        default: Any = None,
    ) -> Any:
        """umo 或 key 为 None 时返回 Preference 列表（上游语义）。"""
        if umo is None or key is None:
            return self._range(SCOPE_UMO, umo, key)
        return self._read(SCOPE_UMO, umo, key, default)

    async def session_put(self, umo: str, key: str, value: Any) -> None:
        self._write(SCOPE_UMO, umo, key, value)

    async def session_remove(self, umo: str, key: str) -> None:
        self._delete(SCOPE_UMO, umo, key)

    async def global_get(self, key: str | None, default: Any = None) -> Any:
        if key is None:
            return self._range(SCOPE_GLOBAL, SCOPE_GLOBAL, None)
        return self._read(SCOPE_GLOBAL, SCOPE_GLOBAL, key, default)

    async def global_put(self, key: str, value: Any) -> None:
        self._write(SCOPE_GLOBAL, SCOPE_GLOBAL, key, value)

    async def global_remove(self, key: str) -> None:
        self._delete(SCOPE_GLOBAL, SCOPE_GLOBAL, key)

    # ---------- 同步 API（上游已标 deprecated，但插件仍在用） ----------

    def get(
        self,
        key: str,
        default: Any = None,
        scope: str | None = None,
        scope_id: str | None = "",
    ) -> Any:
        s, sid, k = self._norm(scope, scope_id or "unknown", key)
        return self._read(s, sid, k, default)

    def put(
        self,
        key: str,
        value: Any,
        scope: str | None = None,
        scope_id: str | None = None,
    ) -> None:
        s, sid, k = self._norm(scope, scope_id or "unknown", key)
        self._write(s, sid, k, value)

    def remove(
        self,
        key: str,
        scope: str | None = None,
        scope_id: str | None = None,
    ) -> None:
        s, sid, k = self._norm(scope, scope_id or "unknown", key)
        self._delete(s, sid, k)

    def clear(self, scope: str | None = None, scope_id: str | None = None) -> None:
        for pref in self._range(scope or "unknown", scope_id, None):
            self._delete(pref.scope, pref.scope_id, pref.key)

    def range_get(
        self,
        scope: str,
        scope_id: str | None = None,
        key: str | None = None,
    ) -> list[Preference]:
        return self._range(scope, scope_id, key)

    def reset_cache(self) -> None:
        """仅供单测：换 DB_PATH 后必须清缓存，否则读到上个库的值。"""
        self._cache.clear()
        self.temporary_cache.clear()


sp = SharedPreferences()


__all__ = ["SCOPE_GLOBAL", "SCOPE_PLUGIN", "SCOPE_UMO", "Preference", "SharedPreferences", "sp"]
