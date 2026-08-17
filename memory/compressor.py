# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""长期记忆压缩器（memory.compressor）。

负责把 memories 表里冗余/超长/低价值的内容做收敛处理，包含三类动作：
1. 去重合并 _merge_duplicate_memories：内容相似（Jaccard ≥ 0.65 或互为子串）的记忆
   合并成一条，保留更高的重要度/置信度、累加确认次数，被合并方标记为 archived；
2. 原子化 _atomize_long_memories：把超过 80 字的记忆拆成若干“原子事实”
   写入 atomic_facts 表（见 _split_into_fragments / _store_atomic_facts），原记忆打上 is_atomized=1；
3. 低价值归档 _archive_low_value_memories：importance 低于阈值 且 长时间未访问（或从未访问）
   的记忆批量转为 archived（不删除，只是不再参与 active 检索）。

触发入口：
- run_weekly()：周度全量压缩（合并 + 原子化 + 归档全部跑），由定时任务调用；
- maybe_compress(reason)：轻量压缩——仅在活动记忆数达到阈值、距上次轻量压缩超过冷却期时，
  对最近 2×阈值 条记录做合并与原子化（不归档），用于频繁写库时节的节流。

统计与日志：每次运行会把 merged/atomized/archived 数量记入 compressor_stats，并追加一条人类可读日志。
注意：所有操作都发生在调用方传入的同一连接/事务里，由调用方 commit（轻量/周度流程各自 commit）。
"""

from __future__ import annotations

import re
import sqlite3
import time
import uuid
from pathlib import Path

from nonebot import logger

from config import (
    DB_PATH,
    MEMORY_ARCHIVE_IMPORTANCE_THRESHOLD,
    MEMORY_ARCHIVE_INACTIVE_DAYS,
    MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS,
    MEMORY_COMPRESS_LIGHT_THRESHOLD,
    MEMORY_COMPRESS_LOG_FILENAME,
    MEMORY_DECAY_DAYS,
    PROJECT_ROOT,
)
from memory.schema import create_memories_table
from memory.text_similarity import is_similar, merge_content


class MemoryCompressor:
    """记忆压缩器：把冗余记忆合并、长记忆原子化、低价值记忆归档。"""

    def __init__(self):
        # 保证数据表存在后再开始，避免 create 失败导致后续 SQL 直接报错
        self._ensure_tables()
        # 轻量压缩的最小触发阈值（活动记忆数），可由配置覆盖
        self._light_threshold = MEMORY_COMPRESS_LIGHT_THRESHOLD
        # 轻量压缩最小间隔（秒）——避免频繁触发
        self._light_cooldown = MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS
        # 日志文件路径（项目根）
        self._log_path = Path(PROJECT_ROOT) / MEMORY_COMPRESS_LOG_FILENAME

    def _ensure_tables(self) -> None:
        """幂等地创建压缩用表：memories（主记忆表，复用 schema 规范 DDL）与 compressor_stats（压缩统计表）。"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        create_memories_table(conn)
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
        """周度全量压缩（重度运行）：合并 + 原子化 + 归档三管齐下，并记录统计与日志。

        对 status='active' 的全部记忆排序后依次执行三步，最后把步进数字写入
        compressor_stats 并追加一条人类可读日志；无活动记忆时提前退出。
        """
        logger.info("🧹 [MemoryCompressor] 开始周度全量压缩任务（重度运行）")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        self._ensure_tables()

        rows = cursor.execute(
            "SELECT id, group_shared_space, user_id, type, content, importance, confidence, confirmation_count, compressed_at, is_atomized "
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
        decayed = self._apply_decay(cursor)

        # 记录统计与日志
        conn.commit()
        cursor.execute(
            "INSERT INTO compressor_stats (run_type, reason, merged_count, atomized_count, archived_count) VALUES (?, ?, ?, ?, ?)",
            ("weekly", "scheduled", merged, atomized, archived),
        )
        conn.commit()
        conn.close()
        self._append_log(f"周度压缩：合并 {merged}，原子化 {atomized}，归档 {archived}，衰减 {decayed}")
        logger.info("🧹 [MemoryCompressor] 周度压缩完成")

    def maybe_compress(self, reason: str = "auto") -> None:
        """轻量化触发：基于活动记忆数量与冷却判断是否运行小规模压缩。
        用于频繁发生写入时的节流触发，避免每次都做重度压缩。

        触发条件（同时满足）：active 记忆数 ≥ 阈值，且距上次轻量运行 ≥ 冷却期。
        只取最近 2×阈值 条记录做合并/原子化（不做归档），写完更新 last_light_run 时间戳。
        整个流程被 try/except 包裹，任何失败只记录 warning，不影响调用方。
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
                    "SELECT id, group_shared_space, user_id, type, content, importance, confidence, confirmation_count, compressed_at, is_atomized "
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

    def _merge_duplicate_memories(self, cursor: sqlite3.Cursor, rows: list[tuple]) -> int:
        """把内容相似（同空间同用户同类型 + _is_similar）的记忆合并成一条，被合并方转 archived。

        合并规则：content 用 _merge_content（保留更完整一方或分号拼接）；
        importance/confidence 取两者更大值；confirmation_count 累加（体现“多人/多次确认更可信”）；
        存活方只更新字段、被合并方的 status 置为 'archived'（不删除，仅使其退出检索）。
        返回被归档（合并掉）的记忆条数，供统计用。

        :param cursor: 已连接的数据库游标（写操作由调用方统一 commit）
        :param rows: 待检查的记忆行（含 id, content, importance, confidence, confirmation_count 等）
        :return: 被归档的记忆条数
        """
        seen = set()
        memories = [
            {
                "id": row[0],
                "group_shared_space": row[1],
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
                # 必须同空间 + 同用户 + 同类型才允许合并。跨用户合并会把 A 的事实
                # 并入 B 的记忆并把 A 那条置 archived，且发生在周度定时任务里，
                # 数据不可恢复（与 memory_manager._find_similar_memory 的约束一致）。
                if (
                    memory["group_shared_space"] != other["group_shared_space"]
                    or memory["user_id"] != other["user_id"]
                    or memory["type"] != other["type"]
                ):
                    continue
                if is_similar(memory["content"], other["content"]):
                    merged_content = merge_content(memory["content"], other["content"])
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

    def _atomize_long_memories(self, cursor: sqlite3.Cursor, rows: list[tuple]) -> int:
        """把长度 ≥ 80 字、尚未原子化（is_atomized=0）的记忆拆成“原子事实”。

        对每行用 _split_into_fragments 切成片段，写入 atomic_facts 表
        （INSERT OR IGNORE，以 uuid 作主键防重），随后把原记忆标记 is_atomized=1
        并递增 compression_version，避免下次再切。返回新生成的原子事实条数。

        :param cursor: 数据库游标
        :param rows: 待处理的记忆行（含 id, group_shared_space, user_id, content, is_atomized）
        :return: 本次产生的新原子事实总数
        """
        atomized_total = 0
        for row in rows:
            memory_id = row[0]
            group_shared_space = row[1]
            user_id = row[2]
            content = row[4] or ""
            is_atomized = bool(row[9])
            if is_atomized or len(content) < 80:
                continue
            fragments = self._split_into_fragments(content)
            if not fragments:
                continue
            self._store_atomic_facts(cursor, memory_id, group_shared_space, user_id, fragments)
            cursor.execute(
                "UPDATE memories SET is_atomized = 1, compressed_at = CURRENT_TIMESTAMP, compression_version = COALESCE(compression_version, 0) + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (memory_id,),
            )
            logger.info(f"🧹 [MemoryCompressor] 生成原子事实: {memory_id} ({len(fragments)} 条)")
            atomized_total += len(fragments)
        return atomized_total

    def _archive_low_value_memories(self, cursor: sqlite3.Cursor) -> int:
        """把“重要度低 且 长期未访问（或从未访问）”的记忆归档（status='archived'）。

        条件：importance < MEMORY_ARCHIVE_IMPORTANCE_THRESHOLD，
        且 (last_accessed_at 为空 或 距今超过 MEMORY_ARCHIVE_INACTIVE_DAYS 天)。
        归档不删数据，只是让这些记忆退出 active 检索；返回受影响行数（cursor.rowcount）。

        :param cursor: 数据库游标
        :return: 被归档的记忆条数
        """
        cursor.execute(
            "UPDATE memories SET status = 'archived', compressed_at = CURRENT_TIMESTAMP, compression_version = COALESCE(compression_version, 0) + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'active' AND importance < ? "
            "AND (last_accessed_at IS NULL OR julianday('now') - julianday(last_accessed_at) > ?)",
            (
                MEMORY_ARCHIVE_IMPORTANCE_THRESHOLD,
                MEMORY_ARCHIVE_INACTIVE_DAYS,
            ),
        )
        count = cursor.rowcount
        if count > 0:
            logger.info(f"🧹 [MemoryCompressor] 归档低价值记忆 {count} 条")
        return count

    def _apply_decay(self, cursor: sqlite3.Cursor) -> int:
        """按记忆类型生命周期做衰减归档（Memory Decay）。

        每种类型有不同的“保质期”（见 MEMORY_DECAY_DAYS）：
        FACT 极慢 → STYLE 慢 → PREFERENCE/RELATION 中 → EVENT/PLAN 快 → GROUP_CONTEXT 很快。
        超过类型生命周期且近期未访问的记忆，转为 archived（不删除，只退出检索）。
        """
        total = 0
        for mem_type, max_days in MEMORY_DECAY_DAYS.items():
            cursor.execute(
                "UPDATE memories SET status = 'archived', compressed_at = CURRENT_TIMESTAMP, "
                "compression_version = COALESCE(compression_version, 0) + 1, updated_at = CURRENT_TIMESTAMP "
                "WHERE status = 'active' AND type = ? "
                "AND (last_accessed_at IS NULL OR julianday('now') - julianday(last_accessed_at) > ?)",
                (mem_type, max_days),
            )
            total += cursor.rowcount
        if total > 0:
            logger.info(f"🧹 [MemoryCompressor] 按类型生命周期衰减归档 {total} 条")
        return total

    def _split_into_fragments(self, text: str) -> list[str]:
        """把一段长文本切成“原子事实”候选片段。

        先按句末标点（。！？；; 与换行）切开，随即去掉空白块；
        超过 60 字的块再按 60 字滑窗切成小段，保证每条片段可独立入库。

        :param text: 待切分文本
        :return: 非空原子片段列表；输入为空返回空列表
        """
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

    def _store_atomic_facts(self, cursor: sqlite3.Cursor, memory_id: str, group_shared_space: str, user_id: str, fragments: list[str]) -> int:
        """把原子片段逐条写入 atomic_facts 表（INSERT OR IGNORE，靠随机 uuid 主键防重）。

        subject 取“用户{user_id}”或“空间{group_shared_space}”（无 user_id 时用空间标识），
        predicate 固定为“记忆片段”，object 为片段文本，confidence 初始为 0。
        返回尝试插入的条数（注意 OR IGNORE 条件下实际落库数可能更少）。

        :param cursor: 数据库游标
        :param memory_id: 来源记忆的 id
        :param group_shared_space: 空间标识
        :param user_id: 用户 ID（可为空）
        :param fragments: 原子片段列表
        :return: 尝试写入的片段数量
        """
        inserted = 0
        for fragment in fragments:
            cursor.execute(
                "INSERT OR IGNORE INTO atomic_facts (id, memory_id, group_shared_space, subject, predicate, object, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    memory_id,
                    group_shared_space,
                    f"用户{user_id}" if user_id else f"空间{group_shared_space}",
                    "记忆片段",
                    fragment,
                    0.0,
                ),
            )
            inserted += 1
        return inserted

    def _append_log(self, text: str) -> None:
        """把一行压缩摘要追加到 _log_path 对应的日志文件（带时间标题）。

        自动创建父目录，写入失败仅记录 warning 不抛出（不干扰压缩主流程）。

        :param text: 要追加的人类可读摘要
        :return: None
        """
        try:
            header = f"\n## {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(header)
                f.write(text + "\n")
        except Exception as e:
            logger.warning(f"🧹 [MemoryCompressor] 写日志失败: {e}")


_compressor_instance: MemoryCompressor | None = None


def get_compressor() -> MemoryCompressor:
    """返回全局唯一的 MemoryCompressor 实例（懒加载单例），供各模块复用。"""
    global _compressor_instance
    if _compressor_instance is None:
        _compressor_instance = MemoryCompressor()
    return _compressor_instance
