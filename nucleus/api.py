# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Authenticate Corona-to-Nucleus business requests on the private listener."""

from __future__ import annotations

import hmac
import ipaddress
import json
from typing import Any

from nucleus.lifecycle import NucleusLifecycle
from stella_contracts.control import (
    CONTROL_PROTOCOL_VERSION,
    HEADER_ACTOR_AUTH,
    HEADER_ACTOR_ID,
    HEADER_ACTOR_KIND,
    HEADER_CAPABILITY,
    HEADER_CONTROLLER,
    HEADER_GENERATION,
    HEADER_INSTANCE,
    HEADER_PROTOCOL,
    HEADER_REQUEST_ID,
    HEADER_REVISION,
    ControlContractError,
    ControlIdentity,
    TrustedActor,
    actor_id_from_header,
    valid_request_id,
)


class InternalRequestGuard:
    """Require this generation's capability, protocol, identity, and actor."""

    def __init__(self, application: Any, lifecycle: NucleusLifecycle) -> None:
        self.application = application
        self.lifecycle = lifecycle
        self.identity = ControlIdentity(
            instance_id=lifecycle.instance_id,
            controller_boot_id=lifecycle.controller_boot_id,
            generation_id=lifecycle.generation_id,
            revision_id=lifecycle.revision_id,
        )

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        scope_type = scope.get("type")
        if scope_type not in {"http", "websocket"}:
            await self.application(scope, receive, send)
            return

        status, code, actor = self._authorize(scope)
        if status:
            if scope_type == "http":
                await _send_json(send, status, {"ok": False, "error": {"code": code}})
            else:
                # Before websocket.accept, close rejects the handshake.
                close_code = 4401 if status == 401 else 4409 if status == 409 else 4403
                await send({"type": "websocket.close", "code": close_code, "reason": code})
            return

        trusted_scope = dict(scope)
        state = dict(scope.get("state") or {})
        assert actor is not None
        state["stella_actor"] = actor.to_dict()
        state["stella_internal_authenticated"] = True
        state["stella_request_id"] = _single_header(
            scope.get("headers", ()), HEADER_REQUEST_ID.encode("ascii")
        )
        trusted_scope["state"] = state
        trusted_scope["headers"] = [
            (name, value)
            for name, value in scope.get("headers", ())
            if not bytes(name).lower().startswith(b"x-stella-")
        ]
        await self.application(trusted_scope, receive, send)

    def _authorize(self, scope: dict[str, Any]) -> tuple[int, str, TrustedActor | None]:
        try:
            peer = ipaddress.ip_address((scope.get("client") or (None,))[0])
        except (ValueError, TypeError, IndexError):
            return 404, "not_found", None
        if not peer.is_loopback:
            return 404, "not_found", None

        raw_headers = scope.get("headers", ())
        values = _required_headers(raw_headers)
        if values is None:
            return 401, "unauthorized", None
        capability = values.get(HEADER_CAPABILITY)
        expected_capability = self.lifecycle.launch_token.encode("ascii")
        if capability is None or not hmac.compare_digest(
            capability, expected_capability
        ):
            return 401, "unauthorized", None

        if values.get(HEADER_PROTOCOL) != str(CONTROL_PROTOCOL_VERSION).encode("ascii"):
            return 409, "protocol_mismatch", None
        expected = {
            HEADER_INSTANCE: self.identity.instance_id,
            HEADER_CONTROLLER: self.identity.controller_boot_id,
            HEADER_GENERATION: self.identity.generation_id,
            HEADER_REVISION: self.identity.revision_id,
        }
        for name, value in expected.items():
            supplied = values.get(name)
            if supplied is None or not hmac.compare_digest(
                supplied, value.encode("ascii")
            ):
                return 409, "identity_mismatch", None

        try:
            request_id = values[HEADER_REQUEST_ID].decode("ascii")
        except (KeyError, UnicodeDecodeError):
            return 400, "invalid_request", None
        if not valid_request_id(request_id):
            return 400, "invalid_request", None
        try:
            decoded = {
                HEADER_ACTOR_ID: actor_id_from_header(values[HEADER_ACTOR_ID]),
                HEADER_ACTOR_KIND: values[HEADER_ACTOR_KIND].decode("ascii"),
                HEADER_ACTOR_AUTH: values[HEADER_ACTOR_AUTH].decode("ascii"),
            }
            actor = TrustedActor(
                actor_id=decoded[HEADER_ACTOR_ID],
                kind=decoded[HEADER_ACTOR_KIND],
                authentication=decoded[HEADER_ACTOR_AUTH],
            )
        except (KeyError, UnicodeDecodeError, ControlContractError):
            return 403, "untrusted_actor", None
        return 0, "", actor


def _required_headers(raw_headers: Any) -> dict[str, bytes] | None:
    required = {
        HEADER_PROTOCOL,
        HEADER_CAPABILITY,
        HEADER_INSTANCE,
        HEADER_CONTROLLER,
        HEADER_GENERATION,
        HEADER_REVISION,
        HEADER_ACTOR_ID,
        HEADER_ACTOR_KIND,
        HEADER_ACTOR_AUTH,
        HEADER_REQUEST_ID,
    }
    values: dict[str, bytes] = {}
    for name, value in raw_headers:
        try:
            lower = bytes(name).decode("ascii").lower()
        except UnicodeDecodeError:
            continue
        if lower in required:
            if lower in values:
                return None
            values[lower] = bytes(value)
    return values if required.issubset(values) else None


def _single_header(raw_headers: Any, name: bytes) -> str:
    for key, value in raw_headers:
        if bytes(key).lower() == name:
            try:
                return bytes(value).decode("ascii")
            except UnicodeDecodeError:
                return ""
    return ""


async def _send_json(send: Any, status: int, body: dict[str, Any]) -> None:
    encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"cache-control", b"no-store"),
                (b"content-length", str(len(encoded)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": encoded})
