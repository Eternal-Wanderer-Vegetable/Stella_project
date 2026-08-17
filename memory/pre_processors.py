# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""
对话前处理器（Pre-processors）模块。

本模块位于记忆工作流的“读取侧 + 写入侧入口”：
- record_message：把每条群聊消息落库（group_messages，新消息统一写此，messages 为旧版回退）；
- build_context：为每次回复组装短期上下文——话题层摘要（过期时标注时长）+ 最近
  RECENT_TAIL_LIMIT 条原始消息尾巴（按时间窗过滤、内部空白处标注断层）；
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
    RECENT_TAIL_GAP_MARK_MINUTES,
    RECENT_TAIL_LIMIT,
    RECENT_TAIL_MAX_AGE_MINUTES,
    REPLY_LONG_TERM_LIMIT,
    SHORT_TERM_SUMMARY_STALE_MINUTES,
)
from config.spaces import resolve_space
from core.context import ChatContext
from memory.prompt_builder import build_memory_context
from memory.retriever import get_group_memories, get_related_memories, get_user_memories
from memory.schema import normalize_source_kind
from memory.session_context import ensure_initialized as session_ensure_initialized
from memory.session_context import get_summary as get_session_summary
from memory.timeutil import (
    humanize_duration,
    parse_db_timestamp,
    seconds_since,
    utc_now,
)


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

    摘要过期时改用「之前的话题」标题并注明时长；尾巴按时间窗过滤并在
    内部空白处插入断层标记。

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
        summary_age: str | None = None
        try:
            cursor.execute(
                "SELECT active_summary, pending_topic, updated_at FROM short_term_context "
                "WHERE group_id = ?",
                (str(ctx.group_id),),
            )
            row = cursor.fetchone()
            if row:
                active_summary, pending_topic = (row[0] or ""), (row[1] or "")
                # 摘要由整合器产出、按设计滞后。不标注新鲜度会让模型
                # 把几小时前的话题当成当前话题。
                elapsed = seconds_since(row[2]) if len(row) > 2 else None
                if (
                    elapsed is not None
                    and SHORT_TERM_SUMMARY_STALE_MINUTES > 0
                    and elapsed > SHORT_TERM_SUMMARY_STALE_MINUTES * 60.0
                ):
                    summary_age = humanize_duration(elapsed)
        except sqlite3.OperationalError:
            pass

        # ── 2) 最近原始消息（含 Bot 自己的发言，带来源标注） ──
        tail, tail_start_id = _fetch_recent_tail(cursor, ctx.group_id, RECENT_TAIL_LIMIT)

        # ── 2.5) 会话摘要：覆盖已滚出尾巴窗口的较早内容 ──
        # 先对齐起点再取摘要：首次使用时把已压缩位置对齐到尾巴起点，
        # 避免把整个历史当成待压缩内容。
        if tail_start_id > 0:
            session_ensure_initialized(ctx.group_id, tail_start_id)
        session_summary = get_session_summary(ctx.group_id)
        # 供 post 侧触发压缩（回复发出后异步进行，不阻塞本次回复）
        ctx.tail_start_id = tail_start_id

        # ── 3) recent_exchanges 只在没有原始尾巴时兜底 ──
        # 它是整合器产出的滞后快照，与原始尾巴并存会出现同一段对话的两个版本，
        # 模型会以摘要为准从而接错话题（2026-08-13 bug）。
        exchanges_text = "" if tail else _fetch_recent_exchanges_text(cursor, ctx.group_id)

        conn.close()

        parts: list[str] = []
        if active_summary:
            if summary_age:
                parts.append(f"之前的话题（{summary_age}前）: {active_summary}")
            else:
                parts.append(f"对话摘要: {active_summary}")
        if pending_topic and pending_topic != "无":
            # 摘要已过期时，「进行中的话题」同样不再是进行中
            label = "之前未聊完的话题" if summary_age else "进行中的话题"
            parts.append(f"{label}: {pending_topic}")
        if exchanges_text:
            parts.append("近期关键发言:\n" + exchanges_text)
        if session_summary:
            parts.append("本场对话较早的内容（已压缩）:\n" + session_summary)
        if tail:
            parts.append("最近的对话（时间正序，「我」是你自己说过的话）:\n" + tail)

        if parts:
            ctx.short_term = "\n".join(parts)
            logger.info(
                f"🧠 [Context] 摘要={'过期' if summary_age else '有' if active_summary else '无'} "
                f"原始尾巴={len(tail.splitlines()) if tail else 0} 行"
                f"{' 会话摘要=有' if session_summary else ''}"
            )
    except Exception as e:
        logger.warning(f"读取上下文异常（跳过）: {e}")
    return ctx


def _fetch_recent_tail(cursor: sqlite3.Cursor, group_id: int, limit: int) -> tuple[str, int]:
    """取最近 limit 条原始消息，按时间正序拼成文本。

    返回 ``(文本, 尾巴起点消息 id)``。起点 id 供会话压缩计算不重叠的待压缩
    区间——摘要必须严格覆盖尾巴之前的内容（见 memory/session_context.py）。
    无消息时返回 ``("", 0)``。

    三件事：

    1. **来源渲染**：Bot 自己的发言（BOT_SELF）渲染为「我」，让聊天模型知道
       自己刚说过什么——否则用户的简短回应（「手机」「对」）会被接到上一个话题上；
    2. **时间窗过滤**：超过 RECENT_TAIL_MAX_AGE_MINUTES 的消息不进尾巴。
       仅按 id 取最近 N 条时，停机数小时后重启会把几小时前的对话当成刚刚发生
       （2026-08-15 缺陷）；
    3. **断层标记**：相邻消息间隔超过 RECENT_TAIL_GAP_MARK_MINUTES 时插入一行
       说明。比直接丢弃更好——让模型知道「之前聊过但已经过去很久」。

    旧库没有 source_kind 列时回退为全部按用户渲染、且无时间信息。
    """
    if limit <= 0:
        return "", 0

    rows = _query_tail_rows(cursor, group_id, limit)
    if not rows:
        return "", 0
    rows.reverse()  # id 倒序 → 时间正序

    now = utc_now().timestamp()
    max_age = RECENT_TAIL_MAX_AGE_MINUTES * 60.0
    gap_threshold = RECENT_TAIL_GAP_MARK_MINUTES * 60.0

    lines: list[str] = []
    prev_epoch: float | None = None
    tail_start_id = 0
    for mid, uid, content, kind, ts in rows:
        text = (content or "").strip()
        if not text:
            continue

        epoch = parse_db_timestamp(ts)
        # 时间窗过滤：解析失败的消息（旧库无 timestamp）不过滤，保留原有行为
        if max_age > 0 and epoch is not None and (now - epoch) > max_age:
            continue

        # 起点取「第一条真正进入尾巴」的消息 id：被时间窗过滤掉的不算
        if tail_start_id == 0:
            tail_start_id = int(mid)

        # 断层标记：两条消息之间隔了很久，明确告诉模型中间有空白
        if (
            gap_threshold > 0
            and prev_epoch is not None
            and epoch is not None
            and (epoch - prev_epoch) > gap_threshold
        ):
            lines.append(f"（……中间隔了{humanize_duration(epoch - prev_epoch)}……）")

        lines.append(f"我: {text}" if kind == "BOT_SELF" else f"用户({uid}): {text}")
        if epoch is not None:
            prev_epoch = epoch

    return "\n".join(lines), tail_start_id


def _query_tail_rows(cursor: sqlite3.Cursor, group_id: int, limit: int) -> list[tuple]:
    """取尾巴原始行（id 倒序），带 id / source_kind / timestamp；旧库自动降级。

    返回 (id, user_id, content, source_kind, timestamp) 五元组列表。
    """
    try:
        return cursor.execute(
            "SELECT id, user_id, content, source_kind, timestamp FROM group_messages "
            "WHERE group_id = ? ORDER BY id DESC LIMIT ?",
            (str(group_id), limit),
        ).fetchall()
    except sqlite3.OperationalError:
        pass
    try:
        return [
            (mid, uid, content, "PASSIVE", ts)
            for mid, uid, content, ts in cursor.execute(
                "SELECT id, user_id, content, timestamp FROM group_messages "
                "WHERE group_id = ? ORDER BY id DESC LIMIT ?",
                (str(group_id), limit),
            ).fetchall()
        ]
    except sqlite3.OperationalError:
        pass
    try:
        return [
            (mid, uid, content, "PASSIVE", None)
            for mid, uid, content in cursor.execute(
                "SELECT id, user_id, content FROM group_messages "
                "WHERE group_id = ? ORDER BY id DESC LIMIT ?",
                (str(group_id), limit),
            ).fetchall()
        ]
    except sqlite3.OperationalError:
        return []


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

    # 共享空间：同一空间内的多个 QQ 群共享画像与记忆（M2.5-1 的 __post_init__ 应已填好，or 只是防御）
    space = ctx.group_shared_space or resolve_space(ctx.group_id)

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        parts = []

        is_proactive = ctx.trigger == "proactive"

        if not is_proactive:
            # ── @-回复：读取用户画像（性格 + 对 bot 态度） ──
            # 按共享空间隔离：同一空间内的多个 QQ 群共享一份画像
            cursor.execute(
                "SELECT personality_traits, agent_attitude FROM user_profiles WHERE group_shared_space = ? AND user_id = ?",
                (space, str(ctx.user_id)),
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
        # 主动发言：回顾全空间记忆；@-回复：检索该用户相关记忆 + 其他相关记忆
        if is_proactive:
            memories = get_group_memories(
                space,
                query=ctx.message,
                limit=PROACTIVE_LONG_TERM_LIMIT,
            )
            if memories:
                parts.append("最近的记忆回顾：\n" + build_memory_context(memories))
        else:
            user_memories = get_user_memories(
                space,
                ctx.user_id,
                query=ctx.message,
                limit=REPLY_LONG_TERM_LIMIT,
            )
            if user_memories:
                parts.append(
                    f"关于用户{ctx.user_id}的重要记忆：\n" + build_memory_context(user_memories)
                )

            related = get_related_memories(space, ctx.user_id, ctx.message, limit=3)
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
                        space,
                        query=ctx.message,
                        limit=PROACTIVE_LONG_TERM_LIMIT,
                    )
                except Exception:
                    memories = []
            else:
                try:
                    user_memories = get_user_memories(
                        space,
                        ctx.user_id,
                        query=ctx.message,
                        limit=REPLY_LONG_TERM_LIMIT,
                    )
                except Exception:
                    user_memories = []
                try:
                    related = get_related_memories(space, ctx.user_id, ctx.message, limit=3)
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

    # 共享空间：同一空间内的多个 QQ 群共享画像与记忆（M2.5-1 的 __post_init__ 应已填好，or 只是防御）
    space = ctx.group_shared_space or resolve_space(ctx.group_id)

    # 先组装稳定画像（只读稳定事实，过滤人格判断）
    profile = _read_stable_profile(space, ctx.user_id)
    ctx.user_profile = profile

    # v2 检索（Context-aware Memory Activation），按群组共享空间检索。
    # 开启 MEMORY_EMBEDDING_ENABLED 时走 embedding 语义分（失败自动回退规则版）。
    if MEMORY_EMBEDDING_ENABLED:
        from memory.retrieval_v2 import retrieve_memories_emb

        result = await retrieve_memories_emb(
            group_shared_space=space,
            user_id=ctx.user_id,
            query=ctx.message,
            trigger=ctx.trigger,
        )
    else:
        result = retrieve_memories(
            group_shared_space=space,
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
            f"🧠 [Context v2] 空间={space} 模式={result.mode} 聊天素材={len(result.conversation_memories)} "
            f"行为约束={len(result.behavior_constraints)}"
        )
    return ctx


def _read_stable_profile(group_shared_space: str, user_id: int) -> str:
    """读取用户画像，只保留「稳定事实」（语言偏好/技术水平/可观察行为），
    过滤人格判断与心理状态（见 Memory Policy / User Profile 治理方案）。
    按共享空间隔离——同一空间内的多个 QQ 群共享一份画像（v8 user_profiles 主键
    (group_shared_space, user_id)）。"""
    from memory.policy import stable_profile_facts

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT personality_traits, agent_attitude FROM user_profiles WHERE group_shared_space = ? AND user_id = ?",
            (group_shared_space, str(user_id)),
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
