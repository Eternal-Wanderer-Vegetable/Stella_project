import re
import sqlite3
from nonebot import logger
from core.context import ChatContext
from config import (
    DB_PATH, RECENT_MESSAGE_LIMIT,
    PROACTIVE_LONG_TERM_LIMIT, REPLY_LONG_TERM_LIMIT,
    LONG_TERM_RELEVANCE_ENABLED,
)
from memory.retriever import get_group_memories, get_user_memories, get_related_memories
from memory.prompt_builder import build_memory_context


async def record_message(ctx: ChatContext) -> ChatContext:
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT,
                user_id TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
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
            INSERT INTO group_messages (group_id, user_id, content)
            VALUES (?, ?, ?)
        """, (str(ctx.group_id), str(ctx.user_id), ctx.message))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"记录消息失败: {e}")
    return ctx


async def build_context(ctx: ChatContext) -> ChatContext:
    if not DB_PATH.exists():
        return ctx
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT active_summary, pending_topic FROM short_term_context WHERE group_id = ?",
            (str(ctx.group_id),),
        )
        row = cursor.fetchone()
        if row and (row[0] or row[1]):
            parts = []
            if row[0]:
                parts.append(f"对话摘要: {row[0]}")
            if row[1] and row[1] != "无":
                parts.append(f"进行中的话题: {row[1]}")
            summary_text = "\n".join(parts) if parts else ""
            if summary_text:
                ctx.short_term = summary_text
                logger.info(f"🧠 [Context] 使用短期记忆摘要")
                conn.close()
                return ctx

        if RECENT_MESSAGE_LIMIT > 0:
            try:
                cursor.execute(
                    "SELECT user_id, content FROM group_messages WHERE group_id = ? ORDER BY id DESC LIMIT ?",
                    (str(ctx.group_id), RECENT_MESSAGE_LIMIT),
                )
            except sqlite3.OperationalError:
                cursor.execute(
                    "SELECT user_id, content FROM messages WHERE group_id = ? ORDER BY id DESC LIMIT ?",
                    (str(ctx.group_id), RECENT_MESSAGE_LIMIT),
                )
            rows = cursor.fetchall()
            if rows:
                rows.reverse()
                text = "\n".join(f"用户({uid}): {content}" for uid, content in rows)
                ctx.short_term = text
                logger.info(f"📝 [Context] 短期记忆为空，回退到最近{RECENT_MESSAGE_LIMIT}条原始消息")

        conn.close()
    except Exception as e:
        logger.warning(f"读取上下文异常（跳过）: {e}")
    return ctx


async def build_user_context(ctx: ChatContext) -> ChatContext:
    if not DB_PATH.exists():
        return ctx
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        parts = []

        is_proactive = ctx.trigger == "proactive"

        if not is_proactive:
            # ── @-回复：读取用户画像 ──
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
        if is_proactive:
            memories = get_group_memories(ctx.group_id, limit=PROACTIVE_LONG_TERM_LIMIT)
            if memories:
                parts.append("最近的记忆回顾：\n" + build_memory_context(memories))
        else:
            user_memories = get_user_memories(ctx.group_id, ctx.user_id, limit=REPLY_LONG_TERM_LIMIT)
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
                if p.startswith(f"关于用户{ctx.user_id}") or p.startswith("关于用户") or p.startswith("关于当前用户"):
                    up = p
                    break
            ctx.user_profile = up
            # 构造用于 prompt 的 memories 列表（从之前检索得到的记忆片段）
            memories: list[dict] = []
            # 主动发言时 parts 中第一项为群记忆回顾（build_context 已把短期赋给 short_term）
            if ctx.trigger == "proactive":
                try:
                    memories = get_group_memories(ctx.group_id, limit=PROACTIVE_LONG_TERM_LIMIT)
                except Exception:
                    memories = []
            else:
                try:
                    user_memories = get_user_memories(ctx.group_id, ctx.user_id, limit=REPLY_LONG_TERM_LIMIT)
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


# 中文停用词（高频无意义词，匹配时排除）
_STOP_WORDS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 "
    "他 她 它 们 那 些 什么 怎么 如何 可以 可能 已经 还 但 而 且 或 虽然 因为 所以 如果 被 把 让 "
    "从 对 为 与 向 以 及 等 之 其 此 该 本 中 里 后 前 时 年 月 日 个 些 多 少 更 最 ".split()
)


def _extract_keywords(text: str, max_keywords: int) -> list[str]:
    """从中文文本中提取关键词（2-4 字词组），用于记忆话题匹配。"""
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
