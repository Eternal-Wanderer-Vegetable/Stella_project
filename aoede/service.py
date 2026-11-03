# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""Aoede 主动插话编排（原 ``ai_gateway`` 主动发言区，2026-11-03 计划 §3.1
S1-02 外移）。

覆盖：参与评分证据/指令构建、ALLOW_LLM 后台发言、定时主动插话主体、
睡眠/苏醒播报与定时 tick 主体。行为与外移前逐行等价；宿主相关依赖由
:mod:`aoede.host` 注入。本模块不导入 NoneBot 适配器类型。

``ai_gateway`` 保留 scheduler 注册与 ``_sole_timer_qq_bot``（适配器发现属
装配层职责），job 体委托给 :func:`proactive_timer_tick`。
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import random

from nonebot import logger

from aoede.gate import is_sleeping, note_sleep_transition, user_now
from aoede.host import ProactiveHost
from aoede.prompts import PROACTIVE_SKIP_MARKER, is_proactive_skip
from aoede.storage.legacy_state import get_runtime_state, mark_announced
from config import (
    PROACTIVE_MAX_LINES,
    PROACTIVE_SLEEP_ANNOUNCE,
    PROACTIVE_SLEEP_MESSAGES,
    PROACTIVE_WAKEUP_MESSAGES,
    SEND_INTERVAL,
)
from core.context import ChatContext
from core.llm import ROLE_CHAT
from core.runtime.facade import E_CANCELLED, RuntimeTurnError, new_turn_deadline
from core.social.contracts import (
    ConversationScope,
    delivered_texts,
    new_trace_id,
)
from core.social.delivery import DeliveryPlanError, deliver_lines
from core.transport import BotRef, DeliveryTarget, OutboundMessage, SceneRef
from gravitas.errors import DeadlineExceeded

# 后台参与发言任务引用：必须持有，否则可能在完成前被 GC（原
# ai_gateway._reply_check_tasks 语义；关停时由装配层统一 drain）。
background_tasks: set[asyncio.Task] = set()


def register_background_task(task: asyncio.Task) -> None:
    """登记后台任务引用并在完成时自动丢弃（防 GC）。"""
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


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


def build_participation_evidence(decision, trigger_text: str, snapshot: dict | None) -> dict:
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


def participation_instruction(instruction: str, evidence: dict | None) -> str:
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


def log_participation_event(decision, event: str, reason: str = "") -> None:
    """把生成器生命周期事件交给 ParticipationManager，缺失时静默降级。

    经已安装宿主解析 manager（与 gateway 级 monkeypatch 合同一致）；宿主
    未装配时静默跳过。
    """
    if decision is None:
        return
    try:
        from aoede.host import get_host

        manager = get_host().get_participation_manager()
        log_event = getattr(manager, "log_event", None)
        if callable(log_event):
            log_event(decision, event, reason=reason)
    except Exception:
        # 观测失败不能影响主动发言控制流。
        pass


def spawn_participation_speak(
    host: ProactiveHost,
    group_id: int,
    decision,
    *,
    bot_ref=None,
    trigger_text: str = "",
    parent_trace_id: str = "",
) -> None:
    """决策命中 ALLOW_LLM 后的后台执行（不阻塞消息监听）。

    任务引用必须持有（见 background_tasks 的说明），否则可能在完成前被 GC。
    """

    async def _runner() -> None:
        if host.resolve_background_bot is None:
            logger.debug(f"[参与评分] 群 {group_id} 跳过触发：宿主未装配后台 Bot 解析")
            return
        bot = host.resolve_background_bot(bot_ref) if bot_ref is not None else None
        if bot is None:
            logger.debug(f"[参与评分] 群 {group_id} 跳过触发：原 Bot 已离线或身份不匹配")
            return
        try:
            manager = host.get_participation_manager()
            snapshot = manager.snapshot(group_id)
            evidence = build_participation_evidence(decision, trigger_text, snapshot)
            await host.proactive_speak_for_group(
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
    hook = getattr(host, "register_task", None)
    if hook is not None:
        hook(task)
    else:
        register_background_task(task)


async def proactive_speak_for_group(
    host: ProactiveHost,
    bot,
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
        await proactive_speak_impl(
            host, bot, group_id, intent=intent, instruction=instruction,
            skip_dice=skip_dice, decision=decision, evidence=evidence, fctx=fctx,
        )
    except Exception:
        host.flow_set_outcome(fctx, "error")
        raise
    finally:
        try:
            from core.observability import message_flow

            if fctx is not None and not fctx.ended:
                message_flow.end_trace(fctx, outcome=fctx.outcome or "closed")
        except Exception:
            pass


async def proactive_speak_impl(
    host: ProactiveHost,
    bot,
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
    from gravitas.controller import active_controller

    pressure_controller = active_controller()
    if pressure_controller is not None:
        try:
            from gravitas.contracts import WorkClass
            from gravitas.model_calls import role_call_context

            resource_id = role_call_context(
                ROLE_CHAT,
                work_class=WorkClass.BACKGROUND,
                tag="proactive-pressure",
            ).resource_group_id
            pressure = pressure_controller.admit_proactive(resource_id)
            if not pressure.allowed:
                host.flow_decision(
                    fctx,
                    "proactive.preflight",
                    status="blocked",
                    reason_code=pressure.reason_code,
                )
                log_participation_event(
                    decision, "generation_skip", pressure.reason_code
                )
                return
        except Exception as exc:
            if pressure_controller.effective_mode.value == "enforce":
                logger.warning(
                    "[Gravitas] 主动任务压力决策不可用，安全跳过: %s", exc
                )
                host.flow_decision(
                    fctx,
                    "proactive.preflight",
                    status="blocked",
                    reason_code="pressure_policy_unavailable",
                )
                log_participation_event(
                    decision, "generation_skip", "pressure_policy_unavailable"
                )
                return
            logger.debug("[Gravitas] shadow pressure observation skipped: %s", exc)

    # 先判断该群是否到了“可以主动发言”的时机（统一闸门判定）
    allowed, reason = host.can_speak(group_id, "join")
    if not allowed:
        host.flow_decision(fctx, "proactive.preflight", status="blocked",
                           reason_code=f"can_speak:{reason}")
        logger.debug(f"[主动发言] 群 {group_id} 跳过：{reason}")
        return
    proactive = host.get_proactive()
    # gate 通过后再掷概率骰：概率是话题插话独有的（主动 @ 由配额与冷却约束，不掷骰）
    if not skip_dice and not proactive.should_speak(group_id):
        host.flow_decision(fctx, "proactive.preflight", status="skipped",
                           reason_code="dice_skip")
        return
    turn_deadline = new_turn_deadline()
    # 同样要抢占本群的互斥锁：主动发言不能和 @ 回复并发，避免上下文被互相污染
    lock = host.group_locks[group_id]
    async with lock:
        # 必须在群锁内判断：多个后台触发可能同时排队，锁外判断会让它们
        # 一起通过 cooldown，随后连续启动多次主动回复。
        gate = host.get_reply_gate().evaluate(
            group_id,
            trigger="proactive",
            intent=intent,
        )
        if not gate.allowed:
            host.flow_decision(fctx, "proactive.preflight", status="blocked",
                               reason_code="reply_gate")
            logger.info(
                f"[ReplyGate] 群 {group_id} 跳过主动发言："
                f"{', '.join(gate.reasons)}"
            )
            return
        host.get_reply_gate().start(group_id, proactive=True)
        conversation_ref = host.register_group_ref(str(bot.self_id), group_id)
        # 主动发言前先确保短期记忆已更新（force 本地小批量，不打扰在线 LLM）
        try:
            from config import CONSOLIDATION_TRIGGER_NEW_MESSAGES
            from mneme.consolidator import maybe_consolidate

            consolidator = host.get_consolidator()
            new_count = consolidator.has_new_messages_to_consolidate(
                conversation_ref.storage_session_id,
                threshold=CONSOLIDATION_TRIGGER_NEW_MESSAGES,
            )
            if new_count > 0:
                logger.info(f"🧠 [Proactive] 主动发言前触发短期记忆总结（新消息 {new_count} 条）")
                host.flow_checkpoint(fctx, "proactive.consolidate",
                                     summary="spawned, sleep 1s, not awaiting success")
                maybe_consolidate(
                    conversation_ref=conversation_ref,
                    force=True,
                    parent_trace_id=getattr(fctx, "trace_id", ""),
                )
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.warning(f"⚠️ 主动发言前总结异常（跳过）: {e}")

        # 构造一次"主动插话"的对话上下文
        # 注意 user_id=0、trigger='proactive'：让 Pipeline 认为自己是被邀请插话，而不是 @ 回复
        ctx = ChatContext(
            user_id=0,
            group_id=group_id,
            msg_id=0,
            message=participation_instruction(
                instruction or _PARTICIPATION_DEFAULT_INSTRUCTION,
                evidence,
            ),
            trigger="proactive",
            intent=intent,
            gate_path=gate.path,
            gate_score=gate.score,
            gate_reasons=gate.reasons,
            trace_id=fctx.trace_id if fctx is not None else new_trace_id(),
            turn_deadline=turn_deadline,
            conversation_kind="group",
            conversation_key=conversation_ref.conversation_key,
            bot_ref=BotRef(
                f"legacy-qq:{bot.self_id}", "onebot-v11", "qq", str(bot.self_id)
            ),
            scene_ref=SceneRef("group", str(group_id)),
            connection_id=f"legacy-qq:{bot.self_id}",
            adapter_name="onebot-v11",
            platform_scope="qq",
            scene_kind="group",
            scene_id=str(group_id),
            bot_id=str(bot.self_id),
            peer_id=str(group_id),
            storage_session_id=conversation_ref.storage_session_id,
        )
        try:
            from core.observability import message_flow

            message_flow.attach(ctx, fctx)
        except Exception:
            pass
        # 话题版本快照（计划 §6.9 层 3）：生成前捕获，发送前与逐段发送中比对
        try:
            rev_before = host.get_participation_manager().topic_revision(group_id)
        except Exception:
            rev_before = 0

        def _stale() -> bool:
            try:
                return host.get_participation_manager().topic_revision(group_id) != rev_before
            except Exception:
                return False

        try:
            with host.flow_span(fctx, "proactive.turn"):
                ctx = await host.run_turn(conversation_ref.runtime_key, ctx)
        except DeadlineExceeded as e:
            host.flow_set_outcome(fctx, "deadline_exceeded")
            log_participation_event(decision, "generation_skip", f"turn_deadline_{e.phase}")
            logger.info(f"⏳ [主动发言] 群 {group_id} 总期限耗尽，跳过发送（{e.phase}）")
            return
        except RuntimeTurnError as e:
            # 取消（reset/新直接请求抢占）：无发送、无兜底、无记账
            if e.code == E_CANCELLED:
                host.flow_set_outcome(fctx, "cancelled")
                log_participation_event(decision, "generation_skip", "cancelled")
                logger.info(f"🔇 [主动发言] 群 {group_id} 轮次已取消，静默退出")
                return
            raise
        except Exception as e:
            host.flow_set_outcome(fctx, "turn_error")
            logger.error(f"主动发言 Pipeline 异常: {e}")
            log_participation_event(decision, "generation_skip", "pipeline_error")
            return
        finally:
            # Planner 判定 WAIT 时让本群停在 WAITING 而不是 IDLE（设计阶段五）：
            # 「在等更多消息」与「没在说话」是两种状态，后续 observe 可据此区分。
            host.get_reply_gate().finish(group_id, waiting=bool(getattr(ctx, "planner_wait", False)))
        if not ctx.lines:
            host.flow_decision(fctx, "proactive.filter", status="skipped",
                               reason_code="empty_output")
            log_participation_event(decision, "generation_skip", "empty_output")
            return

        # 发送前过期检查：生成期间出现转题/撤销/静音/新直接请求 → 丢弃旧输出
        if _stale():
            host.flow_decision(fctx, "proactive.filter", status="skipped",
                               reason_code="stale_output")
            log_participation_event(decision, "generation_skip", "stale_output")
            logger.info(f"[主动发言] 群 {group_id} 输出已过期（话题版本变化），丢弃不发")
            return

        if is_proactive_skip(ctx.lines):
            host.flow_decision(fctx, "proactive.filter", status="skipped",
                               reason_code="naturalness_skip")
            log_participation_event(decision, "generation_skip", "naturalness_skip")
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
                host.join_lines_naturally(ctx.lines[i : i + per_chunk])
                for i in range(0, len(ctx.lines), per_chunk)
            ]
        if not ctx.lines:
            # 行合并后的空输出也是一次过滤器退出（计划 §6.4：每次退出有原因）
            host.flow_decision(fctx, "proactive.filter", status="skipped",
                               reason_code="empty_after_merge")
            return

        # 防刷屏：与最近一次主动/回复高度相似时，本次主动发言直接放弃
        if host.get_proactive().recently_spoken(group_id, ctx.lines):
            host.flow_decision(fctx, "proactive.filter", status="skipped",
                               reason_code="duplicate_output")
            log_participation_event(decision, "generation_skip", "duplicate_output")
            logger.info(f"🛑 [主动发言] 群 {group_id} 与已发言内容重复，跳过")
            return

        # 逐段发送 + 回执收集（计划 §6.1）：确认送达后才记账。原实现先记账后
        # 发送，发送失败已被记成「说过」并进入学习——正是计划 §2 优先修复项。
        scope = ConversationScope.from_context(ctx) if host.social_delivery_enabled() else None

        async def _send_proactive_segment(seg_line: str, _i: int):
            return await host.get_outbound_service().send(
                host.delivery_target_for_context(ctx),
                OutboundMessage.text(seg_line),
                bot_handle=bot,
                deadline=getattr(ctx, "turn_deadline", None),
            )

        try:
            delivery_plan = host.seal_ctx_delivery_plan(
                ctx, list(ctx.lines), variant_origin="proactive-group-merge",
            )
        except DeliveryPlanError as e:
            host.flow_decision(fctx, "proactive.send", status="blocked",
                               reason_code="invalid_delivery_plan", summary=str(e)[:160])
            host.flow_set_outcome(fctx, "delivery_plan_rejected")
            log_participation_event(decision, "generation_skip", "delivery_plan_rejected")
            return
        receipts = await deliver_lines(
            delivery_plan,
            scope=scope,
            trace_id=ctx.trace_id,
            turn_id=ctx.turn_id,
            send_one=_send_proactive_segment,
            interval_seconds=SEND_INTERVAL,
            abort_check=_stale,
            deadline=getattr(ctx, "turn_deadline", None),
            plan_guard=lambda plan: host.delivery_plan_is_current(ctx, plan),
        )
        delivered = delivered_texts(receipts)
        if not delivered:
            host.flow_set_outcome(fctx, "not_delivered")
            log_participation_event(decision, "send_failed", "no_segment_delivered")
            logger.error(f"[主动发言] 群 {group_id} 全部片段发送失败（不记账不学习）")
            return

        host.flow_set_outcome(fctx, "delivered")
        # 发送后动作（计划 §6.4：不用空 span 冒充——记账/学习/记录/压缩
        # 都真实发生在确认送达之后，proactive.after span 包住它们）
        with host.flow_span(fctx, "proactive.after"):
            # 只对 acknowledged 段记账（计划 §6.1/§6.4）：delivered 是发送
            # 确认后的片段，未确认段不进入任何记账/学习
            host.flow_checkpoint(fctx, "proactive.after",
                                 summary="acknowledged-only bookkeeping",
                                 metrics={"delivered_segments": len(delivered),
                                          "total_segments": len(receipts)})
            # 通知频率跟踪“本群已发言”，避免连续多次主动插话打扰
            proactive.mark_spoke(group_id)
            host.get_proactive().record_spoken(group_id, delivered)
            # 评分层记账：主动插话（累积 RecentSpeechPenalty / RepetitionPenalty），
            # 一次逻辑发言只更新一次，不按片段重复计数；文本进 novelty 比对语料
            with contextlib.suppress(Exception):
                host.get_participation_manager().note_stella_spoke(
                    group_id, "proactive", text=delivered[0]
                )
            host.flow_checkpoint(fctx, "proactive.after",
                                 summary="note_stella_spoke(proactive)")
            # 回复效果学习（设计阶段六）：群级记录「主动插话是否被接话」；
            # user_id=0 表示全群目标，效果结算按群归因（不再作为过滤条件）。
            from mneme import expression_learning

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
                bot_id=scope.bot_id if scope else "",
                connection_id=scope.connection_id if scope else "",
            )
            logger.success(f"✨ [主动发言] 群 {group_id}: {' | '.join(delivered)}")
            # 群级主动（user_id=0）：origin 给出但无个人收件人——
            # _record_bot_lines 内部把收件人与源消息留空（unknown），不猜目标
            await host.record_bot_lines(
                int(bot.self_id), conversation_ref.storage_session_id, delivered,
                origin=ctx, receipts=receipts,
            )

            # 主动发言同样推进对话：回复后异步触发压缩（不阻塞本次发言）
            if ctx.tail_start_id:
                host.schedule_compact(
                    conversation_ref.storage_session_id, ctx.tail_start_id,
                    parent_trace_id=fctx.trace_id if fctx is not None else "")
                host.flow_checkpoint(fctx, "proactive.after",
                                     summary="compact spawned, not awaited")

            log_participation_event(
                decision, "sent",
                _aggregate_delivery_status([r.status for r in receipts]),
            )


def _aggregate_delivery_status(statuses) -> str:
    """聚合逐段回执状态（委托 core.social.contracts，保持原语义）。"""
    from core.social.contracts import aggregate_delivery_status

    return aggregate_delivery_status(statuses)


async def announce_sleep_transition(host: ProactiveHost, bot, group_id: int) -> None:
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

    bot_id = str(getattr(bot, "self_id", "") or "")
    if not bot_id:
        logger.warning(f"⚠️ [{kind}] 播报 Bot 身份缺失，跳过")
        return
    conversation_ref = host.register_group_ref(bot_id, group_id)
    target = DeliveryTarget(
        BotRef(f"legacy-qq:{bot_id}", "onebot-v11", "qq", bot_id),
        SceneRef("group", str(group_id)),
    )
    if host.send_background_message is None:
        logger.warning(f"⚠️ [{kind}] 宿主未装配后台发送通道，跳过播报")
        return
    # 自发播报共用普通主动预算（S2-03，计划 §6.5）：R=0 时播报也关闭；
    # ACK 才 commit，失败 release，未知保守消耗。
    from aoede.budget import (
        ProactiveBudgetStore,
        budget_scope_key,
        new_operation_id,
    )
    from config import PROACTIVE_FREQUENCY

    store = ProactiveBudgetStore(host.db_path())
    operation_id = new_operation_id()
    reservation = store.reserve(
        budget_scope_key(target.bot, group_id),
        operation_id,
        frequency_per_hour=float(PROACTIVE_FREQUENCY),
        kind="ANNOUNCE",
    )
    if not reservation.granted:
        logger.info(f"⏳ [{kind}] 播报因预算未放行（{reservation.reason}）")
        return

    try:
        result = await host.send_background_message(target, OutboundMessage.text(line))
    except Exception as e:
        logger.warning(f"⚠️ [{kind}] 播报发送结果未知: {e}")
        store.resolve_unknown(operation_id)
        return
    if result.status.value != "accepted":
        logger.warning(
            f"⚠️ [{kind}] 播报未确认送达: {result.status.value}/"
            f"{result.error_code or '-'}"
        )
        store.release(operation_id)
        return
    store.commit(operation_id)

    mark_announced(group_id, kind, today)
    await host.record_bot_lines(
        int(bot.self_id), conversation_ref.storage_session_id, [line]
    )
    logger.info(f"{'🌙' if kind == 'sleep' else '☀️'} [{kind}] 群 {group_id}: {line}")


async def proactive_timer_tick(host: ProactiveHost, bot, *, fctx=None) -> None:
    """定时主动发言单轮 tick 主体（原 ``proactive_speak_job`` 循环体）。

    scheduler 注册与 ``_sole_timer_qq_bot`` 留在装配层；本函数只负责逐群
    尝试。睡眠/苏醒播报独立于主动发言：即使 gate 拒绝发言也要播报。
    """
    from aoede.verification.service import proactive_at_user
    from config import PARTICIPATION_ENABLED

    for group_id in _allowed_groups():
        try:
            await announce_sleep_transition(host, bot, group_id)
        except Exception as e:
            logger.warning(f"⚠️ 睡眠播报异常（群 {group_id}）: {e}")

        try:
            # 主动 @ 优先：它有明确目的（获取/验证记忆），
            # 且已受每用户配额与冷却约束。命中即跳过本轮话题插话，
            # 同一轮只发一次言。
            if await proactive_at_user(host, bot, group_id, flow_ctx=fctx):
                host.flow_decision(fctx, "proactive.timer.preflight",
                                   status="succeeded", reason_code="at_spoke",
                                   instance_key=f"grp:{group_id}")
                continue
            if PARTICIPATION_ENABLED:
                # 评分层接管「什么时候说」：掷骰子路径停用，
                # 话题插话由被动消息上的 observe() 事件驱动。
                host.flow_decision(fctx, "proactive.timer.preflight",
                                   status="skipped",
                                   reason_code="participation_event_driven",
                                   instance_key=f"grp:{group_id}")
                continue
            await proactive_speak_for_group(host, bot, group_id)
        except Exception as e:
            logger.error(f"主动发言异常（群 {group_id}）: {e}")


def _allowed_groups() -> list[int]:
    """读 ALLOWED_GROUPS（惰性，避免 aoede 在 import 时触配置）。"""
    from config import ALLOWED_GROUPS

    return list(ALLOWED_GROUPS)


def participation_tick(host: ProactiveHost) -> list[str]:
    """评分层状态机推进（原 ``participation_tick_job`` 体）。"""
    return host.get_participation_manager().tick()
