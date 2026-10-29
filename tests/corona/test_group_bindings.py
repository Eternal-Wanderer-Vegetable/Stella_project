# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Route ownership and crash-safe mixed group binding contracts."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from corona.app import create_corona_app
from corona.bootstrap import prepare_corona_bootstrap
from corona.config_store import ConfigStore
from corona.nucleus_client import NucleusClient, NucleusProtocolError
from corona.operations import OperationError, OperationManager
from corona.routes import (
    BUSINESS_ROUTE_KEYS,
    CONTROL_ROUTE_KEYS,
    MIXED_ROUTE_KEYS,
    ROUTE_OWNERSHIP,
)
from nucleus.api import InternalRequestGuard
from nucleus.group_bindings import (
    GroupBindingsStore,
    _files_with_bindings,
    _snapshot_digest,
)
from nucleus.routes import create_nucleus_business_app
from stella_bootstrap.config import build_config_revision, write_revision
from stella_contracts.control import ControlIdentity, TrustedActor, internal_headers
from webui.auth import AuthContext, require_auth
from webui.responses import ApiError

ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "cn06-groups-test"


def test_route_matrix_matches_plan_and_nucleus_business_assembly(
    tmp_path: Path,
) -> None:
    inventory = json.loads(
        (ROOT / "docs/plans/2026-10-23-corona-nucleus-inventory.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        (row["method"], row["path"], row["proposed_owner"])
        for row in inventory["webui_routes"]
    }
    # The initial route inventory is a frozen planning snapshot. These endpoints
    # were added afterward and are owned by Nucleus like the other business APIs.
    expected.add(("GET", "/api/v1/gravitas/status", "nucleus"))
    expected.add(("GET", "/api/v1/conversations/scenes", "nucleus"))
    expected.add(("GET", "/api/v1/conversations/messages", "nucleus"))
    assert set(ROUTE_OWNERSHIP) == expected
    assert (
        len(CONTROL_ROUTE_KEYS),
        len(BUSINESS_ROUTE_KEYS),
        len(MIXED_ROUTE_KEYS),
    ) == (
        21,
        114,
        1,
    )

    group_store = GroupBindingsStore(
        spaces_directory=tmp_path / "spaces",
        journal_path=tmp_path / "runtime" / "groups.sqlite3",
    )
    app = create_nucleus_business_app(group_bindings_store=group_store)
    assert app.state.route_keys == BUSINESS_ROUTE_KEYS
    assert {
        (method, route.path)
        for route in app.routes
        if hasattr(route, "methods")
        for method in route.methods or ()
        if (method, route.path) in BUSINESS_ROUTE_KEYS
    } == BUSINESS_ROUTE_KEYS
    assert not (app.state.route_keys & CONTROL_ROUTE_KEYS)


def test_group_binding_store_is_idempotent_and_compensates_exact_snapshot(
    tmp_path: Path,
) -> None:
    spaces = tmp_path / "spaces"
    spaces.mkdir()
    original = b'qq_groups = [1, 2]\nsystem_prompt = "friends.md"\n'
    (spaces / "friends.toml").write_bytes(original)
    (spaces / "work.toml").write_text("qq_groups = [3]\n", encoding="utf-8")
    store = GroupBindingsStore(
        spaces_directory=spaces,
        journal_path=tmp_path / "runtime" / "groups.sqlite3",
    )
    bindings, snapshot = store.validate(
        [
            {"group_id": "7", "space": "friends"},
            {"group_id": 8, "space": "new-space"},
            {"group_id": 7, "space": "friends"},
        ]
    )
    operation_id = "group-operation-0001"
    result = store.apply(
        operation_id=operation_id,
        bindings=bindings,
        expected_digest=snapshot["digest"],
    )
    assert result["applied"] is True
    assert (
        store.apply(
            operation_id=operation_id,
            bindings=bindings,
            expected_digest=snapshot["digest"],
        )
        == result
    )
    assert "qq_groups = [7]" in (spaces / "friends.toml").read_text()
    assert (spaces / "new-space.toml").exists()
    assert store.rollback(operation_id)["restored"] is True
    assert (spaces / "friends.toml").read_bytes() == original
    assert (spaces / "work.toml").read_text(encoding="utf-8") == "qq_groups = [3]\n"
    assert not (spaces / "new-space.toml").exists()
    assert store.rollback(operation_id)["restored"] is True


def test_group_binding_compensation_refuses_external_space_edit(tmp_path: Path) -> None:
    spaces = tmp_path / "spaces"
    spaces.mkdir()
    path = spaces / "friends.toml"
    path.write_text('qq_groups = [1]\nsystem_prompt = "friends.md"\n', encoding="utf-8")
    store = GroupBindingsStore(
        spaces_directory=spaces,
        journal_path=tmp_path / "runtime" / "groups.sqlite3",
    )
    bindings, snapshot = store.validate([{"group_id": 2, "space": "friends"}])
    store.apply(
        operation_id="group-operation-0002",
        bindings=bindings,
        expected_digest=snapshot["digest"],
    )
    path.write_text(
        'qq_groups = [99]\nsystem_prompt = "external.md"\n', encoding="utf-8"
    )
    result = store.rollback("group-operation-0002")
    assert result == {
        "operation_id": "group-operation-0002",
        "restored": False,
        "reason": "external_spaces_edit",
    }
    assert "99" in path.read_text(encoding="utf-8")


def test_group_binding_crash_recovery_preserves_unexpected_external_edit(
    tmp_path: Path,
) -> None:
    spaces = tmp_path / "spaces"
    spaces.mkdir()
    original = {
        "friends": b'qq_groups = [1]\nsystem_prompt = "friends.md"\n',
        "work": b"qq_groups = [2]\n",
    }
    for name, content in original.items():
        (spaces / f"{name}.toml").write_bytes(content)
    journal = tmp_path / "runtime" / "groups.sqlite3"
    store = GroupBindingsStore(spaces_directory=spaces, journal_path=journal)
    bindings, snapshot = store.validate([{"group_id": 7, "space": "friends"}])
    after = _files_with_bindings(original, bindings)
    store._insert_operation(
        operation_id="group-operation-interrupted",
        request_digest="request-digest",
        before=original,
        after=after,
        before_digest=snapshot["digest"],
        after_digest=_snapshot_digest(after),
        result={"operation_id": "group-operation-interrupted", "applied": True},
    )

    # Simulate a crash after one replacement and an operator edit before recovery.
    (spaces / "friends.toml").write_bytes(after["friends"])
    external_edit = b"qq_groups = [99]\nsystem_prompt = \"operator.md\"\n"
    (spaces / "work.toml").write_bytes(external_edit)

    recovered = GroupBindingsStore(spaces_directory=spaces, journal_path=journal)
    assert recovered._one(
        "SELECT state FROM group_binding_operations WHERE operation_id=?",
        ("group-operation-interrupted",),
    )[0] == "CONFLICT"
    assert (spaces / "work.toml").read_bytes() == external_edit
    assert (spaces / "friends.toml").read_bytes() == after["friends"]


def test_invalid_group_payload_does_not_mutate_spaces(tmp_path: Path) -> None:
    spaces = tmp_path / "spaces"
    spaces.mkdir()
    path = spaces / "friends.toml"
    path.write_text("qq_groups = [1]\n", encoding="utf-8")
    store = GroupBindingsStore(
        spaces_directory=spaces,
        journal_path=tmp_path / "runtime" / "groups.sqlite3",
    )
    with pytest.raises(Exception, match="group_bound_to_multiple_spaces"):
        store.validate(
            [
                {"group_id": 1, "space": "friends"},
                {"group_id": 1, "space": "work"},
            ]
        )
    assert path.read_text(encoding="utf-8") == "qq_groups = [1]\n"


@dataclass
class _Snapshot:
    phase: str
    revision_id: str
    generation_id: str = "generation-cn06-test"
    controller_boot_id: str = "controller-cn06-test"

    @property
    def desired(self):
        return "running" if self.phase == "ready" else "stopped"

    def public(self):
        return {"phase": self.phase, "revision_id": self.revision_id}


class _Supervisor:
    def __init__(self, bootstrap) -> None:
        self.bootstrap = bootstrap
        self.snapshot = _Snapshot("stopped", bootstrap.revision.revision_id)

    async def start(self):
        self.snapshot.phase = "failed"
        return self.snapshot

    async def stop(self, **_kwargs):
        self.snapshot.phase = "stopped"

    def business_client(self):
        return None


def _corona_app(tmp_path: Path, *, serve_dist: bool = False):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        "HOST=127.0.0.1\nPORT=18765\nWEBUI_ENABLED=true\n"
        f"WEBUI_SERVE_DIST={'true' if serve_dist else 'false'}\n",
        encoding="utf-8",
    )
    external = {"DB_PATH": str(tmp_path / "isolated.db")}
    initial = build_config_revision(
        project_root=ROOT,
        stella_home=home,
        external_environment=external,
    )
    revision_file = write_revision(home, INSTANCE, initial)
    bootstrap = prepare_corona_bootstrap(
        {
            "STELLA_CONFIG_REVISION_FILE": str(revision_file),
            "STELLA_INSTANCE_ID": INSTANCE,
        },
        project_root=ROOT,
    )
    store = ConfigStore(
        stella_home=home,
        instance_id=INSTANCE,
        project_root=ROOT,
        external_environment=external,
    )
    store.initialize(initial)
    supervisor = _Supervisor(bootstrap)
    manager = OperationManager(store, supervisor)
    app = create_corona_app(
        bootstrap,
        supervisor,
        config_store=store,
        operation_manager=manager,
    )
    return app, store


def test_corona_control_routes_stay_online_and_business_is_explicit_503(
    tmp_path: Path,
) -> None:
    app, store = _corona_app(tmp_path, serve_dist=True)
    planned_keys = set(CONTROL_ROUTE_KEYS | MIXED_ROUTE_KEYS)
    actual = {
        (method.upper(), path)
        for path, path_item in app.openapi()["paths"].items()
        for method in path_item
        if method.lower()
        in {
            "get",
            "post",
            "put",
            "patch",
            "delete",
            "options",
            "head",
        }
        if (method.upper(), path) in planned_keys
    }
    assert actual == planned_keys
    before = store.state().desired_revision
    with TestClient(app) as client:
        assert client.get("/api/v1/config").status_code == 401
        setup = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "cn06-admin-password"},
        )
        token = setup.json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/config", headers=headers).status_code == 200
        business = client.get("/api/v1/usage/today", headers=headers)
        assert business.status_code == 503
        assert business.json()["data"]["code"] == "core_unavailable"
        scenes = client.get("/api/v1/conversations/scenes", headers=headers)
        assert scenes.status_code == 503
        assert scenes.json()["data"]["code"] == "core_unavailable"
        history = client.get(
            "/api/v1/conversations/messages",
            params={"conversation_key": "c2.example"},
            headers=headers,
        )
        assert history.status_code == 503
        assert history.json()["data"]["code"] == "core_unavailable"
        mixed = client.put(
            "/api/v1/groups/bindings",
            headers=headers,
            json=[{"group_id": 101, "space": "friends"}],
        )
        assert mixed.status_code == 503
        assert mixed.json()["data"]["code"] == "core_unavailable"
    assert store.state().desired_revision == before


def test_internal_guard_sets_unforgeable_managed_admin_context() -> None:
    identity = ControlIdentity(
        instance_id="cn06-auth-test",
        controller_boot_id="controller-cn06-auth",
        generation_id="generation-cn06-auth",
        revision_id="revision-cn06-auth",
    )
    lifecycle = SimpleNamespace(
        instance_id=identity.instance_id,
        controller_boot_id=identity.controller_boot_id,
        generation_id=identity.generation_id,
        revision_id=identity.revision_id,
        launch_token="b" * 64,
    )
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(request: Request):
        context: AuthContext = require_auth(request)
        return {"username": context.username, "via": context.via}

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError):
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)

    guarded = InternalRequestGuard(app, lifecycle)
    headers = internal_headers(
        identity=identity,
        capability=lifecycle.launch_token,
        actor=TrustedActor("admin-user", "admin", "jwt"),
        request_id="cn06-request-0001",
    )
    with TestClient(guarded, client=("127.0.0.1", 1234)) as client:
        response = client.get("/whoami", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"username": "admin-user", "via": "managed-jwt"}

        adapter_headers = internal_headers(
            identity=identity,
            capability=lifecycle.launch_token,
            actor=TrustedActor("onebot", "adapter", "adapter"),
            request_id="cn06-request-0002",
        )
        assert client.get("/whoami", headers=adapter_headers).status_code == 401
        assert client.get("/whoami").status_code == 401


def test_private_group_binding_routes_require_guard_and_apply_idempotently(
    tmp_path: Path,
) -> None:
    identity = ControlIdentity(
        instance_id="cn06-private-groups",
        controller_boot_id="controller-cn06-private",
        generation_id="generation-cn06-private",
        revision_id="revision-cn06-private",
    )
    lifecycle = SimpleNamespace(
        instance_id=identity.instance_id,
        controller_boot_id=identity.controller_boot_id,
        generation_id=identity.generation_id,
        revision_id=identity.revision_id,
        launch_token="c" * 64,
    )
    spaces = tmp_path / "spaces"
    spaces.mkdir()
    (spaces / "friends.toml").write_text(
        'qq_groups = [1]\nsystem_prompt = "friends.md"\n', encoding="utf-8"
    )
    store = GroupBindingsStore(
        spaces_directory=spaces,
        journal_path=tmp_path / "runtime" / "groups.sqlite3",
    )
    guarded = InternalRequestGuard(
        create_nucleus_business_app(group_bindings_store=store), lifecycle
    )
    headers = internal_headers(
        identity=identity,
        capability=lifecycle.launch_token,
        actor=TrustedActor("admin", "admin", "jwt"),
        request_id="cn06-private-groups-1",
    )
    with TestClient(guarded, client=("127.0.0.1", 1234)) as client:
        assert (
            client.post(
                "/_nucleus/v1/private/groups/bindings/validate",
                json={"bindings": []},
            ).status_code
            == 401
        )
        validation = client.post(
            "/_nucleus/v1/private/groups/bindings/validate",
            headers=headers,
            json={"bindings": [{"group_id": 7, "space": "friends"}]},
        )
        assert validation.status_code == 200
        data = validation.json()["data"]
        payload = {
            "operation_id": "private-group-operation-1",
            "bindings": data["bindings"],
            "expected_digest": data["snapshot"]["digest"],
        }
        first = client.post(
            "/_nucleus/v1/private/groups/bindings/apply",
            headers=headers,
            json=payload,
        )
        repeated = client.post(
            "/_nucleus/v1/private/groups/bindings/apply",
            headers=headers,
            json=payload,
        )
        assert first.status_code == repeated.status_code == 200
        assert first.json() == repeated.json()
        rollback = client.post(
            "/_nucleus/v1/private/groups/bindings/rollback",
            headers=headers,
            json={"operation_id": payload["operation_id"]},
        )
        assert rollback.json()["data"]["restored"] is True


def test_nucleus_http_proxy_preserves_path_body_duplicate_headers_and_status() -> None:
    class EchoHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                chunks = []
                while True:
                    size = int(self.rfile.readline().strip().split(b";", 1)[0], 16)
                    if size == 0:
                        while self.rfile.readline().strip():
                            pass
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.read(2)
                body = b"".join(chunks)
            else:
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.server.observed = {
                "path": self.path,
                "body": body,
                "authorization": self.headers.get("Authorization"),
                "cookie": self.headers.get("Cookie"),
                "generation": self.headers.get("X-Stella-Generation-Id"),
                "custom": self.headers.get_all("X-Test-Header"),
                "connection_nominated": self.headers.get("X-Drop-Me"),
            }
            response_body = b"proxied-response"
            self.send_response(201)
            self.send_header("Set-Cookie", "one=1; Path=/")
            self.send_header("Set-Cookie", "two=2; Path=/")
            self.send_header("Connection", "x-hop")
            self.send_header("X-Hop", "drop")
            self.send_header("X-Upstream", "keep")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), EchoHandler)
    server.observed = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    identity = ControlIdentity(
        instance_id="cn06-proxy-test",
        controller_boot_id="controller-cn06-proxy",
        generation_id="generation-cn06-proxy",
        revision_id="revision-cn06-proxy",
    )
    client = NucleusClient(
        "127.0.0.1",
        server.server_address[1],
        identity=identity,
        capability="d" * 64,
    )
    actor = TrustedActor("admin", "admin", "jwt")

    async def run_proxy():
        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/v1/chat",
                "raw_path": b"/api/v1/chat",
                "query_string": b"x=1&x=2",
                "headers": [
                    (b"host", b"localhost"),
                    (b"authorization", b"Bearer browser-secret"),
                    (b"cookie", b"webui_jwt=browser-secret"),
                    (b"x-stella-generation-id", b"forged-generation"),
                    (b"connection", b"x-drop-me"),
                    (b"x-drop-me", b"secret"),
                    (b"x-test-header", b"preserved"),
                    (b"x-test-header", b"second-value"),
                ],
                "client": ("127.0.0.1", 4321),
                "server": ("127.0.0.1", 8080),
            },
            receive=lambda: None,
        )
        body_delivered = False

        async def receive():
            nonlocal body_delivered
            if not body_delivered:
                body_delivered = True
                return {
                    "type": "http.request",
                    "body": b"request-body",
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        request._receive = receive
        response = await client.proxy_http(request, actor)
        events = []

        async def send(message):
            events.append(message)

        await response(
            request.scope,
            receive,
            send,
        )
        headers = events[0]["headers"]
        return events, headers

    try:
        events, headers = asyncio.run(run_proxy())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert server.observed == {
        "path": "/api/v1/chat?x=1&x=2",
        "body": b"request-body",
        "authorization": None,
        "cookie": None,
        "generation": identity.generation_id,
        "custom": ["preserved", "second-value"],
        "connection_nominated": None,
    }
    assert events[0]["status"] == 201
    assert (
        b"".join(event.get("body", b"") for event in events[1:]) == b"proxied-response"
    )
    assert sum(name == b"set-cookie" for name, _value in headers) == 2
    assert (b"x-upstream", b"keep") in headers
    assert not any(
        name in {b"connection", b"x-hop", b"transfer-encoding"} for name, _ in headers
    )


class _GroupBindingsFakeClient:
    def __init__(self, *, fail_apply: bool = False, fail_rollback: bool = False):
        self.fail_apply = fail_apply
        self.fail_rollback = fail_rollback
        self.calls = []

    def group_bindings(self, action, payload, *, actor):
        self.calls.append((action, payload, actor.actor_id))
        if action == "validate":
            return {
                "bindings": payload["bindings"],
                "snapshot": {"digest": "a" * 64},
            }
        if action == "apply" and self.fail_apply:
            raise NucleusProtocolError("spaces_revision_conflict")
        if action == "apply":
            return {"applied": True, "digest": "b" * 64}
        if action == "rollback":
            return {"restored": not self.fail_rollback}
        raise AssertionError(action)


class _OperationsFake:
    async def accept(self, *_args, **_kwargs):
        return {"operation_id": "apply-operation-1", "phase": "accepted"}

    async def wait(self, _operation_id, *, timeout):
        assert timeout == 120.0
        return {
            "operation_id": "apply-operation-1",
            "phase": "succeeded",
            "terminal": True,
        }


def test_mixed_group_saga_commits_both_sides_before_success(tmp_path: Path) -> None:
    app, store = _corona_app(tmp_path)
    coordinator = app.state.group_bindings_coordinator
    client = _GroupBindingsFakeClient()
    coordinator.supervisor.business_client = lambda: client
    coordinator.operations = _OperationsFake()
    result = asyncio.run(
        coordinator.execute(
            [{"group_id": 12345, "space": "friends"}],
            actor={"actor_id": "admin"},
        )
    )
    assert result["groups"] == [12345]
    assert result["restart_required"] is True
    with store._connect() as connection:
        saga = connection.execute(
            "SELECT phase,request_json,target_revision,config_transaction_id,steps_json FROM group_binding_sagas WHERE operation_id=?",
            (result["operation_id"],),
        ).fetchone()
    assert saga[0] == "succeeded"
    assert json.loads(saga[1])["bindings"] == [{"group_id": 12345, "space": "friends"}]
    assert saga[2] == result["revision_id"]
    assert saga[3]
    assert [step["name"] for step in json.loads(saga[4])] == [
        "validated",
        "config_saved",
        "bindings_applied",
        "apply_accepted",
        "apply_succeeded",
    ]


def test_mixed_group_partial_compensation_blocks_future_apply(tmp_path: Path) -> None:
    app, store = _corona_app(tmp_path)
    coordinator = app.state.group_bindings_coordinator
    client = _GroupBindingsFakeClient(fail_apply=True, fail_rollback=True)
    coordinator.supervisor.business_client = lambda: client
    previous_revision = store.state().desired_revision
    with pytest.raises(Exception, match="group_binding_partial"):
        asyncio.run(
            coordinator.execute(
                [{"group_id": 12345, "space": "friends"}],
                actor={"actor_id": "admin"},
            )
        )
    assert store.state().desired_revision == previous_revision
    with store._connect() as connection:
        saga = connection.execute(
            "SELECT phase,error_code,steps_json FROM group_binding_sagas"
        ).fetchone()
    assert saga[0] == "needs_reconcile"
    assert "spaces_rollback_failed" in saga[1]
    assert json.loads(saga[2])[-1]["name"] == "nucleus_apply_failed"
    with pytest.raises(OperationError, match="group_bindings_needs_reconcile"):
        asyncio.run(
            app.state.operation_manager.accept(
                "apply",
                target_revision=store.state().desired_revision,
                actor={"via": "webui", "username": "admin"},
            )
        )
    with TestClient(app) as browser:
        setup = browser.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "cn06-admin-password"},
        )
        response = browser.post(
            "/api/v1/system/apply",
            headers={"Authorization": f"Bearer {setup.json()['data']['token']}"},
            json={},
        )
        assert response.status_code == 409
        assert response.json()["data"]["code"] == "group_bindings_needs_reconcile"
