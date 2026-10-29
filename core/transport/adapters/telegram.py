# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Opt-in Telegram transport codecs for the locked NoneBot adapter.

The module does not import the platform package at import time. Connection
owners explicitly install the normalizer in ingress and register the exporter;
it is never activated as a matcher or by constructing OutboundService.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from core.transport.capabilities import AdapterCapabilities
from core.transport.keys import conversation_key_v2
from core.transport.media import MediaSource
from core.transport.message_event import (
    MessageEventV1,
    MessagePartV1,
    MessageRelationV1,
)
from core.transport.models import BotRef, SceneRef, UserRef
from core.transport.normalizers import NormalizedEvent, UnsupportedEvent
from core.transport.outbound import (
    AdapterSendResult,
    DeliveryStatus,
    DeliveryTarget,
    OutboundKind,
    OutboundMessage,
)

_INTEGER_ID = re.compile(r"^(?:0|-[1-9][0-9]*|[1-9][0-9]*)$")
_MAX_TELEGRAM_INTEGER = (1 << 63) - 1

# OutboundService splits by Python code points. 2048 therefore stays within
# Telegram's 4096 UTF-16-code-unit text limit even for all-astral text.
TELEGRAM_CAPABILITIES = AdapterCapabilities(
    adapter="telegram",
    platform_scope="telegram",
    passive_receive=True,
    private=True,
    group=True,
    thread=True,
    quote=True,
    upload_image=True,
    upload_file=True,
    proactive_send=False,
    max_text_length=2048,
)


@dataclass(frozen=True, slots=True)
class TelegramTarget:
    """Exact numeric chat and optional forum/private-forum topic route."""

    chat_id: int
    message_thread_id: int | None = None


class TelegramNormalizer:
    """Normalize message events emitted by nonebot-adapter-telegram."""

    def normalize(
        self, bot: Any, event: Any, *, connection_id: str
    ) -> NormalizedEvent | UnsupportedEvent:
        if not isinstance(connection_id, str) or not connection_id:
            return UnsupportedEvent("connection_id_missing")

        adapter = _get(bot, "adapter")
        get_name = _get(adapter, "get_name")
        try:
            adapter_name = get_name() if callable(get_name) else ""
        except Exception:
            return UnsupportedEvent("bot_adapter_identity_unavailable")
        if _adapter_key(adapter_name) != "telegram":
            return UnsupportedEvent("bot_adapter_identity_mismatch")

        self_id = _string_id(_get(bot, "self_id"))
        parsed_self_id = _canonical_int(self_id, allow_negative=False)
        if parsed_self_id is None or parsed_self_id == 0:
            return UnsupportedEvent("telegram_bot_identity_invalid")
        self_id = str(parsed_self_id)
        chat = _get(event, "chat")
        chat_type = _get(chat, "type")
        chat_id = _decimal_id(_get(chat, "id"), allow_negative=True)
        if not self_id or chat_id is None or chat_id == 0:
            return UnsupportedEvent("bot_or_chat_identity_missing")

        if _has_direct_messages_topic(event):
            return UnsupportedEvent("direct_messages_topic_unsupported_by_locked_adapter")

        if chat_type == "private":
            scene_kind = "private"
        elif chat_type in {"group", "supergroup"}:
            scene_kind = "group"
        else:
            return UnsupportedEvent("telegram_chat_type_unsupported")

        sender = _get(event, "from_")
        user_id = _decimal_id(_get(sender, "id"), allow_negative=False)
        if user_id is None or user_id == 0:
            # Anonymous administrators and channel senders are not user identities.
            return UnsupportedEvent("telegram_sender_identity_missing")

        message_id = _decimal_id(_get(event, "message_id"), allow_negative=False)
        if message_id is None or message_id == 0:
            # Bot API message_id=0 is explicitly ephemeral and cannot be replied to.
            return UnsupportedEvent("telegram_message_id_unavailable")

        event_type_getter = _get(event, "get_type")
        try:
            event_type = event_type_getter() if callable(event_type_getter) else ""
        except Exception:
            event_type = ""
        if event_type not in {"message", "edit_message"}:
            return UnsupportedEvent("telegram_event_type_unsupported")

        raw_message = _raw_telegram_message(event)
        thread_value = _first_present(
            _get(event, "message_thread_id"),
            _get(raw_message, "message_thread_id"),
        )
        thread_id: str | None = None
        if thread_value is not None:
            parsed_thread = _decimal_id(thread_value, allow_negative=False)
            if parsed_thread is None or parsed_thread == 0:
                return UnsupportedEvent("telegram_thread_identity_invalid")
            thread_id = str(parsed_thread)

        bot_ref = BotRef(connection_id, "telegram", "telegram", self_id)
        scene_ref = SceneRef(scene_kind, str(chat_id), thread_id=thread_id)
        user_ref = UserRef(
            "telegram:user",
            str(user_id),
            _display_name(sender),
        )

        parts, text, has_image = _message_parts(event, raw_message)
        occurred_at = _event_time(event, event_type)
        if occurred_at is None:
            return UnsupportedEvent("telegram_event_timestamp_invalid")

        relations: tuple[MessageRelationV1, ...] = ()
        reply = _first_present(
            _get(event, "reply_to_message"),
            _get(raw_message, "reply_to_message"),
        )
        reply_id = _decimal_id(_get(reply, "message_id"), allow_negative=False)
        if reply_id is not None and reply_id > 0:
            relations = (
                MessageRelationV1(
                    kind="reply",
                    target_message_id=str(reply_id),
                    target_connection_id=connection_id,
                    target_conversation_key=conversation_key_v2(bot_ref, scene_ref),
                    resolved=False,
                ),
            )

        revision: str | None = None
        if event_type == "edit_message":
            edit_date = _decimal_id(_get(event, "edit_date"), allow_negative=False)
            if edit_date is not None and edit_date > 0:
                revision = str(edit_date)

        normalized_message = MessageEventV1(
            platform_message_id=str(message_id),
            occurred_at=occurred_at,
            components=parts,
            relations=relations,
            event_kind="edit" if event_type == "edit_message" else "create",
            platform_revision_id=revision,
        )

        is_tome_getter = _get(event, "is_tome")
        try:
            is_tome = bool(is_tome_getter()) if callable(is_tome_getter) else False
        except Exception:
            is_tome = False
        if scene_kind == "private":
            is_tome = True

        display_name = user_ref.display_name or ""
        return NormalizedEvent(
            bot_ref=bot_ref,
            user_ref=user_ref,
            scene_ref=scene_ref,
            text=text,
            platform_message_id=str(message_id),
            sender_display_name=display_name,
            is_tome=is_tome,
            is_self=str(user_id) == self_id,
            has_image=has_image,
            has_segments=bool(parts),
            raw_event=event,
            bot_handle=bot,
            message_event=normalized_message,
        )


class TelegramTargetCodec:
    """Encode only trusted Telegram chat IDs and topic IDs."""

    def encode(self, target: DeliveryTarget, *, bot_handle: Any) -> TelegramTarget:
        if target.target_codec_version != 1:
            raise ValueError("Telegram target codec version is unsupported")
        if target.bot.adapter != "telegram" or target.bot.platform_scope != "telegram":
            raise ValueError("Telegram target identity mismatch")
        if target.routing_parameters:
            raise ValueError("Telegram target has unsupported routing parameters")
        if target.scene.kind not in {"private", "group"} or target.scene.parent_path:
            raise ValueError("Telegram target must be a private or group chat")
        adapter = _get(_get(bot_handle, "adapter"), "get_name")
        try:
            runtime_name = adapter() if callable(adapter) else ""
        except Exception as exc:
            raise ValueError("Telegram Bot adapter identity is unavailable") from exc
        if _adapter_key(runtime_name) != "telegram":
            raise ValueError("Telegram Bot handle identity mismatch")
        if _string_id(_get(bot_handle, "self_id")) != target.bot.self_id:
            raise ValueError("Telegram Bot handle self identity mismatch")

        chat_id = _canonical_int(target.scene.scene_id, allow_negative=True)
        if chat_id is None or chat_id == 0:
            raise ValueError("Telegram chat ID is invalid")
        if (target.scene.kind == "private" and chat_id < 0) or (
            target.scene.kind == "group" and chat_id > 0
        ):
            raise ValueError("Telegram chat ID sign does not match the trusted scene kind")
        thread_id = None
        if target.scene.thread_id is not None:
            thread_id = _canonical_int(target.scene.thread_id, allow_negative=False)
            if thread_id is None or thread_id == 0:
                raise ValueError("Telegram topic ID is invalid")
        return TelegramTarget(chat_id=chat_id, message_thread_id=thread_id)


class TelegramExporter:
    """Send transport-neutral parts through the exact Telegram Bot handle."""

    async def send(
        self,
        target: DeliveryTarget,
        message: OutboundMessage,
        *,
        bot_handle: Any,
        capabilities: AdapterCapabilities,
        encoded_target: TelegramTarget,
    ) -> AdapterSendResult:
        del target, capabilities
        try:
            from nonebot.adapters.telegram.message import Entity, File, Message, Reply
        except ImportError:
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="telegram_adapter_unavailable"
            )

        segments: list[Any] = []
        try:
            for segment in message.segments:
                if segment.kind is OutboundKind.TEXT:
                    if segment.text:
                        segments.append(Entity.text(segment.text))
                elif segment.kind is OutboundKind.IMAGE:
                    assert segment.media is not None
                    segments.append(File.photo(_telegram_file_source(segment.media)))
                elif segment.kind is OutboundKind.FILE:
                    assert segment.media is not None
                    segments.append(File.document(_telegram_file_source(segment.media)))
                elif segment.kind is OutboundKind.REPLY:
                    reply_id = _canonical_int(segment.target_id, allow_negative=False)
                    if reply_id is None or reply_id == 0:
                        return AdapterSendResult(
                            DeliveryStatus.UNSUPPORTED,
                            error_code="telegram_reply_id_invalid",
                        )
                    segments.append(
                        Reply.reply(reply_id, chat_id=encoded_target.chat_id)
                    )
                elif segment.kind is OutboundKind.AT:
                    return AdapterSendResult(
                        DeliveryStatus.UNSUPPORTED,
                        error_code="telegram_user_mention_requires_username_or_user_object",
                    )
                else:
                    return AdapterSendResult(
                        DeliveryStatus.UNSUPPORTED,
                        error_code="telegram_segment_unsupported",
                    )
        except (ValueError, OSError, binascii.Error):
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="telegram_media_source_invalid"
            )

        if not segments:
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="empty_after_export"
            )
        send_to = _get(bot_handle, "send_to")
        if not callable(send_to):
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="telegram_send_api_unavailable"
            )

        try:
            receipt = await send_to(
                encoded_target.chat_id,
                Message(segments),
                message_thread_id=encoded_target.message_thread_id,
            )
        except TimeoutError:
            return AdapterSendResult(
                DeliveryStatus.UNKNOWN, error_code="telegram_send_timeout"
            )
        except Exception as exc:
            if _is_telegram_action_failed(exc):
                return AdapterSendResult(
                    DeliveryStatus.FAILED, error_code="telegram_action_failed"
                )
            # The locked adapter wraps HTTP/network failures without a stable
            # not-accepted receipt; do not retry or fabricate a failure result.
            return AdapterSendResult(
                DeliveryStatus.UNKNOWN, error_code="telegram_send_outcome_unknown"
            )

        return AdapterSendResult(
            DeliveryStatus.ACCEPTED,
            tuple(_receipt_ids(receipt)),
        )


def register_telegram_transport(registry: Any) -> None:
    """Explicitly register Telegram codecs; never called by default wiring."""
    registry.register_exporter(
        "telegram",
        TelegramExporter(),
        TELEGRAM_CAPABILITIES,
        target_codec=TelegramTargetCodec(),
    )


def _get(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _string_id(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    return value if isinstance(value, str) else ""


def _decimal_id(value: Any, *, allow_negative: bool) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value == 0 and not allow_negative:
        return 0
    if not allow_negative and value < 0:
        return None
    if value < -_MAX_TELEGRAM_INTEGER or value > _MAX_TELEGRAM_INTEGER:
        return None
    return value


def _canonical_int(value: Any, *, allow_negative: bool) -> int | None:
    if not isinstance(value, str) or not _INTEGER_ID.fullmatch(value):
        return None
    try:
        result = int(value)
    except ValueError:
        return None
    if str(result) != value:
        return None
    if not allow_negative and result < 0:
        return None
    if result < -_MAX_TELEGRAM_INTEGER or result > _MAX_TELEGRAM_INTEGER:
        return None
    return result


def _adapter_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(char.lower() for char in value if char.isalnum())


def _display_name(sender: Any) -> str | None:
    values = [
        _get(sender, "first_name"),
        _get(sender, "last_name"),
    ]
    name = " ".join(value.strip() for value in values if isinstance(value, str) and value.strip())
    return name or None


def _raw_telegram_message(event: Any) -> Any:
    update = _get(event, "telegram_model")
    for name in ("message", "edited_message"):
        message = _get(update, name)
        if message is not None:
            return message
    return None


def _has_direct_messages_topic(event: Any) -> bool:
    raw = _raw_telegram_message(event)
    for value in (event, raw):
        if _get(value, "direct_messages_topic_id") is not None:
            return True
        topic = _get(value, "direct_messages_topic")
        if topic is not None:
            return True
    return False


def _event_time(event: Any, event_type: str) -> datetime | None:
    value = _get(event, "edit_date") if event_type == "edit_message" else None
    if value is None:
        value = _get(event, "date")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _message_parts(event: Any, raw_message: Any) -> tuple[tuple[MessagePartV1, ...], str, bool]:
    getter = _get(event, "get_message")
    try:
        message = getter() if callable(getter) else _get(event, "message")
        if message is None or isinstance(message, (str, bytes)):
            return (), "", False
        segments = tuple(message)
    except Exception:
        return (), "", False

    parts: list[MessagePartV1] = []
    text_parts: list[str] = []
    has_image = False
    for segment in segments:
        segment_type = _get(segment, "type")
        if not isinstance(segment_type, str):
            segment_type = ""
        data = _get(segment, "data")
        if not isinstance(data, dict):
            data = {}
        is_text = _get(segment, "is_text")
        try:
            text_like = bool(is_text()) if callable(is_text) else segment_type == "text"
        except Exception:
            text_like = segment_type == "text"
        if text_like:
            value = data.get("text")
            if isinstance(value, str):
                parts.append(MessagePartV1("text", text=value))
                text_parts.append(value)
            continue

        kind = {
            "photo": "image",
            "audio": "audio",
            "voice": "audio",
            "video": "video",
            "animation": "video",
            "video_note": "video",
            "document": "file",
        }.get(segment_type)
        if kind is None:
            parts.append(MessagePartV1("unsupported"))
            continue
        has_image = has_image or kind == "image"
        mime_type, size_bytes = _media_metadata(raw_message, segment_type)
        parts.append(
            MessagePartV1(kind, mime_type=mime_type, size_bytes=size_bytes)
        )
    return tuple(parts), "".join(text_parts), has_image


def _media_metadata(raw_message: Any, segment_type: str) -> tuple[str, int | None]:
    model_field = {
        "photo": "photo",
        "audio": "audio",
        "voice": "voice",
        "video": "video",
        "animation": "animation",
        "video_note": "video_note",
        "document": "document",
    }[segment_type]
    value = _get(raw_message, model_field)
    if isinstance(value, (tuple, list)):
        value = value[-1] if value else None
    mime_type = _get(value, "mime_type")
    if not isinstance(mime_type, str) or not mime_type:
        mime_type = {
            "photo": "image/telegram",
            "audio": "audio/telegram",
            "voice": "audio/telegram",
            "video": "video/telegram",
            "animation": "video/telegram",
            "video_note": "video/telegram",
            "document": "application/telegram",
        }[segment_type]
    size = _get(value, "file_size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        size = None
    return mime_type, size


def _telegram_file_source(media: MediaSource) -> str | bytes | tuple[str, bytes]:
    source = media.uri
    parsed = urlsplit(source)
    if parsed.scheme in {"http", "https"}:
        return source
    if parsed.scheme == "file":
        return url2pathname(unquote(parsed.path))
    if parsed.scheme == "data":
        header, separator, body = source.partition(",")
        if not separator or ";base64" not in header:
            raise ValueError("Telegram only accepts base64 data URIs")
        try:
            return base64.b64decode(body, validate=True)
        except binascii.Error as exc:
            raise ValueError("invalid media data URI") from exc
    if parsed.scheme == "base64":
        try:
            return base64.b64decode(unquote(parsed.path or parsed.netloc), validate=True)
        except binascii.Error as exc:
            raise ValueError("invalid base64 media URI") from exc
    if parsed.scheme:
        raise ValueError("unsupported Telegram media URI scheme")
    return source


def _receipt_ids(receipt: Any) -> list[str]:
    values = receipt if isinstance(receipt, (tuple, list)) else (receipt,)
    result: list[str] = []
    for value in values:
        message_id = _get(value, "message_id")
        if isinstance(message_id, int) and not isinstance(message_id, bool) and message_id > 0:
            text = str(message_id)
            if text not in result:
                result.append(text)
    return result


def _is_telegram_action_failed(exc: Exception) -> bool:
    cls = type(exc)
    return cls.__name__ == "ActionFailed" and cls.__module__.startswith(
        "nonebot.adapters.telegram"
    )


__all__ = [
    "TELEGRAM_CAPABILITIES",
    "TelegramExporter",
    "TelegramNormalizer",
    "TelegramTarget",
    "TelegramTargetCodec",
    "register_telegram_transport",
]
