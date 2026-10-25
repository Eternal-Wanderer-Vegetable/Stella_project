# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Fixtures built from the lock-pinned NoneBot Telegram adapter models."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

telegram = pytest.importorskip("nonebot.adapters.telegram")
from nonebot.adapters.telegram.event import (
    ForumTopicMessageEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.adapters.telegram.message import Entity, File, Message
from nonebot.adapters.telegram.model import Chat, Update, User
from nonebot.adapters.telegram.model import Message as TelegramModelMessage

from core.transport.adapters.telegram import (
    TelegramNormalizer,
    TelegramTargetCodec,
    register_telegram_transport,
)
from core.transport.ingress import TransportIngress
from core.transport.keys import conversation_key_v2
from core.transport.models import BotRef, ConversationRefV2, SceneRef
from core.transport.outbound import (
    DeliveryStatus,
    DeliveryTarget,
    OutboundMessage,
    OutboundSegment,
    OutboundService,
    TransportRegistry,
)
from stella_bootstrap.transport_settings import parse_transport_settings_json

CONNECTION_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BOT_ID = "9001"
BOT = SimpleNamespace(
    self_id=BOT_ID,
    adapter=SimpleNamespace(get_name=lambda: "Telegram"),
)


def _user(user_id: int = 777) -> User:
    return User(id=user_id, is_bot=False, first_name="Ada", last_name="Lovelace")


def _private_event(
    *,
    message_id: int = 101,
    text: str = "hello",
    reply_to_message=None,
    message: Message | None = None,
) -> PrivateMessageEvent:
    return PrivateMessageEvent(
        message_id=message_id,
        date=1_793_000_000,
        chat=Chat(id=777, type="private", first_name="Ada"),
        **{"from": _user()},
        message=message or Message([Entity.text(text)]),
        reply_to_message=reply_to_message,
    )


def test_telegram_normalizer_preserves_private_group_topic_identity_and_reply_media():
    normalizer = TelegramNormalizer()

    private = normalizer.normalize(BOT, _private_event(), connection_id=CONNECTION_ID)
    assert private.bot_ref == BotRef(CONNECTION_ID, "telegram", "telegram", BOT_ID)
    assert private.scene_ref.kind == "private"
    assert private.scene_ref.scene_id == "777"
    assert private.user_ref.raw_user_id == "777"
    assert private.user_ref.identity_domain == "telegram:user"
    assert private.is_tome is True
    assert private.text == "hello"
    assert private.message_event.occurred_at == datetime.fromtimestamp(
        1_793_000_000, tz=timezone.utc
    )

    private_topic = _private_event(message_id=102)
    private_topic.telegram_model = Update(
        update_id=5,
        message=TelegramModelMessage(
            message_id=102,
            message_thread_id=303,
            date=1_793_000_000,
            chat=Chat(id=777, type="private", first_name="Ada"),
            **{"from": _user()},
            text="private topic",
        ),
    )
    normalized_private_topic = normalizer.normalize(
        BOT, private_topic, connection_id=CONNECTION_ID
    )
    assert normalized_private_topic.scene_ref.kind == "private"
    assert normalized_private_topic.scene_ref.thread_id == "303"

    group = GroupMessageEvent(
        message_id=202,
        date=1_793_000_000,
        chat=Chat(id=-100123, type="supergroup", title="Algorithms"),
        **{"from": _user()},
        message=Message([Entity.text("group hello")]),
    )
    normalized_group = normalizer.normalize(BOT, group, connection_id=CONNECTION_ID)
    assert normalized_group.scene_ref.kind == "group"
    assert normalized_group.scene_ref.scene_id == "-100123"

    topic = ForumTopicMessageEvent(
        message_id=203,
        message_thread_id=404,
        date=1_793_000_000,
        chat=Chat(id=-100123, type="supergroup", title="Algorithms"),
        **{"from": _user()},
        message=Message([Entity.text("topic hello")]),
    )
    normalized_topic = normalizer.normalize(BOT, topic, connection_id=CONNECTION_ID)
    assert normalized_topic.scene_ref.kind == "group"
    assert normalized_topic.scene_ref.scene_id == "-100123"
    assert normalized_topic.scene_ref.thread_id == "404"

    original = _private_event(message_id=88, text="original")
    replied = _private_event(
        message_id=89,
        text="with photo",
        reply_to_message=original,
        message=Message([Entity.text("with photo"), File.photo("telegram-file-id")]),
    )
    normalized_reply = normalizer.normalize(BOT, replied, connection_id=CONNECTION_ID)
    assert normalized_reply.message_event.relations[0].kind == "reply"
    assert normalized_reply.message_event.relations[0].target_message_id == "88"
    assert normalized_reply.message_event.relations[0].target_connection_id == CONNECTION_ID
    assert normalized_reply.message_event.relations[0].target_conversation_key == (
        conversation_key_v2(normalized_reply.bot_ref, normalized_reply.scene_ref)
    )
    assert normalized_reply.message_event.relations[0].resolved is False
    assert [part.kind for part in normalized_reply.message_event.components] == [
        "text",
        "image",
    ]
    assert normalized_reply.message_event.components[1].mime_type == "image/telegram"
    assert all(
        part.attachment_ref is None
        for part in normalized_reply.message_event.components
    )
    assert normalized_reply.has_image is True
    assert "telegram-file-id" not in repr(normalized_reply.message_event)


def test_telegram_normalizer_rejects_ephemeral_ids_wrong_adapter_and_channel_posts():
    normalizer = TelegramNormalizer()
    ephemeral = normalizer.normalize(
        BOT, _private_event(message_id=0), connection_id=CONNECTION_ID
    )
    assert ephemeral.reason_code == "telegram_message_id_unavailable"

    wrong_bot = SimpleNamespace(
        self_id=BOT_ID,
        adapter=SimpleNamespace(get_name=lambda: "Discord"),
    )
    result = normalizer.normalize(wrong_bot, _private_event(), connection_id=CONNECTION_ID)
    assert result.reason_code == "bot_adapter_identity_mismatch"

    channel_post = GroupMessageEvent(
        message_id=300,
        date=1_793_000_000,
        chat=Chat(id=-100987, type="channel", title="News"),
        **{"from": _user()},
        message=Message([Entity.text("post")]),
    )
    unsupported = normalizer.normalize(BOT, channel_post, connection_id=CONNECTION_ID)
    assert unsupported.reason_code == "telegram_chat_type_unsupported"


def test_enabled_telegram_connection_uses_its_normalizer_and_keeps_capture_identity():
    settings = parse_transport_settings_json(
        json.dumps(
            {
                "version": 1,
                "connections": [
                    {
                        "connection_id": CONNECTION_ID,
                        "adapter": "telegram",
                        "platform_scope": "telegram",
                        "self_id": BOT_ID,
                        "enabled": True,
                    }
                ],
                "defaults": {"capture_enabled": True, "llm_enabled": False},
            }
        )
    )
    registered = []
    captured = []

    def register(bot_ref, scene_ref, memory_space):
        reference = ConversationRefV2(
            bot=bot_ref,
            scene=scene_ref,
            storage_session_id=-91,
            memory_space=memory_space or f"transport:{conversation_key_v2(bot_ref, scene_ref)}",
        )
        registered.append(reference)
        return reference

    service = TransportIngress(
        settings,
        normalizers={"telegram": TelegramNormalizer()},
        register_conversation=register,
        capture_gate=lambda *_: True,
        capture_writer=lambda context, message_event: captured.append(
            (context, message_event)
        ),
    )
    result = asyncio.run(
        service.handle_event(CONNECTION_ID, BOT, _private_event(message_id=404))
    )

    assert result.status == "captured"
    assert result.capture_status == "captured"
    assert registered[0].bot == BotRef(CONNECTION_ID, "telegram", "telegram", BOT_ID)
    assert registered[0].scene.kind == "private"
    assert captured[0][1].platform_message_id == "404"
    assert captured[0][0].connection_id == CONNECTION_ID


def test_telegram_target_codec_and_exporter_keep_exact_topic_and_receipt():
    registry = TransportRegistry()
    register_telegram_transport(registry)
    normalized = TelegramNormalizer().normalize(
        BOT,
        ForumTopicMessageEvent(
            message_id=500,
            message_thread_id=606,
            date=1_793_000_000,
            chat=Chat(id=-100123, type="supergroup", title="Algorithms"),
            **{"from": _user()},
            message=Message([Entity.text("question")]),
        ),
        connection_id=CONNECTION_ID,
    )
    target = DeliveryTarget(normalized.bot_ref, normalized.scene_ref)
    codec_target = TelegramTargetCodec().encode(target, bot_handle=BOT)
    assert codec_target.chat_id == -100123
    assert codec_target.message_thread_id == 606

    sent = {}

    async def fake_send_to(chat_id, message, *, message_thread_id=None, **kwargs):
        sent["chat_id"] = chat_id
        sent["message"] = message
        sent["message_thread_id"] = message_thread_id
        sent["kwargs"] = kwargs
        return SimpleNamespace(message_id=501)

    bot = SimpleNamespace(
        self_id=BOT_ID,
        adapter=SimpleNamespace(get_name=lambda: "Telegram"),
        send_to=fake_send_to,
    )
    registry.bind_bot(normalized.bot_ref, bot)
    service = OutboundService(registry)
    result = asyncio.run(
        service.send(
            target,
            OutboundMessage(
                (
                    OutboundSegment.reply("500"),
                    OutboundSegment.text_segment("answer"),
                )
            ),
        )
    )

    assert result.status is DeliveryStatus.ACCEPTED
    assert result.message_ids == ("501",)
    assert sent["chat_id"] == -100123
    assert sent["message_thread_id"] == 606
    assert sent["message"][0].type == "reply"
    assert sent["message"][0].data["message_id"] == 500
    assert str(sent["message"]).endswith("answer")


def test_telegram_connection_codec_rejects_noncanonical_and_nested_targets():
    codec = TelegramTargetCodec()
    bot_ref = BotRef(CONNECTION_ID, "telegram", "telegram", BOT_ID)
    for scene in (
        # Numeric aliases can resolve to the same chat and are not accepted.
        SceneRef("group", "-0100123"),
        SceneRef("group", "-100123", ("channel:1",)),
        SceneRef("private", "-100123"),
    ):
        with pytest.raises(ValueError):
            codec.encode(DeliveryTarget(bot_ref, scene), bot_handle=BOT)
