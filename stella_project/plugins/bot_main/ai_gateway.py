# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""AI 网关模块（bot_main.ai_gateway）：QQ 群消息与智能体 Pipeline 之间的桥梁。

本模块负责：
1. Pipeline 装配：注册 pre/post hooks（见下）、设置 LLM 后端（LM Studio）、加载扩展、加载系统提示词；
2. QQ 事件监听：
   - group_silent_listener（静默监听，priority 0）：只记录群消息到短期记忆，不触发总结；
   - toggle_handler（运行时开关，priority 1）：管理员 @ 机器人说「安静」/「恢复」时
     临时关闭或恢复本群主动发言（必须早于 chat_handler，否则会被当成普通对话）；
   - plugin_handler（AstrBot 插件，priority 2）：对所有消息跑一遍插件过滤器，
     是否唤醒由过滤器自己决定（指令受 "/" 前缀与 @ 约束，正则/全量监听不受约束）；
   - chat_handler（@ 触发，priority 3）：当机器人被 @ 且发出非空消息时才会走完整推理；
   - 主动 @ 用户（获取/验证记忆，受每用户日配额与冷却约束）——见 _proactive_at_user；
   - 主动发言（基于群消息频率的定时任务）——见 _proactive_speak_for_group；
3. 定时任务（借 NoneBot APScheduler）：
   - 周度记忆压缩（run_weekly）、主动发言检查（proactive_speak_job，含睡眠/苏醒播报）、
     每日消息清理（trim_messages_job）、会话空闲检查（session_idle_check_job，结束会话并触发整合）、
     定时整合（consolidation_drain_job，排空各群的整合积压）；
4. 并发控制：_group_locks 每群一把 asyncio.Lock，防止同一群内 @ 回复与主动发言同时跑 Pipeline。

依赖注入注意：模块级 pipeline / _group_locks 在 import 阶段创建，
NoneBot 单进程下天然复用；多 worker 场景需外部保证单实例。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import math
import os
import random
import time
from collections import OrderedDict, defaultdict
from datetime import date

from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.exception import FinishedException
from nonebot.rule import Rule

from capability.hooks import register as register_capability_hook
from config import (
    ALLOWED_GROUPS,
    ASTRBOT_COMPAT_ALLOW_PRIVATE,
    CONSOLIDATION_LOCAL_BATCH_SIZE,
    CONSOLIDATION_MAX_ROUNDS_PER_RUN,
    CONSOLIDATION_SCHEDULE_INTERVAL,
    CONSOLIDATION_TRIGGER_NEW_MESSAGES,
    DB_CLEANUP_CLEAR_MESSAGES,
    DB_CLEANUP_ON_START,
    EXTENSIONS_DIR,
    LLM_TIMEOUT,
    LM_STUDIO_API_KEY,
    LM_STUDIO_BASE_URL,
    LM_STUDIO_MODEL,
    MESSAGE_CLEANUP_ENABLED,
    MESSAGE_CLEANUP_HOUR,
    PROACTIVE_CHECK_INTERVAL,
    PROACTIVE_ENABLED,
    PROACTIVE_MAX_LINES,
    PROACTIVE_REPLY_WINDOW_SECONDS,
    PROACTIVE_RUNTIME_TOGGLE_ENABLED,
    PROACTIVE_SLEEP_ANNOUNCE,
    PROACTIVE_SLEEP_MESSAGES,
    PROACTIVE_TOGGLE_ADMINS,
    PROACTIVE_WAKEUP_MESSAGES,
    SEND_INTERVAL,
    SESSION_CONTEXT_ENABLED,
    SESSION_IDLE_CHECK_INTERVAL,
    SHUTDOWN_GRACE_SECONDS,
    STOP_WATCH_INTERVAL_SECONDS,
    SYSTEM_PROMPT_PATH,
)
from config.spaces import prompt_text, resolve_space
from core.context import ChatContext
from core.llm.lm_studio import LMStudioBackend
from core.pipeline import Pipeline
from core.shutdown import wait_for_tasks
from core.stop_signal import clear_stop_request, is_stop_requested, read_stop_request
from extensions import load_extensions
from memory.compressor import get_compressor
from memory.consolidator import get_consolidator, maybe_consolidate
from memory.post_processors import (
    bad_phrase_filter,
    log_thought,
    parse_output,
    split_lines,
)
from memory.pre_processors import build_context, record_message
from memory.proactive import get_proactive
from memory.proactive_gate import can_speak, is_sleeping, note_sleep_transition
from memory.proactive_prompt import build_instruction
from memory.proactive_state import (
    get_runtime_state,
    mark_announced,
    record_at,
    record_reply_result,
    set_proactive_muted,
)
from memory.proactive_target import pick_target
from memory.session_compact import schedule_compact
from memory.session_context import end_session
from memory.session_context import idle_groups as idle_session_groups
from memory.session_context import touch as session_touch

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

# 插件已处理标记：message_id -> timestamp，限长 256，避免 pydantic 模型上 setattr 的兼容问题
_plugin_handled_msgs: OrderedDict[int, float] = OrderedDict()

# pre-hook 按 priority 降序执行（数值越大越先）：
# 50 -> build_context（组装短期上下文：话题摘要 + 原始尾巴 + 会话摘要）
# 45 -> activate_capabilities（Router 判定 → 并行跑 {长期记忆检索, Comes 工具执行}）
#
# build_user_context **不再单独注册**：它已被 activate_capabilities 接管。
# 方案第 17 节要求 Memory 与 Comes 并行，两个独立钩子只能串行，必须收进同一个
# gather。这里再注册一次会让记忆检索跑两遍（一次串行、一次在 gather 里）。
pipeline.register_pre_hook(build_context, priority=50)
register_capability_hook(pipeline)

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
    api_key=LM_STUDIO_API_KEY,
))

# 读取系统提示词文件（若存在则注入，否则只警告不中断）
system_prompt_path = SYSTEM_PROMPT_PATH.resolve()
if system_prompt_path.exists():
    pipeline.system_prompt = system_prompt_path.read_text(encoding="utf-8")
    logger.success(f"✅ 加载系统提示词 ({len(pipeline.system_prompt)} 字符)")
else:
    logger.warning(f"⚠️ 系统提示词文件不存在: {system_prompt_path}")


def _space_system_prompt(ctx: ChatContext) -> str:
    """按共享空间选择人格；空间 prompt 不可用时由 config.spaces 回退默认文件。"""
    try:
        return prompt_text(resolve_space(int(ctx.group_id))) or pipeline.system_prompt
    except Exception as e:
        logger.warning(f"⚠️ 读取空间人格失败，使用默认人格: {e}")
        return pipeline.system_prompt


pipeline.system_prompt_resolver = _space_system_prompt

# 加载插件目录下所有扩展（扩展可再向 pipeline 注册钩子/资源）
load_extensions(pipeline, EXTENSIONS_DIR)

# 本地状态接口：挂在 NoneBot 已有的 ASGI app 上（不新增端口）。
# 放在扩展加载之后：link_status 来自扩展（虽是延迟导入，顺序清晰些更好）。
# 注册失败只告警——状态接口是加分项，缺了只是 GUI 少一块信息，不该阻断启动。
try:
    from .status_api import setup_status_api

    setup_status_api()
except Exception as e:
    logger.warning(f"⚠️ 本地状态接口注册失败: {e}")

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

# ── 启动时对齐整合 checkpoint ──
# 消息清理会删除旧消息，但 checkpoint 不会随之调整，导致 `id > checkpoint`
# 命中全部剩余消息、把已整理过的内容重新整理一遍（2026-08-15 实测 1487 条）。
# 这里在任何整合触发之前修正历史遗留的错位。
try:
    from memory.db_cleaner import align_all_checkpoints

    adjusted = align_all_checkpoints()
    if adjusted:
        logger.info(f"🔧 [Startup] 已对齐 {adjusted} 个群的整合 checkpoint")
except Exception as e:
    logger.warning(f"⚠️ 启动时对齐 checkpoint 失败: {e}")

# ── 启动时统计各群 source_kind 分布 ──
# AT_MENTION 长期为 0 而 BOT_SELF>0 是 @ 消息未入库的退化信号（2026-08-17 缺陷）。
# 表缺失 / 查询失败时函数内部静默返回，不影响启动。
with contextlib.suppress(Exception):
    from memory.db_cleaner import log_source_kind_distribution

    log_source_kind_distribution()

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
# 静默监听：必须是最高优先级（priority=0、不阻断其他处理器）——它是唯一的落库入口，
# 若排在 block=True 的处理器之后，@ 消息会被拦截而永不入库
# （2026-08-17 实测：13 批整合、270 条消息，AT_MENTION 计数全为 0，@ 对话的内容从未
#   进入记忆系统）。职责顺序是「先落库，再决定要不要回复」。
# ── 监听器优先级不变量（启动期自检用常量，避免依赖 NoneBot Matcher 内部属性） ──
# 落库监听必须早于所有 block=True 的处理器，否则 @ 消息会被拦截而永不入库。
# 2026-08-17 实测：落库监听器为 priority 99 时，13 批整合共消费 270 条消息，
# AT_MENTION 计数全为 0 —— @ 对话（设计上唯一稳定的用户信息源）的内容从未进入
# 记忆系统，且连带 AT_MENTION 单次晋升、主动 @ 的候选验证模式全部空转。
# 这个错误不会抛异常、不会影响回复，只会让记忆系统静默地什么都学不到，
# 因此必须在启动时主动断言。
_PRIORITY_SILENT = 0
_PRIORITY_TOGGLE = 1
_PRIORITY_PLUGIN = 2
_PRIORITY_CHAT = 3

group_silent_listener = on_message(priority=_PRIORITY_SILENT, block=False)


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
    # 记录会话活动时间（用于空闲判定）。只更新时间戳，无 DB 访问。
    session_touch(ctx.group_id)


async def is_chat_trigger(event: GroupMessageEvent) -> bool:
    """触发规则：(1) 属于已启用群 (2) 有人 @ 机器人 (3) 附带非空文本。"""
    _tome = event.is_tome()
    _txt = event.get_plaintext().strip()
    _gid_ok = event.group_id in ALLOWED_GROUPS
    logger.info(f"[chat_debug] is_chat_trigger gid={event.group_id} gid_ok={_gid_ok} is_tome={_tome} text={_txt!r} self_id={event.self_id} raw={event.get_message()!r}")
    if event.group_id not in ALLOWED_GROUPS:
        return False
    if not event.is_tome():
        return False
    return len(event.get_plaintext().strip()) > 0


async def is_plugin_trigger(event: MessageEvent) -> bool:
    """AstrBot 插件的触发规则——刻意比 is_chat_trigger 宽。

    上游 AstrBot 对**每一条**消息都跑一遍插件 filter，是否唤醒由 filter 自己决定：
    @filter.command 受唤醒前缀（默认 "/"）与 @ 约束，而 @filter.regex /
    @filter.event_message_type 明确不受约束。若在这里就要求 is_tome()，
    正则监听、全量监听、以及群里直接打 "/xxx" 的标准用法会全部失效。
    实际的唤醒判定在 astrbot_compat.pipeline.collect_handlers 内完成。
    """
    if isinstance(event, GroupMessageEvent):
        if event.group_id not in ALLOWED_GROUPS:
            return False
    elif not ASTRBOT_COMPAT_ALLOW_PRIVATE:
        return False
    return len(event.get_plaintext().strip()) > 0


# AstrBot 插件入口（priority=2）：命中则不再走 Stella LLM（priority=3）。
# block=False 保证未命中时仍能落到 chat_handler；命中时通过 _plugin_handled_msgs 让 chat 跳过。
plugin_handler = on_message(rule=Rule(is_plugin_trigger), priority=_PRIORITY_PLUGIN, block=False)


@plugin_handler.handle()
async def handle_plugin(bot: Bot, event: MessageEvent):
    """AstrBot 插件分发。无插件安装时 dispatch 会立即返回，开销可忽略。"""
    try:
        from astrbot_compat.pipeline import dispatch

        logger.info(f"[plugin_debug] handle_plugin event={event.get_plaintext()!r} msg_id={event.message_id}")
        handled = await dispatch(event, bot)
        logger.info(f"[plugin_debug] dispatch handled={handled} msg_id={event.message_id}")
        if handled:
            _plugin_handled_msgs[event.message_id] = time.time()
            if len(_plugin_handled_msgs) > 256:
                _plugin_handled_msgs.popitem(last=False)
    except Exception as e:
        logger.warning(f"[plugin] dispatch 异常: {e}", exc_info=True)


# 对话入口：只有命中以上规则才会进入（priority=3、命中即 block）。
# 它 block=True，因此任何需要看到全部消息的处理器（如落库监听）都必须排在它之前。
chat_handler = on_message(rule=Rule(is_chat_trigger), priority=_PRIORITY_CHAT, block=True)


@chat_handler.handle()
async def handle_chat(bot: Bot, event: GroupMessageEvent):
    """@ 触发主流程：加群锁 → 按需总结 → 跑 Pipeline → 逐条发送回复。"""
    if event.message_id in _plugin_handled_msgs:
        _plugin_handled_msgs.pop(event.message_id, None)
        logger.debug(f"[chat] 已由插件处理，跳过 LLM (group {event.group_id})")
        return
    lock = _group_locks[event.group_id]
    async with lock:
        ctx = ChatContext(
            user_id=event.user_id,
            group_id=event.group_id,
            msg_id=event.message_id,
            message=event.get_plaintext().strip(),
            # 平台原始句柄：Comes 调插件工具时，工具 handler 内部会用 event.send() /
            # event.bot.call_action()，必须是真实对象。只有 @ 回复这条路径能提供它们
            # （主动发言没有对应的用户事件，那条路径上工具能力自然不可用）。
            raw_event=event,
            bot=bot,
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

        # 压缩放在回复之后：不阻塞本次回复，摘要从下一轮开始生效
        if ctx.tail_start_id:
            schedule_compact(event.group_id, ctx.tail_start_id)

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
# 运行时开关（管理员临时关闭/恢复主动发言）
# ============================================================

_MUTE_KEYWORDS = ("安静", "闭嘴", "别说话", "停止主动发言")
_UNMUTE_KEYWORDS = ("恢复", "醒醒", "可以说话", "开启主动发言")


async def is_toggle_command(event: GroupMessageEvent) -> bool:
    """触发规则：已启用群 + @ 机器人 + 文本命中开关关键词。"""
    if not PROACTIVE_RUNTIME_TOGGLE_ENABLED:
        return False
    if event.group_id not in ALLOWED_GROUPS or not event.is_tome():
        return False
    text = event.get_plaintext().strip()
    return any(k in text for k in _MUTE_KEYWORDS + _UNMUTE_KEYWORDS)


# priority=1 必须高于 plugin_handler(priority=2) 与 chat_handler(priority=3, block=True)，
# 否则「安静」这类命令会被当成普通对话交给 LLM/插件
toggle_handler = on_message(rule=Rule(is_toggle_command), priority=_PRIORITY_TOGGLE, block=True)

# ── 监听器优先级不变量（启动期自检） ──
def _assert_listener_priorities() -> None:
    """校验落库监听器优先级最高；违反时输出 critical 日志（不中断启动）。"""
    for name, priority in (
        ("toggle_handler", _PRIORITY_TOGGLE),
        ("plugin_handler", _PRIORITY_PLUGIN),
        ("chat_handler", _PRIORITY_CHAT),
    ):
        if priority <= _PRIORITY_SILENT:
            logger.critical(
                f"❌ 监听器优先级错误：group_silent_listener(priority={_PRIORITY_SILENT}) "
                f"必须小于 {name}(priority={priority}, block=True)，"
                f"否则 @ 消息会被拦截而永不入库（见 2026-08-17 缺陷）。"
                f"请检查 ai_gateway.py 中三个监听器的 priority。"
            )
            return
    logger.debug(
        f"✅ 监听器优先级正常（落库 {_PRIORITY_SILENT} < toggle "
        f"{_PRIORITY_TOGGLE} < plugin {_PRIORITY_PLUGIN} < chat {_PRIORITY_CHAT}）"
    )


_assert_listener_priorities()


@toggle_handler.handle()
async def handle_toggle(bot: Bot, event: GroupMessageEvent):
    """管理员运行时开关：临时关闭/恢复本群主动发言。

    权限：PROACTIVE_TOGGLE_ADMINS 白名单，或群主/管理员。
    静音只影响主动发言，被 @ 时仍照常回复。
    非管理员触发时不做任何改动、也不回复——避免被当作可用命令反复尝试。
    """
    user_id = event.user_id
    role = getattr(getattr(event, "sender", None), "role", "") or ""
    if user_id not in PROACTIVE_TOGGLE_ADMINS and role not in ("owner", "admin"):
        logger.info(f"[Toggle] 群 {event.group_id} 用户 {user_id} 无权操作主动发言开关")
        return

    mute = any(k in event.get_plaintext() for k in _MUTE_KEYWORDS)
    set_proactive_muted(event.group_id, mute, operator_id=user_id)

    reply = "好，我不主动说话了，被 @ 还是会回的" if mute else "好，我继续正常参与聊天"
    await _record_bot_lines(int(bot.self_id), event.group_id, [reply])
    await toggle_handler.finish(
        Message([MessageSegment.reply(event.message_id), MessageSegment.text(reply)])
    )


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
        # 纯标点/单字兜底行（如 "......？"）无信息量，只会占用上下文尾巴窗口
        if len(text) < 2 or not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in text):
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
    allowed, reason = can_speak(group_id, "at")
    if not allowed:
        logger.debug(f"[主动@] 群 {group_id} 跳过：{reason}")
        return False
    proactive = get_proactive()

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

        # 主动 @ 同样推进对话：回复后异步触发压缩（不阻塞本次发言）
        if ctx.tail_start_id:
            schedule_compact(group_id, ctx.tail_start_id)

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


async def _announce_sleep_transition(bot: Bot, group_id: int) -> None:
    """检测睡眠状态跃变并播报一句（每日每类最多一次）。

    去重靠 group_runtime_state 的 last_*_announce_date：播报由定时任务触发，
    不记录已播报日期的话，睡眠期内重启会重复播报「我去睡了」。

    播报绕过 Pipeline（不需要 LLM），但仍写入 group_messages（BOT_SELF），
    让下一轮整合知道自己说过这句话。
    """
    if not PROACTIVE_SLEEP_ANNOUNCE:
        return

    kind = note_sleep_transition(group_id, is_sleeping())
    if kind is None:
        return

    today = date.today().isoformat()
    field = "last_sleep_announce_date" if kind == "sleep" else "last_wakeup_announce_date"
    if get_runtime_state(group_id)[field] == today:
        return

    pool = PROACTIVE_SLEEP_MESSAGES if kind == "sleep" else PROACTIVE_WAKEUP_MESSAGES
    if not pool:
        return
    line = random.choice(pool)

    try:
        await bot.send_group_msg(group_id=group_id, message=line)
    except Exception as e:
        logger.warning(f"⚠️ [{kind}] 播报发送失败: {e}")
        return

    mark_announced(group_id, kind, today)
    await _record_bot_lines(int(bot.self_id), group_id, [line])
    logger.info(f"{'🌙' if kind == 'sleep' else '☀️'} [{kind}] 群 {group_id}: {line}")


async def _proactive_speak_for_group(bot: Bot, group_id: int):
    """对单个群尝试主动发言：概率命中时生成一句自然的话并发送。

    :param bot: OneBot Bot 实例（用于组群发消息）
    :param group_id: 目标群号
    :return: None；命中时发送若干条群消息并记录“已发言”
    """
    # 先判断该群是否到了“可以主动发言”的时机（统一闸门判定）
    allowed, reason = can_speak(group_id, "join")
    if not allowed:
        logger.debug(f"[主动发言] 群 {group_id} 跳过：{reason}")
        return
    proactive = get_proactive()
    # gate 通过后再掷概率骰：概率是话题插话独有的（主动 @ 由配额与冷却约束，不掷骰）
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
            intent="proactive_join",
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

        # 主动发言同样推进对话：回复后异步触发压缩（不阻塞本次发言）
        if ctx.tail_start_id:
            schedule_compact(group_id, ctx.tail_start_id)

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
                # 睡眠/苏醒播报独立于主动发言：即使 gate 拒绝发言也要播报
                await _announce_sleep_transition(bot, group_id)
            except Exception as e:
                logger.warning(f"⚠️ 睡眠播报异常（群 {group_id}）: {e}")

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
# 会话空闲检查（结束会话并触发一次完整整合）
# ============================================================

if scheduler is not None and SESSION_CONTEXT_ENABLED:

    @scheduler.scheduled_job(
        "interval", seconds=SESSION_IDLE_CHECK_INTERVAL, id="session_idle_check"
    )
    async def session_idle_check_job():
        """空闲超时的会话：清空压缩状态并触发一次完整整合。

        会话结束时整合的理由：这一场对话的内容此前只以「压缩摘要」形式存在于
        内存，重启即失。结束时整合一次，把它沉淀为长期记忆的候选。
        """
        for group_id in idle_session_groups():
            try:
                if end_session(group_id):
                    logger.info(f"💤 [Session] 群 {group_id} 会话空闲结束，触发整合")
                    maybe_consolidate(group_id)
            except Exception as e:
                logger.warning(f"⚠️ 会话收尾异常（群 {group_id}）: {e}")


# ============================================================
# 定时整合（排空积压）
# ============================================================

if scheduler is not None:

    @scheduler.scheduled_job(
        "interval", seconds=CONSOLIDATION_SCHEDULE_INTERVAL, id="consolidation_drain"
    )
    async def consolidation_drain_job():
        """定期排空各群的整合积压。

        整合此前只在 @ 触发与主动发言前进行，被动摄入速度超过整合速度时会
        无界积压，超过 MESSAGE_CLEANUP_KEEP_COUNT 后未整合消息会被清理丢弃。
        """
        consolidator = get_consolidator()
        for group_id in ALLOWED_GROUPS:
            try:
                pending = consolidator.backlog(group_id)
                if pending < CONSOLIDATION_LOCAL_BATCH_SIZE:
                    continue
                rounds = await consolidator.drain_group(
                    group_id, max_rounds=CONSOLIDATION_MAX_ROUNDS_PER_RUN
                )
                if rounds:
                    logger.info(
                        f"🧠 [Drain] 群 {group_id} 整合 {rounds} 批，"
                        f"剩余积压 {consolidator.backlog(group_id)} 条"
                    )
            except Exception as e:
                logger.warning(f"⚠️ 定时整合异常（群 {group_id}）: {e}")


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
        # 清理后复查各群 source_kind 分布，捕捉 @ 消息未入库的退化（每日复查）
        with contextlib.suppress(Exception):
            from memory.db_cleaner import log_source_kind_distribution

            log_source_kind_distribution()
        # 同步清理过期的记忆决策追踪，防止 memory_traces 无限膨胀
        try:
            from memory.trace import prune_traces
            pruned = prune_traces(keep_days=30.0)
            if pruned > 0:
                logger.info(f"📊 [Trace] 已清理 {pruned} 条过期决策追踪")
        except Exception as e:
            logger.debug(f"📊 [Trace] 决策追踪清理异常: {e}")


# ============================================================
# 停止请求哨兵：deploy 写文件 → watcher 观察到 → 触发优雅关闭
# ============================================================
# asyncio.create_task 的返回值必须持有引用，否则任务可能在完成前被 GC 回收
_stop_watcher_task: asyncio.Task | None = None


@get_driver().on_startup
async def _start_stop_watcher() -> None:
    """启动时清残留哨兵并拉起 watcher。

    清残留必须放在最前面：上次硬杀可能留下文件，不清会导致新进程一启动就
    自杀——这是整个方案最致命的失败模式。
    """
    clear_stop_request()
    global _stop_watcher_task
    _stop_watcher_task = asyncio.create_task(watch_stop_request())


async def watch_stop_request() -> None:
    """轮询哨兵文件；发现请求后触发优雅关闭并退出循环。

    watcher 自己挂了而静默，比不停更糟糕——异常时记录后继续监控。
    """
    while True:
        try:
            await asyncio.sleep(STOP_WATCH_INTERVAL_SECONDS)
            if not is_stop_requested():
                continue
            info = read_stop_request() or {}
            source = f"来自 PID {info['pid']}" if info.get("pid") else "来自未知来源"
            reason = f"，原因：{info['reason']}" if info.get("reason") else ""
            logger.info(f"[StopSignal] 收到停止请求（{source}{reason}）")
            await _trigger_shutdown()
            break
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("[StopSignal] watcher 异常，继续监控")


def _find_uvicorn_server():
    """从 bot 模块取 uvicorn Server 实例（bot.py 自持，Driver 不落地）。

    ``python bot.py`` 时模块名为 ``__main__``，``python -m bot`` 或被
    import 时为 ``bot``，两处都试。原来遍历 ``dir(driver)`` 的实现会触发
    抛异常的 property，且已确认肯定找不到。
    """
    import sys

    for mod_name in ("__main__", "bot"):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        srv = getattr(mod, "SERVER", None)
        if srv is not None and hasattr(srv, "should_exit"):
            return srv
    return None


async def _trigger_shutdown() -> None:
    """触发优雅关闭，保证 _graceful_shutdown 的整合收尾后进程一定退出。

    阻塞缺陷（c099d0b）：前三档都只跑收尾、不让进程退出，导致 ``deploy stop``
    永远拖到第 4 阶硬杀。``await ls.shutdown()`` 更会 ``cancel_scope.cancel()``
    掉 watcher 自己所在的 task group，并把 ``_task_group`` 置 ``None``，使 uvicorn
    真退出时二次 ``shutdown()`` 抛 ``RuntimeError`` 且钩子被跑两遍。

    正确语义：能拿到 ``uvicorn.Server`` 就让 uvicorn 自己收尾（它会跑
    ``lifespan.shutdown`` → ``_graceful_shutdown``）；拿不到才手工跑钩子，
    且**必须** ``os._exit(0)``，否则端口继续监听、QQ 还能回消息。
    """
    # 0. 优先：让 uvicorn 自己收尾（会走完整 lifespan shutdown）
    server = _find_uvicorn_server()
    if server is not None:
        server.should_exit = True
        return

    # 拿不到 server：降级为手工钩子 + 硬退（否则进程不死）
    logger.warning("[StopSignal] 未找到 uvicorn Server，降级为手工钩子 + 硬退")
    driver = get_driver()
    ls = getattr(driver, "_lifespan", None)
    _ran_via_funcs = False
    if ls is not None:
        # 不直接 await ls.shutdown()：会 cancel 自己所在 task group
        # 且二次调用抛 RuntimeError。只手工 reversed 跑 _shutdown_funcs。
        funcs = getattr(ls, "_shutdown_funcs", None)
        if funcs is None:
            funcs = getattr(ls, "shutdown_funcs", None)
        if funcs is None:
            funcs = getattr(driver, "_on_shutdown", None)
        if funcs:
            try:
                seq = list(funcs)
            except Exception:
                seq = []
            for f in reversed(seq):
                try:
                    r = f()
                    if inspect.isawaitable(r):
                        await r
                except Exception:
                    logger.exception("[StopSignal] 手工执行 shutdown 钩子失败，继续下一个")
            _ran_via_funcs = True

    if not _ran_via_funcs:
        # 既无 _shutdown_funcs 又无 server，直接跑整合收尾
        try:
            await _graceful_shutdown()
        except Exception:
            logger.exception("[StopSignal] 直接执行 _graceful_shutdown 失败")

    # 手工路径必须硬退：否则只是跑完钩子、进程继续服务
    try:
        import sys

        sys.stdout.flush()
        sys.stderr.flush()
        complete = getattr(logger, "complete", None)
        if callable(complete):
            with contextlib.suppress(Exception):
                complete()
    except Exception:
        pass
    os._exit(0)


# ============================================================
# 优雅停止：等待在途后台任务收尾，避免整合被中途 kill
# ============================================================
@get_driver().on_shutdown
async def _graceful_shutdown() -> None:
    """等整合/压缩收尾后再退出，避免 checkpoint 与消息表不一致。

    三类在途任务：整合（consolidator）、会话压缩（session_compact）、
    主动 @ 的回应检测（_reply_check_tasks）。前两类必须等——整合中途退出
    会让那批消息的候选丢失（checkpoint 未推进，下次会重跑，数据不会坏，
    但白跑一次 LLM）；回应检测只是 sleep，直接取消。

    超时上界取 SHUTDOWN_GRACE_SECONDS，超时后放弃等待并告警。
    """
    if _stop_watcher_task is not None and _stop_watcher_task is not asyncio.current_task():
        _stop_watcher_task.cancel()
    from memory.consolidator import pending_tasks as pending_consolidations
    from memory.session_compact import pending_tasks as pending_compactions

    await wait_for_tasks(
        _reply_check_tasks,
        list(pending_consolidations()) + list(pending_compactions()),
        SHUTDOWN_GRACE_SECONDS,
    )
