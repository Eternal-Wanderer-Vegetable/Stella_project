# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""AI 网关模块（bot_main.ai_gateway）：QQ 群消息与智能体 Pipeline 之间的桥梁。

本模块负责：
1. Pipeline 装配：注册 pre/post hooks（见下）、设置 LLM 后端（LM Studio）、加载扩展、加载系统提示词；
2. QQ 事件监听：
   - group_silent_listener（静默监听，priority 99）：只记录群消息到短期记忆，不触发总结；
   - chat_handler（@ 触发，priority 1）：当机器人被 @ 且发出非空消息时才会走完整推理；
   - 主动发言（基于群消息频率的定时任务）——见 _proactive_speak_for_group；
3. 定时任务（借 NoneBot APScheduler）：
   - 周度记忆压缩（run_weekly）、主动发言检查（proactive_speak_job）、每日消息清理（trim_messages_job）；
4. 并发控制：_group_locks 每群一把 asyncio.Lock，防止同一群内 @ 回复与主动发言同时跑 Pipeline。

依赖注入注意：模块级 pipeline / _group_locks 在 import 阶段创建，
NoneBot 单进程下天然复用；多 worker 场景需外部保证单实例。
"""

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
    CONSOLIDATION_LLM_PRIORITY,
    MESSAGE_CLEANUP_ENABLED, MESSAGE_CLEANUP_HOUR,
)
from core.context import ChatContext
from core.pipeline import Pipeline
from core.llm.lm_studio import LMStudioBackend
import core.llm.flexiweb as _flexiweb
from core.llm.flexiweb import FlexiWebManager
from extensions import load_extensions
from memory.pre_processors import record_message, build_context, build_user_context
from memory.compressor import get_compressor
from memory.post_processors import parse_output, bad_phrase_filter, split_lines, log_thought
from memory.consolidator import maybe_consolidate, get_consolidator
from memory.proactive import get_proactive

# ============================================================
# Pipeline 构建
# ============================================================
# 全局唯一的处理管线：前钩子做记忆召回/上下文组装，后钩子做输出解析与过滤
pipeline = Pipeline(timeout=LLM_TIMEOUT)

# ── 每群互斥锁：@-回复与主动发言不可并发，避免管道竞争 ──
# defaultdict 保证每个群首次访问时自动生成一把锁；锁内串行执行 Pipeline =
# 同一群人同一时刻只跑一次推理，防止并发写同一条上下文造成状态混乱
_group_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

# pre-hook 按 priority 升序执行（数值越小越先）：
# 50 -> build_context（构造群长期记忆上下文）
# 40 -> build_user_context（叠加用户短期记忆）—— priority 更小所以先于 build_context？
# 实际排序由 Pipeline 决定，这里只保证注册关系，具体先后以 implementation 为准
pipeline.register_pre_hook(build_context, priority=50)
pipeline.register_pre_hook(build_user_context, priority=40)

# post-hook 同样按 priority 升序执行：
# 100 -> parse_output（解析 LLM 输出为结构化结果）
# 80  -> bad_phrase_filter（过滤脏词 / 违禁语）
# 60  -> split_lines（把文本拆成可逐条发送的多行）
# 40  -> log_thought（记录思维链/日志）
pipeline.register_post_hook(parse_output, priority=100)
pipeline.register_post_hook(bad_phrase_filter, priority=80)
pipeline.register_post_hook(split_lines, priority=60)
pipeline.register_post_hook(log_thought, priority=40)

# 指定 LLM 后端（LM Studio 本地模型）
pipeline.set_llm_backend(LMStudioBackend(
    base_url=LM_STUDIO_BASE_URL,
    model=LM_STUDIO_MODEL,
))

# 读取系统提示词文件（若存在则注入，否则只警告不中断）
system_prompt_path = SYSTEM_PROMPT_PATH.resolve()
if system_prompt_path.exists():
    pipeline.system_prompt = system_prompt_path.read_text(encoding="utf-8")
    logger.success(f"✅ 加载系统提示词 ({len(pipeline.system_prompt)} 字符)")
else:
    logger.warning(f"⚠️ 系统提示词文件不存在: {system_prompt_path}")

# 加载插件目录下所有扩展（扩展可再向 pipeline 注册钩子/资源）
load_extensions(pipeline, EXTENSIONS_DIR)

# 启动时注册周度记忆压缩任务（每 7 天执行一次，由 APScheduler 调度）
try:
    if scheduler is not None:
        @scheduler.scheduled_job('interval', days=7, id='memory_compress_weekly')
        async def weekly_compress():
            # 调用 MemoryCompressor 做全量压缩；异常只记录不阻断其他定时任务
            try:
                get_compressor().run_weekly()
            except Exception as e:
                logger.warning(f"🧹 [Startup] 周度记忆压缩失败: {e}")
except Exception as e:
    logger.debug(f"注册周度压缩任务失败: {e}")

# ── 启动时数据库清理（测试期用，避免频繁重启注入脏记忆） ──
# 打开开关后，在插件装载阶段立即清空短期 / 长期记忆、重置检查点
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

# ── 启动时检查消息清理（补执行因离线而错过的每日清理） ──
# 若距上次清理已超 24h（如机器人昨晚关机漏跑），启动时补做一次，防止消息表无限膨胀
if MESSAGE_CLEANUP_ENABLED:
    try:
        from memory.db_cleaner import needs_cleanup, trim_group_messages
        if needs_cleanup():
            logger.info("🧹 [消息清理] 距上次清理超过 24h，启动时补执行")
            result = trim_group_messages()
            if result["deleted"] > 0:
                logger.info(f"🧹 [消息清理] 已清理 {result['deleted']} 条旧消息（{result['groups']} 个群）")
    except Exception as e:
        logger.warning(f"⚠️ 启动时消息清理异常: {e}")

# ── FlexiWeb 自动启动（仅在优先级链启用 flexiweb 时，后台拉起） ──────
# 只在 consolidation LLM 优先级链里含 flexiweb 且批次大小>0 时，才启动无头浏览器服务
if "flexiweb" in CONSOLIDATION_LLM_PRIORITY and CONSOLIDATION_BATCH_SIZE > 0:
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
# 静默监听：优先级最低(99)、不阻断其他处理器，负责把每条群聊写进短期记忆
group_silent_listener = on_message(priority=99, block=False)


@group_silent_listener.handle()
async def record_group_chat(event: GroupMessageEvent):
    """记录群聊消息到短期记忆（静默侧，不触发总结/推理）。"""
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
    """触发规则：(1) 属于已启用群 (2) 有人 @ 机器人 (3) 附带非空文本。"""
    if event.group_id not in ALLOWED_GROUPS:
        return False
    if not event.is_tome():
        return False
    return len(event.get_plaintext().strip()) > 0


# 对话入口：只有命中以上规则才会进入（priority=1 最高优先级、命中即 block）
chat_handler = on_message(rule=Rule(is_chat_trigger), priority=1, block=True)


@chat_handler.handle()
async def handle_chat(bot: Bot, event: GroupMessageEvent):
    """@ 触发主流程：加群锁 → 按需总结 → 跑 Pipeline → 逐条发送回复。"""
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
        # 这里用 force=True 强制总结（离线合并新消息到短期记忆），但因为是本地小批量，
        # 并不强制调用在线 LLM，避免影响响应速度。
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

        # 跑完整 Pipeline（前钩子组装上下文 → LLM 生成 → 后钩子解析/过滤/分段/日志）
        try:
            ctx = await pipeline.run(ctx)
        # FinishedException 应该被原样向上抛，避免把“已结束”当作异常处理
        except FinishedException:
            raise
        except Exception as e:
            logger.error(f"Pipeline 异常: {e}")
            # 兜底：异常时给用户一句温和的占位回复，避免冷场
            ctx.reply = "......？"
            ctx.lines = ["......？"]

        # 防御：就算后钩子没产出任何行，也一定给一句兜底
        if not ctx.lines:
            ctx.lines = ["......？"]

        logger.success(f"✨ [即将发送给 QQ 的台词]: {' | '.join(ctx.lines)}")

        # 第一条回复带引用原消息；多行之间间隔 SEND_INTERVAL 秒发送
        reply_segment = MessageSegment.reply(event.message_id)

        for i, line in enumerate(ctx.lines):
            if i > 0:
                await asyncio.sleep(SEND_INTERVAL)
            if i == 0:
                msg = Message([reply_segment, MessageSegment.text(line)])
            else:
                msg = Message(line)
            if i == len(ctx.lines) - 1:
                # 最后一行用 finish（结束本次处理），前面几行用 send
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
    """对单个群尝试主动发言：概率命中时生成一句自然的话并发送。

    :param bot: OneBot Bot 实例（用于组群发消息）
    :param group_id: 目标群号
    :return: None；命中时发送若干条群消息并记录“已发言”
    """
    # 先判断该群是否到了“可以主动发言”的时机（消息频率 / 冷却判定）
    proactive = get_proactive()
    if not proactive.should_speak(group_id):
        return

    # 同样要抢占本群的互斥锁：主动发言不能和 @ 回复并发，避免上下文被互相污染
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
        # 注意 user_id=0、trigger='proactive'：让 Pipeline 认为自己是被邀请插话，而不是 @ 回复
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

        # 通知频率跟踪“本群已发言”，避免连续多次主动插话打扰
        proactive.mark_spoke(group_id)
        logger.success(f"✨ [主动发言] 群 {group_id}: {' | '.join(ctx.lines)}")
        try:
            for i, line in enumerate(ctx.lines):
                if i > 0:
                    await asyncio.sleep(SEND_INTERVAL)
                await bot.send_group_msg(group_id=group_id, message=line)
        except Exception as e:
            logger.error(f"主动发言发送失败: {e}")


# 定时主动发言：每 PROACTIVE_CHECK_INTERVAL 秒检查一次所有启用群
if scheduler is not None and PROACTIVE_ENABLED:
    @scheduler.scheduled_job("interval", seconds=PROACTIVE_CHECK_INTERVAL, id="proactive_speak")
    async def proactive_speak_job():
        if not PROACTIVE_ENABLED:
            return
        # 每个循环重新取 bot，避免 Bot 对象失效
        try:
            from nonebot import get_bot
            bot = get_bot()
        except Exception as e:
            logger.debug(f"主动发言跳过：无可用 Bot（{e}）")
            return
        # 逐个群尝试主动发言；单个群失败不拖垮其他群
        for group_id in ALLOWED_GROUPS:
            try:
                await _proactive_speak_for_group(bot, group_id)
            except Exception as e:
                logger.error(f"主动发言异常（群 {group_id}）: {e}")


# ============================================================
# 消息表定期清理（每天定时执行，防止数据库无限膨胀）
# ============================================================
# 每日在 MESSAGE_CLEANUP_HOUR 点整点触发一次消息表裁剪
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
