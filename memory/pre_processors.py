import sqlite3
from nonebot import logger
from core.context import ChatContext
from config import DB_PATH, RECENT_MESSAGE_LIMIT


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

        cursor.execute(
            "SELECT summary FROM long_term_memories WHERE user_id = ? AND group_id = ? ORDER BY importance DESC, last_accessed_at DESC LIMIT 3",
            (str(ctx.user_id), str(ctx.group_id)),
        )
        memories = cursor.fetchall()
        if memories:
            mem_texts = [m[0] for m in memories if m[0]]
            parts.append("关于此用户的重要记忆: " + " | ".join(mem_texts))

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
