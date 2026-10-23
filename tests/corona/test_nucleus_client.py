# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Corona mints identity headers and rejects stale health/lifecycle replies."""

from __future__ import annotations

import base64

import pytest
from starlette.requests import Request

from corona.nucleus_client import NucleusClient, NucleusProtocolError
from stella_contracts.control import (
    CONTROL_PROTOCOL_VERSION,
    DRAIN_PATH,
    ControlIdentity,
    TrustedActor,
)
from webui import security
from webui.responses import ApiError


def _client() -> NucleusClient:
    return NucleusClient(
        "127.0.0.1",
        18080,
        identity=ControlIdentity(
            instance_id="client-test",
            controller_boot_id="controller-client-0001",
            generation_id="generation-client-0001",
            revision_id="revision-client-0001",
        ),
        capability="a" * 64,
    )


def test_forward_headers_strip_browser_control_and_auth_headers() -> None:
    client = _client()
    actor = TrustedActor("admin user", "admin", "jwt")
    headers = client.forward_headers(
        [
            ("Authorization", "Bearer browser-token"),
            ("Cookie", "stella_webui_jwt=browser-token"),
            ("X-Stella-Internal-Capability", "forged-capability"),
            ("X-Stella-Generation-ID", "stale-generation"),
            ("X-Platform-Signature", "platform-signature"),
            ("Accept", "application/json"),
        ],
        actor=actor,
        request_id="request-forward-0001",
    )
    assert "authorization" not in headers
    assert "cookie" not in headers
    assert headers["x-stella-internal-capability"] == "a" * 64
    assert headers["x-stella-generation-id"] == "generation-client-0001"
    assert headers["x-stella-actor-id"] == base64.urlsafe_b64encode(
        actor.actor_id.encode("utf-8")
    ).decode("ascii").rstrip("=")
    assert headers["x-platform-signature"] == "platform-signature"
    assert headers["accept"] == "application/json"

    adapter_headers = client.forward_headers(
        [("Authorization", "Bearer platform-adapter-token"), ("Cookie", "untrusted=cookie")],
        actor=TrustedActor("onebot-v11", "adapter", "adapter"),
        request_id="request-adapter-0001",
    )
    assert adapter_headers["authorization"] == "Bearer platform-adapter-token"
    assert "cookie" not in adapter_headers


def test_browser_actor_is_derived_only_after_corona_jwt_validation(tmp_path) -> None:
    security.configure_auth_runtime(stella_home=tmp_path, token_ttl_hours=1)
    try:
        record = security.setup_admin("admin-user", "correct horse battery")
        token, _expiry = security.create_token(record)
        request = _request({"authorization": f"Bearer {token}"})
        headers = _client().forward_browser_headers(
            request,
            [("Authorization", f"Bearer {token}"), ("X-Stella-Actor-ID", "forged")],
        )
        encoded_actor = headers["x-stella-actor-id"]
        actor_id = base64.urlsafe_b64decode(encoded_actor + "=" * (-len(encoded_actor) % 4))
        assert actor_id.decode("utf-8") == "admin-user"
        assert headers["x-stella-actor-kind"] == "admin"
        assert headers["x-stella-actor-authentication"] == "jwt"
        assert "authorization" not in headers

        bad_request = _request({"authorization": "Bearer forged"})
        with pytest.raises(ApiError) as exc:
            _client().forward_browser_headers(bad_request)
        assert exc.value.status_code == 401
    finally:
        security.reset_auth_runtime()


def test_health_protocol_and_identity_are_checked_before_core_readiness() -> None:
    client = _client()
    client._request = lambda *_args, **_kwargs: (
        200,
        {
            "control_protocol_version": CONTROL_PROTOCOL_VERSION + 1,
            **client.identity.to_payload(),
            "ready": True,
        },
    )
    with pytest.raises(NucleusProtocolError, match="protocol_mismatch"):
        client.health()

    client._request = lambda *_args, **_kwargs: (
        200,
        {
            "control_protocol_version": CONTROL_PROTOCOL_VERSION,
            **client.identity.to_payload(),
            "generation_id": "generation-old-0001",
            "ready": True,
        },
    )
    with pytest.raises(NucleusProtocolError, match="identity_mismatch"):
        client.health()


def test_late_or_wrong_generation_lifecycle_ack_is_rejected() -> None:
    client = _client()
    response = {
        "ok": True,
        "control_protocol_version": CONTROL_PROTOCOL_VERSION,
        **client.identity.to_payload(),
        "operation_id": "old-operation-0001",
    }
    client._request = lambda *_args, **_kwargs: (202, response)
    with pytest.raises(NucleusProtocolError, match="late_ack"):
        client.lifecycle(DRAIN_PATH, operation_id="current-operation-0001")

    stale_generation = dict(response)
    stale_generation["operation_id"] = "current-operation-0001"
    stale_generation["generation_id"] = "generation-old-0001"
    client._request = lambda *_args, **_kwargs: (202, stale_generation)
    with pytest.raises(NucleusProtocolError, match="identity_mismatch"):
        client.lifecycle(DRAIN_PATH, operation_id="current-operation-0001")


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/business",
            "raw_path": b"/api/v1/business",
            "query_string": b"",
            "headers": [
                (name.lower().encode("ascii"), value.encode("ascii"))
                for name, value in headers.items()
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8080),
        }
    )
