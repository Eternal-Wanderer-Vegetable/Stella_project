# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Versioned, unambiguous codecs for transport identity keys."""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

from core.transport.models import BotRef, SceneRef

_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _encode(prefix: str, payload: list[Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{prefix}.{token}"


def _decode(key: str, prefix: str) -> Any:
    if not isinstance(key, str):
        raise ValueError("identity key must be a string")
    marker = f"{prefix}."
    if not key.startswith(marker):
        raise ValueError(f"identity key must start with {marker!r}")
    token = key[len(marker) :]
    if not token or not _KEY_RE.fullmatch(token):
        raise ValueError("identity key contains invalid base64url data")
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != token:
            raise ValueError("identity key is not canonically encoded")
        return json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("identity key payload is malformed") from exc


def conversation_key_v2(bot: BotRef, scene: SceneRef) -> str:
    """Encode the complete bot+scene identity without delimiter ambiguity."""
    if not isinstance(bot, BotRef) or not isinstance(scene, SceneRef):
        raise ValueError("bot and scene must use the transport identity models")
    return _encode(
        "c2",
        [
            2,
            bot.connection_id,
            bot.adapter,
            bot.platform_scope,
            bot.self_id,
            scene.kind,
            list(scene.parent_path),
            scene.scene_id,
            scene.thread_id,
        ],
    )


def decode_conversation_key_v2(key: str) -> tuple[BotRef, SceneRef]:
    """Decode a canonical V2 key; legacy colon-delimited keys are rejected."""
    payload = _decode(key, "c2")
    if (
        not isinstance(payload, list)
        or len(payload) != 9
        or payload[0] != 2
        or not all(isinstance(value, str) for value in payload[1:6])
        or not isinstance(payload[6], list)
        or not all(isinstance(value, str) for value in payload[6])
        or not isinstance(payload[7], str)
        or (payload[8] is not None and not isinstance(payload[8], str))
    ):
        raise ValueError("conversation key payload does not match V2 schema")
    bot = BotRef(
        connection_id=payload[1],
        adapter=payload[2],
        platform_scope=payload[3],
        self_id=payload[4],
    )
    scene = SceneRef(
        kind=payload[5],
        parent_path=tuple(payload[6]),
        scene_id=payload[7],
        thread_id=payload[8],
    )
    if conversation_key_v2(bot, scene) != key:
        raise ValueError("conversation key is not canonical")
    return bot, scene


def subject_key_v2(identity_domain: str, raw_user_id: str) -> str:
    """Create a domain-qualified subject key; never coerce opaque IDs to numbers."""
    if not isinstance(identity_domain, str) or identity_domain == "":
        raise ValueError("identity_domain must be a non-empty string")
    if not isinstance(raw_user_id, str) or raw_user_id == "":
        raise ValueError("raw_user_id must be a non-empty string")
    return _encode("u2", [2, identity_domain, raw_user_id])


def decode_subject_key_v2(key: str) -> tuple[str, str]:
    payload = _decode(key, "u2")
    if (
        not isinstance(payload, list)
        or len(payload) != 3
        or payload[0] != 2
        or not all(isinstance(value, str) and value for value in payload[1:])
    ):
        raise ValueError("subject key payload does not match V2 schema")
    domain, raw_user_id = payload[1:]
    if subject_key_v2(domain, raw_user_id) != key:
        raise ValueError("subject key is not canonical")
    return domain, raw_user_id
