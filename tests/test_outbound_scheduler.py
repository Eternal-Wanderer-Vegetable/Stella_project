# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Queue, quota, retry, and Bot-generation contracts for outbound delivery."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest

from core.transport import (
    AdapterCapabilities,
    AdapterSendResult,
    BotRef,
    DeliveryStatus,
    DeliveryTarget,
    OutboundMessage,
    OutboundSendScheduler,
    OutboundService,
    RateLimitBucket,
    SceneRef,
    TransportRegistry,
)


class _Codec:
    def encode(self, target, *, bot_handle):
        return (target.bot.connection_id, bot_handle.self_id, target.scene.scene_id)


class _Bot:
    def __init__(self, self_id="shared-bot"):
        self.self_id = self_id


def _target(
    *, adapter="fake", connection="conn-a", scene_id="scene-a", expires_at_utc=""
):
    return DeliveryTarget(
        BotRef(connection, adapter, adapter, "shared-bot"),
        SceneRef("group", scene_id, parent_path=("guild",), thread_id="thread-a"),
        expires_at_utc=expires_at_utc,
    )


def _service(exporter, capabilities, *, registry=None, scheduler=None, retries=2):
    registry = registry or TransportRegistry()
    registry.register_exporter(
        capabilities.adapter,
        exporter,
        capabilities,
        target_codec=_Codec(),
    )
    return OutboundService(
        registry, scheduler=scheduler, max_rate_limit_retries=retries
    ), registry


class _QueueExporter:
    def __init__(self, *, block_first=False, results=()):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block_first = block_first
        self.results = None if results is None else iter(results)
        self.calls = []

    async def send(self, target, message, *, bot_handle, capabilities, encoded_target):
        text = "".join(segment.text for segment in message.segments)
        self.calls.append((target, text, bot_handle))
        self.started.set()
        if self.block_first and len(self.calls) == 1:
            await self.release.wait()
        if self.results is None:
            return AdapterSendResult(DeliveryStatus.ACCEPTED, (f"msg:{text}",))
        try:
            return next(self.results)
        except StopIteration:
            return AdapterSendResult(DeliveryStatus.ACCEPTED, (f"msg:{text}",))


@pytest.mark.asyncio
async def test_target_queue_is_fifo_and_bounded():
    exporter = _QueueExporter(block_first=True, results=None)
    service, _ = _service(
        exporter,
        AdapterCapabilities("fake", "fake", group=True),
        scheduler=OutboundSendScheduler(max_queue_per_target=1),
    )
    target = _target()
    bot = _Bot()
    first = asyncio.create_task(service.send(target, OutboundMessage.text("first"), bot_handle=bot))
    await exporter.started.wait()
    second = asyncio.create_task(service.send(target, OutboundMessage.text("second"), bot_handle=bot))
    while not any(lane.waiters for lane in service.scheduler._lanes.values()):
        await asyncio.sleep(0)
    third = await service.send(target, OutboundMessage.text("third"), bot_handle=bot)
    assert third.status is DeliveryStatus.FAILED
    assert third.error_code == "send_queue_full"
    exporter.release.set()
    first_result, second_result = await asyncio.gather(first, second)
    assert first_result.status is second_result.status is DeliveryStatus.ACCEPTED
    assert [call[1] for call in exporter.calls] == ["first", "second"]


@pytest.mark.asyncio
async def test_target_expiry_while_queued_prevents_exporter_call():
    exporter = _QueueExporter(block_first=True, results=None)
    service, _ = _service(
        exporter,
        AdapterCapabilities("fake", "fake", group=True),
    )
    bot = _Bot()
    target = _target()
    first = asyncio.create_task(service.send(target, OutboundMessage.text("active"), bot_handle=bot))
    await exporter.started.wait()
    expiry = (datetime.now(timezone.utc) + timedelta(milliseconds=40)).isoformat()
    queued_target = _target(expires_at_utc=expiry)
    queued = asyncio.create_task(
        service.send(queued_target, OutboundMessage.text("expired"), bot_handle=bot)
    )
    await asyncio.sleep(0.06)
    exporter.release.set()
    first_result, queued_result = await asyncio.gather(first, queued)
    assert first_result.status is DeliveryStatus.ACCEPTED
    assert queued_result.status is DeliveryStatus.EXPIRED
    assert queued_result.error_code == "send_window_expired"
    assert [call[1] for call in exporter.calls] == ["active"]


@pytest.mark.asyncio
async def test_request_and_api_quotas_remain_independent():
    exporter = _QueueExporter(results=None)
    caps = AdapterCapabilities(
        "fake",
        "fake",
        group=True,
        rate_limit_buckets=(
            RateLimitBucket("messages", "adapter", "api", 2, 0.3),
            RateLimitBucket("messages", "connection", "request", 1, 0.02),
        ),
    )
    service, _ = _service(exporter, caps)
    target = _target()
    bot = _Bot()
    assert (await service.send(target, OutboundMessage.text("one"), bot_handle=bot)).status is DeliveryStatus.ACCEPTED
    started = time.monotonic()
    result = await service.send(target, OutboundMessage.text("two"), bot_handle=bot)
    elapsed = time.monotonic() - started
    assert result.status is DeliveryStatus.ACCEPTED
    assert elapsed >= 0.015
    assert elapsed < 0.15


@pytest.mark.asyncio
async def test_adapter_quota_is_shared_across_connections():
    exporter = _QueueExporter(results=None)
    caps = AdapterCapabilities(
        "fake",
        "fake",
        group=True,
        rate_limit_buckets=(RateLimitBucket("send", "adapter", "api", 1, 0.02),),
    )
    service, _ = _service(exporter, caps)
    first = _target(connection="conn-a")
    second = _target(connection="conn-b", scene_id="scene-b")
    bot = _Bot()
    assert (await service.send(first, OutboundMessage.text("one"), bot_handle=bot)).status is DeliveryStatus.ACCEPTED
    started = time.monotonic()
    result = await service.send(second, OutboundMessage.text("two"), bot_handle=bot)
    assert result.status is DeliveryStatus.ACCEPTED
    assert time.monotonic() - started >= 0.015


@pytest.mark.asyncio
async def test_rate_limit_retry_requires_explicit_rejection_and_records_attempts():
    exporter = _QueueExporter(results=(
        AdapterSendResult(
            DeliveryStatus.FAILED,
            error_code="http_429",
            retry_after_seconds=0.01,
        ),
        AdapterSendResult(DeliveryStatus.ACCEPTED, ("opaque:accepted",)),
    ))
    service, _ = _service(exporter, AdapterCapabilities("fake", "fake", group=True))
    result = await service.send(_target(), OutboundMessage.text("hello"), bot_handle=_Bot())
    assert result.status is DeliveryStatus.ACCEPTED
    assert result.message_ids == ("opaque:accepted",)
    assert len(exporter.calls) == 2
    assert result.parts[0].attempts == 2


@pytest.mark.asyncio
async def test_retry_after_over_budget_is_rejected_without_waiting():
    exporter = _QueueExporter(results=(
        AdapterSendResult(
            DeliveryStatus.FAILED,
            error_code="rate_limited",
            retry_after_seconds=31,
        ),
        AdapterSendResult(DeliveryStatus.ACCEPTED, ("must-not-send",)),
    ))
    service, _ = _service(exporter, AdapterCapabilities("fake", "fake", group=True))
    started = time.monotonic()
    result = await service.send(_target(), OutboundMessage.text("hello"), bot_handle=_Bot())
    assert time.monotonic() - started < 0.2
    assert result.status is DeliveryStatus.FAILED
    assert result.error_code == "retry_after_exceeds_budget"
    assert len(exporter.calls) == 1
    assert result.parts[0].attempts == 1


@pytest.mark.asyncio
async def test_rebind_while_queued_never_sends_on_stale_generation():
    exporter = _QueueExporter(block_first=True, results=None)
    registry = TransportRegistry()
    caps = AdapterCapabilities("fake", "fake", group=True)
    service, registry = _service(exporter, caps, registry=registry)
    target = _target()
    old_bot = _Bot()
    registry.bind_bot(target.bot, old_bot)
    first = asyncio.create_task(service.send(target, OutboundMessage.text("active")))
    await exporter.started.wait()
    queued = asyncio.create_task(service.send(target, OutboundMessage.text("stale")))
    while not any(lane.waiters for lane in service.scheduler._lanes.values()):
        await asyncio.sleep(0)
    registry.bind_bot(target.bot, _Bot())
    exporter.release.set()
    first_result, queued_result = await asyncio.gather(first, queued)
    assert first_result.status is DeliveryStatus.ACCEPTED
    assert queued_result.status is DeliveryStatus.FAILED
    assert queued_result.error_code == "exact_bot_binding_stale"
    assert [call[1] for call in exporter.calls] == ["active"]


@pytest.mark.asyncio
async def test_disconnect_while_queued_never_uses_old_bot_handle():
    exporter = _QueueExporter(block_first=True, results=None)
    caps = AdapterCapabilities("fake", "fake", group=True)
    service, registry = _service(exporter, caps)
    target = _target()
    registry.bind_bot(target.bot, _Bot())
    first = asyncio.create_task(service.send(target, OutboundMessage.text("active")))
    await exporter.started.wait()
    queued = asyncio.create_task(service.send(target, OutboundMessage.text("disconnected")))
    while not any(lane.waiters for lane in service.scheduler._lanes.values()):
        await asyncio.sleep(0)
    assert registry.unbind_bot(target.bot) is True
    exporter.release.set()
    first_result, queued_result = await asyncio.gather(first, queued)
    assert first_result.status is DeliveryStatus.ACCEPTED
    assert queued_result.status is DeliveryStatus.FAILED
    assert queued_result.error_code == "exact_bot_binding_stale"
    assert [call[1] for call in exporter.calls] == ["active"]


def test_transport_registry_allows_same_self_id_on_other_adapter_and_rejects_slot_conflict():
    registry = TransportRegistry()
    one = BotRef("conn-one", "adapter-one", "one", "shared")
    two = BotRef("conn-two", "adapter-two", "two", "shared")
    one_bot = _Bot("shared")
    registry.bind_bot(one, one_bot)
    registry.bind_bot(two, _Bot("shared"))
    generation = registry.resolve_bot_binding(one)[1]
    registry.bind_bot(one, one_bot)
    assert registry.resolve_bot_binding(one)[1] == generation
    assert registry.resolve_bot(one) is not None
    assert registry.resolve_bot(two) is not None
    with pytest.raises(ValueError, match="duplicate self_id"):
        registry.bind_bot(BotRef("conn-three", "adapter-one", "one", "shared"), _Bot("shared"))
    assert registry.unbind_bot(one) is True
    assert registry.unbind_bot(one) is False
    registry.bind_bot(one, one_bot)
    assert registry.resolve_bot_binding(one)[1] > generation
    assert registry.resolve_bot(two) is not None
