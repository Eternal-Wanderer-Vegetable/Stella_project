# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""长期记忆检索模块（memory.retriever）。

本模块对外提供三个取记忆的入口：
- get_group_memories   —— 某群组共享空间的活动记忆（主动发言/闲聊上下文用）；
- get_user_memories    —— 某用户在指定群组共享空间中的记忆（@ 回复上下文用）；
- get_related_memories —— “别人（≠ user_id）”的相关记忆（查无此人时的兜底/安抚）。

三个入口的归属参数都是 ``group_shared_space``（群组共享空间），由
``config.spaces.resolve_space(qq_group_id)`` 得到；同一空间内的多个 QQ 群共享记忆。

检索有两级路径，都是先试 FTS5 全文索引，失败再回退到多维权重排序：
- FTS 命中（RAG 开关全开时）：走 memories_fts 虚拟表 + bm25() 排序；
- FTS 关闭 / 索引缺失 / 无命中：回退 SQL 抓候选行，
  再由 _rank_fallback_rows / _score_memory 按关键词、近期度、重要度、
  置信度、用户相关性综合打分重排。

RAG 开关组合（决定走哪条路径）：
- RAG_ENABLED=False                  → 永远走回退路径；
- RAG_ENABLED=True 且 FTS 开关关闭     → 仍走回退路径；
- 两者都开                          → 尝试 FTS 索引，没结果再回退。
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
import time
from typing import Any

from config import (
    DB_PATH,
    LONG_TERM_RELEVANCE_CANDIDATE_LIMIT,
    LONG_TERM_RELEVANCE_ENABLED,
    LONG_TERM_RELEVANCE_KEYWORDS,
    LONG_TERM_RELEVANCE_WEIGHT_CONFIDENCE,
    LONG_TERM_RELEVANCE_WEIGHT_IMPORTANCE,
    LONG_TERM_RELEVANCE_WEIGHT_KEYWORDS,
    LONG_TERM_RELEVANCE_WEIGHT_RECENCY,
    LONG_TERM_RELEVANCE_WEIGHT_USER_RELEVANCE,
    PROACTIVE_LONG_TERM_LIMIT,
    RAG_ENABLED,
    RAG_SQLITE_FTS_ENABLED,
    RAG_TOP_K,
    REPLY_LONG_TERM_LIMIT,
)
from memory.text_similarity import normalize_text


def _extract_keywords(text: str, max_keywords: int) -> list[str]:
    """从查询文本中抽取出现频次最高的中文关键词（回退排序用）。

    策略：先切出 2~8 个汉字连成的片段；长度 ≤4 的整个保留，
    更长的片段再切成 3 字/2 字滑窗子串；最后按频次降序取前 max_keywords 个。

    :param text: 任意文本（通常是用户查询）
    :param max_keywords: 最多返回的关键词个数
    :return: 按频次降序的关键词列表，无命中则为空列表
    """
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
    """计算 query 与 text 在规范化后词集中的交集大小（重叠词数，用于补充关键词分）。"""
    if not query or not text:
        return 0
    query_words = set(normalize_text(query).split())
    text_words = set(normalize_text(text).split())
    if not query_words or not text_words:
        return 0
    return len(query_words & text_words)


def _fetch_table(cursor: sqlite3.Cursor, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    """执行一条查询并把结果行取出；表尚不存在等 OperationalError 时返回空列表，避免异常穿透调用方。"""
    try:
        return cursor.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def _memories_from_rows(rows: list[tuple[Any, ...]]) -> list[dict[str, Any]]:
    """把标准行结构（content, user_id, [type], [last_accessed_at]）转成记忆 dict 列表。"""
    return [
        {
            "content": row[0],
            "user_id": row[1],
            "type": row[2] if len(row) > 2 else "FACT",
            "last_accessed_at": row[3] if len(row) > 3 else None,
        }
        for row in rows
    ]


def _parse_timestamp(value: Any) -> float:
    """把 last_accessed_at 等时间字段解析为 epoch 秒（float，UTC 基准）。

    兼容三种形态：
    - 数值（epoch 秒）
    - 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DD HH:MM:SS.ffffff' / 'YYYY-MM-DD'
    - 空值 / 无法解析 → 返回 0.0
    """
    from memory.timeutil import parse_db_timestamp


    return parse_db_timestamp(value) or 0.0


def _recency_score(value: Any, max_days: float = 30.0) -> float:
    """把"距上次访问的时间"换算成一个 0~1 之间的近期权重。

    - 无时间信息 → 0.0（无法判断是否近期，视为不新）
    - 距今越近分数越高：30 天内线性衰减，超过 30 天保留 0.3 的基础分，
      避免"稍微旧一点的记忆"直接被清零挤出前几名。
    """
    ts = _parse_timestamp(value)
    if ts <= 0:
        return 0.0
    age_days = max(0.0, (time.time() - ts) / 86400.0)
    if age_days >= max_days:
        return 0.3
    return 1.0 - (age_days / max_days) * 0.7


def _score_memory(query: str, memory: dict[str, Any], user_id: int) -> float:
    """对单条记忆计算“与当前查询的相关度”综合分（回退排序的核心打分函数）。

    分数 = 关键词命中分 + 词重叠分 + 近期度分 + 重要度分 + 置信度分 + 用户相关分。
    - 关键词命中：用 _extract_keywords 抽到的关键词在内容中出现的次数 × 权重；
    - 词重叠：query 与 content 规范化后词集合交集大小（区分覆盖程度）；
    - 近期度：_recency_score(last_accessed_at) × 权重；
    - 重要度 / 置信度：直接数值乘权重（无法解析的按 0 计）；
    - 用户相关：记忆所属 user_id 与请求 user_id 一致时给予固定加分。

    :param query: 用户查询文本
    :param memory: 一条记忆的 dict（含 content / importance / confidence / last_accessed_at / user_id）
    :param user_id: 当前请求的用户 ID（0 表示不关心具体用户）
    :return: 综合分数，分数越高越相关
    """
    content = (memory.get("content") or "").strip()
    if not content:
        return 0.0

    keywords = _extract_keywords(query, LONG_TERM_RELEVANCE_KEYWORDS)
    keyword_hits = sum(1 for kw in keywords if kw in content)
    keyword_score = keyword_hits * LONG_TERM_RELEVANCE_WEIGHT_KEYWORDS

    # 细化：词项重叠次数（非去重）也计入关键词分，能更好地区分覆盖程度
    overlap = _compute_overlap(query, content)
    keyword_score += overlap * 0.5

    recency_score = LONG_TERM_RELEVANCE_WEIGHT_RECENCY * _recency_score(
        memory.get("last_accessed_at")
    )

    importance = memory.get("importance")
    importance_score = 0.0
    if importance is not None:
        try:
            importance_score = float(importance) * LONG_TERM_RELEVANCE_WEIGHT_IMPORTANCE
        except (TypeError, ValueError):
            importance_score = 0.0

    confidence = memory.get("confidence")
    confidence_score = 0.0
    if confidence is not None:
        try:
            confidence_score = float(confidence) * LONG_TERM_RELEVANCE_WEIGHT_CONFIDENCE
        except (TypeError, ValueError):
            confidence_score = 0.0

    user_relevance_score = 0.0
    memory_user = memory.get("user_id")
    if memory_user is not None and str(memory_user) == str(user_id):
        user_relevance_score = LONG_TERM_RELEVANCE_WEIGHT_USER_RELEVANCE

    return keyword_score + recency_score + importance_score + confidence_score + user_relevance_score


def _rank_fallback_rows(
    query: str,
    rows: list[tuple[Any, ...]],
    user_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    """对 query 检索无 FTS 命中时回退得到的行（或直接回退扫描的行）做更细粒度的排序。

    行结构：content, user_id, type, last_accessed_at, importance, confidence
    排序依据 `_score_memory` 的综合权重（关键词 + 近期度衰减 + 重要度 + 置信度 + 用户相关），
    分数相同则保持 SQL 返回顺序（SQL 已按 last_accessed_at DESC），保证稳定。
    """
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        content = row[0] or ""
        if not content:
            continue
        memory = {
            "content": content,
            "user_id": row[1],
            "type": row[2] if len(row) > 2 else "FACT",
            "last_accessed_at": row[3] if len(row) > 3 else None,
            "importance": row[4] if len(row) > 4 else None,
            "confidence": row[5] if len(row) > 5 else None,
        }
        score = _score_memory(query, memory, user_id)
        if score > 0:
            scored.append((score, memory))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in scored[:limit]]


def _segment_text(text: str) -> str:
    """把原始文本转换成 FTS5 适合匹配的“词串”：中文按滑窗切 3/2 字片段，其余按 \\w+ 分词。

    与 _extract_keywords 类似，但结果用于全文索引的 content 列（写入时）和 MATCH 查询词。
    会去掉重复片段（dict.fromkeys 保序去重），避免同一词在索引里重复膨胀。
    """
    normalized = normalize_text(text)
    segments = re.findall(r"[\u4e00-\u9fff]{2,8}", normalized)
    tokens: list[str] = []
    for seg in segments:
        if len(seg) <= 4:
            tokens.append(seg)
        else:
            for size in (3, 2):
                for i in range(len(seg) - size + 1):
                    tokens.append(seg[i : i + size])
    tokens.extend(re.findall(r"\w+", normalized))
    return " ".join(dict.fromkeys(tokens))


def _ensure_fts_table(cursor: sqlite3.Cursor) -> bool:
    """确保 FTS5 虚拟表 memories_fts 已创建（幂等）；失败（如 SQLite 未编译 FTS5）返回 False。

    v8 起 memories_fts 的归属列改名为 ``group_shared_space``。FTS5 虚拟表无法
    ALTER 加列/改列名，因此探测到旧结构（无 ``group_shared_space`` 列）时直接
    DROP 重建——索引可从主表全量重建，无数据损失。否则后续按新列名查询会抛
    OperationalError 而被 _query_rag_results 静默吞掉，表现为「检索永远无 FTS
    命中、静默降级」（新库无此问题，但测试库与旧库会遇到）。
    """
    fts_ddl = (
        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5("
        "mem_id UNINDEXED, content, group_shared_space UNINDEXED, user_id UNINDEXED)"
    )
    try:
        cursor.execute(fts_ddl)
        columns = [row[1] for row in cursor.execute("PRAGMA table_info(memories_fts)").fetchall()]
        if "group_shared_space" not in columns:
            # 旧结构（group_id）→ 重建为新结构
            cursor.execute("DROP TABLE memories_fts")
            cursor.execute(fts_ddl)
        return True
    except sqlite3.OperationalError:
        return False


def _rebuild_fts_index(cursor: sqlite3.Cursor) -> None:
    """全量重建 FTS5 索引：先清空 memories_fts，再从 memories 表重新灌入 active 行。

    何时触发：查询时发现索引行数与 memories 表 active 行数不一致（数不匹配），
    说明索引缺失或过期，重建可让检索结果与主表对齐。代价是 O(N) 全量重新写入。
    """
    cursor.execute("DELETE FROM memories_fts")
    rows = cursor.execute(
        "SELECT id, group_shared_space, user_id, content FROM memories WHERE status = 'active' AND content IS NOT NULL"
    ).fetchall()
    records = []
    for memory_id, group_shared_space, user_id, content in rows:
        text = _segment_text(content)
        if not text:
            continue
        records.append((memory_id, text, group_shared_space, user_id))
    if records:
        cursor.executemany(
            "INSERT INTO memories_fts (mem_id, content, group_shared_space, user_id) VALUES (?, ?, ?, ?)",
            records,
        )
    # 全量重建要立即提交，否则连接关闭后回滚，下次查询仍需重扫（且修复结果不落盘）
    with contextlib.suppress(Exception):
        cursor.connection.commit()


def _upsert_fts_record(cursor: sqlite3.Cursor, memory_id: str, group_shared_space: str, user_id: str, content: str) -> None:
    """把单条记忆写入 FTS5 索引。

    关键点：FTS5 表没有唯一约束，重复 INSERT 会累积多行 → 检索时出现重复。
    因此这里必须“先删后插”（DELETE + INSERT）来模拟 upsert，以 mem_id 为准保证一条记忆只有一行索引。
    开关（RAG_ENABLED / RAG_SQLITE_FTS_ENABLED）不满足时直接返回，不写索引。
    """
    if not RAG_ENABLED or not RAG_SQLITE_FTS_ENABLED:
        return
    if not _ensure_fts_table(cursor):
        return
    text = _segment_text(content)
    if not text:
        return
    # FTS5 表没有唯一约束，INSERT OR REPLACE 会累积重复行；
    # 因此先按 mem_id 删除旧行再插入，保证“每个记忆只对应一条索引”。
    cursor.execute(
        "DELETE FROM memories_fts WHERE mem_id = ?",
        (memory_id,),
    )
    cursor.execute(
        "INSERT INTO memories_fts (mem_id, content, group_shared_space, user_id) VALUES (?, ?, ?, ?)",
        (memory_id, text, group_shared_space, user_id),
    )


def _query_rag_results(
    cursor: sqlite3.Cursor,
    group_shared_space: str,
    query: str,
    limit: int,
    include_user_id: str | None = None,
    exclude_user_id: str | None = None,
) -> list[tuple[Any, ...]]:
    """用 FTS5 bm25 全文检索拉取候选记忆行（RAG 主路径）。

    逻辑：
    1. 前置开关检查（RAG_ENABLED / RAG_SQLITE_FTS_ENABLED）不满足 → 返回空；
    2. 确保索引存在（_ensure_fts_table 会处理旧版结构重建），并把查询也走一遍
       _segment_text 得到 MATCH 词串；
    3. 若索引空 或 索引行数与 memories active 行数不一致 → 全量重建；
    4. 构造 JOIN 查询：先到 FTS 表（memories_fts f）匹配，再 JOIN 主表取完整字段，
       通过 include_user_id / exclude_user_id 控制是否限定具体用户；
    5. 排序必须用 bm25(memories_fts)——注意 FTS5 的 bm25() 第一个参数必须传
       虚拟表的真实表名，不能传别名（如 f），否则报 "no such column" 错误。

    :param cursor: 数据库游标
    :param group_shared_space: 群组共享空间标识（由 config.spaces.resolve_space 得到）
    :param query: 用户查询文本
    :param limit: 返回行数上限
    :param include_user_id: 若非空，只取该用户的记忆
    :param exclude_user_id: 若非空，排除该用户的记忆（与 include 二选一）
    :return: 行列表（content, user_id, type, last_accessed_at, importance, confidence）
    """
    if not RAG_ENABLED or not RAG_SQLITE_FTS_ENABLED:
        return []
    if not _ensure_fts_table(cursor):
        return []

    query_tokens = _segment_text(query)
    if not query_tokens:
        return []

    try:
        row = cursor.execute("SELECT COUNT(*) FROM memories_fts").fetchone()
        active_row = cursor.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()
        fts_count = int(row[0]) if row and row[0] is not None else 0
        active_count = int(active_row[0]) if active_row and active_row[0] is not None else 0
        if fts_count == 0 or fts_count != active_count:
            _rebuild_fts_index(cursor)

        query_sql = (
            "SELECT m.content, m.user_id, m.type, m.last_accessed_at, m.importance, m.confidence "
            "FROM memories_fts f "
            "JOIN memories m ON f.mem_id = m.id "
            "WHERE f.group_shared_space = ? AND m.status = 'active' "
        )
        params: list[Any] = [group_shared_space]
        if include_user_id is not None:
            query_sql += "AND m.user_id = ? "
            params.append(include_user_id)
        elif exclude_user_id is not None:
            query_sql += "AND m.user_id != ? "
            params.append(exclude_user_id)
        # 注意：bm25() 必须传 FTS 表真实名（不能用别名），否则会报 "no such column"
        query_sql += "AND f.content MATCH ? ORDER BY bm25(memories_fts) LIMIT ?"
        params.extend([query_tokens, limit])

        return cursor.execute(query_sql, tuple(params)).fetchall()
    except sqlite3.OperationalError:
        return []


def get_group_memories(
    group_shared_space: str,
    query: str | None = None,
    limit: int = PROACTIVE_LONG_TERM_LIMIT,
) -> list[dict[str, Any]]:
    """取某群组共享空间的活动记忆；若传入 query 则优先走 RAG 全文检索，无命中时回退加权排序。

    ``group_shared_space`` 为群组共享空间标识，由 ``config.spaces.resolve_space(qq_group_id)``
    得到；同一空间内的多个 QQ 群共享记忆。

    路径：
    1. 有 query 且 RAG 开 → _query_rag_results（取 max(limit, RAG_TOP_K) 候选）；
    2. FTS 无结果 → 回退从 memories 表按访问时间倒序取候选池
       （有 query 时放宽到 LONG_TERM_RELEVANCE_CANDIDATE_LIMIT），
       仍无 → 回退 long_term_memories（该表列名仍为 group_id，但写/查的都是空间标识）；
    3. 有 query → _rank_fallback_rows 在内存里按多维权重排序（群场景 user_id=0，不用用户相关性）；
       无 query → 直接按访问时间返回前 limit 条。

    :param group_shared_space: 群组共享空间标识（str）
    :param query: 查询关键词，可为 None（此时走纯时间倒序）
    :param limit: 返回条数上限
    :return: 记忆 dict 列表
    """
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    rows: list[tuple[Any, ...]] = []
    if query and RAG_ENABLED:
        rows = _query_rag_results(
            cursor,
            group_shared_space,
            query,
            max(limit, RAG_TOP_K),
            include_user_id=None,
            exclude_user_id=None,
        )
    if not rows:
        # 回退：抓取候选行时带上 importance / confidence，便于加权排序；
        # 有 query 时放宽候选池上限，再在内存里按权重精细化排序
        pool_limit = max(limit, LONG_TERM_RELEVANCE_CANDIDATE_LIMIT) if query else limit
        rows = _fetch_table(
            cursor,
            "SELECT content, user_id, type, last_accessed_at, importance, confidence FROM memories "
            "WHERE group_shared_space = ? AND status = 'active' ORDER BY last_accessed_at DESC LIMIT ?",
            (group_shared_space, pool_limit),
        )
        if not rows:
            # long_term_memories 是待废弃的旧兼容表：列名仍为 group_id，
            # 但值已按空间写入（见 M2.5-2），此处同样传空间标识。
            rows = _fetch_table(
                cursor,
                "SELECT summary, user_id, 'FACT', last_accessed_at, importance, 1.0 FROM long_term_memories "
                "WHERE group_id = ? ORDER BY rowid DESC LIMIT ?",
                (group_shared_space, pool_limit),
            )
    conn.close()
    if query and rows:
        # 用户在群记忆场景下不特指某个人，user_id 传 0（无需用户相关性加权）
        return _rank_fallback_rows(query, rows, user_id=0, limit=limit)
    return _memories_from_rows(rows[:limit])


def get_user_memories(
    group_shared_space: str,
    user_id: int,
    query: str | None = None,
    limit: int = REPLY_LONG_TERM_LIMIT,
) -> list[dict[str, Any]]:
    """取某用户在指定群组共享空间中的活动记忆（回复时使用），逻辑同 get_group_memories 但限定用户。

    ``group_shared_space`` 为群组共享空间标识，由 ``config.spaces.resolve_space(qq_group_id)``
    得到；同一空间内的多个 QQ 群共享记忆。

    区别：FTS 查询传 include_user_id=str(user_id)；回退 SQL 也会带 user_id 过滤；
    有 query 时最终用 _rank_fallback_rows 排序（此时 user_id 有实际意义，会加用户相关性分）。
    long_term_memories 兜底：列名仍为 group_id，但传的是空间标识。

    :param group_shared_space: 群组共享空间标识（str）
    :param user_id: 目标用户 ID
    :param query: 查询关键词，可为 None
    :param limit: 返回条数上限
    :return: 记忆 dict 列表
    """
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    rows: list[tuple[Any, ...]] = []
    if query and RAG_ENABLED:
        rows = _query_rag_results(
            cursor,
            group_shared_space,
            query,
            max(limit, RAG_TOP_K),
            include_user_id=str(user_id),
        )
    if not rows:
        pool_limit = max(limit, LONG_TERM_RELEVANCE_CANDIDATE_LIMIT) if query else limit
        rows = _fetch_table(
            cursor,
            "SELECT content, user_id, type, last_accessed_at, importance, confidence FROM memories "
            "WHERE group_shared_space = ? AND user_id = ? AND status = 'active' ORDER BY last_accessed_at DESC LIMIT ?",
            (group_shared_space, str(user_id), pool_limit),
        )
        if not rows:
            rows = _fetch_table(
                cursor,
                "SELECT summary, user_id, 'FACT', last_accessed_at, importance, 1.0 FROM long_term_memories "
                "WHERE group_id = ? AND user_id = ? ORDER BY rowid DESC LIMIT ?",
                (group_shared_space, str(user_id), pool_limit),
            )
    conn.close()
    if query and rows:
        return _rank_fallback_rows(query, rows, user_id=user_id, limit=limit)
    return _memories_from_rows(rows[:limit])


def get_related_memories(group_shared_space: str, user_id: int, query: str, limit: int = 3) -> list[dict[str, Any]]:
    """找"其他人"（排除 user_id 自己的）之中与 query 相关的记忆，返回给用作“你信她还说”的联想。

    ``group_shared_space`` 为群组共享空间标识，由 ``config.spaces.resolve_space(qq_group_id)``
    得到；同一空间内的多个 QQ 群共享记忆。

    前提：LONG_TERM_RELEVANCE_ENABLED 开启且 query 非空；
    流程：优先走 _query_rag_results（exclude_user_id=str(user_id)）用 bm25 拿结果；
    若无命中则抽取关键词、扫其他人记忆，在内存里用 _score_memory 打分后取前 limit 个，
    并把返回字典的 type 统一标记为 "RELATED"。
    long_term_memories 兜底：列名仍为 group_id，但传的是空间标识。

    :param group_shared_space: 群组共享空间标识（str）
    :param user_id: 当前用户（要排除的人）
    :param query: 查询文本
    :param limit: 返回条数上限
    :return: RELATED 记忆 dict 列表（不含 last_accessed_at）
    """
    if not DB_PATH.exists() or not LONG_TERM_RELEVANCE_ENABLED:
        return []
    if not query or not query.strip():
        return []

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    rag_rows = _query_rag_results(
        cursor,
        group_shared_space,
        query,
        max(limit, RAG_TOP_K),
        exclude_user_id=str(user_id),
    )
    if rag_rows:
        conn.close()
        return [
            {
                "content": row[0],
                "user_id": row[1],
                "type": row[2] if len(row) > 2 else "FACT",
                "importance": row[4] if len(row) > 4 else None,
                "confidence": row[5] if len(row) > 5 else None,
            }
            for row in rag_rows[:limit]
        ]

    keywords = _extract_keywords(query, LONG_TERM_RELEVANCE_KEYWORDS)
    if not keywords:
        conn.close()
        return []

    rows = _fetch_table(
        cursor,
        "SELECT content, user_id, type, last_accessed_at, importance, confidence FROM memories "
        "WHERE group_shared_space = ? AND user_id != ? AND status = 'active'",
        (group_shared_space, str(user_id)),
    )
    if not rows:
        rows = _fetch_table(
            cursor,
            "SELECT summary, user_id, 'FACT', CURRENT_TIMESTAMP, importance, confidence FROM long_term_memories "
            "WHERE group_id = ? AND user_id != ?",
            (group_shared_space, str(user_id)),
        )
    conn.close()

    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        content = row[0] or ""
        if not content:
            continue
        memory = {
            "content": content,
            "user_id": row[1],
            "type": row[2] if len(row) > 2 else "FACT",
            "last_accessed_at": row[3] if len(row) > 3 else None,
            "importance": row[4] if len(row) > 4 else None,
            "confidence": row[5] if len(row) > 5 else None,
        }
        score = _score_memory(query, memory, user_id)
        if score > 0:
            candidates.append((score, memory))

    candidates.sort(key=lambda item: item[0], reverse=True)
    ranked_memories = [
        {
            "content": memory["content"],
            "user_id": memory["user_id"],
            "type": "RELATED",
            "importance": memory.get("importance"),
            "confidence": memory.get("confidence"),
        }
        for _, memory in candidates[: LONG_TERM_RELEVANCE_CANDIDATE_LIMIT]
    ]
    return ranked_memories[:limit]
