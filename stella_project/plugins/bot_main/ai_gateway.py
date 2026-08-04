from __future__ import annotations

import asyncio
from collections import defaultdict
from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.exception import FinishedException
from nonebot.rule import Rule

from config import (
    ALLOWED_GROUPS, SEND_INTERVAL, SYSTEM_PROMPT_PATH,
    LM_STUDIO_BASE_URL, LM_STUDIO_MODEL, LLM_TIMEOUT,
    EXTENSIONS_DIR, FLEXIWEB_PROJECT_DIR, FLEXIWEB_BASE_URL, CONSOLIDATION_SITE,
    CONSOLIDATION_BATCH_SIZE, FLEXIWEB_HEADLESS,
    DB_CLEANUP_ON_START, DB_CLEANUP_CLEAR_MESSAGES,
    PROACTIVE_ENABLED, PROACTIVE_COOLDOWN, PROACTIVE_CHECK_INTERVAL,
    CONSOLIDATION_TRIGGER_NEW_MESSAGES,
    MESSAGE_CLEANUP_ENABLED, MESSAGE_CLEANUP_HOUR,
)
from core.context import ChatContext
from core.pipeline import Pipeline
from core.llm.lm_studio import LMStudioBackend
import core.llm.flexiweb as _flexiweb
from core.llm.flexiweb import FlexiWebManager
from extensions import load_extensions
from memory.pre_processors import build_context, build_user_context
from memory.post_processors import parse_output, bad_phrase_filter, split_lines, log_thought
from memory.consolidator import maybe_consolidate, get_consolidator
from memory.proactive import get_proactive

# ============================================================
# Pipeline 构建
# ============================================================
pipeline = Pipeline(timeout=LLM_TIMEOUT)

# ── 每群互斥锁：@-回复与主动发言不可并发，避免管道竞争 ──
_group_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

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

# ── 启动时数据库清理（测试期用，避免频繁重启注入脏记忆） ──
if DB_CLEANUP_ON_START:
    try:
        from memory.db_cleaner import clean_db, print_summary
        results = clean_db(
            clear_short_term=True,
            clear_long_term=True,
            reset_checkpoint=True,
            clear_messages=DB_CLEANUP_CLEAR_MESSAGES,
        )
        logger.info(f"🧹 启动清理完成（用户画像保留）: {results}")
    except Exception as e:
        logger.warning(f"⚠️ 数据库清理失败: {e}")

# ── FlexiWeb 自动启动（后台，不影响 QQ 聊天响应） ──────
if CONSOLIDATION_BATCH_SIZE > 0:
    _flexiweb.global_manager = FlexiWebManager(
        project_dir=FLEXIWEB_PROJECT_DIR,
        base_url=FLEXIWEB_BASE_URL,
        site=CONSOLIDATION_SITE,
        headless=FLEXIWEB_HEADLESS,
    )
    try:
        asyncio.get_running_loop().create_task(_flexiweb.global_manager.ensure_running())
    except RuntimeError as e:
        logger.warning(f"⚠️ FlexiWeb 启动异常（未在事件循环中）: {e}")

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
    # 不再每条消息都触发短期记忆总结（避免频繁空检查消耗服务器资源）；
    # 只记录时间戳用于频率估算，总结改由 @ 触发或主动发言前按需触发。
    get_proactive().record_message(ctx.group_id)


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
    lock = _group_locks[event.group_id]
    async with lock:
        ctx = ChatContext(
            user_id=event.user_id,
            group_id=event.group_id,
            msg_id=event.message_id,
            message=event.get_plaintext().strip(),
        )

        # @ 触发对话时：若距上次总结已累积足够新消息，后台触发一次短期记忆总结，
        # 避免每次群消息都做无用总结，同时保证对话用到的短期记忆是最新的。
        try:
            consolidator = get_consolidator()
            new_count = consolidator.has_new_messages_to_consolidate(
                event.group_id, threshold=CONSOLIDATION_TRIGGER_NEW_MESSAGES
            )
            if new_count > 0:
                logger.info(f"🧠 [Trigger] @对话触发短期记忆总结（新消息 {new_count} 条）")
                maybe_consolidate(event.group_id, force=True)
        except Exception as e:
            logger.warning(f"⚠️ @触发总结异常（跳过）: {e}")

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


# ============================================================
# 主动发言（基于群消息频率）
# ============================================================
try:
    from nonebot_plugin_apscheduler import scheduler
except Exception:
    scheduler = None


async def _proactive_speak_for_group(bot: Bot, group_id: int):
    """对单个群尝试主动发言：概率命中时生成一句自然的话并发送。"""
    proactive = get_proactive()
    if not proactive.should_speak(group_id):
        return

    lock = _group_locks[group_id]
    async with lock:
        # 主动发言前先确保短期记忆已更新（force 本地小批量，不打扰在线 LLM）
        try:
            consolidator = get_consolidator()
            new_count = consolidator.has_new_messages_to_consolidate(
                group_id, threshold=CONSOLIDATION_TRIGGER_NEW_MESSAGES
            )
            if new_count > 0:
                logger.info(f"🧠 [Proactive] 主动发言前触发短期记忆总结（新消息 {new_count} 条）")
                maybe_consolidate(group_id, force=True)
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.warning(f"⚠️ 主动发言前总结异常（跳过）: {e}")

        # 构造一次"主动插话"的对话上下文
        ctx = ChatContext(
            user_id=0,
            group_id=group_id,
            msg_id=0,
            message="（群聊里没有人在@你，但你想自然地插一句话，和大家随便聊聊。请说一句自然的话。）",
            trigger="proactive",
        )
        try:
            ctx = await pipeline.run(ctx)
        except Exception as e:
            logger.error(f"主动发言 Pipeline 异常: {e}")
            return
        if not ctx.lines:
            return

        proactive.mark_spoke(group_id)
        logger.success(f"✨ [主动发言] 群 {group_id}: {' | '.join(ctx.lines)}")
        try:
            for i, line in enumerate(ctx.lines):
                if i > 0:
                    await asyncio.sleep(SEND_INTERVAL)
                await bot.send_group_msg(group_id=group_id, message=line)
        except Exception as e:
            logger.error(f"主动发言发送失败: {e}")


if scheduler is not None and PROACTIVE_ENABLED:
    @scheduler.scheduled_job("interval", seconds=PROACTIVE_CHECK_INTERVAL, id="proactive_speak")
    async def proactive_speak_job():
        if not PROACTIVE_ENABLED:
            return
        try:
            from nonebot import get_bot
            bot = get_bot()
        except Exception as e:
            logger.debug(f"主动发言跳过：无可用 Bot（{e}）")
            return
        for group_id in ALLOWED_GROUPS:
            try:
                await _proactive_speak_for_group(bot, group_id)
            except Exception as e:
                logger.error(f"主动发言异常（群 {group_id}）: {e}")


# ============================================================
# 消息表定期清理（每天定时执行，防止数据库无限膨胀）
# ============================================================
if scheduler is not None and MESSAGE_CLEANUP_ENABLED:
    @scheduler.scheduled_job("cron", hour=MESSAGE_CLEANUP_HOUR, id="trim_group_messages")
    async def trim_messages_job():
        try:
            from memory.db_cleaner import trim_group_messages
            result = trim_group_messages()
            deleted = result["deleted"]
            groups = result["groups"]
            if deleted > 0:
                logger.info(f"🧹 [消息清理] 已清理 {deleted} 条旧消息（{groups} 个群）")
            else:
                logger.debug(f"🧹 [消息清理] 无需清理（{groups} 个群）")
        except Exception as e:
            logger.warning(f"⚠️ 消息清理异常: {e}")
