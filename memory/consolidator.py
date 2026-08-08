# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""
消息整合（Consolidator）模块。

本模块位于记忆工作流的“写入侧”：它把积累的群聊原始消息批量取出来，
交给 LLM 总结为「短期上下文 + 用户画像更新 + 记忆候选」等结构化 JSON，
再落库到 SQLite，并推进每群的 checkpoint（last_processed_id）保证每条消息只被处理一次。

典型调用链（示例）：
    新消息入表（pre_processors.record_message）
    → maybe_consolidate() 启动后台任务
    → consolidate_group() 读取 checkpoint 之后的新消息
    → _generate() 按优先级调用 LLM（在线 FlexiWeb 失败自动降级本地 LM Studio）
    → _parse_json() 容错解析 LLM 输出
    → 写短期上下文 / 用户画像 / 记忆候选
    → _update_checkpoint() 推进进度，避免重复处理
"""
import asyncio
import json
import sqlite3
import re
import time
import uuid
from datetime import datetime
from typing import Optional
from nonebot import logger

from config import DB_PATH, CONSOLIDATION_BATCH_SIZE, CONSOLIDATION_OVERLAP
from config import (
    CONSOLIDATION_LLM_PRIORITY, CONSOLIDATION_ONLINE_COOLDOWN,
    CONSOLIDATION_LM_STUDIO_BASE_URL, CONSOLIDATION_LM_STUDIO_MODEL,
    CONSOLIDATION_LM_STUDIO_TEMPERATURE,
    CONSOLIDATION_MAX_TOKENS, CONSOLIDATION_LOCAL_BATCH_SIZE,
    CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE, CONSOLIDATION_LOCAL_MAX_TOKENS,
)
from core.llm.lm_studio import LMStudioBackend
from core.llm import consolidation_llm_lock
from memory.consolidation_prompt import CONSOLIDATION_PROMPT
from memory.consolidation_log import append_consolidation_log
from memory.memory_manager import get_memory_manager


_consolidator_instance: Optional["MemoryConsolidator"] = None


class MemoryConsolidator:
    """群聊消息整合器。

    负责把「消息库」中积压的新消息批量总结为结构化记忆：
    - 短期上下文（short_term_context）
    - 用户画像（user_profiles）
    - 记忆候选（memory_candidates，后续由 MemoryManager 晋升为长期记忆）

    同时维护每群的 checkpoint，保证不重不漏地消费消息；后端具备在线→本地的降级能力。
    单例通过 get_consolidator() 获取。
    """

    def __init__(self):
        # 后端列表：元素为 (名称, backend对象)，按优先级顺序，由 config 决定
        self._backends = []
        # 在线后端（FlexiWeb）的冷却截止时刻（time.monotonic 时间戳），小于当前时间表明已过冷却期
        self._online_cooldown_until = 0.0
        self._build_backends()

    def _build_backends(self):
        """按 CONSOLIDATION_LLM_PRIORITY 顺序构建 LLM 列表
        按优先级配置逐一实例化后端并存入 self._backends；
        其中 flexiweb 为可选在线后端，构造失败（如管理器创建异常）时跳过。
        """
        for name in CONSOLIDATION_LLM_PRIORITY:
            if name == "flexiweb":
                backend = self._create_flexiweb_backend()
                if backend is not None:
                    self._backends.append(("flexiweb", backend))
            elif name == "lm_studio":
                # 本地后端：使用整合专用配置（可与聊天用模型隔离，避免互相阻塞）
                backend = LMStudioBackend(
                    base_url=CONSOLIDATION_LM_STUDIO_BASE_URL,
                    model=CONSOLIDATION_LM_STUDIO_MODEL,
                    max_tokens=CONSOLIDATION_LOCAL_MAX_TOKENS,
                    temperature=CONSOLIDATION_LM_STUDIO_TEMPERATURE,
                )
                self._backends.append(("lm_studio", backend))

    def _create_flexiweb_backend(self):
        """创建（或复用全局）FlexiWeb 在线后端；失败返回 None 表示不可用。"""
        from config import CONSOLIDATION_SITE, FLEXIWEB_BASE_URL, FLEXIWEB_PROJECT_DIR, FLEXIWEB_HEADLESS
        import core.llm.flexiweb as _flexiweb
        from core.llm.flexiweb import FlexiWebBackend, FlexiWebManager
        mgr = _flexiweb.global_manager
        if mgr is None:
            # 全局管理器尚未初始化时，为整合用途创建一个独立管理器
            mgr = FlexiWebManager(
                project_dir=FLEXIWEB_PROJECT_DIR,
                base_url=FLEXIWEB_BASE_URL,
                site=CONSOLIDATION_SITE,
                headless=FLEXIWEB_HEADLESS,
            )
        self.manager = mgr
        return FlexiWebBackend(manager=mgr, base_url=FLEXIWEB_BASE_URL, site=CONSOLIDATION_SITE)

    def _online_available(self) -> bool:
        """FlexiWeb 是否在优先级链中且未处于冷却
        返回 True 表示当前可用在线后端（在优先级链中且已经过了冷却截止时刻）。
        """
        has_flexiweb = any(name == "flexiweb" for name, _ in self._backends)
        if not has_flexiweb:
            return False
        return time.monotonic() >= self._online_cooldown_until

    async def _generate(self, group_id: int, last_id: int, force: bool = False) -> tuple[str, int, str]:
        """按优先级依次调用 LLM；在线 LLM 失败自动降级到本地（用小批次重建 prompt）。
        force=True 时只走本地小批量（用于 @触发/主动发言前的轻量总结）。
        返回 (回复文本, 实际处理到的 batch_end, 实际使用的后端名)，用于准确推进 checkpoint。"""
        last_error: Optional[Exception] = None
        for name, backend in self._backends:
            # 是否本地后端：本地后端用 is_local 标志区分，force 时必须走本地
            is_local = bool(getattr(backend, "is_local", False))
            if force and not is_local:
                continue
            if name == "flexiweb":
                # 在线后端若处于冷却期则直接跳过（不去调用，避免浪费请求）
                if time.monotonic() < self._online_cooldown_until:
                    logger.info("🕐 [Consolidator] FlexiWeb 冷却中，跳过在线 LLM")
                    continue
                limit = CONSOLIDATION_BATCH_SIZE
            elif force:
                # force 小批次：固定使用较小批，用于 @触发 / 主动发言前的轻量总结
                limit = CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE
            else:
                limit = CONSOLIDATION_LOCAL_BATCH_SIZE

            try:
                messages, batch_end = self._fetch_next_messages(group_id, last_id, limit)
                if not messages:
                    raise RuntimeError("没有可整合的消息")
                prompt = self._build_prompt(group_id, messages)
                logger.info(f"🌐 [Consolidator] 尝试 LLM: {name}（{limit} 条）")
                model_tag = getattr(backend, "model", "") or getattr(backend, "site", "") or name
                result = await backend.generate(prompt)
                append_consolidation_log(
                    f"- **🧠 后端**: {name}（{model_tag}，批次 {limit} 条）\n"
                    f"  > 原始输出：\n  > {result.replace(chr(10), chr(10) + '  > ')}\n"
                )
                # 返回真实处理到的 batch_end 与后端名，供调用方准确推进 checkpoint
                return result, batch_end, name
            except Exception as e:
                last_error = e
                logger.warning(f"⚠️ [Consolidator] LLM {name} 失败: {e}")
                if name == "flexiweb":
                    # 在线后端失败：设置冷却窗口，下次循环直接跳过它，实现“降级到本地”
                    self._online_cooldown_until = time.monotonic() + CONSOLIDATION_ONLINE_COOLDOWN
                    logger.info(f"⏲ [Consolidator] FlexiWeb 进入冷却（{CONSOLIDATION_ONLINE_COOLDOWN}s），降级到本地")
        if last_error:
            raise last_error
        raise RuntimeError("没有可用的 LLM 后端")

    def _build_prompt(self, group_id: int, messages: str) -> str:
        """用当前短期摘要 + 本批消息填充整合 prompt 模板。"""
        current_summary = self._fetch_current_summary(group_id)
        return CONSOLIDATION_PROMPT.format(
            messages=messages,
            current_summary=current_summary or "（无）",
        )

    # ── checkpoint 表 ──────────────────────────────────
    def _ensure_state_table(self, conn: sqlite3.Connection):
        """确保 checkpoint 表存在：记录每群已处理到的最新消息 id。"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consolidation_state (
                group_id  TEXT PRIMARY KEY,
                last_processed_id INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def _ensure_common_tables(self, conn: sqlite3.Connection):
        """确保整合落库所需的公共表（短期上下文 / 消息 / 用户画像 / 记忆候选 / 记忆等）存在。"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS short_term_context (
                group_id TEXT PRIMARY KEY,
                active_summary TEXT,
                pending_topic TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT,
                user_id TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                nickname TEXT,
                personality_traits TEXT,
                agent_attitude TEXT,
                interaction_count INTEGER DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
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
        conn.execute("""
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
        conn.execute("""
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
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_group_user_status
            ON memories (group_id, user_id, status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_group_status_accessed
            ON memories (group_id, status, last_accessed_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_group_id
            ON messages (group_id, id)
        """)

    def _get_last_processed_id(self, group_id: int) -> int:
        """读取指定群的 checkpoint（已整合到的最大消息 id），无记录时返回 0。"""
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
        try:
            table = self._get_message_table(cursor)
            cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE group_id = ? AND id > ?",
                (str(group_id), last_id),
            )
            n = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        conn.close()
        return n

    def _get_message_table(self, cursor: sqlite3.Cursor) -> str:
        """确定当前数据源的消息表名：优先 group_messages，回退到旧版 messages 表。"""
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('messages', 'group_messages')"
        )
        tables = {row[0] for row in cursor.fetchall()}
        if "group_messages" in tables:
            return "group_messages"
        if "messages" in tables:
            return "messages"
        return "group_messages"

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
        """整合指定群的消息：读取新消息→LLM 总结→解析 JSON→落库→推进 checkpoint。
        force=True 表示走本地小批次轻量总结（用于 @触发/主动发言前的即时总结）。
        副作用：更新 checkpoint、写入 short_term_context / user_profiles / memory_candidates。
        """
        if not DB_PATH.exists():
            return

        # 整合使用独立的 LM Studio 配置（可指向低阶整合模型/独立实例），与聊天互不阻塞；
        # 但整合自身仍需串行，避免多群并发打爆同一整合服务
        async with consolidation_llm_lock:
            try:
                last_id = self._get_last_processed_id(group_id)
                new_count = self._count_new_messages(group_id, last_id)

                # force 路径走小批次；非 force 路径按当前可用后端决定阈值
                threshold = CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE if force else (
                    CONSOLIDATION_BATCH_SIZE if self._online_available() else CONSOLIDATION_LOCAL_BATCH_SIZE
                )
                if new_count < threshold:
                    return

                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                append_consolidation_log(
                    f"### 🕒 [{now_str}] 群 `{group_id}` 开始整合"
                    f"（force={force}，新消息 {new_count}，批次阈值 {threshold}）\n"
                )

                result, processed_end, backend_name = await self._generate(group_id, last_id, force=force)
                logger.info(f"📥 [Consolidator Response]\n{result}")

                parsed = self._parse_json(result)
                if not parsed:
                    logger.warning(f"⚠️ [Consolidator] JSON 解析失败，跳过本批次: {result[:200]}")
                    # 即使解析失败也推进 checkpoint，避免同一批消息反复重处理
                    append_consolidation_log("  > ⚠️ JSON 解析失败，已推进 checkpoint 避免重处理\n")
                    self._update_checkpoint(group_id, processed_end)
                    return

                self._write_short_term(group_id, parsed.get("short_term"))
                self._write_user_profiles(parsed.get("user_profiles", []))
                candidates = parsed.get("memory_candidates")
                if candidates is None:
                    candidates = []
                self._write_memory_candidates(group_id, candidates)
                if candidates:
                    # 有新候选记忆时同步触发 MemoryManager 晋升处理
                    get_memory_manager().process_new_candidates()
                elif parsed.get("long_term_memories"):
                    # 兼容旧版输出，将旧格式记忆写入旧表，以免丢失历史信息。
                    self._write_long_term_memories(group_id, parsed.get("long_term_memories", []))
                self._update_checkpoint(group_id, processed_end)

                append_consolidation_log(
                    f"  > ✅ 整合完成（后端 {backend_name}，checkpoint {last_id} → {processed_end}，"
                    f"记忆候选 {len(candidates)} 条）\n"
                )
                logger.success(f"✅ [Consolidator] 群 {group_id} 整合完成，已处理至 id {processed_end}")
            except Exception:
                logger.exception(f"❌ [Consolidator] 群 {group_id} 整合失败")
                append_consolidation_log("  > ❌ 整合失败（详见控制台日志）\n")

    def _fetch_next_messages(self, group_id: int, last_id: int, limit: int) -> tuple[str, int]:
        """取 last_id 之后最多 limit 条消息（含 overlap 上下文）。
        返回 (文本, 本批次末尾的最大消息 id)。按实际行数取，可容忍 id 空洞。"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        message_table = self._get_message_table(cursor)
        # 先定位 last_id 之后 limit 条消息的真实 id 范围
        cursor.execute(
            f"SELECT id FROM {message_table} WHERE group_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (str(group_id), last_id, limit),
        )
        new_ids = [r[0] for r in cursor.fetchall()]
        if not new_ids:
            conn.close()
            return "", last_id
        batch_end = new_ids[-1]

        fetch_from = max(0, last_id - CONSOLIDATION_OVERLAP)
        cursor.execute(
            f"SELECT id, user_id, content FROM {message_table} WHERE group_id = ? AND id > ? AND id <= ? ORDER BY id ASC",
            (str(group_id), fetch_from, batch_end),
        )
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return "", last_id
        return "\n".join(f"消息ID({mid}) 用户({uid}): {content}" for mid, uid, content in rows), batch_end

    def _fetch_current_summary(self, group_id: int) -> str:
        """读取当前群的短期摘要（active_summary），无记录或表不存在时返回空串。"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT active_summary FROM short_term_context WHERE group_id = ?",
                (str(group_id),),
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else ""
        except sqlite3.OperationalError:
            return ""
        finally:
            conn.close()

    # ── DB 写入 ─────────────────────────────────────────
    def _update_checkpoint(self, group_id: int, max_id: int):
        """推进该群的 checkpoint（记录已处理到的最大消息 id），使用 upsert 保证幂等。"""
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
        """写入短期上下文（摘要 + 进行中的话题），data 为空则跳过；使用 upsert。"""
        if not data:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        self._ensure_common_tables(conn)
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
        LLM 有时返回 '3089665724'，有时返回 '用户(3089665724)'，需统一。
        匹配失败时原样返回（保留可能的后缀，避免误吞数据）。"""
        uid = (uid or "").strip()
        m = re.match(r"^(?:用户\()?(\d+)\)?$", uid)
        if m:
            return m.group(1)
        return uid

    def _write_user_profiles(self, profiles: list):
        """把 LLM 给出的用户画像批量写入 user_profiles：已存在则合并特征并累计互动次数。
        副作用：更新/插入 user_profiles 表；单条记录 user_id 非法（空）时跳过。"""
        if not profiles:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        self._ensure_common_tables(conn)
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
                # 新值优先，缺失字段则保留旧值；特征合并去重
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
                # 新用户：直接插入，互动次数初始为 1
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

    def _write_memory_candidates(self, group_id: int, candidates: list):
        """把 LLM 给出的记忆候选写入 memory_candidates 表（状态 NEW），供 MemoryManager 晋升。
        数据清洗：user_id 规范化、type 大写、importance/confidence 转浮点、source_message_ids 序列化。
        """
        if not candidates:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        self._ensure_common_tables(conn)
        for c in candidates:
            uid = self._normalize_user_id(str(c.get("user_id", "")))
            if not uid:
                continue
            type_ = (str(c.get("type", "FACT")) or "FACT").strip().upper()
            content = (c.get("content", "") or "").strip()
            if not content:
                continue
            importance = float(c.get("importance", 0.0) or 0.0)
            confidence = float(c.get("confidence", 0.0) or 0.0)
            evidence = (c.get("evidence", "") or "").strip()
            # LLM 可能返回字符串形式的消息 id 列表，做一次容错反序列化
            source_ids = c.get("source_message_ids", [])
            if isinstance(source_ids, str):
                try:
                    source_ids = json.loads(source_ids)
                except Exception:
                    source_ids = []
            if not isinstance(source_ids, list):
                source_ids = []
            source_ids = json.dumps([str(x) for x in source_ids if str(x).strip()], ensure_ascii=False)
            # 无 id 时生成本地候选 id
            candidate_id = str(c.get("id", "")) or uuid.uuid4().hex
            cursor.execute("""
                INSERT INTO memory_candidates (id, group_id, user_id, type, content, importance, confidence, evidence, status, source_message_ids)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    group_id = excluded.group_id,
                    user_id = excluded.user_id,
                    type = excluded.type,
                    content = excluded.content,
                    importance = excluded.importance,
                    confidence = excluded.confidence,
                    evidence = excluded.evidence,
                    status = excluded.status,
                    source_message_ids = excluded.source_message_ids,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                candidate_id,
                str(group_id),
                uid,
                type_,
                content,
                importance,
                confidence,
                evidence,
                "NEW",
                source_ids,
            ))
        conn.commit()
        conn.close()

    def _write_long_term_memories(self, group_id: int, memories: list):
        """兼容旧版整合输出：把旧格式的 long_term_memories 写入旧表 long_term_memories。
        仅保留 importance>=5 且有摘要的记录；同群同用户同摘要去重。"""
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
        """容错解析 LLM 输出为 JSON 对象。

        处理策略（依次尝试）：
        1. 去除首尾的 ```json 代码块标记后直接 json.loads；
        2. 失败则扫描文本，用括号配平逐段尝试提取第一个完整 JSON 对象
           （模型常拼接多份输出或用散文包裹 JSON），全部失败返回 None。
        """
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # 提取第一个完整且平衡的 JSON 对象（考虑字符串中的花括号与转义）
        start = text.find("{")
        while start != -1:
            depth = 0
            in_str = False
            escape = False
            for i in range(start, len(text)):
                ch = text[i]
                if in_str:
                    # 字符串内部：仅识别转义字符与结束引号，忽略花括号
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
                        # 找到配平的 JSON 片段，尝试解析；失败则从下一个 { 重新扫描
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
    """返回进程级单例 MemoryConsolidator（懒初始化）。"""
    global _consolidator_instance
    if _consolidator_instance is None:
        _consolidator_instance = MemoryConsolidator()
    return _consolidator_instance


def maybe_consolidate(group_id: int, force: bool = False):
    """异步触发一次群整合（后台任务），并登记以跟踪完成与否（不等待）。
    force=True 走本地小批次轻量总结，适合 @触发 / 主动发言前调用。"""
    consolidator = get_consolidator()
    task = asyncio.create_task(consolidator.consolidate_group(group_id, force=force))
    _consolidation_tasks.add(task)
    task.add_done_callback(_consolidation_tasks.discard)
