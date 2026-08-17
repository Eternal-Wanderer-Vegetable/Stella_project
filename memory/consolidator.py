# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""
消息整合（Consolidator）模块。

本模块位于记忆工作流的“写入侧”：它把积累的群聊原始消息批量取出来，
交给本地 LLM（LM Studio）总结为「短期上下文 + 用户画像更新 + 记忆候选」等结构化 JSON，
再落库到 SQLite，并推进每群的 checkpoint（last_processed_id）保证每条消息只被处理一次。

典型调用链（示例）：
    新消息入表（pre_processors.record_message）
    → maybe_consolidate() 启动后台任务
    → consolidate_group() 读取 checkpoint 之后的新消息
    → _generate() 调用本地 LM Studio（在线整合流程已废弃，见 _deprecated/core_llm_flexiweb.py）
    → _parse_json() 容错解析 LLM 输出
    → 写短期上下文 / 用户画像 / 记忆候选
    → _update_checkpoint() 推进进度，避免重复处理
    定时整合任务（ai_gateway 定时调度，排空积压）
    → drain_group() 多批排空（每批内部仍走 consolidate_group）
    → backlog() 读取剩余积压用于日志与可观测性
"""
import asyncio
import contextlib
import json
import re
import sqlite3
import uuid
from datetime import datetime
from typing import Optional

from nonebot import logger

from config import (
    CONSOLIDATION_BACKLOG_WARN,
    CONSOLIDATION_LM_STUDIO_API_KEY,
    CONSOLIDATION_LM_STUDIO_BASE_URL,
    CONSOLIDATION_LM_STUDIO_MODEL,
    CONSOLIDATION_LM_STUDIO_TEMPERATURE,
    CONSOLIDATION_LOCAL_BATCH_SIZE,
    CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE,
    CONSOLIDATION_LOCAL_MAX_TOKENS,
    CONSOLIDATION_OVERLAP,
    DB_PATH,
    MEMORY_CANDIDATE_EVIDENCE_MAX_CHARS,
    MEMORY_CANDIDATE_REOCCURRENCE_BONUS,
    MEMORY_EXTRACT_ENABLED,
    MEMORY_EXTRACT_LM_STUDIO_API_KEY,
    MEMORY_EXTRACT_LM_STUDIO_BASE_URL,
    MEMORY_EXTRACT_LM_STUDIO_MODEL,
    MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE,
    MEMORY_EXTRACT_MAX_TOKENS,
    MEMORY_SOURCE_KIND_ENABLED,
)
from config.spaces import resolve_space
from core.llm import RESOURCE_CHAT, RESOURCE_CONSOLIDATION, acquire
from core.llm.lm_studio import LMStudioBackend
from memory.consolidation_log import append_consolidation_log
from memory.consolidation_prompt import format_consolidation_prompt
from memory.memory_manager import get_memory_manager
from memory.policy import validate_candidate
from memory.schema import (
    create_atomic_facts_table,
    create_memories_table,
    create_memory_candidates_table,
    create_user_profiles_table,
    ensure_v2_schema,
)
from memory.text_similarity import is_similar, merge_content

_consolidator_instance: Optional["MemoryConsolidator"] = None


class MemoryConsolidator:
    """群聊消息整合器。

    负责把「消息库」中积压的新消息批量总结为结构化记忆：
    - 短期上下文（short_term_context）
    - 用户画像（user_profiles）
    - 记忆候选（memory_candidates，后续由 MemoryManager 晋升为长期记忆）

    同时维护每群的 checkpoint，保证不重不漏地消费消息；整合固定使用本地
    LM Studio 后端（在线整合流程已废弃）。单例通过 get_consolidator() 获取。
    """

    def __init__(self):
        # 唯一后端：本地 LM Studio（使用整合专用配置，可与聊天用模型隔离，避免互相阻塞）
        self._backends: list[tuple[str, LMStudioBackend]] = [
            (
                "lm_studio",
                LMStudioBackend(
                    base_url=CONSOLIDATION_LM_STUDIO_BASE_URL,
                    model=CONSOLIDATION_LM_STUDIO_MODEL,
                    max_tokens=CONSOLIDATION_LOCAL_MAX_TOKENS,
                    temperature=CONSOLIDATION_LM_STUDIO_TEMPERATURE,
                    api_key=CONSOLIDATION_LM_STUDIO_API_KEY,
                ),
            )
        ]
        # 阶段2 候选提取后端：默认 27B（继承主聊天配置）。
        # E4B 能总结主题却系统性把候选提取判空（log_2026_8_16_1717：7 批全空，
        # 且信息明确出现在 active_summary 里——是「读到了但主动弃掉」而非没看到）。
        # 候选提取是高精度抽取任务，交给 27B；仅在阶段1 判定有自我披露时唤醒。
        self._extract_backend: tuple[str, LMStudioBackend] = (
            "lm_studio_extract",
            LMStudioBackend(
                base_url=MEMORY_EXTRACT_LM_STUDIO_BASE_URL,
                model=MEMORY_EXTRACT_LM_STUDIO_MODEL,
                max_tokens=MEMORY_EXTRACT_MAX_TOKENS,
                temperature=MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE,
                api_key=MEMORY_EXTRACT_LM_STUDIO_API_KEY,
            ),
        )
        # 群级锁：保证同一群「读 checkpoint → 整合 → 推进 checkpoint」不被并发打断。
        # 必须与模型锁分离——若整段整合都占着 consolidation 闸门，
        # 群A 等 27B（chat 闸门）时会把群B 的 E4B 阶段一起堵死，
        # 使两个模型退化为串行（多群部署下尤其明显）。
        self._group_locks: dict[str, asyncio.Lock] = {}

    def _get_group_lock(self, group_id: int) -> asyncio.Lock:
        """取该群的整合锁（懒建）。asyncio.Lock 的等待队列是 FIFO，
        因此同群多次触发天然按「先来后到」一次处理一个。"""
        key = str(group_id)
        lock = self._group_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._group_locks[key] = lock
        return lock

    async def _generate(self, group_id: int, last_id: int, force: bool = False) -> tuple[str, int, str, list, list, str]:
        """调用本地 LM Studio 后端生成整合输出。

        force=True 时走小批次（用于 @触发/主动发言前的轻量总结）。
        返回 (回复文本, 实际处理到的 batch_end, 实际使用的后端名, 本批发送者 QQ 号列表,
        AT_MENTION 来源发送者列表, 本批消息文本)，供调用方准确推进 checkpoint、
        对记忆候选做发送者白名单校验与来源分级，并把同一份消息文本交给阶段2 提取。
        """
        backend_name, backend = self._backends[0]
        limit = CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE if force else CONSOLIDATION_LOCAL_BATCH_SIZE
        messages, batch_end, senders, at_senders = self._fetch_next_messages(group_id, last_id, limit)
        if not messages:
            raise RuntimeError("没有可整合的消息")
        prompt = self._build_prompt(group_id, messages)
        logger.info(f"🌐 [Consolidator] 尝试 LLM: {backend_name}（{limit} 条）")
        model_tag = getattr(backend, "model", "") or backend_name
        # 只在真正调用 E4B 的这一刻持闸门：DB 读取与 prompt 拼装不占锁，
        # 且绝不与 chat 闸门同时持有（防止跨模型队头阻塞）。
        async with acquire(RESOURCE_CONSOLIDATION, tag=f"consolidate:{group_id}"):
            result = await backend.generate(prompt)
        append_consolidation_log(
            f"- **🧠 后端**: {backend_name}（{model_tag}，批次 {limit} 条）\n"
            f"  > 原始输出：\n  > {result.replace(chr(10), chr(10) + '  > ')}\n"
        )
        # 返回真实处理到的 batch_end、后端名、发送者列表与本批消息文本，
        # 供调用方准确推进 checkpoint 并做发送者白名单校验与阶段2 提取
        return result, batch_end, backend_name, senders, at_senders, messages

    def _build_prompt(self, group_id: int, messages: str) -> str:
        """用当前短期摘要 + 本批消息填充整合 prompt 模板。"""
        current_summary = self._fetch_current_summary(group_id)
        return format_consolidation_prompt(
            current_summary=current_summary or "（无）",
            messages=messages,
        )

    @staticmethod
    def _has_self_disclosure(parsed: dict) -> bool:
        """读取阶段1 输出的 has_self_disclosure（容错字符串/缺失）。
        缺失时保守返回 False——旧模型或异常输出不该误唤醒 27B。"""
        v = parsed.get("has_self_disclosure", False)
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("true", "1", "yes")

    async def _extract_candidates(self, group_id: int, messages_text: str) -> list | None:
        """阶段2：用 27B 从消息里精确提取 memory_candidates。

        只在调用 27B 的那一刻持有 chat 闸门（与聊天、会话压缩共用同一 GPU
        模型，应用层 FIFO 串行，聊天不会被并发推理拖慢）。此时绝不持有
        consolidation 闸门，因此别的群可同时跑 E4B 阶段1。

        返回候选列表；调用异常或 JSON 解析失败返回 None，表示「阶段2 未成功，
        回退阶段1 候选」——与「成功但无候选」（返回 []，即 27B 复核认为确实
        没有）区别处理。
        """
        from memory.extraction_prompt import format_extraction_prompt

        name, backend = self._extract_backend
        model_tag = getattr(backend, "model", "") or name
        prompt = format_extraction_prompt(messages_text)
        logger.info(f"🎯 [Extractor] 阶段2 候选提取：{name}（{model_tag}）")
        try:
            async with acquire(RESOURCE_CHAT, tag=f"extract:{group_id}"):
                result = await backend.generate(prompt)
        except Exception:
            logger.exception("❌ [Extractor] 阶段2 提取调用失败，回退阶段1 候选")
            append_consolidation_log(" > ❌ 阶段2（提取）调用失败，回退阶段1 候选\n")
            return None
        append_consolidation_log(
            f"- **🎯 阶段2 提取**: {name}（{model_tag}）\n"
            f" > 原始输出：\n > {result.replace(chr(10), chr(10) + ' > ')}\n"
        )
        parsed = self._parse_json(result)
        if not parsed:
            logger.warning(f"⚠️ [Extractor] 阶段2 JSON 解析失败，回退阶段1 候选: {result[:200]}")
            append_consolidation_log(" > ⚠️ 阶段2 JSON 解析失败，回退阶段1 候选\n")
            return None
        extracted = parsed.get("memory_candidates")
        return extracted if isinstance(extracted, list) else []

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
        """确保整合落库所需的公共表（短期上下文 / 消息 / 用户画像 / 记忆候选 / 记忆等）存在。
        先建基础表，再跑 v2 增量迁移补字段/索引（确保目标表已存在）。"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS short_term_context (
                group_id TEXT PRIMARY KEY,
                active_summary TEXT,
                pending_topic TEXT,
                recent_exchanges TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 旧库升级：short_term_context 缺少 recent_exchanges 列时补上（幂等，失败说明已存在）
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("ALTER TABLE short_term_context ADD COLUMN recent_exchanges TEXT")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT,
                user_id TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 用户画像表：复用 schema 的规范 DDL（v8 主键 (group_shared_space, user_id)），
        # 避免建表语句手抄两份导致加字段时漂移
        create_user_profiles_table(conn)
        # 记忆候选 / 长期记忆 / 原子事实：v8 起统一走 schema 规范 DDL（group_shared_space）
        create_memory_candidates_table(conn)
        create_memories_table(conn)
        create_atomic_facts_table(conn)
        # 常用检索索引（memories 按空间维度；messages 仍按 QQ 群）
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_space_user_status
            ON memories (group_shared_space, user_id, status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_space_status_accessed
            ON memories (group_shared_space, status, last_accessed_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_group_id
            ON messages (group_id, id)
        """)
        # v2 记忆系统：基础表建好后，增量迁移补新字段/索引（幂等）
        with contextlib.suppress(Exception):
            ensure_v2_schema(DB_PATH)

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

        两层归属（见 config/spaces.py）：checkpoint / 短期上下文按 **QQ 群**；
        画像 / 候选 / 长期记忆按 **共享空间**（group_shared_space）。
        """
        if not DB_PATH.exists():
            return

        # 群级串行（不再整段持有 consolidation 闸门）：模型闸门只在各自的
        # generate 调用处短暂持有，两把闸门从不同时持有，因此 E4B 与 27B
        # 可真正并行，且同一模型上的任务仍是 FIFO 一次一个。
        async with self._get_group_lock(group_id):
            try:
                # 空间归属：多个 QQ 群可映射到同一共享空间（隐式空间=群号字符串）
                group_shared_space = resolve_space(group_id)
                last_id = self._get_last_processed_id(group_id)
                new_count = self._count_new_messages(group_id, last_id)

                # 积压可观测性：checkpoint 已由 db_cleaner 保证在范围内，
                # 因此这里的大数是「整合跟不上摄入」而非越界。
                if new_count > CONSOLIDATION_BACKLOG_WARN:
                    logger.warning(
                        f"⚠️ [Consolidator] 群 {group_id} 整合积压 {new_count} 条"
                        f"（checkpoint={last_id}）。定时整合会逐批排空；"
                        f"若持续增长请调大 CONSOLIDATION_LOCAL_BATCH_SIZE "
                        f"或缩短 CONSOLIDATION_SCHEDULE_INTERVAL"
                    )

                # force 路径走小批次；非 force 路径按本地批次大小决定阈值
                threshold = CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE if force else CONSOLIDATION_LOCAL_BATCH_SIZE
                if new_count < threshold:
                    return

                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                append_consolidation_log(
                    f"### 🕒 [{now_str}] 群 `{group_id}`（空间 `{group_shared_space}`）开始整合"
                    f"（force={force}，新消息 {new_count}，批次阈值 {threshold}）\n"
                )

                result, processed_end, backend_name, senders, at_senders, messages_text = await self._generate(group_id, last_id, force=force)
                logger.info(f"📥 [Consolidator Response]\n{result}")

                parsed = self._parse_json(result)
                if not parsed:
                    logger.warning(f"⚠️ [Consolidator] JSON 解析失败，跳过本批次: {result[:200]}")
                    # 即使解析失败也推进 checkpoint，避免同一批消息反复重处理
                    append_consolidation_log("  > ⚠️ JSON 解析失败，已推进 checkpoint 避免重处理\n")
                    self._update_checkpoint(group_id, processed_end)
                    return

                self._write_short_term(group_id, parsed.get("short_term"))
                self._write_user_profiles(group_shared_space, parsed.get("user_profiles", []))
                candidates = parsed.get("memory_candidates")
                if candidates is None:
                    candidates = []

                # ── 阶段2：候选精确提取（27B）──
                # 仅在阶段1 判定 has_self_disclosure 为真时唤醒，节约 27B 占用。
                # 成功时其结果覆盖阶段1 候选——包括返回空数组的情况：
                # 那是 27B 复核认为确实没有，正好纠正 E4B 的误判。
                # 调用失败/解析失败返回 None，此时回退阶段1 候选。
                if MEMORY_EXTRACT_ENABLED and self._has_self_disclosure(parsed):
                    extracted = await self._extract_candidates(group_id, messages_text)
                    if extracted is not None:
                        candidates = extracted

                self._write_memory_candidates(group_shared_space, candidates, sender_ids=senders, at_senders=at_senders)
                if candidates:
                    # 有新候选记忆时同步触发 MemoryManager 晋升处理
                    get_memory_manager().process_new_candidates()
                elif parsed.get("long_term_memories"):
                    # 兼容旧版输出，将旧格式记忆写入旧表，以免丢失历史信息。
                    self._write_long_term_memories(group_shared_space, parsed.get("long_term_memories", []))
                self._update_checkpoint(group_id, processed_end)

                at_sender_set = set(at_senders or [])
                at_count = sum(
                    1 for c in candidates
                    if self._normalize_user_id(str(c.get("user_id", ""))) in at_sender_set
                )
                append_consolidation_log(
                    f"  > ✅ 整合完成（后端 {backend_name}，checkpoint {last_id} → {processed_end}，"
                    f"记忆候选 {len(candidates)} 条，其中 AT_MENTION 来源 {at_count} 条）\n"
                )
                logger.success(f"✅ [Consolidator] 群 {group_id}（空间 {group_shared_space}）整合完成，已处理至 id {processed_end}")
            except Exception:
                logger.exception(f"❌ [Consolidator] 群 {group_id} 整合失败")
                append_consolidation_log("  > ❌ 整合失败（详见控制台日志）\n")

    async def drain_group(self, group_id: int, max_rounds: int = 1) -> int:
        """连续整合该群的积压消息，最多 max_rounds 批；返回实际完成的批数。

        整合按批次推进（每批 CONSOLIDATION_LOCAL_BATCH_SIZE 条），单次 @ 触发
        只能消化一批。积压较多时靠定时任务多批排空——否则积压会一直增长，
        直到超过 MESSAGE_CLEANUP_KEEP_COUNT 被清理丢弃。

        每批之间重新读取 checkpoint：consolidate_group 会推进它，
        因此循环天然是增量的。任一批未达阈值即停止（说明已排空）。
        """
        rounds = 0
        for _ in range(max(1, max_rounds)):
            last_id = self._get_last_processed_id(group_id)
            if self._count_new_messages(group_id, last_id) < CONSOLIDATION_LOCAL_BATCH_SIZE:
                break
            before = last_id
            await self.consolidate_group(group_id)
            # checkpoint 未推进说明这批失败了（解析失败已自行推进，此处指异常）
            if self._get_last_processed_id(group_id) <= before:
                logger.warning(f"⚠️ [Consolidator] 群 {group_id} 批次未推进，停止本轮排空")
                break
            rounds += 1
        return rounds

    def backlog(self, group_id: int) -> int:
        """该群当前积压的未整合消息数。"""
        return self._count_new_messages(group_id, self._get_last_processed_id(group_id))

    def _fetch_next_messages(self, group_id: int, last_id: int, limit: int) -> tuple[str, int, list, list]:
        """取 last_id 之后最多 limit 条消息（含 overlap 上下文）。
        返回 (文本, 本批次末尾的最大消息 id, 本批次的发送者 QQ 号列表, AT_MENTION 来源的发送者列表)。
        按实际行数取，可容忍 id 空洞。
        消息文本拼装（MEMORY_SOURCE_KIND_ENABLED 开启时）：
        - BOT_SELF   → 「不属于任何用户」标注，只作上下文，绝不作为候选来源；
        - AT_MENTION → 「[对Bot说]」标注来源；
        - PASSIVE    → 保持原格式不带标记。
        关闭时全部退回「消息ID(id) 用户(QQ号): 内容」原格式。
        两个发送者列表都排除 BOT_SELF：senders 是 _write_memory_candidates 的
        发送者白名单，Bot 的 QQ 号一旦进入名单，「Bot 把自己说的话记成用户属性」
        就无法被代码层拦截。旧 messages 表没有 source_kind 列时回退到旧查询，
        全部视为 PASSIVE。
        """
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
            return "", last_id, [], []

        batch_end = new_ids[-1]
        fetch_from = max(0, last_id - CONSOLIDATION_OVERLAP)
        try:
            cursor.execute(
                f"SELECT id, user_id, content, source_kind FROM {message_table} WHERE group_id = ? AND id > ? AND id <= ? ORDER BY id ASC",
                (str(group_id), fetch_from, batch_end),
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            # 旧 messages 表没有 source_kind 列，回退到旧查询，全部视为 PASSIVE
            cursor.execute(
                f"SELECT id, user_id, content FROM {message_table} WHERE group_id = ? AND id > ? AND id <= ? ORDER BY id ASC",
                (str(group_id), fetch_from, batch_end),
            )
            rows = [(mid, uid, content, "PASSIVE") for mid, uid, content in cursor.fetchall()]
        conn.close()
        if not rows:
            return "", last_id, [], []
        lines = []
        for mid, uid, content, source_kind in rows:
            if not MEMORY_SOURCE_KIND_ENABLED:
                lines.append(f"消息ID({mid}) 用户({uid}): {content}")
            elif source_kind == "BOT_SELF":
                # Bot 自己的发言：给出语境（否则用户的「对」「是的」无从理解），
                # 但绝不能成为候选来源。
                # 用完整中文标签而非「我说」——「[我说]:」这种没有 QQ 号的格式会让
                # 小模型把「我说」当成 user_id 填进 recent_exchanges（见 log_2026_8_16_1717），
                # 换成结构上不可能被误当作 QQ 号的显式说明。
                lines.append(f"消息ID({mid}) [这是机器人自己发送的消息，不属于任何用户]: {content}")
            elif source_kind == "AT_MENTION":
                lines.append(f"消息ID({mid}) 用户({uid}) [对Bot说]: {content}")
            else:
                lines.append(f"消息ID({mid}) 用户({uid}): {content}")
        text = "\n".join(lines)
        senders = list(
            dict.fromkeys(
                str(uid) for _, uid, _, kind in rows if kind != "BOT_SELF"
            )
        )
        at_senders = list(
            dict.fromkeys(
                str(uid) for _, uid, _, source_kind in rows if source_kind == "AT_MENTION"
            )
        )
        return text, batch_end, senders, at_senders

    def _fetch_current_summary(self, group_id: int) -> str:
        """读取当前群的短期摘要（active_summary）及其关键发言，无记录或表不存在时返回空串。

        返回内容会把 recent_exchanges 一并带上（带说话人归属），
        供下一批整合 prompt 保持"谁说了什么"的连续性。
        """
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT active_summary, pending_topic, recent_exchanges FROM short_term_context WHERE group_id = ?",
                (str(group_id),),
            )
            row = cursor.fetchone()
            if not row:
                return ""
            parts = []
            if row[0]:
                parts.append(f"对话摘要: {row[0]}")
            if row[1] and row[1] != "无":
                parts.append(f"进行中的话题: {row[1]}")
            if len(row) > 2 and row[2]:
                try:
                    exchanges = json.loads(row[2])
                    if exchanges:
                        lines = []
                        for e in exchanges:
                            uid = (e or {}).get("user_id", "")
                            content = (e or {}).get("content", "")
                            if uid and content:
                                lines.append(f"用户({uid}): {content}")
                        if lines:
                            parts.append("近期关键发言:\n" + "\n".join(lines))
                except (json.JSONDecodeError, TypeError):
                    pass
            return "\n".join(parts)
        except sqlite3.OperationalError:
            # 旧库可能没有 recent_exchanges 列，回退到仅读取摘要
            try:
                cursor.execute(
                    "SELECT active_summary, pending_topic FROM short_term_context WHERE group_id = ?",
                    (str(group_id),),
                )
                row = cursor.fetchone()
                if not row:
                    return ""
                parts = []
                if row[0]:
                    parts.append(f"对话摘要: {row[0]}")
                if row[1] and row[1] != "无":
                    parts.append(f"进行中的话题: {row[1]}")
                return "\n".join(parts)
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

    def _write_short_term(self, group_id: int, data: dict | None):
        """写入短期上下文（摘要 + 进行中的话题 + 关键发言），data 为空则跳过；使用 upsert。

        recent_exchanges 会以 JSON 数组落库（每条 {user_id, content}），
        供 build_context 拼回带说话人归属的上下文，避免聊天模型张冠李戴。
        """
        if not data:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        self._ensure_common_tables(conn)
        # 规范化 recent_exchanges：只保留含 user_id 与 content 的条目，防止脏数据
        exchanges = data.get("recent_exchanges") or []
        normalized: list[dict] = []
        for e in exchanges:
            if not isinstance(e, dict):
                continue
            uid = self._normalize_user_id(str(e.get("user_id", "")))
            content = (e.get("content", "") or "").strip()
            if uid and content:
                normalized.append({"user_id": uid, "content": content})
        exchanges_json = json.dumps(normalized, ensure_ascii=False) if normalized else "[]"
        cursor.execute("""
            INSERT INTO short_term_context (group_id, active_summary, pending_topic, recent_exchanges, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(group_id) DO UPDATE SET
                active_summary = excluded.active_summary,
                pending_topic = excluded.pending_topic,
                recent_exchanges = excluded.recent_exchanges,
                updated_at = CURRENT_TIMESTAMP
        """, (
            str(group_id),
            data.get("active_summary", ""),
            data.get("pending_topic", "无"),
            exchanges_json,
        ))
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

    def _write_user_profiles(self, group_shared_space: str, profiles: list):
        """把 LLM 给出的用户画像批量写入 user_profiles：已存在则合并特征并累计互动次数。
        写入前用 stable_profile_facts 过滤人格判断/心理状态，只保留稳定事实（User Profile 治理）。
        画像按 (group_shared_space, user_id) 隔离——同一空间内的多个 QQ 群共享一份画像，
        不同空间彼此独立；interaction_count 也分空间计数。
        副作用：更新/插入 user_profiles 表；单条记录 user_id 非法（空）时跳过。"""
        from memory.policy import stable_profile_facts

        if not profiles:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        self._ensure_common_tables(conn)
        for p in profiles:
            uid = self._normalize_user_id(str(p.get("user_id", "")))
            if not uid:
                continue
            # 只保留稳定事实，过滤人格/心理/价值判断
            traits = "，".join(stable_profile_facts(p.get("personality_traits", "")))
            cursor.execute(
                "SELECT nickname, personality_traits, agent_attitude, interaction_count "
                "FROM user_profiles WHERE group_shared_space = ? AND user_id = ?",
                (group_shared_space, uid),
            )
            row = cursor.fetchone()
            if row:
                old_nick, old_traits, old_attitude, old_count = row
                # 新值优先，缺失字段则保留旧值；特征合并去重
                new_nick = p.get("nickname", "") or old_nick
                new_traits = self._merge_traits(old_traits, traits)
                new_attitude = self._merge_traits(old_attitude, p.get("agent_attitude", ""))
                cursor.execute("""
                    UPDATE user_profiles
                    SET nickname = ?, personality_traits = ?, agent_attitude = ?,
                        interaction_count = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE group_shared_space = ? AND user_id = ?
                """, (new_nick, new_traits, new_attitude, old_count + 1, group_shared_space, uid))
            else:
                # 新用户：直接插入，互动次数初始为 1
                cursor.execute("""
                    INSERT INTO user_profiles (group_shared_space, user_id, nickname, personality_traits, agent_attitude, interaction_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                """, (group_shared_space, uid, p.get("nickname", ""), traits, p.get("agent_attitude", "")))
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

    @staticmethod
    def _merge_source_kinds(old, new_kind: str) -> str:
        """把本次来源并入历次来源集合（JSON 数组，去重保序）。

        晋升判定看的是「历次证据里有没有 AT_MENTION」，因此必须累积而非覆盖：
        一条事实先在群聊被动提到、后来用户又直接对 Bot 说过，两次证据的
        权重不同，只保留最后一次会丢失关键信息。
        """
        kinds: list[str] = []
        try:
            parsed = json.loads(old or "[]")
            if isinstance(parsed, list):
                kinds = [str(k).strip().upper() for k in parsed if str(k).strip()]
        except (ValueError, TypeError):
            kinds = []
        kind = (new_kind or "PASSIVE").strip().upper()
        if kind not in kinds:
            kinds.append(kind)
        return json.dumps(kinds or ["PASSIVE"], ensure_ascii=False)

    @staticmethod
    def _merge_source_ids(old: str, new: str) -> str:
        """合并两批 source_message_ids（JSON 数组），取并集去重保序。"""
        def _parse(value) -> list[str]:
            try:
                parsed = json.loads(value or "[]")
                return [str(x) for x in parsed if str(x).strip()] if isinstance(parsed, list) else []
            except (ValueError, TypeError):
                return []

        merged: list[str] = []
        for mid in _parse(old) + _parse(new):
            if mid not in merged:
                merged.append(mid)
        return json.dumps(merged, ensure_ascii=False)

    def _write_memory_candidates(self, group_shared_space: str, candidates: list, sender_ids: list | None = None, at_senders: list | None = None):
        """把 LLM 给出的记忆候选写入 memory_candidates 表（状态 NEW），供 MemoryManager 晋升。
        数据清洗：user_id 规范化、type 大写、importance/confidence 转浮点、source_message_ids 序列化。
        每个候选先经过 Policy Validator（validate_candidate）审核，自动修正错误的
        usage/visibility 分类（如「不喜欢摸头」被误标为 TOPIC_START → 强制改为
        BOUNDARY_PROTECTION + RESTRICTED）。
        sender_ids 为当前批次的实际发送者 QQ 号白名单：候选的 user_id 不在名单内一律丢弃，
        防止 LLM 把 A 的发言归属给 B 造成长期记忆张冠李戴。
        at_senders 为 AT_MENTION 来源发送者列表：候选的 user_id 在其中时标记 source_kind
        为 AT_MENTION，否则为 PASSIVE。

        候选强化（交叉验证）：同空间同用户同类型且内容相似的待处理候选（NEW/OBSERVING）
        不重复插入，改为累积证据——occurrence_count +1、confidence 加
        MEMORY_CANDIDATE_REOCCURRENCE_BONUS、source_kinds 并集、status 回 NEW。
        这是「单次陈述不足以晋升，复现才是证据」的实现基础（见 MemoryManager Gate 1）。
        """
        if not candidates:
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        self._ensure_common_tables(conn)
        at_sender_set = set(at_senders or [])
        for c in candidates:
            uid = self._normalize_user_id(str(c.get("user_id", "")))
            if not uid:
                continue
            # 发送者白名单校验：只接受本批消息中真实出现过的人
            if sender_ids and uid not in set(sender_ids):
                logger.warning(f"⚠️ [Consolidator] 丢弃归属不明的记忆候选（空间 {group_shared_space}，user_id={uid} 不在本批发送者中）")
                continue
            source_kind = "AT_MENTION" if uid in at_sender_set else "PASSIVE"
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

            # ── v2：Policy Validator 审核（Gate 3），修正 usage/visibility/behavior_rule ──
            validated = validate_candidate({
                "type": type_,
                "content": content,
                "usage_tags": c.get("usage_tags"),
                "visibility": c.get("visibility"),
                "behavior_rule": c.get("behavior_rule"),
                "confidence": confidence,
                "importance": importance,
            })
            usage_tags = json.dumps(validated.get("usage_tags") or [], ensure_ascii=False)
            visibility = validated.get("visibility", "OPEN")
            behavior_rule = (validated.get("behavior_rule") or "").strip()
            confidence = float(validated.get("confidence", confidence))
            importance = float(validated.get("importance", importance))

            # ── 候选强化（交叉验证）：先找同空间同用户同类型的待处理候选 ──
            # 命中则累积证据（occurrence_count +1、confidence 加成、status 回 NEW
            # 重新参与晋升评估），而不是插入新行。否则同一事实会反复以新 uuid
            # 落库、各自卡在 OBSERVING，交叉验证永远不成立。
            existing = None
            for row in cursor.execute(
                "SELECT id, content, confidence, importance, evidence, occurrence_count, "
                "source_message_ids, source_kinds FROM memory_candidates "
                "WHERE group_shared_space = ? AND user_id = ? AND type = ? AND status IN ('NEW', 'OBSERVING')",
                (group_shared_space, uid, type_),
            ).fetchall():
                if is_similar(content, row[1] or ""):
                    existing = row
                    break

            if existing is not None:
                (
                    existing_id,
                    old_content,
                    old_conf,
                    old_imp,
                    old_evidence,
                    old_count,
                    old_source_ids,
                    old_source_kinds,
                ) = existing
                merged_confidence = min(
                    1.0,
                    max(float(old_conf or 0.0), confidence) + MEMORY_CANDIDATE_REOCCURRENCE_BONUS,
                )
                merged_evidence = merge_content(old_evidence or "", evidence)
                if len(merged_evidence) > MEMORY_CANDIDATE_EVIDENCE_MAX_CHARS:
                    merged_evidence = merged_evidence[:MEMORY_CANDIDATE_EVIDENCE_MAX_CHARS] + "…"
                new_count = int(old_count or 1) + 1
                cursor.execute(
                    "UPDATE memory_candidates SET content = ?, confidence = ?, importance = ?, "
                    "evidence = ?, occurrence_count = ?, source_message_ids = ?, source_kinds = ?, "
                    "usage_tags = ?, visibility = ?, behavior_rule = ?, source_kind = ?, "
                    "status = 'NEW', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (
                        merge_content(old_content or "", content),
                        merged_confidence,
                        max(float(old_imp or 0.0), importance),
                        merged_evidence,
                        new_count,
                        self._merge_source_ids(old_source_ids, source_ids),
                        self._merge_source_kinds(old_source_kinds, source_kind),
                        usage_tags,
                        visibility,
                        behavior_rule,
                        source_kind,
                        existing_id,
                    ),
                )
                logger.info(
                    f"🔁 [Consolidator] 候选获得新证据 {existing_id}（第 {new_count} 次，"
                    f"conf {float(old_conf or 0.0):.2f} → {merged_confidence:.2f}，来源 {source_kind}）"
                )
                continue

            # 无 id 时生成本地候选 id
            candidate_id = str(c.get("id", "")) or uuid.uuid4().hex
            cursor.execute("""
                INSERT INTO memory_candidates (id, group_shared_space, user_id, type, content, importance, confidence, evidence, status, source_message_ids, usage_tags, visibility, behavior_rule, source_kind, occurrence_count, first_seen_at, source_kinds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(id) DO UPDATE SET
                    group_shared_space = excluded.group_shared_space,
                    user_id = excluded.user_id,
                    type = excluded.type,
                    content = excluded.content,
                    importance = excluded.importance,
                    confidence = excluded.confidence,
                    evidence = excluded.evidence,
                    status = excluded.status,
                    source_message_ids = excluded.source_message_ids,
                    usage_tags = excluded.usage_tags,
                    visibility = excluded.visibility,
                    behavior_rule = excluded.behavior_rule,
                    source_kind = excluded.source_kind,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                candidate_id,
                group_shared_space,
                uid,
                type_,
                content,
                importance,
                confidence,
                evidence,
                "NEW",
                source_ids,
                usage_tags,
                visibility,
                behavior_rule,
                source_kind,
                self._merge_source_kinds("[]", source_kind),
            ))
        conn.commit()
        conn.close()

    def _write_long_term_memories(self, group_shared_space: str, memories: list):
        """兼容旧版整合输出：把旧格式的 long_term_memories 写入旧表 long_term_memories。
        仅保留 importance>=5 且有摘要的记录；同空间同用户同摘要去重。

        ⚠️ 本表为待废弃的旧兼容表：列名仍是 ``group_id``（不给将淘汰的表做重命名），
        但写入的值是**空间标识**（group_shared_space）——与检索侧一致，
        retriever 的兜底查询会用 space 去查它。新记忆一律走 memories 表。
        """
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
            # 去重：同空间、同用户、摘要完全相同则跳过
            cursor.execute(
                "SELECT id FROM long_term_memories WHERE group_id = ? AND user_id = ? AND summary = ?",
                (group_shared_space, uid, summary),
            )
            if cursor.fetchone():
                continue
            cursor.execute("""
                INSERT INTO long_term_memories (group_id, user_id, summary, importance, access_count, last_accessed_at)
                VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
            """, (group_shared_space, uid, summary, importance))
        conn.commit()
        conn.close()

    def _parse_json(self, text: str) -> dict | None:
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
# 每群已在排队/执行中的整合任务标记：防止活跃群每条消息都触发、堆出一长串
# 等同一把群级锁的任务（每群最多 1 个在途，最大排队数 = 群数）。
_pending_groups: set[str] = set()


def get_consolidator() -> MemoryConsolidator:
    """返回进程级单例 MemoryConsolidator（懒初始化）。"""
    global _consolidator_instance
    if _consolidator_instance is None:
        _consolidator_instance = MemoryConsolidator()
    return _consolidator_instance


def maybe_consolidate(group_id: int, force: bool = False):
    """异步触发一次群整合（后台任务），并登记以跟踪完成与否（不等待）。

    force=True 走本地小批次轻量总结，适合 @触发 / 主动发言前调用。


    同群合并：该群已有整合任务在排队或执行时直接跳过。否则活跃群里每条消息
    都触发一次，会堆出一长串等同一把群级锁的任务——既浪费，也让「先来后到」
    失去意义：排在后面的任务醒来时 checkpoint 早已被前面的推进，无事可做。
    """
    key = str(group_id)
    if key in _pending_groups:
        logger.debug(f"⏭️ [Consolidator] 群 {group_id} 已有整合任务在途，跳过本次触发")
        return
    _pending_groups.add(key)
    consolidator = get_consolidator()
    task = asyncio.create_task(consolidator.consolidate_group(group_id, force=force))
    _consolidation_tasks.add(task)

    def _done(t: asyncio.Task):
        _consolidation_tasks.discard(t)
        _pending_groups.discard(key)

    task.add_done_callback(_done)
