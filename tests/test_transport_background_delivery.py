# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Exact registry and proactive-policy boundary for background sends."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.transport.capabilities import AdapterCapabilities
from core.transport.models import BotRef, SceneRef
from core.transport.outbound import (
    DeliveryResult,
    DeliveryStatus,
    DeliveryTarget,
    OutboundMessage,
)
from stella_project.plugins.bot_main import transport_delivery

CONNECTION_ID = "11111111-1111-4111-8111-111111111111"
TARGET = DeliveryTarget(
    BotRef(CONNECTION_ID, "synthetic", "synthetic", "bot:雪"),
    SceneRef(
        "thread",
        "thread:3",
        parent_path=("guild:1", "channel:2"),
        thread_id="thread:3",
    ),
)


def _settings(*, proactive=True) -> str:
    return json.dumps(
        {
            "version": 1,
            "defaults": {"proactive_enabled": proactive, "requests_per_window": 3,
                         "rate_window_seconds": 120},
            "connections": [
                {
                    "connection_id": CONNECTION_ID,
                    "adapter": "synthetic",
                    "platform_scope": "synthetic",
                    "self_id": "bot:雪",
                    "enabled": True,
                }
            ],
            "profiles": [{"policy_profile_id": "fixture-profile"}],
            "bindings": [
                {
                    "connection_id": CONNECTION_ID,
                    "scene": {
                        "kind": "thread",
                        "scene_id": "thread:3",
                        "parent_path": ["guild:1", "channel:2"],
                        "thread_id": "thread:3",
                    },
                    "policy_profile_id": "fixture-profile",
                }
            ],
        }
    )


class _Registry:
    def __init__(self, *, bound=True, capabilities=None):
        self.bound = bound
        self.bot = SimpleNamespace(self_id="bot:雪")
        self.capabilities = capabilities or AdapterCapabilities(
            "synthetic", "synthetic", thread=True, proactive_send=True
        )
        self.resolved = []

    def resolve_bot_binding(self, bot_ref):
        self.resolved.append(bot_ref)
        return (self.bot, 4) if self.bound else None

    def capabilities_for(self, target):
        return self.capabilities


class _Service:
    def __init__(self, registry):
        self.registry = registry
        self.calls = []

    async def send(self, target, message, *, bot_handle=None, instance_capabilities=None):
        self.calls.append((target, message, bot_handle, instance_capabilities))
        return DeliveryResult(target, DeliveryStatus.ACCEPTED, ("m:1",))


@pytest.mark.asyncio
async def test_registered_route_uses_exact_registry_and_policy_request_bucket(monkeypatch):
    registry = _Registry()
    service = _Service(registry)
    monkeypatch.setattr(transport_delivery, "get_outbound_service", lambda: service)
    monkeypatch.setattr(
        transport_delivery, "_configured_transport_settings_json", lambda: _settings()
    )
    monkeypatch.setattr(
        transport_delivery,
        "_resolve_legacy_qq_bot",
        lambda _bot_ref: pytest.fail("registered nonlegacy Bot must not use QQ fallback"),
    )

    result = await transport_delivery.send_background_message(
        TARGET, OutboundMessage.text("fixture")
    )

    assert result.status is DeliveryStatus.ACCEPTED
    assert registry.resolved == [TARGET.bot]
    assert len(service.calls) == 1
    _, _, bot_handle, instance_capabilities = service.calls[0]
    assert bot_handle is None  # OutboundService owns generation revalidation.
    assert instance_capabilities.proactive_send is True
    assert any(
        bucket.category == "request"
        and bucket.scope == "scene"
        and bucket.limit == 3
        and bucket.window_seconds == 120
        for bucket in instance_capabilities.rate_limit_buckets
    )


@pytest.mark.asyncio
async def test_policy_or_adapter_capability_denial_never_calls_sender(monkeypatch):
    registry = _Registry(
        capabilities=AdapterCapabilities("synthetic", "synthetic", thread=True)
    )
    service = _Service(registry)
    monkeypatch.setattr(transport_delivery, "get_outbound_service", lambda: service)
    monkeypatch.setattr(
        transport_delivery, "_configured_transport_settings_json", lambda: _settings()
    )

    capability_denied = await transport_delivery.send_background_message(
        TARGET, OutboundMessage.text("fixture")
    )
    registry.capabilities = AdapterCapabilities(
        "synthetic", "synthetic", thread=True, proactive_send=True
    )
    monkeypatch.setattr(
        transport_delivery, "_configured_transport_settings_json", lambda: _settings(proactive=False)
    )
    policy_denied = await transport_delivery.send_background_message(
        TARGET, OutboundMessage.text("fixture")
    )

    assert capability_denied.status is DeliveryStatus.UNSUPPORTED
    assert capability_denied.error_code == "background_proactive_capability_missing"
    assert policy_denied.status is DeliveryStatus.UNSUPPORTED
    assert policy_denied.error_code == "background_proactive_disabled"
    assert service.calls == []


@pytest.mark.asyncio
async def test_unbound_nonlegacy_target_never_falls_back_to_another_bot(monkeypatch):
    service = _Service(_Registry(bound=False))
    monkeypatch.setattr(transport_delivery, "get_outbound_service", lambda: service)
    monkeypatch.setattr(
        transport_delivery,
        "_resolve_legacy_qq_bot",
        lambda _bot_ref: pytest.fail("nonlegacy target must not use legacy QQ fallback"),
    )

    result = await transport_delivery.send_background_message(
        TARGET, OutboundMessage.text("fixture")
    )

    assert result.status is DeliveryStatus.FAILED
    assert result.error_code == "exact_bot_binding_missing"
    assert service.calls == []


def test_resolve_background_bot_checks_registry_before_legacy_lookup(monkeypatch):
    bot_ref = BotRef(CONNECTION_ID, "synthetic", "synthetic", "bot:雪")
    service = _Service(_Registry())
    monkeypatch.setattr(transport_delivery, "get_outbound_service", lambda: service)
    monkeypatch.setattr(
        transport_delivery,
        "_resolve_legacy_qq_bot",
        lambda _bot_ref: pytest.fail("registered binding must be preferred"),
    )

    assert transport_delivery.resolve_background_bot(bot_ref) is service.registry.bot
