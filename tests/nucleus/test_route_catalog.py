# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Route catalogs are a validated, generation-bound platform ingress contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

from nucleus.route_catalog import build_adapter_route_catalog
from stella_contracts.control import ControlContractError, ControlIdentity
from stella_contracts.route_catalog import (
    AdapterRoute,
    create_route_catalog,
    validate_route_catalog,
)

ROOT = Path(__file__).resolve().parents[2]


def _identity(generation: str = "route-generation-0001") -> ControlIdentity:
    return ControlIdentity(
        instance_id="route-catalog-test",
        controller_boot_id="route-controller-0001",
        generation_id=generation,
        revision_id="route-revision-0001",
    )


def test_catalog_round_trip_matches_only_supported_methods_and_protocols() -> None:
    catalog = create_route_catalog(
        _identity(),
        [
            AdapterRoute(
                "OneBot V11",
                "/onebot/v11/http/{event_id}",
                "http",
                ("POST",),
                "OneBot V11 HTTP",
            ),
            AdapterRoute(
                "OneBot V11", "/onebot/v11/ws", "websocket", (), "OneBot V11 WS"
            ),
        ],
    )
    verified = validate_route_catalog(catalog.to_payload(), _identity())
    assert verified.digest == catalog.digest
    assert (
        verified.match("/onebot/v11/http/evt-1", "POST", "http").adapter == "OneBot V11"
    )
    assert verified.match("/onebot/v11/http/evt-1", "GET", "http") is None
    assert verified.match("/onebot/v11/ws", "GET", "websocket").name == "OneBot V11 WS"
    assert verified.claims_path("/onebot/v11/http/unknown") is True
    assert verified.claims_path("/onebot/v12/unknown") is False


@pytest.mark.parametrize(
    "route",
    [
        AdapterRoute("OneBot V11", "/", "http", ("POST",), "root"),
        AdapterRoute("OneBot V11", "/_nucleus/v1/health", "http", ("GET",), "private"),
        AdapterRoute(
            "OneBot V11", "/api/v1/chat", "http", ("POST",), "control-conflict"
        ),
        AdapterRoute(
            "OneBot V11",
            "/api/{version}",
            "http",
            ("POST",),
            "dynamic-control-conflict",
        ),
        AdapterRoute(
            "OneBot V11",
            "/{namespace}/{path}",
            "http",
            ("POST",),
            "dynamic-internal-conflict",
        ),
        AdapterRoute("OneBot V11", "/onebot//v11", "http", ("POST",), "double-slash"),
        AdapterRoute(
            "OneBot V11", "/onebot/v11/{rest:path}", "http", ("POST",), "catch-all"
        ),
        AdapterRoute("OneBot V11", "/onebot/v11", "http", ("TRACE",), "unsafe-method"),
    ],
)
def test_catalog_rejects_reserved_unsafe_or_catch_all_routes(
    route: AdapterRoute,
) -> None:
    with pytest.raises(ControlContractError):
        create_route_catalog(_identity(), [route])


def test_catalog_rejects_conflicts_stale_identity_and_digest_changes() -> None:
    route = AdapterRoute("OneBot V11", "/onebot/v11", "http", ("POST",), "Root HTTP")
    with pytest.raises(ControlContractError, match="route_catalog_conflict"):
        create_route_catalog(_identity(), [route, route])

    catalog = create_route_catalog(_identity(), [route])
    with pytest.raises(ControlContractError, match="identity_mismatch"):
        validate_route_catalog(catalog.to_payload(), _identity("route-generation-0002"))

    tampered = catalog.to_payload()
    tampered["routes"][0]["path"] = "/onebot/other"
    with pytest.raises(ControlContractError, match="digest_mismatch"):
        validate_route_catalog(tampered, _identity())


def test_driver_catalog_exports_registered_http_and_websocket_routes_only() -> None:
    app = FastAPI()
    app.add_api_route(
        "/onebot/v11/http",
        lambda: {"ok": True},
        methods=["POST"],
        name="OneBot V11 Root HTTP",
    )
    app.add_api_websocket_route(
        "/onebot/v11/ws", lambda _ws: None, name="OneBot V11 Root WebSocket"
    )
    app.add_api_route(
        "/api/v1/chat", lambda: {"ok": True}, methods=["POST"], name="chat"
    )
    driver = type(
        "Driver", (), {"server_app": app, "_adapters": {"OneBot V11": object()}}
    )()

    catalog = build_adapter_route_catalog(driver, _identity())
    assert len(catalog.routes) == 2
    assert catalog.match("/onebot/v11/http", "POST", "http") is not None
    assert catalog.match("/onebot/v11/ws", "GET", "websocket") is not None
    assert catalog.match("/api/v1/chat", "POST", "http") is None


def test_real_onebot_v11_driver_registers_exportable_public_routes(
    tmp_path: Path,
) -> None:
    probe = r"""
import json
from nucleus.lifecycle import NucleusLifecycle, set_active_lifecycle
life = NucleusLifecycle(instance_id="onebot-shape", controller_boot_id="controller-shape-0001",
    generation_id="generation-shape-0001", revision_id="revision-shape-0001",
    launch_token="a" * 64, internal_host="127.0.0.1", internal_port=18080)
set_active_lifecycle(life)
from nucleus.framework import install_managed_driver
from core.transport.adapter_loader import register_enabled_adapters
from nucleus.route_catalog import build_adapter_route_catalog
from stella_contracts.control import ControlIdentity
driver = install_managed_driver()
register_enabled_adapters(driver, ("nonebot.adapters.onebot.v11",))
identity = ControlIdentity("onebot-shape", "controller-shape-0001", "generation-shape-0001", "revision-shape-0001")
catalog = build_adapter_route_catalog(driver, identity)
print(json.dumps([route.to_payload() for route in catalog.routes]))
set_active_lifecycle(None)
"""
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if os.environ.get(key)
    }
    environment.update(
        {
            "PYTHONPATH": str(ROOT),
            "PYTHONNOUSERSITE": "1",
            "STELLA_HOME": str(tmp_path / "isolated-home"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    routes = json.loads(result.stdout.strip())
    route_shapes = {
        (item["protocol"], item["path"], tuple(item["methods"])) for item in routes
    }
    assert (
        "http",
        "/onebot/v11/",
        ("POST",),
    ) in route_shapes
    assert ("http", "/onebot/v11/http", ("POST",)) in route_shapes
    assert ("http", "/onebot/v11/http/", ("POST",)) in route_shapes
    assert ("websocket", "/onebot/v11/", ()) in route_shapes
    assert ("websocket", "/onebot/v11/ws", ()) in route_shapes
    assert ("websocket", "/onebot/v11/ws/", ()) in route_shapes
