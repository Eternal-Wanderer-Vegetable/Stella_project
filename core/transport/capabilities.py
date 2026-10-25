# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Adapter and instance capability descriptions used before outbound effects."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from core.transport.outbound import DeliveryTarget


@dataclass(frozen=True, slots=True)
class RateLimitBucket:
    """One independently enforced outbound quota."""

    name: str
    scope: str
    category: str
    limit: int
    window_seconds: float

    def __post_init__(self) -> None:
        if not self.name or self.scope not in {"adapter", "connection", "scene", "target"}:
            raise ValueError("rate limit bucket needs a name and valid scope")
        if self.category not in {"api", "request"}:
            raise ValueError("rate limit category must be api or request")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit <= 0:
            raise ValueError("rate limit must be a positive integer")
        if (
            isinstance(self.window_seconds, bool)
            or not isinstance(self.window_seconds, (int, float))
            or not math.isfinite(self.window_seconds)
            or self.window_seconds <= 0
        ):
            raise ValueError("rate limit window must be finite and positive")
        object.__setattr__(self, "window_seconds", float(self.window_seconds))


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    adapter: str
    platform_scope: str
    passive_receive: bool = False
    private: bool = False
    group: bool = False
    channel: bool = False
    thread: bool = False
    quote: bool = False
    mention_user: bool = False
    mention_role: bool = False
    fetch_message: bool = False
    fetch_member: bool = False
    read_roles: bool = False
    upload_image: bool = False
    upload_file: bool = False
    proactive_send: bool = False
    max_text_length: int | None = None
    requests_per_window: int | None = None
    rate_window_seconds: float | None = None
    send_window_seconds: float | None = None
    rate_limit_buckets: tuple[RateLimitBucket, ...] = ()

    def __post_init__(self) -> None:
        if not self.adapter or not self.platform_scope:
            raise ValueError("adapter and platform_scope are required")
        if self.max_text_length is not None and self.max_text_length <= 0:
            raise ValueError("max_text_length must be positive or None")
        if self.requests_per_window is not None and (
            isinstance(self.requests_per_window, bool)
            or not isinstance(self.requests_per_window, int)
            or self.requests_per_window <= 0
        ):
            raise ValueError("requests_per_window must be positive or None")
        if (self.requests_per_window is None) != (self.rate_window_seconds is None):
            raise ValueError("requests_per_window and rate_window_seconds must be set together")
        for name in ("rate_window_seconds", "send_window_seconds"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and positive or None")
        buckets = tuple(self.rate_limit_buckets)
        if any(not isinstance(bucket, RateLimitBucket) for bucket in buckets):
            raise ValueError("rate_limit_buckets must contain RateLimitBucket values")
        identities = [(bucket.scope, bucket.category, bucket.name) for bucket in buckets]
        if len(identities) != len(set(identities)):
            raise ValueError("rate limit bucket identities must be unique")
        object.__setattr__(self, "rate_limit_buckets", buckets)

    def quota_buckets(self) -> tuple[RateLimitBucket, ...]:
        """Return explicit quotas plus the legacy adapter-scoped API quota."""
        buckets = list(self.rate_limit_buckets)
        has_legacy_adapter_quota = any(
            bucket.scope == "adapter" and bucket.category == "api" and bucket.name == "legacy"
            for bucket in buckets
        )
        if self.requests_per_window is not None and not has_legacy_adapter_quota:
            assert self.rate_window_seconds is not None
            buckets.append(RateLimitBucket(
                "legacy", "adapter", "api", self.requests_per_window, self.rate_window_seconds
            ))
        return tuple(buckets)

    def narrowed_by(self, instance: "AdapterCapabilities") -> "AdapterCapabilities":
        """Apply connection or scene restrictions; an instance cannot widen support."""
        if (self.adapter, self.platform_scope) != (instance.adapter, instance.platform_scope):
            raise ValueError("instance capability identity does not match adapter")
        values: dict[str, object] = {"adapter": self.adapter, "platform_scope": self.platform_scope}
        for name in (
            "passive_receive", "private", "group", "channel", "thread", "quote",
            "mention_user", "mention_role", "fetch_message", "fetch_member", "read_roles",
            "upload_image", "upload_file", "proactive_send",
        ):
            values[name] = bool(getattr(self, name) and getattr(instance, name))
        for name in ("max_text_length", "send_window_seconds"):
            base, limit = getattr(self, name), getattr(instance, name)
            values[name] = limit if base is None else base if limit is None else min(base, limit)
        # The legacy pair describes only the adapter bucket. Connection and
        # scene limits stay independent in rate_limit_buckets below.
        values["requests_per_window"] = self.requests_per_window
        values["rate_window_seconds"] = self.rate_window_seconds
        buckets = list(self.quota_buckets())
        instance_buckets = list(instance.rate_limit_buckets)
        if instance.requests_per_window is not None:
            assert instance.rate_window_seconds is not None
            instance_buckets.append(RateLimitBucket(
                "legacy", "connection", "api", instance.requests_per_window,
                instance.rate_window_seconds,
            ))
        for bucket in instance_buckets:
            same_identity = [
                current for current in buckets
                if (current.scope, current.category, current.name)
                == (bucket.scope, bucket.category, bucket.name)
            ]
            if not same_identity:
                buckets.append(bucket)
            elif bucket not in same_identity:
                # Distinct limits at the same scope are independent constraints;
                # preserve both instead of synthesizing a fieldwise-min bucket.
                candidate = f"instance:{bucket.name}"
                suffix = 2
                while any(
                    current.scope == bucket.scope
                    and current.category == bucket.category
                    and current.name == candidate
                    for current in buckets
                ):
                    candidate = f"instance:{bucket.name}:{suffix}"
                    suffix += 1
                buckets.append(replace(bucket, name=candidate))
        values["rate_limit_buckets"] = tuple(buckets)
        return AdapterCapabilities(**values)  # type: ignore[arg-type]


class CapabilityProvider(Protocol):
    def capabilities_for(self, target: "DeliveryTarget") -> AdapterCapabilities | None:
        """Return capabilities already narrowed for this connection and target."""


@dataclass(frozen=True, slots=True)
class StaticCapabilityProvider:
    capabilities: AdapterCapabilities

    def capabilities_for(self, target: "DeliveryTarget") -> AdapterCapabilities | None:
        if (
            target.bot.adapter != self.capabilities.adapter
            or target.bot.platform_scope != self.capabilities.platform_scope
        ):
            return None
        return self.capabilities


ONEBOT_V11_CAPABILITIES = AdapterCapabilities(
    adapter="onebot-v11",
    platform_scope="qq",
    passive_receive=True,
    private=True,
    group=True,
    quote=True,
    mention_user=True,
    fetch_message=True,
    fetch_member=True,
    read_roles=True,
    upload_image=True,
    upload_file=True,
    proactive_send=True,
)
