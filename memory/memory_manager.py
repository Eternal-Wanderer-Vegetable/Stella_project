# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""
记忆经理（MemoryManager）模块。

本模块位于记忆工作流的“晋升侧”：消费整合器写入的 memory_candidates 候选，
按置信度/重要度打分决定进入「观察(OBSERVING)」等待进一步证据，还是立即晋升为长期记忆
（memories 表 + FTS 同步索引），并与已有相似记忆合并。

典型调用链（示例）：
    Consolidator 写出记忆候选 → process_new_candidates()
    → 低分候选标记为 OBSERVING（等待后续更多证据）
    → 高分候选：相似合并（_merge_into_memory）或新建（_create_memory）
    → 晋升批次提交后异步触发轻量压缩（避免 SQLite 写事务锁冲突）
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from typing import Optional

from config import (
    DB_PATH,
    MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE,
    MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE,
)
from nonebot import logger
from memory.compressor import get_compressor
from memory.retriever import _upsert_fts_record
from memory.schema import ensure_v2_schema


class MemoryManager:
    """记忆候选晋升为长期记忆的管理器。

    职责：
    - 读取 memory_candidates 中 NEW / OBSERVING 状态的候选；
    - 依据「置信度 + 重要度」双阈值决定候选取向（观察或晋升）；
    - 晋升时与已有相似记忆合并，避免重复记忆堆积；
    - 维护 memories 表与 FTS 全文索引的同步（_upsert_fts_record）。
    """

    def __init__(self):
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        """打开默认 SQLite 连接（DB_PATH）。"""
        return sqlite3.connect(DB_PATH)

    def _ensure_tables(self) -> None:
        """确保记忆相关表存在：memory_candidates（候选）、memories（长期记忆）、
        atomic_facts（原子事实，备用），并创建常用检索索引。"""
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
                usage_tags TEXT,
                visibility TEXT DEFAULT 'OPEN',
                trigger_data TEXT,
                behavior_rule TEXT,
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
                usage_tags TEXT,
                visibility TEXT DEFAULT 'OPEN',
                trigger_data TEXT,
                behavior_rule TEXT,
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
        # v2 记忆系统：基础表建好后，增量迁移补新字段/索引（幂等）
        try:
            ensure_v2_schema(DB_PATH)
        except Exception:
            pass

    def process_new_candidates(self) -> None:
        """处理全部待晋升的记忆候选（status ∈ {NEW, OBSERVING}），并把结果提交。

        关键逻辑：
        1. OBSERVING 判定：候选的置信度和重要度都低于阈值时，标记为 OBSERVING，
           等待后续批次带来更多证据，而不是直接晋升；
        2. 相似度合并：命中已有相似记忆则合并进入该记忆，否则新建记忆；
        3. 新旧都同步 FTS 索引；
        4. 提交后驱动轻量压缩（见注释）。
        副作用：修改 memory_candidates / memories / FTS 等表。
        """
        if not DB_PATH.exists():
            return
        conn = self._connect()
        cursor = conn.cursor()
        self._ensure_tables()

        # 按创建时间先后处理，避免同批候选间的顺序抖动
        candidates = cursor.execute(
            "SELECT id, group_id, user_id, type, content, importance, confidence, evidence, status, source_message_ids, usage_tags, visibility, behavior_rule"
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
                "usage_tags": row[10] or "[]",
                "visibility": row[11] or "OPEN",
                "behavior_rule": row[12] or "",
            }

            # OBSERVING 判定：双阈值都达不到时，暂不晋升，等更多证据
            if candidate["confidence"] < MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE and candidate["importance"] < MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE:
                cursor.execute(
                    "UPDATE memory_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    ("OBSERVING", candidate["id"]),
                )
                continue

            # 冲突解决（Conflict Resolution）：新候选与旧记忆矛盾时，标记旧记忆为 CONFLICT
            self._resolve_conflicts(cursor, candidate)

            # 相似度合并：与已有的活跃同类型记忆比对，相似则合并而非重复新建
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
        """在同类型、状态为 active 的记忆中查找与候选内容相似的记忆 id；找不到返回 None。"""
        rows = cursor.execute(
            "SELECT id, content, type FROM memories WHERE status = 'active' AND type = ? ORDER BY last_accessed_at DESC",
            (candidate["type"],),
        ).fetchall()
        for mem_id, content, _ in rows:
            if self._is_similar(candidate["content"], content):
                return mem_id
        return None

    def _create_memory(self, cursor: sqlite3.Cursor, candidate: dict) -> None:
        """新建长期记忆并同步写入 FTS 索引。内存记忆内容与原样都取 candidate.content。
        同时写入 v2 元字段（usage_tags / visibility / behavior_rule）。"""
        memory_id = uuid.uuid4().hex
        cursor.execute(
            "INSERT OR IGNORE INTO memories ("
            "id, group_id, user_id, type, content, content_raw, importance, confidence, status, "
            "confirmation_count, last_confirmed_at, last_accessed_at, compressed_at, compression_version, is_atomized, "
            "usage_tags, visibility, behavior_rule)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, 0, 0, ?, ?, ?)",
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
                candidate.get("usage_tags") or "[]",
                candidate.get("visibility") or "OPEN",
                candidate.get("behavior_rule") or "",
            ),
        )
        _upsert_fts_record(
            cursor,
            memory_id,
            str(candidate["group_id"]),
            str(candidate["user_id"]),
            candidate["content"],
        )
        logger.info(f"🧠 [MemoryManager] 新增长期记忆 {memory_id} ({candidate['type']})")

    def _merge_into_memory(self, cursor: sqlite3.Cursor, memory_id: str, candidate: dict) -> None:
        """把候选合并进已有记忆：合并内容块、重要度/置信度取最大值、累计确认次数，并同步 FTS。
        合并时同步吸收 v2 元字段（usage_tags 并集、behavior_rule 优先取候选值）。"""
        row = cursor.execute(
            "SELECT content, content_raw, importance, confidence, confirmation_count, usage_tags, visibility, behavior_rule FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if not row:
            return
        content, content_raw, importance, confidence, count = row[0], row[1], row[2], row[3], row[4]
        # 相似度合并：内容去重拼接（正文与原样都合并）
        merged_content = self._merge_content(content, candidate["content"])
        merged_content_raw = self._merge_content(content_raw or content, candidate["content"])
        # 合并时重要度/置信度取双方较大值，保留更强证据
        merged_importance = max(importance or 0.0, candidate["importance"])
        merged_confidence = max(confidence or 0.0, candidate["confidence"])
        # v2 元字段：usage_tags 取并集；behavior_rule 优先取候选值（候选更可能是边界规则）
        merged_usage = self._merge_usage_tags(row[5], candidate.get("usage_tags"))
        merged_visibility = self._merge_visibility(row[6], candidate.get("visibility"))
        merged_behavior = (candidate.get("behavior_rule") or "").strip() or (row[7] or "")
        cursor.execute(
            "UPDATE memories SET content = ?, content_raw = ?, importance = ?, confidence = ?, "
            "confirmation_count = ?, last_confirmed_at = CURRENT_TIMESTAMP, last_accessed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP, "
            "usage_tags = ?, visibility = ?, behavior_rule = ? "
            "WHERE id = ?",
            (
                merged_content,
                merged_content_raw,
                merged_importance,
                merged_confidence,
                (count or 0) + 1,
                merged_usage,
                merged_visibility,
                merged_behavior,
                memory_id,
            ),
        )
        # 合并后更新 FTS 索引，保证内容同步
        _upsert_fts_record(
            cursor,
            memory_id,
            str(candidate["group_id"]),
            str(candidate["user_id"]),
            merged_content,
        )
        logger.info(f"🧠 [MemoryManager] 合并入已有记忆 {memory_id}")

    @staticmethod
    def _merge_usage_tags(old: str, new) -> str:
        """合并两批 usage_tags（JSON 数组），取并集、去重、保序。"""
        import json as _json

        def _parse(value) -> list[str]:
            if isinstance(value, list):
                return [str(x).strip().upper() for x in value if str(x).strip()]
            try:
                parsed = _json.loads(value or "[]")
                return [str(x).strip().upper() for x in parsed if str(x).strip()]
            except (ValueError, TypeError):
                return []

        merged: list[str] = []
        for tag in _parse(old) + _parse(new):
            if tag not in merged:
                merged.append(tag)
        return _json.dumps(merged, ensure_ascii=False)

    @staticmethod
    def _merge_visibility(old, new) -> str:
        """合并可见性：候选若为更严格的 RESTRICTED/INTERNAL 则升级，否则保留旧值。"""
        from memory.policy import VISIBILITY_INTERNAL, VISIBILITY_RESTRICTED, parse_visibility

        old_vis = parse_visibility(old)
        new_vis = parse_visibility(new)
        order = {VISIBILITY_INTERNAL: 0, VISIBILITY_RESTRICTED: 1, "CONTEXTUAL": 2, "OPEN": 3}
        return new_vis if order.get(new_vis, 3) <= order.get(old_vis, 3) else old_vis

    def _resolve_conflicts(self, cursor: sqlite3.Cursor, candidate: dict) -> None:
        """冲突解决（Conflict Resolution）：检测候选是否与已有活跃记忆矛盾。

        矛盾判定：同用户、同类型，两者共享关键对象词，但情感极性相反
        （旧=肯定、新=否定，反之亦然）。若新候选置信度更高，旧记忆标记为
        CONFLICT（不再参与检索），新候选晋升；否则新候选压入 OBSERVING 等更多证据。
        """
        if not candidate["content"]:
            return
        rows = cursor.execute(
            "SELECT id, content, confidence FROM memories WHERE status = 'active' AND group_id = ? AND user_id = ? AND type = ?",
            (str(candidate["group_id"]), str(candidate["user_id"]), candidate["type"]),
        ).fetchall()
        for mem_id, old_content, old_confidence in rows:
            if not old_content or old_content == candidate["content"]:
                continue
            if self._detect_contradiction(old_content, candidate["content"]):
                old_conf = float(old_confidence or 0.0)
                if candidate["confidence"] >= old_conf:
                    cursor.execute(
                        "UPDATE memories SET status = 'conflict', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (mem_id,),
                    )
                    logger.info(f"⚔️ [MemoryManager] 候选与旧记忆冲突，旧记忆标记 CONFLICT: {mem_id}")
                else:
                    cursor.execute(
                        "UPDATE memory_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        ("OBSERVING", candidate["id"]),
                    )
                    logger.info("⚔️ [MemoryManager] 候选与旧记忆冲突但置信度更低，转为 OBSERVING")
                return

    @staticmethod
    def _detect_contradiction(a: str, b: str) -> bool:
        """启发式矛盾检测：两段内容共享关键词对象，但情感极性相反。"""
        negation = (
            "不喜欢", "不爱", "不想", "不常", "不愿意", "讨厌", "反感",
            "拒绝", "不再", "停止", "禁止", "没兴趣",
        )
        affirmation = ("喜欢", "爱玩", "常玩", "经常", "愿意", "想玩", "感兴趣", "好")

        def _polarity(text: str) -> int:
            if any(w in text for w in negation):
                return -1
            if any(w in text for w in affirmation):
                return 1
            return 0

        pa, pb = _polarity(a), _polarity(b)
        if pa == 0 or pb == 0 or pa == pb:
            return False
        # 共享对象词：两段内容中都出现过的 2~4 字片段
        common = MemoryManager._common_terms(a, b)
        return bool(common)

    @staticmethod
    def _common_terms(a: str, b: str, min_len: int = 2) -> set[str]:
        """提取两段文本共同的 2~4 字中文片段或英数词（用于判断是否谈论同一对象）。"""
        import re as _re

        def _segments(text: str) -> set[str]:
            segs = _re.findall(r"[\u4e00-\u9fff]{2,8}", text or "")
            out: set[str] = set()
            for seg in segs:
                if len(seg) <= 4:
                    out.add(seg)
                else:
                    for size in (2, 3, 4):
                        for i in range(len(seg) - size + 1):
                            out.add(seg[i : i + size])
            # 英数词（游戏名/型号等），如 Helldivers2 / RTX5080
            out.update(_re.findall(r"[a-zA-Z0-9]+", text or ""))
            return out

        return _segments(a) & _segments(b)

    def _merge_content(self, old: str, new: str) -> str:
        """合并两段内容：去空白；若一段包含另一段则取较长者，否则以「；」连接。"""
        old = old.strip()
        new = new.strip()
        if not old:
            return new
        if not new:
            return old
        # 新增内容已包含旧内容（或相反）时，不重复存储
        if new in old:
            return old
        if old in new:
            return new
        return old + "；" + new

    def _normalize_text(self, text: str) -> str:
        """文本归一化：小写、替换非字母数字字符为空格、去多余空白，供相似度比较。"""
        text = (text or "").strip().lower()
        text = re.sub(r"[\W_]+", " ", text)
        return " ".join(text.split())

    def _is_similar(self, a: str, b: str) -> bool:
        """判断两段内容是否语义相近：先做归一化，子串包含即相似，
        否则用 Jaccard 相似度 >=0.65 判定。"""
        if not a or not b:
            return False
        a_norm = self._normalize_text(a)
        b_norm = self._normalize_text(b)
        if not a_norm or not b_norm:
            return False
        # 归一化后短文本互相包含，视为同一记忆，直接返回相似
        if a_norm in b_norm or b_norm in a_norm:
            return True
        # 词集合的 Jaccard 相似度达到阈值即判定相似
        return self._jaccard_similarity(set(a_norm.split()), set(b_norm.split())) >= 0.65

    def _jaccard_similarity(self, a: set[str], b: set[str]) -> float:
        """计算两词集合的 Jaccard 相似度 = 交集大小 / 并集大小（任一方为空返回 0）。"""
        if not a or not b:
            return 0.0
        intersection = a & b
        union = a | b
        return len(intersection) / len(union)


_memory_manager_instance: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """返回进程级单例 MemoryManager（懒初始化）。"""
    global _memory_manager_instance
    if _memory_manager_instance is None:
        _memory_manager_instance = MemoryManager()
    return _memory_manager_instance
