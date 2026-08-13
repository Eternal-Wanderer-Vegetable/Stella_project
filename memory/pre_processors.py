# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""
对话前处理器（Pre-processors）模块。

本模块位于记忆工作流的“读取侧 + 写入侧入口”：
- record_message：把每条群聊消息落库（group_messages，新消息统一写此，messages 为旧版回退）；
- build_context：为每次回复组装短期上下文——话题层摘要 + 最近 RECENT_TAIL_LIMIT 条
  原始消息尾巴（可并存，recent_exchanges 仅在无尾巴时兜底）；
- build_user_context：组装用户画像与长期记忆——@-回复时读用户画像 + 该用户相关记忆，
  主动发言时用群级记忆回顾；
- _extract_keywords / _STOP_WORDS：中文停用词与关键词提取，供记忆话题匹配使用。
"""
import contextlib
import json
import re
import sqlite3

from nonebot import logger

from config import (
    DB_PATH,
    MEMORY_V2_ENABLED,
    PROACTIVE_LONG_TERM_LIMIT,
    RECENT_TAIL_LIMIT,
    REPLY_LONG_TERM_LIMIT,
)
from core.context import ChatContext
from memory.prompt_builder import build_memory_context
from memory.retriever import get_group_memories, get_related_memories, get_user_memories
from memory.schema import normalize_source_kind


async def record_message(ctx: ChatContext) -> ChatContext:
    """把本条消息写入群消息表（group_messages），供后续整合器消费。

    source_kind 由调用方（ai_gateway）按 event.is_tome() 决定：
    AT_MENTION=用户直接对 Bot 说，Bot 自己的发言传 BOT_SELF，其余为 PASSIVE。

    参数：ctx — 拥有 group_id / user_id / message 的上下文字段；
    副作用：插入一条群消息记录并建表（幂等）；
    返回：原样的 ctx（调用方无需依赖返回值做后续处理）。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT,
                user_id TEXT,
                content TEXT,
                source_kind TEXT DEFAULT 'PASSIVE',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 老库的 group_messages 已存在且 ensure_v2_schema 可能晚于首条消息执行，
        # 这里自补一次 source_kind 列（失败即说明列已存在）
        with contextlib.suppress(sqlite3.OperationalError):
            cursor.execute("ALTER TABLE group_messages ADD COLUMN source_kind TEXT DEFAULT 'PASSIVE'")
        # messages 表为旧版兼容（只读回退），新消息统一写入 group_messages
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT,
                user_id TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_messages_group_id
            ON group_messages (group_id, id)
        """)
        cursor.execute("""
            INSERT INTO group_messages (group_id, user_id, content, source_kind)
            VALUES (?, ?, ?, ?)
        """, (str(ctx.group_id), str(ctx.user_id), ctx.message,
              normalize_source_kind(ctx.source_kind)))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"记录消息失败: {e}")
    return ctx


async def build_context(ctx: ChatContext) -> ChatContext:
    """组装短期上下文：话题层摘要 + 最近原始消息尾巴（可同时存在）。

    参数：ctx — 会被写入 ctx.short_term；
    副作用：向 ctx.short_term 写入文本（读取 DB，不写库）；
    返回：ctx。
    """
    if not DB_PATH.exists():
        return ctx
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # ── 1) 短期摘要：只取「话题层」信息（active_summary / pending_topic） ──
        active_summary = pending_topic = ""
        try:
            cursor.execute(
                "SELECT active_summary, pending_topic FROM short_term_context WHERE group_id = ?",
                (str(ctx.group_id),),
            )
            row = cursor.fetchone()
            if row:
                active_summary, pending_topic = (row[0] or ""), (row[1] or "")
        except sqlite3.OperationalError:
            pass

        # ── 2) 最近原始消息（含 Bot 自己的发言，带来源标注） ──
        tail = _fetch_recent_tail(cursor, ctx.group_id, RECENT_TAIL_LIMIT)

        # ── 3) recent_exchanges 只在没有原始尾巴时兜底 ──
        # 它是整合器产出的滞后快照，与原始尾巴并存会出现同一段对话的两个版本，
        # 模型会以摘要为准从而接错话题（2026-08-13 bug）。
        exchanges_text = "" if tail else _fetch_recent_exchanges_text(cursor, ctx.group_id)

        conn.close()

        parts: list[str] = []
        if active_summary:
            parts.append(f"对话摘要: {active_summary}")
        if pending_topic and pending_topic != "无":
            parts.append(f"进行中的话题: {pending_topic}")
        if exchanges_text:
            parts.append("近期关键发言:\n" + exchanges_text)
        if tail:
            parts.append("最近的对话（时间正序，「我」是你自己说过的话）:\n" + tail)

        if parts:
            ctx.short_term = "\n".join(parts)
            logger.info(
                f"🧠 [Context] 摘要={'有' if active_summary else '无'} "
                f"原始尾巴={len(tail.splitlines()) if tail else 0} 条"
            )
    except Exception as e:
        logger.warning(f"读取上下文异常（跳过）: {e}")
    return ctx


def _fetch_recent_tail(cursor: sqlite3.Cursor, group_id: int, limit: int) -> str:
    """取最近 limit 条原始消息，按时间正序拼成文本。

    Bot 自己的发言（source_kind=BOT_SELF）渲染为「我」，让聊天模型知道自己
    刚说过什么——否则用户的简短回应（「手机」「对」）会被接到上一个话题上。
    旧库没有 source_kind 列时回退为全部按用户渲染。
    """
    if limit <= 0:
        return ""
    try:
        rows = cursor.execute(
            "SELECT user_id, content, source_kind FROM group_messages "
            "WHERE group_id = ? ORDER BY id DESC LIMIT ?",
            (str(group_id), limit),
        ).fetchall()
    except sqlite3.OperationalError:
        try:
            rows = [
                (uid, content, "PASSIVE")
                for uid, content in cursor.execute(
                    "SELECT user_id, content FROM group_messages "
                    "WHERE group_id = ? ORDER BY id DESC LIMIT ?",
                    (str(group_id), limit),
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            return ""
    if not rows:
        return ""
    rows.reverse()
    lines = [
        f"我: {content}" if kind == "BOT_SELF" else f"用户({uid}): {content}"
        for uid, content, kind in rows
        if (content or "").strip()
    ]
    return "\n".join(lines)


def _fetch_recent_exchanges_text(cursor: sqlite3.Cursor, group_id: int) -> str:
    """读整合器产出的 recent_exchanges（带说话人归属），拼成文本；无则空串。"""
    try:
        raw = cursor.execute(
            "SELECT recent_exchanges FROM short_term_context WHERE group_id = ?",
            (str(group_id),),
        ).fetchone()
    except sqlite3.OperationalError:
        return ""
    if not raw or not raw[0]:
        return ""
    try:
        parsed = json.loads(raw[0])
    except (json.JSONDecodeError, TypeError):
        return ""
    lines = [
        f"用户({e.get('user_id')}): {e.get('content')}"
        for e in parsed
        if isinstance(e, dict) and e.get("user_id") and e.get("content")
    ]
    return "\n".join(lines)


async def build_user_context(ctx: ChatContext) -> ChatContext:
    """组装用户画像与长期记忆上下文（写到 ctx.user_profile / ctx.memories_for_prompt）。

    参数：ctx — 触发方式（ctx.trigger）决定走主动发言还是 @-回复路径；
    副作用：写入 ctx.user_profile（画像段落）与 ctx.memories_for_prompt（记忆列表）；
    返回：ctx。

    v2：当 MEMORY_V2_ENABLED 时走记忆系统 v2 检索（Context-aware Memory Activation），
    把结果写入 ctx.conversation_memories / ctx.behavior_constraints / ctx.memory_mode /
    ctx.memory_trace，供 pipeline 做分区注入。
    """
    if not DB_PATH.exists():
        return ctx

    if MEMORY_V2_ENABLED:
        return await _build_user_context_v2(ctx)

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        parts = []

        is_proactive = ctx.trigger == "proactive"

        if not is_proactive:
            # ── @-回复：读取用户画像（性格 + 对 bot 态度） ──
            cursor.execute(
                "SELECT personality_traits, agent_attitude FROM user_profiles WHERE user_id = ?",
                (str(ctx.user_id),),
            )
            row = cursor.fetchone()
            if row:
                traits = []
                if row[0]:
                    traits.append(f"性格: {row[0]}")
                if row[1]:
                    traits.append(f"对bot态度: {row[1]}")
                if traits:
                    parts.append(f"关于用户{ctx.user_id}的了解: {'，'.join(traits)}")

        # ── 长期记忆 ──
        # 主动发言：回顾全群记忆；@-回复：检索该用户相关记忆 + 其他相关记忆
        if is_proactive:
            memories = get_group_memories(
                ctx.group_id,
                query=ctx.message,
                limit=PROACTIVE_LONG_TERM_LIMIT,
            )
            if memories:
                parts.append("最近的记忆回顾：\n" + build_memory_context(memories))
        else:
            user_memories = get_user_memories(
                ctx.group_id,
                ctx.user_id,
                query=ctx.message,
                limit=REPLY_LONG_TERM_LIMIT,
            )
            if user_memories:
                parts.append(
                    f"关于用户{ctx.user_id}的重要记忆：\n" + build_memory_context(user_memories)
                )

            related = get_related_memories(ctx.group_id, ctx.user_id, ctx.message, limit=3)
            if related:
                parts.append("其他相关记忆：\n" + build_memory_context(related))

        conn.close()

        if parts:
            # 结构化字段交给 prompt_builder 构建提示，不再写 ctx.context
            ctx.short_term = ctx.short_term or ""
            # 尝试提取关于用户的段落作为 user_profile（以 '关于用户' 开头的段落）
            up = ""
            for p in parts:
                if p.startswith((f"关于用户{ctx.user_id}", "关于用户", "关于当前用户")):
                    up = p
                    break
            ctx.user_profile = up
            # 构造用于 prompt 的 memories 列表（从之前检索得到的记忆片段）
            memories: list[dict] = []
            # 主动发言时 parts 中第一项为群记忆回顾（build_context 已把短期赋给 short_term）
            if ctx.trigger == "proactive":
                try:
                    memories = get_group_memories(
                        ctx.group_id,
                        query=ctx.message,
                        limit=PROACTIVE_LONG_TERM_LIMIT,
                    )
                except Exception:
                    memories = []
            else:
                try:
                    user_memories = get_user_memories(
                        ctx.group_id,
                        ctx.user_id,
                        query=ctx.message,
                        limit=REPLY_LONG_TERM_LIMIT,
                    )
                except Exception:
                    user_memories = []
                try:
                    related = get_related_memories(ctx.group_id, ctx.user_id, ctx.message, limit=3)
                except Exception:
                    related = []
                memories = (user_memories or []) + (related or [])
            ctx.memories_for_prompt = memories
    except Exception as e:
        logger.warning(f"读取用户画像异常（跳过）: {e}")
    return ctx


async def _build_user_context_v2(ctx: ChatContext) -> ChatContext:
    """记忆系统 v2 的上下文组装：Policy 检索 + 分区记忆 + 决策轨迹。"""
    from config import MEMORY_EMBEDDING_ENABLED
    from memory.retrieval_v2 import retrieve_memories

    # 先组装稳定画像（只读稳定事实，过滤人格判断）
    profile = _read_stable_profile(ctx.group_id, ctx.user_id)
    ctx.user_profile = profile

    # v2 检索（Context-aware Memory Activation）。
    # 开启 MEMORY_EMBEDDING_ENABLED 时走 embedding 语义分（失败自动回退规则版）。
    if MEMORY_EMBEDDING_ENABLED:
        from memory.retrieval_v2 import retrieve_memories_emb

        result = await retrieve_memories_emb(
            group_id=ctx.group_id,
            user_id=ctx.user_id,
            query=ctx.message,
            trigger=ctx.trigger,
        )
    else:
        result = retrieve_memories(
            group_id=ctx.group_id,
            user_id=ctx.user_id,
            query=ctx.message,
            trigger=ctx.trigger,
        )
    ctx.memory_mode = result.mode
    ctx.conversation_memories = result.conversation_memories
    ctx.behavior_constraints = result.behavior_constraints
    ctx.memory_trace = result.trace
    # 兼容旧字段（memories_for_prompt），供仍读取它的模块使用
    ctx.memories_for_prompt = result.conversation_memories

    if ctx.conversation_memories or ctx.behavior_constraints:
        logger.info(
            f"🧠 [Context v2] 模式={result.mode} 聊天素材={len(result.conversation_memories)} "
            f"行为约束={len(result.behavior_constraints)}"
        )
    return ctx


def _read_stable_profile(group_id: int, user_id: int) -> str:
    """读取用户画像，只保留「稳定事实」（语言偏好/技术水平/可观察行为），
    过滤人格判断与心理状态（见 Memory Policy / User Profile 治理方案）。"""
    from memory.policy import stable_profile_facts

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT personality_traits, agent_attitude FROM user_profiles WHERE user_id = ?",
            (str(user_id),),
        )
        row = cursor.fetchone()
        conn.close()
    except sqlite3.OperationalError:
        return ""
    if not row:
        return ""
    parts = []
    traits = stable_profile_facts(row[0] or "")
    if traits:
        parts.append(f"关于用户{user_id}的可观察特征: {'，'.join(traits)}")
    if row[1]:
        parts.append(f"对bot态度: {row[1]}")
    return "；".join(parts)


# 中文停用词（高频无意义词，匹配时排除）
_STOP_WORDS = frozenset(
    ["的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些", "什么", "怎么", "如何", "可以", "可能", "已经", "还", "但", "而", "且", "或", "虽然", "因为", "所以", "如果", "被", "把", "让", "从", "对", "为", "与", "向", "以", "及", "等", "之", "其", "此", "该", "本", "中", "里", "后", "前", "时", "年", "月", "日", "个", "些", "多", "少", "更", "最"]
)


def _extract_keywords(text: str, max_keywords: int) -> list[str]:
    """从中文文本中提取关键词（2-4 字词组），用于记忆话题匹配。

    算法：先按连续汉字段落（2-8 字）切分，长的再按 3-2 字滑动窗口切，过滤停用词，
    按出现频率降序取前 max_keywords 个。
    """
    # 提取连续中文字符片段
    segments = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    # 按 2-3 字切分
    candidates: list[str] = []
    for seg in segments:
        if len(seg) <= 4:
            candidates.append(seg)
        else:
            for size in (3, 2):
                for i in range(len(seg) - size + 1):
                    candidates.append(seg[i : i + size])
    # 过滤停用词，按出现次数取 top N
    freq: dict[str, int] = {}
    for c in candidates:
        if c not in _STOP_WORDS:
            freq[c] = freq.get(c, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [word for word, _ in ranked[:max_keywords]]
