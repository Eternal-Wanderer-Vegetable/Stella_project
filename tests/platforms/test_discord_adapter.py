# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Fixtures built from the lock-pinned NoneBot Discord adapter models."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

discord = pytest.importorskip("nonebot.adapters.discord")
from nonebot.adapters.discord.api import Attachment, Channel, MessageReference, User
from nonebot.adapters.discord.api.types import (
    ChannelType,
    MessageReferenceType,
    MessageType,
)
from nonebot.adapters.discord.config import BotInfo, Intents
from nonebot.adapters.discord.event import (
    DirectMessageCreateEvent,
    GuildMessageCreateEvent,
    GuildMessageUpdateEvent,
)
from nonebot.adapters.discord.message import parse_message

from core.transport.adapters.discord import (
    DISCORD_CAPABILITIES,
    DISCORD_MAX_TEXT_LENGTH,
    DiscordExporter,
    DiscordNormalizer,
    DiscordTargetCodec,
    register_discord_transport,
)
from core.transport.keys import conversation_key_v2
from core.transport.models import BotRef, SceneRef
from core.transport.outbound import (
    DeliveryStatus,
    DeliveryTarget,
    OutboundMessage,
    OutboundSegment,
    OutboundService,
    TransportRegistry,
)

CONNECTION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
BOT_ID = "9001"
GUILD_ID = "8100"
CHANNEL_ID = "8200"
CATEGORY_ID = "8250"
PARENT_CHANNEL_ID = "8300"
THREAD_A_ID = "8401"
THREAD_B_ID = "8402"
DM_CHANNEL_ID = "8500"
NOW = datetime(2026, 10, 25, 8, 30, tzinfo=timezone.utc)


def _bot(*, intents: Intents | None = None, self_id: str = BOT_ID):
    return SimpleNamespace(
        self_id=self_id,
        adapter=SimpleNamespace(get_name=lambda: "Discord"),
        bot_info=BotInfo(
            token="fixture-only",
            intent=intents if intents is not None else Intents(message_content=True),
        ),
    )


def _author(user_id: str = "777") -> User:
    return User(
        id=user_id,
        username="ada",
        discriminator="0",
        global_name="Ada",
        avatar=None,
    )


def _guild_event(
    *,
    message_id: str = "7001",
    channel_id: str = CHANNEL_ID,
    content: str = "hello",
    **overrides,
) -> GuildMessageCreateEvent:
    values = {
        "id": message_id,
        "channel_id": channel_id,
        "guild_id": GUILD_ID,
        "author": _author(),
        "content": content,
        "timestamp": NOW,
        "edited_timestamp": None,
        "tts": False,
        "mention_everyone": False,
        "mentions": [],
        "mention_roles": [],
        "attachments": [],
        "embeds": [],
        "pinned": False,
        "type": MessageType.DEFAULT,
    }
    values.update(overrides)
    return GuildMessageCreateEvent(**values)


def _dm_event(*, message_id: str = "7002", content: str = "direct hello"):
    return DirectMessageCreateEvent(
        id=message_id,
        channel_id=DM_CHANNEL_ID,
        author=_author(),
        content=content,
        timestamp=NOW,
        edited_timestamp=None,
        tts=False,
        mention_everyone=False,
        mentions=[],
        mention_roles=[],
        attachments=[],
        embeds=[],
        pinned=False,
        type=MessageType.DEFAULT,
    )


def _channels():
    return {
        CHANNEL_ID: Channel(
            id=CHANNEL_ID,
            type=ChannelType.GUILD_TEXT,
            guild_id=GUILD_ID,
            parent_id=CATEGORY_ID,
            name="general",
        ),
        PARENT_CHANNEL_ID: Channel(
            id=PARENT_CHANNEL_ID,
            type=ChannelType.GUILD_TEXT,
            guild_id=GUILD_ID,
            name="forum-parent",
        ),
        THREAD_A_ID: Channel(
            id=THREAD_A_ID,
            type=ChannelType.PUBLIC_THREAD,
            guild_id=GUILD_ID,
            parent_id=PARENT_CHANNEL_ID,
            name="thread-a",
        ),
        THREAD_B_ID: Channel(
            id=THREAD_B_ID,
            type=ChannelType.PRIVATE_THREAD,
            guild_id=GUILD_ID,
            parent_id=PARENT_CHANNEL_ID,
            name="thread-b",
        ),
        DM_CHANNEL_ID: Channel(id=DM_CHANNEL_ID, type=ChannelType.DM),
    }


def _normalizer(channels=None) -> DiscordNormalizer:
    available = channels or _channels()
    return DiscordNormalizer(lambda _bot, channel_id: available.get(channel_id))


def test_discord_normalizer_keeps_dm_channel_and_distinct_thread_identity():
    normalizer = _normalizer()
    bot = _bot()

    channel = normalizer.normalize(bot, _guild_event(), connection_id=CONNECTION_ID)
    dm = normalizer.normalize(bot, _dm_event(), connection_id=CONNECTION_ID)
    thread_a = normalizer.normalize(
        bot,
        _guild_event(channel_id=THREAD_A_ID, message_id="7003"),
        connection_id=CONNECTION_ID,
    )
    thread_b = normalizer.normalize(
        bot,
        _guild_event(channel_id=THREAD_B_ID, message_id="7004"),
        connection_id=CONNECTION_ID,
    )

    assert channel.scene_ref == SceneRef("channel", CHANNEL_ID, (GUILD_ID, CATEGORY_ID))
    assert dm.scene_ref == SceneRef("private", DM_CHANNEL_ID)
    assert thread_a.scene_ref == SceneRef(
        "thread", THREAD_A_ID, (GUILD_ID, PARENT_CHANNEL_ID), THREAD_A_ID
    )
    assert thread_b.scene_ref == SceneRef(
        "thread", THREAD_B_ID, (GUILD_ID, PARENT_CHANNEL_ID), THREAD_B_ID
    )
    assert thread_a.scene_ref != thread_b.scene_ref
    assert channel.bot_ref == BotRef(CONNECTION_ID, "discord", "discord", BOT_ID)
    assert thread_a.user_ref.identity_domain == "discord:user"
    assert thread_a.user_ref.raw_user_id == "777"
    assert thread_a.message_event.platform_message_id == "7003"


def test_discord_normalizer_requires_intents_and_channel_type_evidence():
    no_guild_intent = _bot(intents=Intents(guild_messages=False))
    result = _normalizer().normalize(
        no_guild_intent, _guild_event(), connection_id=CONNECTION_ID
    )
    assert result.reason_code == "discord_message_intent_missing"

    no_dm_intent = _bot(intents=Intents(direct_messages=False))
    result = _normalizer().normalize(
        no_dm_intent, _dm_event(), connection_id=CONNECTION_ID
    )
    assert result.reason_code == "discord_message_intent_missing"

    no_content_intent = _bot(intents=Intents(message_content=False))
    result = _normalizer().normalize(
        no_content_intent, _guild_event(), connection_id=CONNECTION_ID
    )
    assert result.reason_code == "discord_message_content_intent_missing"

    mentioned_event = _guild_event(
        mentions=[_author(BOT_ID)], content="<@9001> hi", to_me=True
    )
    result = _normalizer().normalize(
        no_content_intent, mentioned_event, connection_id=CONNECTION_ID
    )
    assert result.text == "<@9001> hi"
    assert result.is_tome is True

    missing_metadata = DiscordNormalizer().normalize(
        _bot(), _guild_event(), connection_id=CONNECTION_ID
    )
    assert missing_metadata.reason_code == "discord_channel_metadata_unavailable"

    group_dm_channel = Channel(id=DM_CHANNEL_ID, type=ChannelType.GROUP_DM)
    group_dm = DirectMessageCreateEvent(
        **{
            **_dm_event().model_dump(exclude_unset=True),
            "channel_id": DM_CHANNEL_ID,
        }
    )
    result = _normalizer({DM_CHANNEL_ID: group_dm_channel}).normalize(
        _bot(), group_dm, connection_id=CONNECTION_ID
    )
    assert result.reason_code == "discord_group_dm_unsupported"


def test_discord_normalizer_preserves_unresolved_reply_attachment_hints_and_edits():
    reply_reference = MessageReference(
        type=MessageReferenceType.DEFAULT,
        message_id="6100",
        channel_id=CHANNEL_ID,
        guild_id=GUILD_ID,
    )
    attachment = Attachment(
        id="6200",
        filename="diagram.png",
        content_type="image/png",
        size=123,
        url="https://cdn.discordapp.com/attachments/secret-fixture-url",
        proxy_url="https://media.discordapp.net/secret-fixture-url",
    )
    event = _guild_event(
        message_reference=reply_reference,
        referenced_message=None,
        attachments=[attachment],
    )
    normalized = _normalizer().normalize(_bot(), event, connection_id=CONNECTION_ID)

    assert len(normalized.message_event.relations) == 1
    relation = normalized.message_event.relations[0]
    assert relation.kind == "reply"
    assert relation.target_message_id == "6100"
    assert relation.target_connection_id == CONNECTION_ID
    assert relation.target_conversation_key == conversation_key_v2(
        normalized.bot_ref, normalized.scene_ref
    )
    assert relation.resolved is False
    image_part = normalized.message_event.components[-1]
    assert image_part.kind == "image"
    assert image_part.mime_type == "image/png"
    assert image_part.size_bytes == 123
    assert "secret-fixture-url" not in repr(normalized.message_event)
    assert "6200" not in repr(normalized.message_event)

    update = GuildMessageUpdateEvent(
        id="7001",
        channel_id=CHANNEL_ID,
        guild_id=GUILD_ID,
        author=_author(),
        content="edited",
        timestamp=NOW,
        edited_timestamp=datetime(2026, 10, 25, 8, 32, tzinfo=timezone.utc),
        attachments=[],
        embeds=[],
    )
    edited = _normalizer().normalize(_bot(), update, connection_id=CONNECTION_ID)
    assert edited.message_event.event_kind == "edit"
    assert edited.message_event.platform_revision_id == "2026-10-25T08:32:00+00:00"


def test_discord_target_codec_uses_exact_thread_id_and_rejects_ambiguous_routes():
    bot = _bot()
    codec = DiscordTargetCodec()
    target_a = DeliveryTarget(
        BotRef(CONNECTION_ID, "discord", "discord", BOT_ID),
        SceneRef("thread", THREAD_A_ID, (GUILD_ID, PARENT_CHANNEL_ID), THREAD_A_ID),
    )
    target_b = DeliveryTarget(
        BotRef(CONNECTION_ID, "discord", "discord", BOT_ID),
        SceneRef("thread", THREAD_B_ID, (GUILD_ID, PARENT_CHANNEL_ID), THREAD_B_ID),
    )

    encoded_a = codec.encode(target_a, bot_handle=bot)
    encoded_b = codec.encode(target_b, bot_handle=bot)
    assert encoded_a.channel_id == THREAD_A_ID
    assert encoded_a.channel_id != PARENT_CHANNEL_ID
    assert encoded_a.guild_id == GUILD_ID
    assert encoded_b.channel_id == THREAD_B_ID
    assert encoded_a.channel_id != encoded_b.channel_id

    malformed = DeliveryTarget(
        target_a.bot,
        SceneRef("thread", PARENT_CHANNEL_ID, (GUILD_ID, PARENT_CHANNEL_ID), THREAD_A_ID),
    )
    with pytest.raises(ValueError, match="exact thread"):
        codec.encode(malformed, bot_handle=bot)
    with pytest.raises(ValueError, match="identity"):
        codec.encode(
            DeliveryTarget(
                BotRef(CONNECTION_ID, "discord", "discord", "9999"),
                target_a.scene,
            ),
            bot_handle=bot,
        )


def test_discord_exporter_preserves_markdown_suppresses_mentions_and_replies_exactly():
    target = DeliveryTarget(
        BotRef(CONNECTION_ID, "discord", "discord", BOT_ID),
        SceneRef("thread", THREAD_A_ID, (GUILD_ID, PARENT_CHANNEL_ID), THREAD_A_ID),
    )
    encoded_target = DiscordTargetCodec().encode(target, bot_handle=_bot())
    sent = []

    async def fake_send_to(channel_id, message, *, allowed_mentions=None):
        sent.append((channel_id, message, allowed_mentions))
        return SimpleNamespace(id="99001")

    bot = _bot()
    bot.send_to = fake_send_to
    message = OutboundMessage(
        (
            OutboundSegment.text_segment("**literal markdown** <@&12345>"),
            OutboundSegment.reply("6100"),
        )
    )
    result = asyncio.run(
        DiscordExporter().send(
            target,
            message,
            bot_handle=bot,
            capabilities=DISCORD_CAPABILITIES,
            encoded_target=encoded_target,
        )
    )

    assert result.status is DeliveryStatus.ACCEPTED
    assert result.message_ids == ("99001",)
    assert sent[0][0] == THREAD_A_ID
    assert sent[0][2].parse == []
    payload = parse_message(sent[0][1])
    assert payload["content"] == "**literal markdown** <@&12345>"
    assert payload["message_reference"].message_id == 6100
    assert payload["message_reference"].channel_id == int(THREAD_A_ID)
    assert payload["message_reference"].guild_id == int(GUILD_ID)
    assert payload["message_reference"].fail_if_not_exists is True


def test_discord_exporter_permission_failure_is_definite_and_long_text_is_split():
    target = DeliveryTarget(
        BotRef(CONNECTION_ID, "discord", "discord", BOT_ID),
        SceneRef("channel", CHANNEL_ID, (GUILD_ID,)),
    )
    bot = _bot()
    calls = []

    async def denied_send_to(channel_id, message, *, allowed_mentions=None):
        calls.append(channel_id)
        error_type = type(
            "ActionFailed",
            (Exception,),
            {"__module__": "nonebot.adapters.discord.exception"},
        )
        raise error_type("missing SEND_MESSAGES permission")

    bot.send_to = denied_send_to
    registry = TransportRegistry()
    register_discord_transport(registry)
    service = OutboundService(registry)
    registry.bind_bot(target.bot, bot)
    denied = asyncio.run(service.send(target, OutboundMessage.text("hello")))
    assert denied.status is DeliveryStatus.FAILED
    assert calls == [CHANNEL_ID]
    assert denied.parts[0].attempts == 1
    delivered = []

    async def fake_send_to(channel_id, message, *, allowed_mentions=None):
        delivered.append((channel_id, parse_message(message)["content"]))
        return SimpleNamespace(id=str(99010 + len(delivered)))

    bot.send_to = fake_send_to
    long_text = "**x**" + ("y" * (DISCORD_MAX_TEXT_LENGTH * 2 + 30))
    result = asyncio.run(service.send(target, OutboundMessage.text(long_text)))

    assert result.status is DeliveryStatus.ACCEPTED
    assert len(delivered) == 3
    assert all(channel_id == CHANNEL_ID for channel_id, _ in delivered)
    assert all(len(chunk) <= DISCORD_MAX_TEXT_LENGTH for _, chunk in delivered)
    assert "".join(chunk for _, chunk in delivered) == long_text


def test_discord_explicit_registration_stays_opt_in_and_caps_are_narrow():
    registry = TransportRegistry()
    assert registry.binding_for("discord") is None
    register_discord_transport(registry)
    assert registry.binding_for("discord") is not None
    assert DISCORD_CAPABILITIES.passive_receive is False
    assert DISCORD_CAPABILITIES.proactive_send is False
    assert DISCORD_CAPABILITIES.mention_user is False
    assert DISCORD_CAPABILITIES.mention_role is False
    assert DISCORD_CAPABILITIES.upload_image is False
    assert DISCORD_CAPABILITIES.upload_file is False
    assert DISCORD_MAX_TEXT_LENGTH < 2000
