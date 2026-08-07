from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from typing import Optional

from config import DB_PATH
from nonebot import logger
from memory.compressor import get_compressor


class MemoryManager:
    def __init__(self):
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(DB_PATH)

    def _ensure_tables(self) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_candidates (
                id TEXT PRIMARY KEY,
                group_id TEXT,
                user_id TEXT,
                type TEXT,
                content TEXT,
                importance REAL,
                confidence REAL,
                evidence TEXT,
                status TEXT,
                source_message_ids TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                group_id TEXT,
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
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS atomic_facts (
                id TEXT PRIMARY KEY,
                memory_id TEXT,
                group_id TEXT,
                subject TEXT,
                predicate TEXT,
                object TEXT,
                confidence REAL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 常用检索索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_group_user_status
            ON memories (group_id, user_id, status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_group_status_accessed
            ON memories (group_id, status, last_accessed_at)
        """)
        conn.commit()
        conn.close()

    def process_new_candidates(self) -> None:
        if not DB_PATH.exists():
            return
        conn = self._connect()
        cursor = conn.cursor()
        self._ensure_tables()

        candidates = cursor.execute(
            "SELECT id, group_id, user_id, type, content, importance, confidence, evidence, status, source_message_ids"
            " FROM memory_candidates WHERE status IN ('NEW', 'OBSERVING') ORDER BY created_at ASC"
        ).fetchall()

        promoted = False
        for row in candidates:
            candidate = {
                "id": row[0],
                "group_id": row[1],
                "user_id": row[2],
                "type": row[3] or "FACT",
                "content": row[4] or "",
                "importance": float(row[5] or 0.0),
                "confidence": float(row[6] or 0.0),
                "evidence": row[7] or "",
                "status": row[8] or "NEW",
                "source_message_ids": row[9] or "[]",
            }

            if candidate["confidence"] < 0.5 and candidate["importance"] < 0.5:
                cursor.execute(
                    "UPDATE memory_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    ("OBSERVING", candidate["id"]),
                )
                continue

            existing_id = self._find_similar_memory(cursor, candidate)
            if existing_id:
                self._merge_into_memory(cursor, existing_id, candidate)
            else:
                self._create_memory(cursor, candidate)

            cursor.execute(
                "UPDATE memory_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ("CONFIRMED", candidate["id"]),
            )
            # 只记录有晋升（CONFIRMED）的批次，用于提交后统一触发压缩
            promoted = True
        conn.commit()
        conn.close()

        # 提交并关闭连接后再触发压缩，避免对仍在写事务的连接产生 SQLite 锁冲突
        if promoted:
            try:
                # 轻量触发压缩（节流），避免每次都执行重度压缩
                get_compressor().maybe_compress(reason="candidate_processed")
            except Exception as e:
                logger.warning(f"🧹 [MemoryManager] 触发轻量压缩失败: {e}")

    def _find_similar_memory(self, cursor: sqlite3.Cursor, candidate: dict) -> Optional[str]:
        rows = cursor.execute(
            "SELECT id, content, type FROM memories WHERE status = 'active' AND type = ? ORDER BY last_accessed_at DESC",
            (candidate["type"],),
        ).fetchall()
        for mem_id, content, _ in rows:
            if self._is_similar(candidate["content"], content):
                return mem_id
        return None

    def _create_memory(self, cursor: sqlite3.Cursor, candidate: dict) -> None:
        memory_id = uuid.uuid4().hex
        cursor.execute(
            "INSERT OR IGNORE INTO memories ("
            "id, group_id, user_id, type, content, content_raw, importance, confidence, status, "
            "confirmation_count, last_confirmed_at, last_accessed_at, compressed_at, compression_version, is_atomized)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, 0, 0)",
            (
                memory_id,
                candidate["group_id"],
                candidate["user_id"],
                candidate["type"],
                candidate["content"],
                candidate["content"],
                candidate["importance"],
                candidate["confidence"],
                "active",
                1,
            ),
        )
        logger.info(f"🧠 [MemoryManager] 新增长期记忆 {memory_id} ({candidate['type']})")

    def _merge_into_memory(self, cursor: sqlite3.Cursor, memory_id: str, candidate: dict) -> None:
        row = cursor.execute(
            "SELECT content, content_raw, importance, confidence, confirmation_count FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if not row:
            return
        content, content_raw, importance, confidence, count = row
        merged_content = self._merge_content(content, candidate["content"])
        merged_content_raw = self._merge_content(content_raw or content, candidate["content"])
        merged_importance = max(importance or 0.0, candidate["importance"])
        merged_confidence = max(confidence or 0.0, candidate["confidence"])
        cursor.execute(
            "UPDATE memories SET content = ?, content_raw = ?, importance = ?, confidence = ?, "
            "confirmation_count = ?, last_confirmed_at = CURRENT_TIMESTAMP, last_accessed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (
                merged_content,
                merged_content_raw,
                merged_importance,
                merged_confidence,
                (count or 0) + 1,
                memory_id,
            ),
        )
        logger.info(f"🧠 [MemoryManager] 合并入已有记忆 {memory_id}")

    def _merge_content(self, old: str, new: str) -> str:
        old = old.strip()
        new = new.strip()
        if not old:
            return new
        if not new:
            return old
        if new in old:
            return old
        if old in new:
            return new
        return old + "；" + new

    def _normalize_text(self, text: str) -> str:
        text = (text or "").strip().lower()
        text = re.sub(r"[\W_]+", " ", text)
        return " ".join(text.split())

    def _is_similar(self, a: str, b: str) -> bool:
        if not a or not b:
            return False
        a_norm = self._normalize_text(a)
        b_norm = self._normalize_text(b)
        if not a_norm or not b_norm:
            return False
        if a_norm in b_norm or b_norm in a_norm:
            return True
        return self._jaccard_similarity(set(a_norm.split()), set(b_norm.split())) >= 0.65

    def _jaccard_similarity(self, a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        intersection = a & b
        union = a | b
        return len(intersection) / len(union)


_memory_manager_instance: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    global _memory_manager_instance
    if _memory_manager_instance is None:
        _memory_manager_instance = MemoryManager()
    return _memory_manager_instance
