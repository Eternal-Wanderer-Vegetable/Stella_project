# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Generation-bound external route catalog contract shared by Corona/Nucleus."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from stella_contracts.control import (
    CONTROL_PROTOCOL_VERSION,
    ControlContractError,
    ControlIdentity,
)

ROUTE_CATALOG_VERSION = 1
NUCLEUS_ROUTES_PATH = "/_nucleus/v1/routes"

_ALLOWED_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
)
_ADAPTER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")
_PARAMETER = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)(?::(str|int|float|uuid))?\}$")
_RESERVED_PREFIXES = (
    "/_nucleus",
    "/_corona",
    "/api/v1",
    "/stella/status",
    "/docs",
    "/openapi.json",
)


@dataclass(frozen=True)
class AdapterRoute:
    adapter: str
    path: str
    protocol: str
    methods: tuple[str, ...] = ()
    name: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "path": self.path,
            "protocol": self.protocol,
            "methods": list(self.methods),
            "name": self.name,
        }


@dataclass(frozen=True)
class AdapterRouteCatalog:
    identity: ControlIdentity
    routes: tuple[AdapterRoute, ...]
    digest: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "control_protocol_version": CONTROL_PROTOCOL_VERSION,
            "route_catalog_version": ROUTE_CATALOG_VERSION,
            **self.identity.to_payload(),
            "routes": [route.to_payload() for route in self.routes],
            "digest": self.digest,
        }

    def match(self, path: str, method: str, protocol: str) -> AdapterRoute | None:
        method = method.upper()
        candidates = sorted(
            (route for route in self.routes if route.protocol == protocol),
            key=lambda route: (_path_specificity(route.path), route.path),
            reverse=True,
        )
        for route in candidates:
            if _path_pattern(route.path).fullmatch(path) and (
                protocol == "websocket" or method in route.methods
            ):
                return route
        return None

    def path_matches(self, path: str, protocol: str) -> tuple[AdapterRoute, ...]:
        return tuple(
            route
            for route in self.routes
            if route.protocol == protocol and _path_pattern(route.path).fullmatch(path)
        )

    def slash_alternate(self, path: str, protocol: str) -> str | None:
        """Return the FastAPI-compatible trailing-slash form for HTTP routes."""
        if protocol != "http" or path == "/":
            return None
        alternate = path[:-1] if path.endswith("/") else path + "/"
        if self.path_matches(alternate, "http"):
            return alternate
        return None

    def claims_path(self, path: str) -> bool:
        """Identify the static adapter namespace, including unknown child routes."""
        for route in self.routes:
            prefix = []
            for segment in route.path.split("/")[1:]:
                if segment.startswith("{"):
                    break
                if segment:
                    prefix.append(segment)
            if prefix and path.strip("/").split("/")[: len(prefix)] == prefix:
                return True
        return False


def create_route_catalog(
    identity: ControlIdentity, routes: list[AdapterRoute] | tuple[AdapterRoute, ...]
) -> AdapterRouteCatalog:
    normalized = tuple(sorted(routes, key=_route_sort_key))
    _validate_routes(normalized)
    digest = _routes_digest(normalized)
    return AdapterRouteCatalog(identity=identity, routes=normalized, digest=digest)


def validate_route_catalog(
    payload: Any, expected_identity: ControlIdentity
) -> AdapterRouteCatalog:
    if not isinstance(payload, dict):
        raise ControlContractError("route_catalog_invalid")
    if payload.get("control_protocol_version") != CONTROL_PROTOCOL_VERSION:
        raise ControlContractError("protocol_mismatch")
    if payload.get("route_catalog_version") != ROUTE_CATALOG_VERSION:
        raise ControlContractError("route_catalog_version_mismatch")
    try:
        identity = ControlIdentity.from_payload(payload)
    except (TypeError, ValueError) as exc:
        raise ControlContractError("identity_mismatch") from exc
    if identity != expected_identity:
        raise ControlContractError("identity_mismatch")
    values = payload.get("routes")
    if not isinstance(values, list) or len(values) > 1024:
        raise ControlContractError("route_catalog_invalid")
    routes: list[AdapterRoute] = []
    for item in values:
        if not isinstance(item, dict):
            raise ControlContractError("route_catalog_invalid")
        adapter = item.get("adapter")
        path = item.get("path")
        protocol = item.get("protocol")
        methods = item.get("methods")
        name = item.get("name", "")
        if (
            not isinstance(adapter, str)
            or not isinstance(path, str)
            or not isinstance(protocol, str)
            or not isinstance(methods, list)
            or not all(isinstance(method, str) for method in methods)
            or not isinstance(name, str)
        ):
            raise ControlContractError("route_catalog_invalid")
        routes.append(
            AdapterRoute(
                adapter=adapter,
                path=path,
                protocol=protocol,
                methods=tuple(methods),
                name=name,
            )
        )
    catalog = create_route_catalog(identity, routes)
    if payload.get("digest") != catalog.digest:
        raise ControlContractError("route_catalog_digest_mismatch")
    return catalog


def _validate_routes(routes: tuple[AdapterRoute, ...]) -> None:
    seen: set[tuple[str, str, str]] = set()
    if len(routes) > 1024:
        raise ControlContractError("route_catalog_too_large")
    for route in routes:
        if not _ADAPTER_NAME.fullmatch(route.adapter):
            raise ControlContractError("route_catalog_adapter_invalid")
        if route.protocol not in {"http", "websocket"}:
            raise ControlContractError("route_catalog_protocol_invalid")
        if (
            not isinstance(route.name, str)
            or len(route.name) > 160
            or "\x00" in route.name
        ):
            raise ControlContractError("route_catalog_name_invalid")
        _validate_path(route.path)
        if route.protocol == "http":
            if not route.methods or any(
                method not in _ALLOWED_METHODS for method in route.methods
            ):
                raise ControlContractError("route_catalog_methods_invalid")
            if len(set(route.methods)) != len(route.methods):
                raise ControlContractError("route_catalog_methods_invalid")
            keys = ((route.protocol, route.path, method) for method in route.methods)
        else:
            if route.methods:
                raise ControlContractError("route_catalog_methods_invalid")
            keys = iter(((route.protocol, route.path, "websocket"),))
        for key in keys:
            if key in seen:
                raise ControlContractError("route_catalog_conflict")
            seen.add(key)


def _validate_path(path: str) -> None:
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path == "/"
        or path.startswith("//")
        or "//" in path
        or "\\" in path
        or any(char in path for char in "?#%\x00\r\n")
        or len(path) > 512
    ):
        raise ControlContractError("route_catalog_path_invalid")
    if any(
        path == prefix or path.startswith(prefix + "/") for prefix in _RESERVED_PREFIXES
    ):
        raise ControlContractError("route_catalog_reserved_path")
    segments = path.split("/")[1:]
    for segment in segments:
        if segment in {".", ".."}:
            raise ControlContractError("route_catalog_path_invalid")
        if segment.startswith("{") or segment.endswith("}"):
            if not _PARAMETER.fullmatch(segment):
                raise ControlContractError("route_catalog_path_invalid")
        elif "{" in segment or "}" in segment:
            raise ControlContractError("route_catalog_path_invalid")
    pattern = _path_pattern(path)
    if any(
        pattern.fullmatch(candidate)
        for prefix in _RESERVED_PREFIXES
        for candidate in (prefix, prefix + "/_reserved_probe")
    ):
        raise ControlContractError("route_catalog_reserved_path")


def _route_sort_key(route: AdapterRoute) -> tuple[str, str, str, tuple[str, ...], str]:
    return (
        route.protocol,
        route.path,
        route.adapter.lower(),
        route.methods,
        route.name,
    )


def _path_specificity(path: str) -> tuple[int, int, int]:
    parameters = sum("{" in segment for segment in path.split("/"))
    static_length = sum(
        len(segment) for segment in path.split("/") if "{" not in segment
    )
    return -parameters, static_length, len(path)


@lru_cache(maxsize=2048)
def _path_pattern(path: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^{}]+\})", path)
    expression = "^"
    for part in parts:
        if not (part.startswith("{") and part.endswith("}")):
            expression += re.escape(part)
            continue
        match = _PARAMETER.fullmatch(part)
        if match is None:
            expression += "[^/]+"
            continue
        converter = match.group(2) or "str"
        expression += {
            "str": "[^/]+",
            "int": "[0-9]+",
            "float": "[0-9]+(?:\\.[0-9]+)?",
            "uuid": "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        }[converter]
    expression += "$"
    return re.compile(expression)


def _routes_digest(routes: tuple[AdapterRoute, ...]) -> str:
    canonical = json.dumps(
        [route.to_payload() for route in routes],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()
