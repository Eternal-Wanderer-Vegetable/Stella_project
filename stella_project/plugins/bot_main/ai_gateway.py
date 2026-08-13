# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""AI 网关模块（bot_main.ai_gateway）：QQ 群消息与智能体 Pipeline 之间的桥梁。

本模块负责：
1. Pipeline 装配：注册 pre/post hooks（见下）、设置 LLM 后端（LM Studio）、加载扩展、加载系统提示词；
2. QQ 事件监听：
   - group_silent_listener（静默监听，priority 99）：只记录群消息到短期记忆，不触发总结；
   - chat_handler（@ 触发，priority 1）：当机器人被 @ 且发出非空消息时才会走完整推理；
   - 主动 @ 用户（获取/验证记忆，受每用户日配额与冷却约束）——见 _proactive_at_user；
   - 主动发言（基于群消息频率的定时任务）——见 _proactive_speak_for_group；
3. 定时任务（借 NoneBot APScheduler）：
   - 周度记忆压缩（run_weekly）、主动发言检查（proactive_speak_job）、每日消息清理（trim_messages_job）；
4. 并发控制：_group_locks 每群一把 asyncio.Lock，防止同一群内 @ 回复与主动发言同时跑 Pipeline。

依赖注入注意：模块级 pipeline / _group_locks 在 import 阶段创建，
NoneBot 单进程下天然复用；多 worker 场景需外部保证单实例。
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections import defaultdict

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.exception import FinishedException
from nonebot.rule import Rule

from config import (
    ALLOWED_GROUPS,
    CONSOLIDATION_TRIGGER_NEW_MESSAGES,
    DB_CLEANUP_CLEAR_MESSAGES,
    DB_CLEANUP_ON_START,
    EXTENSIONS_DIR,
    LLM_TIMEOUT,
    LM_STUDIO_BASE_URL,
    LM_STUDIO_MODEL,
    MESSAGE_CLEANUP_ENABLED,
    MESSAGE_CLEANUP_HOUR,
    PROACTIVE_AT_ENABLED,
    PROACTIVE_CHECK_INTERVAL,
    PROACTIVE_ENABLED,
    PROACTIVE_MAX_LINES,
    PROACTIVE_REPLY_WINDOW_SECONDS,
    SEND_INTERVAL,
    SYSTEM_PROMPT_PATH,
)
from core.context import ChatContext
from core.llm.lm_studio import LMStudioBackend
from core.pipeline import Pipeline
from extensions import load_extensions
from memory.compressor import get_compressor
from memory.consolidator import get_consolidator, maybe_consolidate
from memory.post_processors import (
    bad_phrase_filter,
    log_thought,
    parse_output,
    split_lines,
)
from memory.pre_processors import build_context, build_user_context, record_message
from memory.proactive import get_proactive
from memory.proactive_prompt import build_instruction
from memory.proactive_state import record_at, record_reply_result
from memory.proactive_target import pick_target

# ============================================================
# Pipeline 构建
# ============================================================
# 全局唯一的处理管线：前钩子做记忆召回/上下文组装，后钩子做输出解析与过滤
pipeline = Pipeline(timeout=LLM_TIMEOUT)

# ── 每群互斥锁：@-回复与主动发言不可并发，避免管道竞争 ──
# defaultdict 保证每个群首次访问时自动生成一把锁；锁内串行执行 Pipeline =
# 同一群人同一时刻只跑一次推理，防止并发写同一条上下文造成状态混乱
_group_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

# 回应检测的后台任务集合：asyncio.create_task 的返回值必须持有引用，
# 否则任务可能在完成前被 GC 回收
_reply_check_tasks: set[asyncio.Task] = set()

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
# APScheduler 全局调度器由 nonebot_plugin_apscheduler 插件提供；未安装时为 None。
try:
    from nonebot_plugin_apscheduler import scheduler
except Exception:
    scheduler = None

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

# ── 启动时记忆系统 Schema 迁移（Additive Migration） ──
# 只加字段/索引、绝不删数据；旧库升级到 v3（source_kind 等），
# 首次迁移前自动备份为 stella_memory_backup.db
try:
    from memory.schema import ensure_v2_schema

    if ensure_v2_schema():
        logger.info("🔧 [Startup] 记忆系统 Schema 已升级到 v3")
except Exception as e:
    logger.warning(f"⚠️ 记忆系统 Schema 迁移失败: {e}")

# ── 启动时数据库清理（测试期用，避免频繁重启注入脏记忆） ──
# 打开开关后，在插件装载阶段立即清空短期 / 长期记忆、重置检查点
if DB_CLEANUP_ON_START:
    try:
        from memory.db_cleaner import clean_db
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
    # 防止 OneBot 回显自身消息造成重复入库（自身发言会经 _record_bot_lines 单独落库）
    if event.user_id == event.self_id:
        return
    text = event.get_plaintext().strip()
    if not text or text.startswith("/"):
        return
    ctx = ChatContext(
        user_id=event.user_id,
        group_id=event.group_id,
        msg_id=event.message_id,
        message=text,
        # @ 到 Bot 的消息是最可靠的用户信息源，落库时标记来源以供整合/审计
        source_kind="AT_MENTION" if event.is_tome() else "PASSIVE",
    )
    await record_message(ctx)
    # 不再每条消息都触发短期记忆总结（避免频繁空检查消耗服务器资源）；
    # 只记录时间戳用于频率估算，总结改由 @ 触发或主动发言前按需触发。
    get_proactive().record_message(ctx.group_id, ctx.user_id)


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

        # 把本次回复记入“已说过的话”，防止随后主动发言再重复刷屏
        with contextlib.suppress(Exception):
            get_proactive().record_spoken(event.group_id, ctx.lines)

        logger.success(f"✨ [即将发送给 QQ 的台词]: {' | '.join(ctx.lines)}")

        # 发送前先把 Bot 自己的台词落库（source_kind=BOT_SELF），给下一轮整合提供语境。
        # 必须放在发送前：最后一行走 chat_handler.finish() 会抛 FinishedException，后续代码不执行。
        await _record_bot_lines(event.self_id, event.group_id, ctx.lines)

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
_SENTENCE_ENDERS = "，。！？、；：;:?!.…\"\"''"


def _join_lines_naturally(lines: list[str]) -> str:
    """把多行台词自然地合并为一句/段，去掉硬换行并补齐标点。

    行间用“，”自然衔接：若上一行已经以标点结尾则直接相连，
    否则补一个逗号，避免出现“救命\n感觉好无聊啊”这类生硬断句。
    """
    text = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if text and text[-1] not in _SENTENCE_ENDERS:
            text += "，"
        text += line
    return text


async def _record_bot_lines(self_id: int, group_id: int, lines: list[str]) -> None:
    """把 Bot 自己发出的台词写入 group_messages（source_kind=BOT_SELF）。

    目的：让下一轮整合能看到「我问了什么」，否则用户回答「对」「是的」时
    整合模型缺少语境，只能放弃或自行编造。BOT_SELF 只作上下文，
    consolidator 已保证它不进候选发送者白名单。
    """
    for line in lines:
        text = (line or "").strip()
        if not text:
            continue
        try:
            await record_message(
                ChatContext(
                    user_id=self_id,
                    group_id=group_id,
                    msg_id=0,
                    message=text,
                    source_kind="BOT_SELF",
                )
            )
        except Exception as e:
            logger.warning(f"⚠️ 记录 Bot 自身发言失败（跳过）: {e}")


async def _resolve_nickname(bot: Bot, group_id: int, user_id: int) -> str:
    """取群名片/昵称用于自然称呼；失败时回退「对方」。

    只用于生成台词的措辞，取不到不影响功能，因此所有异常都吞掉。
    """
    try:
        info = await bot.get_group_member_info(
            group_id=group_id, user_id=user_id, no_cache=False
        )
        return (info.get("card") or info.get("nickname") or "").strip() or "对方"
    except Exception:
        return "对方"


async def _check_reply_later(group_id: int, user_id: int, asked_at: float) -> None:
    """延迟检查主动 @ 是否获得回应，据此更新退避计数。

    判定标准：在 PROACTIVE_REPLY_WINDOW_SECONDS 内该用户是否有过任何发言
    （用内存中的活跃度时间戳，不查库——只需要知道「有没有说话」）。

    无回应即累计 consecutive_no_reply，达到 PROACTIVE_MAX_NO_REPLY 后
    can_at_user 会拒绝继续追问该用户，这是对「不想聊的人」的自动退避。
    """
    try:
        await asyncio.sleep(PROACTIVE_REPLY_WINDOW_SECONDS)
        last = get_proactive().last_spoke_ts(group_id, user_id)
        replied = last is not None and last > asked_at
        record_reply_result(group_id, user_id, replied)
        logger.info(
            f"{'✅' if replied else '🔇'} [主动@] 群 {group_id} 用户 {user_id} "
            f"{'已回应' if replied else '未回应'}（窗口 {PROACTIVE_REPLY_WINDOW_SECONDS:.0f}s）"
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"⚠️ [主动@] 回应检测异常（跳过）: {e}")


async def _proactive_at_user(bot: Bot, group_id: int) -> bool:
    """尝试主动 @ 一位活跃用户以获取/验证记忆；返回是否已发言。

    与话题插话互斥：本函数返回 True 时调用方不再尝试话题插话，
    同一轮只做一件事，避免连续两次发言。

    流程：选目标（配额/冷却/退避过滤）→ 生成指令 → 跑 Pipeline →
    发送（带 @ 段）→ 记账（发出即计数）→ 起延迟任务检测回应。
    """
    if not PROACTIVE_AT_ENABLED:
        return False

    proactive = get_proactive()
    if proactive.in_cooldown(group_id):
        return False

    # 排除 Bot 自身，避免自问自答
    try:
        self_id = int(bot.self_id)
    except (TypeError, ValueError):
        self_id = 0
    target = pick_target(group_id, exclude_user_ids={self_id, 0})
    if target is None:
        return False

    target.nickname = await _resolve_nickname(bot, group_id, target.user_id)
    logger.info(
        f"🎯 [主动@] 群 {group_id} 选定用户 {target.user_id}"
        f"（{target.nickname}，mode={target.mode}）：{target.reason}"
    )

    lock = _group_locks[group_id]
    async with lock:
        ctx = ChatContext(
            user_id=target.user_id,
            group_id=group_id,
            msg_id=0,
            message=build_instruction(target),
            # trigger 用 reply：主动 @ 是「对着某个具体人说话」，
            # 需要该用户的画像与记忆参与上下文构建（proactive 走的是群级检索）
            trigger="reply",
            # 纯诊断字段：日志据此区分「用户 @ 我」与「我主动 @ 人」
            intent="proactive_at",
        )
        try:
            ctx = await pipeline.run(ctx)
        except Exception as e:
            logger.error(f"主动 @ Pipeline 异常: {e}")
            return False

        if not ctx.lines:
            return False

        # 主动 @ 只发一句：追问必须简短，多行会像连续质询
        line = _join_lines_naturally(ctx.lines) if len(ctx.lines) > 1 else ctx.lines[0].strip()
        if not line:
            return False

        if proactive.recently_spoken(group_id, [line]):
            logger.info(f"🛑 [主动@] 群 {group_id} 与已发言内容重复，跳过")
            return False

        proactive.mark_spoke(group_id)
        proactive.record_spoken(group_id, [line])
        logger.success(f"✨ [主动@] 群 {group_id} → {target.user_id}: {line}")

        await _record_bot_lines(self_id, group_id, [line])

        try:
            await bot.send_group_msg(
                group_id=group_id,
                message=Message([MessageSegment.at(target.user_id), MessageSegment.text(" " + line)]),
            )
        except Exception as e:
            logger.error(f"主动 @ 发送失败: {e}")
            return False

    # 发出即计数（不论是否获得回应），否则无回应的追问不占配额，
    # 会导致对同一个人连续搭话
    record_at(
        group_id,
        target.user_id,
        topic=target.topic,
        candidate_id=target.candidate_id,
    )

    # 起后台任务检测回应；登记到集合防止被 GC 回收
    task = asyncio.create_task(
        _check_reply_later(group_id, target.user_id, time.monotonic())
    )
    _reply_check_tasks.add(task)
    task.add_done_callback(_reply_check_tasks.discard)
    return True


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

        # 主动插话只保留 PROACTIVE_MAX_LINES 条以内的消息（避免刷屏），
        # 超出的行按自然句读合并进前几行，而不是直接丢弃后半段（避免出现只发“救命”这类断句）
        if PROACTIVE_MAX_LINES > 0 and len(ctx.lines) > PROACTIVE_MAX_LINES:
            per_chunk = math.ceil(len(ctx.lines) / PROACTIVE_MAX_LINES)
            ctx.lines = [
                _join_lines_naturally(ctx.lines[i : i + per_chunk])
                for i in range(0, len(ctx.lines), per_chunk)
            ]
        if not ctx.lines:
            return

        # 防刷屏：与最近一次主动/回复高度相似时，本次主动发言直接放弃
        if get_proactive().recently_spoken(group_id, ctx.lines):
            logger.info(f"🛑 [主动发言] 群 {group_id} 与已发言内容重复，跳过")
            return

        # 通知频率跟踪“本群已发言”，避免连续多次主动插话打扰
        proactive.mark_spoke(group_id)
        get_proactive().record_spoken(group_id, ctx.lines)
        logger.success(f"✨ [主动发言] 群 {group_id}: {' | '.join(ctx.lines)}")
        await _record_bot_lines(int(bot.self_id), group_id, ctx.lines)
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
                # 主动 @ 优先：它有明确目的（获取/验证记忆），
                # 且已受每用户配额与冷却约束。命中即跳过本轮话题插话，
                # 同一轮只发一次言。
                if await _proactive_at_user(bot, group_id):
                    continue
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
        # 同步清理过期的记忆决策追踪，防止 memory_traces 无限膨胀
        try:
            from memory.trace import prune_traces
            pruned = prune_traces(keep_days=30.0)
            if pruned > 0:
                logger.info(f"📊 [Trace] 已清理 {pruned} 条过期决策追踪")
        except Exception as e:
            logger.debug(f"📊 [Trace] 决策追踪清理异常: {e}")
