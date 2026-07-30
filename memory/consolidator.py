import asyncio
import json
import sqlite3
import re
from typing import Optional
from nonebot import logger

from config import DB_PATH, CONSOLIDATION_BATCH_SIZE, CONSOLIDATION_OVERLAP
from config import CONSOLIDATION_SITE, FLEXIWEB_BASE_URL, PROJECT_ROOT
from core.llm.flexiweb import FlexiWebBackend
from memory.consolidation_prompt import CONSOLIDATION_PROMPT


_consolidator_instance: Optional["MemoryConsolidator"] = None


class MemoryConsolidator:
    def __init__(self):
        self.llm = FlexiWebBackend(base_url=FLEXIWEB_BASE_URL, site=CONSOLIDATION_SITE)

    # ── checkpoint 表 ──────────────────────────────────
    def _ensure_state_table(self, conn: sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consolidation_state (
                group_id  TEXT PRIMARY KEY,
                last_processed_id INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def _get_last_processed_id(self, group_id: int) -> int:
        conn = sqlite3.connect(DB_PATH)
        self._ensure_state_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_processed_id FROM consolidation_state WHERE group_id = ?",
            (str(group_id),),
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else 0

    def _get_max_message_id(self, group_id: int) -> int:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MAX(id) FROM group_messages WHERE group_id = ?",
            (str(group_id),),
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else 0

    # ── 核心 ────────────────────────────────────────────
    async def consolidate_group(self, group_id: int):
        if not DB_PATH.exists():
            return

        try:
            last_id = self._get_last_processed_id(group_id)
            max_id = self._get_max_message_id(group_id)
            new_count = max_id - last_id

            if new_count < CONSOLIDATION_BATCH_SIZE:
                return

            batch_end = min(max_id, last_id + CONSOLIDATION_BATCH_SIZE)

            messages = self._fetch_messages(group_id, last_id, batch_end)
            if not messages:
                return

            current_summary = self._fetch_current_summary(group_id)
            prompt = CONSOLIDATION_PROMPT.format(
                messages=messages,
                current_summary=current_summary or "（无）",
            )

            logger.info(f"🧠 [Consolidator] 整合群 {group_id}：id {last_id} → {batch_end}（{batch_end - last_id} 条）")
            result = await self.llm.generate(prompt)

            parsed = self._parse_json(result)
            if not parsed:
                logger.warning(f"⚠️ [Consolidator] JSON 解析失败: {result[:200]}")
                return

            self._write_short_term(group_id, parsed.get("short_term"))
            self._write_user_profiles(parsed.get("user_profiles", []))
            self._write_long_term_memories(group_id, parsed.get("long_term_memories", []))
            self._update_checkpoint(group_id, batch_end)

            logger.success(f"✅ [Consolidator] 群 {group_id} 整合完成，已处理至 id {batch_end}")
        except Exception as e:
            logger.error(f"❌ [Consolidator] 群 {group_id} 整合失败: {e}")

    def _fetch_messages(self, group_id: int, last_id: int, batch_end: int) -> str:
        fetch_from = max(0, last_id - CONSOLIDATION_OVERLAP)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, content FROM group_messages WHERE group_id = ? AND id > ? AND id <= ? ORDER BY id ASC",
            (str(group_id), fetch_from, batch_end),
        )
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return ""
        return "\n".join(f"用户({uid}): {content}" for uid, content in rows)

    def _fetch_current_summary(self, group_id: int) -> str:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT active_summary FROM short_term_context WHERE group_id = ?",
            (str(group_id),),
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else ""

    # ── DB 写入 ─────────────────────────────────────────
    def _update_checkpoint(self, group_id: int, max_id: int):
        conn = sqlite3.connect(DB_PATH)
        self._ensure_state_table(conn)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO consolidation_state (group_id, last_processed_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(group_id) DO UPDATE SET
                last_processed_id = excluded.last_processed_id,
                updated_at = CURRENT_TIMESTAMP
        """, (str(group_id), max_id))
        conn.commit()
        conn.close()

    def _write_short_term(self, group_id: int, data: Optional[dict]):
        if not data:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO short_term_context (group_id, active_summary, pending_topic, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(group_id) DO UPDATE SET
                active_summary = excluded.active_summary,
                pending_topic = excluded.pending_topic,
                updated_at = CURRENT_TIMESTAMP
        """, (str(group_id), data.get("active_summary", ""), data.get("pending_topic", "无")))
        conn.commit()
        conn.close()

    def _write_user_profiles(self, profiles: list):
        if not profiles:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for p in profiles:
            uid = str(p.get("user_id", ""))
            if not uid:
                continue
            cursor.execute("SELECT interaction_count FROM user_profiles WHERE user_id = ?", (uid,))
            row = cursor.fetchone()
            count = (row[0] + 1) if row else 1
            cursor.execute("""
                INSERT INTO user_profiles (user_id, nickname, personality_traits, agent_attitude, interaction_count, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    personality_traits = excluded.personality_traits,
                    agent_attitude = excluded.agent_attitude,
                    interaction_count = excluded.interaction_count,
                    updated_at = CURRENT_TIMESTAMP
            """, (uid, p.get("nickname", ""), p.get("personality_traits", ""), p.get("agent_attitude", ""), count))
        conn.commit()
        conn.close()

    def _write_long_term_memories(self, group_id: int, memories: list):
        if not memories:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for m in memories:
            importance = m.get("importance", 5)
            if importance < 5:
                continue
            cursor.execute("""
                INSERT INTO long_term_memories (group_id, user_id, summary, importance, access_count, last_accessed_at)
                VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
            """, (str(group_id), str(m.get("user_id", "")), m.get("summary", ""), importance))
        conn.commit()
        conn.close()

    def _parse_json(self, text: str) -> Optional[dict]:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            return None


# ── 外部接口 ────────────────────────────────────────────

def get_consolidator() -> MemoryConsolidator:
    global _consolidator_instance
    if _consolidator_instance is None:
        _consolidator_instance = MemoryConsolidator()
    return _consolidator_instance


def maybe_consolidate(group_id: int):
    consolidator = get_consolidator()
    asyncio.create_task(consolidator.consolidate_group(group_id))
