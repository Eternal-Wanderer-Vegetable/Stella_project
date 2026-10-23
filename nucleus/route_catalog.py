# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Export only adapter routes that can be represented by the v1 proxy contract."""

from __future__ import annotations

from typing import Any

from fastapi.routing import APIRoute, APIWebSocketRoute

from stella_contracts.control import ControlIdentity
from stella_contracts.route_catalog import (
    AdapterRoute,
    AdapterRouteCatalog,
    create_route_catalog,
)


def build_adapter_route_catalog(
    driver: Any, identity: ControlIdentity
) -> AdapterRouteCatalog:
    """Build an immutable catalog from routes registered on the actual FastAPI Driver.

    Adapter packages with non-standard route names or route types are omitted and
    remain uncertified. Their behavior is never inferred from an arbitrary path.
    """
    app = getattr(driver, "server_app", None)
    if app is None or not isinstance(getattr(app, "routes", None), list):
        raise RuntimeError("managed driver does not expose its FastAPI route table")
    registered = getattr(driver, "_adapters", None)
    if not isinstance(registered, dict):
        raise RuntimeError("managed driver adapter registry is unavailable")
    adapter_names = tuple(
        sorted(
            {str(name).strip() for name in registered if str(name).strip()},
            key=lambda name: (-len(name), name.lower()),
        )
    )
    routes: list[AdapterRoute] = []
    for route in app.routes:
        route_name = getattr(route, "name", None)
        if not isinstance(route_name, str) or not route_name:
            continue
        adapter = next(
            (
                name
                for name in adapter_names
                if route_name == name or route_name.startswith(name + " ")
            ),
            None,
        )
        if adapter is None:
            continue
        path = getattr(route, "path", None)
        if not isinstance(path, str):
            continue
        if isinstance(route, APIWebSocketRoute):
            routes.append(
                AdapterRoute(
                    adapter=adapter,
                    path=path,
                    protocol="websocket",
                    name=route_name,
                )
            )
        elif isinstance(route, APIRoute):
            methods = tuple(
                sorted(str(method).upper() for method in (route.methods or ()))
            )
            routes.append(
                AdapterRoute(
                    adapter=adapter,
                    path=path,
                    protocol="http",
                    methods=methods,
                    name=route_name,
                )
            )
    return create_route_catalog(identity, routes)
