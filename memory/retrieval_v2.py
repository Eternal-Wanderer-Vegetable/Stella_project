# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆检索 v2（Context-aware Memory Activation）。

对应设计文档《Memory Retrieval Specification v1.0》。与旧 Retriever 的关键区别：
旧的是“找最相关的文本”，v2 是“找当前 Stella 行为真正需要的记忆”。

流程（Policy 优先于 Similarity）：
    Mode Detection → Policy Filter → Visibility Access → Hybrid Search
    → Rank（Policy 权重）→ 分离聊天素材与行为约束 → 动态上限

与旧 Retriever 的关系：双轨并存。旧 get_group_memories / get_user_memories 保留
（MEMORY_V2_ENABLED=False 时回退）；本模块是 v2 的检索入口。
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from config import (
    DB_PATH,
    LONG_TERM_RELEVANCE_CANDIDATE_LIMIT,
    MEMORY_V2_ENABLED,
    RAG_ENABLED,
    RAG_TOP_K,
)
from memory.policy import (
    MODE_CONFLICT_AVOID,
    VISIBILITY_INTERNAL,
    VISIBILITY_OPEN,
    VISIBILITY_RESTRICTED,
    detect_mode,
    mode_limit,
    normalize_mode,
    rank_memories,
    split_behavior_constraints,
    usage_allowed,
)


@dataclass
class RetrievalResult:
    """一次 v2 检索的完整结果（含决策轨迹，供 Evaluation & Debug）。"""

    mode: str = ""
    conversation_memories: list[dict[str, Any]] = field(default_factory=list)
    behavior_constraints: list[dict[str, Any]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _parse_usage_tags(value: Any) -> list[str]:
    """从库里的 usage_tags（JSON 字符串或 None）解析为列表。"""
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _row_to_memory(row: tuple[Any, ...]) -> dict[str, Any]:
    """把 v2 检索 SQL 行转成记忆 dict。

    行结构：id, group_id, user_id, type, content, importance, confidence,
            visibility, usage_tags, trigger_data, behavior_rule, last_accessed_at
    """
    memory = {
        "id": row[0],
        "group_id": row[1],
        "user_id": row[2],
        "type": row[3] or "FACT",
        "content": row[4] or "",
        "importance": row[5],
        "confidence": row[6],
        "visibility": row[7] or VISIBILITY_OPEN,
        "usage_tags": _parse_usage_tags(row[8]),
        "trigger_data": row[9],
        "behavior_rule": row[10],
        "last_accessed_at": row[11],
    }
    return memory


def _select_columns() -> str:
    return (
        "id, group_id, user_id, type, content, importance, confidence, "
        "visibility, usage_tags, trigger_data, behavior_rule, last_accessed_at"
    )


def _allowed_visibility_clause(mode: str) -> str:
    """根据模式生成 SQL 级 Visibility 预过滤。

    原理（正确检索顺序）：先决定“什么东西有资格被找到”，再在合法范围内找最相关。
    除 CONFLICT_AVOID 外，RESTRICTED/INTERNAL 一律不进候选池，避免污染；
    CONFLICT_AVOID 是 Behavior Guard 入口，允许 RESTRICTED 进入候选（随后被分离为行为约束），
    仅把 INTERNAL（仅供系统决策，禁止进 LLM Prompt）挡在门外。
    """
    mode = normalize_mode(mode)
    if mode == MODE_CONFLICT_AVOID:
        return "m.visibility IS NULL OR m.visibility != ?"
    return "m.visibility IS NULL OR m.visibility NOT IN (?, ?)"


def _fetch_candidates(
    cursor: sqlite3.Cursor,
    group_id: int,
    user_id: Optional[int],
    mode: str,
    query: str,
    pool_limit: int,
) -> list[dict[str, Any]]:
    """拉取候选记忆行（先按 Visibility 过滤，再按访问时间倒序）。

    include_user 为 None 表示群级（主动发言）；否则限定该用户（@ 回复）。
    这是“Policy 优先于 Similarity”的第一步：在合法范围内取候选。
    """
    where = "m.status = 'active'"
    params: list[Any] = []
    if user_id is None:
        where += " AND m.group_id = ?"
        params.append(str(group_id))
    else:
        where += " AND m.group_id = ? AND m.user_id = ?"
        params.extend([str(group_id), str(user_id)])

    # Visibility 预过滤
    where += f" AND ({_allowed_visibility_clause(mode)})"
    if mode == MODE_CONFLICT_AVOID:
        # 只挡 INTERNAL（Behavior Guard 需要 RESTRICTED 进入候选）
        params.append(VISIBILITY_INTERNAL)
    else:
        params.extend([VISIBILITY_RESTRICTED, VISIBILITY_INTERNAL])

    # 有关键词时优先走 FTS（语义/关键词混合）
    rows: list[tuple[Any, ...]] = []
    if query and RAG_ENABLED:
        rows = _query_fts(cursor, group_id, user_id, query, max(pool_limit, RAG_TOP_K), mode)
    if not rows:
        sql = (
            f"SELECT {_select_columns()} FROM memories m WHERE {where} "
            "ORDER BY m.last_accessed_at DESC LIMIT ?"
        )
        params.append(pool_limit)
        try:
            rows = cursor.execute(sql, tuple(params)).fetchall()
        except sqlite3.OperationalError:
            # 旧库可能还没有 v2 列：退化为不带新列的查询
            return _fetch_candidates_legacy(cursor, group_id, user_id, mode, pool_limit)
    return [_row_to_memory(r) for r in rows]


def _fetch_candidates_legacy(
    cursor: sqlite3.Cursor,
    group_id: int,
    user_id: Optional[int],
    mode: str,
    pool_limit: int,
) -> list[dict[str, Any]]:
    """旧库（无 v2 列）回退：只按 status/group/user 取，不按 Visibility 过滤。"""
    if user_id is None:
        sql = (
            "SELECT id, group_id, user_id, type, content, importance, confidence, "
            "'OPEN', NULL, NULL, NULL, last_accessed_at FROM memories m "
            "WHERE m.group_id = ? AND m.status = 'active' ORDER BY m.last_accessed_at DESC LIMIT ?"
        )
        params: list[Any] = [str(group_id), pool_limit]
    else:
        sql = (
            "SELECT id, group_id, user_id, type, content, importance, confidence, "
            "'OPEN', NULL, NULL, NULL, last_accessed_at FROM memories m "
            "WHERE m.group_id = ? AND m.user_id = ? AND m.status = 'active' "
            "ORDER BY m.last_accessed_at DESC LIMIT ?"
        )
        params = [str(group_id), str(user_id), pool_limit]
    try:
        return [_row_to_memory(r) for r in cursor.execute(sql, tuple(params)).fetchall()]
    except sqlite3.OperationalError:
        return []


def _query_fts(
    cursor: sqlite3.Cursor,
    group_id: int,
    user_id: Optional[int],
    query: str,
    limit: int,
    mode: str,
) -> list[tuple[Any, ...]]:
    """FTS5 语义检索候选（复用 memories_fts 索引，并做 Visibility 预过滤）。"""
    from memory.retriever import _ensure_fts_table, _segment_text

    if not _ensure_fts_table(cursor):
        return []
    tokens = _segment_text(query)
    if not tokens:
        return []
    try:
        sql = (
            "SELECT m.id, m.group_id, m.user_id, m.type, m.content, m.importance, m.confidence, "
            "m.visibility, m.usage_tags, m.trigger_data, m.behavior_rule, m.last_accessed_at "
            "FROM memories_fts f "
            "JOIN memories m ON f.mem_id = m.id "
            "WHERE f.group_id = ? AND m.status = 'active' "
        )
        params: list[Any] = [str(group_id)]
        if user_id is not None:
            sql += "AND m.user_id = ? "
            params.append(str(user_id))
        sql += f"AND ({_allowed_visibility_clause(mode)}) "
        if mode == MODE_CONFLICT_AVOID:
            params.append(VISIBILITY_INTERNAL)
        else:
            params.extend([VISIBILITY_RESTRICTED, VISIBILITY_INTERNAL])
        sql += "AND f.content MATCH ? ORDER BY bm25(memories_fts) LIMIT ?"
        params.extend([tokens, limit])
        return cursor.execute(sql, tuple(params)).fetchall()
    except sqlite3.OperationalError:
        return []


def _merge_similar(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同类记忆合并（Selection Rule 1）：同一 type 且内容高度相似的记忆合并为一条。"""
    merged: list[dict[str, Any]] = []
    for mem in memories:
        target = None
        for existing in merged:
            if existing["type"] == mem["type"] and _is_similar(existing["content"], mem["content"]):
                target = existing
                break
        if target is None:
            merged.append(dict(mem))
        else:
            # 合并内容：取更完整的一方；置信度/重要度取较大值
            target["content"] = _merge_content(target["content"], mem["content"])
            target["confidence"] = _max_float(target.get("confidence"), mem.get("confidence"))
            target["importance"] = _max_float(target.get("importance"), mem.get("importance"))
    return merged


def _merge_content(old: str, new: str) -> str:
    old = (old or "").strip()
    new = (new or "").strip()
    if not old:
        return new
    if not new:
        return old
    if new in old:
        return old
    if old in new:
        return new
    return old + "；" + new


def _normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[\W_]+", " ", text)
    return " ".join(text.split())


def _is_similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    a_norm = _normalize_text(a)
    b_norm = _normalize_text(b)
    if not a_norm or not b_norm:
        return False
    if a_norm in b_norm or b_norm in a_norm:
        return True
    a_set, b_set = set(a_norm.split()), set(b_norm.split())
    if not a_set or not b_set:
        return False
    inter = a_set & b_set
    return len(inter) / len(a_set | b_set) >= 0.65


def _max_float(a: Any, b: Any) -> float:
    def _f(v: Any) -> float:
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    return max(_f(a), _f(b))


def retrieve_memories(
    group_id: int,
    user_id: int,
    query: str,
    trigger: str = "reply",
    mode: Optional[str] = None,
) -> RetrievalResult:
    """v2 记忆检索主入口。

    :param group_id: 群 ID
    :param user_id: 当前用户 ID（主动发言时传 0）
    :param query: 当前消息/话题文本
    :param trigger: "reply"（@ 回复）或 "proactive"（主动插话）
    :param mode: 可显式指定行为模式；不传则自动检测
    :return: RetrievalResult（含聊天素材、行为约束与决策轨迹）
    """
    if not MEMORY_V2_ENABLED or not DB_PATH.exists():
        return RetrievalResult()

    mode = normalize_mode(mode or detect_mode(query, trigger=trigger))

    # 短期缓存：5 分钟内同一群同一触发方式的检索结果直接复用，避免每句话重新检索
    cache_key = (str(DB_PATH), str(group_id), str(user_id), trigger, mode)
    cached = _CACHE.get(cache_key)
    if cached is not None and (time.monotonic() - cached[0]) < RETRIEVAL_CACHE_TTL:
        _CACHE[cache_key] = cached  # 简单 LRU：命中即刷新计时
        return cached[1]

    limit = mode_limit(mode)
    pool_limit = max(LONG_TERM_RELEVANCE_CANDIDATE_LIMIT, limit * 5)

    conn = _connect()
    cursor = conn.cursor()
    try:
        include_user: Optional[int] = None if trigger == "proactive" else user_id
        candidates = _fetch_candidates(cursor, group_id, include_user, mode, query, pool_limit)
    finally:
        conn.close()

    trace: dict[str, Any] = {
        "mode": mode,
        "candidate_count": len(candidates),
        "candidates": [c.get("id") for c in candidates[:10]],
    }

    # 1) Usage 层过滤（Policy Filtering）
    allowed = [m for m in candidates if usage_allowed(mode, m)[0]]
    trace["allowed_count"] = len(allowed)

    # 2) Ranking（Policy 权重）
    ranked = rank_memories(allowed, mode, query=query)
    trace["ranked_ids"] = [m.get("id") for m in ranked[:10]]

    # 3) 同类合并
    ranked = _merge_similar(ranked)
    trace["merged_count"] = len(ranked)

    # 4) 分离聊天素材与行为约束
    behavior = split_behavior_constraints(ranked)
    conversation = [m for m in ranked if m not in behavior]
    trace["behavior_count"] = len(behavior)

    # 5) 动态上限：安全优先（CONFLICT_AVOID 上限更大）
    conversation = conversation[:limit]
    trace["final_ids"] = [m.get("id") for m in conversation]
    trace["rejected_ids"] = [m.get("id") for m in candidates if m.get("id") not in {x.get("id") for x in conversation}]

    result = RetrievalResult(
        mode=mode,
        conversation_memories=conversation,
        behavior_constraints=behavior,
        trace=trace,
    )
    # 写回缓存
    _CACHE[cache_key] = (time.monotonic(), result)
    # 容量控制：只保留最近 _CACHE_MAX_ENTRIES 项
    if len(_CACHE) > _CACHE_MAX_ENTRIES:
        for key in list(_CACHE)[: len(_CACHE) - _CACHE_MAX_ENTRIES]:
            _CACHE.pop(key, None)
    return result


# 短期检索缓存（进程内，Key = (db_path, group, user, trigger, mode)）
# 设计参考：Memory Retrieval Specification §12 Retrieval Cache
RETRIEVAL_CACHE_TTL = 300.0  # 5 分钟
_CACHE_MAX_ENTRIES = 128
_CACHE: dict[tuple[str, str, str, str, str], tuple[float, RetrievalResult]] = {}
