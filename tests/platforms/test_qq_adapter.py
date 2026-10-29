# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Fixture coverage against the official QQ adapter event and Bot contracts."""

from __future__ import annotations

import os
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

# Local work may point this test at the exact wheel source extracted under /tmp.
# Normal CI uses the pinned distribution from project dependencies.
_qq_source = os.environ.get("STELLA_QQ_ADAPTER_SOURCE")
if _qq_source:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Failed to get nonebot adapters:.*")
        warnings.filterwarnings("ignore", message="No adapters found,.*")
        import nonebot.adapters

    _adapter_path = str(Path(_qq_source) / "nonebot" / "adapters")
    if _adapter_path not in nonebot.adapters.__path__:
        nonebot.adapters.__path__.append(_adapter_path)

from nonebot.adapters.qq.event import (
    AtMessageCreateEvent,
    C2CMessageCreateEvent,
    DirectMessageCreateEvent,
    GroupAtMessageCreateEvent,
    GroupMessageCreateEvent,
    MessageCreateEvent,
)
from nonebot.adapters.qq.models.guild import User as GuildUser
from nonebot.adapters.qq.models.qq import (
    Attachment,
    FriendAuthor,
    GroupMemberAuthor,
)

from core.transport.adapters.qq import (
    QQ_ADAPTER,
    QQ_CAPABILITIES,
    QQExporter,
    QQNormalizer,
    QQTargetCodec,
    qq_delivery_target,
    register_qq_transport,
)
from core.transport.normalizers import NormalizedEvent, UnsupportedEvent
from core.transport.outbound import (
    DeliveryStatus,
    DeliveryTarget,
    OutboundMessage,
    TransportRegistry,
)


def _bot(**intent_overrides):
    intents = {
        "c2c_group_at_messages": True,
        "at_messages": True,
        "direct_message": True,
    }
    intents.update(intent_overrides)
    return SimpleNamespace(
        self_id="app-id-opaque-01",
        adapter=SimpleNamespace(get_name=lambda: "QQ"),
        bot_info=SimpleNamespace(intent=SimpleNamespace(**intents)),
        ready=True,
    )


def _event_timestamp(minutes_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _events(*, minutes_ago: int = 0):
    base = {
        "id": "message-id:opaque/001",
        "content": "hello, QQ",
        "timestamp": _event_timestamp(minutes_ago),
    }
    return (
        C2CMessageCreateEvent(
            **base,
            author=FriendAuthor(id="friend-record", user_openid="c2c-openid-A"),
        ),
        GroupAtMessageCreateEvent(
            **base,
            author=GroupMemberAuthor(
                id="member-record",
                member_openid="group-member-openid-A",
                bot=False,
                member_role="member",
            ),
            group_id="legacy-number-not-used",
            group_openid="group-openid-A",
        ),
        AtMessageCreateEvent(
            **base,
            author=GuildUser(id="guild-user-openid-A", username="Kai"),
            channel_id="channel-openid-A",
            guild_id="guild-openid-A",
        ),
        DirectMessageCreateEvent(
            **base,
            author=GuildUser(id="guild-user-openid-A", username="Kai"),
            channel_id="dm-channel-openid-A",
            guild_id="guild-openid-A",
        ),
    )


@pytest.mark.parametrize(
    ("event_index", "scene_kind", "scene_id", "window_seconds"),
    [
        (0, "private", "c2c-openid-A", 3600),
        (1, "group", "group-openid-A", 300),
        (2, "channel", "channel-openid-A", 300),
        (3, "private", "dm-channel-openid-A", 300),
    ],
)
def test_qq_official_events_normalize_opaque_identities_and_reply_windows(
    event_index, scene_kind, scene_id, window_seconds
):
    event = _events()[event_index]
    bot = _bot()
    normalized = QQNormalizer().normalize(bot, event, connection_id="qq-fixture-connection")

    assert isinstance(normalized, NormalizedEvent)
    assert normalized.bot_ref.adapter == QQ_ADAPTER == "qq-official"
    assert normalized.bot_ref.self_id == "app-id-opaque-01"
    assert normalized.scene_ref.kind == scene_kind
    assert normalized.scene_ref.scene_id == scene_id
    assert normalized.platform_message_id == "message-id:opaque/001"
    assert normalized.text == "hello, QQ"

    target = qq_delivery_target(normalized)
    encoded = QQTargetCodec().encode(target, bot_handle=bot)
    assert encoded.message_id == "message-id:opaque/001"
    remaining = datetime.fromisoformat(target.expires_at_utc.replace("Z", "+00:00")) - datetime.now(timezone.utc)
    assert window_seconds - 2 <= remaining.total_seconds() <= window_seconds
    if event_index == 3:
        assert target.scene.parent_path == ("guild-openid-A",)
        assert encoded.route_kind == "direct"


def test_qq_normalizer_rejects_unmentioned_group_and_guild_events():
    now = _event_timestamp()
    group = GroupMessageCreateEvent(
        id="g-msg",
        content="not addressed to the bot",
        timestamp=now,
        author=GroupMemberAuthor(
            id="member-record",
            member_openid="member-openid",
            bot=False,
            member_role="member",
        ),
        group_id="legacy-id",
        group_openid="group-openid",
    )
    guild = MessageCreateEvent(
        id="guild-msg",
        content="not addressed to the bot",
        timestamp=datetime.now(timezone.utc),
        author=GuildUser(id="guild-user"),
        channel_id="channel-id",
        guild_id="guild-id",
    )

    result_group = QQNormalizer().normalize(_bot(), group, connection_id="qq")
    result_guild = QQNormalizer().normalize(_bot(), guild, connection_id="qq")
    assert isinstance(result_group, UnsupportedEvent)
    assert result_group.reason_code == "qq_event_type_unsupported"
    assert isinstance(result_guild, UnsupportedEvent)
    assert result_guild.reason_code == "qq_event_type_unsupported"


def test_qq_normalizer_requires_the_specific_configured_intent():
    event = _events()[0]
    result = QQNormalizer().normalize(
        _bot(c2c_group_at_messages=False), event, connection_id="qq"
    )
    assert isinstance(result, UnsupportedEvent)
    assert result.reason_code == "qq_required_intent_missing"


def test_qq_normalizer_keeps_attachment_metadata_but_discards_signed_url():
    event = C2CMessageCreateEvent(
        id="c2c-message-with-image",
        content="look",
        timestamp=_event_timestamp(),
        author=FriendAuthor(id="friend", user_openid="c2c-openid"),
        attachments=[
            Attachment(
                content_type="image/png",
                filename="photo.png",
                size=1234,
                url="https://cdn.example/signed-secret-token",
            )
        ],
    )
    normalized = QQNormalizer().normalize(_bot(), event, connection_id="qq")

    assert isinstance(normalized, NormalizedEvent)
    assert normalized.has_image is True
    assert normalized.message_event is not None
    image_part = next(part for part in normalized.message_event.components if part.kind == "image")
    assert image_part.mime_type == "image/png"
    assert image_part.size_bytes == 1234
    assert image_part.display_name == "photo.png"
    assert "signed-secret-token" not in repr(normalized.message_event)


def test_qq_normalizer_rejects_surrogate_ids_and_sanitizes_surrogate_names():
    bot = _bot()
    invalid_id_event = _events()[0].model_copy(update={"id": "bad\ud800id"})
    assert QQNormalizer().normalize(bot, invalid_id_event, connection_id="qq") == UnsupportedEvent(
        "qq_message_id_missing"
    )

    event = _events()[0].model_copy(
        update={
            "author": FriendAuthor(
                id="friend-record", user_openid="c2c-openid-A", username="Kai\ud800"
            )
        }
    )
    normalized = QQNormalizer().normalize(bot, event, connection_id="qq")
    assert isinstance(normalized, NormalizedEvent)
    assert normalized.user_ref.display_name is None


def test_qq_target_codec_rejects_retargeting_expiry_extension_and_serialized_targets():
    bot = _bot()
    normalized = QQNormalizer().normalize(bot, _events()[0], connection_id="qq")
    assert isinstance(normalized, NormalizedEvent)
    target = qq_delivery_target(normalized)

    wrong_scene = DeliveryTarget(
        target.bot,
        type(target.scene)("private", "another-openid"),
        expires_at_utc=target.expires_at_utc,
        event_handle=target.event_handle,
    )
    with pytest.raises(ValueError, match="exact target"):
        QQTargetCodec().encode(wrong_scene, bot_handle=bot)

    # A second Bot with the same public self_id must not reuse this event target.
    with pytest.raises(ValueError, match="exact source Bot"):
        QQTargetCodec().encode(target, bot_handle=_bot())

    routed = DeliveryTarget(
        target.bot,
        target.scene,
        routing_parameters=(("channel_id", "spoofed-channel"),),
        expires_at_utc=target.expires_at_utc,
        event_handle=target.event_handle,
    )
    with pytest.raises(ValueError, match="routing parameters"):
        QQTargetCodec().encode(routed, bot_handle=bot)

    extended = DeliveryTarget(
        target.bot,
        target.scene,
        expires_at_utc=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        event_handle=target.event_handle,
    )
    with pytest.raises(ValueError, match="deadline"):
        QQTargetCodec().encode(extended, bot_handle=bot)

    restored = DeliveryTarget.loads(target.dumps())
    with pytest.raises(ValueError, match="original event"):
        QQTargetCodec().encode(restored, bot_handle=bot)

    expired_event = _events(minutes_ago=61)[0]
    expired = QQNormalizer().normalize(bot, expired_event, connection_id="qq")
    assert isinstance(expired, NormalizedEvent)
    with pytest.raises(ValueError, match="expired"):
        QQTargetCodec().encode(qq_delivery_target(expired), bot_handle=bot)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_index", "expected_method", "expected_kwargs"),
    [
        (0, "send_to_c2c", {"msg_id": "message-id:opaque/001", "msg_seq": 1}),
        (1, "send_to_group", {"msg_id": "message-id:opaque/001", "msg_seq": 1}),
        (2, "send_to_channel", {"msg_id": "message-id:opaque/001"}),
        (3, "send_to_dms", {"msg_id": "message-id:opaque/001"}),
    ],
)
async def test_qq_exporter_uses_exact_bot_route_and_original_msg_id(
    event_index, expected_method, expected_kwargs
):
    bot = _bot()
    normalized = QQNormalizer().normalize(bot, _events()[event_index], connection_id="qq")
    assert isinstance(normalized, NormalizedEvent)
    target = qq_delivery_target(normalized)
    encoded = QQTargetCodec().encode(target, bot_handle=bot)
    called: dict[str, object] = {}

    async def fake_send(*args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs
        called["message"] = args[1] if len(args) > 1 else kwargs["message"]
        return SimpleNamespace(id="receipt-id:opaque/003")

    setattr(bot, expected_method, fake_send)
    result = await QQExporter().send(
        target,
        OutboundMessage.text("<@!do-not-mention> literal"),
        bot_handle=bot,
        capabilities=QQ_CAPABILITIES,
        encoded_target=encoded,
    )

    assert result.status is DeliveryStatus.ACCEPTED
    assert result.message_ids == ("receipt-id:opaque/003",)
    assert {key: called["kwargs"][key] for key in expected_kwargs} == expected_kwargs
    if expected_method == "send_to_group":
        assert called["kwargs"]["group_openid"] == "group-openid-A"
    assert "event_id" not in called["kwargs"]
    sdk_message = called["message"]
    assert len(sdk_message) == 1
    assert sdk_message[0].type == "text"
    assert sdk_message[0].data["text"] == "<@!do-not-mention> literal"


@pytest.mark.asyncio
async def test_qq_exporter_maps_ambiguous_network_outcome_to_unknown(monkeypatch):
    bot = _bot()
    normalized = QQNormalizer().normalize(bot, _events()[0], connection_id="qq")
    assert isinstance(normalized, NormalizedEvent)
    target = qq_delivery_target(normalized)
    encoded = QQTargetCodec().encode(target, bot_handle=bot)

    async def timeout(*_args, **_kwargs):
        raise TimeoutError

    bot.send_to_c2c = timeout
    result = await QQExporter().send(
        target,
        OutboundMessage.text("reply"),
        bot_handle=bot,
        capabilities=QQ_CAPABILITIES,
        encoded_target=encoded,
    )
    assert result.status is DeliveryStatus.UNKNOWN
    assert result.error_code == "qq_send_timeout"


@pytest.mark.asyncio
async def test_qq_exporter_maps_definite_adapter_rejection_to_failed():
    from nonebot.adapters.qq.exception import ActionFailed
    from nonebot.drivers import Response

    bot = _bot()
    normalized = QQNormalizer().normalize(bot, _events()[0], connection_id="qq")
    assert isinstance(normalized, NormalizedEvent)
    target = qq_delivery_target(normalized)
    encoded = QQTargetCodec().encode(target, bot_handle=bot)

    async def rejected(*_args, **_kwargs):
        raise ActionFailed(Response(403, content=b'{"code":403,"message":"rejected"}'))

    bot.send_to_c2c = rejected
    result = await QQExporter().send(
        target,
        OutboundMessage.text("reply"),
        bot_handle=bot,
        capabilities=QQ_CAPABILITIES,
        encoded_target=encoded,
    )
    assert result.status is DeliveryStatus.FAILED
    assert result.error_code == "qq_action_failed"


def test_qq_codecs_are_not_registered_until_the_connection_owner_opts_in():
    registry = TransportRegistry()
    assert registry.binding_for(QQ_ADAPTER) is None
    register_qq_transport(registry)
    assert registry.binding_for(QQ_ADAPTER) is not None
    assert registry.binding_for(QQ_ADAPTER).target_codec is not None
    assert QQ_CAPABILITIES.proactive_send is False
    assert QQ_CAPABILITIES.upload_image is False
    assert QQ_CAPABILITIES.upload_file is False
