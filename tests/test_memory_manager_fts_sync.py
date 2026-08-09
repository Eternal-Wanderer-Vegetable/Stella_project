# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""MemoryManager 与 SQLite FTS5 索引的“完全同步”测试。

保证 memory_manager 在晋升 / 合并记忆时，memories_fts 索引与 memories 表
保持一致（条数、内容都要对得上），并且新记忆开完 FTS 后能被 RAG 检索命中。
"""
import sqlite3
from pathlib import Path

import memory.memory_manager as memory_manager
import memory.retriever as retriever


def _dummy_compressor() -> object:
    return type("Dummy", (), {"maybe_compress": lambda self, reason=None: None})()


def _prepare_db(tmp_path: Path, monkeypatch, *, fts_enabled: bool = True) -> Path:
    """初始化临时数据库：建表 + 开关（RAG / FTS5）打点 + 返回 db 路径。"""
    db = tmp_path / "agent_memory.db"
    # MemoryManager 侧配置
    monkeypatch.setattr(memory_manager, "DB_PATH", db)
    monkeypatch.setattr(memory_manager, "get_compressor", _dummy_compressor)
    monkeypatch.setattr(memory_manager, "MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE", 0.5)
    monkeypatch.setattr(memory_manager, "MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE", 0.5)
    # retriever 侧配置（_upsert_fts_record / _query_rag_results 读取的是 retriever 模块全局量）
    monkeypatch.setattr(retriever, "DB_PATH", db)
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", fts_enabled)
    # 初始化表结构（memory_candidates / memories / memories_fts 由 MemoryManager 自动建）
    memory_manager.MemoryManager()
    return db


def _count(db: Path, sql: str, params: tuple = ()) -> int:
    """便捷查询：返回整数值；表不存在时视为 0。"""
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchone()[0]
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _seed_candidate(
    db: Path,
    cid: str,
    group: str,
    user: str,
    content: str,
    importance: float = 0.9,
    confidence: float = 0.9,
) -> None:
    """写入一条 NEW 状态候选记忆。"""
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO memory_candidates (id, group_id, user_id, type, content, importance, confidence, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (cid, group, user, "FACT", content, importance, confidence, "NEW"),
    )
    conn.commit()
    conn.close()


def test_fts_index_stays_in_sync_after_promotion(tmp_path, monkeypatch):
    """晋升后 memories_fts 行数必须与 active 记忆数一致，且可被 RAG 检索到。"""
    db = _prepare_db(tmp_path, monkeypatch)
    _seed_candidate(db, "c1", "1", "100", "用户100最近喜欢打羽毛球")

    memory_manager.MemoryManager().process_new_candidates()

    assert _count(db, "SELECT COUNT(*) FROM memories_fts") == 1
    assert _count(db, "SELECT COUNT(*) FROM memories WHERE status = 'active'") == 1

    results = retriever.get_group_memories(1, query="羽毛球", limit=5)
    assert len(results) == 1
    assert "羽毛球" in results[0]["content"]


def test_fts_index_sync_after_merge_updates_content(tmp_path, monkeypatch):
    """合并记忆后，FTS 索引应随最新合并内容整体更新（条数不变、内容可检索）。"""
    db = _prepare_db(tmp_path, monkeypatch)
    # 第一条候选晋升为用户 101 的记忆
    _seed_candidate(db, "c1", "1", "101", "用户101喜欢打羽毛球")
    memory_manager.MemoryManager().process_new_candidates()
    assert _count(db, "SELECT COUNT(*) FROM memories_fts") == 1

    # 第二条候选内容高度相似 → 合并进已有记忆，而不是新建
    _seed_candidate(db, "c2", "1", "101", "用户101喜欢打羽毛球和游泳")
    memory_manager.MemoryManager().process_new_candidates()

    # 仍是同一条记忆、同一索引行
    assert _count(db, "SELECT COUNT(*) FROM memories_fts") == 1
    assert _count(db, "SELECT COUNT(*) FROM memories WHERE status = 'active'") == 1

    # 合并后的内容应能被“游泳”检索命中
    results = retriever.get_group_memories(1, query="游泳", limit=5)
    assert results and "游泳" in results[0]["content"]


def test_fts_disabled_means_no_index_and_query_falls_back(tmp_path, monkeypatch):
    """关闭 RAG_SQLITE_FTS_ENABLED 后：不建 FTS 表、不写索引，检索走回退路径。"""
    db = _prepare_db(tmp_path, monkeypatch, fts_enabled=False)
    _seed_candidate(db, "c3", "2", "200", "用户200喜欢打网球")
    memory_manager.MemoryManager().process_new_candidates()

    # 没有 FTS 表
    assert _count(db, "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='memories_fts'") == 0

    # 检索（FTS 关闭 → 走内存回退排序）仍能返回该记忆
    results = retriever.get_user_memories(2, 200, query="网球", limit=5)
    assert results and "网球" in results[0]["content"]


def test_fts_rebuilds_when_index_is_stale(tmp_path, monkeypatch):
    """绕过 MemoryManager 直接插入的记忆（FTS 缺失/过期），查询时应自动全量重建。"""
    db = _prepare_db(tmp_path, monkeypatch, fts_enabled=True)
    # 手动写一条 memories 记录，但不走 MemoryManager（此时 FTS 为空 → 索引过期）
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance, confidence, status, confirmation_count) "
        "VALUES ('m_direct', '3', '300', 'FACT', '散步时路过了新开的羽毛球馆', '散步时路过了新开的羽毛球馆', 0.8, 0.9, 'active', 1)",
    )
    conn.commit()
    conn.close()

    assert _count(db, "SELECT COUNT(*) FROM memories_fts") == 0

    # 检索触发自动重建（fts_count(0) != active_count(1)）后命中
    results = retriever.get_group_memories(3, query="羽毛球馆", limit=5)
    assert len(results) == 1
    assert "羽毛球馆" in results[0]["content"]
    # 重建后 FTS 已补齐
    assert _count(db, "SELECT COUNT(*) FROM memories_fts") == 1
