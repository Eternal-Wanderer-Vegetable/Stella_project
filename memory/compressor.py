from __future__ import annotations

import sqlite3
import time
import re
import uuid
from pathlib import Path
from config import DB_PATH, PROJECT_ROOT, MEMORY_COMPRESS_LIGHT_THRESHOLD, MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS, MEMORY_COMPRESS_LOG_FILENAME
from nonebot import logger


class MemoryCompressor:
    def __init__(self):
        self._ensure_tables()
        # 轻量压缩的最小触发阈值（活动记忆数），可由配置覆盖
        self._light_threshold = MEMORY_COMPRESS_LIGHT_THRESHOLD
        # 轻量压缩最小间隔（秒）——避免频繁触发
        self._light_cooldown = MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS
        # 日志文件路径（项目根）
        self._log_path = Path(PROJECT_ROOT) / MEMORY_COMPRESS_LOG_FILENAME

    def _ensure_tables(self) -> None:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
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
        conn.commit()
        conn.close()
        # 统计表：记录每次压缩运行的汇总信息
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compressor_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT,
                reason TEXT,
                merged_count INTEGER,
                atomized_count INTEGER,
                archived_count INTEGER,
                run_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def run_weekly(self) -> None:
        logger.info("🧹 [MemoryCompressor] 开始周度全量压缩任务（重度运行）")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        self._ensure_tables()

        rows = cursor.execute(
            "SELECT id, group_id, user_id, type, content, importance, confidence, confirmation_count, compressed_at, is_atomized "
            "FROM memories WHERE status = 'active' ORDER BY last_accessed_at DESC"
        ).fetchall()
        if not rows:
            logger.info("🧹 [MemoryCompressor] 无可压缩的活动记忆")
            conn.close()
            return

        # 全量处理：去重、原子化并归档低价值记忆
        merged = self._merge_duplicate_memories(cursor, rows)
        atomized = self._atomize_long_memories(cursor, rows)
        archived = self._archive_low_value_memories(cursor)

        # 记录统计与日志
        conn.commit()
        cursor.execute(
            "INSERT INTO compressor_stats (run_type, reason, merged_count, atomized_count, archived_count) VALUES (?, ?, ?, ?, ?)",
            ("weekly", "scheduled", merged, atomized, archived),
        )
        conn.commit()
        conn.close()
        self._append_log(f"周度压缩：合并 {merged}，原子化 {atomized}，归档 {archived}")
        logger.info("🧹 [MemoryCompressor] 周度压缩完成")

    def maybe_compress(self, reason: str = "auto") -> None:
        """轻量化触发：基于活动记忆数量与冷却判断是否运行小规模压缩。
        用于频繁发生写入时的节流触发，避免每次都做重度压缩。
        """
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            self._ensure_tables()
            # 建表保存上次轻量运行时间
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS compressor_state (
                    k TEXT PRIMARY KEY,
                    v TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 读取上次轻量运行时间
            cursor.execute("SELECT v FROM compressor_state WHERE k = 'last_light_run'")
            row = cursor.fetchone()
            last_light = float(row[0]) if row and row[0] else 0.0

            # 统计活动记忆数
            cursor.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'")
            total_active = cursor.fetchone()[0]

            now = time.time()
            if total_active >= self._light_threshold and (now - last_light) >= self._light_cooldown:
                logger.info(f"🧹 [MemoryCompressor] 触发轻量压缩（原因={reason}，active={total_active}）")
                # 只对最近一部分进行轻量合并与原子化
                rows = cursor.execute(
                    "SELECT id, group_id, user_id, type, content, importance, confidence, confirmation_count, compressed_at, is_atomized "
                    "FROM memories WHERE status = 'active' ORDER BY last_accessed_at DESC LIMIT ?",
                    (self._light_threshold * 2,)
                ).fetchall()
                merged = self._merge_duplicate_memories(cursor, rows)
                atomized = self._atomize_long_memories(cursor, rows)
                # 记录轻量运行时间和统计
                cursor.execute("REPLACE INTO compressor_state (k, v, updated_at) VALUES ('last_light_run', ?, CURRENT_TIMESTAMP)", (str(now),))
                cursor.execute(
                    "INSERT INTO compressor_stats (run_type, reason, merged_count, atomized_count, archived_count) VALUES (?, ?, ?, ?, ?)",
                    ("light", reason, merged, atomized, 0),
                )
                conn.commit()
                self._append_log(f"轻量压缩（{reason}）：合并 {merged}，原子化 {atomized}（active={total_active}）")
            else:
                logger.debug(f"🧹 [MemoryCompressor] 轻量压缩跳过（active={total_active}, last_light={last_light}）")
            conn.close()
        except Exception as e:
            logger.warning(f"🧹 [MemoryCompressor] maybe_compress 失败: {e}")

    def _merge_duplicate_memories(self, cursor: sqlite3.Cursor, rows: list[tuple]) -> None:
        seen = set()
        memories = [
            {
                "id": row[0],
                "group_id": row[1],
                "user_id": row[2],
                "type": row[3],
                "content": row[4] or "",
                "importance": float(row[5] or 0.0),
                "confidence": float(row[6] or 0.0),
                "confirmation_count": int(row[7] or 0),
            }
            for row in rows
        ]
        for i, memory in enumerate(memories):
            if memory["id"] in seen:
                continue
            for other in memories[i + 1 :]:
                if other["id"] in seen:
                    continue
                if memory["group_id"] != other["group_id"] or memory["type"] != other["type"]:
                    continue
                if self._is_similar(memory["content"], other["content"]):
                    merged_content = self._merge_content(memory["content"], other["content"])
                    merged_importance = max(memory["importance"], other["importance"])
                    merged_confidence = max(memory["confidence"], other["confidence"])
                    merged_count = memory["confirmation_count"] + other["confirmation_count"]
                    cursor.execute(
                        "UPDATE memories SET content = ?, content_raw = ?, importance = ?, confidence = ?, "
                        "confirmation_count = ?, last_confirmed_at = CURRENT_TIMESTAMP, last_accessed_at = CURRENT_TIMESTAMP, "
                        "compressed_at = CURRENT_TIMESTAMP, compression_version = COALESCE(compression_version, 0) + 1, updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = ?",
                        (
                            merged_content,
                            merged_content,
                            merged_importance,
                            merged_confidence,
                            merged_count,
                            memory["id"],
                        ),
                    )
                    cursor.execute(
                        "UPDATE memories SET status = 'archived', updated_at = CURRENT_TIMESTAMP, compressed_at = CURRENT_TIMESTAMP "
                        "WHERE id = ?",
                        (other["id"],),
                    )
                    seen.add(other["id"])
                    logger.info(f"🧹 [MemoryCompressor] 合并并归档重复记忆 {other['id']} -> {memory['id']}")
        # 返回合并/归档的数量
        return len(seen)

    def _atomize_long_memories(self, cursor: sqlite3.Cursor, rows: list[tuple]) -> None:
        atomized_total = 0
        for row in rows:
            memory_id = row[0]
            group_id = row[1]
            user_id = row[2]
            content = row[4] or ""
            is_atomized = bool(row[9])
            if is_atomized or len(content) < 80:
                continue
            fragments = self._split_into_fragments(content)
            if not fragments:
                continue
            self._store_atomic_facts(cursor, memory_id, group_id, user_id, fragments)
            cursor.execute(
                "UPDATE memories SET is_atomized = 1, compressed_at = CURRENT_TIMESTAMP, compression_version = COALESCE(compression_version, 0) + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (memory_id,),
            )
            logger.info(f"🧹 [MemoryCompressor] 生成原子事实: {memory_id} ({len(fragments)} 条)")
            atomized_total += len(fragments)
        return atomized_total

    def _archive_low_value_memories(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            "UPDATE memories SET status = 'archived', compressed_at = CURRENT_TIMESTAMP, compression_version = COALESCE(compression_version, 0) + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'active' AND importance < 0.3 "
            "AND (last_accessed_at IS NULL OR julianday('now') - julianday(last_accessed_at) > 180)"
        )
        count = cursor.rowcount
        if count > 0:
            logger.info(f"🧹 [MemoryCompressor] 归档低价值记忆 {count} 条")
        return count

    def _split_into_fragments(self, text: str) -> list[str]:
        fragments = re.split(r"[。！？；;\n]+", text)
        fragments = [frag.strip() for frag in fragments if frag.strip()]
        atoms: list[str] = []
        for frag in fragments:
            if len(frag) <= 60:
                atoms.append(frag)
            else:
                for i in range(0, len(frag), 60):
                    atoms.append(frag[i : i + 60].strip())
        return [atom for atom in atoms if atom]

    def _store_atomic_facts(self, cursor: sqlite3.Cursor, memory_id: str, group_id: str, user_id: str, fragments: list[str]) -> None:
        inserted = 0
        for fragment in fragments:
            cursor.execute(
                "INSERT OR IGNORE INTO atomic_facts (id, memory_id, group_id, subject, predicate, object, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    memory_id,
                    group_id,
                    f"用户{user_id}" if user_id else f"群{group_id}",
                    "记忆片段",
                    fragment,
                    0.0,
                ),
            )
            inserted += 1
        return inserted

    def _append_log(self, text: str) -> None:
        try:
            header = f"\n## {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(header)
                f.write(text + "\n")
        except Exception as e:
            logger.warning(f"🧹 [MemoryCompressor] 写日志失败: {e}")

    # ---- 文本相似度与合并辅助 ----
    def _normalize_text(self, text: str) -> str:
        text = (text or "").strip().lower()
        text = re.sub(r"[\W_]+", " ", text)
        return " ".join(text.split())

    def _jaccard_similarity(self, a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        intersection = a & b
        union = a | b
        return len(intersection) / len(union)

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

    def _merge_content(self, old: str, new: str) -> str:
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


_compressor_instance: MemoryCompressor | None = None


def get_compressor() -> MemoryCompressor:
    global _compressor_instance
    if _compressor_instance is None:
        _compressor_instance = MemoryCompressor()
    return _compressor_instance
