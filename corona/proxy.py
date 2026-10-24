# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Explicit, authenticated HTTP proxy for the Nucleus business API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from corona.nucleus_client import NucleusProtocolError
from corona.routes import methods_for_path, route_owner
from stella_contracts.control import ControlContractError, TrustedActor
from webui.auth import AuthContext, require_auth
from webui.responses import error

_HOP_BY_HOP = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authenticate",
        b"proxy-authorization",
        b"te",
        b"trailer",
        b"transfer-encoding",
        b"upgrade",
    }
)


class ProxyResponse(Response):
    """ASGI response that relays upstream header multiplicity and body chunks."""

    def __init__(self, *, status_code: int, headers, body, close) -> None:
        self.status_code = int(status_code)
        self.raw_headers = list(headers)
        self.body = body
        self.close = close
        # FastAPI's routing layer attaches dependency background tasks to any
        # returned Response instance, so this field is part of its contract.
        self.background = None

    async def __call__(self, scope, receive, send) -> None:
        try:
            await send(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": self.raw_headers,
                }
            )
            if scope.get(
                "method", "GET"
            ).upper() != "HEAD" and self.status_code not in {
                204,
                304,
            }:
                async for chunk in self.body:
                    await send(
                        {
                            "type": "http.response.body",
                            "body": chunk,
                            "more_body": True,
                        }
                    )
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            await self.close()
        if self.background is not None:
            await self.background()


def response_headers(raw_headers):
    connection_tokens = set()
    for name, value in raw_headers:
        if name.lower() == b"connection":
            connection_tokens.update(
                token.strip().lower() for token in value.split(b",") if token.strip()
            )
    excluded = _HOP_BY_HOP | connection_tokens
    return [
        (bytes(name).lower(), bytes(value))
        for name, value in raw_headers
        if bytes(name).lower() not in excluded
    ]


def create_business_proxy_endpoint(supervisor: Any):
    async def proxy(
        request: Request,
        business_path: str,
        auth: Annotated[AuthContext, Depends(require_auth)],
    ):
        path = request.url.path
        method = request.method.upper()
        owner = route_owner(method, path)
        if owner != "nucleus":
            methods = methods_for_path(path)
            if methods:
                return JSONResponse(
                    error("方法不允许", {"allow": sorted(methods)}),
                    status_code=405,
                    headers={"Allow": ", ".join(sorted(methods))},
                )
            return JSONResponse(error("接口不存在"), status_code=404)

        try:
            actor = TrustedActor(
                actor_id=auth.username,
                kind="admin",
                authentication="jwt",
            )
        except ControlContractError:
            return JSONResponse(error("未授权"), status_code=401)

        client = supervisor.business_client()
        if client is None:
            return JSONResponse(
                error("核心当前不可用", {"code": "core_unavailable"}),
                status_code=503,
                headers={"Retry-After": "1"},
            )
        try:
            return await client.proxy_http(request, actor)
        except NucleusProtocolError as exc:
            if exc.code == "core_unavailable":
                return JSONResponse(
                    error("核心当前不可用", {"code": exc.code}),
                    status_code=503,
                    headers={"Retry-After": "1"},
                )
            return JSONResponse(
                error("核心请求失败", {"code": "core_protocol_error"}),
                status_code=502,
            )

    return proxy
