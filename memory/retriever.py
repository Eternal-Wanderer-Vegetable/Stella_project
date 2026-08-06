from __future__ import annotations

import re
import sqlite3
from typing import Any
from config import (
    DB_PATH,
    PROACTIVE_LONG_TERM_LIMIT,
    REPLY_LONG_TERM_LIMIT,
    LONG_TERM_RELEVANCE_ENABLED,
    LONG_TERM_RELEVANCE_KEYWORDS,
)


def _normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[\W_]+", " ", text)
    return " ".join(text.split())


def _extract_keywords(text: str, max_keywords: int) -> list[str]:
    segments = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    candidates: list[str] = []
    for seg in segments:
        if len(seg) <= 4:
            candidates.append(seg)
        else:
            for size in (3, 2):
                for i in range(len(seg) - size + 1):
                    candidates.append(seg[i : i + size])
    freq: dict[str, int] = {}
    for c in candidates:
        if len(c) < 2:
            continue
        freq[c] = freq.get(c, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [word for word, _ in ranked[:max_keywords]]


def _compute_overlap(query: str, text: str) -> int:
    if not query or not text:
        return 0
    query_words = set(_normalize_text(query).split())
    text_words = set(_normalize_text(text).split())
    if not query_words or not text_words:
        return 0
    return len(query_words & text_words)


def _fetch_table(cursor: sqlite3.Cursor, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    try:
        return cursor.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def _memories_from_rows(rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    return [
        {
            "content": row[0],
            "user_id": row[1],
            "type": row[2] if len(row) > 2 else "FACT",
            "last_accessed_at": row[3] if len(row) > 3 else None,
        }
        for row in rows
    ]


def get_group_memories(group_id: int, limit: int = PROACTIVE_LONG_TERM_LIMIT) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    rows = _fetch_table(
        cursor,
        "SELECT content, user_id, type, last_accessed_at FROM memories "
        "WHERE group_id = ? AND status = 'active' ORDER BY last_accessed_at DESC LIMIT ?",
        (str(group_id), limit),
    )
    if not rows:
        rows = _fetch_table(
            cursor,
            "SELECT summary, user_id, 'FACT', CURRENT_TIMESTAMP FROM long_term_memories "
            "WHERE group_id = ? ORDER BY rowid DESC LIMIT ?",
            (str(group_id), limit),
        )
    conn.close()
    return _memories_from_rows(rows)


def get_user_memories(group_id: int, user_id: int, limit: int = REPLY_LONG_TERM_LIMIT) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    rows = _fetch_table(
        cursor,
        "SELECT content, user_id, type, last_accessed_at FROM memories "
        "WHERE group_id = ? AND user_id = ? AND status = 'active' ORDER BY last_accessed_at DESC LIMIT ?",
        (str(group_id), str(user_id), limit),
    )
    if not rows:
        rows = _fetch_table(
            cursor,
            "SELECT summary, user_id, 'FACT', CURRENT_TIMESTAMP FROM long_term_memories "
            "WHERE group_id = ? AND user_id = ? ORDER BY rowid DESC LIMIT ?",
            (str(group_id), str(user_id), limit),
        )
    conn.close()
    return _memories_from_rows(rows)


def get_related_memories(group_id: int, user_id: int, query: str, limit: int = 3) -> list[dict[str, Any]]:
    if not DB_PATH.exists() or not LONG_TERM_RELEVANCE_ENABLED:
        return []
    keywords = _extract_keywords(query, LONG_TERM_RELEVANCE_KEYWORDS)
    if not keywords:
        return []
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    rows = _fetch_table(
        cursor,
        "SELECT content, user_id, type, last_accessed_at FROM memories "
        "WHERE group_id = ? AND user_id != ? AND status = 'active'",
        (str(group_id), str(user_id)),
    )
    if not rows:
        rows = _fetch_table(
            cursor,
            "SELECT summary, user_id, 'FACT', CURRENT_TIMESTAMP FROM long_term_memories "
            "WHERE group_id = ? AND user_id != ?",
            (str(group_id), str(user_id)),
        )
    conn.close()

    candidates = []
    for row in rows:
        content = row[0] or ""
        hits = sum(1 for kw in keywords if kw in content)
        if hits > 0:
            candidates.append((hits, content, row[1]))
    candidates.sort(key=lambda x: (x[0],), reverse=True)
    return [
        {"content": content, "user_id": user_id, "type": "RELATED"}
        for _, content, user_id in candidates[:limit]
    ]
