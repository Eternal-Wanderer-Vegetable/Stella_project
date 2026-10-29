# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Opt-in Discord transport codecs for the lock-pinned NoneBot adapter.

The module does not import the platform package at import time. Guild and DM
events require a caller-supplied channel resolver because the locked gateway
message models carry channel IDs but do not carry the channel type. No matcher,
Bot connection, permission grant, or startup registration is installed here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.transport.capabilities import AdapterCapabilities
from core.transport.keys import conversation_key_v2
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

_SNOWFLAKE = re.compile(r"^[1-9][0-9]*$")
_DISCORD_ADAPTER_KEYS = frozenset({"discord", "nonebotadapterdiscord"})
DISCORD_MAX_TEXT_LENGTH = 1900

# Discord's default MESSAGE_CONTENT intent is disabled. The normalizer checks
# configured intents per event; this static flag therefore does not certify
# unrestricted passive guild reception. Replying remains event scoped and
# proactive output, mentions, and uploads stay disabled.
DISCORD_CAPABILITIES = AdapterCapabilities(
    adapter="discord",
    platform_scope="discord",
    passive_receive=False,
    private=True,
    channel=True,
    thread=True,
    quote=True,
    mention_user=False,
    mention_role=False,
    upload_image=False,
    upload_file=False,
    proactive_send=False,
    max_text_length=DISCORD_MAX_TEXT_LENGTH,
)


@dataclass(frozen=True, slots=True)
class DiscordTarget:
    """The exact Discord channel ID; thread IDs are channel IDs too."""

    channel_id: str
    guild_id: str | None
    scene_kind: str


ChannelResolver = Callable[[Any, str], Any | None]


class DiscordNormalizer:
    """Normalize locked Discord message events using trusted channel metadata."""

    def __init__(self, channel_resolver: ChannelResolver | None = None) -> None:
        self._channel_resolver = channel_resolver

    def normalize(
        self, bot: Any, event: Any, *, connection_id: str
    ) -> NormalizedEvent | UnsupportedEvent:
        if not isinstance(connection_id, str) or not connection_id:
            return UnsupportedEvent("connection_id_missing")

        adapter = _get(_get(bot, "adapter"), "get_name")
        try:
            adapter_name = adapter() if callable(adapter) else ""
        except Exception:
            return UnsupportedEvent("bot_adapter_identity_unavailable")
        if _adapter_key(adapter_name) not in _DISCORD_ADAPTER_KEYS:
            return UnsupportedEvent("bot_adapter_identity_mismatch")

        self_id = _snowflake(_get(bot, "self_id"))
        if self_id is None:
            return UnsupportedEvent("discord_bot_identity_invalid")

        event_type = _event_type(event)
        if event_type not in {"MESSAGE_CREATE", "MESSAGE_UPDATE"}:
            return UnsupportedEvent("discord_event_type_unsupported")
        event_get_type = _get(event, "get_type")
        try:
            if not callable(event_get_type) or event_get_type() not in (
                {"message"} if event_type == "MESSAGE_CREATE" else {"notice"}
            ):
                return UnsupportedEvent("discord_event_kind_mismatch")
        except Exception:
            return UnsupportedEvent("discord_event_kind_unavailable")

        channel_id = _snowflake(_get(event, "channel_id"))
        message_id = _snowflake(_get(event, "id"))
        author = _get(event, "author")
        user_id = _snowflake(_get(author, "id"))
        if channel_id is None or message_id is None or user_id is None:
            return UnsupportedEvent("discord_message_identity_missing")

        guild_id_value = _get(event, "guild_id")
        guild_id = None if _is_unset(guild_id_value) or guild_id_value is None else _snowflake(guild_id_value)
        if not _is_unset(guild_id_value) and guild_id_value is not None and guild_id is None:
            return UnsupportedEvent("discord_guild_identity_invalid")

        intents = _get(_get(bot, "bot_info"), "intent")
        if intents is None or _is_unset(intents):
            return UnsupportedEvent("discord_intents_unavailable")
        intent_name = "direct_messages" if guild_id is None else "guild_messages"
        if _get(intents, intent_name) is not True:
            return UnsupportedEvent("discord_message_intent_missing")

        try:
            channel = self._resolve_channel(bot, event, channel_id)
        except Exception:
            return UnsupportedEvent("discord_channel_metadata_unavailable")
        scene = _scene_from_channel(channel, channel_id, guild_id)
        if isinstance(scene, UnsupportedEvent):
            return scene

        raw_content = _get(event, "content")
        if _is_unset(raw_content) or not isinstance(raw_content, str):
            return UnsupportedEvent("discord_message_content_missing")

        is_tome_getter = _get(event, "is_tome")
        try:
            is_tome = bool(is_tome_getter()) if callable(is_tome_getter) else False
        except Exception:
            is_tome = False
        if scene.kind == "private":
            is_tome = True
        if scene.kind != "private" and _get(intents, "message_content") is not True:
            bot_mentioned = any(
                _snowflake(_get(mention, "id")) == self_id
                for mention in (_get(event, "mentions") or ())
            )
            if not (is_tome or bot_mentioned):
                return UnsupportedEvent("discord_message_content_intent_missing")

        parts: list[MessagePartV1] = []
        if raw_content:
            parts.append(MessagePartV1("text", text=raw_content))
        has_image = False
        attachments = _get(event, "attachments")
        if _is_unset(attachments) or attachments is None:
            attachments = ()
        if not isinstance(attachments, (tuple, list)):
            return UnsupportedEvent("discord_attachments_invalid")
        for attachment in attachments:
            part = _attachment_part(attachment)
            if isinstance(part, UnsupportedEvent):
                return part
            parts.append(part)
            has_image = has_image or part.kind == "image"
        if not parts:
            return UnsupportedEvent("discord_message_has_no_supported_content")

        occurred_at = _event_timestamp(event, event_type)
        if occurred_at is None:
            return UnsupportedEvent("discord_message_timestamp_missing")

        relations: tuple[MessageRelationV1, ...] = ()
        reference = _get(event, "message_reference")
        if not _is_unset(reference) and reference is not None:
            relation = _reply_relation(
                reference,
                channel_id=channel_id,
                guild_id=guild_id,
                bot_ref=BotRef(connection_id, "discord", "discord", self_id),
                scene_ref=scene,
            )
            if isinstance(relation, UnsupportedEvent):
                return relation
            if relation is not None:
                relations = (relation,)

        bot_ref = BotRef(connection_id, "discord", "discord", self_id)
        user_ref = UserRef(
            "discord:user",
            user_id,
            _display_name(author),
        )
        revision_id: str | None = None
        event_kind = "create"
        if event_type == "MESSAGE_UPDATE":
            edited_timestamp = _get(event, "edited_timestamp")
            if _is_unset(edited_timestamp) or edited_timestamp is None:
                return UnsupportedEvent("discord_edit_revision_missing")
            revision_id = _timestamp_text(edited_timestamp)
            if revision_id is None:
                return UnsupportedEvent("discord_edit_revision_invalid")
            event_kind = "edit"

        message_event = MessageEventV1(
            platform_message_id=message_id,
            occurred_at=occurred_at,
            components=tuple(parts),
            relations=relations,
            event_kind=event_kind,
            platform_revision_id=revision_id,
        )
        display_name = user_ref.display_name or ""
        return NormalizedEvent(
            bot_ref=bot_ref,
            user_ref=user_ref,
            scene_ref=scene,
            text=raw_content,
            platform_message_id=message_id,
            sender_display_name=display_name,
            is_tome=is_tome,
            is_self=user_id == self_id,
            has_image=has_image,
            has_segments=bool(parts),
            raw_event=event,
            bot_handle=bot,
            message_event=message_event,
        )

    def _resolve_channel(self, bot: Any, event: Any, channel_id: str) -> Any:
        direct = _get(event, "channel")
        if direct is not None and not _is_unset(direct):
            direct_id = _snowflake(_get(direct, "id"))
            if direct_id == channel_id:
                return direct
        if self._channel_resolver is None:
            return None
        return self._channel_resolver(bot, channel_id)


class DiscordTargetCodec:
    """Encode only canonical IDs and exact private/channel/thread scenes."""

    def encode(self, target: DeliveryTarget, *, bot_handle: Any) -> DiscordTarget:
        if target.target_codec_version != 1:
            raise ValueError("Discord target codec version is unsupported")
        if target.bot.adapter != "discord" or target.bot.platform_scope != "discord":
            raise ValueError("Discord target identity mismatch")
        if target.routing_parameters:
            raise ValueError("Discord target has unsupported routing parameters")
        if _adapter_key(_adapter_name(bot_handle)) not in _DISCORD_ADAPTER_KEYS:
            raise ValueError("Discord Bot adapter identity mismatch")
        if _snowflake(_get(bot_handle, "self_id")) != target.bot.self_id:
            raise ValueError("Discord Bot handle self identity mismatch")

        channel_id = _canonical_snowflake(target.scene.scene_id)
        if channel_id is None:
            raise ValueError("Discord channel ID is invalid")
        if target.scene.kind == "private":
            if target.scene.parent_path or target.scene.thread_id is not None:
                raise ValueError("Discord DM target carries unsupported parent routing")
            return DiscordTarget(channel_id, None, "private")
        if target.scene.kind == "channel":
            if len(target.scene.parent_path) not in {1, 2} or target.scene.thread_id is not None:
                raise ValueError("Discord channel target needs a guild and optional category parent")
            guild_id = _canonical_snowflake(target.scene.parent_path[0])
            if guild_id is None:
                raise ValueError("Discord guild ID is invalid")
            if len(target.scene.parent_path) == 2 and _canonical_snowflake(target.scene.parent_path[1]) is None:
                raise ValueError("Discord category ID is invalid")
            return DiscordTarget(channel_id, guild_id, "channel")
        if target.scene.kind == "thread":
            if (
                len(target.scene.parent_path) != 2
                or target.scene.thread_id != target.scene.scene_id
            ):
                raise ValueError("Discord thread target must identify its exact thread")
            guild_id, _parent_channel_id = target.scene.parent_path
            canonical_guild = _canonical_snowflake(guild_id)
            if canonical_guild is None:
                raise ValueError("Discord thread guild ID is invalid")
            if _canonical_snowflake(_parent_channel_id) is None:
                raise ValueError("Discord parent channel ID is invalid")
            return DiscordTarget(channel_id, canonical_guild, "thread")
        raise ValueError("Discord target scene kind is unsupported")


class DiscordExporter:
    """Send text and exact message replies through the bound Discord Bot."""

    async def send(
        self,
        target: DeliveryTarget,
        message: OutboundMessage,
        *,
        bot_handle: Any,
        capabilities: AdapterCapabilities,
        encoded_target: DiscordTarget,
    ) -> AdapterSendResult:
        if (target.bot.adapter, target.bot.platform_scope) != ("discord", "discord"):
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="discord_target_identity_mismatch"
            )
        if capabilities.adapter != "discord" or capabilities.platform_scope != "discord":
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="discord_capability_identity_mismatch"
            )
        try:
            trusted_target = DiscordTargetCodec().encode(target, bot_handle=bot_handle)
        except Exception:
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="discord_target_identity_mismatch"
            )
        if trusted_target != encoded_target:
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="discord_encoded_target_mismatch"
            )
        try:
            from nonebot.adapters.discord.api import AllowedMention
            from nonebot.adapters.discord.message import Message, MessageSegment
        except ImportError:
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="discord_adapter_unavailable"
            )

        segments: list[Any] = []
        for segment in message.segments:
            if segment.kind is OutboundKind.TEXT:
                if len(segment.text) > DISCORD_MAX_TEXT_LENGTH:
                    return AdapterSendResult(
                        DeliveryStatus.UNSUPPORTED,
                        error_code="discord_text_segment_too_long",
                    )
                if segment.text:
                    # Constructing a text segment bypasses the adapter's parser,
                    # so markdown and literal mention syntax remain literal text.
                    segments.append(MessageSegment.text(segment.text))
            elif segment.kind is OutboundKind.REPLY:
                reply_id = _canonical_snowflake(segment.target_id)
                if reply_id is None:
                    return AdapterSendResult(
                        DeliveryStatus.UNSUPPORTED,
                        error_code="discord_reply_id_invalid",
                    )
                segments.append(
                    MessageSegment.reference(
                        reply_id,
                        channel_id=encoded_target.channel_id,
                        guild_id=encoded_target.guild_id,
                        fail_if_not_exists=True,
                    )
                )
            else:
                return AdapterSendResult(
                    DeliveryStatus.UNSUPPORTED,
                    error_code="discord_segment_unsupported",
                )
        if not segments:
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="discord_empty_after_export"
            )

        send_to = _get(bot_handle, "send_to")
        if not callable(send_to):
            return AdapterSendResult(
                DeliveryStatus.UNSUPPORTED, error_code="discord_send_api_unavailable"
            )
        allowed_mentions = AllowedMention(
            parse=[], roles=[], users=[], replied_user=False
        )
        try:
            receipt = await send_to(
                encoded_target.channel_id,
                Message(segments),
                allowed_mentions=allowed_mentions,
            )
        except TimeoutError:
            return AdapterSendResult(
                DeliveryStatus.UNKNOWN, error_code="discord_send_timeout"
            )
        except Exception as exc:
            if _is_discord_action_failed(exc):
                return AdapterSendResult(
                    DeliveryStatus.FAILED, error_code="discord_action_failed"
                )
            return AdapterSendResult(
                DeliveryStatus.UNKNOWN, error_code="discord_send_outcome_unknown"
            )

        message_id = _receipt_id(receipt)
        if message_id is None:
            return AdapterSendResult(
                DeliveryStatus.UNKNOWN, error_code="discord_receipt_id_missing"
            )
        return AdapterSendResult(DeliveryStatus.ACCEPTED, (message_id,))


def register_discord_transport(registry: Any) -> None:
    """Explicitly register Discord codecs; never called by default wiring."""
    registry.register_exporter(
        "discord",
        DiscordExporter(),
        DISCORD_CAPABILITIES,
        target_codec=DiscordTargetCodec(),
    )


def _get(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def _is_unset(value: Any) -> bool:
    return isinstance(value, type) and getattr(value, "__name__", "") == "UNSET"


def _snowflake(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    return text if _SNOWFLAKE.fullmatch(text) else None


def _canonical_snowflake(value: Any) -> str | None:
    return value if isinstance(value, str) and _SNOWFLAKE.fullmatch(value) else None


def _adapter_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(char.lower() for char in value if char.isalnum())


def _adapter_name(bot_handle: Any) -> Any:
    getter = _get(_get(bot_handle, "adapter"), "get_name")
    try:
        return getter() if callable(getter) else ""
    except Exception:
        return ""


def _event_type(event: Any) -> str:
    value = _get(event, "__type__")
    enum_value = _get(value, "value")
    if isinstance(enum_value, str):
        value = enum_value
    return value if isinstance(value, str) else ""


def _enum_name(value: Any) -> str:
    name = _get(value, "name")
    if isinstance(name, str):
        return name.upper()
    if isinstance(value, int) and not isinstance(value, bool):
        return {
            0: "GUILD_TEXT",
            1: "DM",
            3: "GROUP_DM",
            5: "GUILD_ANNOUNCEMENT",
            10: "ANNOUNCEMENT_THREAD",
            11: "PUBLIC_THREAD",
            12: "PRIVATE_THREAD",
        }.get(value, "")
    return ""


def _scene_from_channel(
    channel: Any, channel_id: str, event_guild_id: str | None
) -> SceneRef | UnsupportedEvent:
    if channel is None:
        return UnsupportedEvent("discord_channel_metadata_unavailable")
    if _snowflake(_get(channel, "id")) != channel_id:
        return UnsupportedEvent("discord_channel_identity_mismatch")
    channel_type = _enum_name(_get(channel, "type"))
    if channel_type == "DM":
        parent_id = _get(channel, "parent_id")
        if event_guild_id is not None or (parent_id is not None and not _is_unset(parent_id)):
            return UnsupportedEvent("discord_dm_scope_mismatch")
        return SceneRef("private", channel_id)
    if channel_type == "GROUP_DM":
        return UnsupportedEvent("discord_group_dm_unsupported")

    channel_guild = _get(channel, "guild_id")
    if _is_unset(channel_guild) or channel_guild is None:
        channel_guild_id = event_guild_id
    else:
        channel_guild_id = _snowflake(channel_guild)
    if channel_guild_id is None or event_guild_id != channel_guild_id:
        return UnsupportedEvent("discord_guild_channel_scope_mismatch")
    if channel_type in {"GUILD_TEXT", "GUILD_ANNOUNCEMENT"}:
        parent_value = _get(channel, "parent_id")
        parent_id = None if parent_value is None or _is_unset(parent_value) else _snowflake(parent_value)
        if parent_value is not None and not _is_unset(parent_value) and parent_id is None:
            return UnsupportedEvent("discord_channel_parent_invalid")
        parent_path = (channel_guild_id,) if parent_id is None else (channel_guild_id, parent_id)
        return SceneRef("channel", channel_id, parent_path=parent_path)
    if channel_type in {"ANNOUNCEMENT_THREAD", "PUBLIC_THREAD", "PRIVATE_THREAD"}:
        parent_id = _snowflake(_get(channel, "parent_id"))
        if parent_id is None:
            return UnsupportedEvent("discord_thread_parent_missing")
        return SceneRef(
            "thread",
            channel_id,
            parent_path=(channel_guild_id, parent_id),
            thread_id=channel_id,
        )
    return UnsupportedEvent("discord_channel_type_unsupported")


def _event_timestamp(event: Any, event_type: str) -> datetime | None:
    if event_type == "MESSAGE_UPDATE":
        edited = _get(event, "edited_timestamp")
        if not _is_unset(edited) and edited is not None and isinstance(edited, datetime):
            return _aware_utc(edited)
    value = _get(event, "timestamp")
    if _is_unset(value):
        return None
    return _aware_utc(value) if isinstance(value, datetime) else None


def _timestamp_text(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    normalized = _aware_utc(value)
    return normalized.isoformat() if normalized is not None else None


def _aware_utc(value: datetime) -> datetime | None:
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _attachment_part(attachment: Any) -> MessagePartV1 | UnsupportedEvent:
    content_type = _get(attachment, "content_type")
    if _is_unset(content_type) or not isinstance(content_type, str) or not content_type:
        content_type = None
    if content_type is not None:
        top_level = content_type.split("/", 1)[0].lower()
        kind = {
            "image": "image",
            "audio": "audio",
            "video": "video",
        }.get(top_level, "file")
    else:
        kind = "file"
    size = _get(attachment, "size")
    if _is_unset(size) or isinstance(size, bool) or not isinstance(size, int) or size < 0:
        size = None
    if content_type is None and size is None:
        return UnsupportedEvent("discord_attachment_metadata_missing")
    try:
        return MessagePartV1(kind, mime_type=content_type, size_bytes=size)
    except ValueError:
        return UnsupportedEvent("discord_attachment_metadata_invalid")


def _reply_relation(
    reference: Any,
    *,
    channel_id: str,
    guild_id: str | None,
    bot_ref: BotRef,
    scene_ref: SceneRef,
) -> MessageRelationV1 | UnsupportedEvent | None:
    reference_type = _get(reference, "type")
    if _is_unset(reference_type):
        return UnsupportedEvent("discord_reply_type_missing")
    if _enum_name(reference_type) != "DEFAULT" and reference_type != 0:
        return UnsupportedEvent("discord_non_reply_reference_unsupported")
    target_channel = _snowflake(_get(reference, "channel_id"))
    target_message = _snowflake(_get(reference, "message_id"))
    if target_channel is None or target_message is None:
        return UnsupportedEvent("discord_reply_reference_incomplete")
    if target_channel != channel_id:
        return UnsupportedEvent("discord_cross_channel_reply_unsupported")
    target_guild = _get(reference, "guild_id")
    if (
        not _is_unset(target_guild)
        and target_guild is not None
        and _snowflake(target_guild) != guild_id
    ):
        return UnsupportedEvent("discord_cross_guild_reply_unsupported")
    return MessageRelationV1(
        kind="reply",
        target_message_id=target_message,
        target_connection_id=bot_ref.connection_id,
        target_conversation_key=conversation_key_v2(bot_ref, scene_ref),
        resolved=False,
    )


def _display_name(author: Any) -> str | None:
    for field in ("global_name", "username"):
        value = _get(author, field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _receipt_id(receipt: Any) -> str | None:
    value = _get(receipt, "id")
    return _snowflake(value)


def _is_discord_action_failed(exc: Exception) -> bool:
    return any(
        cls.__name__ == "ActionFailed"
        and cls.__module__.startswith("nonebot.adapters.discord")
        for cls in type(exc).__mro__
    )


__all__ = [
    "DISCORD_CAPABILITIES",
    "DISCORD_MAX_TEXT_LENGTH",
    "DiscordExporter",
    "DiscordNormalizer",
    "DiscordTarget",
    "DiscordTargetCodec",
    "register_discord_transport",
]
