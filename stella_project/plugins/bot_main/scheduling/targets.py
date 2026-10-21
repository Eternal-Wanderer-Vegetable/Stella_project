# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Durable target helpers for the QQ scheduling compatibility path."""

from __future__ import annotations

import json

from core.transport.keys import conversation_key_v2
from core.transport.models import BotRef, SceneRef, UserRef
from core.transport.outbound import DeliveryTarget


def legacy_qq_target(bot_id: str, group_id: int | str) -> DeliveryTarget | None:
    """Build the exact historical OneBot v11 group route, or fail closed."""
    bot_id = str(bot_id or "")
    group_text = str(group_id or "")
    if not bot_id.isdigit() or int(bot_id) <= 0:
        return None
    if not group_text.isdigit() or int(group_text) <= 0:
        return None
    bot = BotRef(f"legacy-qq:{bot_id}", "onebot-v11", "qq", bot_id)
    return DeliveryTarget(bot=bot, scene=SceneRef("group", group_text))


def target_scope_key(target: DeliveryTarget) -> str:
    return conversation_key_v2(target.bot, target.scene)


def dump_target(target: DeliveryTarget | None) -> str:
    return json.dumps(target.dump(), ensure_ascii=False, sort_keys=True) if target else "{}"


def load_target(value: str | dict | None) -> DeliveryTarget | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None
    if not isinstance(value, dict) or not value:
        return None
    try:
        return DeliveryTarget.load(value)
    except (TypeError, ValueError, KeyError):
        return None


def qq_subject_key(user_id: int | str) -> str:
    """QQ account-domain subject key; the raw user id remains opaque text."""
    return UserRef("qq:client", str(user_id)).subject_key


__all__ = [
    "dump_target",
    "legacy_qq_target",
    "load_target",
    "qq_subject_key",
    "target_scope_key",
]
