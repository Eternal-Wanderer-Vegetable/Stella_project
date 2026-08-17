# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Memory Decision Trace（记忆决策追踪）。

对应设计文档《Evaluation & Debug Specification v1.0》。每次回复保存：
- 为什么这些记忆被调用；
- 为什么其他记忆没有被调用（拒绝原因）。

普通模式下只记 Input / Memory / Output；Debug 模式下记录完整的
Candidate / Policy / Ranking / Prompt。全部落到 SQLite 表 ``memory_traces``，
避免把结构化日志写进人类可读的 thought 日志文件。

错误分类体系（记录在 reason 里）：
    Type A Memory Creation Error / Type B Classification Error / Type C Policy Error
    Type D Retrieval Error / Type E Prompt Assembly Error / Type F Generation Error
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from typing import Any

from nonebot import logger

from config import DB_PATH, MEMORY_TRACE_ENABLED, MEMORY_TRACE_TABLE


def _ensure_table(conn: sqlite3.Connection) -> None:
    """确保 memory_traces 表存在（幂等），并为旧表补齐 v8 新增列。

    group_id 是触发这次回复的真实 QQ 群；group_shared_space 是记忆检索所用的
    共享空间（config.spaces.resolve_space(group_id)）。排查时两者都需要，
    因此都落库。旧表没有 group_shared_space 列时用 ALTER 补上（追踪数据有
    诊断价值，重建会丢）；列已存在时 ALTER 会抛 OperationalError，静默跳过。
    """
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MEMORY_TRACE_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            group_id TEXT,
            group_shared_space TEXT,
            user_id TEXT,
            message TEXT,
            mode TEXT,
            trigger TEXT,
            candidate_ids TEXT,
            filtered_ids TEXT,
            final_ids TEXT,
            rejected_ids TEXT,
            behavior_ids TEXT,
            score_map TEXT,
            prompt_snapshot TEXT,
            output TEXT,
            debug INTEGER DEFAULT 0
        )
        """
    )
    # 旧表兼容：v8 之前的 memory_traces 没有 group_shared_space 列 → 补列（幂等）
    with contextlib.suppress(sqlite3.OperationalError):
        conn.execute(f"ALTER TABLE {MEMORY_TRACE_TABLE} ADD COLUMN group_shared_space TEXT")


def record_trace(
    *,
    group_id: Any,
    group_shared_space: Any = "",
    user_id: Any,
    message: str,
    mode: str = "",
    trigger: str = "reply",
    candidates: list[dict[str, Any]] | None = None,
    allowed: list[dict[str, Any]] | None = None,
    final: list[dict[str, Any]] | None = None,
    rejected: list[dict[str, Any]] | None = None,
    behavior: list[dict[str, Any]] | None = None,
    prompt_snapshot: str = "",
    output: str = "",
    debug: bool = False,
) -> None:
    """把一次记忆决策写入 memory_traces 表；开关关闭或异常时静默跳过。

    group_id 是触发这次回复的真实 QQ 群；group_shared_space 是记忆检索所用的
    共享空间；两者分别落库，排查时都需要。
    """
    if not MEMORY_TRACE_ENABLED or not DB_PATH.exists():
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        _ensure_table(conn)
        conn.execute(
            f"""
            INSERT INTO {MEMORY_TRACE_TABLE} (
                group_id, group_shared_space, user_id, message, mode, trigger,
                candidate_ids, filtered_ids, final_ids, rejected_ids, behavior_ids,
                score_map, prompt_snapshot, output, debug
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(group_id),
                str(group_shared_space),
                str(user_id),
                (message or "")[:500],
                mode,
                trigger,
                _dump_ids(candidates),
                _dump_ids(allowed),
                _dump_ids(final),
                _dump_ids(rejected),
                _dump_ids(behavior),
                _dump_scores(final),
                (prompt_snapshot or "")[:8000],
                (output or "")[:2000],
                1 if debug else 0,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f"📊 [Trace] 写入决策追踪失败: {e}")


def _dump_ids(memories: list[dict[str, Any]] | None) -> str:
    """把记忆列表的 id 序列化为 JSON 字符串。"""
    if not memories:
        return "[]"
    return json.dumps([m.get("id") for m in memories if m.get("id")], ensure_ascii=False)


def _dump_scores(memories: list[dict[str, Any]] | None) -> str:
    """把记忆的 id→score 映射序列化为 JSON 字符串。"""
    if not memories:
        return "{}"
    scores: dict[str, float] = {}
    for m in memories:
        if m.get("id") and m.get("_score") is not None:
            scores[str(m["id"])] = float(m["_score"])
    return json.dumps(scores, ensure_ascii=False)


# ── 统计（Debug Dashboard） ─────────────────────────────

def _parse_ids(text: str) -> list[str]:
    try:
        parsed = json.loads(text or "[]")
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def memory_statistics(days: float = 7.0) -> dict[str, Any]:
    """汇总最近 N 天的记忆统计：生成/采纳/拒绝率、平均召回量、各模式召回量。"""
    if not DB_PATH.exists():
        return {}
    try:
        conn = sqlite3.connect(DB_PATH)
        _ensure_table(conn)
        cutoff_ts = time.time() - days * 86400
        rows = conn.execute(
            f"SELECT ts, mode, final_ids FROM {MEMORY_TRACE_TABLE}"
        ).fetchall()
        stats: dict[str, Any] = {"by_mode": {}, "total_traces": len(rows), "recent": 0}
        mode_counts: dict[str, list[int]] = {}
        recent = 0
        for ts, mode, final_ids in rows:
            parsed_ts = _parse_ts(ts)
            if parsed_ts and parsed_ts >= cutoff_ts:
                recent += 1
            ids = _parse_ids(final_ids)
            key = (mode or "UNKNOWN").strip() or "UNKNOWN"
            mode_counts.setdefault(key, []).append(len(ids))
        stats["recent_traces"] = recent
        stats["avg_memories_per_reply"] = round(_avg(mode_counts.values()), 2)
        stats["by_mode"] = {
            mode: round(_avg([counts]), 2) for mode, counts in mode_counts.items()
        }
        conn.close()
        return stats
    except Exception as e:
        logger.debug(f"📊 [Trace] 统计失败: {e}")
        return {}


def _avg(groups) -> float:
    values = [v for group in groups for v in group]
    return (sum(values) / len(values)) if values else 0.0


def _parse_ts(value: Any) -> float | None:
    from memory.timeutil import parse_db_timestamp


    return parse_db_timestamp(value)


def prune_traces(keep_days: float = 30.0) -> int:
    """清理超过 keep_days 的决策追踪，防止数据库无限膨胀；返回删除条数。"""
    if not DB_PATH.exists():
        return 0
    try:
        conn = sqlite3.connect(DB_PATH)
        _ensure_table(conn)
        conn.execute(
            f"DELETE FROM {MEMORY_TRACE_TABLE} WHERE julianday('now') - julianday(ts) > ?",
            (keep_days,),
        )
        deleted = conn.total_changes
        conn.commit()
        conn.close()
        return deleted
    except Exception as e:
        logger.debug(f"📊 [Trace] 清理失败: {e}")
        return 0
