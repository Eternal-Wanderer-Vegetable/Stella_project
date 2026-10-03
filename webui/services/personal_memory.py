# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""个人记忆管理服务（计划 §6.9）：owner/audience 维度的审计、删除与导出。

权限模型：路由层 require_auth（单管理员）之后，这里仍按服务端过滤——
只展示/操作 ``owner_type='PERSON'`` 的行；群页面（按空间）不会混入个人事实。
删除是**硬删除**（个人事实属本人数据，管理员审计后可彻底移除），并推进
对应 owner 的持久缓存版本（§6.6：热缓存立刻失效）。默认 metadata 不含
私聊正文之外的私密证据；content 只在显式请求 include_content 时返回。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from config import DB_PATH
from memory import scope_versions


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def list_personal_memories(
    *,
    subject_key: str = "",
    audience: str = "",
    source_conversation_key: str = "",
    include_content: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """按 owner/audience/source 精确筛选 PERSON 记忆（服务端过滤）。"""
    if not DB_PATH.exists():
        return {"items": [], "total": 0}
    where = ["owner_type = 'PERSON'"]
    params: list[Any] = []
    if subject_key:
        where.append("subject_key = ?")
        params.append(subject_key)
    if audience:
        where.append("audience = ?")
        params.append(audience)
    if source_conversation_key:
        where.append("source_conversation_key = ?")
        params.append(source_conversation_key)
    clause = " AND ".join(where)
    conn = _connect()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM memories WHERE {clause}", params
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT id, group_shared_space, owner_key, subject_key, audience,"
            " source_conversation_key, type, content, importance, confidence,"
            " status, fact_key, policy_version, created_at, updated_at"
            f" FROM memories WHERE {clause}"
            " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)),
        ).fetchall()
    finally:
        conn.close()
    items = []
    for r in rows:
        item = dict(r)
        if not include_content:
            item["content"] = ""
        items.append(item)
    return {"items": items, "total": int(total)}


def delete_personal_memory(memory_id: str) -> bool:
    """删除一条 PERSON 记忆（硬删除）并推进 owner 缓存版本。

    只允许删 PERSON 行——群记忆的治理走既有空间页面，本接口永不触碰。
    返回是否删除了行。
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT owner_key FROM memories WHERE id = ? AND owner_type = 'PERSON'",
            (memory_id,),
        ).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        scope_versions.bump(str(row["owner_key"]), conn=conn)
        conn.commit()
        return True
    finally:
        conn.close()


def export_personal_memories(subject_key: str = "") -> dict[str, Any]:
    """导出个人事实（JSON 安全结构；审计/数据可携带权用）。"""
    data = list_personal_memories(
        subject_key=subject_key, include_content=True, limit=100000
    )
    return {
        "schema_version": 1,
        "exported_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "count": data["total"],
        "items": data["items"],
    }
