# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""cometa 的 QQ 桥接：可信 Origin、ack 认领发送、通知 Sender（方案 §6.5/§6.11）。

职责边界：桥只做「平台 ↔ cometa 通知协议」的翻译——构造 Origin（来自
真实 OneBot 事件，**不由模型生成**）、认领并发送受理确认、把通知投到原
会话。cometa 内核对 QQ 零依赖；桥对任务库只有经 service/store CAS 的短操作。

ack 双通道互斥（§6.5）：入口（本桥 ``deliver_ack``）与后台投递泵对同一条
ack 通知做 ``pending → sending`` 的 CAS 竞争，谁先认领谁发送，另一方放弃
——绝不出现「当前聊天发送一次 ack，后台又发送一次」。
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable

from nonebot import logger

AckSender = Callable[[str], Awaitable[str | None]]


def build_origin(event, bot, *, instance_id: str) -> dict | None:
    """从真实群消息事件构造可信 Origin dict（方案 §6.1）。

    只在 handle_chat（@ 触达）路径调用；被动摄入与主动发言路径不会构造
    Origin——这是「委派只由用户显式请求触发」的入口保证（§6.4.1）。
    """
    if not instance_id:
        return None
    return {
        "instance_id": instance_id,
        "platform": "qq",
        "bot_id": str(getattr(event, "self_id", "") or getattr(bot, "self_id", "")),
        "conversation_id": str(event.group_id),
        "requester_id": str(event.user_id),
        "source_request_id": f"msg-{event.message_id}",
        "reply_to_message_id": str(event.message_id),
        "conversation_generation": 1,
    }


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


async def notification_sender(target: dict, text: str) -> str | None:
    """后台投递泵的 QQ/WebChat Sender（cometa.delivery.NotificationSender 协议）。

    - bot 不在线 → 抛 SenderUnavailable（发送**前**失败，泵可退避重试）；
    - 调用异常/超时语义由泵统一判 delivery_unknown；
    - WebChat：结果真源是任务中心/SSE 订阅，直接返回 ``server_emitted``
      占位回执——只声称服务端已可查询，不声称用户已阅读（§6.5）；
    - QQ：引用原消息 + 文本（CQ 码按纯文本处理，Agent 文字不解释为控制码）。
    """
    from nonebot import get_bot
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    from cometa.delivery import SenderUnavailable

    platform = str(target.get("platform") or "qq")
    if platform != "qq":
        # WebChat 没有后台推送通道；结果留在任务中心（WebUI 可查/可订阅）
        return "server_emitted"
    group_id = int(target.get("group_id") or 0)
    bot_id = str(target.get("bot_id") or "")
    reply_to = str(target.get("reply_to_message_id") or "")
    requester = str(target.get("requester_id") or "")
    try:
        bot = get_bot(bot_id or None)
    except Exception as e:
        raise SenderUnavailable(f"bot {bot_id or '<default>'} 不在线") from e
    segments: list = []
    if reply_to.isdigit():
        segments.append(MessageSegment.reply(int(reply_to)))
    if requester.isdigit():
        segments.append(MessageSegment.at(int(requester)))
    segments.append(MessageSegment.text(text))
    try:
        resp = await bot.send_group_msg(group_id=group_id, message=Message(segments))
    except Exception as e:
        raise RuntimeError(f"send_group_msg failed: {type(e).__name__}") from e
    receipt = ""
    if isinstance(resp, dict):
        receipt = str(resp.get("message_id") or "")
    elif resp is not None:
        receipt = str(getattr(resp, "message_id", "") or "")
    with contextlib.suppress(Exception):
        logger.info(f"📤 [Cometa] 通知已投递到群 {group_id}（回执 {receipt or '无'}）")
    return receipt or None


__all__ = ["AckSender", "build_origin", "deliver_ack", "notification_sender"]
