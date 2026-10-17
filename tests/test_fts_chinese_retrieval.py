# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
r"""FTS 中文检索修复的回归测试（分词去整段 CJK token + MATCH OR + bm25）。

背景：_segment_text 曾用 ``\w+`` 补词，Python \w 含 CJK，整段连续中文被当成一个
token；两处查询侧把 token 空格连进 MATCH（FTS5 空格 = 隐式 AND），文档须含全部
token（含整段）→ 恒假 → 中文句子查询恒 0 命中，检索静默回退新鲜度排序，bm25 从未
生效（生产实证 101/101 例 0 行）。本文件钉住：

- 分词：中文只出滑窗片段，整段 CJK token 不再出现在索引词串/查询表达式里；
- MATCH 表达式：OR 连接、带引号防保留字、无空段、空查询返回空串；
- 端到端：自然中文句子查询经 _query_rag_results 与 retrieval_v2._query_fts 均能
  命中含相关词的记忆行——此前正是「静默 0 命中」的盲区。
"""
import sqlite3

import memory.retrieval_v2 as retrieval_v2
import memory.retriever as retriever

# ── 分词单元 ──────────────────────────────────────────────


def test_segment_text_chinese_emits_windows_without_whole_run_token():
    """中文查询的分词含滑窗片段、不含整段 CJK token（整段 token 是 AND 恒假的根因）。"""
    tokens = retriever._tokenize("有什么游戏推荐吗")
    assert "游戏" in tokens
    assert "推荐" in tokens
    assert "有什么游戏推荐吗" not in tokens
    # 8 字段滑窗：3/2 双档片段齐备，且保序去重
    assert "有什么" in tokens
    assert len(tokens) == len(set(tokens))
    # 写侧接口仍是空格连接的词串
    assert retriever._segment_text("有什么游戏推荐吗") == " ".join(tokens)


def test_segment_text_ascii_words_and_mixed_text():
    """非 CJK 词照常切出（\\w 语义去除 CJK），中英混查两侧都有 token。"""
    assert retriever._segment_text("hello world") == "hello world"
    tokens = retriever._tokenize("玩minecraft游戏")
    assert "minecraft" in tokens
    assert "游戏" in tokens
    # 数字同样保留（原 \w 行为的 ASCII 子集）
    assert "101" in retriever._tokenize("用户101住在杭州")


def test_match_expression_or_join_quoted_no_empty_segment():
    """MATCH 表达式：OR 连接、token 带引号、无空段。"""
    expression = retriever._match_expression("有什么游戏推荐吗")
    assert expression == " OR ".join(f'"{t}"' for t in retriever._tokenize("有什么游戏推荐吗"))
    assert "" not in expression.split(" OR ")
    assert expression.startswith('"') and expression.endswith('"')


def test_match_expression_reserved_keywords_are_quoted_terms():
    """查询含 AND/OR/NEAR 等保留字时被小写化为普通词并带引号，不构成语法成分。"""
    expression = retriever._match_expression("游戏 OR 推荐")
    assert '"游戏"' in expression and '"推荐"' in expression
    # 裸 OR/AND/NEAR 会让 MATCH 直接 fts5 syntax error；引号化后是合法 term
    assert retriever._match_expression("OR AND NEAR") == '"or" OR "and" OR "near"'


def test_match_expression_empty_or_punctuation_only_returns_empty():
    """空查询 / 纯标点 → 空串（调用方跳过 MATCH，避免 fts5 syntax error）。"""
    assert retriever._match_expression("") == ""
    assert retriever._match_expression("！！！???") == ""
    assert retriever._match_expression("   ") == ""


# ── 集成：内存 FTS5 双路径中文召回 ────────────────────────


def _prepare_mem_db(conn: sqlite3.Connection, rows: list[tuple[str, str]]) -> None:
    """建 memories（含 v2 列）+ memories_fts，写入用例行并按生产分词灌索引。"""
    conn.execute(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            group_shared_space TEXT,
            user_id TEXT,
            type TEXT,
            content TEXT,
            content_raw TEXT,
            importance REAL,
            confidence REAL,
            status TEXT,
            confirmation_count INTEGER,
            last_confirmed_at DATETIME,
            last_accessed_at DATETIME,
            compressed_at DATETIME,
            compression_version INTEGER,
            is_atomized INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            usage_tags TEXT,
            visibility TEXT,
            trigger_data TEXT,
            behavior_rule TEXT
        )
        """
    )
    conn.execute(
        "CREATE VIRTUAL TABLE memories_fts USING fts5("
        "mem_id UNINDEXED, content, group_shared_space UNINDEXED, user_id UNINDEXED)"
    )
    for mid, content in rows:
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content, content_raw,"
            " importance, confidence, status, confirmation_count, last_accessed_at)"
            " VALUES (?, 'space_a', '100', 'FACT', ?, ?, 0.8, 0.9, 'active', 1,"
            " '2026-10-01 10:00:00')",
            (mid, content, content),
        )
        conn.execute(
            "INSERT INTO memories_fts (mem_id, content, group_shared_space, user_id)"
            " VALUES (?, ?, 'space_a', '100')",
            (mid, retriever._segment_text(content)),
        )
    conn.commit()


def test_query_rag_results_recalls_chinese_sentence(tmp_path, monkeypatch):
    """自然中文句子查询经 _query_rag_results 命中含相关词的记忆（此前恒 0 命中）。"""
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    conn = sqlite3.connect(":memory:")
    _prepare_mem_db(conn, [("m1", "推荐几款游戏")])

    rows = retriever._query_rag_results(conn.cursor(), "space_a", "有什么游戏推荐吗", limit=5)
    assert [r[0] for r in rows] == ["推荐几款游戏"]
    conn.close()


def test_query_fts_recalls_chinese_sentence(monkeypatch):
    """retrieval_v2._query_fts 用 _match_expression 同样命中（生产主路候选池）。"""
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    conn = sqlite3.connect(":memory:")
    _prepare_mem_db(conn, [("m1", "推荐几款游戏")])

    rows = retrieval_v2._query_fts(
        conn.cursor(), "space_a", None, "有什么游戏推荐吗", 5, "CASUAL_REPLY"
    )
    assert [r[4] for r in rows] == ["推荐几款游戏"]
    conn.close()


def test_bm25_orders_multi_term_hits_first(monkeypatch):
    """OR 召回多条时，命中更多查询词的文档应排在前（bm25 默认权重的可用性检查）。"""
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    conn = sqlite3.connect(":memory:")
    _prepare_mem_db(
        conn,
        [
            ("m_partial", "游戏机维修店"),  # 只命中「游戏」
            ("m_full", "推荐几款游戏"),  # 命中「游戏」「推荐」
        ],
    )

    rows = retriever._query_rag_results(conn.cursor(), "space_a", "有什么游戏推荐吗", limit=5)
    assert [r[0] for r in rows] == ["推荐几款游戏", "游戏机维修店"]
    conn.close()


def test_fts_hits_do_not_narrow_candidate_pool(monkeypatch):
    """FTS 命中不窄化候选池：不匹配查询词的记忆仍在候选里（并集语义）。

    只保留 FTS 行时池里只剩「恰与查询共享分词片段」的记忆，竞争者变少后
    旧值/干扰项更容易穿过下游 LIMIT 截断与分数门槛（基准 temporal/conflict
    用例 forbidden 硬零被破的根因）。
    """
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    conn = sqlite3.connect(":memory:")
    _prepare_mem_db(conn, [("m1", "推荐几款游戏"), ("m2", "今天天气不错")])

    rows = retriever._query_rag_results(conn.cursor(), "space_a", "有什么游戏推荐吗", limit=5)
    contents = [r[0] for r in rows]
    assert contents[0] == "推荐几款游戏"  # FTS 命中领跑
    assert "今天天气不错" in contents  # 池不窄化：新鲜度头部兜底并入
    conn.close()


def test_fetch_candidates_unions_fts_with_recency_pool(monkeypatch):
    """retrieval_v2._fetch_candidates 同样并集：FTS 行在前、新鲜度头部去重并入。"""
    import memory.retrieval_v2 as v2

    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    monkeypatch.setattr(v2, "RAG_ENABLED", True)
    conn = sqlite3.connect(":memory:")
    _prepare_mem_db(conn, [("m1", "推荐几款游戏"), ("m2", "今天天气不错")])

    candidates = v2._fetch_candidates(
        conn.cursor(), "space_a", None, "CASUAL_REPLY", "有什么游戏推荐吗", 20
    )
    ids = [m["id"] for m in candidates]
    assert ids[0] == "m1"
    assert "m2" in ids
    conn.close()


def test_match_expression_with_keywords_does_not_break_match(monkeypatch):
    """保留字查询（裸 AND/OR/NEAR 词形）经引号化后可安全执行，不再 fts5 syntax error。"""
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    conn = sqlite3.connect(":memory:")
    _prepare_mem_db(conn, [("m1", "推荐几款游戏")])

    # 修复前这类表达式直接抛 OperationalError（被吞成静默 0 命中）
    rows = retriever._query_rag_results(conn.cursor(), "space_a", "游戏 AND OR NEAR", limit=5)
    assert [r[0] for r in rows] == ["推荐几款游戏"]
    conn.close()


def test_punctuation_only_query_skips_match(monkeypatch):
    """纯标点查询：表达式为空 → 直接返回空，不进 MATCH（降级路径接手）。"""
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    conn = sqlite3.connect(":memory:")
    _prepare_mem_db(conn, [("m1", "推荐几款游戏")])

    assert retriever._query_rag_results(conn.cursor(), "space_a", "！！！???", limit=5) == []
    assert (
        retrieval_v2._query_fts(conn.cursor(), "space_a", None, "？？？", 5, "CASUAL_REPLY")
        == []
    )
    conn.close()


def test_fts_unavailable_degrades_to_empty(monkeypatch):
    """FTS5 不可用（建表失败）→ 两查询点返回空，异常不穿透调用方。"""
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    monkeypatch.setattr(retriever, "_ensure_fts_table", lambda cursor: False)
    conn = sqlite3.connect(":memory:")
    _prepare_mem_db(conn, [("m1", "推荐几款游戏")])

    assert retriever._query_rag_results(conn.cursor(), "space_a", "游戏", limit=5) == []
    assert (
        retrieval_v2._query_fts(conn.cursor(), "space_a", None, "游戏", 5, "CASUAL_REPLY") == []
    )
    conn.close()
