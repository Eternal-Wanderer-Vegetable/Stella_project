# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Adapter and instance capability descriptions used before outbound effects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from core.transport.outbound import DeliveryTarget


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

    def __post_init__(self) -> None:
        if not self.adapter or not self.platform_scope:
            raise ValueError("adapter and platform_scope are required")
        if self.max_text_length is not None and self.max_text_length <= 0:
            raise ValueError("max_text_length must be positive or None")
        if self.requests_per_window is not None and self.requests_per_window <= 0:
            raise ValueError("requests_per_window must be positive or None")
        for name in ("rate_window_seconds", "send_window_seconds"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive or None")

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
        for name in ("max_text_length", "requests_per_window", "rate_window_seconds", "send_window_seconds"):
            base, limit = getattr(self, name), getattr(instance, name)
            values[name] = limit if base is None else base if limit is None else min(base, limit)
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
