from __future__ import annotations

import re
from datetime import datetime
from nonebot import logger
from core.context import ChatContext
from config import (
    THOUGHT_LOG_PATH, MAX_REPLY_LINES, BAD_PHRASES,
    FALLBACK_REPLY,
)


def parse_raw_output(raw: str) -> tuple[str, str, str]:
    thought = "（无思考过程）"
    action = "NONE"
    reply = ""

    thought_match = re.search(r"<thought>(.*?)(?:</thought>|<action>|<reply>|$)", raw, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    action_match = re.search(r"<action>(.*?)(?:</action>|<reply>|$)", raw, re.DOTALL)
    if action_match:
        action = action_match.group(1).strip()

    reply_match = re.search(r"<reply>(.*?)(?:</reply>|$)", raw, re.DOTALL)
    if reply_match:
        reply = reply_match.group(1).strip()

    if not reply:
        clean = re.sub(r"<[^>]+>.*?(?:</[^>]+>|$)", "", raw, flags=re.DOTALL).strip()
        if clean:
            reply = clean

    return thought, action, reply


async def parse_output(ctx: ChatContext) -> ChatContext:
    raw = ctx.raw_output
    if not raw:
        return ctx
    ctx.thought, ctx.action, ctx.reply = parse_raw_output(raw)
    return ctx


async def bad_phrase_filter(ctx: ChatContext) -> ChatContext:
    if any(p in ctx.reply for p in BAD_PHRASES):
        ctx.reply = FALLBACK_REPLY
        ctx.thought = "破防兜底"
    return ctx


async def split_lines(ctx: ChatContext) -> ChatContext:
    if not ctx.reply:
        ctx.reply = "......？"
    ctx.reply = ctx.reply.replace("\\n", "\n")
    ctx.reply = re.sub(r"[\（\(][^\）\)]*[\）\)]", "", ctx.reply).strip()
    lines = [line.strip() for line in ctx.reply.split("\n") if line.strip()][:MAX_REPLY_LINES]
    ctx.lines = lines or ["......？"]
    return ctx


async def log_thought(ctx: ChatContext) -> ChatContext:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reply_str = " <br> ".join(ctx.lines)
    thought_formatted = ctx.thought.replace("\n", "\n  > ")
    log_entry = f"""### 🕒 [{now_str}] 用户: `{ctx.user_id}`
- **📥 用户输入**: {ctx.message}
- **🧠 内部思考**:
  > {thought_formatted}
- **⚙️ 判定动作**: `{ctx.action}`
- **💬 最终台词**: {reply_str}

---
"""
    try:
        if not THOUGHT_LOG_PATH.exists():
            THOUGHT_LOG_PATH.write_text("# 🤖 思考过程与决策日志\n\n", encoding="utf-8")
        with open(THOUGHT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        logger.error(f"日志写入失败: {e}")
    return ctx



