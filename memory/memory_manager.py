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

import contextlib
import json
import sqlite3
import uuid

from nonebot import logger

from config import (
    DB_PATH,
    MEMORY_CANDIDATE_MAX_OBSERVING_DAYS,
    MEMORY_CONFIRM_HIGH_CONFIDENCE,
    MEMORY_OBSERVE_LOW_CONFIDENCE,
    MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT,
    MEMORY_PROMOTE_MIN_IMPORTANCE,
    MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE,
    MEMORY_QUOTA_CONFIRMATION_CAP,
    MEMORY_QUOTA_ENFORCE,
    MEMORY_QUOTA_W_CONFIRMATION,
    MEMORY_QUOTA_W_IMPORTANCE,
    MEMORY_QUOTA_W_RECENCY,
    MEMORY_USER_QUOTA,
)
from memory.compressor import get_compressor
from memory.retriever import _upsert_fts_record
from memory.schema import (
    create_atomic_facts_table,
    create_memories_table,
    create_memory_candidates_table,
    ensure_v2_schema,
)
from memory.text_similarity import is_similar, merge_content


class MemoryManager:
    """记忆候选晋升为长期记忆的管理器。

    职责：
    - 读取 memory_candidates 中 NEW / OBSERVING 状态的候选；
    - 依据 Gate 1 三档（置信度 × 证据充分度）决定候选取向（观察 / 晋升 / 超期淘汰）；
    - 晋升时与已有相似记忆合并，避免重复记忆堆积；
    - 维护 memories 表与 FTS 全文索引的同步（_upsert_fts_record）。
    - 维护每用户记忆配额（MEMORY_USER_QUOTA）：超额时竞争性淘汰最弱记忆。
    """

    def __init__(self):
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        """打开默认 SQLite 连接（DB_PATH）。"""
        return sqlite3.connect(DB_PATH)

    def _ensure_tables(self) -> None:
        """确保记忆相关表存在：memory_candidates（候选）、memories（长期记忆）、
        atomic_facts（原子事实，备用），并创建常用检索索引。

        v8 起统一复用 schema 规范 DDL（group_shared_space 归属），
        不再手抄一份建表语句。
        """
        conn = self._connect()
        cursor = conn.cursor()
        create_memory_candidates_table(conn)
        create_memories_table(conn)
        create_atomic_facts_table(conn)
        # 常用检索索引（memories 按空间维度）
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_space_user_status
            ON memories (group_shared_space, user_id, status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_space_status_accessed
            ON memories (group_shared_space, status, last_accessed_at)
        """)
        conn.commit()
        conn.close()
        # v2 记忆系统：基础表建好后，增量迁移补新字段/索引（幂等）
        with contextlib.suppress(Exception):
            ensure_v2_schema(DB_PATH)

    def process_new_candidates(self) -> None:
        """处理全部待晋升的记忆候选（status ∈ {NEW, OBSERVING}），并把结果提交。

        关键逻辑：
        1. Gate 1 三档判定：先淘汰超期 OBSERVING 候选，再按置信度 × 证据充分度
           （来源等级 / 复现次数）决定观察或晋升；
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

        # 先淘汰超期候选，避免它们参与本轮评估
        self._reject_stale_candidates(cursor)

        # 按创建时间先后处理，避免同批候选间的顺序抖动
        candidates = cursor.execute(
            "SELECT id, group_shared_space, user_id, type, content, importance, confidence, evidence, status, "
            "source_message_ids, usage_tags, visibility, behavior_rule, "
            "occurrence_count, source_kinds, source_kind, origin_group_id"
            " FROM memory_candidates WHERE status IN ('NEW', 'OBSERVING') ORDER BY created_at ASC"
        ).fetchall()

        promoted = False
        for row in candidates:
            candidate = {
                "id": row[0],
                "group_shared_space": row[1],
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
                "occurrence_count": int(row[13] or 1),
                "source_kinds": row[14] or '["PASSIVE"]',
                "source_kind": row[15] or "PASSIVE",
            }

            # ── Gate 1 三档判定：置信度 + 证据充分度（来源等级 / 复现次数） ──
            should_promote, reason = self._decide_promotion(candidate)
            if not should_promote:
                cursor.execute(
                    "UPDATE memory_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    ("OBSERVING", candidate["id"]),
                )
                logger.debug(
                    f"👀 [MemoryManager] 候选转 OBSERVING {candidate['id']}：{reason}"
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
                # 新建才可能突破配额；合并不增加条数
                self._enforce_user_quota(
                    cursor, candidate["group_shared_space"], candidate["user_id"]
                )

            logger.info(f"⬆️ [MemoryManager] 候选晋升 {candidate['id']}：{reason}")

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

    @staticmethod
    def _has_at_mention(source_kinds: str | None) -> bool:
        """历次证据中是否包含 AT_MENTION（用户直接对 Bot 说过）。

        看的是 source_kinds（历次来源集合）而非 source_kind（最近一次）：
        一条事实先在群聊被动提到、后来用户又直接确认过，那次直接确认
        不应因为后续又有被动观察而失效。
        """
        try:
            kinds = json.loads(source_kinds or "[]")
        except (ValueError, TypeError):
            return False
        return isinstance(kinds, list) and any(
            str(k).strip().upper() == "AT_MENTION" for k in kinds
        )

    @staticmethod
    def _decide_promotion(candidate: dict) -> tuple[bool, str]:
        """Gate 1 三档判定：返回 (是否晋升, 原因说明)。

        档位（依据 Memory Consolidation Spec 的 Gate 1）：
          conf >= HIGH(0.85)  → 晋升。用户明确直接陈述，无需额外佐证。
          conf >= LOW(0.6)    → 看证据充分度：
                                  历次来源含 AT_MENTION 且开关开 → 晋升（高密度证据）
                                  occurrence_count >= MIN_OCCURRENCE_PASSIVE → 晋升（交叉验证通过）
                                  否则 → OBSERVING，等复现
          conf <  LOW(0.6)    → OBSERVING。置信度不足，无论来源都要等更多证据。

        另设 importance 下限：低于 MEMORY_PROMOTE_MIN_IMPORTANCE 的候选一律
        不晋升（过于琐碎），但仍保留在 OBSERVING 中等待——它可能后续被证明重要。

        与旧逻辑的区别：旧判定为 `conf < 0.5 AND imp < 0.5` 才观察，即
        importance 单独达标就能晋升。importance 是 LLM 自评、最不可靠的一项，
        不应单独构成晋升依据。
        """
        conf = candidate["confidence"]
        imp = candidate["importance"]
        occurrence = candidate["occurrence_count"]

        if imp < MEMORY_PROMOTE_MIN_IMPORTANCE:
            return False, f"重要度不足（imp={imp:.2f} < {MEMORY_PROMOTE_MIN_IMPORTANCE}）"

        if conf >= MEMORY_CONFIRM_HIGH_CONFIDENCE:
            return True, f"高置信直接晋升（conf={conf:.2f}）"

        if conf >= MEMORY_OBSERVE_LOW_CONFIDENCE:
            if MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT and MemoryManager._has_at_mention(
                candidate["source_kinds"]
            ):
                return True, f"AT_MENTION 高密度证据单次晋升（conf={conf:.2f}）"
            if occurrence >= MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE:
                return True, f"交叉验证通过（conf={conf:.2f}，观察 {occurrence} 次）"
            return False, (
                f"置信度中等但证据不足（conf={conf:.2f}，观察 {occurrence} 次 < "
                f"{MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE}，无 AT_MENTION）"
            )

        return False, f"置信度不足（conf={conf:.2f} < {MEMORY_OBSERVE_LOW_CONFIDENCE}）"

    def _reject_stale_candidates(self, cursor: sqlite3.Cursor) -> int:
        """把超期未获新证据的 OBSERVING 候选标记为 REJECTED（不删除，保留供审计）。

        没有这一步，OBSERVING 会变成只进不出的死胡同：一条永远等不到复现的
        候选会被无限次重新评估、反复失败，把候选表堆大并拖慢每轮晋升。
        以 first_seen_at 为锚点（不是 updated_at，后者每次复现都会刷新）。
        """
        cursor.execute(
            "UPDATE memory_candidates SET status = 'REJECTED', updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'OBSERVING' AND first_seen_at IS NOT NULL "
            "AND julianday('now') - julianday(first_seen_at) > ?",
            (MEMORY_CANDIDATE_MAX_OBSERVING_DAYS,),
        )
        rejected = cursor.rowcount
        if rejected > 0:
            logger.info(
                f"🗑️ [MemoryManager] {rejected} 条候选超过 "
                f"{MEMORY_CANDIDATE_MAX_OBSERVING_DAYS} 天未获新证据，标记 REJECTED"
            )
        return rejected

    def _find_similar_memory(self, cursor: sqlite3.Cursor, candidate: dict) -> str | None:
        """在同空间、同用户、同类型的 active 记忆中查找与候选内容相似的记忆 id；找不到返回 None。

        **必须按 group_shared_space + user_id 过滤**：只比 type 会把用户 A 的候选合并进
        用户 B 的记忆（_merge_content 用「；」把两人的内容拼在一起），造成
        不可恢复的归属污染。与 _resolve_conflicts 的过滤条件保持一致。
        """
        rows = cursor.execute(
            "SELECT id, content FROM memories WHERE status = 'active' "
            "AND group_shared_space = ? AND user_id = ? AND type = ? "
            "ORDER BY last_accessed_at DESC",
            (str(candidate["group_shared_space"]), str(candidate["user_id"]), candidate["type"]),
        ).fetchall()
        for mem_id, content in rows:
            if is_similar(candidate["content"], content):
                return mem_id
        return None

    def _create_memory(self, cursor: sqlite3.Cursor, candidate: dict) -> None:
        """新建长期记忆并同步写入 FTS 索引。内存记忆内容与原样都取 candidate.content。
        同时写入 v2 元字段（usage_tags / visibility / behavior_rule）。"""
        memory_id = uuid.uuid4().hex
        cursor.execute(
            "INSERT OR IGNORE INTO memories ("
            "id, group_shared_space, user_id, type, content, content_raw, importance, confidence, status, "
            "confirmation_count, last_confirmed_at, last_accessed_at, compressed_at, compression_version, is_atomized, "
            "usage_tags, visibility, behavior_rule, source_kind)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, 0, 0, ?, ?, ?, ?)",
            (
                memory_id,
                candidate["group_shared_space"],
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
                candidate.get("source_kind") or "PASSIVE",
            ),
        )
        _upsert_fts_record(
            cursor,
            memory_id,
            str(candidate["group_shared_space"]),
            str(candidate["user_id"]),
            candidate["content"],
        )
        logger.info(f"🧠 [MemoryManager] 新增长期记忆 {memory_id} ({candidate['type']})")

    @staticmethod
    def _quota_score(importance, confirmation_count, last_accessed_at) -> float:
        """配额竞争分：越低越先被淘汰。

        三维加权：importance（信息本身的重要度）、confirmation_count（被独立确认
        的次数，最硬的证据，按 MEMORY_QUOTA_CONFIRMATION_CAP 归一化）、
        recency（最近是否仍被触达，指数衰减 τ=30 天，与 policy._recency_factor 一致）。

        用 last_accessed_at 而非 created_at：一条老但仍被频繁调用的记忆比一条新
        却从未被用过的更有价值。
        """
        import math

        from memory.timeutil import seconds_since

        imp = 0.0
        try:
            imp = max(0.0, min(1.0, float(importance or 0.0)))
        except (TypeError, ValueError):
            imp = 0.0

        conf_count = 0
        try:
            conf_count = int(confirmation_count or 0)
        except (TypeError, ValueError):
            conf_count = 0
        confirmation = min(1.0, conf_count / max(1, MEMORY_QUOTA_CONFIRMATION_CAP))

        # recency：解析失败或从未访问按「最旧」处理（recency=0），优先淘汰
        recency = 0.0
        elapsed = seconds_since(last_accessed_at) if last_accessed_at else None
        if elapsed is not None:
            age_days = max(0.0, elapsed / 86400.0)
            recency = math.exp(-age_days / 30.0)

        return (
            MEMORY_QUOTA_W_IMPORTANCE * imp
            + MEMORY_QUOTA_W_CONFIRMATION * confirmation
            + MEMORY_QUOTA_W_RECENCY * recency
        )

    def _enforce_user_quota(self, cursor: sqlite3.Cursor, group_shared_space, user_id) -> int:
        """把该空间该用户的 active 记忆压回 MEMORY_USER_QUOTA 条以内（竞争性淘汰）。

        超额时按 _quota_score 升序把最弱的若干条置 archived（不删除，仅退出
        active 检索，可人工恢复）。返回被淘汰的条数。

        ⚠️ 语义变化（v8）：MEMORY_USER_QUOTA 现在是「每空间每用户」的上限，
        不再是「每 QQ 群」。多个群组成一个空间时配额实际收紧了——这符合设计
        （同一个人在同一空间就是一份认知），但调参时要知道。

        MEMORY_QUOTA_ENFORCE=False 时只记录「本来会淘汰谁」的日志、不实际执行，
        用于上线前观察配额在真实库上的行为——25 条这个数在具体库上会淘汰什么，
        必须先看过再打开。

        注意：只统计 status='active'。archived / conflict 不占配额。
        """
        rows = cursor.execute(
            "SELECT id, content, importance, confirmation_count, last_accessed_at "
            "FROM memories WHERE status = 'active' AND group_shared_space = ? AND user_id = ?",
            (str(group_shared_space), str(user_id)),
        ).fetchall()
        if len(rows) <= MEMORY_USER_QUOTA:
            return 0

        scored = sorted(
            (
                (self._quota_score(r[2], r[3], r[4]), r[0], r[1] or "")
                for r in rows
            ),
            key=lambda item: item[0],
        )
        overflow = len(rows) - MEMORY_USER_QUOTA
        victims = scored[:overflow]

        if not MEMORY_QUOTA_ENFORCE:
            for score, mem_id, content in victims:
                logger.info(
                    f"📊 [Quota dry-run] 用户 {user_id} 超额（{len(rows)}/{MEMORY_USER_QUOTA}），"
                    f"本来会淘汰 {mem_id}（分 {score:.3f}）「{content[:40]}」"
                )
            return 0

        for score, mem_id, content in victims:
            cursor.execute(
                "UPDATE memories SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (mem_id,),
            )
            logger.info(
                f"📦 [Quota] 用户 {user_id} 超额（{len(rows)}/{MEMORY_USER_QUOTA}），"
                f"归档最弱记忆 {mem_id}（分 {score:.3f}）「{content[:40]}」"
            )
        return len(victims)

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
        merged_content = merge_content(content, candidate["content"])
        merged_content_raw = merge_content(content_raw or content, candidate["content"])
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
            str(candidate["group_shared_space"]),
            str(candidate["user_id"]),
            merged_content,
        )
        logger.info(f"🧠 [MemoryManager] 合并入已有记忆 {memory_id}")

    @staticmethod
    def _merge_usage_tags(old: str, new) -> str:
        """合并两批 usage_tags（JSON 数组），取并集、去重、保序。"""

        def _parse(value) -> list[str]:
            if isinstance(value, list):
                return [str(x).strip().upper() for x in value if str(x).strip()]
            try:
                parsed = json.loads(value or "[]")
                return [str(x).strip().upper() for x in parsed if str(x).strip()]
            except (ValueError, TypeError):
                return []

        merged: list[str] = []
        for tag in _parse(old) + _parse(new):
            if tag not in merged:
                merged.append(tag)
        return json.dumps(merged, ensure_ascii=False)

    @staticmethod
    def _merge_visibility(old, new) -> str:
        """合并可见性：候选若为更严格的 RESTRICTED/INTERNAL 则升级，否则保留旧值。"""
        from memory.policy import (
            VISIBILITY_INTERNAL,
            VISIBILITY_RESTRICTED,
            parse_visibility,
        )

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
            "SELECT id, content, confidence FROM memories WHERE status = 'active' AND group_shared_space = ? AND user_id = ? AND type = ?",
            (str(candidate["group_shared_space"]), str(candidate["user_id"]), candidate["type"]),
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


_memory_manager_instance: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """返回进程级单例 MemoryManager（懒初始化）。"""
    global _memory_manager_instance
    if _memory_manager_instance is None:
        _memory_manager_instance = MemoryManager()
    return _memory_manager_instance
