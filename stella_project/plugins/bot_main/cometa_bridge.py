# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""cometa 的 QQ 桥接：可信 Origin、ack 认领发送、通知 Sender（方案 §6.5/§6.11/§6.12）。

职责边界：桥只做「平台 ↔ cometa 通知协议」的翻译——构造 Origin（来自
真实 OneBot 事件，**不由模型生成**）、认领并发送受理确认、把通知投到原
会话。cometa 内核对 QQ 零依赖；桥对任务库只有经 service/store CAS 的短操作。

ack 双通道互斥（§6.5）：入口（本桥 ``deliver_ack``）与后台投递泵对同一条
ack 通知做 ``pending → sending`` 的 CAS 竞争，谁先认领谁发送，另一方放弃
——绝不出现「当前聊天发送一次 ack，后台又发送一次」。

长结果投递（§6.12 附件交付，2026-10-01 依用户决策实现）：final 结果的完整
文本超过阈值时，**上传 .md 文件为主**（QQ 原生渲染 Markdown），合并转发
消息兜底，纯文本摘要垫底；只有平台明确拒绝时才降级。超时或结果不明会停止
后续发送，避免重复投递；封面文本如实说明完整内容是否送达。
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from pathlib import Path

from nonebot import logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from core.transport.models import BotRef, SceneRef
from core.transport.outbound import DeliveryTarget

AckSender = Callable[[str], Awaitable[str | None]]


def build_origin(event: MessageEvent, bot, *, instance_id: str) -> dict | None:
    """从真实消息事件构造可信 Origin dict v3（方案 §6.1，计划 §6.8）。

    只在用户显式触达路径（群 @ / 私聊消息）调用；被动摄入与主动发言路径不会
    构造 Origin——这是「委派只由用户显式请求触发」的入口保证（§6.4.1）。

    v3 持久化完整 BotRef 与 DeliveryTarget。conversation_id 保持历史显示/查询
    口径；后台投递只认版本化 target，不从 conversation_id 或模型文本猜路由。
    """
    if not instance_id:
        return None
    bot_id = str(getattr(event, "self_id", "") or getattr(bot, "self_id", ""))
    if isinstance(event, GroupMessageEvent):
        kind, peer = "group", str(event.group_id)
        conversation_id = str(event.group_id)
    else:
        peer = str(getattr(event, "user_id", "") or "")
        kind = "private"
        conversation_id = f"qq:{bot_id}:private:{peer}"
    conversation_key = f"qq:{bot_id}:{kind}:{peer}"
    bot_ref = BotRef(f"legacy-qq:{bot_id}", "onebot-v11", "qq", bot_id)
    target = DeliveryTarget(bot=bot_ref, scene=SceneRef(kind, peer))
    from cometa.models import Origin

    return Origin(
        instance_id=instance_id,
        platform="qq",
        bot_id=bot_id,
        conversation_id=conversation_id,
        requester_id=str(event.user_id),
        source_request_id=f"msg-{event.message_id}",
        reply_to_message_id=str(event.message_id),
        conversation_generation=1,
        conversation_kind=kind,
        peer_id=peer,
        conversation_key=conversation_key,
        bot_ref=bot_ref,
        target=target,
    ).to_dict()


async def deliver_ack(submission: dict, send: AckSender) -> str:
    """入口发送受理确认。返回 ``sent`` / ``unknown`` / ``pump_owned``。

    - 先 CAS 认领 ack 通知（pending → sending）：抢不到说明泵已接管，
      入口**跳过发送**（调用方据此不再走普通回复链路的这条 ack）；
    - 发送成功按回执记 sent；失败记 delivery_unknown，**不自动重发**
      （§6.5：后续状态/结果附任务短 ID，用户仍能识别任务）。
    """
    from cometa import runtime as cometa_runtime
    from cometa.models import NotificationState

    service = cometa_runtime.current_service()
    if service is None:
        return "unknown"
    notification_id = str(submission.get("ack_notification_id") or "")
    if not notification_id:
        return "unknown"
    claimed = service.store.claim_notification(notification_id)
    if claimed is None:
        return "pump_owned"
    ack_text = str(submission.get("ack_text") or "")
    try:
        receipt = await send(ack_text)
    except Exception as e:
        service.store.mark_notification(
            notification_id,
            state=NotificationState.DELIVERY_UNKNOWN,
            error=f"ack_send_error: {type(e).__name__}",
        )
        logger.warning(f"⚠️ [Cometa] ack 发送失败（结果未知，不自动重发）: {e!r}")
        return "unknown"
    service.store.mark_notification(
        notification_id, state=NotificationState.SENT, receipt=str(receipt or "")
    )
    return "sent"


# ============================================================
# 长结果投递：切段器 + 文件/合并转发双通道（§6.12）
# ============================================================

_NODE_MAX_CHARS = 900  # 单个转发 node 的舒适上限（QQ 手机端展开阅读友好）


def split_markdown(text: str, max_chars: int = _NODE_MAX_CHARS) -> list[str]:
    """按 Markdown 结构边界切段，绝不切进代码围栏内部。

    切分优先级：标题行（# 开头）> 空行 > 硬切。用于合并转发 node 的内容，
    也可单独用于分段文本投递（方案 3 的内部件）。
    """
    if len(text) <= max_chars:
        return [text] if text else []
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    in_fence = False

    def flush() -> None:
        nonlocal current, size
        if current:
            chunks.append("\n".join(current).strip("\n"))
        current, size = [], 0

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        line_len = len(line) + 1
        boundary = (
            not in_fence
            and current
            and (line.startswith("#") or line.strip() == "")
        )
        if (size + line_len > max_chars and not in_fence) or (boundary and size + line_len > max_chars // 2):
            flush()
        if len(line) + 1 > max_chars and not in_fence:
            # 单行超限：硬切（保留内容，接受边界粗糙）
            while line:
                take = line[:max_chars]
                line = line[max_chars:]
                chunks.append(take)
            continue
        current.append(line)
        size += line_len
    flush()
    return [c for c in chunks if c]


def make_notification_sender(
    artifacts_dir: Path, delivery_config
):
    """构造 QQ/WebChat 通知 Sender（pump 的 NotificationSender 协议）。

    长结果投递链（final 通知携带 full_text_ref/full_text_chars 且达到
    阈值时启用，§6.12）：

    1. **上传 .md 群文件**（主）：QQ 原生渲染 Markdown，视觉保真最好；
    2. **合并转发消息**（兜底）：NapCat 扩展 API，切段器分 node；
    3. **纯文本摘要**（垫底）：现行行为，封面文本注明完整内容未送达。

    每一级先于发送探测精确 Bot 在线（离线 → SenderUnavailable → 泵退避重试，
    那时尚无任何平台调用）。平台明确 ActionFailed 才进入下一级；超时和通用异常
    作为 delivery_unknown 终态，不再尝试另一条发送路径。
    """
    artifacts_dir = Path(artifacts_dir)
    long_result = getattr(delivery_config, "long_result", "file")
    file_above_chars = int(getattr(delivery_config, "file_above_chars", 500))

    def _target_from_dict(target: dict) -> DeliveryTarget:
        raw = target.get("delivery_target")
        if raw is not None:
            delivery_target = DeliveryTarget.load(raw)
        else:
            bot_id = str(target.get("bot_id") or "")
            group_id = str(target.get("group_id") or "")
            kind = str(target.get("conversation_kind") or "")
            peer = str(target.get("peer_id") or "")
            if not kind and group_id.isdigit() and int(group_id) > 0:
                # Pre-v3 notification rows only recorded a group destination.
                kind, peer = "group", group_id
            if kind == "group":
                peer = peer or group_id
                if group_id and peer != group_id:
                    raise ValueError("Cometa group target fields disagree")
            if (
                not bot_id.isdigit()
                or int(bot_id) <= 0
                or kind not in {"group", "private"}
                or not peer.isdigit()
                or int(peer) <= 0
            ):
                raise ValueError("Cometa QQ target is incomplete; refusing to guess")
            from core.transport.models import BotRef, SceneRef

            delivery_target = DeliveryTarget(
                bot=BotRef(f"legacy-qq:{bot_id}", "onebot-v11", "qq", bot_id),
                scene=SceneRef(kind, peer),
            )
        if (
            delivery_target.bot.adapter != "onebot-v11"
            or delivery_target.bot.platform_scope != "qq"
            or delivery_target.bot.connection_id
            != f"legacy-qq:{delivery_target.bot.self_id}"
            or delivery_target.scene.kind not in {"group", "private"}
            or not delivery_target.scene.scene_id.isdigit()
            or int(delivery_target.scene.scene_id) <= 0
        ):
            raise ValueError("Cometa DeliveryTarget is not a verifiable QQ route")
        if str(target.get("bot_id") or "") not in {"", delivery_target.bot.self_id}:
            raise ValueError("Cometa bot_id does not match DeliveryTarget")
        if str(target.get("conversation_kind") or "") not in {
            "", delivery_target.scene.kind
        }:
            raise ValueError("Cometa conversation_kind does not match DeliveryTarget")
        if str(target.get("peer_id") or "") not in {
            "", delivery_target.scene.scene_id
        }:
            raise ValueError("Cometa peer_id does not match DeliveryTarget")
        if delivery_target.scene.kind == "group" and str(target.get("group_id") or "") not in {
            "", delivery_target.scene.scene_id
        }:
            raise ValueError("Cometa group_id does not match DeliveryTarget")
        return delivery_target

    async def _send_text(
        delivery_target: DeliveryTarget,
        body: str,
        *,
        reply_to: str = "",
        requester: str = "",
    ) -> str | None:
        from cometa.delivery import SenderUnavailable
        from core.transport.outbound import (
            DeliveryStatus,
            OutboundMessage,
            OutboundSegment,
        )
        from stella_project.plugins.bot_main.transport_delivery import (
            send_background_message,
        )

        segments = []
        if reply_to.isdigit():
            segments.append(OutboundSegment.reply(reply_to))
        if requester.isdigit() and delivery_target.scene.kind == "group":
            segments.append(OutboundSegment.at(requester))
        segments.append(OutboundSegment.text_segment(body))
        result = await send_background_message(
            delivery_target, OutboundMessage(tuple(segments))
        )
        if result.status is DeliveryStatus.ACCEPTED:
            return result.message_ids[0] if result.message_ids else None
        if (
            result.status is DeliveryStatus.FAILED
            and result.error_code == "exact_bot_binding_missing"
        ):
            raise SenderUnavailable("exact QQ Bot is not online")
        raise RuntimeError(
            f"outbound notification {result.status.value}: {result.error_code or 'no receipt'}"
        )

    async def send(target: dict, text: str, payload: dict | None = None) -> str | None:
        platform = str(target.get("platform") or "qq")
        if platform == "webchat":
            # The WebChat response is delivered by its existing server stream.
            return "server_emitted"
        if platform != "qq":
            raise ValueError(f"unsupported Cometa notification platform: {platform!r}")
        delivery_target = _target_from_dict(target)
        task_id = str(target.get("task_id") or "")
        reply_to = str(target.get("reply_to_message_id") or "")
        requester = str(target.get("requester_id") or "")
        payload = payload or {}
        full_ref = str(payload.get("full_text_ref") or "")
        full_chars = int(payload.get("full_text_chars") or 0)
        body = text

        if delivery_target.scene.kind == "private":
            if full_ref and 0 < full_chars <= file_above_chars:
                full_path = artifacts_dir / task_id / full_ref
                try:
                    full_text = full_path.read_text(encoding="utf-8").strip()
                except OSError:
                    full_text = ""
                if full_text:
                    body = f"{text.split(chr(10), 1)[0]}\n\n{full_text}"
            elif full_chars > file_above_chars:
                body = (
                    f"{text}\n📄 完整结果约 {full_chars} 字，过长未全文附上；"
                    "可在 WebUI 任务页查看全文。"
                )
            receipt = await _send_text(delivery_target, body, reply_to=reply_to)
            with contextlib.suppress(Exception):
                logger.info(
                    f"📤 [Cometa] 通知已投递到私聊 {delivery_target.scene.scene_id}"
                    f"（回执 {receipt or '无'}）"
                )
            return receipt

        group_id = int(delivery_target.scene.scene_id)
        bot_id = delivery_target.bot.self_id
        is_long = bool(full_ref) and full_chars >= file_above_chars and long_result != "text"
        note = ""
        if is_long:
            path = artifacts_dir / task_id / full_ref
            file_note = f"📄 完整结果已上传为群文件「{full_ref}」（QQ 内点开即渲染）。"
            forward_note = "📜 完整结果已以转发消息发送（点开查看全部）。"
            unavailable_note = (
                "⚠️ 完整结果未能送达（文件与转发均失败），"
                "可在 WebUI 任务页查看或要求重试。"
            )
            missing_note = "⚠️ 完整结果文件缺失（内部错误），可在 WebUI 任务页查看。"
            if path.is_file():
                from cometa.delivery import SenderUnavailable
                from stella_project.plugins.bot_main.transport_delivery import (
                    resolve_background_bot,
                )

                bot = resolve_background_bot(delivery_target.bot)
                if bot is None:
                    raise SenderUnavailable(f"bot {bot_id} 不在线")

                if long_result == "file":
                    try:
                        await bot.call_api(
                            "upload_group_file", group_id=group_id,
                            file=str(path), name=full_ref,
                        )
                    except Exception as upload_err:
                        if upload_err.__class__.__name__ != "ActionFailed":
                            raise RuntimeError(
                                f"upload_group_file result unknown: {type(upload_err).__name__}"
                            ) from upload_err
                        logger.warning(
                            "⚠️ [Cometa] 群文件上传被平台明确拒绝，尝试合并转发"
                        )
                    else:
                        # If the upload succeeded but the cover is ambiguous, do not
                        # attempt another delivery method and duplicate the result.
                        return await _send_text(
                            delivery_target, f"{text}\n{file_note}",
                            reply_to=reply_to, requester=requester,
                        )

                try:
                    full_text = path.read_text(encoding="utf-8")
                    nodes = [
                        {
                            "type": "node",
                            "data": {
                                "uin": bot_id,
                                "name": "Stella",
                                "content": [
                                    {"type": "text", "data": {"text": chunk}}
                                ],
                            },
                        }
                        for chunk in split_markdown(full_text)
                    ][:20]
                    await bot.call_api(
                        "send_group_forward_msg", group_id=group_id, messages=nodes
                    )
                except Exception as forward_err:
                    if forward_err.__class__.__name__ != "ActionFailed":
                        raise RuntimeError(
                            f"send_group_forward_msg result unknown: {type(forward_err).__name__}"
                        ) from forward_err
                    logger.warning(
                        "⚠️ [Cometa] 合并转发被平台明确拒绝，降级纯文本摘要"
                    )
                    note = unavailable_note
                else:
                    # A sent forward followed by an uncertain cover is still unknown;
                    # never send a second fallback message.
                    return await _send_text(
                        delivery_target, f"{text}\n{forward_note}",
                        reply_to=reply_to, requester=requester,
                    )
            else:
                logger.warning(f"⚠️ [Cometa] 完整文本文件缺失（{path}），按纯文本摘要投递")
                note = missing_note

        body = f"{text}\n{note}" if note else text
        receipt = await _send_text(
            delivery_target, body, reply_to=reply_to, requester=requester
        )
        with contextlib.suppress(Exception):
            logger.info(
                f"📤 [Cometa] 通知已投递到群 {group_id}（回执 {receipt or '无'}）"
            )
        return receipt

    return send


async def notification_sender(target: dict, text: str, payload: dict | None = None) -> str | None:
    """模块级直连 Sender（旧接线形态）：无产物目录与投递配置，仅纯文本。

    生产接线请用 :func:`make_notification_sender`（runtime 装配使用）；此兼容入口
    同样拒绝默认 Bot 与不可验证的持久路由。"""
    from cometa.config import DeliveryConfig

    sender = make_notification_sender(Path(), DeliveryConfig(long_result="text"))
    return await sender(target, text, payload)


__all__ = [
    "AckSender",
    "build_origin",
    "deliver_ack",
    "make_notification_sender",
    "notification_sender",
    "split_markdown",
]
