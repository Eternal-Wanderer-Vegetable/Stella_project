# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""群组与绑定管理（方案 §6.11）。

群的白名单（``ALLOWED_GROUPS``，.env）与空间绑定（spaces/*.toml）是两个
持久层：绑定写 toml + reload，白名单变更走 envfile（写 .env，
restart_required）。静音是运行期状态（``group_runtime_state`` 表），
即时生效不重启——它本来就是管理员「出了问题先闭嘴」的开关。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import config.settings as settings
from webui.responses import ApiError
from webui.services import envfile


def _memory_db() -> Path:
    return Path(settings.DB_PATH)


def list_groups() -> list[dict]:
    """白名单群 + 空间绑定 + 静音态。"""
    from config import ALLOWED_GROUPS
    from config import spaces as spaces_mod

    mute: dict[str, dict] = {}
    counts: dict[str, int] = {}
    conn = (
        sqlite3.connect(f"file:{_memory_db().as_posix()}?mode=ro", uri=True)
        if _memory_db().exists()
        else None
    )
    if conn is not None:
        try:
            for row in conn.execute(
                "SELECT group_id, proactive_muted, muted_by, muted_at FROM group_runtime_state"
            ):
                mute[str(row[0])] = {
                    "proactive_muted": bool(row[1]), "muted_by": row[2], "muted_at": row[3],
                }
        except sqlite3.Error:
            pass
        try:
            for row in conn.execute(
                "SELECT group_id, COUNT(*) FROM group_messages GROUP BY group_id"
            ):
                counts[str(row[0])] = int(row[1])
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    items = []
    for gid in ALLOWED_GROUPS:
        key = str(gid)
        items.append(
            {
                "group_id": gid,
                "space": spaces_mod.resolve_space(gid),
                "messages": counts.get(key, 0),
                **mute.get(key, {"proactive_muted": False, "muted_by": None, "muted_at": None}),
            }
        )
    return items


def set_bindings(payload: list[dict]) -> dict:
    """{group_id, space} 列表：更新 ALLOWED_GROUPS 与空间绑定。

    绑定变化即时生效（spaces.reload）；白名单变化写 .env 需重启。
    """
    from config import ALLOWED_GROUPS
    from webui.services import spaces as spaces_service

    allowed = {int(g) for g in ALLOWED_GROUPS}
    seen: dict[int, str] = {}
    for item in payload:
        gid = int(item["group_id"])
        if gid in seen and seen[gid] != item["space"]:
            raise ApiError(f"群 {gid} 被绑到多个空间")
        seen[gid] = item["space"]
    for _gid, space in seen.items():
        spaces_service._validate_name(space)
    # 逐空间落地绑定
    by_space: dict[str, list[int]] = {}
    for gid, space in seen.items():
        by_space.setdefault(space, []).append(gid)
    for space, gids in by_space.items():
        spaces_service.put_bindings(space, gids)
    # 未出现在 payload 里的旧绑定群从空间里摘除
    for space_item in spaces_service.list_spaces():
        if space_item["name"] in by_space:
            continue
        if space_item["qq_groups"]:
            keep = [g for g in space_item["qq_groups"] if g not in seen]
            if keep != space_item["qq_groups"]:
                spaces_service.put_bindings(space_item["name"], keep)
    # 白名单 = 全部被绑定群
    whitelist = sorted(seen.keys())
    changed = whitelist != sorted(allowed)
    if changed:
        envfile.write_values({"ALLOWED_GROUPS": ",".join(str(g) for g in whitelist)})
    return {
        "groups": whitelist,
        "restart_required": changed,
    }


def set_mute(group_id: int, *, muted: bool, actor: str) -> dict:
    """运行期静音（写 group_runtime_state，即时生效）。"""
    _memory_db().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_memory_db())
    try:
        from memory.schema import create_group_runtime_state_table

        create_group_runtime_state_table(conn)
        conn.execute(
            """
            INSERT INTO group_runtime_state (group_id, proactive_muted, muted_by, muted_at, updated_at)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(group_id) DO UPDATE SET
                proactive_muted = excluded.proactive_muted,
                muted_by = excluded.muted_by,
                muted_at = excluded.muted_at,
                updated_at = excluded.updated_at
            """,
            (str(group_id), int(muted), actor if muted else None),
        )
        conn.commit()
    finally:
        conn.close()
    return {"group_id": group_id, "proactive_muted": muted, "ts": time.time()}
