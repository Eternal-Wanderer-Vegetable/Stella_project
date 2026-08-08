# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""LLM 原始输出的后处理工具。

解析模型返回的 ``<thought>``/``<action>``/``<reply>`` 三段标记文本，
做行数收敛、坏语料过滤；当模型没给出可用回复时，兜底到底层
FALLBACK_REPLY，并把每次思考过程写入 thought 日志供调试。
"""

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
    # 只删除半角括号 ()，保留中文括号（）和其他全角括号
    ctx.reply = re.sub(r"\([^）\n]*\)", "", ctx.reply).strip()
    lines = [line.strip() for line in ctx.reply.split("\n") if line.strip()][:MAX_REPLY_LINES]
    ctx.lines = lines or ["......？"]
    return ctx


async def log_thought(ctx: ChatContext) -> ChatContext:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reply_str = " <br> ".join(ctx.lines)
    thought_formatted = ctx.thought.replace("\n", "\n  > ")
    raw_output_formatted = ctx.raw_output.replace("\n", "\n  > ") if ctx.raw_output else ""
    trigger_str = {
        "reply": "@回复触发",
        "proactive": "主动发言",
    }.get(ctx.trigger, ctx.trigger)
    llm_info = f"{ctx.llm_backend or '未知'} / {ctx.llm_model or '未指定'}"
    log_entry = f"""### 🕒 [{now_str}] {trigger_str} | 群: `{ctx.group_id}` | 用户: `{ctx.user_id}`
- **🖥 模型**: `{llm_info}`（耗时 {ctx.llm_elapsed:.2f}s，系统提示词 {ctx.system_prompt_len} 字符）
- **📥 用户输入**: {ctx.message}
- **📤 完整 Prompt（发给 LLM）**:
  > {ctx.prompt_log.replace(chr(10), chr(10) + "  > ") if ctx.prompt_log else "(空)"}
- **📥 原始 LLM 输出（完整）**:
  > {raw_output_formatted if raw_output_formatted else "(空)"}
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



