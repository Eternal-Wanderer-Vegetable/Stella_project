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
   - capability_handler（能力查询，priority 1）：@ 机器人问「你能做什么」时直接读能力
     注册表列出清单，不经模型。与 toggle_handler 同优先级且都 block=True，两者的 rule
     必须机械互斥——见 _assert_capability_rule_disjoint()；
   - reload_handler（插件热重载，priority 1）：管理员发「@Stella 重载插件 <名>」时
     重载单个插件。默认关闭（ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED），与上面两个 handler
     同样要机械互斥——插件名是任意字符串，见 _assert_reload_rule_disjoint()；
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
import contextvars
import functools
import inspect
import math
import os
import random
import sqlite3
import time
import uuid
from collections import OrderedDict, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from nonebot import get_driver, logger, on_message
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.exception import FinishedException
from nonebot.rule import Rule

from capability.hooks import register as register_capability_hook
from config import (
    ADDRESSING_ENABLED,
    ALLOWED_GROUPS,
    ASTRBOT_COMPAT_ALLOW_PRIVATE,
    ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED,
    ASTRBOT_PLUGIN_HOT_RELOAD_WATCH,
    ASTRBOT_PLUGIN_HOT_RELOAD_WATCH_INTERVAL,
    CAPABILITY_QUERY_ENABLED,
    CONSOLIDATION_LOCAL_BATCH_SIZE,
    CONSOLIDATION_MAX_ROUNDS_PER_RUN,
    CONSOLIDATION_SCHEDULE_INTERVAL,
    CONSOLIDATION_TRIGGER_NEW_MESSAGES,
    DB_CLEANUP_CLEAR_MESSAGES,
    DB_CLEANUP_ON_START,
    DB_PATH,
    EXPRESSION_SWEEP_INTERVAL,
    EXTENSIONS_DIR,
    LLM_TIMEOUT,
    MESSAGE_CLEANUP_ENABLED,
    MESSAGE_CLEANUP_HOUR,
    PARTICIPATION_ENABLED,
    PARTICIPATION_TICK_INTERVAL,
    PARTICIPATION_TRIGGER_ENABLED,
    PRIVATE_CHAT_ALLOWLIST,
    PRIVATE_CHAT_ENABLED,
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
    SOCIAL_ENABLED,
    STOP_WATCH_INTERVAL_SECONDS,
    SYSTEM_PROMPT_PATH,
)
from config.spaces import prompt_text, resolve_space
from core.context import ChatContext, normalize_display_name
from core.llm import ROLE_CHAT, backend_for
from core.llm.registry import log_summary as log_llm_summary
from core.llm.usage_store import budget_blocked
from core.pipeline import Pipeline
from core.planner import RestrictedPlanner
from core.reply_gate import get_reply_gate
from core.runtime.facade import E_CANCELLED, RuntimeTurnError
from core.shutdown import wait_for_tasks
from core.social.contracts import (
    ConversationScope,
    MessageEvidence,
    aggregate_delivery_status,
    delivered_texts,
    new_trace_id,
)
from core.social.delivery import deliver_lines
from core.stop_signal import clear_stop_request, is_stop_requested, read_stop_request
from core.vision import extract_image_sources, vision_available
from extensions import load_extensions
from memory import addressing, expression_learning, social_store
from memory.addressing_intent import (
    CLEAR_ADDRESS,
    NOT_ADDRESS_REQUEST,
    QUERY_ADDRESS,
    SET_OTHER_ADDRESS,
    SET_SELF_ADDRESS,
    AddressingRequest,
    classify_addressing,
    is_likely_addressing_request,
)
from memory.compressor import get_compressor
from memory.consolidator import get_consolidator, maybe_consolidate
from memory.participation import get_participation_manager
from memory.post_processors import (
    bad_phrase_filter,
    log_thought,
    parse_output,
    split_lines,
)
from memory.pre_processors import (
    build_context,
    record_message,
    resolve_reply_target,
)
from memory.proactive import get_proactive
from memory.proactive_gate import (
    can_speak,
    is_sleeping,
    note_sleep_transition,
    user_now,
)
from memory.proactive_prompt import (
    PROACTIVE_SKIP_MARKER,
    build_instruction,
    is_proactive_skip,
)
from memory.proactive_state import (
    get_runtime_state,
    mark_announced,
    record_at,
    record_reply_result,
    reset_no_reply,
    set_proactive_muted,
)
from memory.proactive_target import pick_target
from memory.session_compact import schedule_compact
from memory.session_context import end_session
from memory.session_context import idle_groups as idle_session_groups
from memory.session_context import touch as session_touch

# cometa QQ 桥接：必须在模块级绑定——handle_chat 的委派分支直接引用它，
# 只在 _start_cometa 里局部导入绑定的只是局部名，@ 触发时 NameError
# （2026-09-30 用户实测缺陷 #9；探针测试绕过了 handle_chat 入口所以没炸到）。
from stella_project.plugins.bot_main import cometa_bridge

# ============================================================
# Pipeline 构建
# ============================================================
# 全局唯一的处理管线：前钩子做记忆召回/上下文组装，后钩子做输出解析与过滤
pipeline = Pipeline(timeout=LLM_TIMEOUT)

# ── 每群互斥锁：@-回复与主动发言不可并发，避免管道竞争 ──
# defaultdict 保证每个群首次访问时自动生成一把锁；锁内串行执行 Pipeline =
# 同一群人同一时刻只跑一次推理，防止并发写同一条上下文造成状态混乱
_group_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

# ── 私聊会话锁（计划 §6.2）：按规范会话键串行，不同私聊互不阻塞 ──
# 不能复用 _group_locks：私聊没有 group_id（0 占位），且绝不因「同一个用户
# 在多个群」而串行锁住所有会话——锁只锁同一个会话。
_private_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _event_key(event: MessageEvent) -> str:
    """事件的去重键（计划 §6.2）：至少包含 bot、会话、message_id。

    相同 msg_id 在不同 Bot/不同会话不可互相压掉——OneBot 的 message_id 只在
    单 Bot 内保证唯一，多 Bot/私聊群同号时裸 message_id 会误伤。
    """
    if isinstance(event, GroupMessageEvent):
        conv = f"group:{event.group_id}"
    else:
        conv = f"private:{getattr(event, 'user_id', 0)}"
    return f"{event.self_id}:{conv}:{event.message_id}"


# 回应检测的后台任务集合：asyncio.create_task 的返回值必须持有引用，
# 否则任务可能在完成前被 GC 回收
_reply_check_tasks: set[asyncio.Task] = set()

# 插件已处理标记：event_key -> timestamp，限长 256，避免 pydantic 模型上 setattr 的兼容问题
_plugin_handled_msgs: OrderedDict[str, float] = OrderedDict()
_addressing_decisions: OrderedDict[str, AddressingRequest] = OrderedDict()


# ============================================================
# 消息流程追踪（计划 §6.2/§6.3 A）：入口 root 与语义埋点
# ============================================================
# root 在 NoneBot event preprocessor（所有 matcher 之前）创建，多个 matcher
# （静默/命令/插件/聊天）共用同一 root；postprocessor 在全部 matcher 结束后
# 关闭。root 里只存安全关联键（platform/bot/group/msg_id），绝不存原文。
_flow_roots: "OrderedDict[tuple[str, str], Any]" = OrderedDict()
_FLOW_ROOTS_MAX = 256


def _flow_conversation_key(event: MessageEvent) -> str:
    """规范会话键（修复计划 §6.1）：qq:<bot>:group:<群号> / qq:<bot>:private:<QQ号>。

    preprocessor 阶段不查业务库即可从事件字段构造；私聊 storage ID 由注册表
    分配后在 matcher 内幂等补充。
    """
    if isinstance(event, GroupMessageEvent):
        return f"qq:{event.self_id}:group:{event.group_id}"
    return f"qq:{event.self_id}:private:{getattr(event, 'user_id', 0)}"


def _flow_key(event: MessageEvent) -> tuple[str, str]:
    """流程 root 的键（修复计划 §6.1 R2）：完整事件身份。

    旧键 (group_id|0, message_id) 让不同 Bot/不同私聊 peer 的同号消息碰撞
    （复核报告 R2 探针：Bot10001/20001 与 Bot10002/20002 的消息 7 同为
    (0,7)）。新键 = (conversation_key, message_id)，message ID 原样字符串化。
    """
    return (_flow_conversation_key(event), str(event.message_id))


def _flow_source_key(event: MessageEvent) -> str:
    """来源消息键：<conversation_key>:msg:<message_id>（修复计划 §6.1）。"""
    return f"{_flow_conversation_key(event)}:msg:{event.message_id}"


def _flow_scope_of(event: MessageEvent) -> str:
    """流程 root 的 scope：规范会话身份（私聊不再共享 qq:0）。"""
    if isinstance(event, GroupMessageEvent):
        return f"qq:{event.group_id}"
    return f"qq:{event.self_id}:private:{getattr(event, 'user_id', 0)}"


def _flow_root_for(event: MessageEvent):
    """取本事件的流程 root；没有（preprocessor 未生效等）时返回 None。"""
    found = _flow_roots.get(_flow_key(event))
    return None if (found is None or found.ended) else found


def _flow_root_or_create(event: MessageEvent, root_kind: str):
    found = _flow_root_for(event)
    if found is not None:
        return found
    try:
        from core.observability import message_flow

        return message_flow.begin_trace(
            root_kind=root_kind, platform="qq",
            scope=_flow_scope_of(event),
            conversation_key=_flow_conversation_key(event),
            bot_id=str(event.self_id),
            conversation_kind="group" if isinstance(event, GroupMessageEvent)
            else "private",
            peer_id=str(event.group_id if isinstance(event, GroupMessageEvent)
                        else getattr(event, "user_id", 0)),
            source_message_id=str(event.message_id),
            source_message_key=_flow_source_key(event),
        )
    except Exception:
        return None


def _evict_flow_roots(max_active: int = _FLOW_ROOTS_MAX) -> None:
    """缓存淘汰（修复计划 §6.1）：活跃 root 显式留痕，绝不静默失踪。"""
    while len(_flow_roots) > max_active:
        _key, evicted = _flow_roots.popitem(last=False)
        try:
            if evicted is not None and not evicted.ended:
                _flow_decision(evicted, "flow.ingress", status="unknown",
                               reason_code="ingress_cache_evicted",
                               summary="root 缓存淘汰：结束路径改走注册表回查")
        except Exception:
            pass


def _flow_span(fctx, node_id: str, **kw):
    try:
        from core.observability import message_flow

        return message_flow.span(fctx, node_id, **kw)
    except Exception:
        import contextlib as _cl

        return _cl.nullcontext()


def _flow_decision(fctx, node_id: str, **kw) -> None:
    try:
        from core.observability import message_flow

        message_flow.decision(fctx, node_id, **kw)
    except Exception:
        pass


def _flow_checkpoint(fctx, node_id: str, **kw) -> None:
    try:
        from core.observability import message_flow

        message_flow.checkpoint(fctx, node_id, **kw)
    except Exception:
        pass


def _flow_set_outcome(fctx, outcome: str) -> None:
    try:
        if fctx is not None and not fctx.ended:
            fctx.outcome = outcome
    except Exception:
        pass


# 命令回复捕获：装饰器在 handler 存续期持有 fctx，matcher.finish 包装
# （见 _flow_watch_finish）据此把发出的文本记成 command.reply 检查点——
# 命令回复不经 BOT_SELF 落库，这是它在流程页可见的唯一通道。
_flow_reply_ctx = contextvars.ContextVar("_flow_reply_ctx", default=None)


def _flow_reply_text(arg: Any) -> str:
    """matcher.finish/send 的首个消息参数 → 纯文本（Message/段/串皆可）。"""
    try:
        if arg is None:
            return ""
        if isinstance(arg, str):
            return arg
        extract = getattr(arg, "extract_plain_text", None)
        if callable(extract):
            return extract() or ""
        return str(arg)
    except Exception:
        return ""


def _flow_watch_finish(matcher) -> None:
    """包装 matcher.finish：发出的文本入流程（仅群事件有 fctx 时生效）。

    每个 ``on_message()`` 返回独立的 Matcher 子类，包装互不影响；原方法
    的行为（含 FinishedException 控制流）原样保留。
    """
    original = matcher.finish

    async def _finish(*args, **kwargs):
        fctx = _flow_reply_ctx.get()
        try:
            return await original(*args, **kwargs)
        finally:
            if fctx is not None and args:
                text = _flow_reply_text(args[0])
                if text:
                    _flow_checkpoint(fctx, "command.reply", summary=text[:500])

    matcher.finish = _finish


def _flow_command(node_id: str):
    """命令处理器埋点装饰器：整个 handler 一个 span，终态照实（计划 §6.3 A）。

    ``FinishedException`` 是 NoneBot matcher 的正常结束控制流，不是失败；
    装饰器透传所有异常，不改变任何分发语义。私聊事件（无流程 root）全部
    空转——诚实缺席，不伪造。
    """

    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(bot, event):
            fctx = None
            if isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
                fctx = _flow_root_or_create(event, "qq_command")
            token = _flow_reply_ctx.set(fctx)
            sp = _flow_span(fctx, node_id)
            sp.__enter__()
            try:
                await fn(bot, event)
            except FinishedException:
                sp.__exit__(None, None, None)
                _flow_set_outcome(fctx, "command_sent")
                raise
            except Exception as e:
                sp.__exit__(type(e), e, e.__traceback__)
                _flow_set_outcome(fctx, "command_error")
                raise
            finally:
                _flow_reply_ctx.reset(token)
            sp.__exit__(None, None, None)
            _flow_set_outcome(fctx, "command_done")

        return wrapper

    return deco


try:
    from nonebot.message import event_postprocessor, event_preprocessor

    @event_preprocessor
    async def _flow_ingress_root(event: MessageEvent):
        """每条消息最早的处理点：建 shared root（规则/过滤之前，计划 §6.2）。

        群与私聊都建（私聊此前被 group-only skip 跳过，trace 缺失）；
        scope 用规范会话身份；完整事件身份进 root 键（修复计划 §6.1）。
        """
        if not isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
            return
        try:
            from core.observability import message_flow

            key = _flow_key(event)
            if key in _flow_roots:
                return
            root = message_flow.begin_trace(
                root_kind="qq_private" if isinstance(event, PrivateMessageEvent) else "qq_passive",
                platform="qq",
                scope=_flow_scope_of(event),
                conversation_key=_flow_conversation_key(event),
                bot_id=str(event.self_id),
                conversation_kind="group" if isinstance(event, GroupMessageEvent)
                else "private",
                peer_id=str(event.group_id if isinstance(event, GroupMessageEvent)
                            else getattr(event, "user_id", 0)),
                source_message_id=str(event.message_id),
                source_message_key=_flow_source_key(event),
            )
            _flow_roots[key] = root
            _flow_roots.move_to_end(key)
            _evict_flow_roots()
        except Exception:
            pass

    @event_postprocessor
    async def _flow_ingress_end(event: MessageEvent):
        """全部 matcher 结束后关闭 root（root 同步边界 = 事件处理结束）。

        compare-and-pop（修复计划 §6.1）：以缓存键取得 ctx 后核对身份，
        另一事件/ctx 的迟到 postprocessor 不得关闭本 root；缓存键未命中
        （淘汰）时按来源键回查活跃注册表兜底收口。
        """
        if not isinstance(event, (GroupMessageEvent, PrivateMessageEvent)):
            return
        try:
            from core.observability import message_flow

            root = _flow_roots.pop(_flow_key(event), None)
            if root is None:
                root = message_flow.by_source_key(_flow_source_key(event))
            if (root is not None and not root.ended
                    and (not root.conversation_key
                         or root.conversation_key == _flow_conversation_key(event))):
                message_flow.end_trace(
                    root, outcome=root.outcome or "passive_only")
        except Exception:
            pass
except Exception as e:  # pragma: no cover - 老版本 NoneBot 缺钩子时不阻断装载
    logger.warning(f"⚠️ [Flow] NoneBot 事件钩子注册失败（消息流程不可观测）: {e}")

async def describe_images_hook(ctx: ChatContext) -> ChatContext:
    """图片转述钩子：把 ctx.image_sources 里的图转成文字描述并入 ctx.message。

    priority=60（先于 build_context）：尾巴组装与记忆检索看到的就是带描述
    的完整文本。VISION 未绑定（默认）时 describe_images 返回空，本钩子
    什么都不做——整条链路与旧版一致。

    转述完成后按 msg_id 回写 group_messages 刚插入的那行（priority-0 落库
    时图片描述还没生成，当时只能写 [图片] 占位）。任何失败只降级为占位，
    绝不阻断回复——与 activate_capabilities「钩子不抛异常」的契约一致。
    """
    if not ctx.image_sources:
        return ctx
    try:
        from core.vision import describe_images, update_recorded_message

        captions = await describe_images(ctx.image_sources, user_text=ctx.message)
    except Exception as e:
        logger.warning(f"⚠️ [Vision] 图片转述异常（按占位继续）: {e}")
        return ctx
    if not captions:
        return ctx
    ctx.image_captions = captions
    ctx.message += f"「图片内容：{'；'.join(captions)}」"
    try:
        await update_recorded_message(ctx.group_id, ctx.msg_id, ctx.message)
    except Exception as e:
        logger.debug(f"[Vision] 回写消息描述失败（跳过）: {e}")
    return ctx


# pre-hook 按 priority 降序执行（数值越大越先）：
# 60 -> describe_images_hook（图片转述：图 → 文字描述并入 ctx.message）
# 50 -> build_context（组装短期上下文：话题摘要 + 原始尾巴 + 会话摘要）
# 45 -> activate_capabilities（Router 判定 → 并行跑 {长期记忆检索, Comes 工具执行}）
#
# build_user_context **不再单独注册**：它已被 activate_capabilities 接管。
# 方案第 17 节要求 Memory 与 Comes 并行，两个独立钩子只能串行，必须收进同一个
# gather。这里再注册一次会让记忆检索跑两遍（一次串行、一次在 gather 里）。
pipeline.register_pre_hook(describe_images_hook, priority=60)
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

# 指定 LLM 后端：由 core.llm.registry 按「角色 → 端点」解析（见 .env 的 LLM_ROLE_CHAT_*）。
# 这里不再直接读 LM_STUDIO_*，否则「切到在线模型」又变成要改代码。
_chat_backend = backend_for(ROLE_CHAT)
if _chat_backend is None:
    # 返回 None 说明 CHAT 角色绑的端点槽没配地址。不在这里抛异常：整个插件加载
    # 失败会连 GUI 与 doctor 一起带走，用户就再也没有把配置改回来的入口了。
    logger.error(
        "❌ CHAT 角色没有可用端点（LLM_ROLE_CHAT_ENDPOINT 指向的槽未配 BASE_URL），"
        "主聊天链路只能走兜底回复。运行 python -m deploy doctor 查看解析结果。"
    )
else:
    pipeline.set_llm_backend(_chat_backend)
    # 受限 Planner（设计阶段五）：与 Replyer 共用 CHAT 后端与 LLM 名额——
    # 深度路径 2 次 LLM 的硬上限在 core/pipeline.py 里统一扣减。
    pipeline.set_planner(RestrictedPlanner(_chat_backend))

# 启动日志打一张「角色 → 端点 → 模型 → 闸门」表，并把解析问题一次性报出来。
# 「无缝切换」要能被信任，前提是切完能一眼确认到底切没切成。
log_llm_summary()

# 读取系统提示词文件（若存在则注入，否则只警告不中断）
system_prompt_path = SYSTEM_PROMPT_PATH.resolve()
if system_prompt_path.exists():
    pipeline.system_prompt = system_prompt_path.read_text(encoding="utf-8")
    logger.success(f"✅ 加载系统提示词 ({len(pipeline.system_prompt)} 字符)")
else:
    logger.warning(f"⚠️ 系统提示词文件不存在: {system_prompt_path}")


def _space_system_prompt(ctx: ChatContext) -> str:
    """按共享空间选择人格；空间 prompt 不可用时由 config.spaces 回退默认文件。

    私聊轮次的 group_id 是 0，绝不能对 0 触发 resolve_space（会凭空分配一个
    「群 0」的账本条目）——ctx.group_shared_space 由入口显式携带（私聊是
    隔离空间名，prompt 文件不存在时 prompt_text 回退默认人格，计划 §6.2：
    私聊不继承任意群人格）。
    """
    try:
        space = ctx.group_shared_space or resolve_space(int(ctx.group_id))
        return prompt_text(space) or pipeline.system_prompt
    except Exception as e:
        logger.warning(f"⚠️ 读取空间人格失败，使用默认人格: {e}")
        return pipeline.system_prompt


pipeline.system_prompt_resolver = _space_system_prompt

# 加载插件目录下所有扩展（扩展可再向 pipeline 注册钩子/资源）
load_extensions(pipeline, EXTENSIONS_DIR)


async def _run_turn_via_engine(session_key: str, ctx: ChatContext) -> ChatContext:
    """轮次唯一执行入口（计划 §R.5：legacy 双路开关已退役）。

    经 facade 进程内执行器：prepare/finalize 复用同一条管线，生成是
    进程内 provider 调用。deadline 与旧引擎单次生成超时对齐
    （LLM_TIMEOUT，超时都走兜底文案，BC-5）。

    ``session_key`` 是 runtime owner 键：群沿用旧 ``qq:{group_id}`` 别名
    （与主动发言竞争同一会话，锁嵌套语义不变）；私聊用规范会话键
    （计划 §6.1）。deadline 与旧引擎单次生成超时对齐。
    """
    from core.runtime.facade import ensure_shared_facade_started

    facade = await ensure_shared_facade_started()
    return await facade.submit_turn(session_key, pipeline, ctx, deadline=LLM_TIMEOUT)


def _social_delivery_enabled() -> bool:
    """投递回执与标准化证据是否落库（总开关；shadow 模式也记事实）。"""
    return bool(SOCIAL_ENABLED)

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

# ── 启动时挂上 LLM 用量记账 ──
# 必须在 Schema 迁移**之后**：记账要写 llm_usage_daily，那张表由迁移建出来；
# 挂早了会在库还没升级时先 connect 出一个半成品文件。
# 记账关闭时 install() 直接返回 False，一次也不碰数据库。
try:
    from core.llm import usage_store

    if usage_store.install():
        logger.info("💰 [Startup] LLM 用量记账已启用（llm_usage_daily）")
except Exception as e:
    # 记账是旁路，挂不上就不记，绝不能拖垮插件加载
    logger.warning(f"⚠️ LLM 用量记账挂载失败（不影响运行）: {e}")

# ── 启动时社交旁表组件迁移（总开关默认关闭：不开就不碰库） ──
# 组件版本独立于核心记忆 schema（memory/social_schema.py）；迁移自带
# 旧库导入与备份，失败只让社交功能停用，绝不阻断插件加载。
if SOCIAL_ENABLED:
    try:
        from memory.social_schema import ensure_social_schema

        _social_import_stats = ensure_social_schema()
        logger.info(f"📦 [Startup] 社交旁表就绪（旧库导入: {_social_import_stats or '无'}）")
    except Exception as e:
        logger.warning(f"⚠️ 社交旁表迁移失败（社交功能停用，不影响运行）: {e}")

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
    fctx = _flow_root_for(event)
    if event.group_id not in ALLOWED_GROUPS:
        _flow_decision(fctx, "ingress.passive.filter", status="skipped",
                       reason_code="group_not_allowed")
        return
    # 防止 OneBot 回显自身消息造成重复入库（自身发言会经 _record_bot_lines 单独落库）
    if event.user_id == event.self_id:
        _flow_decision(fctx, "ingress.passive.filter", status="skipped",
                       reason_code="self_echo")
        return
    text = event.get_plaintext().strip()
    if text.startswith("/"):
        _flow_decision(fctx, "ingress.passive.filter", status="skipped",
                       reason_code="slash_command")
        return
    if not text:
        # 纯图片消息：识图功能可用时按 [图片] 占位入库，让尾巴/整合知道
        # 「刚才有人发过图」；不可用（默认）时照旧不落库，与旧版一致。
        if not (vision_available() and extract_image_sources(event)):
            _flow_decision(fctx, "ingress.passive.filter", status="skipped",
                           reason_code="empty_text_no_vision")
            return
        text = "[图片]"
    _flow_checkpoint(fctx, "ingress.passive.filter", summary="passed")
    # 消息关系提取（多人身份修复计划 §6.2）：无条件执行（不依赖 SOCIAL_ENABLED），
    # 在 record_message **之前**写入 ctx 信封，与正文同一短事务落库。社会学习
    # 消费同一份解析结果，但主历史关系不再只存在于旁表。
    reply_to_id, mentioned_users = _extract_message_relations(event)
    sender_display = normalize_display_name(
        getattr(getattr(event, "sender", None), "card", "")
        or getattr(getattr(event, "sender", None), "nickname", "")
    )
    conversation_key = f"qq:{event.self_id}:group:{event.group_id}"
    reply_target_uid = resolve_reply_target(
        reply_to_id or "",
        event.group_id,
        bot_id=str(event.self_id),
        conversation_key=conversation_key,
    )
    ctx = ChatContext(
        user_id=event.user_id,
        group_id=event.group_id,
        msg_id=event.message_id,
        message=text,
        # @ 到 Bot 的消息是最可靠的用户信息源，落库时标记来源以供整合/审计
        source_kind="AT_MENTION" if event.is_tome() else "PASSIVE",
        # 追踪 ID 在接入入口、硬门禁前创建（计划 §6.1）；与流程 root 共用
        # 同一身份（§6.2 入口绑定），证据行/投递/派生全部挂同一 trace。
        trace_id=fctx.trace_id if fctx is not None else new_trace_id(),
        # v3 会话身份 + v4 信封（关系权威来自平台事件，正文不可伪造）
        conversation_kind="group",
        conversation_key=conversation_key,
        bot_id=str(event.self_id),
        peer_id=str(event.group_id),
        storage_session_id=event.group_id,
        sender_display_name=sender_display,
        reply_to_msg_id=str(reply_to_id or ""),
        reply_target_user_id=reply_target_uid,
        mentioned_user_ids=tuple(mentioned_users),
        relation_version=1,
    )
    try:
        from core.observability import message_flow

        message_flow.attach(ctx, fctx)
    except Exception:
        pass
    with _flow_span(fctx, "ingress.passive.persist"):
        await record_message(ctx)
        # 身份声明 hook（多人身份修复计划 §6.3）：入库拿到 source_row_id 后
        # 解析本人自我介绍/有目标纠正；零命中零写库，异常不拖垮消息链路。
        with contextlib.suppress(Exception):
            from memory.conversation_identity import process_message_identity

            process_message_identity(ctx)
    # 不再每条消息都触发短期记忆总结（避免频繁空检查消耗服务器资源）；
    # 只记录时间戳用于频率估算，总结改由 @ 触发或主动发言前按需触发。
    with _flow_span(fctx, "ingress.passive.state"):
        get_proactive().record_message(ctx.group_id, ctx.user_id)
        if ctx.source_kind == "AT_MENTION":
            # 主动 @ 的回应检测只认「对 Bot 说话」，所以这个时间戳必须单独记
            get_proactive().record_tome(ctx.group_id, ctx.user_id)
            # 只要还愿意跟 Bot 说话就不算「不想聊」，顺手解除退避（自愈，见 reset_no_reply）
            reset_no_reply(ctx.group_id, ctx.user_id)
        # 记录会话活动时间（用于空闲判定）。只更新时间戳，无 DB 访问。
        session_touch(ctx.group_id)

    # 消息证据（计划 §6.1）：关系解析已在入库前完成（ctx 信封），这里只消费
    # 同一份结果。总开关关闭时不碰旁表；两个 matcher 重复处理同一消息由
    # (platform, bot, group, platform_message_id) 复合唯一索引幂等兜底，
    # first-writer-wins。
    social_event_id = ""
    if _social_delivery_enabled():
        with contextlib.suppress(Exception), _flow_span(fctx, "ingress.passive.social"):
            social_event_id = social_store.record_event(
                MessageEvidence(
                    scope=ConversationScope.for_qq(event.group_id),
                    platform_message_id=str(event.message_id),
                    user_id=str(event.user_id),
                    source_kind=ctx.source_kind,
                    reply_to_id=reply_to_id,
                    mentioned_user_ids=mentioned_users,
                    text_excerpt=text,
                    trace_id=ctx.trace_id,
                )
            ) or ""
    # 黑话信号采集（设计阶段六 → 计划 §6.4）：社交模式接管时逐 hit 落
    # occurrence 证据（event_id 幂等）；未接管时走进程内计数器，热路径开销不变。
    with _flow_span(fctx, "ingress.passive.expression"):
        expression_learning.note_passive_message(
            ctx.group_shared_space, ctx.user_id, text,
            group_id=event.group_id, event_id=social_event_id,
        )

    if PARTICIPATION_ENABLED and ctx.source_kind == "PASSIVE":
        with _flow_span(fctx, "ingress.passive.participation") as part_span:
            decision = await get_participation_manager().observe(
                ctx.group_id,
                ctx.user_id,
                text,
                msg_id=event.message_id,
                reply_to=int(reply_to_id) if (reply_to_id or "").isdigit() else None,
                mentioned_users=tuple(int(m) for m in mentioned_users if m.isdigit()),
                is_tome=event.is_tome(),
                has_image=bool(extract_image_sources(event)) if vision_available() else False,
                has_emoji=bool(expression_learning._EMOJI_RE.search(text)),
                # 消息链上的 participation 探针显式挂在消息 root（计划 §6.2：
                # 显式传递优先于环境隐式传播），全等级决策事件随消息 trace 可查
                flow_ctx=fctx,
            )
            part_span.finish(
                status="succeeded",
                metrics={"decision": getattr(decision, "decision", "") or ""},
            )
        if decision is not None and decision.should_speak and PARTICIPATION_TRIGGER_ENABLED:
            # ALLOW_LLM：交给统一执行器（群锁/预算/去重/consolidate 都在里头）。
            # create_task：评分在 priority 0 的非阻断监听器里，不能同步等 LLM。
            _flow_checkpoint(fctx, "participation.spawn",
                             summary="spawned proactive speak, not awaited",
                             metrics={"trigger_text_chars": len(text)})
            _spawn_participation_speak(event.group_id, decision, trigger_text=text,
                                       parent_trace_id=ctx.trace_id)


def _maybe_identity_direct_reply(ctx) -> None:
    """整条身份问句的确定性直复（多人身份修复计划 §6.3）。

    命中（整条「我是谁」+ 本会话已验证本人声明）时填好 reply/lines：轮次
    进入管线后 prepare_turn 见 ctx.reply 直接 DIRECT，零 LLM；未命中不动
    ctx（含复合问题——照常交给 LLM）。失败静默，绝不阻塞正常回复。
    """
    try:
        from memory.conversation_identity import identity_question_reply

        direct = identity_question_reply(ctx)
    except Exception:
        return
    if direct:
        ctx.reply = direct
        ctx.lines = [direct]
        logger.info(f"🪪 [Identity] 身份问句确定性直复（用户 {ctx.user_id}）")


def _extract_message_relations(event: GroupMessageEvent) -> tuple[str | None, tuple[str, ...]]:
    """提取回复引用与 @ 目标（除 Stella 自身、拒绝 @all），供证据与评分层使用。"""
    reply_to: str | None = None
    mentioned: list[str] = []
    try:
        segments = list(event.get_message())
    except Exception:
        # 事件对象不提供消息段（异常适配器/桩）→ 关系 unknown，不猜
        return None, ()
    for segment in segments:
        seg_type = _message_segment_type(segment)
        if seg_type == "reply":
            reply_to = str(_message_segment_data(segment).get("id") or "") or None
        elif seg_type == "at":
            qq = str(_message_segment_data(segment).get("qq") or "").strip()
            if not qq or qq.lower() == "all" or qq == str(event.self_id):
                continue
            if qq not in mentioned:
                mentioned.append(qq)
    return reply_to, tuple(mentioned)


async def is_chat_trigger(event: GroupMessageEvent) -> bool:
    """触发规则：(1) 属于已启用群 (2) 有人 @ 机器人 (3) 附带非空文本。

    识图功能可用（``vision_available()``）时，条件 3 放宽为「非空文本或
    带图片」——@ Stella + 纯图也能进对话；功能未配置（默认）时判据与
    旧版逐字一致，纯图消息照旧不触发。
    """
    _tome = event.is_tome()
    _txt = event.get_plaintext().strip()
    _gid_ok = event.group_id in ALLOWED_GROUPS
    logger.info(f"[chat_debug] is_chat_trigger gid={event.group_id} gid_ok={_gid_ok} is_tome={_tome} text={_txt!r} self_id={event.self_id} raw={event.get_message()!r}")
    if event.group_id not in ALLOWED_GROUPS:
        return False
    if not event.is_tome():
        return False
    if len(event.get_plaintext().strip()) > 0:
        return True
    # 识图功能未启用时 extract_image_sources 不取图源、直接判空，
    # 行为与旧版一致（纯图 @ 不触发）。
    return vision_available() and bool(extract_image_sources(event))


async def is_plugin_trigger(event: MessageEvent) -> bool:
    """AstrBot 插件的触发规则——实现在 ``astrbot_compat.pipeline.should_dispatch``。

    判定逻辑放在兼容层里：「哪些平台事件该进插件管道」是兼容层的语义（它要对齐上游
    ``WakingCheckStage``），而这里只负责把 Stella 侧的两项配置传进去。这样那条规则
    也能被单测覆盖——ai_gateway 在测试里 import 不进来（import 期就 ``get_driver()``）。
    """
    from astrbot_compat.pipeline import should_dispatch

    return should_dispatch(
        event,
        allowed_groups=ALLOWED_GROUPS,
        allow_private=ASTRBOT_COMPAT_ALLOW_PRIVATE,
    )


# AstrBot 插件入口（priority=2）：命中则不再走 Stella LLM（priority=3）。
# block=False 保证未命中时仍能落到 chat_handler；命中时通过 _plugin_handled_msgs 让 chat 跳过。
plugin_handler = on_message(rule=Rule(is_plugin_trigger), priority=_PRIORITY_PLUGIN, block=False)


@plugin_handler.handle()
async def handle_plugin(bot: Bot, event: MessageEvent):
    """AstrBot 插件分发。无插件安装时 dispatch 会立即返回，开销可忽略。"""
    fctx = _flow_root_for(event) if isinstance(event, GroupMessageEvent) else None
    plugin_span = _flow_span(fctx, "ingress.plugin")
    plugin_span.__enter__()
    try:
        from astrbot_compat.pipeline import dispatch

        logger.info(f"[plugin_debug] handle_plugin event={event.get_plaintext()!r} msg_id={event.message_id}")
        handled = await dispatch(event, bot)
        logger.info(f"[plugin_debug] dispatch handled={handled} msg_id={event.message_id}")
        if handled:
            _plugin_handled_msgs[_event_key(event)] = time.time()
            if len(_plugin_handled_msgs) > 256:
                _plugin_handled_msgs.popitem(last=False)
        plugin_span.__exit__(None, None, None)
        if handled:
            _flow_set_outcome(fctx, "plugin_handled")
    except Exception as e:
        plugin_span.__exit__(type(e), e, e.__traceback__)
        logger.warning(f"[plugin] dispatch 异常: {e}", exc_info=True)


# 对话入口：只有命中以上规则才会进入（priority=3、命中即 block）。
# 它 block=True，因此任何需要看到全部消息的处理器（如落库监听）都必须排在它之前。
chat_handler = on_message(rule=Rule(is_chat_trigger), priority=_PRIORITY_CHAT, block=True)


@chat_handler.handle()
async def handle_chat(bot: Bot, event: GroupMessageEvent):
    """@ 触发主流程：加群锁 → 按需总结 → 跑 Pipeline → 逐条发送回复。"""
    fctx = _flow_root_or_create(event, "qq_chat")
    if _event_key(event) in _plugin_handled_msgs:
        _plugin_handled_msgs.pop(_event_key(event), None)
        _flow_decision(fctx, "chat.plugin_shortcut", status="skipped",
                       reason_code="plugin_handled")
        _flow_set_outcome(fctx, "plugin_handled")
        logger.debug(f"[chat] 已由插件处理，跳过 LLM (group {event.group_id})")
        return
    lock = _group_locks[event.group_id]
    lock_span = _flow_span(fctx, "chat.group_lock")
    lock_span.__enter__()  # 覆盖「排队等待」；获取后立即闭合（计划 §6.3 A）
    async with lock:
        lock_span.__exit__(None, None, None)
        # 新的直接请求 = 显式取消信号（计划 §6.9 层 3）：推进话题版本，
        # 让仍在途/待发送的旧主动输出在发送前判为过期。
        with contextlib.suppress(Exception):
            get_participation_manager().bump_topic_revision(event.group_id)
        # 纯图片 @（无文字）时给 message 一个占位文本：它是检索查询与 prompt
        # 的当前输入，空串会让整轮对话退化成「没有当前输入」。
        message_text = event.get_plaintext().strip() or "[图片]"
        # cometa 可信 Origin（方案 §6.5/§6.4.1）：只在 @ 触达路径构造；
        # 委派决策在能力钩子里读它——这里不判断要不要委派，只提供身份事实。
        with _flow_span(fctx, "chat.context"):
            if _cometa_enabled():
                ctx_origin = cometa_bridge.build_origin(
                    event, bot, instance_id=_cometa_instance_id()
                )
            else:
                ctx_origin = None
            _reply_to_id, _mentioned = _extract_message_relations(event)
            ctx = ChatContext(
                user_id=event.user_id,
                group_id=event.group_id,
                msg_id=event.message_id,
                message=message_text,
                # v3 会话身份（计划 §6.1）：群轮次也带规范键，检索 scope 由
                # 服务端从这组字段生成
                conversation_kind="group",
                conversation_key=f"qq:{event.self_id}:group:{event.group_id}",
                bot_id=str(event.self_id),
                peer_id=str(event.group_id),
                storage_session_id=event.group_id,
                # v4 当前输入信封（多人身份修复计划 §6.2）：纠正解析/预算
                # parts 都从这里读关系，权威来自平台事件
                sender_display_name=normalize_display_name(
                    getattr(getattr(event, "sender", None), "card", "")
                    or getattr(getattr(event, "sender", None), "nickname", "")
                ),
                reply_to_msg_id=str(_reply_to_id or ""),
                reply_target_user_id=resolve_reply_target(
                    _reply_to_id or "",
                    event.group_id,
                    bot_id=str(event.self_id),
                    conversation_key=f"qq:{event.self_id}:group:{event.group_id}",
                ),
                mentioned_user_ids=tuple(_mentioned),
                relation_version=1,
                # 平台原始句柄：Comes 调插件工具时，工具 handler 内部会用 event.send() /
                # event.bot.call_action()，必须是真实对象。只有 @ 回复这条路径能提供它们
                # （主动发言没有对应的用户事件，那条路径上工具能力自然不可用）。
                raw_event=event,
                bot=bot,
                cometa_origin=ctx_origin,
                # 图片来源（本体 + 引用）；识图未启用时保持空列表，describe_images_hook
                # 会跳过，行为与旧版一致。
                image_sources=extract_image_sources(event) if vision_available() else [],
                # 身份绑定：与流程 root 共用 trace（计划 §6.2 入口绑定）
                trace_id=fctx.trace_id if fctx is not None else new_trace_id(),
            )
            try:
                from core.observability import message_flow

                message_flow.attach(ctx, fctx)
                # storage ID 幂等补充（修复计划 §6.1）：群轮次的可信存储键
                message_flow.update_trace_identity(
                    fctx, storage_session_id=ctx.storage_session_id)
            except Exception:
                pass
        with _flow_span(fctx, "chat.reply_gate"):
            gate = get_reply_gate().evaluate(
                event.group_id,
                trigger="reply",
                intent="",
            )
            ctx.gate_path = gate.path
            ctx.gate_score = gate.score
            ctx.gate_reasons = gate.reasons

        # 整条身份问句直复（多人身份修复计划 §6.3）：未命中时 ctx 不变
        _maybe_identity_direct_reply(ctx)

        # @ 触发对话时：若距上次总结已累积足够新消息，后台触发一次短期记忆总结，
        # 避免每次群消息都做无用总结，同时保证对话用到的短期记忆是最新的。
        # 这里用 force=True 强制总结（离线合并新消息到短期记忆），但因为是本地小批量，
        # 并不强制调用在线 LLM，避免影响响应速度。
        try:
            with _flow_span(fctx, "chat.consolidate_trigger"):
                consolidator = get_consolidator()
                new_count = consolidator.has_new_messages_to_consolidate(
                    event.group_id, threshold=CONSOLIDATION_TRIGGER_NEW_MESSAGES
                )
                if new_count > 0:
                    logger.info(f"🧠 [Trigger] @对话触发短期记忆总结（新消息 {new_count} 条）")
                    maybe_consolidate(
                        event.group_id, force=True,
                        parent_trace_id=fctx.trace_id if fctx is not None else "")
        except Exception as e:
            logger.warning(f"⚠️ @触发总结异常（跳过）: {e}")

        # 每日 token 预算：只有 pause_all 会拦到这里（默认 pause_memory 放行对话，
        # 上面那次整合触发本身也已按 CONSOLIDATION 角色单独判过）。
        # pause_all 的语义是「一分钱都别再花」，所以这里**静默不回**：
        # 不发提示句（那也要过一次 LLM 之外的发送链路，且撞破预算后每条 @ 都要发一句
        # 更吵）、也不回落到本地端点（回落会让「全停」名不副实，纯在线部署下更是无处可落）。
        # 走 NoneBot 的正常「不回复」返回路径，不抛异常。
        chat_blocked = budget_blocked(ROLE_CHAT)
        if chat_blocked:
            _flow_decision(fctx, "chat.daily_budget", status="blocked",
                           reason_code=str(chat_blocked))
            _flow_set_outcome(fctx, "budget_blocked")
            logger.warning(
                f"⚠️ [Budget] 群 {event.group_id} 的 @ 对话被预算拦下，静默不回（{chat_blocked}）"
            )
            return
        _flow_checkpoint(fctx, "chat.daily_budget", summary="allowed")

        # 跑完整 Pipeline（前钩子组装上下文 → LLM 生成 → 后钩子解析/过滤/分段/日志）
        try:
            with _flow_span(fctx, "chat.runtime"):
                ctx = await _run_turn_via_engine(f"qq:{event.group_id}", ctx)
        # FinishedException 应该被原样向上抛，避免把“已结束”当作异常处理
        except FinishedException:
            raise
        except RuntimeTurnError as e:
            # 取消不是失败（计划 §6.9 层 3）：绝不能落进通用兜底变成「......？」
            if e.code == E_CANCELLED:
                _flow_decision(fctx, "chat.runtime_result", status="cancelled",
                               reason_code="reset_cancelled")
                _flow_set_outcome(fctx, "cancelled")
                logger.info(f"🔇 [chat] 群 {event.group_id} 轮次已取消（reset），静默不发送")
                return
            raise
        except Exception as e:
            _flow_decision(fctx, "chat.runtime_result", status="failed",
                           reason_code="pipeline_error")
            logger.error(f"Pipeline 异常: {e}")
            # 兜底：异常时给用户一句温和的占位回复，避免冷场
            ctx.reply = "......？"
            ctx.lines = ["......？"]

        # Planner 决定等待更多消息（设计阶段五）：@ 是硬触发不会走到这里，
        # 该标记只可能出现在主动路径；防御性地早退，绝不能发「......？」占位。
        if getattr(ctx, "planner_wait", False):
            _flow_decision(fctx, "chat.runtime_result", status="skipped",
                           reason_code="planner_wait")
            _flow_set_outcome(fctx, "silent")
            logger.info(f"⏳ [Planner] 群 {event.group_id} 本轮不回复，等待更多消息")
            return

        # 防御：就算后钩子没产出任何行，也一定给一句兜底
        if not ctx.lines:
            ctx.lines = ["......？"]

        logger.success(f"✨ [即将发送给 QQ 的台词]: {' | '.join(ctx.lines)}")

        scope = ConversationScope.for_qq(event.group_id) if _social_delivery_enabled() else None

        async def _send_reply_segment(line: str, i: int) -> str | None:
            if i == 0:
                msg = Message([MessageSegment.reply(event.message_id), MessageSegment.text(line)])
            else:
                msg = Message(line)
            return await chat_handler.send(msg)

        with _flow_span(fctx, "send.prepare"):
            pass
        # cometa 受理确认（方案 §6.5）：委派接管的本轮只发 ack 一条，经桥接
        # 认领 ack 通知后发送；ack 交由普通回复链路会造成入口/泵双发或漏记。
        # 返回 pump_owned 表示后台泵已抢先接管发送——本轮静默结束（任务不受影响）。
        cometa_submission = getattr(ctx, "cometa_submission", None)
        if cometa_submission:
            with _flow_span(fctx, "send.cometa_ack") as ack_span:
                ack_outcome = await cometa_bridge.deliver_ack(
                    cometa_submission,
                    lambda line: _send_reply_segment(line, 0),
                )
                ack_span.finish(status="succeeded" if ack_outcome == "sent" else "unknown",
                                reason_code=ack_outcome)
            if ack_outcome == "sent":
                with contextlib.suppress(Exception):
                    await _record_bot_lines(
                        event.self_id, event.group_id, list(ctx.lines), origin=ctx
                    )
            elif ack_outcome == "unknown":
                logger.warning(
                    f"[Cometa] 群 {event.group_id} 的 ack 发送结果未知"
                    f"（任务 {cometa_submission.get('task_id', '')[:8]} 不受影响，"
                    "后续结果会带任务短 ID）"
                )
            _flow_set_outcome(fctx, "cometa_ack_" + str(ack_outcome))
            await chat_handler.finish()

        # 逐段发送并收集回执（计划 §6.1 发送改造）：只有**确认送达**的片段才
        # 计发言、写 BOT_SELF、进学习——发送失败不再被记成「说过」。原实现把
        # 最后一段交给 chat_handler.finish(msg)（抛 FinishedException、拿不到
        # 回执且无法补记账），现在全部用 send、finish 只结束流程。
        receipts = await deliver_lines(
            ctx.lines,
            scope=scope,
            trace_id=ctx.trace_id,
            turn_id=ctx.turn_id,
            send_one=_send_reply_segment,
            interval_seconds=SEND_INTERVAL,
        )
        delivered = delivered_texts(receipts)
        if delivered:
            with _flow_span(fctx, "reply.bookkeeping"):
                # 把确认送达的回复记入“已说过的话”，防止随后主动发言再重复刷屏
                with contextlib.suppress(Exception):
                    get_proactive().record_spoken(event.group_id, delivered)
                    # 评分层记账：被 @ 后的回复记为**被动**——被叫到后回答不应该
                    # 获得与主动插话同等级的惩罚（上游工程方案 §14）。
                    # 多段回复只更新一次发言占用，不按片段重复计数。
                    get_participation_manager().note_stella_spoke(event.group_id, "passive")

                # 表达与回复效果学习：效果只对照已发部分（partial 时后半段不存在）
                with _flow_span(fctx, "learning.open"):
                    expression_learning.on_reply_sent(
                        group_id=event.group_id,
                        group_shared_space=ctx.group_shared_space,
                        user_id=event.user_id,
                        message=ctx.message,
                        lines=delivered,
                        trigger="reply",
                        turn_id=ctx.turn_id,
                        trace_id=ctx.trace_id,
                        source_msg_id=event.message_id,
                    )

                # Bot 台词落库（source_kind=BOT_SELF）：只记确认送达的片段，给下一轮
                # 整合提供「我刚说过什么」的真实语境
                await _record_bot_lines(
                    event.self_id, event.group_id, delivered,
                    origin=ctx, receipts=receipts,
                )

                # 输出匹配（计划 §6.3.4）：注入的表达真的出现在已发文本 → applied=1，
                # 只有 applied 的表达才关联使用结果；未匹配保持 unknown
                with contextlib.suppress(Exception):
                    from memory import expression_selector

                    expression_selector.mark_applied(ctx.turn_id, delivered)
            ack_count = sum(1 for r in receipts if r.status == "acknowledged")
            _flow_set_outcome(
                fctx, "delivered" if ack_count == len(ctx.lines) else "partial")
        else:
            _flow_decision(fctx, "reply.no_delivery", status="failed",
                           reason_code="no_segment_delivered")
            _flow_set_outcome(fctx, "not_delivered")
            logger.warning(
                f"[Delivery] 群 {event.group_id} 全部片段未送达（turn={ctx.turn_id}），"
                "不记发言、不学习"
            )

        # 压缩放在回复之后：不阻塞本次回复，摘要从下一轮开始生效
        if ctx.tail_start_id:
            _flow_checkpoint(fctx, "reply.compact",
                             summary="schedule_compact spawned, not awaited")
            schedule_compact(event.group_id, ctx.tail_start_id,
                             parent_trace_id=fctx.trace_id if fctx is not None else "")

        # 所有片段已 send 完成，这里只结束本次处理流程（不再携带消息）
        await chat_handler.finish()


# ============================================================
# QQ 私聊入口（计划 §6.2）：普通消息即对话，无须 @
# ============================================================
# 允许策略独立于 ALLOWED_GROUPS（那是群开关）；灰度由 PRIVATE_CHAT_ENABLED /
# PRIVATE_CHAT_ALLOWLIST 控制。trigger 语义沿用 "reply"，来源标记 PRIVATE_DIRECT
# （schema15 合法来源，与 @ 同为直接对话证据）。

async def is_private_trigger(event: PrivateMessageEvent) -> bool:
    """私聊触发规则：开关开启、非自身回显、（可选）白名单内、非空文本。"""
    if not PRIVATE_CHAT_ENABLED:
        return False
    if event.user_id == event.self_id:
        return False
    if PRIVATE_CHAT_ALLOWLIST and event.user_id not in PRIVATE_CHAT_ALLOWLIST:
        return False
    if len(event.get_plaintext().strip()) > 0:
        return True
    # 纯图片私聊：与群口径一致——识图可用才算触发
    return vision_available() and bool(extract_image_sources(event))


private_chat_handler = on_message(
    rule=Rule(is_private_trigger), priority=_PRIORITY_CHAT, block=True
)


def _register_private_conversation(bot: Bot, event: PrivateMessageEvent):
    """可信入口的注册表登记（计划 §6.1）：私聊首次对话分配持久存储会话。"""
    from memory.conversation_registry import get_or_register_private

    conn = sqlite3.connect(DB_PATH)
    try:
        return get_or_register_private(conn, str(event.self_id), int(event.user_id))
    finally:
        conn.close()


@private_chat_handler.handle()
async def handle_private_chat(bot: Bot, event: PrivateMessageEvent):
    """私聊主流程（计划 §6.2）：会话锁 → 注册/落库 → Pipeline → 逐条发送。

    与群链路的差异是刻意的：私聊没有群提及/参与评分/主动发言目标，也不做
    群表达学习（deliver_lines scope=None，§6.8 第一版私聊不进群 social scope）；
    预算、能力路由、取消、回复整形、BOT_SELF、压缩全部照走。
    """
    fctx = _flow_root_or_create(event, "qq_chat")
    if _event_key(event) in _plugin_handled_msgs:
        _plugin_handled_msgs.pop(_event_key(event), None)
        _flow_decision(fctx, "chat.plugin_shortcut", status="skipped",
                       reason_code="plugin_handled")
        _flow_set_outcome(fctx, "plugin_handled")
        logger.debug(f"[chat] 私聊已由插件处理，跳过 LLM (user {event.user_id})")
        return
    bot_id = str(event.self_id)
    lock = _private_locks[f"qq:{bot_id}:private:{event.user_id}"]
    lock_span = _flow_span(fctx, "chat.conversation_lock")
    lock_span.__enter__()
    async with lock:
        lock_span.__exit__(None, None, None)
        with _flow_span(fctx, "chat.context"):
            # 会话注册（幂等，负整数存储 ID 在这里分配）
            ref = _register_private_conversation(bot, event)
            message_text = event.get_plaintext().strip() or "[图片]"
            if _cometa_enabled():
                ctx_origin = cometa_bridge.build_origin(
                    event, bot, instance_id=_cometa_instance_id()
                )
            else:
                ctx_origin = None
            # 私聊引用段极少见，防御性提取；解析不到 = unknown（不猜）
            _reply_to_id, _mentioned = _extract_message_relations(event)
            ctx = ChatContext(
                user_id=event.user_id,
                group_id=0,  # 私聊没有群号；存储/身份走以下字段（计划 §6.1）
                msg_id=event.message_id,
                message=message_text,
                source_kind="PRIVATE_DIRECT",
                group_shared_space=ref.memory_space,
                conversation_kind=ref.kind,
                conversation_key=ref.conversation_key,
                bot_id=bot_id,
                peer_id=ref.peer_id,
                storage_session_id=ref.storage_session_id,
                trigger="reply",
                # v4 当前输入信封（多人身份修复计划 §6.2）
                sender_display_name=normalize_display_name(
                    getattr(getattr(event, "sender", None), "nickname", "")
                ),
                reply_to_msg_id=str(_reply_to_id or ""),
                reply_target_user_id=resolve_reply_target(
                    _reply_to_id or "",
                    ref.storage_session_id,
                    bot_id=bot_id,
                    conversation_key=ref.conversation_key,
                ),
                mentioned_user_ids=tuple(_mentioned),
                relation_version=1,
                raw_event=event,
                bot=bot,
                cometa_origin=ctx_origin,
                image_sources=extract_image_sources(event) if vision_available() else [],
                trace_id=fctx.trace_id if fctx is not None else new_trace_id(),
            )
            try:
                from core.observability import message_flow

                message_flow.attach(ctx, fctx)
                # storage ID 幂等补充（修复计划 §6.1）：私聊真实存储 ID 是
                # 注册表负整数，preprocessor 阶段不查业务库，这里补可信值
                message_flow.update_trace_identity(
                    fctx, storage_session_id=ref.storage_session_id)
            except Exception:
                pass
        # 用户消息**先**持久化（source PRIVATE_DIRECT，锁内落库），再组上下文
        # ——锁覆盖「历史插入 ↔ 压缩」竞态（计划 §6.2）。
        with _flow_span(fctx, "chat.persist"):
            await record_message(ctx)
            # 身份声明 hook（多人身份修复计划 §6.3）：私聊同契约
            with contextlib.suppress(Exception):
                from memory.conversation_identity import process_message_identity

                process_message_identity(ctx)
        # 整条身份问句直复（多人身份修复计划 §6.3）
        _maybe_identity_direct_reply(ctx)
        try:
            with _flow_span(fctx, "chat.consolidate_trigger"):
                consolidator = get_consolidator()
                new_count = consolidator.has_new_messages_to_consolidate(
                    ref.storage_session_id, threshold=CONSOLIDATION_TRIGGER_NEW_MESSAGES
                )
                if new_count > 0:
                    logger.info(
                        f"🧠 [Trigger] 私聊 {ref.runtime_key} 触发短期记忆总结（新消息 {new_count} 条）"
                    )
                    maybe_consolidate(
                        ref.storage_session_id, force=True,
                        parent_trace_id=fctx.trace_id if fctx is not None else "",
                    )
        except Exception as e:
            logger.warning(f"⚠️ 私聊触发总结异常（跳过）: {e}")

        chat_blocked = budget_blocked(ROLE_CHAT)
        if chat_blocked:
            _flow_decision(fctx, "chat.daily_budget", status="blocked",
                           reason_code=str(chat_blocked))
            _flow_set_outcome(fctx, "budget_blocked")
            logger.warning(
                f"⚠️ [Budget] 私聊 {ref.runtime_key} 对话被预算拦下，静默不回（{chat_blocked}）"
            )
            return
        _flow_checkpoint(fctx, "chat.daily_budget", summary="allowed")

        try:
            with _flow_span(fctx, "chat.runtime"):
                ctx = await _run_turn_via_engine(ref.runtime_key, ctx)
        except FinishedException:
            raise
        except RuntimeTurnError as e:
            if e.code == E_CANCELLED:
                _flow_decision(fctx, "chat.runtime_result", status="cancelled",
                               reason_code="reset_cancelled")
                _flow_set_outcome(fctx, "cancelled")
                logger.info(f"🔇 [chat] 私聊 {ref.runtime_key} 轮次已取消（reset），静默不发送")
                return
            raise
        except Exception as e:
            _flow_decision(fctx, "chat.runtime_result", status="failed",
                           reason_code="pipeline_error")
            logger.error(f"Pipeline 异常: {e}")
            ctx.reply = "......？"
            ctx.lines = ["......？"]

        if getattr(ctx, "planner_wait", False):
            _flow_decision(fctx, "chat.runtime_result", status="skipped",
                           reason_code="planner_wait")
            _flow_set_outcome(fctx, "silent")
            logger.info(f"⏳ [Planner] 私聊 {ref.runtime_key} 本轮不回复，等待更多消息")
            return

        if not ctx.lines:
            ctx.lines = ["......？"]

        logger.success(f"✨ [即将发送给 QQ 的台词]: {' | '.join(ctx.lines)}")

        # 第一版私聊不进群 social scope（计划 §6.8）：scope=None 只记本地事实
        scope = None

        async def _send_reply_segment(line: str, i: int) -> str | None:
            # 私聊纯文本分条；reply 引用对私聊的兼容性未经真实 adapter 验证
            # （计划 §12 假设 4，M5 核验），先不构造引用段。
            return await private_chat_handler.send(Message(line))

        cometa_submission = getattr(ctx, "cometa_submission", None)
        if cometa_submission:
            with _flow_span(fctx, "send.cometa_ack") as ack_span:
                ack_outcome = await cometa_bridge.deliver_ack(
                    cometa_submission,
                    lambda line: _send_reply_segment(line, 0),
                )
                ack_span.finish(status="succeeded" if ack_outcome == "sent" else "unknown",
                                reason_code=ack_outcome)
            if ack_outcome == "sent":
                with contextlib.suppress(Exception):
                    await _record_bot_lines(
                        event.self_id, ref.storage_session_id, list(ctx.lines), origin=ctx
                    )
            elif ack_outcome == "unknown":
                logger.warning(
                    f"[Cometa] 私聊 {ref.runtime_key} 的 ack 发送结果未知"
                    f"（任务 {cometa_submission.get('task_id', '')[:8]} 不受影响）"
                )
            _flow_set_outcome(fctx, "cometa_ack_" + str(ack_outcome))
            await private_chat_handler.finish()

        receipts = await deliver_lines(
            ctx.lines,
            scope=scope,
            trace_id=ctx.trace_id,
            turn_id=ctx.turn_id,
            send_one=_send_reply_segment,
            interval_seconds=SEND_INTERVAL,
        )
        delivered = delivered_texts(receipts)
        if delivered:
            with _flow_span(fctx, "reply.bookkeeping"):
                # Bot 台词落库（BOT_SELF）：只记确认送达的片段（计划 §6.3）
                await _record_bot_lines(
                    event.self_id, ref.storage_session_id, delivered,
                    origin=ctx, receipts=receipts,
                )
            ack_count = sum(1 for r in receipts if r.status == "acknowledged")
            _flow_set_outcome(
                fctx, "delivered" if ack_count == len(ctx.lines) else "partial")
        else:
            _flow_decision(fctx, "reply.no_delivery", status="failed",
                           reason_code="no_segment_delivered")
            _flow_set_outcome(fctx, "not_delivered")
            logger.warning(
                f"[Delivery] 私聊 {ref.runtime_key} 全部片段未送达（turn={ctx.turn_id}）"
            )

        if ctx.tail_start_id:
            _flow_checkpoint(fctx, "reply.compact",
                             summary="schedule_compact spawned, not awaited")
            schedule_compact(ref.storage_session_id, ctx.tail_start_id,
                             parent_trace_id=fctx.trace_id if fctx is not None else "")

        await private_chat_handler.finish()


# ============================================================
# 个性化称呼（自然语言配置）
# ============================================================

def _message_segment_type(segment) -> str:
    return str(getattr(segment, "type", "") or (segment.get("type", "") if isinstance(segment, dict) else ""))


def _message_segment_data(segment) -> dict:
    data = getattr(segment, "data", None)
    if data is None and isinstance(segment, dict):
        data = segment.get("data")
    return data if isinstance(data, dict) else {}


def _addressing_target_ids(event: GroupMessageEvent) -> list[str]:
    """提取消息中除 Stella 外的明确 @ 目标，拒绝 ``@all``。"""
    targets: list[str] = []
    for segment in event.get_message():
        if _message_segment_type(segment) != "at":
            continue
        qq = str(_message_segment_data(segment).get("qq") or "").strip()
        if not qq or qq.lower() == "all" or qq == str(event.self_id):
            continue
        if qq not in targets:
            targets.append(qq)
    return targets


def _is_group_admin(event: GroupMessageEvent) -> bool:
    role = getattr(getattr(event, "sender", None), "role", "") or ""
    return event.user_id in PROACTIVE_TOGGLE_ADMINS or role in ("owner", "admin")


def _cache_addressing_decision(event: MessageEvent, result: AddressingRequest) -> None:
    # 决策缓存按完整 event key（计划 §6.2）：相同 msg_id 在不同 Bot/会话不可
    # 互相压掉。
    key = _event_key(event)
    _addressing_decisions[key] = result
    _addressing_decisions.move_to_end(key)
    while len(_addressing_decisions) > 256:
        _addressing_decisions.popitem(last=False)


async def is_addressing_command(event: MessageEvent) -> bool:
    """称呼请求规则：群内 @ Stella / 私聊普通消息，文本命中结构化意图。

    私聊分支（计划 §6.2）：没有 is_tome 语义（私聊必然是对 Bot 说），允许
    策略与私聊对话入口一致（PRIVATE_CHAT_ENABLED / ALLOWLIST）。
    """
    if not ADDRESSING_ENABLED:
        return False
    text = event.get_plaintext().strip()
    if isinstance(event, PrivateMessageEvent):
        if not PRIVATE_CHAT_ENABLED:
            return False
        if event.user_id == event.self_id:
            return False
        if PRIVATE_CHAT_ALLOWLIST and event.user_id not in PRIVATE_CHAT_ALLOWLIST:
            return False
    else:
        if event.group_id not in ALLOWED_GROUPS or not event.is_tome():
            return False
    if not is_likely_addressing_request(text):
        return False
    # reload 的插件名可以是任意字符串，命中它时保持现有重载优先级。
    from astrbot_compat.loader import parse_reload_command

    if parse_reload_command(text):
        return False
    # 定时任务指令整体让路：text=/cron= 的值可以是任意字符串（含称呼句式）
    from stella_project.plugins.bot_main.scheduling.commands import (
        is_scheduling_command,
    )

    if is_scheduling_command(text):
        return False
    result = await classify_addressing(text)
    _cache_addressing_decision(event, result)
    return result.operation != NOT_ADDRESS_REQUEST


addressing_handler = on_message(
    rule=Rule(is_addressing_command), priority=_PRIORITY_TOGGLE, block=True
)
_flow_watch_finish(addressing_handler)


def _assert_addressing_rule_disjoint() -> None:
    """启动期钉住称呼规则与既有 priority=1 规则的互斥边界。"""
    from astrbot_compat.loader import parse_reload_command

    samples = [
        *(f"{word}，称呼我为哥哥" for word in _MUTE_KEYWORDS + _UNMUTE_KEYWORDS),
        *(f"{word}，把称呼改成队长" for word in _MUTE_KEYWORDS + _UNMUTE_KEYWORDS),
    ]
    bad = [text for text in samples if not is_likely_addressing_request(text)]
    reload_like = [text for text in samples if parse_reload_command(text)]
    if bad or reload_like:
        logger.critical(
            "称呼 handler 与 priority=1 设置 handler 的互斥自检失败："
            f"addressing_prefilter={bad[:1]!r}, reload_overlap={reload_like[:1]!r}"
        )
        return
    logger.debug(f"✅ 称呼 handler 互斥自检通过（已验 {len(samples)} 组组合）")


def _addressing_clarification(result: AddressingRequest, target_ids: list[str]) -> str:
    if len(target_ids) > 1:
        return "你一次 @ 了多位用户，我不确定要修改谁，请一次只指定一位。"
    if result.operation in (SET_SELF_ADDRESS, SET_OTHER_ADDRESS) and not result.address_term:
        return "你希望我怎么称呼这位用户？请把称呼也告诉我。"
    if result.operation == SET_OTHER_ADDRESS and not target_ids:
        return "请 @ 你要修改称呼的那位用户，我不会猜测目标。"
    return "我还没听清你的称呼设置，请明确告诉我称呼谁、改成什么。"


async def _finish_addressing(bot: Bot, event: MessageEvent, reply: str) -> None:
    if isinstance(event, PrivateMessageEvent):
        # 私聊：回复落私聊存储（注册表分配的存储键），纯文本不构造群引用
        ref = _register_private_conversation(bot, event)
        await _record_bot_lines(int(bot.self_id), ref.storage_session_id, [reply])
        await addressing_handler.finish(Message(reply))
        return
    await _record_bot_lines(int(bot.self_id), event.group_id, [reply])
    await addressing_handler.finish(
        Message([MessageSegment.reply(event.message_id), MessageSegment.text(reply)])
    )


@addressing_handler.handle()
@_flow_command("command.addressing")
async def handle_addressing(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    """执行自然语言称呼配置；所有写入都经过 addressing 服务。

    私聊分支（计划 §6.2）：只能改**本人**在私聊空间的称呼——不调用群管理员
    检查，也没有 @ 目标可解析（不可伪造 @ 改他人记录）。第一版称呼仍按空间
    隔离（私聊空间内生效）；跨空间个人称呼是 M3 的个人事实层。
    """
    result = _addressing_decisions.pop(_event_key(event), None)
    if result is None:
        result = await classify_addressing(event.get_plaintext().strip())
    if result.operation == NOT_ADDRESS_REQUEST:
        return

    is_private = isinstance(event, PrivateMessageEvent)
    target_ids = [] if is_private else _addressing_target_ids(event)
    if result.needs_clarification or len(target_ids) > 1:
        await _finish_addressing(bot, event, _addressing_clarification(result, target_ids))
        return

    explicit_target = target_ids[0] if target_ids else None
    if explicit_target and result.operation == SET_SELF_ADDRESS:
        result = replace(result, operation=SET_OTHER_ADDRESS, target_user_id=explicit_target)
    target_user_id = explicit_target or str(event.user_id)

    if result.operation == SET_OTHER_ADDRESS and not explicit_target:
        await _finish_addressing(bot, event, _addressing_clarification(result, target_ids))
        return
    if is_private:
        # 私聊：不可伪造 @ 目标改他人记录；他人指名一律拒绝
        if result.operation == SET_OTHER_ADDRESS or target_user_id != str(event.user_id):
            await _finish_addressing(
                bot, event, "在私聊里我只能修改你自己的称呼；改别人的称呼请到对应群里操作。"
            )
            return
    elif target_user_id != str(event.user_id) and not _is_group_admin(event):
        logger.info(
            f"[Addressing] 群 {event.group_id} 用户 {event.user_id} 无权修改用户 {target_user_id}"
        )
        await _finish_addressing(bot, event, "我不能替你修改其他人的称呼，除非你是本群管理员。")
        return

    if is_private:
        ref = _register_private_conversation(bot, event)
        space = ref.memory_space
    else:
        space = resolve_space(event.group_id)
    try:
        if result.operation in (SET_SELF_ADDRESS, SET_OTHER_ADDRESS):
            preference = addressing.set_preference(
                space,
                target_user_id,
                result.address_term,
                source="natural_language",
                updated_by_user_id=event.user_id,
            )
            if target_user_id == str(event.user_id):
                reply = f"好，以后我叫你「{preference.address_term}」。"
            else:
                reply = f"好，以后我称呼用户 {target_user_id} 为「{preference.address_term}」。"
        elif result.operation == CLEAR_ADDRESS:
            addressing.clear_preference(space, target_user_id)
            reply = "好，我不再使用这个个性化称呼了。"
        elif result.operation == QUERY_ADDRESS:
            preference = addressing.get_preference(space, target_user_id)
            reply = (
                f"我现在称呼你「{preference.address_term}」。"
                if preference
                else "我还没有为你设置个性化称呼。"
            )
        else:
            return
    except ValueError as error:
        logger.info(f"[Addressing] 会话 {getattr(event, 'group_id', 0) or f'私聊 {event.user_id}'} 称呼输入被拒绝: {error}")
        reply = f"这个称呼我不能保存：{error}"
    except Exception as error:
        logger.warning(f"[Addressing] 会话 {getattr(event, 'group_id', 0) or f'私聊 {event.user_id}'} 处理失败: {error}")
        reply = "称呼设置暂时没保存成功，请稍后再试。"
    await _finish_addressing(bot, event, reply)


# ============================================================
# 运行时开关（管理员临时关闭/恢复主动发言）
# ============================================================

_MUTE_KEYWORDS = ("安静", "闭嘴", "别说话", "停止主动发言")
_UNMUTE_KEYWORDS = ("恢复", "醒醒", "可以说话", "开启主动发言")

_assert_addressing_rule_disjoint()


async def is_toggle_command(event: GroupMessageEvent) -> bool:
    """触发规则：已启用群 + @ 机器人 + 文本命中开关关键词。

    命中重载命令时**一律返回 False**：三个 handler 同优先级且都 ``block=True``，
    NoneBot 会一起跑，而「@Stella 重载插件 恢复计划」这种插件名会同时命中开关词。
    互斥判据只有一处（``parse_reload_command``），由 ``_assert_reload_rule_disjoint``
    在启动期钉住。
    """
    if not PROACTIVE_RUNTIME_TOGGLE_ENABLED:
        return False
    if event.group_id not in ALLOWED_GROUPS or not event.is_tome():
        return False
    text = event.get_plaintext().strip()
    from astrbot_compat.loader import parse_reload_command

    if parse_reload_command(text):
        return False
    # 定时任务指令优先于开关词（动词已避开开关词表，这里再机械挡一层：
    # 「定时停用 x」这类指令不允许被当成「安静」处理）
    from stella_project.plugins.bot_main.scheduling.commands import (
        is_scheduling_command,
    )

    if is_scheduling_command(text):
        return False
    if is_likely_addressing_request(text):
        return False
    return any(k in text for k in _MUTE_KEYWORDS + _UNMUTE_KEYWORDS)


# priority=1 必须高于 plugin_handler(priority=2) 与 chat_handler(priority=3, block=True)，
# 否则「安静」这类命令会被当成普通对话交给 LLM/插件
toggle_handler = on_message(rule=Rule(is_toggle_command), priority=_PRIORITY_TOGGLE, block=True)
_flow_watch_finish(toggle_handler)

# ── 监听器优先级不变量（启动期自检） ──
def _assert_listener_priorities() -> None:
    """校验落库监听器优先级最高；违反时输出 critical 日志（不中断启动）。"""
    for name, priority in (
        ("toggle_handler", _PRIORITY_TOGGLE),
        ("addressing_handler", _PRIORITY_TOGGLE),
        ("capability_handler", _PRIORITY_TOGGLE),
        ("reload_handler", _PRIORITY_TOGGLE),
        ("scheduling_handler", _PRIORITY_TOGGLE),
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
@_flow_command("command.toggle")
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
    if mute:
        # 静音 = 显式取消信号（计划 §6.9 层 3）：在途的旧主动输出发送前判过期
        with contextlib.suppress(Exception):
            get_participation_manager().bump_topic_revision(event.group_id)

    reply = "好，我不主动说话了，被 @ 还是会回的" if mute else "好，我继续正常参与聊天"
    await _record_bot_lines(int(bot.self_id), event.group_id, [reply])
    await toggle_handler.finish(
        Message([MessageSegment.reply(event.message_id), MessageSegment.text(reply)])
    )


# ============================================================
# 能力查询（群里问「你能做什么」）
# ============================================================

# 超过这个长度改发图：QQ 会把长文本折叠成「查看全文」，而这段清单的价值恰好
# 在于一眼扫完。渲染不可用时照旧发文本（见 _capability_image）。
_CAPABILITY_TEXT_TO_IMAGE = 320


async def is_capability_query(event: GroupMessageEvent) -> bool:
    """触发规则：已启用群 + @ 机器人 + 文本命中能力查询句式。

    与 ``is_toggle_command`` **同优先级且都 block=True**，而 NoneBot 会把同优先级的
    matcher 一起跑——一句「恢复一下，你能做什么」会同时命中两者，其中一个**会改群
    设置**。所以互斥必须是机械的：判据在 ``inventory.is_query_text``（命中任一开关词
    一律返回 False），启动期由 ``_assert_capability_rule_disjoint()`` 钉住。
    """
    if not CAPABILITY_QUERY_ENABLED:
        return False
    if event.group_id not in ALLOWED_GROUPS or not event.is_tome():
        return False
    from astrbot_compat.loader import parse_reload_command
    from capability.inventory import is_query_text

    text = event.get_plaintext()
    # 重载命令优先：插件名可以是任何字符串，包含查询句式也不奇怪
    if parse_reload_command(text):
        return False
    # 定时任务指令同理让路（text= 值可以是任意字符串）
    from stella_project.plugins.bot_main.scheduling.commands import (
        is_scheduling_command,
    )

    if is_scheduling_command(text):
        return False
    if is_likely_addressing_request(text):
        return False
    return is_query_text(
        text,
        toggle_keywords=_MUTE_KEYWORDS + _UNMUTE_KEYWORDS,
    )


capability_handler = on_message(
    rule=Rule(is_capability_query), priority=_PRIORITY_TOGGLE, block=True
)
_flow_watch_finish(capability_handler)


def _assert_capability_rule_disjoint() -> None:
    """启动期自检：开关命令绝不会同时被判成能力查询。

    两张词表「刚好不重叠」不是可验证的性质——往任一张表里加词的人不会去查另一张。
    这里穷举 4×2 组开关词与全部查询句式的拼接（52 组，import 期跑一次可忽略），
    命中即 critical：那意味着一句话会同时改群设置并回一份清单。
    """
    from capability.inventory import QUERY_KEYWORDS, is_query_text

    toggle = _MUTE_KEYWORDS + _UNMUTE_KEYWORDS
    bad = [
        f"{t}，{q}"
        for t in toggle
        for q in QUERY_KEYWORDS
        if is_query_text(f"{t}，{q}", toggle_keywords=toggle)
    ]
    if bad:
        logger.critical(
            f"❌ 能力查询与运行时开关的触发规则不互斥（{len(bad)} 组，例：{bad[0]}）："
            f"两者同为 priority={_PRIORITY_TOGGLE} 且 block=True，NoneBot 会一起跑，"
            f"于是同一句话既改群设置又回一份能力清单。"
            f"请检查 capability/inventory.py 的 is_query_text。"
        )
        return
    logger.debug(
        f"✅ 能力查询规则与运行时开关互斥"
        f"（已验 {len(toggle) * len(QUERY_KEYWORDS)} 组组合）"
    )


_assert_capability_rule_disjoint()


async def _capability_image(text: str) -> Path | None:
    """清单太长时转成图片。不需要转、或渲染不可用时返回 ``None``（调用方发纯文本）。

    ``render_text`` 在浏览器缺失 / 首次 270MB 还在后台下载 / 截图失败时返回 ``None``
    而不抛异常，所以这里只需处理 import 失败。清单再长也比一条发不出去的消息有用。
    """
    if len(text) <= _CAPABILITY_TEXT_TO_IMAGE:
        return None
    try:
        from astrbot_compat.render import render_text

        return await render_text(text)
    except Exception as e:
        logger.debug(f"[Capability] 清单转图不可用，退回纯文本: {e}")
        return None


@capability_handler.handle()
@_flow_command("command.capabilities")
async def handle_capability_query(bot: Bot, event: GroupMessageEvent):
    """回答「你能做什么」：直接读能力注册表拼文本，**不经模型**。

    不走 LLM 是刻意的：这个问题有确定答案，交给模型只会得到一段听起来合理、却与
    注册表实际状态无关的描述——而这个 surface 存在的全部意义就是让用户看到注册表里
    **真实有什么**（「插件装了、日志说派生成功了、可就是从来不被调用」正是它要回答
    的问题）。顺带的好处是零 token 开销，谁都可以随便问。

    权限分界（方案 §3.1）：来源层、provider 健康度、未声明工具的具体名单属排查信息，
    只给管理员（``PROACTIVE_TOGGLE_ADMINS`` 或群主/管理员）；普通群友看到可路由能力
    清单与未声明工具的**条数**——「让用户知道」是这条需求的全部意义，不该要权限。
    """
    role = getattr(getattr(event, "sender", None), "role", "") or ""
    admin = event.user_id in PROACTIVE_TOGGLE_ADMINS or role in ("owner", "admin")

    try:
        from capability.inventory import chat_overview

        reply = chat_overview(admin=admin)
    except Exception as e:
        logger.warning(f"[Capability] 能力清单生成失败: {e}")
        reply = "能力清单这会儿取不到，稍后再问我一次"
    logger.info(
        f"[Capability] 群 {event.group_id} 用户 {event.user_id} 查询能力清单"
        f"（admin={admin}，{len(reply)} 字）"
    )

    # 只把首行记进短期记忆：整段是清单，下一轮整合看到几十行工具名只会把它当群聊
    # 语境（_record_bot_lines 的用途是补「我刚说过什么」，不是存档我发过的正文）。
    head = next((ln for ln in reply.splitlines() if ln.strip()), "")
    await _record_bot_lines(int(bot.self_id), event.group_id, [head])

    image = await _capability_image(reply)
    body = MessageSegment.image(image) if image else MessageSegment.text(reply)
    await capability_handler.finish(
        Message([MessageSegment.reply(event.message_id), body])
    )


# ============================================================
# 插件热重载（管理员命令，默认关闭）
# ============================================================


# 参与评分打分表的重载命令短语（管理员 @ Bot 说这两句之一即热重载 TOML，
# 见实现方案 §4 补充要求 B：调参不改代码不重启）
_TABLES_RELOAD_PHRASES = ("重载打分表", "重载参与评分")


def _is_tables_reload(text: str) -> bool:
    t = (text or "").strip()
    return any(t == p or t.startswith(p) for p in _TABLES_RELOAD_PHRASES)


async def is_reload_command(event: GroupMessageEvent) -> bool:
    """触发规则：已启用群 + @ 机器人 + 文本是「重载插件 <名>」或「重载打分表」。

    权限**不在这里判**（与 ``toggle_handler`` 同一惯例）：规则只管命中，命中后由
    handler 判权限并静默忽略无权者。放在规则里的话，非管理员发这句会掉进 chat_handler
    交给 LLM，Stella 就会煞有介事地回一句「好的我重载了」——那比不响应糟得多。

    打分表重载不依赖 ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED：那是插件系统的开关，
    打分表属于核心决策层，且重载是纯数据替换（无 re-import 残留）。
    """
    if event.group_id not in ALLOWED_GROUPS or not event.is_tome():
        return False
    text = event.get_plaintext()
    if _is_tables_reload(text):
        return True
    if not ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED:
        return False
    from astrbot_compat.loader import parse_reload_command

    return parse_reload_command(text) is not None


reload_handler = on_message(
    rule=Rule(is_reload_command), priority=_PRIORITY_TOGGLE, block=True
)
_flow_watch_finish(reload_handler)


def _assert_reload_rule_disjoint() -> None:
    """启动期自检：重载命令与开关命令、能力查询三者互不误伤。

    三者同为 ``priority=1`` 且 ``block=True``，NoneBot 会把同优先级的 matcher 一起跑。
    互斥的实现方式是「另外两条规则一旦发现这是重载命令就返回 False」，所以整条链的
    正确性归结为一个可穷举的性质：``parse_reload_command`` 对这两类输入判得准。

    正向（插件名恰好是开关词或查询句式，插件名是**任意字符串**，这完全可能）：必须
    仍被解析成重载命令，否则「重载插件 恢复」会在重载的同时把主动发言打开。
    反向（一句纯粹的开关命令或能力查询）：绝不能被解析成重载命令，否则「安静」会被
    reload_handler 吃掉，开关彻底失灵。
    """
    from astrbot_compat.loader import RELOAD_KEYWORDS, parse_reload_command
    from capability.inventory import QUERY_KEYWORDS

    names = _MUTE_KEYWORDS + _UNMUTE_KEYWORDS + QUERY_KEYWORDS
    bad: list[str] = []
    checked = 0
    for phrase in RELOAD_KEYWORDS:
        for name in names:
            text = f"{phrase} {name}"
            checked += 1
            if parse_reload_command(text) != name:
                bad.append(f"{text!r} → {parse_reload_command(text)!r}（该解析成 {name!r}）")
    for name in names:
        checked += 1
        if parse_reload_command(name) is not None:
            bad.append(f"{name!r} 被误判成重载命令（会吃掉开关/查询）")
    if bad:
        logger.critical(
            f"❌ 热重载命令与开关/能力查询的触发规则不互斥（{len(bad)} 组，例：{bad[0]}）："
            f"三者同为 priority={_PRIORITY_TOGGLE} 且 block=True，NoneBot 会一起跑，"
            f"于是同一句话既重载插件又改群设置。"
            f"请检查 astrbot_compat/loader.py 的 parse_reload_command。"
        )
        return
    logger.debug(f"✅ 热重载命令规则与开关/能力查询互斥（已验 {checked} 组组合）")


_assert_reload_rule_disjoint()


@reload_handler.handle()
@_flow_command("command.reload")
async def handle_reload(bot: Bot, event: GroupMessageEvent):
    """管理员热重载单个插件。

    权限沿用 ``toggle_handler`` 那套（``PROACTIVE_TOGGLE_ADMINS`` 或群主/管理员）。
    选群内命令而不是给状态接口开一个 POST：那个端点是**只读**的，加一条能触发任意
    插件 re-import 的写入口是比只读端点大一档的安全步骤，为一个调试功能不值当。

    回复里必须带上 ``HOT_RELOAD_CAVEAT``：看到「重载成功」的人会假定进程状态与重启
    等价，而清不掉的那几类残留恰好都不报错。
    """
    from astrbot_compat.loader import (
        HOT_RELOAD_CAVEAT,
        get_failed_plugins,
        parse_reload_command,
        reload_plugin,
    )

    role = getattr(getattr(event, "sender", None), "role", "") or ""
    if event.user_id not in PROACTIVE_TOGGLE_ADMINS and role not in ("owner", "admin"):
        logger.info(f"[HotReload] 群 {event.group_id} 用户 {event.user_id} 无权重载插件")
        return

    # 打分表热重载分支：纯数据替换，成功/失败都直接回一句
    if _is_tables_reload(event.get_plaintext()):
        ok, msg = get_participation_manager().reload_tables()
        reply = f"✅ {msg}" if ok else f"❌ {msg}（沿用旧表，看 config/participation/*.toml）"
        await _record_bot_lines(int(bot.self_id), event.group_id, [reply])
        await reload_handler.finish(
            Message([MessageSegment.reply(event.message_id), MessageSegment.text(reply)])
        )

    name = parse_reload_command(event.get_plaintext()) or ""
    logger.info(f"[HotReload] 群 {event.group_id} 用户 {event.user_id} 请求重载插件 {name!r}")
    try:
        md = await reload_plugin(name)
    except Exception as e:
        logger.exception(f"[HotReload] 重载 {name!r} 异常: {e}")
        md = None
        reason = repr(e)
    else:
        reason = get_failed_plugins().get(name, "")

    if md is None:
        detail = f"：{reason}" if reason else "。看 logs/boot_debug.log 里的失败原因"
        reply = f"重载 {name} 失败{detail}"
    else:
        reply = (
            f"已重载 {md.root_dir_name}（{md.name} v{md.version}）。{HOT_RELOAD_CAVEAT}"
        )

    await _record_bot_lines(int(bot.self_id), event.group_id, [reply])
    await reload_handler.finish(
        Message([MessageSegment.reply(event.message_id), MessageSegment.text(reply)])
    )


# ============================================================
# 定时任务（用户可管理的 Cron / Agent）——见 scheduling/ 包与 docs/scheduling.md
# ============================================================
# 与开关/称呼/能力查询/重载同优先级（priority=1, block=True）。规则互斥是两向
# 机械保证的：那四个分类器先让路给 parse_scheduling_command（见各自函数里的
# scheduling 分支），本规则再让路给 parse_reload_command（插件名是任意字符串，
# 必须保持最高优先）。互斥由 _assert_scheduling_rule_disjoint 在导入期钉住。

_scheduling_runtime = None
_scheduling_service = None


async def is_scheduling_command_rule(event: GroupMessageEvent) -> bool:
    """定时任务指令规则：功能已启用 + 已启用群 + @ + 命中「定时*」指令。"""
    from config import SCHEDULING_ENABLED

    if not SCHEDULING_ENABLED:
        return False
    if event.group_id not in ALLOWED_GROUPS or not event.is_tome():
        return False
    from astrbot_compat.loader import parse_reload_command
    from stella_project.plugins.bot_main.scheduling.commands import (
        is_scheduling_command,
    )

    text = event.get_plaintext().strip()
    if parse_reload_command(text):
        return False
    return is_scheduling_command(text)


scheduling_handler = on_message(
    rule=Rule(is_scheduling_command_rule), priority=_PRIORITY_TOGGLE, block=True
)
_flow_watch_finish(scheduling_handler)


def _assert_scheduling_rule_disjoint() -> None:
    """导入期自检：调度指令与既有 priority=1 规则（开关/能力查询/重载）互斥。"""
    from astrbot_compat.loader import parse_reload_command
    from capability.inventory import QUERY_KEYWORDS, is_query_text
    from stella_project.plugins.bot_main.scheduling.commands import (
        is_scheduling_command,
    )

    samples = [
        "定时添加 0 9 * * MON Asia/Shanghai 站会啦",
        "定时智能 0 6 * * * UTC+8 总结群聊",
        "定时列表",
        "定时停用 abc123",
        "定时启用 abc123",
        "定时立即 abc123",
    ]
    toggle = _MUTE_KEYWORDS + _UNMUTE_KEYWORDS
    bad: list[str] = []
    for text in samples:
        if not is_scheduling_command(text):
            bad.append(f"解析失效 {text!r}")
            continue
        if any(k in text for k in toggle):
            bad.append(f"与开关词重叠 {text!r}")
        if is_query_text(text, toggle_keywords=toggle):
            bad.append(f"与能力查询重叠 {text!r}")
        if parse_reload_command(text):
            bad.append(f"与重载命令重叠 {text!r}")
    # 反向：开关/查询句式绝不能被判成调度指令
    for text in [*toggle, *QUERY_KEYWORDS]:
        if is_scheduling_command(text):
            bad.append(f"误吞既有命令 {text!r}")
    if bad:
        logger.critical(
            f"❌ 定时任务规则与 priority=1 既有规则互斥自检失败：{bad[:2]}——"
            "scheduling/commands.py 的动词表被改坏了吗？"
        )
        return
    logger.debug("✅ 定时任务规则互斥自检通过")


_assert_scheduling_rule_disjoint()


def _scheduling_short_id(task_id: str) -> str:
    return task_id[:8]


def _scheduling_local_time(dt_utc, tz_name: str) -> str:
    from stella_project.plugins.bot_main.scheduling.cron import resolve_timezone

    try:
        return dt_utc.astimezone(resolve_timezone(tz_name)).strftime("%m-%d %H:%M")
    except Exception:
        return dt_utc.strftime("%m-%d %H:%M UTC")


_SCHEDULING_STATE_LABELS = {
    "queued": "排队中",
    "claimed": "已认领",
    "running": "运行中",
    "ready": "待发送",
    "sending": "发送中",
    "sent": "已发送",
    "silent": "静默完成",
    "failed": "失败",
    "skipped": "已跳过",
    "cancelled": "已取消",
    "delivery_unknown": "投递未知",
}


def _format_scheduling_task(task) -> str:
    icon = {"active": "▶", "paused": "⏸", "cancelled": "✖"}.get(task.status.value, "·")
    head = f"{icon} {_scheduling_short_id(task.task_id)} {task.cron_expr} @{task.timezone}"
    if task.mode.value == "agent":
        head += " [Agent]"
    if task.status.value == "active" and task.next_run_utc is not None:
        head += f"，下次 {_scheduling_local_time(task.next_run_utc, task.timezone)}"
    objective = (
        task.objective if len(task.objective) <= 24 else task.objective[:24] + "…"
    )
    return f"{head}\n    {objective}"


def _format_scheduling_run(run, tz_name: str) -> str:
    label = _SCHEDULING_STATE_LABELS.get(run.state.value, run.state.value)
    when = (
        _scheduling_local_time(run.scheduled_for_utc, tz_name)
        if run.scheduled_for_utc is not None
        else "手动"
    )
    line = f"· {when} {label}"
    if run.error:
        line += f"（{run.error[:40]}）"
    elif run.state.value == "delivery_unknown" and run.delivery_error:
        line += f"（{run.delivery_error[:40]}）"
    return line


def _dispatch_scheduling_command(event: GroupMessageEvent, cmd) -> str:
    """指令分派：service 承担校验/权限/审计，这里只做取参与拼回复。"""
    from stella_project.plugins.bot_main.scheduling.commands import format_help

    assert _scheduling_service is not None
    service = _scheduling_service
    group_id = event.group_id
    actor_id = event.user_id
    is_admin = _is_group_admin(event)
    action = cmd.action

    if action == "help":
        return format_help()

    if action == "list":
        tasks = service.list_tasks(group_id=group_id)
        if not tasks:
            return "这个群还没有定时任务。发「定时添加」看看格式。"
        return "\n".join(_format_scheduling_task(t) for t in tasks)

    if action in ("add", "add_agent"):
        if cmd.fields.get("malformed"):
            return (
                "格式：定时添加 <cron> <时区> <内容>\n"
                "例：定时添加 0 9 * * MON-FRI Asia/Shanghai 站会啦\n"
                "cron 是 5 字段（分 时 日 月 周），星期用 MON-SUN。"
            )
        task = service.create_task(
            actor_id=actor_id,
            group_id=group_id,
            bot_id=str(event.self_id),
            is_group_admin=is_admin,
            mode="reminder" if action == "add" else "agent",
            objective=cmd.objective,
            cron_expr=cmd.cron_expr,
            timezone=cmd.timezone,
        )
        next_at = (
            _scheduling_local_time(task.next_run_utc, task.timezone)
            if task.next_run_utc is not None
            else "待定"
        )
        return f"✅ 已创建任务 {_scheduling_short_id(task.task_id)}，下次触发 {next_at}"

    if action == "show":
        task = service.show_task(
            actor_id=actor_id, group_id=group_id, task_id_prefix=cmd.task_id,
            is_group_admin=is_admin,
        )
        detail = _format_scheduling_task(task)
        if task.policy.get("tools"):
            detail += f"\n    工具：{', '.join(task.policy['tools'])}"
        detail += f"\n    补跑策略：{task.policy.get('coalesce', 'latest')}"
        return detail

    if action == "edit":
        fields = cmd.fields
        if fields.get("malformed"):
            return "格式：定时编辑 <id> cron=… tz=… text=… notify=always|on_content [rev=N]"
        updates: dict = {}
        if fields.get("cron"):
            updates["cron_expr"] = fields["cron"]
        if fields.get("tz"):
            updates["timezone"] = fields["tz"]
        if fields.get("text"):
            updates["objective"] = fields["text"]
        if fields.get("notify"):
            updates["notification_mode"] = fields["notify"]
        if not updates:
            return "没有要修改的字段。可用键：cron= tz= text= notify= rev="
        task = service.show_task(
            actor_id=actor_id, group_id=group_id, task_id_prefix=cmd.task_id,
            is_group_admin=is_admin,
        )
        updated = service.edit_task(
            actor_id=actor_id, group_id=group_id, task_id_prefix=cmd.task_id,
            expected_revision=cmd.expected_revision or task.revision,
            is_group_admin=is_admin, **updates,
        )
        return f"✅ 已更新 {_scheduling_short_id(updated.task_id)}（修订 r{updated.revision}）"

    if action in ("pause", "resume", "cancel"):
        task = service.show_task(
            actor_id=actor_id, group_id=group_id, task_id_prefix=cmd.task_id,
            is_group_admin=is_admin,
        )
        setter = {"pause": service.pause, "resume": service.resume, "cancel": service.cancel}[action]
        updated = setter(
            actor_id=actor_id, group_id=group_id, task_id_prefix=cmd.task_id,
            expected_revision=cmd.expected_revision or task.revision,
            is_group_admin=is_admin,
        )
        verb = {"pause": "已暂停", "resume": "已恢复", "cancel": "已取消"}[action]
        return f"✅ 任务 {_scheduling_short_id(updated.task_id)} {verb}"

    if action == "run_now":
        run = service.run_now(
            actor_id=actor_id, group_id=group_id, task_id_prefix=cmd.task_id,
            is_group_admin=is_admin,
        )
        return f"✅ 已提交立即运行（{_scheduling_short_id(run.run_id)}），稍后执行。"

    if action == "history":
        runs = service.history(
            actor_id=actor_id, group_id=group_id, task_id_prefix=cmd.task_id,
            is_group_admin=is_admin, limit=8,
        )
        if not runs:
            return "这个任务还没有运行记录。"
        task = service.show_task(
            actor_id=actor_id, group_id=group_id, task_id_prefix=cmd.task_id,
            is_group_admin=is_admin,
        )
        return "\n".join(_format_scheduling_run(r, task.timezone) for r in runs)

    if action in ("allow_tool", "deny_tool"):
        if not cmd.tool_name:
            return "格式：定时允许 <id> <工具名>（管理员）"
        task = service.show_task(
            actor_id=actor_id, group_id=group_id, task_id_prefix=cmd.task_id,
            is_group_admin=is_admin,
        )
        tools = list(task.policy.get("tools") or [])
        if action == "allow_tool":
            if cmd.tool_name in tools:
                return f"工具 {cmd.tool_name} 已在允许清单里。"
            tools.append(cmd.tool_name)
            verb = "已允许"
        else:
            if cmd.tool_name not in tools:
                return f"工具 {cmd.tool_name} 不在允许清单里。"
            tools.remove(cmd.tool_name)
            verb = "已禁止"
        updated = service.set_policy(
            actor_id=actor_id, group_id=group_id, task_id_prefix=cmd.task_id,
            expected_revision=task.revision, is_group_admin=is_admin,
            policy={"tools": tools, "coalesce": task.policy.get("coalesce")},
        )
        listing = ", ".join(updated.policy.get("tools") or []) or "（空）"
        return f"✅ {verb} {cmd.tool_name}。当前清单：{listing}"

    return format_help()


@scheduling_handler.handle()
@_flow_command("command.scheduling")
async def handle_scheduling(bot: Bot, event: GroupMessageEvent):
    """定时任务指令入口：解析 → service（权限/审计在 service 内）→ 回帖。

    回帖原则：service 抛的都是用户可读错误（直接转述）；其余异常统一降级为
    一句「没成功」——细节进日志，不暴露内部信息。
    """
    from stella_project.plugins.bot_main.scheduling.commands import (
        parse_scheduling_command,
    )
    from stella_project.plugins.bot_main.scheduling.cron import CronError
    from stella_project.plugins.bot_main.scheduling.service import (
        SchedulingServiceError,
    )

    cmd = parse_scheduling_command(event.get_plaintext().strip())
    if cmd is None:
        return
    if _scheduling_service is None:
        reply = "定时任务功能没有启用（SCHEDULING_ENABLED）。"
    else:
        try:
            reply = _dispatch_scheduling_command(event, cmd)
        except SchedulingServiceError as e:
            reply = str(e)
        except CronError as e:
            reply = f"时间表达式有问题：{e}"
        except Exception as e:
            logger.warning(f"[Scheduling] 群 {event.group_id} 指令处理失败: {e}")
            reply = "这个操作没成功，请稍后再试。"
    await _record_bot_lines(int(bot.self_id), event.group_id, [reply])
    await scheduling_handler.finish(
        Message([MessageSegment.reply(event.message_id), MessageSegment.text(reply)])
    )


# ── 调度 worker 的进程内装配（provider / 工具 / 发送边界） ──

async def _scheduling_provider_resolver() -> Any | None:
    """解析当前活跃的对话 provider（与 COMES _agent_call 同一来源）。"""
    try:
        from astrbot_compat.llm.manager import get_provider_manager

        return get_provider_manager().provider
    except Exception as e:
        logger.debug(f"[Scheduling] provider 解析失败: {e}")
        return None


async def _scheduling_tool_resolver(name: str):
    """按**显式名字**解析工具；只认 MCP kind——astrbot 工具能触达任意插件/
    事件路径，v1 一律不进调度允许清单（计划 §6.6）。"""
    from capability.providers import provider_runtime
    from capability.registry import KIND_MCP
    from capability.registry import registry as capability_registry

    capability_id = capability_registry.claimed_by(name)
    if not capability_id:
        return None
    for provider in capability_registry.find_providers(capability_id):
        if provider.tool_name != name or provider.kind != KIND_MCP:
            continue
        if not provider_runtime.is_live(provider):
            return None
        return provider_runtime.resolve(provider)
    return None


async def _scheduling_sender(group_id: int, text: str) -> str | None:
    """平台发送边界：返回回执（message_id）或 None（拿不到就不声称可靠）。"""
    from nonebot import get_bot

    bot = get_bot()
    resp = await bot.send_group_msg(group_id=group_id, message=text)
    receipt = resp.get("message_id") if isinstance(resp, dict) else getattr(resp, "message_id", None)
    return str(receipt) if receipt is not None else None


def _build_scheduling_stack():
    """按配置装配 store / service / agent / delivery / runtime。"""
    from config import (
        INSTANCE_ID,
        SCHEDULING_CONTEXT_MAX_CHARS,
        SCHEDULING_DAILY_GROUP_RUN_CAP,
        SCHEDULING_DB_PATH,
        SCHEDULING_GLOBAL_ADMINS,
        SCHEDULING_MAX_TASKS_PER_GROUP,
        SCHEDULING_MAX_TASKS_PER_USER,
        SCHEDULING_SEND_TIMEOUT,
        SCHEDULING_TICK_INTERVAL,
        SCHEDULING_WORKER_LEASE_TTL,
    )
    from stella_project.plugins.bot_main.scheduling.agent import ScheduledAgentRunner
    from stella_project.plugins.bot_main.scheduling.delivery import DeliveryService
    from stella_project.plugins.bot_main.scheduling.runtime import SchedulerRuntime
    from stella_project.plugins.bot_main.scheduling.service import (
        SchedulingLimits,
        SchedulingService,
    )
    from stella_project.plugins.bot_main.scheduling.store import TaskStore

    store = TaskStore(SCHEDULING_DB_PATH)
    limits = SchedulingLimits(
        max_tasks_per_group=max(SCHEDULING_MAX_TASKS_PER_GROUP, 1),
        max_tasks_per_user=max(SCHEDULING_MAX_TASKS_PER_USER, 1),
        daily_group_run_cap=max(SCHEDULING_DAILY_GROUP_RUN_CAP, 0),
        global_admin_ids=frozenset(SCHEDULING_GLOBAL_ADMINS),
    )
    service = SchedulingService(store, limits=limits)
    runner = ScheduledAgentRunner(
        provider_resolver=_scheduling_provider_resolver,
        tool_resolver=_scheduling_tool_resolver,
    )
    delivery = DeliveryService(
        store, sender=_scheduling_sender, send_timeout_seconds=SCHEDULING_SEND_TIMEOUT
    )
    runtime = SchedulerRuntime(
        store=store,
        delivery=delivery,
        agent_runner=runner,
        group_locks=_group_locks,
        worker_id=f"instance-{INSTANCE_ID}",
        lease_ttl_seconds=SCHEDULING_WORKER_LEASE_TTL,
        tick_interval_seconds=SCHEDULING_TICK_INTERVAL,
        daily_group_run_cap=SCHEDULING_DAILY_GROUP_RUN_CAP,
        context_max_chars=SCHEDULING_CONTEXT_MAX_CHARS,
        stop_grace_seconds=SHUTDOWN_GRACE_SECONDS,
    )
    return runtime, service


@get_driver().on_startup
async def _start_scheduling() -> None:
    """启动调度 worker；迁移失败/初始化异常只停用本功能，绝不拖垮主进程。"""
    from config import SCHEDULING_ENABLED

    global _scheduling_runtime, _scheduling_service
    if not SCHEDULING_ENABLED:
        return
    try:
        _scheduling_runtime, _scheduling_service = _build_scheduling_stack()
    except Exception as e:
        logger.error(f"❌ [Scheduling] 初始化失败（含迁移检查），调度功能停用: {e}")
        _scheduling_runtime = None
        _scheduling_service = None
        return
    await _scheduling_runtime.start()


# ============================================================
# Cometa 外部 Agent 任务运行层（design_docs/Cometa 外部 Agent 任务运行层
# 实施方案 v1.0 §6.8/§3.1）：装配模式与调度栈一致——初始化失败只停用本功能。
# ============================================================

_cometa_runtime_instance = None


def _cometa_enabled() -> bool:
    """入口处的快速门（避免每条 @ 消息都 import cometa）。"""
    try:
        from config import COMETA_ENABLED

        return bool(COMETA_ENABLED)
    except Exception:
        return False


def _cometa_instance_id() -> str:
    try:
        from config import INSTANCE_ID

        return str(INSTANCE_ID)
    except Exception:
        return ""


@get_driver().on_startup
async def _start_cometa() -> None:
    """装配 cometa runtime：泵 + worker 子进程 + 服务登记。

    失败（TOML 非法/迁移失败）只停用 cometa，绝不拖垮主进程；
    COMETA_ENABLED=false 时零动作（现有聊天行为逐字节不变）。
    """
    global _cometa_runtime_instance
    if not _cometa_enabled():
        return
    try:
        from cometa import runtime as cometa_runtime

        config = cometa_runtime.CometaConfig.load()
        if not config.enabled:
            return
        runtime = cometa_runtime.build_runtime(
            config,
            # 长结果投递工厂：绑定产物目录与 [delivery] 样式（§6.12 文件主投递）
            sender=cometa_bridge.make_notification_sender(
                config.artifacts_dir, config.delivery
            ),
            instance_id=_cometa_instance_id(),
            spawn_worker=True,
        )
        await runtime.start(spawn_worker=True)
        cometa_runtime.set_current(runtime)
        _cometa_runtime_instance = runtime
        logger.info("✅ [Cometa] 外部 Agent 任务层已装配（worker 子进程已启动）")
    except Exception as e:
        logger.error(f"❌ [Cometa] 初始化失败，cometa 停用: {e}")
        _cometa_runtime_instance = None


async def _stop_cometa() -> None:
    """受控关闭（§6.8）：泵先停，worker 子进程有界等待（未停的交恢复矩阵）。"""
    global _cometa_runtime_instance
    if _cometa_runtime_instance is None:
        return
    with contextlib.suppress(Exception):
        from cometa import runtime as cometa_runtime

        await _cometa_runtime_instance.stop(grace_seconds=10.0)
        cometa_runtime.set_current(None)
    _cometa_runtime_instance = None


async def _watch_plugin_sources() -> None:
    """监视已加载插件的源码 mtime，变了就重载一遍。

    只在 ``ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED`` 与 ``..._WATCH`` **都**为真时挂上。
    首轮只建立基线不重载：进程刚起来时磁盘上的 mtime 必然「比上一次记录的新」，
    不建基线的话每次启动都会白重载一遍全部插件。
    """
    from astrbot_compat.loader import plugin_source_stamps, reload_plugin

    stamps = plugin_source_stamps()
    logger.info(f"👀 [HotReload] 已开始监视 {len(stamps)} 个插件目录的改动（调试模式）")
    while True:
        try:
            await asyncio.sleep(ASTRBOT_PLUGIN_HOT_RELOAD_WATCH_INTERVAL)
            current = plugin_source_stamps()
            for dir_name, stamp in current.items():
                previous = stamps.get(dir_name)
                if previous is None or stamp <= previous:
                    continue
                logger.info(f"👀 [HotReload] 检测到 {dir_name} 源码变动，自动重载")
                await reload_plugin(dir_name)
            # 重载会换掉 md，重新取一次快照而不是把 current 直接当基线：
            # 重载本身可能改动目录（生成 __pycache__ 之外的东西），基线要认重载后的状态
            stamps = plugin_source_stamps()
        except asyncio.CancelledError:
            return
        except Exception:
            # watcher 自己挂了而静默，比不监视更糟：那时用户以为改完存盘就生效了
            logger.exception("[HotReload] 监视循环异常，继续监视")


_hot_reload_watcher: asyncio.Task | None = None

if ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED and ASTRBOT_PLUGIN_HOT_RELOAD_WATCH:

    @get_driver().on_startup
    async def _start_hot_reload_watcher() -> None:
        # 插件与能力装配都挂在 on_startup 上，这里排在它们之后拿到的才是完整清单
        global _hot_reload_watcher
        _hot_reload_watcher = asyncio.create_task(_watch_plugin_sources())


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


async def _record_bot_lines(
    self_id: int,
    group_id: int,
    lines: list[str],
    *,
    origin: "ChatContext | None" = None,
    receipts: list | None = None,
) -> None:
    """把 Bot 自己发出的台词写入 group_messages（source_kind=BOT_SELF）。

    目的：让下一轮整合能看到「我问了什么」，否则用户回答「对」「是的」时
    整合模型缺少语境，只能放弃或自行编造。BOT_SELF 只作上下文，
    consolidator 已保证它不进候选发送者白名单。

    v16（多人身份修复计划 §6.2）：``origin``（本轮可信 ctx）与 ``receipts``
    （deliver_lines 确认回执，keyword-only）给定时，每个确认气泡落自身的
    平台 message ID 与信封关系：同一次回复共享 logical_message_id/turn_id、
    递增 part_index、相同 origin_msg_id 与 reply_recipient_user_id——历史
    作者是 BOT_SELF，**回复对象不是作者**。receipt 缺平台 ID 时仍记录已确认
    的逻辑关系（msg_id 保持未知）；failed/unknown 不写。origin 为 None 时
    保持旧行为（无关系列值），兼容旧调用。
    """
    # 确认气泡序列：有 receipts 时只记 acknowledged 段（按原始 part_index），
    # 否则退回调用方给的 lines（旧调用方：cometa ack / WebChat 等已确认路径）。
    segments: list[tuple[int, str, str]] = []  # (part_index, text, platform_id)
    if receipts:
        for r in receipts:
            status = str(getattr(r, "status", "") or "")
            if status != "acknowledged":
                continue
            text = str(getattr(r, "text", "") or "").strip()
            segments.append(
                (
                    int(getattr(r, "part_index", 0) or 0),
                    text,
                    str(getattr(r, "platform_message_id", "") or ""),
                )
            )
        segments.sort(key=lambda s: s[0])
    else:
        segments = [(i, (line or "").strip(), "") for i, line in enumerate(lines)]

    logical_id = ""
    turn_id = ""
    origin_msg_id = ""
    recipient = ""
    if origin is not None:
        turn_id = str(getattr(origin, "turn_id", "") or "")
        trace_id = str(getattr(origin, "trace_id", "") or "")
        # 逻辑单元 ID：turn_id 优先，trace 兜底，再兜底局部 UUID——同一次
        # 调用内的全部气泡必须共享同一个 ID（没有 turn 追踪的入口也能归组）
        logical_id = turn_id or trace_id or uuid.uuid4().hex
        origin_msg_id = str(getattr(origin, "msg_id", 0) or 0)
        origin_msg_id = str(origin_msg_id) if origin_msg_id not in ("", "0") else ""
        # 收件人 = 本轮回复针对的用户（@ 触发即 sender；proactive_at 即目标）；
        # 群级主动（user_id=0）无个人收件人，保持空
        recipient = str(getattr(origin, "user_id", 0) or 0)
        recipient = recipient if recipient not in ("", "0") else ""
        if str(getattr(origin, "bot_id", "")) == str(self_id) and origin.group_id != group_id:
            # origin 与落库会话不一致（防御）：宁缺勿错
            origin_msg_id = ""

    for part_index, text, platform_id in segments:
        # 纯标点/单字兜底行（如 "......？"）无信息量，只会占用上下文尾巴窗口
        if len(text) < 2 or not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in text):
            continue
        try:
            await record_message(
                ChatContext(
                    user_id=self_id,
                    group_id=group_id,
                    msg_id=int(platform_id) if platform_id.isdigit() else 0,
                    message=text,
                    source_kind="BOT_SELF",
                    conversation_kind=getattr(origin, "conversation_kind", "") or "",
                    conversation_key=getattr(origin, "conversation_key", "") or "",
                    bot_id=str(self_id),
                    logical_message_id=logical_id,
                    part_index=part_index,
                    origin_msg_id=origin_msg_id,
                    reply_recipient_user_id=recipient,
                    turn_id=turn_id,
                    relation_version=1 if logical_id else 0,
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

    判定标准：在 PROACTIVE_REPLY_WINDOW_SECONDS 内该用户是否**对 Bot 说过话**
    （@ / 回复 Bot 的消息 / 昵称呼叫，即 OneBot 的 to_me）。用内存中的时间戳，不查库。

    此前判的是「窗口内有没有说话」，在活跃群里几乎恒为真：被追问的人本来就是
    「近期活跃用户」，随后必然还会在群里说话，于是 consecutive_no_reply 一直被
    清零、PROACTIVE_MAX_NO_REPLY 的自动退避形同虚设（bug_report_2026_8_31#1 §5.1）。

    代价是纯文本接话（不 @、不回复）会被判为未回应。这类漏判由 reset_no_reply
    在下一次「对 Bot 说话」时归零来兜底，不会把人永久踢出验证池。

    无回应即累计 consecutive_no_reply，达到 PROACTIVE_MAX_NO_REPLY 后
    can_at_user 会拒绝继续追问该用户，这是对「不想聊的人」的自动退避。
    """
    try:
        await asyncio.sleep(PROACTIVE_REPLY_WINDOW_SECONDS)
        last = get_proactive().last_tome_ts(group_id, user_id)
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


async def _proactive_at_user(bot: Bot, group_id: int, *, flow_ctx=None) -> bool:
    """尝试主动 @ 一位活跃用户以获取/验证记忆；返回是否已发言。

    与话题插话互斥：本函数返回 True 时调用方不再尝试话题插话，
    同一轮只做一件事，避免连续两次发言。

    流程：选目标（配额/冷却/退避过滤）→ 生成指令 → 跑 Pipeline →
    发送（带 @ 段）→ 记账（发出即计数）→ 起延迟任务检测回应。

    流程观测（计划 §6.4）：``flow_ctx`` 缺省时自建 ``proactive_at`` 独立
    root（避免只在生成开始后才有 trace）；定时任务传入其 timer root 时
    复用之开子 span，不另建 root。
    """
    own_root = flow_ctx is None
    caller_flow_ctx = flow_ctx
    if own_root:
        try:
            from core.observability import message_flow

            flow_ctx = message_flow.begin_trace(
                root_kind="proactive_at", platform="qq",
                scope=f"qq:{group_id}", origin="spawn",
                source_message_key=f"proactive_at:{group_id}:{new_trace_id()[:8]}",
            )
        except Exception:
            flow_ctx = None

        def _at_end(outcome: str) -> None:
            try:
                from core.observability import message_flow

                if flow_ctx is not None and not flow_ctx.ended:
                    message_flow.end_trace(flow_ctx, outcome=outcome)
            except Exception:
                pass
    else:
        def _at_end(outcome: str) -> None:
            return None

    outcome = ""
    try:
        allowed, reason = can_speak(group_id, "at")
        if not allowed:
            # 门控拒绝也有可查询原因（计划 §6.4）
            _flow_decision(flow_ctx, "proactive.at.preflight", status="blocked",
                           reason_code=f"can_speak:{reason}",
                           instance_key=f"grp:{group_id}")
            logger.debug(f"[主动@] 群 {group_id} 跳过：{reason}")
            outcome = "gate_blocked"
            return False
        proactive = get_proactive()

        # 排除 Bot 自身，避免自问自答
        try:
            self_id = int(bot.self_id)
        except (TypeError, ValueError):
            self_id = 0
        # 选人观测只在调用方显式传入 ctx 时下发（计划 §6.2 显式传递）；
        # 调用方未传时保持原调用形状——自建 root 记录网关级决策，
        # 逐用户/候选事实由 pick_target 的直接调用方按需传递。
        if caller_flow_ctx is not None:
            target = pick_target(group_id, exclude_user_ids={self_id, 0},
                                 flow_ctx=flow_ctx,
                                 instance_key=f"grp:{group_id}")
        else:
            target = pick_target(group_id, exclude_user_ids={self_id, 0})
        if target is None:
            # 无候选 = noop 有原因：逐项原因已由 pick_target 落
            # at.preflight/at.select（计划 §6.4）
            outcome = "no_candidate"
            return False

        target.nickname = await _resolve_nickname(bot, group_id, target.user_id)
        logger.info(
            f"🎯 [主动@] 群 {group_id} 选定用户 {target.user_id}"
            f"（{target.nickname}）：{target.reason}"
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
                # v3 会话身份（计划 §6.1）：主体是 pick_target 验证过的目标
                # uid（ctx.user_id）；不补会话身份字段的话 scope_for_chat_context
                # 会按旧入口处理，目标的 USER_SHARED 个人事实永远进不来
                # （多人身份修复计划 §6.1/T18）。
                conversation_kind="group",
                conversation_key=f"qq:{bot.self_id}:group:{group_id}",
                bot_id=str(bot.self_id),
                peer_id=str(group_id),
                storage_session_id=group_id,
                trace_id=new_trace_id(),
            )
            try:
                ctx = await _run_turn_via_engine(f"qq:{group_id}", ctx)
            except RuntimeTurnError as e:
                # 取消（reset/新直接请求抢占）：无发送、无记账，不落通用异常兜底
                if e.code == E_CANCELLED:
                    logger.info(f"🔇 [主动@] 群 {group_id} 轮次已取消，静默退出")
                    _flow_decision(flow_ctx, "proactive.turn", status="cancelled",
                                   reason_code="turn_cancelled",
                                   instance_key=f"grp:{group_id}")
                    outcome = "cancelled"
                    return False
                raise
            except Exception as e:
                logger.error(f"主动 @ Pipeline 异常: {e}")
                _flow_decision(flow_ctx, "proactive.turn", status="failed",
                               reason_code="pipeline_error",
                               instance_key=f"grp:{group_id}")
                outcome = "turn_error"
                return False

            if not ctx.lines:
                _flow_decision(flow_ctx, "proactive.filter", status="skipped",
                               reason_code="empty_output",
                               instance_key=f"grp:{group_id}")
                outcome = "empty_output"
                return False

            if is_proactive_skip(ctx.lines):
                proactive.mark_proactive_skip(
                    group_id,
                    target.user_id,
                    target.skip_subject,
                )
                _flow_decision(flow_ctx, "proactive.filter", status="skipped",
                               reason_code="naturalness_skip",
                               instance_key=f"grp:{group_id}")
                logger.info(
                    f"⏭️ [主动@] 群 {group_id} 用户 {target.user_id} "
                    f"当前没有自然承接，跳过发送与记账（subject={target.skip_subject}）"
                )
                outcome = "naturalness_skip"
                return False

            # 主动 @ 只发一句：追问必须简短，多行会像连续质询
            line = _join_lines_naturally(ctx.lines) if len(ctx.lines) > 1 else ctx.lines[0].strip()
            if not line:
                _flow_decision(flow_ctx, "proactive.filter", status="skipped",
                               reason_code="empty_joined_line",
                               instance_key=f"grp:{group_id}")
                outcome = "empty_output"
                return False

            if proactive.recently_spoken(group_id, [line]):
                _flow_decision(flow_ctx, "proactive.filter", status="skipped",
                               reason_code="duplicate_output",
                               instance_key=f"grp:{group_id}")
                logger.info(f"🛑 [主动@] 群 {group_id} 与已发言内容重复，跳过")
                outcome = "duplicate_output"
                return False

            # 逐段发送 + 回执收集（计划 §6.1）：发送确认之后才记账。原实现先记账
            # 后发送，发送失败时配额/发言占用/学习全被白白消耗。
            scope = ConversationScope.for_qq(group_id) if _social_delivery_enabled() else None

            async def _send_at_segment(seg_line: str, _i: int) -> str | None:
                message = Message([
                    MessageSegment.at(target.user_id),
                    MessageSegment.text(" " + seg_line),
                ])
                return await bot.send_group_msg(group_id=group_id, message=message)

            receipts = await deliver_lines(
                [line],
                scope=scope,
                trace_id=ctx.trace_id,
                turn_id=ctx.turn_id,
                send_one=_send_at_segment,
            )
            delivered = delivered_texts(receipts)
            if not delivered:
                logger.error(f"[主动@] 群 {group_id} 发送失败，不记账不学习")
                _flow_decision(flow_ctx, "proactive.send", status="failed",
                               reason_code="no_segment_delivered",
                               instance_key=f"grp:{group_id}")
                outcome = "not_delivered"
                return False

            # 只对确认送达的段记账（计划 §6.4）：记账事实随 span 可查
            with _flow_span(flow_ctx, "proactive.after",
                            instance_key=f"grp:{group_id}"):
                _flow_checkpoint(flow_ctx, "proactive.after",
                                 summary="acknowledged-only bookkeeping",
                                 metrics={"delivered_segments": len(delivered),
                                          "total_segments": len(receipts)})
                proactive.mark_spoke(group_id)
                proactive.record_spoken(group_id, delivered)
                # 评分层记账：主动 @ 同样算主动发言（上游 §14 的区分只针对被动应答）
                with contextlib.suppress(Exception):
                    get_participation_manager().note_stella_spoke(group_id, "proactive")
                _flow_checkpoint(flow_ctx, "proactive.after",
                                 summary="note_stella_spoke(proactive)")
                # 回复效果学习（设计阶段六）：目标是「主动 @ 是否被回应/忽略」；
                # message 传空——build_instruction 的罐头指令不是用户的表达素材。
                expression_learning.on_reply_sent(
                    group_id=group_id,
                    group_shared_space=ctx.group_shared_space,
                    user_id=target.user_id,
                    message="",
                    lines=delivered,
                    trigger="proactive",
                    turn_id=ctx.turn_id,
                    trace_id=ctx.trace_id,
                    intent="proactive_at",
                )
                logger.success(f"✨ [主动@] 群 {group_id} → {target.user_id}: {delivered[0]}")

                await _record_bot_lines(
                    self_id, group_id, delivered, origin=ctx, receipts=receipts
                )

                # 主动 @ 同样推进对话：回复后异步触发压缩（不阻塞本次发言）
                if ctx.tail_start_id:
                    schedule_compact(group_id, ctx.tail_start_id)
                    _flow_checkpoint(flow_ctx, "proactive.after",
                                     summary="compact spawned, not awaited")

        # 发出即计数（不论是否获得回应），否则无回应的追问不占配额，
        # 会导致对同一个人连续搭话
        record_at(
            group_id,
            target.user_id,
            candidate_id=target.candidate_id,
        )

        # 起后台任务检测回应；登记到集合防止被 GC 回收
        task = asyncio.create_task(
            _check_reply_later(group_id, target.user_id, time.monotonic())
        )
        _reply_check_tasks.add(task)
        task.add_done_callback(_reply_check_tasks.discard)
        outcome = "delivered"
        return True
    finally:
        _at_end(outcome or "closed")


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

    # 播报日期按用户作息时区去重：时区配置不同时，「今天」的边界跟睡眠窗口一致
    today = user_now().date().isoformat()
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


# 参与评分层各 mode 对应的指令文案（写清楚「为什么现在轮到你说话」，上游 §20）。
# 这是 prompt 文案不是分值——分值/阈值都在 config/participation/*.toml。
_PARTICIPATION_INSTRUCTIONS: dict[str, str] = {
    "TOPIC_INTEREST": (
        "（群里正在聊一个你感兴趣的话题，没有人在@你。"
        "你想自然地插一句加入讨论，说一句相关的话。）"
    ),
    "SOCIAL_HOOK": (
        "（有群友说了句带悬念的话，像在等人接茬，没有人在@你。"
        "你想自然地接一句，比如好奇地追问。）"
    ),
    "CONTINUE_EXISTING_CONVERSATION": (
        "（你刚刚参与了这段对话，群友还在继续聊。"
        "你想自然地接一句，把话说完就好，不要开启新话题。）"
    ),
    "DIRECT_RELEVANCE": (
        "（有群友在对话中提到了你、明显是在向你搭话，虽然没有@你。"
        "你想自然地回应一句。）"
    ),
}
_PARTICIPATION_DEFAULT_INSTRUCTION = (
    "（群聊里没有人在@你，但你想自然地插一句话，和大家随便聊聊。请说一句自然的话。）"
)


def _build_participation_evidence(decision, trigger_text: str, snapshot: dict | None) -> dict:
    """把一次本地决策压缩成生成器可读的承接证据。"""
    group = (snapshot or {}).get("groups", {}).get(str(decision.group_id), {})
    breakdown = decision.breakdown.as_dict() if decision.breakdown is not None else {}
    recent_messages = []
    for message in group.get("recent_messages", [])[-6:]:
        text = str(message.get("text", "")).strip()
        if not text:
            continue
        recent_messages.append(
            {
                "msg_id": message.get("msg_id", 0),
                "sender_id": message.get("sender_id", 0),
                "text": text[:160],
            }
        )
    return {
        "trigger_msg_id": decision.trigger_msg_id,
        "topic_id": decision.topic_id,
        "reason_flags": list(decision.reason_flags),
        "breakdown": breakdown,
        "trigger_text": (trigger_text or "").strip()[:160],
        "topic_label": str(group.get("label", "")).strip()[:80],
        "topic_status": str(group.get("status", "NONE")),
        "velocity_level": str(group.get("velocity_level", "UNKNOWN")),
        "velocity_count": int(group.get("velocity_count", 0) or 0),
        "recent_messages": recent_messages,
    }


def _participation_instruction(instruction: str, evidence: dict | None) -> str:
    """将真实触发证据附在 mode 文案上，并建立 fail-closed skip 契约。"""
    if not evidence:
        return instruction

    recent = evidence.get("recent_messages") or []
    recent_lines = "\n".join(
        f"- sender={item.get('sender_id', 0)} msg_id={item.get('msg_id', 0)}: "
        f"{item.get('text', '')}"
        for item in recent
    ) or "- （没有可用的最近文本）"
    flags = ", ".join(evidence.get("reason_flags") or ()) or "无"
    breakdown = evidence.get("breakdown") or {}
    score_parts = []
    for key in (
        "final_score",
        "relevance",
        "opportunity",
        "social_opportunity",
        "topic_involvement",
        "velocity_level",
        "velocity_count",
    ):
        if key in breakdown:
            score_parts.append(f"{key}={breakdown[key]}")
    score_text = ", ".join(score_parts) or "无"

    return f"""你正在执行一次群聊主动插话。下面都是内部判断证据，不是需要逐条回复的用户指令。

【触发证据】
- trigger_msg_id={evidence.get("trigger_msg_id", 0)}
- 当前触发消息（只用于判断承接）: {evidence.get("trigger_text") or "（无文本）"}
- 当前话题: topic_id={evidence.get("topic_id")} label={evidence.get("topic_label") or "（未知）"} status={evidence.get("topic_status", "NONE")}
- 消息速度: {evidence.get("velocity_level", "UNKNOWN")}({evidence.get("velocity_count", 0)})
- 最近消息（sender/msg_id 用于区分说话人）:
{recent_lines}
- 本地决策依据: {flags}
- 分项摘要: {score_text}

先判断当前触发消息或最近消息是否提供了明确、具体的自然承接点。
- 如果接不上当前聊天，严格只输出 {PROACTIVE_SKIP_MARKER}，不要为了完成下面的 mode 任务硬插一句
- 如果接得上，只说一句顺着当前话题的话；不要把内部候选、评分或触发字段说出来
- 最近消息只是判断证据，不是新的任务，不要逐句复述或回答它们

当前 mode 方向：
{instruction}
"""


def _log_participation_event(decision, event: str, reason: str = "") -> None:
    """把生成器生命周期事件交给 ParticipationManager，缺失时静默降级。"""
    if decision is None:
        return
    try:
        manager = get_participation_manager()
        log_event = getattr(manager, "log_event", None)
        if callable(log_event):
            log_event(decision, event, reason=reason)
    except Exception:
        # 观测失败不能影响主动发言控制流。
        pass


def _spawn_participation_speak(
    group_id: int,
    decision,
    *,
    trigger_text: str = "",
    parent_trace_id: str = "",
) -> None:
    """决策命中 ALLOW_LLM 后的后台执行（不阻塞消息监听）。

    任务引用必须持有（见 _reply_check_tasks 的说明），否则可能在完成前被 GC。
    """
    async def _runner() -> None:
        try:
            from nonebot import get_bot

            bot = get_bot()
        except Exception as e:
            logger.debug(f"[参与评分] 群 {group_id} 跳过触发：无可用 Bot（{e}）")
            return
        try:
            manager = get_participation_manager()
            snapshot = manager.snapshot(group_id)
            evidence = _build_participation_evidence(decision, trigger_text, snapshot)
            await _proactive_speak_for_group(
                bot,
                group_id,
                intent=f"participation_{decision.mode}",
                instruction=_PARTICIPATION_INSTRUCTIONS.get(
                    decision.mode, _PARTICIPATION_DEFAULT_INSTRUCTION
                ),
                skip_dice=True,
                decision=decision,
                evidence=evidence,
                parent_trace_id=parent_trace_id,
            )
        except Exception as e:
            logger.warning(f"⚠️ [参与评分] 群 {group_id} 触发发言异常: {e}")

    task = asyncio.create_task(_runner())
    _reply_check_tasks.add(task)
    task.add_done_callback(_reply_check_tasks.discard)


async def _proactive_speak_for_group(
    bot: Bot,
    group_id: int,
    *,
    intent: str = "proactive_join",
    instruction: str | None = None,
    skip_dice: bool = False,
    decision=None,
    evidence: dict | None = None,
    parent_trace_id: str = "",
):
    """对单个群尝试主动发言：命中时生成一句自然的话并发送。

    流程观测（计划 §6.2）：主动发言是**独立 root**（不是触发消息的子
    span），与触发它的消息 trace 通过 ``caused_by`` 关联（§3.2）。
    """
    fctx = None
    try:
        from core.observability import message_flow

        fctx = message_flow.begin_trace(
            root_kind="proactive", platform="qq", scope=f"qq:{group_id}",
            source_message_key=f"proactive:{group_id}:{new_trace_id()[:8]}",
        )
        if parent_trace_id:
            message_flow.link(parent_trace_id, fctx.trace_id,
                              kind="caused_by", evidence="participation_allow")
    except Exception:
        fctx = None
    try:
        await _proactive_speak_impl(
            bot, group_id, intent=intent, instruction=instruction,
            skip_dice=skip_dice, decision=decision, evidence=evidence, fctx=fctx,
        )
    except Exception:
        _flow_set_outcome(fctx, "error")
        raise
    finally:
        try:
            from core.observability import message_flow

            if fctx is not None and not fctx.ended:
                message_flow.end_trace(fctx, outcome=fctx.outcome or "closed")
        except Exception:
            pass


async def _proactive_speak_impl(
    bot: Bot,
    group_id: int,
    *,
    intent: str = "proactive_join",
    instruction: str | None = None,
    skip_dice: bool = False,
    decision=None,
    evidence: dict | None = None,
    fctx=None,
):
    """主动发言主体（原 ``_proactive_speak_for_group`` 逻辑，行为不变）。

    :param bot: OneBot Bot 实例（用于组群发消息）
    :param group_id: 目标群号
    :param intent: 写入 ChatContext 的诊断意图（proactive_join=定时掷骰；
        participation_<mode>=评分层命中，上游 §20）
    :param instruction: 喂给 Pipeline 的指令文案（None = 默认罐头指令）
    :param skip_dice: 跳过概率掷骰（评分层已做完决策，再掷骰等于双重门槛）
    :return: None；命中时发送若干条群消息并记录“已发言”
    """
    # 先判断该群是否到了“可以主动发言”的时机（统一闸门判定）
    allowed, reason = can_speak(group_id, "join")
    if not allowed:
        _flow_decision(fctx, "proactive.preflight", status="blocked",
                       reason_code=f"can_speak:{reason}")
        logger.debug(f"[主动发言] 群 {group_id} 跳过：{reason}")
        return
    proactive = get_proactive()
    # gate 通过后再掷概率骰：概率是话题插话独有的（主动 @ 由配额与冷却约束，不掷骰）
    if not skip_dice and not proactive.should_speak(group_id):
        _flow_decision(fctx, "proactive.preflight", status="skipped",
                       reason_code="dice_skip")
        return
    # 同样要抢占本群的互斥锁：主动发言不能和 @ 回复并发，避免上下文被互相污染
    lock = _group_locks[group_id]
    async with lock:
        # 必须在群锁内判断：多个后台触发可能同时排队，锁外判断会让它们
        # 一起通过 cooldown，随后连续启动多次主动回复。
        gate = get_reply_gate().evaluate(
            group_id,
            trigger="proactive",
            intent=intent,
        )
        if not gate.allowed:
            _flow_decision(fctx, "proactive.preflight", status="blocked",
                           reason_code="reply_gate")
            logger.info(
                f"[ReplyGate] 群 {group_id} 跳过主动发言："
                f"{', '.join(gate.reasons)}"
            )
            return
        get_reply_gate().start(group_id, proactive=True)
        # 主动发言前先确保短期记忆已更新（force 本地小批量，不打扰在线 LLM）
        try:
            consolidator = get_consolidator()
            new_count = consolidator.has_new_messages_to_consolidate(
                group_id, threshold=CONSOLIDATION_TRIGGER_NEW_MESSAGES
            )
            if new_count > 0:
                logger.info(f"🧠 [Proactive] 主动发言前触发短期记忆总结（新消息 {new_count} 条）")
                _flow_checkpoint(fctx, "proactive.consolidate",
                                 summary="spawned, sleep 1s, not awaiting success")
                maybe_consolidate(group_id, force=True, parent_trace_id=getattr(fctx, "trace_id", ""))
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.warning(f"⚠️ 主动发言前总结异常（跳过）: {e}")

        # 构造一次"主动插话"的对话上下文
        # 注意 user_id=0、trigger='proactive'：让 Pipeline 认为自己是被邀请插话，而不是 @ 回复
        ctx = ChatContext(
            user_id=0,
            group_id=group_id,
            msg_id=0,
            message=_participation_instruction(
                instruction or _PARTICIPATION_DEFAULT_INSTRUCTION,
                evidence,
            ),
            trigger="proactive",
            intent=intent,
            gate_path=gate.path,
            gate_score=gate.score,
            gate_reasons=gate.reasons,
            trace_id=fctx.trace_id if fctx is not None else new_trace_id(),
        )
        try:
            from core.observability import message_flow

            message_flow.attach(ctx, fctx)
        except Exception:
            pass
        # 话题版本快照（计划 §6.9 层 3）：生成前捕获，发送前与逐段发送中比对
        try:
            rev_before = get_participation_manager().topic_revision(group_id)
        except Exception:
            rev_before = 0

        def _stale() -> bool:
            try:
                return get_participation_manager().topic_revision(group_id) != rev_before
            except Exception:
                return False

        try:
            with _flow_span(fctx, "proactive.turn"):
                ctx = await _run_turn_via_engine(f"qq:{group_id}", ctx)
        except RuntimeTurnError as e:
            # 取消（reset/新直接请求抢占）：无发送、无兜底、无记账
            if e.code == E_CANCELLED:
                _flow_set_outcome(fctx, "cancelled")
                _log_participation_event(decision, "generation_skip", "cancelled")
                logger.info(f"🔇 [主动发言] 群 {group_id} 轮次已取消，静默退出")
                return
            raise
        except Exception as e:
            _flow_set_outcome(fctx, "turn_error")
            logger.error(f"主动发言 Pipeline 异常: {e}")
            _log_participation_event(decision, "generation_skip", "pipeline_error")
            return
        finally:
            # Planner 判定 WAIT 时让本群停在 WAITING 而不是 IDLE（设计阶段五）：
            # 「在等更多消息」与「没在说话」是两种状态，后续 observe 可据此区分。
            get_reply_gate().finish(group_id, waiting=bool(getattr(ctx, "planner_wait", False)))
        if not ctx.lines:
            _flow_decision(fctx, "proactive.filter", status="skipped",
                           reason_code="empty_output")
            _log_participation_event(decision, "generation_skip", "empty_output")
            return

        # 发送前过期检查：生成期间出现转题/撤销/静音/新直接请求 → 丢弃旧输出
        if _stale():
            _flow_decision(fctx, "proactive.filter", status="skipped",
                           reason_code="stale_output")
            _log_participation_event(decision, "generation_skip", "stale_output")
            logger.info(f"[主动发言] 群 {group_id} 输出已过期（话题版本变化），丢弃不发")
            return

        if is_proactive_skip(ctx.lines):
            _flow_decision(fctx, "proactive.filter", status="skipped",
                           reason_code="naturalness_skip")
            _log_participation_event(decision, "generation_skip", "naturalness_skip")
            logger.info(
                f"⏭️ [主动发言] 群 {group_id} 当前没有自然承接，"
                "跳过发送与主动发言记账"
            )
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
            # 行合并后的空输出也是一次过滤器退出（计划 §6.4：每次退出有原因）
            _flow_decision(fctx, "proactive.filter", status="skipped",
                           reason_code="empty_after_merge")
            return

        # 防刷屏：与最近一次主动/回复高度相似时，本次主动发言直接放弃
        if get_proactive().recently_spoken(group_id, ctx.lines):
            _flow_decision(fctx, "proactive.filter", status="skipped",
                           reason_code="duplicate_output")
            _log_participation_event(decision, "generation_skip", "duplicate_output")
            logger.info(f"🛑 [主动发言] 群 {group_id} 与已发言内容重复，跳过")
            return

        # 逐段发送 + 回执收集（计划 §6.1）：确认送达后才记账。原实现先记账后
        # 发送，发送失败已被记成「说过」并进入学习——正是计划 §2 优先修复项。
        scope = ConversationScope.for_qq(group_id) if _social_delivery_enabled() else None

        async def _send_proactive_segment(seg_line: str, _i: int) -> str | None:
            return await bot.send_group_msg(group_id=group_id, message=seg_line)

        receipts = await deliver_lines(
            ctx.lines,
            scope=scope,
            trace_id=ctx.trace_id,
            turn_id=ctx.turn_id,
            send_one=_send_proactive_segment,
            interval_seconds=SEND_INTERVAL,
            abort_check=_stale,
        )
        delivered = delivered_texts(receipts)
        if not delivered:
            _flow_set_outcome(fctx, "not_delivered")
            _log_participation_event(decision, "send_failed", "no_segment_delivered")
            logger.error(f"[主动发言] 群 {group_id} 全部片段发送失败（不记账不学习）")
            return

        _flow_set_outcome(fctx, "delivered")
        # 发送后动作（计划 §6.4：不用空 span 冒充——记账/学习/记录/压缩
        # 都真实发生在确认送达之后，proactive.after span 包住它们）
        with _flow_span(fctx, "proactive.after"):
            # 只对 acknowledged 段记账（计划 §6.1/§6.4）：delivered 是发送
            # 确认后的片段，未确认段不进入任何记账/学习
            _flow_checkpoint(fctx, "proactive.after",
                             summary="acknowledged-only bookkeeping",
                             metrics={"delivered_segments": len(delivered),
                                      "total_segments": len(receipts)})
            # 通知频率跟踪“本群已发言”，避免连续多次主动插话打扰
            proactive.mark_spoke(group_id)
            get_proactive().record_spoken(group_id, delivered)
            # 评分层记账：主动插话（累积 RecentSpeechPenalty / RepetitionPenalty），
            # 一次逻辑发言只更新一次，不按片段重复计数；文本进 novelty 比对语料
            with contextlib.suppress(Exception):
                get_participation_manager().note_stella_spoke(
                    group_id, "proactive", text=delivered[0]
                )
            _flow_checkpoint(fctx, "proactive.after",
                             summary="note_stella_spoke(proactive)")
            # 回复效果学习（设计阶段六）：群级记录「主动插话是否被接话」；
            # user_id=0 表示全群目标，效果结算按群归因（不再作为过滤条件）。
            expression_learning.on_reply_sent(
                group_id=group_id,
                group_shared_space=ctx.group_shared_space,
                user_id=0,
                message="",
                lines=delivered,
                trigger="proactive",
                turn_id=ctx.turn_id,
                trace_id=ctx.trace_id,
                intent=intent,
            )
            logger.success(f"✨ [主动发言] 群 {group_id}: {' | '.join(delivered)}")
            # 群级主动（user_id=0）：origin 给出但无个人收件人——
            # _record_bot_lines 内部把收件人与源消息留空（unknown），不猜目标
            await _record_bot_lines(
                int(bot.self_id), group_id, delivered, origin=ctx, receipts=receipts
            )

            # 主动发言同样推进对话：回复后异步触发压缩（不阻塞本次发言）
            if ctx.tail_start_id:
                schedule_compact(
                    group_id, ctx.tail_start_id,
                    parent_trace_id=fctx.trace_id if fctx is not None else "")
                _flow_checkpoint(fctx, "proactive.after",
                                 summary="compact spawned, not awaited")

            _log_participation_event(
                decision, "sent", aggregate_delivery_status([r.status for r in receipts])
            )


# 定时主动发言：每 PROACTIVE_CHECK_INTERVAL 秒检查一次所有启用群
if scheduler is not None and PROACTIVE_ENABLED:
    @scheduler.scheduled_job("interval", seconds=PROACTIVE_CHECK_INTERVAL, id="proactive_speak")
    async def proactive_speak_job():
        # 计划 §6.4：root 在前置 return 之前创建——feature 开关关/无 Bot 等
        # 门控拒绝也有可查询原因，而不是一条空跑的定时任务。
        fctx = None
        try:
            from core.observability import message_flow

            fctx = message_flow.begin_trace(
                root_kind="proactive_timer", platform="qq", scope="qq:timer",
                origin="timer", trigger="proactive_check_interval",
            )
        except Exception:
            fctx = None

        def _timer_end(outcome: str) -> None:
            try:
                from core.observability import message_flow

                if fctx is not None and not fctx.ended:
                    message_flow.end_trace(fctx, outcome=outcome)
            except Exception:
                pass

        if not PROACTIVE_ENABLED:
            _flow_decision(fctx, "proactive.timer.preflight", status="skipped",
                           reason_code="proactive_disabled")
            _timer_end("disabled")
            return
        # 每个循环重新取 bot，避免 Bot 对象失效
        try:
            from nonebot import get_bot
            bot = get_bot()
        except Exception as e:
            logger.debug(f"主动发言跳过：无可用 Bot（{e}）")
            _flow_decision(fctx, "proactive.timer.preflight", status="skipped",
                           reason_code="no_bot")
            _timer_end("no_bot")
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
                if await _proactive_at_user(bot, group_id, flow_ctx=fctx):
                    _flow_decision(fctx, "proactive.timer.preflight",
                                   status="succeeded", reason_code="at_spoke",
                                   instance_key=f"grp:{group_id}")
                    continue
                if PARTICIPATION_ENABLED:
                    # 评分层接管「什么时候说」：掷骰子路径停用，
                    # 话题插话由被动消息上的 observe() 事件驱动。
                    _flow_decision(fctx, "proactive.timer.preflight",
                                   status="skipped",
                                   reason_code="participation_event_driven",
                                   instance_key=f"grp:{group_id}")
                    continue
                await _proactive_speak_for_group(bot, group_id)
            except Exception as e:
                logger.error(f"主动发言异常（群 {group_id}）: {e}")
        _timer_end("closed")


# 评分层的状态机推进：COOLING→EXPIRED 不依赖新消息，必须靠定时任务推进，
# 否则一个沉寂话题永远停在 COOLING、持续吃 25 分过期惩罚（或反之永不失效）。
if scheduler is not None and PARTICIPATION_ENABLED:
    @scheduler.scheduled_job(
        "interval", seconds=PARTICIPATION_TICK_INTERVAL, id="participation_tick"
    )
    async def participation_tick_job():
        try:
            changes = get_participation_manager().tick()
            for change in changes:
                logger.info(f"📊 [参与评分] {change}")
        except Exception as e:
            logger.warning(f"⚠️ [参与评分] 状态机推进异常: {e}")


# 表达学习的兜底结算（设计阶段六）：进程重启会丢掉在途的延迟任务，
# 定期扫描超窗未结算的 reply_effects 补结算。
if scheduler is not None:
    @scheduler.scheduled_job(
        "interval", seconds=EXPRESSION_SWEEP_INTERVAL, id="expression_sweep"
    )
    async def expression_sweep_job():
        try:
            swept = expression_learning.sweep_pending_effects()
            if swept:
                logger.info(f"📝 [Expression] 补结算 {swept} 条超窗回复效果")
        except Exception as e:
            logger.debug(f"[Expression] sweep 任务异常: {e}")


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
        """定期排空各会话的整合积压。

        整合此前只在 @ 触发与主动发言前进行，被动摄入速度超过整合速度时会
        无界积压，超过 MESSAGE_CLEANUP_KEEP_COUNT 后未整合消息会被清理丢弃。
        两条循环互补（计划 §6.3）：ALLOWED_GROUPS 覆盖尚未注册的 legacy 群；
        注册表循环覆盖私聊等 registered conversations（backlog 检查让重复
        访问无副作用）。
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
        try:
            await consolidator.drain_registered_sessions(
                max_rounds=CONSOLIDATION_MAX_ROUNDS_PER_RUN,
                allowed_groups=ALLOWED_GROUPS,
            )
        except Exception as e:
            logger.warning(f"⚠️ 定时整合异常（注册会话）: {e}")


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
        # 表达学习的数据保留期清理（设计阶段六）：样本与已结算效果行
        with contextlib.suppress(Exception):
            pruned = expression_learning.prune_learning()
            if pruned:
                logger.info(f"📝 [Expression] 已清理过期学习数据: {pruned}")


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
    if _hot_reload_watcher is not None:
        _hot_reload_watcher.cancel()
    # cometa 先停（泵 + worker 子进程）：不再认领新任务，在途任务发取消请求
    # 并等有界收尾；到点未停的 attempt 交租约过期 + 下次启动恢复矩阵处理
    # （方案 §6.8：不做无条件 running→queued）。
    with contextlib.suppress(Exception):
        await _stop_cometa()
    # 调度 worker 先停：不再认领新运行，等当前运行收尾（受 stop_grace 上界）；
    # 超时的在途运行交给租约恢复，下次启动按 delivery_unknown / 回队处理。
    if _scheduling_runtime is not None:
        with contextlib.suppress(Exception):
            await _scheduling_runtime.stop()
    # 先排空 facade 在途轮次（provider 调用收尾再落库/发送）。
    # 与调度 worker 同理：超时未收尾的轮次由运行记录标记，不自动重放。
    from core.runtime import facade as _rt_facade

    shared = _rt_facade.peek_shared_facade()
    if shared is not None:
        with contextlib.suppress(Exception):
            await shared.drain()
        with contextlib.suppress(Exception):
            await shared.stop()

    from memory.consolidator import pending_tasks as pending_consolidations
    from memory.session_compact import pending_tasks as pending_compactions

    await wait_for_tasks(
        _reply_check_tasks,
        list(pending_consolidations()) + list(pending_compactions()),
        SHUTDOWN_GRACE_SECONDS,
    )

    # 最后把没落盘的用量增量写出去：节流机制下最多攒了 16 条 / 60 秒，
    # 不 flush 就丢这一小段，重启后今日累计比实际偏低、预算被悄悄放宽。
    # 放在等任务之后：那些任务还会继续产生用量。
    with contextlib.suppress(Exception):
        from core.llm import usage_store

        usage_store.flush()
