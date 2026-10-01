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
消息兜底，纯文本摘要垫底；任何一级失败自动降级，封面文本始终报告结果并
如实说明完整内容是否送达。
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from pathlib import Path

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

    每一级先于发送探测 bot 在线（离线 → SenderUnavailable → 泵退避重试，
    那时尚无任何调用发生）。
    """
    artifacts_dir = Path(artifacts_dir)
    long_result = getattr(delivery_config, "long_result", "file")
    file_above_chars = int(getattr(delivery_config, "file_above_chars", 500))

    async def send(target: dict, text: str, payload: dict | None = None) -> str | None:
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
        task_id = str(target.get("task_id") or "")
        try:
            bot = get_bot(bot_id or None)
        except Exception as e:
            raise SenderUnavailable(f"bot {bot_id or '<default>'} 不在线") from e

        def cover(extra_note: str = "") -> Message:
            segments: list = []
            if reply_to.isdigit():
                segments.append(MessageSegment.reply(int(reply_to)))
            if requester.isdigit():
                segments.append(MessageSegment.at(int(requester)))
            body = text if not extra_note else f"{text}\n{extra_note}"
            segments.append(MessageSegment.text(body))
            return Message(segments)

        async def send_cover(extra_note: str = "") -> str | None:
            resp = await bot.send_group_msg(group_id=group_id, message=cover(extra_note))
            receipt = ""
            if isinstance(resp, dict):
                receipt = str(resp.get("message_id") or "")
            elif resp is not None:
                receipt = str(getattr(resp, "message_id", "") or "")
            return receipt or None

        # ── 长结果投递链（§6.12）─────────────────────────
        payload = payload or {}
        full_ref = str(payload.get("full_text_ref") or "")
        full_chars = int(payload.get("full_text_chars") or 0)
        is_long = (
            bool(full_ref)
            and full_chars >= file_above_chars
            and long_result != "text"
        )
        note = ""
        if is_long:
            path = artifacts_dir / task_id / full_ref
            file_note = f"📄 完整结果已上传为群文件「{full_ref}」（QQ 内点开即渲染）。"
            forward_note = "📜 完整结果已以转发消息发送（点开查看全部）。"
            unavailable_note = (
                "⚠️ 完整结果未能送达（文件与转发均失败），"
                "可在 WebUI 任务页查看或要求重试。"
            )
            missing_note = (
                "⚠️ 完整结果文件缺失（内部错误），可在 WebUI 任务页查看。"
            )
            if path.is_file():
                if long_result == "file":
                    try:
                        await bot.call_api(
                            "upload_group_file",
                            group_id=group_id,
                            file=str(path),
                            name=full_ref,
                        )
                        receipt = await send_cover(file_note)
                        with contextlib.suppress(Exception):
                            logger.info(
                                f"📤 [Cometa] 长结果已作为文件投递到群 {group_id}: {full_ref}"
                            )
                        return receipt
                    except Exception as upload_err:
                        with contextlib.suppress(Exception):
                            logger.warning(
                                f"⚠️ [Cometa] 群文件上传失败，降级合并转发: {upload_err!r}"
                            )
                try:
                    full_text = path.read_text(encoding="utf-8")
                    nodes = [
                        {
                            "type": "node",
                            "data": {
                                "uin": bot_id or str(getattr(bot, "self_id", "")),
                                "name": "Stella",
                                "content": [
                                    {"type": "text", "data": {"text": chunk}}
                                ],
                            },
                        }
                        for chunk in split_markdown(full_text)
                    ][:20]  # 合并转发 node 数上限（QQ 限制约 200，保守 20）
                    await bot.call_api(
                        "send_group_forward_msg", group_id=group_id, messages=nodes
                    )
                    receipt = await send_cover(forward_note)
                    with contextlib.suppress(Exception):
                        logger.info(
                            f"📤 [Cometa] 长结果已合并转发投递到群 {group_id}（{len(nodes)} 段）"
                        )
                    return receipt
                except Exception as forward_err:
                    with contextlib.suppress(Exception):
                        logger.warning(
                            "⚠️ [Cometa] 合并转发也失败，降级纯文本摘要: "
                            f"{forward_err!r}"
                        )
                    note = unavailable_note
            else:
                # §6.12：产物未送达时文本仍报告结果，并如实说明
                logger.warning(
                    f"⚠️ [Cometa] 完整文本文件缺失（{path}），按纯文本摘要投递"
                )
                note = missing_note

        # ── 纯文本（短结果 / 长结果兜底）──────────────────
        segments: list = []
        if reply_to.isdigit():
            segments.append(MessageSegment.reply(int(reply_to)))
        if requester.isdigit():
            segments.append(MessageSegment.at(int(requester)))
        body = f"{text}\n{note}" if note else text
        segments.append(MessageSegment.text(body))
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

    return send


async def notification_sender(target: dict, text: str, payload: dict | None = None) -> str | None:
    """模块级直连 Sender（旧接线形态）：无产物目录与投递配置，仅纯文本。

    生产接线请用 :func:`make_notification_sender`（runtime 装配使用）。"""
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


__all__ = [
    "AckSender",
    "build_origin",
    "deliver_ack",
    "make_notification_sender",
    "notification_sender",
    "split_markdown",
]
