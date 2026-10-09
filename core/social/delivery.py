# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""逐段发送 + 回执收集（计划 §6.1「发送改造」的公共实现）。

QQ 发送入口（群/私聊普通回复、主动 @、主动群聊）统一走这里：

- 逐段 ``send_one(line, part_index)`` → 每段一个 :class:`DeliveryReceipt`；
  平台消息 ID 只有真实拿到才记录（引用归因的锚点）；
- 某段明确失败（平台异常）→ 该段 failed，**停止后续片段**（已 ACK 的片段
  不可撤销；继续发只会扩大半成功面），聚合状态由调用方计算（partial/failed）；
- 网络超时等不确定失败按 unknown 处理的判定在平台适配层做不到——适配器
  抛什么异常这里无法区分，统一按 failed 记录并保留错误文本；unknown 只来自
  「发送成功但落库失败」与取消中断；
- 每段回执**立即落库**（短事务、失败静默）：进程在多段发送中途崩溃时，
  已发事实不丢；
- ``FinishedException``（NoneBot matcher 结束控制流）原样上抛，绝不当作
  发送失败。

本模块不 import 网关、不知道 NoneBot matcher 的存在（send_one 由调用方
闭包提供），因此可以脱离机器人运行时单测。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from nonebot import logger
from nonebot.exception import FinishedException

from core.social.contracts import (
    DELIVERY_ACKNOWLEDGED,
    DELIVERY_FAILED,
    DELIVERY_UNKNOWN,
    ConversationScope,
    DeliveryReceipt,
    aggregate_delivery_status,
    utc_now_iso,
)
from memory import social_store

SendOne = Callable[[str, int], Awaitable[str | None]]
PlanGuard = Callable[[dict[str, Any]], bool | Awaitable[bool]]

DELIVERY_PLAN_SCHEMA_VERSION = 1
_DELIVERABLE_DISPOSITIONS = frozenset({"deliver", "fallback", "direct"})
_TRUSTED_SOURCE_KINDS = frozenset(
    {"model", "trusted-server", "trusted-server-fallback", "proactive-contract"}
)


class DeliveryPlanError(ValueError):
    """计划缺失、来源不可信或封存摘要校验失败。"""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_delivery_draft(
    *,
    trace_id: str,
    turn_id: str,
    source_kind: str,
    protocol_version: str,
    disposition: str,
    conversation_key: str,
    target_user_id: str = "",
    identity_revision: int = 0,
    generation_epoch: int = 0,
    captured_scope_versions: dict[str, int] | None = None,
    scope_versions_available: bool = True,
    segments: list[str] | tuple[str, ...] = (),
    decision: dict[str, Any] | None = None,
    origin: str = "model",
    evidence_ids: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """构造可变草稿；最终计划必须在入口完成变体后经 seal 冻结。"""
    versions = captured_scope_versions or {}
    clean_versions: dict[str, int] = {}
    for key, value in versions.items():
        if not isinstance(key, str) or not key or isinstance(value, bool) or not isinstance(value, int):
            raise DeliveryPlanError("scope version 格式无效")
        if value < 0:
            raise DeliveryPlanError("scope version 不可为负数")
        clean_versions[key] = value
    ids = tuple(dict.fromkeys(str(item) for item in evidence_ids if item))
    return {
        "schema_version": DELIVERY_PLAN_SCHEMA_VERSION,
        "trace_id": str(trace_id or ""),
        "turn_id": str(turn_id or ""),
        "source_kind": str(source_kind or ""),
        "protocol_version": str(protocol_version or ""),
        "disposition": str(disposition or ""),
        "conversation_key": str(conversation_key or ""),
        "target_user_id": str(target_user_id or ""),
        "identity_revision": int(identity_revision or 0),
        "generation_epoch": int(generation_epoch or 0),
        "captured_scope_versions": clean_versions,
        "scope_versions_available": bool(scope_versions_available),
        "decision_digest": _digest_json(decision or {}),
        "segments": [
            {
                "part_index": index,
                "text": str(text),
                "text_digest": _digest_text(str(text)),
                "origin": str(origin or "unknown"),
                "evidence_ids": list(ids),
            }
            for index, text in enumerate(segments)
        ],
    }


def delivery_draft_from_context(ctx: Any) -> dict[str, Any]:
    """从运行期 context 制作 Draft；只捕获安全标量与持久 owner 版本。"""
    disposition = str(getattr(ctx, "reply_disposition", "") or "deliver")
    lines = list(getattr(ctx, "lines", ()) or ())
    if disposition not in _DELIVERABLE_DISPOSITIONS or not lines:
        return {}
    captured_versions: dict[str, int] = {}
    scope_versions_available = True
    try:
        from memory.ownership import person_owner_key, space_owner_key
        from memory.scope_versions import current_versions_strict

        keys: list[str] = []
        space = str(getattr(ctx, "group_shared_space", "") or "")
        if space:
            keys.append(space_owner_key(space))
        bot_id = str(getattr(ctx, "bot_id", "") or "")
        user_id = int(getattr(ctx, "user_id", 0) or 0)
        if bot_id and user_id > 0 and str(getattr(ctx, "conversation_key", "")).startswith("qq:"):
            keys.append(person_owner_key("qq", bot_id, user_id))
        captured_versions = current_versions_strict(list(dict.fromkeys(keys)))
    except Exception:
        captured_versions = {}
        scope_versions_available = False
    source_kind = str(getattr(ctx, "delivery_source_kind", "") or "")
    if not source_kind:
        source_kind = "model" if int(getattr(ctx, "llm_call_count", 0) or 0) > 0 else "unknown"
    typed_reply = getattr(ctx, "typed_reply", None) or {}
    decision = getattr(ctx, "guard_decision", None) or getattr(ctx, "attribution_decision", None) or {}
    return create_delivery_draft(
        trace_id=str(getattr(ctx, "trace_id", "") or ""),
        turn_id=str(getattr(ctx, "turn_id", "") or ""),
        source_kind=source_kind,
        protocol_version=str(typed_reply.get("protocol_version") or "legacy"),
        disposition=disposition,
        conversation_key=str(getattr(ctx, "conversation_key", "") or ""),
        target_user_id=str(
            getattr(ctx, "reply_recipient_user_id", "")
            or getattr(ctx, "peer_id", "")
            or ""
        ),
        identity_revision=int(getattr(ctx, "identity_revision", 0) or 0),
        generation_epoch=int(getattr(ctx, "generation_epoch", 0) or 0),
        captured_scope_versions=captured_versions,
        scope_versions_available=scope_versions_available,
        segments=lines,
        decision=decision,
        origin=source_kind,
        evidence_ids=list(getattr(ctx, "retained_evidence_ids", ()) or ()),
    )


def seal_delivery_plan(
    draft: dict[str, Any],
    lines: list[str] | tuple[str, ...] | None = None,
    *,
    target_user_id: str | None = None,
    variant_origin: str = "finalized_variant",
    evidence_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """按最终物理段封存 DeliveryPlan，并对整个版本图计算摘要。"""
    if not isinstance(draft, dict) or draft.get("schema_version") != DELIVERY_PLAN_SCHEMA_VERSION:
        raise DeliveryPlanError("delivery draft 缺失或版本不支持")
    if draft.get("disposition") not in _DELIVERABLE_DISPOSITIONS:
        raise DeliveryPlanError("非交付处置不能封存发送计划")
    if draft.get("source_kind") not in _TRUSTED_SOURCE_KINDS:
        raise DeliveryPlanError("delivery source 未获准")
    if draft.get("scope_versions_available") is not True:
        raise DeliveryPlanError("persistent scope version is unavailable")
    if not draft.get("trace_id") or not draft.get("turn_id") or not draft.get("conversation_key"):
        raise DeliveryPlanError("delivery identity 不完整")
    raw_segments = draft.get("segments")
    if not isinstance(raw_segments, list):
        raise DeliveryPlanError("delivery draft segments 无效")
    final_lines = list(lines) if lines is not None else [item.get("text", "") for item in raw_segments]
    if not final_lines or any(not isinstance(line, str) or not line.strip() for line in final_lines):
        raise DeliveryPlanError("delivery plan 不可为空或含空白段")
    base_ids = list(dict.fromkeys(
        str(item) for segment in raw_segments if isinstance(segment, dict)
        for item in (segment.get("evidence_ids") or []) if item
    ))
    final_ids = list(dict.fromkeys(str(item) for item in (evidence_ids or base_ids) if item))
    segments = []
    for index, line in enumerate(final_lines):
        source = next(
            (item for item in raw_segments if isinstance(item, dict) and item.get("text") == line),
            None,
        )
        origin = str(source.get("origin") or "unknown") if source else str(variant_origin or "unknown")
        ids = list(source.get("evidence_ids") or []) if source else final_ids
        segments.append({
            "part_index": index,
            "text": line,
            "text_digest": _digest_text(line),
            "origin": origin,
            "evidence_ids": list(dict.fromkeys(str(item) for item in ids if item)),
        })
    plan: dict[str, Any] = {
        "schema_version": DELIVERY_PLAN_SCHEMA_VERSION,
        "plan_id": uuid.uuid4().hex,
        "trace_id": str(draft["trace_id"]),
        "turn_id": str(draft["turn_id"]),
        "source_kind": str(draft["source_kind"]),
        "protocol_version": str(draft.get("protocol_version") or "legacy"),
        "disposition": str(draft["disposition"]),
        "conversation_key": str(draft["conversation_key"]),
        "target_user_id": str(target_user_id if target_user_id is not None else draft.get("target_user_id") or ""),
        "identity_revision": int(draft.get("identity_revision") or 0),
        "generation_epoch": int(draft.get("generation_epoch") or 0),
        "captured_scope_versions": dict(draft.get("captured_scope_versions") or {}),
        "scope_versions_available": True,
        "decision_digest": str(draft.get("decision_digest") or _digest_json({})),
        "segments": segments,
    }
    plan["digest"] = _digest_json(plan)
    if not verify_delivery_plan(plan):
        raise DeliveryPlanError("sealed delivery plan 自检失败")
    return plan


def verify_delivery_plan(
    plan: Any, *, trace_id: str | None = None, turn_id: str | None = None,
) -> bool:
    """验证 seal、段摘要、顺序、处置和可持久化身份。"""
    if not isinstance(plan, dict):
        return False
    if plan.get("schema_version") != DELIVERY_PLAN_SCHEMA_VERSION:
        return False
    if plan.get("source_kind") not in _TRUSTED_SOURCE_KINDS:
        return False
    if plan.get("disposition") not in _DELIVERABLE_DISPOSITIONS:
        return False
    if not plan.get("plan_id") or not plan.get("trace_id") or not plan.get("turn_id"):
        return False
    if not plan.get("conversation_key"):
        return False
    if trace_id is not None and plan.get("trace_id") != trace_id:
        return False
    if turn_id is not None and plan.get("turn_id") != turn_id:
        return False
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        return False
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or segment.get("part_index") != index:
            return False
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip() or segment.get("text_digest") != _digest_text(text):
            return False
        if not isinstance(segment.get("origin"), str) or not isinstance(segment.get("evidence_ids"), list):
            return False
    versions = plan.get("captured_scope_versions")
    if plan.get("scope_versions_available") is not True:
        return False
    if not isinstance(versions, dict) or any(
        not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, int) or value < 0
        for key, value in versions.items()
    ):
        return False
    unsigned = {key: value for key, value in plan.items() if key != "digest"}
    return plan.get("digest") == _digest_json(unsigned)


def coerce_platform_message_id(result) -> str | None:
    """把平台 send 调用的返回值规约为消息 ID 字符串；拿不到返回 None。

    OneBot v11 的 ``bot.send_group_msg`` 返回 ``{"message_id": int}`` 字典；
    NoneBot ``Matcher.send`` 透传适配器返回值。识别不了的一律 None——
    宁可没有归因锚点，不猜一个假 ID。
    """
    if result is None:
        return None
    if isinstance(result, bool):
        return None
    if isinstance(result, int):
        return str(result)
    if isinstance(result, dict):
        mid = result.get("message_id")
        return str(mid) if mid is not None else None
    text = str(result)
    return text if text.isdigit() else None


def _flow(trace_id: str):
    """按 trace_id 取消息流程 context（计划 §6.2）；未接入/已结束为 None。"""
    try:
        from core.observability import message_flow

        found = message_flow.by_trace(trace_id)
        return None if (found is None or found.ended) else found
    except Exception:
        return None


def _flow_span(fctx, node_id: str, **kw):
    try:
        from core.observability import message_flow

        return message_flow.span(fctx, node_id, **kw)
    except Exception:
        import contextlib

        return contextlib.nullcontext()


def _flow_decision(fctx, node_id: str, **kw) -> None:
    try:
        from core.observability import message_flow

        message_flow.decision(fctx, node_id, **kw)
    except Exception:
        pass


def _flow_transition(fctx, *, from_node: str, to_node: str, **kw) -> None:
    """显式边级跳转事实（修复计划 §6.4）：fail-open。"""
    try:
        from core.observability import message_flow

        message_flow.transition(fctx, from_node=from_node, to_node=to_node, **kw)
    except Exception:
        pass


async def deliver_lines(
    plan: dict[str, Any],
    *,
    scope: ConversationScope | None,
    trace_id: str,
    turn_id: str,
    send_one: SendOne,
    interval_seconds: float = 0.0,
    stop_on_failure: bool = True,
    abort_check: Callable[[], bool] | None = None,
    plan_guard: PlanGuard | None = None,
    receipt_conversation: Any = None,
) -> list[DeliveryReceipt]:
    """只发送已封存计划中的片段，并收集与该计划关联的回执。

    scope 为 None 时不写群学习行；具备明确 ``receipt_conversation`` 的私聊
    仍会写中立回执。计划决策摘要无论是否启用社交事件记录都先持久化，
    裸字符串/未封存计划在任何平台 side effect 发生前拒绝。

    ``receipt_conversation``（修复计划 §6.3）：可选的规范会话身份
    （:class:`core.conversation.ConversationRef` 或带
    conversation_key/conversation_kind/peer_id/storage_session_id/bot_id
    属性的对象）。``scope=None`` 且身份明确合法时，回执按**会话中立行**
    落库（group_id=''、learning_eligible=0）——私聊发送事实可查，绝不进
    群学习；scope=None 且无身份的旧调用仍跳过 social_deliveries receipt。

    ``abort_check``（计划 §6.9 层 3）：每个片段发送前调用，返回 True 表示
    本轮输出已过期（转题/撤销/静音/新直接请求）——停止后续片段并保留已
    收回执；已 ACK 的片段不可撤销，聚合状态按已尝试片段计算（partial 语义）。
    返回已尝试片段的回执列表（未尝试的片段没有事实，不产生行）。
    """
    if not verify_delivery_plan(plan, trace_id=trace_id, turn_id=turn_id):
        raise DeliveryPlanError("拒绝发送无效、未封存或已变更的 DeliveryPlan")
    # 使用经摘要核验的本地快照。每个片段开始前仍检查调用方持有的原对象，
    # 因为入口代码不得在 seal 后改写计划。
    snapshot = json.loads(_canonical_json(plan).decode("utf-8"))
    lines = [segment["text"] for segment in snapshot["segments"]]
    plan_id = snapshot["plan_id"]
    plan_digest = snapshot["digest"]
    decision_digest = snapshot["decision_digest"]
    epoch = int(snapshot["generation_epoch"])
    if not social_store.record_delivery_plan(snapshot):
        raise RuntimeError("DeliveryPlan decision digest could not be persisted; refusing send")

    receipts: list[DeliveryReceipt] = []
    started_at = time.monotonic()
    fctx = _flow(trace_id)
    for i, line in enumerate(lines):
        if i > 0 and interval_seconds > 0:
            await asyncio.sleep(interval_seconds)
        if not verify_delivery_plan(plan, trace_id=trace_id, turn_id=turn_id):
            logger.warning(f"[Delivery] sealed plan changed before segment {i}; stopping")
            _flow_decision(fctx, "send.segment", status="skipped",
                           reason_code="sealed_plan_changed",
                           instance_key=f"seg:{i}")
            break
        if plan_guard is not None:
            allowed = plan_guard(snapshot)
            if inspect.isawaitable(allowed):
                allowed = await allowed
            if not allowed:
                logger.info(f"[Delivery] captured identity/version changed before segment {i}")
                _flow_decision(fctx, "send.segment", status="skipped",
                               reason_code="delivery_plan_stale",
                               instance_key=f"seg:{i}")
                break
        if abort_check is not None and abort_check():
            logger.info(f"[Delivery] 发送中止（输出已过期）：段 {i}/{len(lines)} 未发送")
            _flow_decision(fctx, "send.segment", status="skipped",
                           reason_code="output_expired",
                           instance_key=f"seg:{i}",
                           summary=f"未尝试段 {i + 1}/{len(lines)}")
            break
        seg_span = _flow_span(fctx, "send.segment", instance_key=f"seg:{i}")
        seg_span.__enter__()
        try:
            platform_id = coerce_platform_message_id(await send_one(line, i))
            status = DELIVERY_ACKNOWLEDGED
        except FinishedException:
            seg_span.__exit__(FinishedException, None, None)
            raise
        except asyncio.CancelledError:
            # 取消中断：该段结果不明（平台可能已收到），绝不重发
            seg_span.__exit__(asyncio.CancelledError, None, None)
            _append_and_persist(
                receipts, scope, trace_id, turn_id, epoch, i,
                status=DELIVERY_UNKNOWN, text=line, platform_id=None, detail="cancelled",
                receipt_conversation=receipt_conversation,
                delivery_plan_id=plan_id, delivery_plan_digest=plan_digest,
                decision_digest=decision_digest,
            )
            raise
        except (asyncio.TimeoutError, TimeoutError) as e:
            # 平台请求超时可能已被受理；记 unknown 且禁止该 turn 重发。
            seg_span.__exit__(type(e), e, e.__traceback__)
            _append_and_persist(
                receipts, scope, trace_id, turn_id, epoch, i,
                status=DELIVERY_UNKNOWN, text=line, platform_id=None,
                detail="platform_timeout",
                receipt_conversation=receipt_conversation,
                delivery_plan_id=plan_id, delivery_plan_digest=plan_digest,
                decision_digest=decision_digest,
            )
            break
        except Exception as e:
            seg_span.__exit__(type(e), e, e.__traceback__)
            logger.warning(f"[Delivery] 群 {scope.group_id if scope else '?'} "
                           f"第 {i + 1}/{len(lines)} 段发送失败: {e}")
            _append_and_persist(
                receipts, scope, trace_id, turn_id, epoch, i,
                status=DELIVERY_FAILED, text=line, platform_id=None, detail=str(e)[:160],
                receipt_conversation=receipt_conversation,
                delivery_plan_id=plan_id, delivery_plan_digest=plan_digest,
                decision_digest=decision_digest,
            )
            if stop_on_failure:
                break
            continue
        seg_span.__exit__(None, None, None)
        _append_and_persist(
            receipts, scope, trace_id, turn_id, epoch, i,
            status=status, text=line, platform_id=platform_id,
            receipt_conversation=receipt_conversation,
            delivery_plan_id=plan_id, delivery_plan_digest=plan_digest,
            decision_digest=decision_digest,
        )
    _trace_delivery(trace_id, turn_id, scope, receipts, started_at)
    if fctx is not None:
        _flow_transition(fctx, from_node="send.segment", to_node="send.aggregate")
        statuses = [r.status for r in receipts]
        ack = statuses.count("acknowledged")
        _flow_decision(
            fctx, "send.aggregate",
            status=_aggregate_flow_status(statuses),
            summary=("partial" if 0 < ack < len(lines) else ""),
            metrics={"attempted": len(receipts), "lines": len(lines),
                     "acknowledged": ack,
                     "failed": statuses.count("failed"),
                     "unknown": statuses.count("unknown")},
        )
    return receipts


def _aggregate_flow_status(statuses: list[str]) -> str:
    """聚合状态 → flow status（业务 outcome 留在 metrics/summary，不混用）。"""
    if not statuses:
        return "failed"
    if all(s == "acknowledged" for s in statuses):
        return "succeeded"
    if any(s == "acknowledged" for s in statuses):
        return "succeeded"  # partial：已送达事实为真，未尝试段在 metrics 里
    if all(s == "unknown" for s in statuses):
        return "unknown"
    return "failed"


def _trace_delivery(trace_id: str, turn_id: str, scope: ConversationScope | None,
                    receipts: list[DeliveryReceipt], started_at: float | None) -> None:
    """投递事实入追踪（计划 §6.8 delivery 阶段）：metadata 恒记，detailed 按群。"""
    if not receipts:
        return
    try:
        from core.observability import turn_trace

        statuses = [r.status for r in receipts]
        scope_str = f"qq:{scope.group_id}" if scope else ""
        turn_trace.record_event(
            trace_id=trace_id, turn_id=turn_id, stage="delivery",
            status=aggregate_delivery_status(statuses),
            scope=scope_str, started_at=started_at,
            metrics={"segments": len(receipts),
                     "acknowledged": statuses.count("acknowledged"),
                     "failed": statuses.count("failed"),
                     "unknown": statuses.count("unknown")},
            detailed={
                "receipts": [
                    {"part": r.part_index, "status": r.status,
                     "platform_message_id": r.platform_message_id,
                     "text": r.text}
                    for r in receipts
                ],
            }
            if turn_trace.detailed_enabled_for_scope(scope_str) else None,
        )
    except Exception:
        pass


def _append_and_persist(
    receipts: list[DeliveryReceipt],
    scope: ConversationScope | None,
    trace_id: str,
    turn_id: str,
    epoch: int,
    part_index: int,
    *,
    status: str,
    text: str,
    platform_id: str | None,
    detail: str = "",
    receipt_conversation: Any = None,
    delivery_plan_id: str = "",
    delivery_plan_digest: str = "",
    decision_digest: str = "",
) -> DeliveryReceipt:
    """落库三分合同（修复计划 §6.3）：见 deliver_lines 文档。

    - scope 非空：沿用既有群存档（learning_eligible 由 scope 判定）；
    - scope=None 且 receipt_conversation 提供明确合法身份：存**会话中立
      回执**（group_id=''、learning_eligible=0），只存档不学习；
    - scope=None 且无身份：完全跳过持久化（原合同保留）。

    落库失败只记 receipt persistence unknown，不取消已确认发送、不重发。
    """
    # 身份读取同时接受两种形状（验收报告 H1）：规范 ConversationRef 的字段
    # 是 kind/platform/bot_id；测试与旧调用方的 SimpleNamespace 用
    # conversation_kind。真实 ref 此前因取错字段名被清空身份、回执不落库。
    conversation_key = str(getattr(receipt_conversation, "conversation_key", "") or "")
    conversation_kind = str(
        getattr(receipt_conversation, "conversation_kind", "")
        or getattr(receipt_conversation, "kind", "")
        or "")
    peer_id = str(getattr(receipt_conversation, "peer_id", "") or "")
    ref_platform = str(getattr(receipt_conversation, "platform", "") or "")
    ref_bot_id = str(getattr(receipt_conversation, "bot_id", "") or "")
    raw_storage = getattr(receipt_conversation, "storage_session_id", None)
    try:
        storage_session_id = int(raw_storage) if raw_storage is not None else None
    except (TypeError, ValueError):
        storage_session_id = None
    if not conversation_key or not conversation_kind:
        # 身份不完整 = 不明确合法：退回旧合同（不持久化），不猜
        conversation_key, conversation_kind, peer_id = "", "", ""
        storage_session_id = None

    neutral = scope is None and bool(conversation_key)
    receipt = DeliveryReceipt(
        trace_id=trace_id,
        turn_id=turn_id,
        part_index=part_index,
        status=status,
        epoch=epoch,
        platform_message_id=platform_id,
        acknowledged_at_utc=utc_now_iso() if status == DELIVERY_ACKNOWLEDGED else "",
        text=text,
        scope=scope,
        conversation_key=conversation_key,
        conversation_kind=conversation_kind,
        peer_id=peer_id,
        storage_session_id=storage_session_id,
        platform=ref_platform,
        bot_id=ref_bot_id,
        delivery_plan_id=delivery_plan_id,
        delivery_plan_digest=delivery_plan_digest,
        decision_digest=decision_digest,
    )
    receipts.append(receipt)
    should_persist = scope is not None or neutral
    if should_persist and not social_store.record_delivery(receipt):
        # 落库失败 = 发送成功但事实缺档（unknown 降级）：记日志，不阻塞后续片段
        logger.warning(f"[Delivery] 回执落库失败（turn={turn_id} part={part_index}）")
        # transmission 与 persistence 是两种独立事实（计划 A17）：发送已
        # confirmed，这里只标回执持久化失败，绝不妨碍该段 acknowledged。
        try:
            from core.observability import message_flow

            fctx = message_flow.by_trace(trace_id)
            if fctx is not None and not fctx.ended:
                message_flow.decision(
                    fctx, "send.receipt", status="failed",
                    reason_code="persist_error",
                    instance_key=f"seg:{part_index}",
                    metrics={"transmission": status})
        except Exception:
            pass
    if detail and status == DELIVERY_UNKNOWN:
        logger.info(f"[Delivery] 段 {part_index} 状态 unknown: {detail}")
    return receipt
