# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Transport-neutral outbound contracts and adapter result handling."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.transport import (
    AdapterCapabilities,
    AdapterSendResult,
    BotRef,
    DeliveryStatus,
    DeliveryTarget,
    MediaSource,
    OutboundMessage,
    OutboundSegment,
    OutboundService,
    RateLimitBucket,
    SceneRef,
    TransportRegistry,
    split_outbound_message,
)


def _target(adapter: str = "fake", platform: str = "test", scene: str = "group"):
    return DeliveryTarget(
        BotRef(f"conn:{adapter}:1", adapter, platform, "bot-1"),
        SceneRef(scene, "room:007", parent_path=("guild:α",), thread_id="thread:02"),
    )


def test_delivery_target_roundtrips_without_process_local_event_handle():
    target = DeliveryTarget(
        BotRef("conn:onebot", "onebot-v11", "qq", "10001"),
        SceneRef("group", "007", parent_path=("guild",)),
        routing_parameters=(("thread_id", "thread:02"),),
        event_handle=object(),
    )

    encoded = target.dumps()
    restored = DeliveryTarget.loads(encoded)

    assert restored.bot == target.bot
    assert restored.scene == target.scene
    assert restored.routing_parameters == (("thread_id", "thread:02"),)
    assert restored.event_handle is None
    assert "object at" not in encoded


def test_delivery_target_rejects_credentials_and_unknown_routes():
    bot = BotRef("c", "fake", "test", "b")
    scene = SceneRef("group", "g")
    with pytest.raises(ValueError, match="routing parameters"):
        DeliveryTarget(bot, scene, routing_parameters=(("access_token", "secret"),))
    with pytest.raises(ValueError, match="routing parameters"):
        DeliveryTarget(bot, scene, routing_parameters=(("thread_id", "t"), ("thread_id", "t2")))


def test_outbound_message_keeps_segment_order_and_rejects_ephemeral_media_persistence():
    message = OutboundMessage((
        OutboundSegment.text_segment("before"),
        OutboundSegment.image(MediaSource("image", "https://cdn.example/x.png", fallback_text="image")),
        OutboundSegment.at("user:007", "Ada"),
        OutboundSegment.reply("msg:abc"),
        OutboundSegment.text_segment("after"),
    ))
    restored = OutboundMessage.load(message.dump())
    assert [part.kind.value for part in restored.segments] == [
        "text", "image", "at", "reply", "text"
    ]
    assert restored.segments[3].target_id == "msg:abc"

    credentialed = OutboundMessage((
        OutboundSegment.image(MediaSource("image", "https://cdn.example/x.png?access_token=secret")),
    ))
    with pytest.raises(ValueError, match="short-lived media URLs"):
        credentialed.dump()


def test_split_outbound_message_preserves_ordered_media_and_text():
    message = OutboundMessage((
        OutboundSegment.text_segment("abcde"),
        OutboundSegment.image(MediaSource("image", "/tmp/p.png")),
        OutboundSegment.text_segment("0123456789"),
    ))

    parts = split_outbound_message(message, 4)

    assert [
        (segment.kind.value, segment.text if segment.kind.value == "text" else "")
        for part in parts for segment in part.segments
    ] == [
        ("text", "abcd"), ("text", "e"), ("image", ""),
        ("text", "0123"), ("text", "4567"), ("text", "89"),
    ]


def test_capability_narrowing_cannot_widen_text_or_scene_support():
    base = AdapterCapabilities(
        "fake", "test", group=True, private=True, max_text_length=100,
        requests_per_window=10, rate_window_seconds=60,
    )
    instance = AdapterCapabilities(
        "fake", "test", group=False, private=True, max_text_length=40,
        requests_per_window=2, rate_window_seconds=30,
    )

    narrowed = base.narrowed_by(instance)

    assert narrowed.group is False
    assert narrowed.private is True
    assert narrowed.max_text_length == 40
    assert narrowed.requests_per_window == 10
    assert narrowed.rate_window_seconds == 60
    assert narrowed.quota_buckets() == (
        RateLimitBucket("legacy", "adapter", "api", 10, 60),
        RateLimitBucket("legacy", "connection", "api", 2, 30),
    )


class _FakeCodec:
    def encode(self, target, *, bot_handle):
        return (target.bot.connection_id, bot_handle.self_id, target.scene.scene_id)


class _FakeExporter:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    async def send(self, target, message, *, bot_handle, capabilities, encoded_target):
        self.calls.append((target, message, bot_handle, encoded_target))
        return next(self.results)


class _Bot:
    def __init__(self, self_id="bot-1"):
        self.self_id = self_id


def _service(exporter, capabilities):
    registry = TransportRegistry()
    registry.register_exporter(
        capabilities.adapter,
        exporter,
        capabilities,
        target_codec=_FakeCodec(),
    )
    return OutboundService(registry)


@pytest.mark.asyncio
async def test_send_splits_to_capability_and_stops_after_unknown_without_retry():
    exporter = _FakeExporter((
        AdapterSendResult(DeliveryStatus.ACCEPTED, ("msg:α", "007")),
        AdapterSendResult(DeliveryStatus.UNKNOWN, error_code="timeout"),
    ))
    service = _service(
        exporter,
        AdapterCapabilities("fake", "test", group=True, max_text_length=3),
    )

    result = await service.send(_target(), OutboundMessage.text("abcdef"), bot_handle=_Bot())

    assert result.status is DeliveryStatus.PARTIAL
    assert result.message_ids == ("msg:α", "007")
    assert [part.status for part in result.parts] == [
        DeliveryStatus.ACCEPTED, DeliveryStatus.UNKNOWN
    ]
    assert [call[1].segments[0].text for call in exporter.calls] == ["abc", "def"]
    assert len(exporter.calls) == 2


@pytest.mark.asyncio
async def test_send_logs_payload_free_acceptance_summary(monkeypatch):
    from core.transport import outbound as outbound_module

    records = []

    class _CaptureLogger:
        def info(self, message):
            records.append(("info", message))

        def warning(self, message):
            records.append(("warning", message))

    monkeypatch.setattr(outbound_module, "logger", _CaptureLogger())
    exporter = _FakeExporter((AdapterSendResult(
        DeliveryStatus.ACCEPTED, ("private-receipt-id",)
    ),))
    service = _service(
        exporter,
        AdapterCapabilities("fake", "test", group=True),
    )

    result = await service.send(
        _target(), OutboundMessage.text("private-message-body"), bot_handle=_Bot()
    )

    assert result.status is DeliveryStatus.ACCEPTED
    assert len(records) == 1
    level, record = records[0]
    assert level == "info"
    assert "[OutboundDelivery] status=accepted" in record
    assert "adapter=fake scene=group" in record
    assert "segment_kinds=text:1" in record
    assert "part_count=1 accepted_parts=1" in record
    assert "receipt_count=1 error_category=none" in record
    assert "private-message-body" not in record
    assert "private-receipt-id" not in record
    assert "room:007" not in record
    assert "bot-1" not in record


@pytest.mark.asyncio
async def test_send_logs_unknown_result_as_warning_without_adapter_error_text(monkeypatch):
    from core.transport import outbound as outbound_module

    records = []

    class _CaptureLogger:
        def info(self, message):
            records.append(("info", message))

        def warning(self, message):
            records.append(("warning", message))

    monkeypatch.setattr(outbound_module, "logger", _CaptureLogger())
    exporter = _FakeExporter((AdapterSendResult(
        DeliveryStatus.UNKNOWN,
        error_code="send_timeout: private-provider-response",
    ),))
    service = _service(
        exporter,
        AdapterCapabilities("fake", "test", group=True),
    )

    result = await service.send(
        _target(), OutboundMessage.text("private-message-body"), bot_handle=_Bot()
    )

    assert result.status is DeliveryStatus.UNKNOWN
    assert len(records) == 1
    level, record = records[0]
    assert level == "warning"
    assert "[OutboundDelivery] status=unknown" in record
    assert "error_category=timeout" in record
    assert "private-provider-response" not in record
    assert "private-message-body" not in record


@pytest.mark.asyncio
async def test_send_deadline_expires_before_first_physical_part():
    from gravitas.clock import system_control_clock
    from gravitas.contracts import Deadline

    exporter = _FakeExporter((AdapterSendResult(DeliveryStatus.ACCEPTED),))
    service = _service(
        exporter,
        AdapterCapabilities("fake", "test", group=True, max_text_length=3),
    )
    clock = system_control_clock()
    deadline = Deadline(clock.now() - 1, clock.clock_id)

    result = await service.send(
        _target(), OutboundMessage.text("abcdef"), bot_handle=_Bot(),
        deadline=deadline,
    )

    assert result.status is DeliveryStatus.EXPIRED
    assert result.error_code == "turn_deadline"
    assert exporter.calls == []


@pytest.mark.asyncio
async def test_send_deadline_between_physical_parts_returns_partial(monkeypatch):
    from gravitas import deadlines as deadline_helpers
    from gravitas.contracts import Deadline

    clock_value = {"now": 0.0}
    clock = SimpleNamespace(now=lambda: clock_value["now"], clock_id="test-clock")
    monkeypatch.setattr(deadline_helpers, "system_control_clock", lambda: clock)

    class ExpiringExporter:
        def __init__(self):
            self.calls = []

        async def send(self, target, message, *, bot_handle, capabilities, encoded_target):
            self.calls.append(message)
            clock_value["now"] = 11.0
            return AdapterSendResult(DeliveryStatus.ACCEPTED, ("physical-1",))

    exporter = ExpiringExporter()
    service = _service(
        exporter,
        AdapterCapabilities("fake", "test", group=True, max_text_length=3),
    )

    result = await service.send(
        _target(), OutboundMessage.text("abcdef"), bot_handle=_Bot(),
        deadline=Deadline(10.0, "test-clock"),
    )

    assert result.status is DeliveryStatus.PARTIAL
    assert result.error_code == "turn_deadline"
    assert len(exporter.calls) == 1


@pytest.mark.asyncio
async def test_send_uses_media_fallback_when_capability_is_absent():
    exporter = _FakeExporter((AdapterSendResult(DeliveryStatus.ACCEPTED),))
    service = _service(
        exporter,
        AdapterCapabilities("fake", "test", group=True, upload_image=False),
    )
    message = OutboundMessage((
        OutboundSegment.image(MediaSource("image", "/tmp/not-sent.png", fallback_text="see summary")),
    ))

    result = await service.send(_target(), message, bot_handle=_Bot())

    assert result.status is DeliveryStatus.ACCEPTED
    assert [segment.text for segment in exporter.calls[0][1].segments] == ["see summary"]


@pytest.mark.asyncio
async def test_send_refuses_random_or_mismatched_bot_bindings():
    exporter = _FakeExporter((AdapterSendResult(DeliveryStatus.ACCEPTED),))
    registry = TransportRegistry()
    caps = AdapterCapabilities("fake", "test", group=True)
    registry.register_exporter("fake", exporter, caps, target_codec=_FakeCodec())
    registry.bind_bot(_target().bot, _Bot())
    service = OutboundService(registry)

    missing = await service.send(_target("other", "test"), OutboundMessage.text("x"))
    mismatch = await service.send(_target(), OutboundMessage.text("x"), bot_handle=_Bot("someone-else"))

    assert missing.status is DeliveryStatus.UNSUPPORTED
    assert missing.error_code == "adapter_exporter_missing"
    assert mismatch.status is DeliveryStatus.UNSUPPORTED
    assert mismatch.error_code == "bot_identity_mismatch"
    assert exporter.calls == []


def test_onebot_target_codec_binds_explicit_adapter_platform_and_bot(monkeypatch):
    from nonebot_plugin_alconna.uniseg import Target

    from core.transport.adapters.onebot_v11 import OneBotV11TargetCodec

    bot = SimpleNamespace(self_id="10001", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"))
    target = DeliveryTarget(
        BotRef("legacy-qq:10001", "onebot-v11", "qq", "10001"),
        SceneRef("group", "007"),
    )

    encoded = OneBotV11TargetCodec().encode(target, bot_handle=bot)

    assert isinstance(encoded, Target)
    assert encoded.id == "007"
    assert encoded.self_id == "10001"
    assert encoded.adapter == "OneBot V11"
    assert encoded.platform == ["qq"]


@pytest.mark.asyncio
async def test_onebot_exporter_preserves_opaque_ids_and_ordered_segments(monkeypatch):
    from nonebot_plugin_alconna.uniseg import UniMessage

    from core.transport.adapters.onebot_v11 import (
        OneBotV11Exporter,
        OneBotV11TargetCodec,
    )

    captured = {}

    async def fake_send(message, *, target=None, bot=None, **kwargs):
        captured["segments"] = list(message)
        captured["target"] = target
        captured["bot"] = bot
        return SimpleNamespace(msg_ids=["external:007", 9])

    monkeypatch.setattr(UniMessage, "send", fake_send)
    bot = SimpleNamespace(self_id="10001", adapter=SimpleNamespace(get_name=lambda: "OneBot V11"))
    target = DeliveryTarget(
        BotRef("legacy-qq:10001", "onebot-v11", "qq", "10001"),
        SceneRef("group", "123"),
    )
    encoded = OneBotV11TargetCodec().encode(target, bot_handle=bot)
    message = OutboundMessage((
        OutboundSegment.reply("007"),
        OutboundSegment.at("user:α", "Ada"),
        OutboundSegment.text_segment(" hello"),
        OutboundSegment.image(MediaSource("image", "https://cdn.example/a.png")),
        OutboundSegment.file(MediaSource("file", "/tmp/report.pdf", name="report.pdf")),
    ))

    result = await OneBotV11Exporter().send(
        target,
        message,
        bot_handle=bot,
        capabilities=AdapterCapabilities("onebot-v11", "qq", group=True),
        encoded_target=encoded,
    )

    assert result.status is DeliveryStatus.ACCEPTED
    assert result.message_ids == ("external:007", "9")
    assert [segment.type for segment in captured["segments"]] == [
        "reply", "at", "text", "image", "file"
    ]
    assert captured["target"] is encoded
    assert captured["bot"] is bot
