# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Oracle 上界实验：把 QA 证据轮原文直接注入 memories（绕过写侧）。

对应 SMB 讨论中的 Oracle 测试——回答错误时先区分「记忆没写对」和
「检索/使用没做对」：注入金标准记忆后重跑检索作答，得到检索+生成上界。
注入行 id 固定为 ``gold-<dia_id>``（幂等），content 为证据轮逐字原文，
归属=发言者，时间=末次会话（与回放时间线一致）。FTS 索引同步走生产
``memory.retriever._upsert_fts_record``。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from memory_eval.scenarios import evidence_texts


def gold_dia_ids(scenario: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for qa in scenario.get("qa") or []:
        for dia in qa.get("evidence_dia_ids") or []:
            if dia:
                ids.add(str(dia))
    return ids


def inject_gold_memories(env: Any, scenario: dict[str, Any]) -> int:
    """写入金标准记忆行；返回新插入条数（幂等，重复运行返回 0）。

    时间戳按证据所在会话回填（不是统一末次会话）：回放把数月压成小时级，
    若全部同刻，freshness 候选池（LIMIT 20）在同分并列里近乎随机取行，
    检索命中会退化为抽签；按会话时间分布才与生产 recency 语义一致。
    """
    from config.spaces import resolve_space
    from memory.retriever import _upsert_fts_record

    space = resolve_space(int(scenario["group_id"]))
    texts = evidence_texts(scenario)
    wanted = gold_dia_ids(scenario)
    dia_ts: dict[str, str] = {}
    rows: list[tuple[str, str, str, str]] = []
    for session in scenario.get("sessions") or []:
        ts = str(session["ts"])
        for msg in session.get("messages") or []:
            dia = str(msg.get("dia_id") or "")
            if dia in wanted:
                dia_ts[dia] = ts
                if texts.get(dia):
                    rows.append((dia, str(msg["user_id"]), str(msg["text"]), ts))
    inserted = 0
    conn = sqlite3.connect(env.db_path)
    try:
        cur = conn.cursor()
        for dia, user_id, text, ts in rows:
            mem_id = f"gold-{dia}"
            exists = cur.execute(
                "SELECT 1 FROM memories WHERE id = ?", (mem_id,)
            ).fetchone()
            if exists:
                continue
            cur.execute(
                "INSERT INTO memories (id, group_shared_space, user_id, type, content, "
                "status, confidence, importance, visibility, created_at, updated_at, "
                "last_confirmed_at) VALUES (?, ?, ?, 'FACT', ?, 'active', 0.9, 0.6, "
                "'OPEN', ?, ?, ?)",
                (mem_id, space, user_id, text, ts, ts, ts),
            )
            _upsert_fts_record(cur, mem_id, space, user_id, text)
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    return inserted
