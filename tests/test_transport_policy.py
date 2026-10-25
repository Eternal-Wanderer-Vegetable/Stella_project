# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Policy precedence is deterministic and retains explicit false and empty values."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.transport.policy import PolicyLayer, resolve_policy
from stella_bootstrap.transport_settings import TransportSettingsError


def test_policy_layers_follow_declared_precedence_and_keep_field_sources():
    policy = resolve_policy(
        [
            PolicyLayer("scene", {"capture_enabled": False, "wake_prefixes": []}),
            PolicyLayer("profile", {"capture_enabled": True, "wake_prefixes": ["!"]}),
            PolicyLayer("global_defaults", {"llm_enabled": True}),
            PolicyLayer("connection_default", {"llm_enabled": False}),
        ],
        now=datetime(2026, 10, 25, tzinfo=timezone.utc),
    )
    assert policy.values["capture_enabled"] is False
    assert policy.sources["capture_enabled"] == "scene"
    assert policy.values["wake_prefixes"] == ()
    assert policy.sources["wake_prefixes"] == "scene"
    assert policy.values["llm_enabled"] is False
    assert policy.sources["llm_enabled"] == "connection_default"
    assert policy.sources["proactive_enabled"] == "system_default"


def test_runtime_overrides_apply_until_expiry_then_inherit_lower_layer():
    now = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    layers = [
        PolicyLayer("profile", {"proactive_enabled": False}),
        PolicyLayer(
            "runtime",
            {"proactive_enabled": True},
            expires_at=now + timedelta(minutes=5),
        ),
    ]
    active = resolve_policy(layers, now=now)
    expired = resolve_policy(layers, now=now + timedelta(minutes=5))
    assert active.values["proactive_enabled"] is True
    assert active.sources["proactive_enabled"] == "runtime"
    assert expired.values["proactive_enabled"] is False
    assert expired.sources["proactive_enabled"] == "profile"


def test_duplicate_layers_and_unbounded_runtime_overrides_are_rejected():
    with pytest.raises(TransportSettingsError, match="duplicate policy layer"):
        resolve_policy(
            [
                PolicyLayer("profile", {"capture_enabled": True}),
                PolicyLayer("profile", {"capture_enabled": False}),
            ]
        )
    with pytest.raises(TransportSettingsError, match="expiry"):
        PolicyLayer("runtime", {"capture_enabled": True})


def test_unknown_fields_and_enum_values_are_rejected():
    with pytest.raises(TransportSettingsError, match="unknown fields"):
        PolicyLayer("profile", {"allow_everything": True})
    with pytest.raises(TransportSettingsError, match="unsupported"):
        PolicyLayer("profile", {"format_mode": "unknown"})
