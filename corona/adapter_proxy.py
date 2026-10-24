# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Stable public ingress for the generation-bound Nucleus adapter routes."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import ipaddress
import re
import urllib.parse
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from corona.nucleus_client import NucleusProtocolError
from stella_contracts.control import ControlContractError, TrustedActor
from stella_contracts.route_catalog import AdapterRoute

_STATUS_PATH = "/stella/status"
_ONEBOT_PREFIX = "/onebot"
_BAD_PERCENT = re.compile(rb"%(?![0-9a-fA-F]{2})")
_FORWARDED_HEADERS = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-forwarded-port",
        "x-forwarded-prefix",
    }
)


class AdapterProxyMiddleware:
    """Route catalogued platform traffic before WebUI static/SPA fallthrough."""

    def __init__(self, app: Any, *, supervisor: Any) -> None:
        self.app = app
        self.supervisor = supervisor

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        scope_type = scope.get("type")
        if scope_type not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if _unsafe_path(scope):
            if scope_type == "http":
                await _json(send, 400, "invalid_path")
            else:
                await send(
                    {"type": "websocket.close", "code": 4400, "reason": "invalid_path"}
                )
            return
        if path == _STATUS_PATH and scope_type == "http":
            await self._status(scope, receive, send)
            return
        if path == "/_nucleus" or path.startswith("/_nucleus/"):
            if scope_type == "http":
                await _json(send, 404, "not_found")
            else:
                await send(
                    {"type": "websocket.close", "code": 4404, "reason": "not_found"}
                )
            return
        if path == "/_corona/v1/health" and scope_type == "http":
            if _is_loopback_peer(scope):
                await self.app(scope, receive, send)
            else:
                await _json(send, 404, "not_found")
            return
        if path == "/_corona" or path.startswith("/_corona/"):
            if scope_type == "http":
                await _json(send, 404, "not_found")
            else:
                await send(
                    {"type": "websocket.close", "code": 4404, "reason": "not_found"}
                )
            return

        catalog = getattr(self.supervisor.snapshot, "route_catalog", None)
        protocol = "websocket" if scope_type == "websocket" else "http"
        matches = catalog.path_matches(path, protocol) if catalog is not None else ()
        method = str(scope.get("method", "GET")).upper()
        route = catalog.match(path, method, protocol) if catalog is not None else None
        claimed = catalog.claims_path(path) if catalog is not None else False
        if path == _ONEBOT_PREFIX or path.startswith(_ONEBOT_PREFIX + "/"):
            claimed = True

        if route is None:
            alternate = (
                catalog.slash_alternate(path, protocol) if catalog is not None else None
            )
            if alternate is not None and scope_type == "http":
                raw_path = scope.get("raw_path")
                if not isinstance(raw_path, bytes):
                    raw_path = path.encode("ascii")
                raw_path = raw_path.split(b"?", 1)[0]
                alternate_raw = (
                    raw_path[:-1] if raw_path.endswith(b"/") else raw_path + b"/"
                )
                query = scope.get("query_string", b"")
                location = alternate_raw + (b"?" + query if query else b"")
                redirect = Response(
                    status_code=307,
                    headers={"location": location.decode("latin-1")},
                )
                await redirect(scope, receive, send)
                return
            if matches or claimed:
                if scope_type == "http":
                    methods = sorted(
                        {method for item in matches for method in item.methods}
                    )
                    headers = {"Allow": ", ".join(methods)} if methods else None
                    await _json(
                        send,
                        405 if matches else 404,
                        "method_not_allowed" if matches else "not_found",
                        headers=headers,
                    )
                else:
                    await send(
                        {"type": "websocket.close", "code": 4404, "reason": "not_found"}
                    )
                return
            await self.app(scope, receive, send)
            return

        client = (
            self.supervisor.business_client_for_catalog(catalog)
            if catalog is not None
            else None
        )
        if client is None:
            if scope_type == "http":
                await _json(send, 503, "core_unavailable", headers={"Retry-After": "1"})
            else:
                await send(
                    {
                        "type": "websocket.close",
                        "code": 1013,
                        "reason": "core_unavailable",
                    }
                )
            return

        if scope_type == "http":
            await self._http(client, scope, receive, send, route)
        else:
            await self._websocket(client, scope, receive, send, route)

    async def _status(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if str(scope.get("method", "GET")).upper() != "GET":
            await _json(send, 405, "method_not_allowed", headers={"Allow": "GET"})
            return
        if not _is_loopback_peer(scope):
            await _json(send, 403, "forbidden")
            return
        client = self.supervisor.business_client()
        if client is None:
            await _json(send, 503, "core_unavailable", headers={"Retry-After": "1"})
            return
        try:
            response = await client.proxy_http(
                Request(scope, receive),
                TrustedActor("stella-status", "system", "system"),
            )
        except NucleusProtocolError as exc:
            await _proxy_error(send, exc)
            return
        await response(scope, receive, send)

    async def _http(
        self,
        client: Any,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
        route: AdapterRoute,
    ) -> None:
        try:
            response = await client.proxy_adapter_http(
                Request(scope, receive), route.adapter
            )
        except NucleusProtocolError as exc:
            await _proxy_error(send, exc)
            return
        await response(scope, receive, send)

    async def _websocket(
        self,
        client: Any,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
        route: AdapterRoute,
    ) -> None:
        try:
            await _proxy_websocket(client, scope, receive, send, route)
        except asyncio.CancelledError:
            raise


async def _proxy_websocket(
    client: Any, scope: dict[str, Any], receive: Any, send: Any, route: AdapterRoute
) -> None:
    try:
        from websockets import connect
        from websockets.exceptions import ConnectionClosed
    except ImportError:
        await send(
            {"type": "websocket.close", "code": 1013, "reason": "websocket_unavailable"}
        )
        return

    connector = _disable_websocket_redirects(connect)
    if connector is None:
        await send(
            {
                "type": "websocket.close",
                "code": 1013,
                "reason": "websocket_redirect_guard_unavailable",
            }
        )
        return

    first = await receive()
    if first.get("type") != "websocket.connect":
        await send(
            {"type": "websocket.close", "code": 4400, "reason": "invalid_handshake"}
        )
        return
    raw_path = scope.get("raw_path")
    if not isinstance(raw_path, bytes) or not raw_path.startswith(b"/"):
        raw_path = str(scope.get("path", "/")).encode("ascii", errors="strict")
    raw_path = raw_path.split(b"?", 1)[0]
    query = scope.get("query_string", b"")
    target = raw_path + (b"?" + query if query else b"")
    import httpx

    upstream_url = str(
        httpx.URL(scheme="ws", host=client.host, port=client.port, raw_path=target)
    )
    incoming = [
        (bytes(name).decode("latin-1").lower(), bytes(value).decode("latin-1"))
        for name, value in scope.get("headers", ())
    ]
    origins = [value for name, value in incoming if name == "origin"]
    if len(origins) > 1:
        await send(
            {"type": "websocket.close", "code": 4400, "reason": "invalid_origin"}
        )
        return
    origin = origins[0] if origins else None
    protocol_headers = {"connection", "host", "upgrade", *_FORWARDED_HEADERS}
    platform_headers = [
        (name, value)
        for name, value in incoming
        if name not in protocol_headers
        and not name.startswith("sec-websocket-")
        and name != "origin"
    ]
    try:
        actor = TrustedActor(route.adapter, "adapter", "adapter")
        forwarded = client.forward_header_pairs(
            platform_headers,
            actor=actor,
            preserve_platform_credentials=True,
        )
    except (ControlContractError, NucleusProtocolError):
        await send(
            {"type": "websocket.close", "code": 4403, "reason": "untrusted_adapter"}
        )
        return

    parameters = inspect.signature(connector).parameters
    header_option = (
        "additional_headers" if "additional_headers" in parameters else "extra_headers"
    )
    options: dict[str, Any] = {
        "origin": origin,
        "subprotocols": list(scope.get("subprotocols") or ()),
        "compression": None,
        "open_timeout": 5,
        "close_timeout": 5,
        "ping_interval": 20,
        "ping_timeout": 20,
    }
    options[header_option] = forwarded
    if "proxy" in parameters:
        options["proxy"] = None
    if "user_agent_header" in parameters:
        options["user_agent_header"] = None
    if "max_size" in parameters:
        options["max_size"] = 4 * 1024 * 1024
    if "max_queue" in parameters:
        options["max_queue"] = 4
    if "write_limit" in parameters:
        options["write_limit"] = 32 * 1024
    try:
        upstream = await connector(upstream_url, **options)
    except asyncio.CancelledError:
        raise
    except Exception:
        await send(
            {"type": "websocket.close", "code": 1013, "reason": "core_unavailable"}
        )
        return

    await send({"type": "websocket.accept", "subprotocol": upstream.subprotocol})

    async def client_to_core() -> None:
        while True:
            message = await receive()
            if message.get("type") == "websocket.disconnect":
                code = message.get("code", 1000)
                if not isinstance(code, int) or code in {1004, 1005, 1006}:
                    code = 1000
                await upstream.close(
                    code=code, reason=_close_reason(message.get("reason", ""))
                )
                return
            if message.get("type") != "websocket.receive":
                continue
            if message.get("text") is not None:
                await upstream.send(message["text"])
            elif message.get("bytes") is not None:
                await upstream.send(message["bytes"])

    async def core_to_client() -> None:
        async for message in upstream:
            if isinstance(message, str):
                await send({"type": "websocket.send", "text": message})
            else:
                await send({"type": "websocket.send", "bytes": message})

    client_task = asyncio.create_task(client_to_core(), name="corona-adapter-ws-client")
    core_task = asyncio.create_task(core_to_client(), name="corona-adapter-ws-core")
    client_disconnected = False
    try:
        done, pending = await asyncio.wait(
            {client_task, core_task}, return_when=asyncio.FIRST_COMPLETED
        )
        client_disconnected = client_task in done and not client_task.cancelled()
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if not client_disconnected:
            code = upstream.close_code or 1000
            if code in {1004, 1005, 1006} or not 1000 <= code <= 4999:
                code = 1011
            await send(
                {
                    "type": "websocket.close",
                    "code": code,
                    "reason": _close_reason(upstream.close_reason or ""),
                }
            )
    except ConnectionClosed:
        code = upstream.close_code or 1011
        if code in {1004, 1005, 1006} or not 1000 <= code <= 4999:
            code = 1011
        await send(
            {
                "type": "websocket.close",
                "code": code,
                "reason": _close_reason(upstream.close_reason or "upstream_closed"),
            }
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        await send({"type": "websocket.close", "code": 1011, "reason": "proxy_failed"})
    finally:
        for task in (client_task, core_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(client_task, core_task, return_exceptions=True)
        with contextlib.suppress(Exception):
            await upstream.close()


def _unsafe_path(scope: dict[str, Any]) -> bool:
    raw_path = scope.get("raw_path")
    path = str(scope.get("path", ""))
    if not isinstance(raw_path, bytes):
        raw_path = path.encode("utf-8", errors="ignore")
    raw_path = raw_path.split(b"?", 1)[0]
    return bool(
        _BAD_PERCENT.search(raw_path)
        or b"%2f" in raw_path.lower()
        or b"%5c" in raw_path.lower()
        or "\\" in path
        or "//" in path
        or path.startswith("//")
        or any(segment in {".", ".."} for segment in path.split("/"))
        or any(
            urllib.parse.unquote_to_bytes(segment).lower() in {b".", b".."}
            for segment in raw_path.split(b"/")
        )
    )


def _disable_websocket_redirects(connect: Any) -> Any | None:
    """Use the websockets API hook that refuses every HTTP redirect."""
    if not inspect.isclass(connect) or not callable(
        getattr(connect, "process_redirect", None)
    ):
        return None

    class NoRedirectConnect(connect):
        def process_redirect(self, exc):
            return exc

    return NoRedirectConnect


def _is_loopback_peer(scope: dict[str, Any]) -> bool:
    client = scope.get("client")
    try:
        return bool(client and ipaddress.ip_address(client[0]).is_loopback)
    except (ValueError, TypeError, IndexError):
        return False


async def _json(
    send: Any, status: int, code: str, *, headers: dict[str, str] | None = None
) -> None:
    body = JSONResponse(
        {"ok": False, "error": {"code": code}}, status_code=status, headers=headers
    )
    await body({"type": "http", "method": "GET"}, None, send)


async def _proxy_error(send: Any, exc: NucleusProtocolError) -> None:
    if exc.code == "core_unavailable":
        await _json(send, 503, "core_unavailable", headers={"Retry-After": "1"})
    else:
        await _json(send, 502, "core_protocol_error")


def _close_reason(value: Any) -> str:
    text = str(value or "")
    encoded = text.encode("utf-8", errors="replace")[:123]
    while True:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
