import asyncio
import json
import sqlite3
import re
import time
from typing import Optional
from nonebot import logger

from config import DB_PATH, CONSOLIDATION_BATCH_SIZE, CONSOLIDATION_OVERLAP
from config import (
    CONSOLIDATION_LLM_PRIORITY, CONSOLIDATION_ONLINE_COOLDOWN,
    LM_STUDIO_BASE_URL, LM_STUDIO_MODEL,
    CONSOLIDATION_MAX_TOKENS, CONSOLIDATION_LOCAL_BATCH_SIZE, CONSOLIDATION_LOCAL_MAX_TOKENS,
)
from core.llm.lm_studio import LMStudioBackend
from core.llm import llm_lock
from memory.consolidation_prompt import CONSOLIDATION_PROMPT


_consolidator_instance: Optional["MemoryConsolidator"] = None


class MemoryConsolidator:
    def __init__(self):
        self._backends = []
        self._online_cooldown_until = 0.0
        self._build_backends()

    def _build_backends(self):
        """按 CONSOLIDATION_LLM_PRIORITY 顺序构建 LLM 列表"""
        for name in CONSOLIDATION_LLM_PRIORITY:
            if name == "flexiweb":
                backend = self._create_flexiweb_backend()
                if backend is not None:
                    self._backends.append(("flexiweb", backend))
            elif name == "lm_studio":
                backend = LMStudioBackend(
                    base_url=LM_STUDIO_BASE_URL,
                    model=LM_STUDIO_MODEL,
                    max_tokens=CONSOLIDATION_LOCAL_MAX_TOKENS,
                )
                self._backends.append(("lm_studio", backend))

    def _create_flexiweb_backend(self):
        from config import CONSOLIDATION_SITE, FLEXIWEB_BASE_URL, FLEXIWEB_PROJECT_DIR, FLEXIWEB_HEADLESS
        import core.llm.flexiweb as _flexiweb
        from core.llm.flexiweb import FlexiWebBackend, FlexiWebManager
        mgr = _flexiweb.global_manager
        if mgr is None:
            mgr = FlexiWebManager(
                project_dir=FLEXIWEB_PROJECT_DIR,
                base_url=FLEXIWEB_BASE_URL,
                site=CONSOLIDATION_SITE,
                headless=FLEXIWEB_HEADLESS,
            )
        self.manager = mgr
        return FlexiWebBackend(manager=mgr, base_url=FLEXIWEB_BASE_URL, site=CONSOLIDATION_SITE)

    def _online_available(self) -> bool:
        """FlexiWeb 是否在优先级链中且未处于冷却"""
        has_flexiweb = any(name == "flexiweb" for name, _ in self._backends)
        if not has_flexiweb:
            return False
        return time.monotonic() >= self._online_cooldown_until

    async def _generate(self, group_id: int, last_id: int, force: bool = False) -> tuple[str, int]:
        """按优先级依次调用 LLM；在线 LLM 失败自动降级到本地 SLM（用小批次重建 prompt）。
        force=True 时只走本地小批量（用于 @触发/主动发言前的轻量总结）。
        返回 (回复文本, 实际处理到的 batch_end)，用于准确推进 checkpoint。"""
        last_error: Optional[Exception] = None
        for name, backend in self._backends:
            if force and name != "lm_studio":
                continue
            if name == "flexiweb":
                if time.monotonic() < self._online_cooldown_until:
                    logger.info("🕐 [Consolidator] FlexiWeb 冷却中，跳过在线 LLM")
                    continue
                limit = CONSOLIDATION_BATCH_SIZE
            else:
                limit = CONSOLIDATION_LOCAL_BATCH_SIZE

            try:
                messages, batch_end = self._fetch_next_messages(group_id, last_id, limit)
                if not messages:
                    raise RuntimeError("没有可整合的消息")
                prompt = self._build_prompt(group_id, messages)
                logger.info(f"🌐 [Consolidator] 尝试 LLM: {name}（{limit} 条）")
                result = await backend.generate(prompt)
                return result, batch_end
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ [Consolidator] LLM {name} 失败: {e}")
                if name == "flexiweb":
                    self._online_cooldown_until = time.monotonic() + CONSOLIDATION_ONLINE_COOLDOWN
                    logger.info(f"⏲ [Consolidator] FlexiWeb 进入冷却（{CONSOLIDATION_ONLINE_COOLDOWN}s），降级到本地 SLM")
        if last_error:
            raise last_error
        raise RuntimeError("没有可用的 LLM 后端")

    def _build_prompt(self, group_id: int, messages: str) -> str:
        current_summary = self._fetch_current_summary(group_id)
        return CONSOLIDATION_PROMPT.format(
            messages=messages,
            current_summary=current_summary or "（无）",
        )

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

    def _count_new_messages(self, group_id: int, last_id: int) -> int:
        """统计 last_id 之后还有多少条未整合的消息"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM group_messages WHERE group_id = ? AND id > ?",
            (str(group_id), last_id),
        )
        n = cursor.fetchone()[0]
        conn.close()
        return n

    def has_new_messages_to_consolidate(self, group_id: int, threshold: int = 0) -> int:
        """@ 触发时判断：距上次总结累积了多少条未整合消息。
        返回新消息数；调用方可据此决定是否值得触发一次轻量总结。"""
        last_id = self._get_last_processed_id(group_id)
        n = self._count_new_messages(group_id, last_id)
        if threshold and n < threshold:
            return 0
        return n

    # ── 核心 ────────────────────────────────────────────
    async def consolidate_group(self, group_id: int, force: bool = False):
        if not DB_PATH.exists():
            return

        # 串行化：FlexiWeb 共享同一浏览器页面，并发打字会导致输入交错乱码；
        # 同时与 Pipeline 共享同一把锁，防止整合与回复并发打本地小模型
        async with llm_lock:
            try:
                last_id = self._get_last_processed_id(group_id)
                new_count = self._count_new_messages(group_id, last_id)

                # force 路径只走本地小批量；非 force 路径按当前可用后端决定阈值
                threshold = CONSOLIDATION_LOCAL_BATCH_SIZE if force else (
                    CONSOLIDATION_BATCH_SIZE if self._online_available() else CONSOLIDATION_LOCAL_BATCH_SIZE
                )
                if new_count < threshold:
                    return

                result, processed_end = await self._generate(group_id, last_id, force=force)
                logger.info(f"📥 [Consolidator Response]\n{result}")

                parsed = self._parse_json(result)
                if not parsed:
                    logger.warning(f"⚠️ [Consolidator] JSON 解析失败，跳过本批次: {result[:200]}")
                    # 即使解析失败也推进 checkpoint，避免同一批消息反复重处理
                    self._update_checkpoint(group_id, processed_end)
                    return

                self._write_short_term(group_id, parsed.get("short_term"))
                self._write_user_profiles(parsed.get("user_profiles", []))
                self._write_long_term_memories(group_id, parsed.get("long_term_memories", []))
                self._update_checkpoint(group_id, processed_end)

                logger.success(f"✅ [Consolidator] 群 {group_id} 整合完成，已处理至 id {processed_end}")
            except Exception:
                logger.exception(f"❌ [Consolidator] 群 {group_id} 整合失败")

    def _fetch_next_messages(self, group_id: int, last_id: int, limit: int) -> tuple[str, int]:
        """取 last_id 之后最多 limit 条消息（含 overlap 上下文）。
        返回 (文本, 本批次末尾的最大消息 id)。按实际行数取，可容忍 id 空洞。"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # 先定位 last_id 之后 limit 条消息的真实 id 范围
        cursor.execute(
            "SELECT id FROM group_messages WHERE group_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (str(group_id), last_id, limit),
        )
        new_ids = [r[0] for r in cursor.fetchall()]
        if not new_ids:
            conn.close()
            return "", last_id
        batch_end = new_ids[-1]

        fetch_from = max(0, last_id - CONSOLIDATION_OVERLAP)
        cursor.execute(
            "SELECT user_id, content FROM group_messages WHERE group_id = ? AND id > ? AND id <= ? ORDER BY id ASC",
            (str(group_id), fetch_from, batch_end),
        )
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return "", last_id
        return "\n".join(f"用户({uid}): {content}" for uid, content in rows), batch_end

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

    @staticmethod
    def _normalize_user_id(uid: str) -> str:
        """把 LLM 返回的 user_id 规范化为纯数字 QQ 号。
        LLM 有时返回 '3089665724'，有时返回 '用户(3089665724)'，需统一。"""
        uid = (uid or "").strip()
        m = re.match(r"^(?:用户\()?(\d+)\)?$", uid)
        if m:
            return m.group(1)
        return uid

    def _write_user_profiles(self, profiles: list):
        if not profiles:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for p in profiles:
            uid = self._normalize_user_id(str(p.get("user_id", "")))
            if not uid:
                continue
            cursor.execute(
                "SELECT nickname, personality_traits, agent_attitude, interaction_count FROM user_profiles WHERE user_id = ?",
                (uid,),
            )
            row = cursor.fetchone()
            if row:
                old_nick, old_traits, old_attitude, old_count = row
                new_nick = p.get("nickname", "") or old_nick
                new_traits = self._merge_traits(old_traits, p.get("personality_traits", ""))
                new_attitude = self._merge_traits(old_attitude, p.get("agent_attitude", ""))
                cursor.execute("""
                    UPDATE user_profiles
                    SET nickname = ?, personality_traits = ?, agent_attitude = ?,
                        interaction_count = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?
                """, (new_nick, new_traits, new_attitude, old_count + 1, uid))
            else:
                cursor.execute("""
                    INSERT INTO user_profiles (user_id, nickname, personality_traits, agent_attitude, interaction_count, updated_at)
                    VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                """, (uid, p.get("nickname", ""), p.get("personality_traits", ""), p.get("agent_attitude", "")))
        conn.commit()
        conn.close()

    @staticmethod
    def _merge_traits(old: str, new: str) -> str:
        """合并两段特征描述：去重、去空、保留顺序。"""
        old = (old or "").strip()
        new = (new or "").strip()
        if not old:
            return new
        if not new:
            return old
        old_parts = [s.strip() for s in re.split(r"[,，;；、\n]+", old) if s.strip()]
        new_parts = [s.strip() for s in re.split(r"[,，;；、\n]+", new) if s.strip()]
        seen = set()
        merged = []
        for part in old_parts + new_parts:
            key = part.lower()
            if key not in seen:
                seen.add(key)
                merged.append(part)
        return "，".join(merged)

    def _write_long_term_memories(self, group_id: int, memories: list):
        if not memories:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for m in memories:
            importance = m.get("importance", 5)
            if importance < 5:
                continue
            uid = self._normalize_user_id(str(m.get("user_id", "")))
            if not uid:
                continue
            summary = (m.get("summary", "") or "").strip()
            if not summary:
                continue
            # 去重：同群、同用户、摘要完全相同则跳过
            cursor.execute(
                "SELECT id FROM long_term_memories WHERE group_id = ? AND user_id = ? AND summary = ?",
                (str(group_id), uid, summary),
            )
            if cursor.fetchone():
                continue
            cursor.execute("""
                INSERT INTO long_term_memories (group_id, user_id, summary, importance, access_count, last_accessed_at)
                VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
            """, (str(group_id), uid, summary, importance))
        conn.commit()
        conn.close()

    def _parse_json(self, text: str) -> Optional[dict]:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 提取第一个完整且平衡的 JSON 对象（模型可能拼接输出多份）
        start = text.find("{")
        while start != -1:
            depth = 0
            in_str = False
            escape = False
            for i in range(start, len(text)):
                ch = text[i]
                if in_str:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i + 1])
                        except json.JSONDecodeError:
                            break
            start = text.find("{", start + 1)
        return None


# ── 外部接口 ────────────────────────────────────────────

_consolidator_instance: Optional["MemoryConsolidator"] = None
_consolidation_tasks: set[asyncio.Task] = set()


def get_consolidator() -> MemoryConsolidator:
    global _consolidator_instance
    if _consolidator_instance is None:
        _consolidator_instance = MemoryConsolidator()
    return _consolidator_instance


def maybe_consolidate(group_id: int, force: bool = False):
    consolidator = get_consolidator()
    task = asyncio.create_task(consolidator.consolidate_group(group_id, force=force))
    _consolidation_tasks.add(task)
    task.add_done_callback(_consolidation_tasks.discard)
