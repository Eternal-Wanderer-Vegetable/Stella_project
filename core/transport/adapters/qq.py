# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Opt-in codecs for the official NoneBot QQ adapter (1.7.3).

Only event-bound passive replies are supported. This module has no startup hook,
matcher, credential lookup, or import-time dependency on the QQ SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from core.transport.capabilities import AdapterCapabilities
from core.transport.message_event import MessageEventV1, MessagePartV1
from core.transport.models import BotRef, SceneRef, UserRef
from core.transport.normalizers import NormalizedEvent, UnsupportedEvent
from core.transport.outbound import (
    AdapterSendResult,
    DeliveryStatus,
    DeliveryTarget,
    OutboundKind,
    OutboundMessage,
)

QQ_ADAPTER = "qq-official"
QQ_PLATFORM_SCOPE = "qq"
QQ_TEXT_SCENES = frozenset({"private", "group", "channel"})
_ADAPTER_NAMES = frozenset({"qq", "nonebotadapterqq"})
_WINDOWS = {
    "C2C_MESSAGE_CREATE": timedelta(minutes=60),
    "GROUP_AT_MESSAGE_CREATE": timedelta(minutes=5),
    "AT_MESSAGE_CREATE": timedelta(minutes=5),
    "DIRECT_MESSAGE_CREATE": timedelta(minutes=5),
}

# QQ active pushes are not enabled. All targets still require a live original
# message event and expire at the platform's documented passive-reply deadline.
QQ_CAPABILITIES = AdapterCapabilities(
    adapter=QQ_ADAPTER,
    platform_scope=QQ_PLATFORM_SCOPE,
    passive_receive=True,
    private=True,
    group=True,
    channel=True,
    thread=False,
    quote=False,
    mention_user=False,
    mention_role=False,
    upload_image=False,
    upload_file=False,
    proactive_send=False,
)


@dataclass(frozen=True, slots=True)
class QQTarget:
    """Exact recipient and source message for a passive QQ reply."""

    route_kind: str
    recipient_id: str
    message_id: str


@dataclass(frozen=True, slots=True)
class _EventRoute:
    scene: SceneRef
    user_id: str
    user_domain: str
    route_kind: str
    recipient_id: str
    event_type: str


@dataclass(frozen=True, slots=True)
class _QQEventHandle:
    """Keep the exact source Bot alongside its process-local event object."""

    event: Any
    bot_handle: Any


class QQNormalizer:
    """Normalize supported event classes from nonebot-adapter-qq 1.7.3."""

    def normalize(
        self, bot: Any, event: Any, *, connection_id: str
    ) -> NormalizedEvent | UnsupportedEvent:
        if not isinstance(connection_id, str) or not connection_id:
            return UnsupportedEvent("connection_id_missing")

        if _adapter_name(bot) not in _ADAPTER_NAMES:
            return UnsupportedEvent("qq_bot_adapter_identity_mismatch")
        self_id = _opaque_id(_get(bot, "self_id"))
        if self_id is None:
            return UnsupportedEvent("qq_bot_identity_missing")

        route = _event_route(event)
        if isinstance(route, UnsupportedEvent):
            return route
        if not _intent_enabled(bot, route.event_type):
            return UnsupportedEvent("qq_required_intent_missing")

        message_id = _opaque_id(_get(event, "id"))
        occurred_at = _event_timestamp(event)
        if message_id is None:
            return UnsupportedEvent("qq_message_id_missing")
        if occurred_at is None:
            return UnsupportedEvent("qq_message_timestamp_invalid")

        parts_result = _message_parts(event)
        if isinstance(parts_result, UnsupportedEvent):
            return parts_result
        parts, text = parts_result
        if not parts:
            return UnsupportedEvent("qq_message_has_no_supported_content")

        bot_ref = BotRef(connection_id, QQ_ADAPTER, QQ_PLATFORM_SCOPE, self_id)
        user_ref = UserRef(route.user_domain, route.user_id, _display_name(_get(event, "author")))
        message_event = MessageEventV1(
            platform_message_id=message_id,
            occurred_at=occurred_at,
            components=parts,
        )
        return NormalizedEvent(
            bot_ref=bot_ref,
            user_ref=user_ref,
            scene_ref=route.scene,
            text=text,
            platform_message_id=message_id,
            sender_display_name=user_ref.display_name or "",
            is_tome=True,
            is_self=False,
            has_image=any(part.kind == "image" for part in parts),
            has_segments=bool(parts),
            raw_event=event,
            bot_handle=bot,
            message_event=message_event,
        )


def qq_delivery_target(event: NormalizedEvent) -> DeliveryTarget:
    """Build a temporary target that can only reply to this exact QQ event."""

    if not isinstance(event, NormalizedEvent):
        raise ValueError("QQ delivery target requires a normalized event")
    if (event.bot_ref.adapter, event.bot_ref.platform_scope) != (
        QQ_ADAPTER,
        QQ_PLATFORM_SCOPE,
    ):
        raise ValueError("QQ normalized event identity mismatch")
    raw_event = event.raw_event
    if event.bot_handle is None:
        raise ValueError("QQ delivery target requires the source Bot handle")
    route = _event_route(raw_event)
    if isinstance(route, UnsupportedEvent) or route.scene != event.scene_ref:
        raise ValueError("QQ source event does not match the normalized scene")
    if event.message_event is None:
        raise ValueError("QQ normalized event is missing its versioned message")
    message_id = _opaque_id(_get(raw_event, "id"))
    occurred_at = _event_timestamp(raw_event)
    if (
        message_id is None
        or message_id != event.message_event.platform_message_id
        or occurred_at is None
        or occurred_at != event.message_event.occurred_at
    ):
        raise ValueError("QQ source event does not match the normalized message")

    expires_at = occurred_at + _WINDOWS[route.event_type]
    return DeliveryTarget(
        bot=event.bot_ref,
        scene=event.scene_ref,
        expires_at_utc=_format_timestamp(expires_at),
        event_handle=_QQEventHandle(raw_event, event.bot_handle),
    )


class QQTargetCodec:
    """Encode only the matching source event and its actual QQ message ID."""

    def encode(self, target: DeliveryTarget, *, bot_handle: Any) -> QQTarget:
        if target.target_codec_version != 1:
            raise ValueError("QQ target codec version is unsupported")
        if (target.bot.adapter, target.bot.platform_scope) != (
            QQ_ADAPTER,
            QQ_PLATFORM_SCOPE,
        ):
            raise ValueError("QQ target identity mismatch")
        if target.routing_parameters:
            raise ValueError("QQ target has unsupported routing parameters")
        if _adapter_name(bot_handle) not in _ADAPTER_NAMES:
            raise ValueError("QQ Bot handle adapter identity mismatch")
        if _opaque_id(_get(bot_handle, "self_id")) != target.bot.self_id:
            raise ValueError("QQ Bot handle self identity mismatch")
        if not isinstance(target.event_handle, _QQEventHandle):
            raise ValueError("QQ passive reply requires its original event")
        if target.event_handle.bot_handle is not bot_handle:
            raise ValueError("QQ target requires the exact source Bot handle")
        if target.is_expired():
            raise ValueError("QQ passive reply window has expired")

        source_event = target.event_handle.event
        route = _event_route(source_event)
        if isinstance(route, UnsupportedEvent) or route.scene != target.scene:
            raise ValueError("QQ source event does not match the exact target")
        if not _intent_enabled(bot_handle, route.event_type):
            raise ValueError("QQ source event intent is no longer enabled")

        message_id = _opaque_id(_get(source_event, "id"))
        occurred_at = _event_timestamp(source_event)
        if message_id is None or occurred_at is None:
            raise ValueError("QQ passive reply source is incomplete")
        expected_expiry = _format_timestamp(occurred_at + _WINDOWS[route.event_type])
        if target.expires_at_utc != expected_expiry:
            raise ValueError("QQ passive reply deadline does not match the source event")

        return QQTarget(route.route_kind, route.recipient_id, message_id)


class QQExporter:
    """Send plain text through the exact SDK Bot using msg_id passive replies."""

    async def send(
        self,
        target: DeliveryTarget,
        message: OutboundMessage,
        *,
        bot_handle: Any,
        capabilities: AdapterCapabilities,
        encoded_target: QQTarget,
    ) -> AdapterSendResult:
        if (target.bot.adapter, target.bot.platform_scope) != (
            QQ_ADAPTER,
            QQ_PLATFORM_SCOPE,
        ):
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="qq_target_identity_mismatch"
            )
        if capabilities.adapter != QQ_ADAPTER or capabilities.platform_scope != QQ_PLATFORM_SCOPE:
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="qq_capability_identity_mismatch"
            )
        try:
            verified_target = QQTargetCodec().encode(target, bot_handle=bot_handle)
        except Exception:
            return AdapterSendResult(
                DeliveryStatus.EXPIRED if target.is_expired() else DeliveryStatus.UNSUPPORTED,
                error_code="qq_target_rejected",
            )
        if verified_target != encoded_target:
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="qq_encoded_target_mismatch"
            )

        text_parts: list[str] = []
        for segment in message.segments:
            if segment.kind is not OutboundKind.TEXT:
                return AdapterSendResult(
                    DeliveryStatus.UNSUPPORTED, error_code="qq_segment_unsupported"
                )
            text_parts.append(segment.text)
        text = "".join(text_parts)
        if not text:
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="qq_empty_text"
            )

        try:
            from nonebot.adapters.qq.message import Message, MessageSegment
        except ImportError:
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="qq_adapter_unavailable"
            )

        # Construct an explicit text segment so model text cannot be reparsed as
        # QQ mention, channel, or other native markup.
        sdk_message = Message([MessageSegment.text(text)])
        route = encoded_target
        if route.route_kind == "channel" and _get(bot_handle, "ready") is not True:
            return AdapterSendResult(
                DeliveryStatus.FAILED, error_code="qq_channel_bot_not_connected"
            )

        try:
            if route.route_kind == "c2c":
                send = _get(bot_handle, "send_to_c2c")
                receipt = await send(
                    route.recipient_id,
                    sdk_message,
                    msg_id=route.message_id,
                    msg_seq=1,
                )
            elif route.route_kind == "group":
                send = _get(bot_handle, "send_to_group")
                receipt = await send(
                    group_openid=route.recipient_id,
                    message=sdk_message,
                    msg_id=route.message_id,
                    msg_seq=1,
                )
            elif route.route_kind == "channel":
                send = _get(bot_handle, "send_to_channel")
                receipt = await send(
                    route.recipient_id,
                    sdk_message,
                    msg_id=route.message_id,
                )
            elif route.route_kind == "direct":
                send = _get(bot_handle, "send_to_dms")
                receipt = await send(
                    route.recipient_id,
                    sdk_message,
                    msg_id=route.message_id,
                )
            else:
                return AdapterSendResult(
                    DeliveryStatus.UNSUPPORTED, error_code="qq_route_unsupported"
                )
        except TimeoutError:
            return AdapterSendResult(
                DeliveryStatus.UNKNOWN, error_code="qq_send_timeout"
            )
        except Exception as exc:
            if _is_qq_action_failed(exc):
                return AdapterSendResult(
                    DeliveryStatus.FAILED, error_code="qq_action_failed"
                )
            # The adapter wraps network failures without a stable rejection
            # receipt. Preserve ambiguity and never replay an UNKNOWN result.
            return AdapterSendResult(
                DeliveryStatus.UNKNOWN, error_code="qq_send_outcome_unknown"
            )

        receipt_id = _receipt_id(receipt)
        if receipt_id is None:
            return AdapterSendResult(
                DeliveryStatus.UNKNOWN, error_code="qq_receipt_id_missing"
            )
        return AdapterSendResult(DeliveryStatus.ACCEPTED, (receipt_id,))


def register_qq_transport(registry: Any) -> None:
    """Explicitly register QQ codecs; this function is never called by default."""

    registry.register_exporter(
        QQ_ADAPTER,
        QQExporter(),
        QQ_CAPABILITIES,
        target_codec=QQTargetCodec(),
    )


def _event_route(event: Any) -> _EventRoute | UnsupportedEvent:
    event_type = _event_type(event)
    if event_type not in _WINDOWS:
        return UnsupportedEvent("qq_event_type_unsupported")
    get_type = _get(event, "get_type")
    try:
        if not callable(get_type) or get_type() != "message":
            return UnsupportedEvent("qq_event_kind_unsupported")
    except Exception:
        return UnsupportedEvent("qq_event_kind_unavailable")

    author = _get(event, "author")
    if event_type == "C2C_MESSAGE_CREATE":
        user_id = _opaque_id(_get(author, "user_openid"))
        if user_id is None:
            return UnsupportedEvent("qq_c2c_user_identity_missing")
        return _EventRoute(SceneRef("private", user_id), user_id, "qq-official:c2c-user", "c2c", user_id, event_type)
    if event_type == "GROUP_AT_MESSAGE_CREATE":
        group_id = _opaque_id(_get(event, "group_openid"))
        user_id = _opaque_id(_get(author, "member_openid"))
        if group_id is None or user_id is None:
            return UnsupportedEvent("qq_group_identity_missing")
        return _EventRoute(SceneRef("group", group_id), user_id, "qq-official:group-member", "group", group_id, event_type)
    if event_type == "AT_MESSAGE_CREATE":
        guild_id = _opaque_id(_get(event, "guild_id"))
        channel_id = _opaque_id(_get(event, "channel_id"))
        user_id = _opaque_id(_get(author, "id"))
        if guild_id is None or channel_id is None or user_id is None:
            return UnsupportedEvent("qq_channel_identity_missing")
        scene = SceneRef("channel", channel_id, parent_path=(guild_id,))
        return _EventRoute(scene, user_id, "qq-official:guild-user", "channel", channel_id, event_type)

    guild_id = _opaque_id(_get(event, "guild_id"))
    channel_id = _opaque_id(_get(event, "channel_id"))
    user_id = _opaque_id(_get(author, "id"))
    if guild_id is None or channel_id is None or user_id is None:
        return UnsupportedEvent("qq_direct_message_identity_missing")
    # The DM channel is the conversation identity. Sending uses its parent guild.
    scene = SceneRef("private", channel_id, parent_path=(guild_id,))
    return _EventRoute(scene, user_id, "qq-official:guild-user", "direct", guild_id, event_type)


def _message_parts(event: Any) -> tuple[tuple[MessagePartV1, ...], str] | UnsupportedEvent:
    get_message = _get(event, "get_message")
    try:
        message = get_message() if callable(get_message) else None
    except Exception:
        return UnsupportedEvent("qq_message_decode_failed")
    if message is None:
        return UnsupportedEvent("qq_message_missing")

    parts: list[MessagePartV1] = []
    text: list[str] = []
    try:
        segments = tuple(message)
    except TypeError:
        return UnsupportedEvent("qq_message_components_invalid")
    for segment in segments:
        kind = _get(segment, "type")
        data = _get(segment, "data")
        if kind == "text":
            value = _get(data, "text")
            if not isinstance(value, str):
                return UnsupportedEvent("qq_text_component_invalid")
            if value:
                text.append(value)
                parts.append(MessagePartV1("text", text=value))
        elif kind in {"image", "audio", "video", "file", "file_image", "file_audio", "file_video", "file_file"}:
            # Media URLs from SDK segments are short lived and are never stored.
            continue
        else:
            parts.append(MessagePartV1("unsupported", text=str(kind or "component")))

    attachments = _get(event, "attachments") or ()
    if not isinstance(attachments, (tuple, list)):
        return UnsupportedEvent("qq_attachments_invalid")
    for attachment in attachments:
        mime = _safe_mime(_get(attachment, "content_type"))
        if mime is None:
            parts.append(MessagePartV1("unsupported", text="attachment"))
            continue
        media_kind = mime.partition("/")[0]
        if media_kind not in {"image", "audio", "video"}:
            media_kind = "file"
        size = _get(attachment, "size")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            size = None
        filename = _safe_display_name(_get(attachment, "filename"))
        parts.append(
            MessagePartV1(
                media_kind,
                display_name=filename,
                mime_type=mime,
                size_bytes=size,
            )
        )
    return tuple(parts), "".join(text)


def _intent_enabled(bot: Any, event_type: str) -> bool:
    bot_info = _get(bot, "bot_info")
    intents = _get(bot_info, "intent")
    intent_name = {
        "C2C_MESSAGE_CREATE": "c2c_group_at_messages",
        "GROUP_AT_MESSAGE_CREATE": "c2c_group_at_messages",
        "AT_MESSAGE_CREATE": "at_messages",
        "DIRECT_MESSAGE_CREATE": "direct_message",
    }.get(event_type)
    return intent_name is not None and _get(intents, intent_name) is True


def _event_type(event: Any) -> str:
    value = _get(event, "__type__")
    enum_value = _get(value, "value")
    if isinstance(enum_value, str):
        value = enum_value
    return value if isinstance(value, str) else ""


def _event_timestamp(event: Any) -> datetime | None:
    value = _get(event, "timestamp")
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _opaque_id(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    result = str(value)
    if not result or len(result) > 2048 or any(
        ord(char) < 0x20 or ord(char) == 0x7F or 0xD800 <= ord(char) <= 0xDFFF
        for char in result
    ):
        return None
    return result


def _adapter_name(bot: Any) -> str:
    getter = _get(_get(bot, "adapter"), "get_name")
    try:
        name = getter() if callable(getter) else ""
    except Exception:
        return ""
    if not isinstance(name, str):
        return ""
    return "".join(char.lower() for char in name if char.isalnum())


def _display_name(author: Any) -> str | None:
    for field in ("username", "nick"):
        value = _get(author, field)
        if isinstance(value, str) and value.strip():
            return _safe_display_name(value)
    return None


def _safe_display_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 256 or any(
        ord(char) < 0x20 or ord(char) == 0x7F or 0xD800 <= ord(char) <= 0xDFFF
        for char in value
    ):
        return None
    return value


def _safe_mime(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    if "/" not in value or len(value) > 255 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    major, _separator, minor = value.partition("/")
    if not major or not minor or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789.+-" for char in major + minor):
        return None
    return value


def _receipt_id(receipt: Any) -> str | None:
    value = _opaque_id(_get(receipt, "id"))
    return value if value is not None else None


def _is_qq_action_failed(exc: Exception) -> bool:
    try:
        from nonebot.adapters.qq.exception import ActionFailed
    except ImportError:
        return False
    return isinstance(exc, ActionFailed)


def _get(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    try:
        return getattr(value, name, None)
    except Exception:
        return None


__all__ = [
    "QQ_ADAPTER",
    "QQ_CAPABILITIES",
    "QQExporter",
    "QQNormalizer",
    "QQTarget",
    "QQTargetCodec",
    "qq_delivery_target",
    "register_qq_transport",
]
