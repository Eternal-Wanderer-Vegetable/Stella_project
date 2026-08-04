import re
import sqlite3
from nonebot import logger
from core.context import ChatContext
from config import (
    DB_PATH, RECENT_MESSAGE_LIMIT,
    PROACTIVE_LONG_TERM_LIMIT, REPLY_LONG_TERM_LIMIT,
    LONG_TERM_RELEVANCE_ENABLED, LONG_TERM_RELEVANCE_KEYWORDS,
)


async def record_message(ctx: ChatContext) -> ChatContext:
    if not DB_PATH.exists():
        return ctx
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
            ctx.context = "\n".join(parts) if parts else ""
            if ctx.context:
                logger.info(f"🧠 [Context] 使用短期记忆摘要")
                conn.close()
                return ctx

        if RECENT_MESSAGE_LIMIT > 0:
            cursor.execute(
                "SELECT user_id, content FROM group_messages WHERE group_id = ? ORDER BY id DESC LIMIT ?",
                (str(ctx.group_id), RECENT_MESSAGE_LIMIT),
            )
            rows = cursor.fetchall()
            if rows:
                rows.reverse()
                ctx.context = "\n".join(f"用户({uid}): {content}" for uid, content in rows)
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
            # 主动发言：取本群最近 N 条（按时间倒序，不限用户）
            cursor.execute(
                "SELECT summary FROM long_term_memories WHERE group_id = ? "
                "ORDER BY last_accessed_at DESC LIMIT ?",
                (str(ctx.group_id), PROACTIVE_LONG_TERM_LIMIT),
            )
            memories = cursor.fetchall()
            if memories:
                mem_texts = [m[0] for m in memories if m[0]]
                parts.append("最近的记忆: " + " | ".join(mem_texts))
        else:
            # @-回复：该用户近期记忆
            cursor.execute(
                "SELECT summary FROM long_term_memories WHERE user_id = ? AND group_id = ? "
                "ORDER BY last_accessed_at DESC LIMIT ?",
                (str(ctx.user_id), str(ctx.group_id), REPLY_LONG_TERM_LIMIT),
            )
            user_memories = [m[0] for m in cursor.fetchall() if m[0]]

            # @-回复：旧记忆话题匹配（跨用户，按关键词相关度）
            relevant_old: list[str] = []
            if LONG_TERM_RELEVANCE_ENABLED and LONG_TERM_RELEVANCE_KEYWORDS > 0:
                keywords = _extract_keywords(ctx.message, LONG_TERM_RELEVANCE_KEYWORDS)
                if keywords:
                    # 取该群所有非当前用户的记忆，在 Python 中做关键词匹配
                    cursor.execute(
                        "SELECT summary, user_id FROM long_term_memories "
                        "WHERE group_id = ? AND user_id != ? "
                        "ORDER BY last_accessed_at DESC",
                        (str(ctx.group_id), str(ctx.user_id)),
                    )
                    all_old = cursor.fetchall()
                    for summary, uid in all_old:
                        if not summary:
                            continue
                        hits = sum(1 for kw in keywords if kw in summary)
                        if hits > 0:
                            relevant_old.append((hits, uid, summary))
                    # 按命中数降序，最多取 3 条
                    relevant_old.sort(key=lambda x: x[0], reverse=True)
                    relevant_old = relevant_old[:3]

            if user_memories:
                parts.append(f"关于用户{ctx.user_id}的重要记忆: " + " | ".join(user_memories))
            if relevant_old:
                old_texts = [f"[用户{uid}] {s}" for _, uid, s in relevant_old]
                parts.append("其他相关记忆: " + " | ".join(old_texts))

        conn.close()

        if parts:
            user_context = "\n".join(parts)
            if ctx.context:
                ctx.context = ctx.context + "\n\n" + user_context
            else:
                ctx.context = user_context
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
