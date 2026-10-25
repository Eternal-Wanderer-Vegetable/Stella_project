# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Fail-closed policy evaluation for durable proactive deliveries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.transport.capabilities import RateLimitBucket
from core.transport.outbound import DeliveryTarget
from core.transport.policy import PolicyLayer, resolve_policy
from stella_bootstrap.transport_settings import (
    TransportSettingsError,
    TransportSettingsV1,
    parse_transport_settings_json,
)


@dataclass(frozen=True, slots=True)
class BackgroundPolicyDecision:
    """A bounded policy result and optional scene-scoped request quota."""

    allowed: bool
    reason_code: str = ""
    request_bucket: RateLimitBucket | None = None


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _layers_for_target(settings: TransportSettingsV1, target: DeliveryTarget) -> list[PolicyLayer]:
    """Build the same ordered policy stack as ingress for one exact target."""
    bot = target.bot
    connections = [
        connection
        for connection in settings.connections
        if (
            connection.connection_id,
            connection.adapter,
            connection.platform_scope,
            connection.self_id,
        ) == (bot.connection_id, bot.adapter, bot.platform_scope, bot.self_id)
    ]
    if len(connections) != 1 or not connections[0].enabled:
        raise ValueError("background_connection_not_enabled")
    connection = connections[0]

    scene = target.scene
    bindings = [
        binding
        for binding in settings.bindings
        if (
            binding.connection_id,
            binding.scene_kind,
            binding.scene_id,
            binding.parent_path,
            binding.thread_id,
        ) == (
            bot.connection_id,
            scene.kind,
            scene.scene_id,
            scene.parent_path,
            scene.thread_id,
        )
    ]
    if len(bindings) != 1:
        raise ValueError("background_scene_binding_missing")
    scene_binding = bindings[0]
    profiles = {
        profile.policy_profile_id: profile for profile in settings.profiles
    }
    profile = profiles.get(scene_binding.policy_profile_id)
    if profile is None:
        raise ValueError("background_policy_profile_missing")

    layers = [PolicyLayer("global_defaults", _thaw(settings.defaults))]
    template = settings.platform_templates.get(connection.adapter)
    if template is not None:
        layers.append(PolicyLayer("platform_template", _thaw(template)))
    layers.append(PolicyLayer("connection_default", _thaw(connection.policy)))
    layers.append(PolicyLayer("profile", _thaw(profile.policy)))
    layers.append(PolicyLayer("scene", _thaw(scene_binding.policy)))
    return layers


def _quiet_hours_active(value: object, now: datetime) -> bool:
    if value is None:
        return False
    if not isinstance(value, Mapping):
        raise ValueError("quiet_hours_invalid")
    try:
        start = time.fromisoformat(str(value["start"]))
        end = time.fromisoformat(str(value["end"]))
        zone = ZoneInfo(str(value["timezone"]))
        local_time = now.astimezone(zone).time().replace(tzinfo=None, second=0, microsecond=0)
    except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("quiet_hours_invalid") from exc

    # Equal endpoints mean a full-day quiet window. The end is exclusive otherwise.
    if start == end:
        return True
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def evaluate_background_policy(
    target: DeliveryTarget,
    settings_json: str | None,
    *,
    now: datetime | None = None,
) -> BackgroundPolicyDecision:
    """Require explicit connection, scene, proactive and time-window policy."""
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        return BackgroundPolicyDecision(False, "background_policy_time_invalid")
    try:
        settings = parse_transport_settings_json(settings_json)
        effective = resolve_policy(_layers_for_target(settings, target), now=instant)
    except (TransportSettingsError, ValueError) as exc:
        reason = str(exc)
        if reason.startswith("background_"):
            return BackgroundPolicyDecision(False, reason)
        return BackgroundPolicyDecision(False, "background_settings_invalid")

    if effective.values.get("proactive_enabled") is not True:
        return BackgroundPolicyDecision(False, "background_proactive_disabled")
    try:
        if _quiet_hours_active(effective.values.get("quiet_hours"), instant):
            return BackgroundPolicyDecision(False, "background_quiet_hours")
    except ValueError:
        return BackgroundPolicyDecision(False, "background_quiet_hours_invalid")

    count = effective.values.get("requests_per_window")
    window = effective.values.get("rate_window_seconds")
    if (count is None) != (window is None):
        return BackgroundPolicyDecision(False, "background_request_quota_invalid")
    if count is None:
        return BackgroundPolicyDecision(True)
    try:
        bucket = RateLimitBucket(
            name="effective-policy",
            scope="scene",
            category="request",
            limit=count,  # type: ignore[arg-type]
            window_seconds=window,  # type: ignore[arg-type]
        )
    except (TypeError, ValueError):
        return BackgroundPolicyDecision(False, "background_request_quota_invalid")
    return BackgroundPolicyDecision(True, request_bucket=bucket)


__all__ = ["BackgroundPolicyDecision", "evaluate_background_policy"]
