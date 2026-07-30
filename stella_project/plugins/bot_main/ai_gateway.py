from __future__ import annotations

import asyncio
from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.exception import FinishedException
from nonebot.rule import Rule

from config import (
    ALLOWED_GROUPS, SEND_INTERVAL, SYSTEM_PROMPT_PATH,
    LM_STUDIO_BASE_URL, LM_STUDIO_MODEL, LLM_TIMEOUT,
    EXTENSIONS_DIR,
)
from core.context import ChatContext
from core.pipeline import Pipeline
from core.llm.lm_studio import LMStudioBackend
from extensions import load_extensions
from memory.pre_processors import record_message, build_context, build_user_context
from memory.post_processors import parse_output, bad_phrase_filter, split_lines, log_thought
from memory.consolidator import maybe_consolidate

# ============================================================
# Pipeline 构建
# ============================================================
pipeline = Pipeline(timeout=LLM_TIMEOUT)

pipeline.register_pre_hook(record_message, priority=100)
pipeline.register_pre_hook(build_context, priority=50)
pipeline.register_pre_hook(build_user_context, priority=40)

pipeline.register_post_hook(parse_output, priority=100)
pipeline.register_post_hook(bad_phrase_filter, priority=80)
pipeline.register_post_hook(split_lines, priority=60)
pipeline.register_post_hook(log_thought, priority=40)

pipeline.set_llm_backend(LMStudioBackend(
    base_url=LM_STUDIO_BASE_URL,
    model=LM_STUDIO_MODEL,
))

system_prompt_path = SYSTEM_PROMPT_PATH.resolve()
if system_prompt_path.exists():
    pipeline.system_prompt = system_prompt_path.read_text(encoding="utf-8")
    logger.success(f"✅ 加载系统提示词 ({len(pipeline.system_prompt)} 字符)")
else:
    logger.warning(f"⚠️ 系统提示词文件不存在: {system_prompt_path}")

load_extensions(pipeline, EXTENSIONS_DIR)

# ============================================================
# QQ 事件监听
# ============================================================
group_silent_listener = on_message(priority=99, block=False)


@group_silent_listener.handle()
async def record_group_chat(event: GroupMessageEvent):
    if event.group_id not in ALLOWED_GROUPS:
        return
    text = event.get_plaintext().strip()
    if not text or text.startswith("/"):
        return
    ctx = ChatContext(
        user_id=event.user_id,
        group_id=event.group_id,
        msg_id=event.message_id,
        message=text,
    )
    await record_message(ctx)
    maybe_consolidate(ctx.group_id)


async def is_chat_trigger(event: GroupMessageEvent) -> bool:
    if event.group_id not in ALLOWED_GROUPS:
        return False
    if not event.is_tome():
        return False
    return len(event.get_plaintext().strip()) > 0


chat_handler = on_message(rule=Rule(is_chat_trigger), priority=1, block=True)


@chat_handler.handle()
async def handle_chat(bot: Bot, event: GroupMessageEvent):
    _ = bot
    ctx = ChatContext(
        user_id=event.user_id,
        group_id=event.group_id,
        msg_id=event.message_id,
        message=event.get_plaintext().strip(),
    )

    try:
        ctx = await pipeline.run(ctx)
    except FinishedException:
        raise
    except Exception as e:
        logger.error(f"Pipeline 异常: {e}")
        ctx.reply = "......？"
        ctx.lines = ["......？"]

    if not ctx.lines:
        ctx.lines = ["......？"]

    logger.success(f"✨ [即将发送给 QQ 的台词]: {' | '.join(ctx.lines)}")

    reply_segment = MessageSegment.reply(event.message_id)

    for i, line in enumerate(ctx.lines):
        if i > 0:
            await asyncio.sleep(SEND_INTERVAL)
        if i == 0:
            msg = Message([reply_segment, MessageSegment.text(line)])
        else:
            msg = Message(line)
        if i == len(ctx.lines) - 1:
            await chat_handler.finish(msg)
        else:
            await chat_handler.send(msg)
