# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Pure policy-layer composition with explicit precedence and provenance."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

from stella_bootstrap.transport_settings import (
    TransportSettingsError,
    validate_policy_values,
)

_PRECEDENCE = {
    "global_defaults": 0,
    "platform_template": 1,
    "connection_default": 2,
    "profile": 3,
    "scene": 4,
    "runtime": 5,
}
_DEFAULTS: Mapping[str, object] = MappingProxyType(
    {
        "capture_enabled": False,
        "llm_enabled": False,
        "wake_mode": "mention",
        "wake_prefixes": (),
        "reply_mention": False,
        "reply_quote": False,
        "format_mode": "native",
        "segmentation": "auto",
        "proactive_enabled": False,
        "quiet_hours": None,
        "requests_per_window": None,
        "rate_window_seconds": None,
    }
)


@dataclass(frozen=True, slots=True)
class PolicyLayer:
    name: str
    values: Mapping[str, object]
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.name not in _PRECEDENCE:
            raise TransportSettingsError(f"unsupported policy layer: {self.name}")
        if self.name == "runtime":
            if (
                self.expires_at is None
                or self.expires_at.tzinfo is None
                or self.expires_at.utcoffset() is None
            ):
                raise TransportSettingsError("runtime policy overrides require a timezone expiry")
        elif self.expires_at is not None:
            raise TransportSettingsError("only runtime policy overrides may expire")
        validated = validate_policy_values(dict(self.values), self.name)
        for name, value in validated.items():
            if isinstance(value, dict):
                validated[name] = MappingProxyType(dict(value))
        object.__setattr__(self, "values", MappingProxyType(validated))


@dataclass(frozen=True, slots=True)
class EffectivePolicy:
    values: Mapping[str, object]
    sources: Mapping[str, str]


def resolve_policy(
    layers: Iterable[PolicyLayer],
    *,
    now: datetime | None = None,
) -> EffectivePolicy:
    """Resolve global < platform < connection < profile < scene < runtime.

    A field absent from a layer inherits. Explicit false and empty arrays replace
    lower-priority values. Expired runtime overrides are ignored.
    """
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise TransportSettingsError("policy resolution time must include a timezone")

    ordered: list[PolicyLayer] = []
    seen: set[str] = set()
    for layer in layers:
        if layer.name in seen:
            raise TransportSettingsError(f"conflicting duplicate policy layer: {layer.name}")
        seen.add(layer.name)
        ordered.append(layer)
    ordered.sort(key=lambda layer: _PRECEDENCE[layer.name])

    values = dict(_DEFAULTS)
    sources = dict.fromkeys(values, "system_default")
    for layer in ordered:
        if (
            layer.name == "runtime"
            and layer.expires_at is not None
            and instant.astimezone(timezone.utc)
            >= layer.expires_at.astimezone(timezone.utc)
        ):
            continue
        for name, value in layer.values.items():
            values[name] = value
            sources[name] = layer.name

    return EffectivePolicy(
        values=MappingProxyType(dict(values)),
        sources=MappingProxyType(dict(sources)),
    )


__all__ = ["EffectivePolicy", "PolicyLayer", "resolve_policy"]
