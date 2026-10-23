# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Versioned Corona client for one authenticated Nucleus generation."""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from stella_contracts.control import (
    DRAIN_PATH,
    HEALTH_PATH,
    STOP_PATH,
    ControlContractError,
    ControlIdentity,
    TrustedActor,
    internal_headers,
    lifecycle_payload,
    validate_health_payload,
    validate_lifecycle_ack,
)

_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
        "cookie",
        "content-length",
    }
)


class NucleusProtocolError(RuntimeError):
    """Nucleus did not answer with this generation's exact protocol contract."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


class NucleusClient:
    """Capability and identity-bound client for a single private Nucleus port."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        identity: ControlIdentity,
        capability: str,
        timeout: float = 2.0,
    ) -> None:
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError("Nucleus client requires a loopback endpoint")
        except ValueError as exc:
            raise ValueError("Nucleus client requires a loopback endpoint") from exc
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Nucleus client port is invalid")
        if not isinstance(capability, str) or not capability or not capability.isascii():
            raise ValueError("Nucleus capability is invalid")
        self.host = host
        self.port = port
        self.identity = identity
        self.capability = capability
        self.timeout = float(timeout)
        self._opener = urllib.request.build_opener(_NoRedirect())

    def health(self) -> tuple[int, dict[str, Any]]:
        status, payload = self._request("GET", HEALTH_PATH)
        if status == 200:
            try:
                validate_health_payload(payload, self.identity)
            except ControlContractError as exc:
                raise NucleusProtocolError(str(exc)) from exc
        return status, payload

    def lifecycle(
        self, path: str, *, operation_id: str, **extra: object
    ) -> dict[str, Any]:
        if path not in {DRAIN_PATH, STOP_PATH}:
            raise NucleusProtocolError("unknown_lifecycle_operation")
        try:
            payload = lifecycle_payload(self.identity, operation_id=operation_id, **extra)
        except ControlContractError as exc:
            raise NucleusProtocolError(str(exc)) from exc
        status, response = self._request("POST", path, payload)
        if status != 202:
            error = response.get("error", {})
            code = error.get("code") if isinstance(error, dict) else None
            raise NucleusProtocolError(str(code or f"lifecycle_http_{status}"))
        try:
            validate_lifecycle_ack(
                response, expected=self.identity, operation_id=operation_id
            )
        except ControlContractError as exc:
            raise NucleusProtocolError(str(exc)) from exc
        return response

    @staticmethod
    def trusted_browser_actor(request: Any) -> TrustedActor:
        """Validate the browser JWT in Corona and return only its trusted actor."""
        from webui.auth import require_auth

        context = require_auth(request)
        try:
            return TrustedActor(
                actor_id=context.username,
                kind="admin",
                authentication="jwt",
            )
        except ControlContractError as exc:
            raise NucleusProtocolError("untrusted_actor") from exc

    def forward_headers(
        self,
        incoming: Mapping[str, str] | list[tuple[str, str]],
        *,
        actor: TrustedActor,
        request_id: str | None = None,
    ) -> dict[str, str]:
        """Strip caller control/auth headers, then mint this generation's headers."""
        pairs = incoming.items() if isinstance(incoming, Mapping) else incoming
        forwarded: dict[str, str] = {}
        for raw_name, raw_value in pairs:
            name = str(raw_name).lower().strip()
            if (
                not name
                or name.startswith("x-stella-")
                or name in _HOP_BY_HOP
                or (name == "authorization" and actor.kind != "adapter")
                or "\r" in name
                or "\n" in name
            ):
                continue
            value = str(raw_value)
            if "\r" in value or "\n" in value:
                continue
            forwarded[name] = value
        forwarded.update(
            internal_headers(
                identity=self.identity,
                capability=self.capability,
                actor=actor,
                request_id=request_id,
            )
        )
        return forwarded

    def forward_browser_headers(
        self,
        request: Any,
        incoming: Mapping[str, str] | list[tuple[str, str]] | None = None,
        *,
        request_id: str | None = None,
    ) -> dict[str, str]:
        actor = self.trusted_browser_actor(request)
        if incoming is None:
            incoming = request.headers
        return self.forward_headers(incoming, actor=actor, request_id=request_id)

    def _request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> tuple[int, dict[str, Any]]:
        encoded = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"http://{self.host}:{self.port}{path}",
            data=encoded,
            headers={
                "Authorization": f"Bearer {self.capability}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status = response.status
                body = response.read(1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read(1024 * 1024 + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise NucleusProtocolError("core_unavailable") from exc
        if len(body) > 1024 * 1024:
            raise NucleusProtocolError("response_too_large")
        try:
            result = json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise NucleusProtocolError("invalid_response") from exc
        if not isinstance(result, dict):
            raise NucleusProtocolError("invalid_response")
        return status, result
