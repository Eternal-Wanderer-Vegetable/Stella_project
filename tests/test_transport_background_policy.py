# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Fixture-only policy checks for durable background transport delivery."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.transport.background_policy import evaluate_background_policy
from core.transport.models import BotRef, SceneRef
from core.transport.outbound import DeliveryTarget

CONNECTION_ID = "11111111-1111-4111-8111-111111111111"
SCENE = SceneRef(
    "thread",
    "thread:3",
    parent_path=("guild:1", "channel:2"),
    thread_id="thread:3",
)
TARGET = DeliveryTarget(
    BotRef(CONNECTION_ID, "synthetic", "synthetic", "bot:雪"),
    SCENE,
)


def _settings(*, defaults=None, connection=None, scene=None, binding=True) -> str:
    bundle = {
        "version": 1,
        "defaults": defaults or {},
        "connections": [
            {
                "connection_id": CONNECTION_ID,
                "adapter": "synthetic",
                "platform_scope": "synthetic",
                "self_id": "bot:雪",
                "enabled": True,
                "policy": connection or {},
            }
        ],
        "profiles": [{"policy_profile_id": "fixture-profile"}],
        "bindings": [],
        "platform_templates": {},
    }
    if binding:
        bundle["bindings"].append(
            {
                "connection_id": CONNECTION_ID,
                "scene": {
                    "kind": SCENE.kind,
                    "scene_id": SCENE.scene_id,
                    "parent_path": list(SCENE.parent_path),
                    "thread_id": SCENE.thread_id,
                },
                "policy_profile_id": "fixture-profile",
                "policy": scene or {},
            }
        )
    return json.dumps(bundle, ensure_ascii=False)


def test_explicit_scene_policy_returns_independent_request_quota():
    result = evaluate_background_policy(
        TARGET,
        _settings(
            defaults={"proactive_enabled": True},
            connection={"requests_per_window": 4, "rate_window_seconds": 90},
            scene={"requests_per_window": 2},
        ),
        now=datetime(2026, 10, 25, 12, tzinfo=timezone.utc),
    )

    assert result.allowed is True
    assert result.reason_code == ""
    assert result.request_bucket is not None
    assert (
        result.request_bucket.scope,
        result.request_bucket.category,
        result.request_bucket.limit,
        result.request_bucket.window_seconds,
    ) == ("scene", "request", 2, 90.0)


def test_proactive_policy_defaults_to_disabled_and_requires_full_scene():
    disabled = evaluate_background_policy(
        TARGET,
        _settings(),
        now=datetime(2026, 10, 25, 12, tzinfo=timezone.utc),
    )
    missing_binding = evaluate_background_policy(
        TARGET,
        _settings(defaults={"proactive_enabled": True}, binding=False),
        now=datetime(2026, 10, 25, 12, tzinfo=timezone.utc),
    )

    assert (disabled.allowed, disabled.reason_code) == (
        False,
        "background_proactive_disabled",
    )
    assert (missing_binding.allowed, missing_binding.reason_code) == (
        False,
        "background_scene_binding_missing",
    )


@pytest.mark.parametrize(
    ("hour", "minute", "blocked"),
    [(21, 59, False), (22, 0, True), (2, 30, True), (6, 0, False)],
)
def test_quiet_hours_cross_midnight_with_exclusive_end(hour, minute, blocked):
    result = evaluate_background_policy(
        TARGET,
        _settings(
            defaults={
                "proactive_enabled": True,
                "quiet_hours": {"start": "22:00", "end": "06:00", "timezone": "UTC"},
            }
        ),
        now=datetime(2026, 10, 25, hour, minute, tzinfo=timezone.utc),
    )

    assert result.allowed is not blocked
    assert result.reason_code == ("background_quiet_hours" if blocked else "")


def test_invalid_timezone_and_incomplete_policy_quota_fail_closed():
    invalid_timezone = evaluate_background_policy(
        TARGET,
        _settings(
            defaults={
                "proactive_enabled": True,
                "quiet_hours": {
                    "start": "22:00",
                    "end": "06:00",
                    "timezone": "No/Such_Zone",
                },
            }
        ),
        now=datetime(2026, 10, 25, 12, tzinfo=timezone.utc),
    )
    incomplete_quota = evaluate_background_policy(
        TARGET,
        _settings(defaults={"proactive_enabled": True, "requests_per_window": 2}),
        now=datetime(2026, 10, 25, 12, tzinfo=timezone.utc),
    )

    assert (invalid_timezone.allowed, invalid_timezone.reason_code) == (
        False,
        "background_quiet_hours_invalid",
    )
    assert (incomplete_quota.allowed, incomplete_quota.reason_code) == (
        False,
        "background_request_quota_invalid",
    )
