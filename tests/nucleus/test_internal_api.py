# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""The managed private port rejects direct or stale business requests."""

from __future__ import annotations

import json
import secrets

import pytest

from nucleus.api import InternalRequestGuard
from nucleus.lifecycle import NucleusLifecycle
from stella_contracts.control import ControlIdentity, TrustedActor, internal_headers


def _lifecycle() -> NucleusLifecycle:
    return NucleusLifecycle(
        instance_id="private-api-test",
        controller_boot_id="controller-test-0001",
        generation_id="generation-test-0001",
        revision_id="revision-test-0001",
        launch_token=secrets.token_hex(32),
        internal_host="127.0.0.1",
        internal_port=18080,
        force_exit=lambda _code: None,
    )


@pytest.mark.asyncio
async def test_private_business_api_requires_current_capability_identity_and_actor() -> None:
    lifecycle = _lifecycle()
    identity = ControlIdentity(
        instance_id=lifecycle.instance_id,
        controller_boot_id=lifecycle.controller_boot_id,
        generation_id=lifecycle.generation_id,
        revision_id=lifecycle.revision_id,
    )
    actor = TrustedActor(actor_id="admin用户", kind="admin", authentication="jwt")
    accepted: list[dict] = []
    seen_internal_headers: list[bytes] = []

    async def inner(scope, _receive, send):
        accepted.append(scope["state"]["stella_actor"])
        seen_internal_headers.extend(
            name.lower()
            for name, _value in scope.get("headers", ())
            if bytes(name).lower().startswith(b"x-stella-")
        )
        body = json.dumps(scope["state"]["stella_actor"], ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": body})

    app = InternalRequestGuard(inner, lifecycle)

    async def request(headers=(), *, peer="127.0.0.1"):
        sent = []
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            sent.append(message)
        await app(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "path": "/api/v1/business",
                "headers": [(name.encode("ascii"), value.encode("ascii")) for name, value in headers],
                "client": (peer, 1234),
                "server": ("127.0.0.1", 18080),
            },
            receive,
            send,
        )
        status = next(item["status"] for item in sent if item["type"] == "http.response.start")
        body = next(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
        return status, json.loads(body) if body else {}

    valid = internal_headers(
        identity=identity,
        capability=lifecycle.launch_token,
        actor=actor,
        request_id="request-test-0001",
    )

    # Caller-supplied actor headers do not establish trust without the private capability.
    forged = {key: value for key, value in valid.items() if key != "x-stella-internal-capability"}
    status, payload = await request(forged.items())
    assert status == 401
    assert payload["error"]["code"] == "unauthorized"

    wrong_capability = dict(valid, **{"x-stella-internal-capability": "0" * 64})
    status, _ = await request(wrong_capability.items())
    assert status == 401

    wrong_protocol = dict(valid, **{"x-stella-control-protocol-version": "99"})
    status, payload = await request(wrong_protocol.items())
    assert status == 409
    assert payload["error"]["code"] == "protocol_mismatch"

    wrong_generation = dict(valid, **{"x-stella-generation-id": "generation-stale-0001"})
    status, payload = await request(wrong_generation.items())
    assert status == 409
    assert payload["error"]["code"] == "identity_mismatch"

    forged_actor_type = dict(valid, **{"x-stella-actor-authentication": "system"})
    status, payload = await request(forged_actor_type.items())
    assert status == 403
    assert payload["error"]["code"] == "untrusted_actor"

    status, actor_payload = await request(valid.items())
    assert status == 200
    assert actor_payload == actor.to_dict()
    assert accepted == [actor.to_dict()]
    assert seen_internal_headers == []

    status, payload = await request(valid.items(), peer="192.0.2.1")
    assert status == 404
    assert payload["error"]["code"] == "not_found"
