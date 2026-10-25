# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Exact Bot resolution for durable background deliveries."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.transport.background_policy import evaluate_background_policy
from core.transport.models import BotRef
from core.transport.outbound import (
    DeliveryResult,
    DeliveryStatus,
    DeliveryTarget,
    OutboundMessage,
    get_outbound_service,
)


def _is_legacy_qq(bot_ref: BotRef) -> bool:
    return (
        bot_ref.adapter == "onebot-v11"
        and bot_ref.platform_scope == "qq"
        and bot_ref.connection_id == f"legacy-qq:{bot_ref.self_id}"
    )


def _resolve_legacy_qq_bot(bot_ref: BotRef) -> Any | None:
    if not _is_legacy_qq(bot_ref):
        return None
    from nonebot import get_bots

    bot = get_bots().get(bot_ref.self_id)
    if bot is None or str(getattr(bot, "self_id", "")) != bot_ref.self_id:
        return None
    adapter_getter = getattr(getattr(bot, "adapter", None), "get_name", None)
    adapter_name = adapter_getter() if callable(adapter_getter) else ""
    if not isinstance(adapter_name, str) or not adapter_name:
        return None
    if "".join(c.lower() for c in adapter_name if c.isalnum()) != "onebotv11":
        return None
    return bot


def _registered_bot_binding(service: Any, bot_ref: BotRef) -> tuple[Any, int] | None:
    registry = getattr(service, "registry", None)
    resolver = getattr(registry, "resolve_bot_binding", None)
    if not callable(resolver):
        return None
    return resolver(bot_ref)


def _configured_transport_settings_json() -> str | None:
    """Read the active non-secret policy bundle from the resolved runtime config."""
    try:
        from config import settings
    except Exception:
        return None
    value = getattr(settings, "STELLA_TRANSPORT_SETTINGS_JSON", None)
    return value if isinstance(value, str) else None


def resolve_background_bot(bot_ref: BotRef) -> Any | None:
    """Resolve an exact registry binding first, then the exact legacy QQ Bot."""
    binding = _registered_bot_binding(get_outbound_service(), bot_ref)
    if binding is not None:
        return binding[0]
    return _resolve_legacy_qq_bot(bot_ref)


async def send_background_message(
    target: DeliveryTarget, message: OutboundMessage
) -> DeliveryResult:
    service = get_outbound_service()
    binding = _registered_bot_binding(service, target.bot)
    if binding is not None:
        if not _is_legacy_qq(target.bot):
            registry = service.registry
            capabilities = registry.capabilities_for(target)
            if capabilities is None or not capabilities.proactive_send:
                return DeliveryResult(
                    target,
                    DeliveryStatus.UNSUPPORTED,
                    error_code="background_proactive_capability_missing",
                )
            decision = evaluate_background_policy(
                target, _configured_transport_settings_json()
            )
            if not decision.allowed:
                return DeliveryResult(
                    target,
                    DeliveryStatus.UNSUPPORTED,
                    error_code=decision.reason_code,
                )
            instance_capabilities = capabilities
            if decision.request_bucket is not None:
                instance_capabilities = replace(
                    capabilities,
                    requests_per_window=None,
                    rate_window_seconds=None,
                    rate_limit_buckets=(
                        *capabilities.rate_limit_buckets,
                        decision.request_bucket,
                    ),
                )
            return await service.send(
                target,
                message,
                instance_capabilities=instance_capabilities,
            )
        # Let OutboundService capture and revalidate the registry generation itself.
        return await service.send(target, message)

    if not _is_legacy_qq(target.bot):
        return DeliveryResult(
            target, DeliveryStatus.FAILED, error_code="exact_bot_binding_missing"
        )
    bot = _resolve_legacy_qq_bot(target.bot)
    if bot is None:
        return DeliveryResult(
            target, DeliveryStatus.FAILED, error_code="exact_bot_binding_missing"
        )
    return await service.send(target, message, bot_handle=bot)


__all__ = ["resolve_background_bot", "send_background_message"]
