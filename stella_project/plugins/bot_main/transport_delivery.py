# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Exact Bot resolution for durable background deliveries."""

from __future__ import annotations

from typing import Any

from core.transport.models import BotRef
from core.transport.outbound import (
    DeliveryResult,
    DeliveryStatus,
    DeliveryTarget,
    OutboundMessage,
    get_outbound_service,
)


def resolve_background_bot(bot_ref: BotRef) -> Any | None:
    """Resolve only the explicitly named legacy QQ Bot; never use get_bot()."""
    if (
        bot_ref.adapter != "onebot-v11"
        or bot_ref.platform_scope != "qq"
        or bot_ref.connection_id != f"legacy-qq:{bot_ref.self_id}"
    ):
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


async def send_background_message(
    target: DeliveryTarget, message: OutboundMessage
) -> DeliveryResult:
    bot = resolve_background_bot(target.bot)
    if bot is None:
        return DeliveryResult(
            target, DeliveryStatus.FAILED, error_code="exact_bot_binding_missing"
        )
    return await get_outbound_service().send(target, message, bot_handle=bot)


__all__ = ["resolve_background_bot", "send_background_message"]
