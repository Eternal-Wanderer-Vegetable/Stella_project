# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Versioned Corona client for one authenticated Nucleus generation."""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.parse
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
    new_request_id,
    validate_health_payload,
    validate_lifecycle_ack,
)
from stella_contracts.route_catalog import (
    NUCLEUS_ROUTES_PATH,
    AdapterRouteCatalog,
    validate_route_catalog,
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
        "expect",
    }
)
_FORWARDED_HEADERS = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-prefix",
        "x-forwarded-proto",
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
        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
        ):
            raise ValueError("Nucleus client port is invalid")
        if (
            not isinstance(capability, str)
            or not capability
            or not capability.isascii()
        ):
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

    def route_catalog(self) -> AdapterRouteCatalog:
        """Read and validate the exact route directory for this generation."""
        status, payload = self._request("GET", NUCLEUS_ROUTES_PATH)
        if status != 200:
            raise NucleusProtocolError("route_catalog_unavailable")
        try:
            return validate_route_catalog(payload, self.identity)
        except ControlContractError as exc:
            raise NucleusProtocolError(str(exc)) from exc

    def lifecycle(
        self, path: str, *, operation_id: str, **extra: object
    ) -> dict[str, Any]:
        if path not in {DRAIN_PATH, STOP_PATH}:
            raise NucleusProtocolError("unknown_lifecycle_operation")
        try:
            payload = lifecycle_payload(
                self.identity, operation_id=operation_id, **extra
            )
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
        return dict(
            self.forward_header_pairs(incoming, actor=actor, request_id=request_id)
        )

    def forward_header_pairs(
        self,
        incoming: Mapping[str, str] | list[tuple[str, str]],
        *,
        actor: TrustedActor,
        request_id: str | None = None,
        preserve_platform_credentials: bool = False,
    ) -> list[tuple[str, str]]:
        """Preserve repeatable application headers while replacing trust headers."""
        pairs = list(incoming.items() if isinstance(incoming, Mapping) else incoming)
        connection_tokens = {
            token.strip().lower()
            for raw_name, raw_value in pairs
            if str(raw_name).lower().strip() == "connection"
            for token in str(raw_value).split(",")
            if token.strip()
        }
        excluded = _HOP_BY_HOP | connection_tokens
        forwarded: list[tuple[str, str]] = []
        for raw_name, raw_value in pairs:
            name = str(raw_name).lower().strip()
            if (
                not name
                or name.startswith("x-stella-")
                or name in excluded
                or name in _FORWARDED_HEADERS
                or (name == "authorization" and actor.kind != "adapter")
                or (name == "cookie" and not preserve_platform_credentials)
                or (name == "content-length" and not preserve_platform_credentials)
                or "\r" in name
                or "\n" in name
            ):
                continue
            value = str(raw_value)
            if "\r" in value or "\n" in value:
                continue
            forwarded.append((name, value))
        forwarded.extend(
            internal_headers(
                identity=self.identity,
                capability=self.capability,
                actor=actor,
                request_id=request_id,
            ).items()
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

    async def proxy_http(self, request: Any, actor: TrustedActor) -> Any:
        """Stream one already-authorized API request to this exact generation."""
        return await self._proxy_http(
            request, actor, preserve_platform_credentials=False
        )

    async def proxy_adapter_http(self, request: Any, adapter: str) -> Any:
        """Stream an adapter request while retaining its protocol credentials."""
        try:
            actor = TrustedActor(adapter, "adapter", "adapter")
        except ControlContractError as exc:
            raise NucleusProtocolError("untrusted_adapter") from exc
        return await self._proxy_http(
            request, actor, preserve_platform_credentials=True
        )

    async def _proxy_http(
        self,
        request: Any,
        actor: TrustedActor,
        *,
        preserve_platform_credentials: bool,
    ) -> Any:
        """Forward a streamed request without allowing a caller-selected upstream."""
        import httpx

        from corona.proxy import ProxyResponse, response_headers

        raw_path = request.scope.get("raw_path")
        if not isinstance(raw_path, bytes) or not raw_path.startswith(b"/"):
            raw_path = request.url.path.encode("ascii", errors="strict")
        if b"%2f" in raw_path.lower() or b"%5c" in raw_path.lower():
            raise NucleusProtocolError("unsafe_encoded_path")
        query = request.scope.get("query_string", b"")
        target = raw_path + (b"?" + query if query else b"")
        url = httpx.URL(scheme="http", host=self.host, port=self.port, raw_path=target)
        incoming = [
            (bytes(name).decode("latin-1"), bytes(value).decode("latin-1"))
            for name, value in request.scope.get("headers", ())
        ]
        content_lengths = [
            value.strip()
            for name, value in incoming
            if name.lower() == "content-length"
        ]
        if preserve_platform_credentials and (
            len(content_lengths) > 1
            or (content_lengths and not content_lengths[0].isascii())
            or (content_lengths and not content_lengths[0].isdigit())
        ):
            raise NucleusProtocolError("unsafe_content_length")
        headers = self.forward_header_pairs(
            incoming,
            actor=actor,
            preserve_platform_credentials=preserve_platform_credentials,
        )

        async def request_body():
            async for chunk in request.stream():
                if chunk:
                    yield chunk

        client = httpx.AsyncClient(
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(None, connect=self.timeout),
        )
        try:
            outgoing = client.build_request(
                request.method,
                url,
                headers=headers,
                content=request_body(),
            )
            response = await client.send(outgoing, stream=True)
        except (httpx.RequestError, OSError, TimeoutError) as exc:
            await client.aclose()
            raise NucleusProtocolError("core_unavailable") from exc
        except BaseException:
            await client.aclose()
            raise

        async def close() -> None:
            await response.aclose()
            await client.aclose()

        outgoing_headers = response_headers(response.headers.raw)
        if preserve_platform_credentials:
            outgoing_headers = self._rewrite_private_locations(outgoing_headers)
        return ProxyResponse(
            status_code=response.status_code,
            headers=outgoing_headers,
            body=response.aiter_raw(),
            close=close,
        )

    def _rewrite_private_locations(
        self, headers: list[tuple[bytes, bytes]]
    ) -> list[tuple[bytes, bytes]]:
        """Never disclose Nucleus's private loopback origin in a redirect."""
        rewritten: list[tuple[bytes, bytes]] = []
        for name, value in headers:
            if name.lower() != b"location":
                rewritten.append((name, value))
                continue
            try:
                parsed = urllib.parse.urlsplit(value.decode("latin-1"))
                if (
                    parsed.scheme.lower() in {"http", "https"}
                    and (parsed.hostname or "").lower() == self.host.lower()
                    and parsed.port == self.port
                ):
                    relative = urllib.parse.urlunsplit(
                        ("", "", parsed.path or "/", parsed.query, parsed.fragment)
                    )
                    value = relative.encode("latin-1")
            except (UnicodeError, ValueError):
                pass
            rewritten.append((name, value))
        return rewritten

    def group_bindings(
        self, action: str, payload: dict[str, object], *, actor: TrustedActor
    ) -> dict[str, Any]:
        """Call one private, actor-bound group binding operation."""
        paths = {
            "validate": "/_nucleus/v1/private/groups/bindings/validate",
            "apply": "/_nucleus/v1/private/groups/bindings/apply",
            "rollback": "/_nucleus/v1/private/groups/bindings/rollback",
        }
        path = paths.get(action)
        if path is None:
            raise NucleusProtocolError("unknown_group_bindings_operation")
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = self.forward_headers(
            {"Content-Type": "application/json"},
            actor=actor,
            request_id=new_request_id(),
        )
        request = urllib.request.Request(
            f"http://{self.host}:{self.port}{path}",
            data=encoded,
            headers=headers,
            method="POST",
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
            response = json.loads(body)
        except (UnicodeDecodeError, ValueError) as exc:
            raise NucleusProtocolError("invalid_response") from exc
        if not isinstance(response, dict):
            raise NucleusProtocolError("invalid_response")
        if status < 200 or status >= 300 or response.get("status") != "ok":
            data = response.get("data")
            code = data.get("code") if isinstance(data, dict) else None
            message = response.get("message")
            raise NucleusProtocolError(
                str(code or message or f"group_bindings_http_{status}")
            )
        data = response.get("data")
        if not isinstance(data, dict):
            raise NucleusProtocolError("invalid_response")
        return data

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
