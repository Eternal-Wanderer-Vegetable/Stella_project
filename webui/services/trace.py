# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""决策轨迹取数（方案 §6.9 追踪页，评审定案硬性交付）。

两个结构化来源（都在记忆库，只读）：
- ``memory_traces``（memory/trace.py）：每次回复的记忆决策链——候选、
  淘汰、最终采纳（含分数）、行为约束、prompt 快照与输出截断；
- ``participation_log``（v13）：每次主动插话评分的全字段与决策
  （IGNORE/OBSERVE/CANDIDATE/ALLOW_LLM + reason_flags）——「为什么这次
  没说话」在这张表里有直接答案。

单条回放（replay）把一条 trace 展开：记忆 id join ``memories`` 表还原
正文，附同期参与决策。诚实边界：Router 命中、工具调用与预算分配目前
只进 thought 日志（Markdown），M1 回放不含这三段——表里没有的字段
不去猜。
"""

from __future__ import annotations

import json
from pathlib import Path

import config.settings as settings
from webui.db import connect_ro


def _memory_db() -> Path:
    return Path(settings.DB_PATH)


def _loads(text: str | None, default):
    try:
        parsed = json.loads(text or "")
        return parsed if parsed is not None else default
    except (ValueError, TypeError):
        return default


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def memory_traces(group_id: str | None, *, limit: int, offset: int = 0) -> dict:
    """轨迹流：列表只带计数与摘要（prompt/output 全文走 replay 详情）。"""
    conn = connect_ro(_memory_db())
    if conn is None or not _table_exists(conn, "memory_traces"):
        return {"total": 0, "items": []}
    try:
        where = "WHERE group_id = ?" if group_id else ""
        params: tuple = (group_id,) if group_id else ()
        total = conn.execute(
            f"SELECT COUNT(*) FROM memory_traces {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT id, ts, group_id, group_shared_space, user_id, message, "
            "mode, trigger, candidate_ids, filtered_ids, final_ids, "
            "rejected_ids, behavior_ids, debug "
            f"FROM memory_traces {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)),
        ).fetchall()
    except Exception:
        return {"total": 0, "items": []}
    finally:
        conn.close()
    items = []
    for (
        tid, ts, gid, space, user, message, mode, trigger,
        candidates, filtered, final, rejected, behavior, debug,
    ) in rows:
        items.append(
            {
                "id": tid,
                "ts": ts,
                "group_id": gid,
                "group_shared_space": space,
                "user_id": user,
                "message": message,
                "mode": mode,
                "trigger": trigger,
                "counts": {
                    "candidates": len(_loads(candidates, [])),
                    "filtered": len(_loads(filtered, [])),
                    "final": len(_loads(final, [])),
                    "rejected": len(_loads(rejected, [])),
                    "behavior": len(_loads(behavior, [])),
                },
                "debug": bool(debug),
            }
        )
    return {"total": int(total), "items": items}


def _resolve_memories(conn, ids: list) -> list[dict]:
    """按 id 还原记忆正文（join memories；查不到的 id 标 missing）。"""
    if not ids:
        return []
    found: dict[str, dict] = {}
    for chunk_start in range(0, len(ids), 200):
        chunk = [str(i) for i in ids[chunk_start:chunk_start + 200]]
        marks = ",".join("?" * len(chunk))
        try:
            rows = conn.execute(
                f"SELECT id, type, content, user_id FROM memories WHERE id IN ({marks})",
                chunk,
            ).fetchall()
        except Exception:
            rows = []
        for mid, mtype, content, user in rows:
            found[str(mid)] = {
                "id": str(mid), "type": mtype, "content": content, "user_id": user,
            }
    return [found.get(str(i), {"id": str(i), "missing": True}) for i in ids]


def memory_trace_detail(trace_id: int) -> dict | None:
    """单条轨迹完整展开（单条消息回放的记忆段）。"""
    conn = connect_ro(_memory_db())
    if conn is None or not _table_exists(conn, "memory_traces"):
        return None
    try:
        row = conn.execute(
            "SELECT id, ts, group_id, group_shared_space, user_id, message, "
            "mode, trigger, candidate_ids, filtered_ids, final_ids, "
            "rejected_ids, behavior_ids, score_map, prompt_snapshot, output, debug "
            "FROM memory_traces WHERE id = ?",
            (int(trace_id),),
        ).fetchone()
    except Exception:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    (
        tid, ts, gid, space, user, message, mode, trigger,
        candidates, filtered, final, rejected, behavior,
        score_map, prompt_snapshot, output, debug,
    ) = row
    conn2 = connect_ro(_memory_db())
    resolved: dict[str, list] = {}
    scores = _loads(score_map, {})
    if conn2 is not None:
        try:
            resolved = {
                "candidates": _resolve_memories(conn2, _loads(candidates, [])),
                "filtered": _resolve_memories(conn2, _loads(filtered, [])),
                "final": _resolve_memories(conn2, _loads(final, [])),
                "rejected": _resolve_memories(conn2, _loads(rejected, [])),
                "behavior": _resolve_memories(conn2, _loads(behavior, [])),
            }
        finally:
            conn2.close()
    for bucket in resolved.values():
        for item in bucket:
            score = scores.get(str(item.get("id")))
            if score is not None:
                item["score"] = score
    return {
        "id": tid,
        "ts": ts,
        "group_id": gid,
        "group_shared_space": space,
        "user_id": user,
        "message": message,
        "mode": mode,
        "trigger": trigger,
        "debug": bool(debug),
        "memories": resolved,
        "score_map": scores,
        "prompt_snapshot": prompt_snapshot or "",
        "output": output or "",
    }


def participation(group_id: str | None, *, limit: int, offset: int = 0) -> dict:
    """参与决策流：评分全字段 + 决策 + 原因标记（「为什么没说话」的答案）。"""
    conn = connect_ro(_memory_db())
    if conn is None or not _table_exists(conn, "participation_log"):
        return {"total": 0, "items": []}
    try:
        where = "WHERE group_id = ?" if group_id else ""
        params: tuple = (group_id,) if group_id else ()
        total = conn.execute(
            f"SELECT COUNT(*) FROM participation_log {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT id, ts, group_id, topic_id, relevance, opportunity, "
            "social_opportunity, topic_involvement, silence_bonus, "
            "recent_speech_penalty, velocity_penalty, repetition_penalty, "
            "expired_penalty, final_score, mode, decision, reason_flags, snapshot "
            f"FROM participation_log {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)),
        ).fetchall()
    except Exception:
        return {"total": 0, "items": []}
    finally:
        conn.close()
    keys = (
        "id", "ts", "group_id", "topic_id", "relevance", "opportunity",
        "social_opportunity", "topic_involvement", "silence_bonus",
        "recent_speech_penalty", "velocity_penalty", "repetition_penalty",
        "expired_penalty", "final_score", "mode", "decision",
    )
    items = []
    for row in rows:
        # 前 16 列是标量键值，末两列（reason_flags/snapshot JSON）单独解析
        item = dict(zip(keys, row[: len(keys)], strict=True))
        item["reason_flags"] = _loads(row[16], [])
        item["snapshot"] = _loads(row[17], {})
        items.append(item)
    return {"total": int(total), "items": items}
