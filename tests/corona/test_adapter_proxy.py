# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Real-process HTTP, SSE, WebSocket, and raw-peer contracts for CN07."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from corona.adapter_proxy import AdapterProxyMiddleware
from corona.bootstrap import prepare_corona_bootstrap
from corona.supervisor import CoreSupervisor
from stella_bootstrap.config import build_config_revision, write_revision

ROOT = Path(__file__).resolve().parents[2]


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _bootstrap(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        f"HOST=127.0.0.1\nPORT={_port()}\nWEBUI_ENABLED=true\n"
        "WEBUI_SERVE_DIST=false\nWEBUI_TOKEN_TTL_HOURS=168\n"
        "WEBUI_LOGIN_RATELIMIT_PER_MIN=5\n",
        encoding="utf-8",
    )
    instance_id = "cn07-adapter-proxy"
    revision = build_config_revision(
        project_root=ROOT,
        stella_home=home,
        external_environment={"DB_PATH": str(tmp_path / "business" / "memory.db")},
    )
    revision_file = write_revision(home, instance_id, revision)
    return prepare_corona_bootstrap(
        {
            "STELLA_HOME": str(home),
            "STELLA_CONFIG_REVISION_FILE": str(revision_file),
            "STELLA_INSTANCE_ID": instance_id,
        },
        project_root=ROOT,
    )


_FAKE_PLATFORM_CORE = r"""
import asyncio
import json
import os
import sys

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response, StreamingResponse

from nucleus.api import InternalRequestGuard
from nucleus.lifecycle import ManagedNucleusASGI, NucleusLifecycle
from stella_contracts.control import ControlIdentity
from stella_contracts.route_catalog import AdapterRoute, create_route_catalog

instance_id = os.environ["STELLA_INSTANCE_ID"]
controller_boot_id = os.environ["STELLA_CONTROLLER_BOOT_ID"]
generation_id = os.environ["STELLA_GENERATION_ID"]
revision_id = os.path.basename(os.path.dirname(os.environ["STELLA_CONFIG_REVISION_FILE"]))
token = os.environ["STELLA_LAUNCH_TOKEN"]
host = os.environ["STELLA_INTERNAL_HOST"]
port = int(os.environ["STELLA_INTERNAL_PORT"])
identity = ControlIdentity(instance_id, controller_boot_id, generation_id, revision_id)
lifecycle = NucleusLifecycle(
    instance_id=instance_id,
    controller_boot_id=controller_boot_id,
    generation_id=generation_id,
    revision_id=revision_id,
    launch_token=token,
    internal_host=host,
    internal_port=port,
)
routes = create_route_catalog(identity, [
    AdapterRoute("OneBot V11", "/onebot/v11/", "http", ("POST",), "OneBot V11 Root HTTP"),
    AdapterRoute("OneBot V11", "/onebot/v11/http", "http", ("POST",), "OneBot V11 Root HTTP"),
    AdapterRoute("OneBot V11", "/onebot/v11/http/", "http", ("POST",), "OneBot V11 HTTP Slash"),
    AdapterRoute("OneBot V11", "/onebot/v11/events", "http", ("GET",), "OneBot V11 Events"),
    AdapterRoute("OneBot V11", "/onebot/v11/download", "http", ("GET",), "OneBot V11 Download"),
    AdapterRoute("OneBot V11", "/onebot/v11/", "websocket", (), "OneBot V11 Root WS"),
    AdapterRoute("OneBot V11", "/onebot/v11/ws", "websocket", (), "OneBot V11 Root WebSocket"),
    AdapterRoute("OneBot V11", "/onebot/v11/redirect", "websocket", (), "OneBot V11 Redirect Probe"),
])
api = FastAPI()

@api.post("/onebot/v11/")
@api.post("/onebot/v11/http/")
@api.post("/onebot/v11/http")
async def onebot_http(request: Request):
    body = await request.body()
    response = Response(body, status_code=202, media_type="application/octet-stream")
    response.headers["x-platform-signature-seen"] = request.headers.get("x-signature", "")
    response.headers["x-platform-authorization-seen"] = request.headers.get("authorization", "")
    response.headers["x-platform-cookie-seen"] = request.headers.get("cookie", "")
    response.headers["x-seen-raw-path"] = request.scope["raw_path"].decode("ascii")
    response.headers["x-seen-raw-query"] = request.scope["query_string"].decode("ascii")
    response.headers["x-stella-spoof-seen"] = request.headers.get("x-stella-generation-id", "")
    response.headers["x-adapter-actor"] = request.state.stella_actor["actor_id"]
    response.raw_headers.extend([
        (b"set-cookie", b"platform-a=1; Path=/"),
        (b"set-cookie", b"platform-b=2; Path=/"),
    ])
    return response

@api.get("/onebot/v11/events")
async def onebot_events():
    async def stream():
        yield b"data: first\n\n"
        await asyncio.sleep(0)
        yield b"data: second\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")

@api.get("/onebot/v11/download")
async def onebot_download():
    async def stream():
        yield b"download-"
        await asyncio.sleep(0)
        yield b"complete"
    return StreamingResponse(stream(), media_type="application/octet-stream")

@api.get("/stella/status")
async def status(request: Request):
    return {
        "status": "ok",
        "actor": request.state.stella_actor,
        "raw_peer": request.client.host if request.client else None,
    }

@api.websocket("/onebot/v11/")
@api.websocket("/onebot/v11/ws")
async def onebot_ws(websocket: WebSocket):
    protocol = "onebot" if "onebot" in websocket.scope.get("subprotocols", []) else None
    await websocket.accept(subprotocol=protocol)
    while True:
        text = await websocket.receive_text()
        if text == "close":
            await websocket.close(code=4001, reason="platform-restart")
            return
        await websocket.send_text(json.dumps({
            "message": text,
            "authorization": websocket.headers.get("authorization"),
            "cookie": websocket.headers.get("cookie"),
            "signature": websocket.headers.get("x-signature"),
            "origin": websocket.headers.get("origin"),
            "raw_path": websocket.scope["raw_path"].decode("ascii"),
            "raw_query": websocket.scope["query_string"].decode("ascii"),
            "actor": websocket.scope["state"]["stella_actor"],
            "spoofed_generation": websocket.headers.get("x-stella-generation-id"),
        }))

@api.websocket("/onebot/v11/redirect")
async def redirect_ws(websocket: WebSocket):
    await websocket.send_denial_response(Response(status_code=307, headers={"Location": "/onebot/v11/ws"}))

server = uvicorn.Server(uvicorn.Config(
    ManagedNucleusASGI(InternalRequestGuard(api, lifecycle), lifecycle, routes),
    host=host,
    port=port,
    log_level="critical",
    access_log=False,
))
lifecycle.attach_server(server)
server.run()
"""


def _proxy_app(supervisor: CoreSupervisor) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AdapterProxyMiddleware, supervisor=supervisor)

    @app.api_route(
        "/{_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    async def spa_fallback(_path: str):
        return HTMLResponse("spa")

    return app


@pytest.mark.asyncio
async def test_onebot_http_sse_download_websocket_reconnect_and_status_peer(
    tmp_path: Path,
) -> None:
    supervisor = CoreSupervisor(
        _bootstrap(tmp_path),
        readiness_timeout=5,
        poll_interval=0.03,
        max_attempts=1,
        command_factory=lambda _bootstrap: [sys.executable, "-c", _FAKE_PLATFORM_CORE],
    )
    try:
        first = await supervisor.start()
        assert first.phase == "ready"
        assert first.route_catalog is not None
        assert first.route_catalog.identity.generation_id == first.generation_id

        with TestClient(_proxy_app(supervisor)) as client:
            body = bytes(range(256)) * 1024
            response = client.post(
                "/onebot/v11/http?access_token=a%2Fb&x=%E4%B8%AD",
                content=body,
                headers={
                    "Authorization": "Bearer onebot-token",
                    "Cookie": "platform-session=onebot",
                    "X-Signature": "signed-raw-body",
                    "X-Stella-Generation-ID": "forged-old-generation",
                },
            )
            assert response.status_code == 202
            assert response.content == body
            assert response.headers["x-platform-signature-seen"] == "signed-raw-body"
            assert (
                response.headers["x-platform-authorization-seen"]
                == "Bearer onebot-token"
            )
            assert (
                response.headers["x-platform-cookie-seen"] == "platform-session=onebot"
            )
            assert (
                response.headers["x-seen-raw-query"] == "access_token=a%2Fb&x=%E4%B8%AD"
            )
            assert response.headers["x-stella-spoof-seen"] == ""
            assert response.headers["x-adapter-actor"] == "OneBot V11"
            assert len(response.headers.get_list("set-cookie")) == 2
            root_without_slash = client.post(
                "/onebot/v11?access_token=stable",
                content=b"root-event",
                follow_redirects=False,
            )
            assert root_without_slash.status_code == 307
            assert (
                root_without_slash.headers["location"]
                == "/onebot/v11/?access_token=stable"
            )
            root_with_slash = client.post(
                "/onebot/v11/",
                content=b"root-event",
                headers={"X-Signature": "root-signature"},
            )
            assert root_with_slash.status_code == 202
            assert root_with_slash.content == b"root-event"

            events = client.get("/onebot/v11/events")
            assert events.status_code == 200
            assert events.headers["content-type"].startswith("text/event-stream")
            assert events.text == "data: first\n\ndata: second\n\n"
            download = client.get("/onebot/v11/download")
            assert download.content == b"download-complete"
            assert client.get("/onebot/v11/not-registered").status_code == 404
            assert client.get("/_nucleus/v1/routes").status_code == 404
            assert client.get("/_corona/private-path").status_code == 404
            assert client.get("/unclaimed-spa").text == "spa"

            with client.websocket_connect(
                "/onebot/v11/ws?access_token=a%2Fb",
                subprotocols=["onebot"],
                headers={
                    "Authorization": "Bearer onebot-ws-token",
                    "Cookie": "platform-ws=session",
                    "X-Signature": "ws-signature",
                    "Origin": "https://platform.example",
                    "X-Stella-Generation-ID": "forged-ws-generation",
                    "X-Forwarded-For": "127.0.0.1",
                },
            ) as websocket:
                assert websocket.accepted_subprotocol == "onebot"
                websocket.send_text("hello")
                result = json.loads(websocket.receive_text())
                assert result["message"] == "hello"
                assert result["authorization"] == "Bearer onebot-ws-token"
                assert result["cookie"] == "platform-ws=session"
                assert result["signature"] == "ws-signature"
                assert result["origin"] == "https://platform.example"
                assert result["raw_query"] == "access_token=a%2Fb"
                assert result["spoofed_generation"] is None
                assert result["actor"]["actor_id"] == "OneBot V11"
                websocket.send_text("close")
                closed = websocket.receive()
                assert closed["type"] == "websocket.close"
                assert closed["code"] == 4001
                assert closed["reason"] == "platform-restart"

            with client.websocket_connect(
                "/onebot/v11/", subprotocols=["onebot"]
            ) as websocket:
                websocket.send_text("root-ws")
                assert json.loads(websocket.receive_text())["message"] == "root-ws"

            with (
                pytest.raises(WebSocketDisconnect) as refused_redirect,
                client.websocket_connect("/onebot/v11/redirect"),
            ):
                pass
            assert refused_redirect.value.code == 1013

            remote = client.get(
                "/stella/status", headers={"X-Forwarded-For": "127.0.0.1"}
            )
            assert remote.status_code == 403

            first_generation = first.generation_id
            await supervisor.stop()
            unavailable = client.post("/onebot/v11/http", content=b"not-forwarded")
            assert unavailable.status_code == 503
            restarted = await supervisor.start()
            assert restarted.phase == "ready"
            assert restarted.generation_id != first_generation
            reconnected_http = client.post(
                "/onebot/v11/http", content=b"http-reconnected"
            )
            assert reconnected_http.status_code == 202
            assert reconnected_http.content == b"http-reconnected"
            with client.websocket_connect(
                "/onebot/v11/ws", subprotocols=["onebot"]
            ) as websocket:
                websocket.send_text("reconnected")
                result = json.loads(websocket.receive_text())
                assert result["message"] == "reconnected"
                assert result["actor"]["actor_id"] == "OneBot V11"

        middleware = AdapterProxyMiddleware(lambda *_args: None, supervisor=supervisor)
        for peer, expected in (
            (("198.51.100.77", 1234), 403),
            (("127.0.0.1", 1234), 200),
        ):
            messages = [{"type": "http.request", "body": b"", "more_body": False}]
            sent = []

            async def receive(messages=messages):
                return messages.pop(0) if messages else {"type": "http.disconnect"}

            async def send(message, sent=sent):
                sent.append(message)

            await middleware(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.3"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": "/stella/status",
                    "raw_path": b"/stella/status",
                    "query_string": b"",
                    "headers": [(b"x-forwarded-for", b"127.0.0.1")],
                    "client": peer,
                    "server": ("127.0.0.1", 8080),
                },
                receive,
                send,
            )
            assert (
                next(
                    message["status"]
                    for message in sent
                    if message["type"] == "http.response.start"
                )
                == expected
            )
            if expected == 200:
                payload = json.loads(
                    next(
                        message["body"]
                        for message in sent
                        if message["type"] == "http.response.body"
                    )
                )
                assert payload["actor"]["kind"] == "system"
                assert payload["raw_peer"] == "127.0.0.1"
    finally:
        await supervisor.stop()


def test_encoded_separator_and_dot_segments_are_rejected_before_fallback() -> None:
    from corona.adapter_proxy import _unsafe_path

    assert _unsafe_path({"path": "/onebot/v11/a/b", "raw_path": b"/onebot/v11/a%2Fb"})
    assert _unsafe_path(
        {"path": "/onebot/v11/../secret", "raw_path": b"/onebot/v11/../secret"}
    )
    assert _unsafe_path(
        {"path": "/onebot/v11/%2e%2e/secret", "raw_path": b"/onebot/v11/%2e%2e/secret"}
    )
    assert _unsafe_path({"path": "/onebot//v11", "raw_path": b"/onebot//v11"})
    assert not _unsafe_path(
        {"path": "/onebot/v11/http", "raw_path": b"/onebot/v11/http"}
    )
