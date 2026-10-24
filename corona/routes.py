# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Frozen ownership contract for the planned WebUI route split."""

from __future__ import annotations

import re
from functools import lru_cache

ROUTE_OWNERSHIP: tuple[tuple[str, str, str], ...] = (
    ("GET", "/api/v1/auth/setup-status", "corona"),
    ("POST", "/api/v1/auth/setup", "corona"),
    ("POST", "/api/v1/auth/login", "corona"),
    ("POST", "/api/v1/auth/desktop-session", "corona"),
    ("GET", "/api/v1/auth/me", "corona"),
    ("POST", "/api/v1/auth/logout", "corona"),
    ("PATCH", "/api/v1/auth/account", "corona"),
    ("GET", "/api/v1/chat/session", "nucleus"),
    ("GET", "/api/v1/chat/messages", "nucleus"),
    ("POST", "/api/v1/chat/reset", "nucleus"),
    ("POST", "/api/v1/chat", "nucleus"),
    ("GET", "/api/v1/cometa/health", "nucleus"),
    ("GET", "/api/v1/cometa/backends", "nucleus"),
    ("GET", "/api/v1/cometa/tasks", "nucleus"),
    ("POST", "/api/v1/cometa/tasks", "nucleus"),
    ("GET", "/api/v1/cometa/tasks/{task_id}", "nucleus"),
    ("GET", "/api/v1/cometa/tasks/{task_id}/events", "nucleus"),
    ("POST", "/api/v1/cometa/tasks/{task_id}/cancel", "nucleus"),
    ("POST", "/api/v1/cometa/tasks/{task_id}/inputs/{request_id}", "nucleus"),
    ("GET", "/api/v1/cometa/tasks/{task_id}/result", "nucleus"),
    ("GET", "/api/v1/cometa/tasks/{task_id}/artifacts/{artifact_id}", "nucleus"),
    ("GET", "/api/v1/cometa/backends/{backend_id}/auth/status", "nucleus"),
    ("POST", "/api/v1/cometa/backends/{backend_id}/auth/api-key", "nucleus"),
    ("POST", "/api/v1/cometa/backends/{backend_id}/auth/custom-endpoint", "nucleus"),
    ("POST", "/api/v1/cometa/backends/{backend_id}/auth/device-login", "nucleus"),
    (
        "GET",
        "/api/v1/cometa/backends/{backend_id}/auth/device-login/{session_id}",
        "nucleus",
    ),
    ("POST", "/api/v1/cometa/backends/{backend_id}/auth/migrate-legacy", "nucleus"),
    ("POST", "/api/v1/cometa/backends/{backend_id}/auth/logout", "nucleus"),
    ("POST", "/api/v1/cometa/backends/{backend_id}/auth/test", "nucleus"),
    ("GET", "/api/v1/config/schema", "corona"),
    ("GET", "/api/v1/config", "corona"),
    ("PUT", "/api/v1/config", "corona"),
    ("GET", "/api/v1/providers/endpoints", "corona"),
    ("PUT", "/api/v1/providers/endpoints", "corona"),
    ("GET", "/api/v1/providers/roles", "corona"),
    ("PUT", "/api/v1/providers/roles", "corona"),
    ("GET", "/api/v1/providers/models", "nucleus"),
    ("POST", "/api/v1/providers/test", "nucleus"),
    ("GET", "/api/v1/platform/onebot", "corona"),
    ("PUT", "/api/v1/platform/onebot", "corona"),
    ("GET", "/api/v1/platform/adapters", "corona"),
    ("PUT", "/api/v1/platform/adapters", "corona"),
    ("GET", "/api/v1/spaces", "nucleus"),
    ("POST", "/api/v1/spaces", "nucleus"),
    ("GET", "/api/v1/spaces/default", "nucleus"),
    ("GET", "/api/v1/spaces/{name}/prompt", "nucleus"),
    ("PUT", "/api/v1/spaces/{name}/prompt", "nucleus"),
    ("PUT", "/api/v1/spaces/{name}/bindings", "nucleus"),
    ("DELETE", "/api/v1/spaces/{name}", "nucleus"),
    ("GET", "/api/v1/groups", "nucleus"),
    ("PUT", "/api/v1/groups/bindings", "split-config-and-business"),
    ("POST", "/api/v1/groups/{group_id}/mute", "nucleus"),
    ("POST", "/api/v1/groups/{group_id}/unmute", "nucleus"),
    ("POST", "/api/v1/system/restart", "corona"),
    ("GET", "/api/v1/system/doctor", "corona"),
    ("GET", "/api/v1/conversations/groups", "nucleus"),
    ("GET", "/api/v1/conversations", "nucleus"),
    ("GET", "/api/v1/conversations/context", "nucleus"),
    ("POST", "/api/v1/evaluation/runs", "nucleus"),
    ("GET", "/api/v1/evaluation/runs", "nucleus"),
    ("GET", "/api/v1/evaluation/runs/{run_id}", "nucleus"),
    ("POST", "/api/v1/evaluation/runs/{run_id}/cancel", "nucleus"),
    ("GET", "/api/v1/logs/history", "nucleus"),
    ("GET", "/api/v1/logs/live", "nucleus"),
    ("GET", "/api/v1/mcp/servers", "nucleus"),
    ("POST", "/api/v1/mcp/servers", "nucleus"),
    ("PUT", "/api/v1/mcp/servers/{server_id}", "nucleus"),
    ("DELETE", "/api/v1/mcp/servers/{server_id}", "nucleus"),
    ("POST", "/api/v1/mcp/servers/{server_id}/test", "nucleus"),
    ("GET", "/api/v1/mcp/servers/{server_id}/tools", "nucleus"),
    ("POST", "/api/v1/mcp/apply", "nucleus"),
    ("GET", "/api/v1/skills", "nucleus"),
    ("GET", "/api/v1/skills/{name}", "nucleus"),
    ("PUT", "/api/v1/skills/{name}", "nucleus"),
    ("POST", "/api/v1/skills/upload", "nucleus"),
    ("DELETE", "/api/v1/skills/{name}", "nucleus"),
    ("GET", "/api/v1/knowledge-bases", "nucleus"),
    ("POST", "/api/v1/knowledge-bases", "nucleus"),
    ("GET", "/api/v1/knowledge-bases/{kb_id}", "nucleus"),
    ("DELETE", "/api/v1/knowledge-bases/{kb_id}", "nucleus"),
    ("POST", "/api/v1/knowledge-bases/{kb_id}/documents", "nucleus"),
    ("POST", "/api/v1/knowledge-bases/{kb_id}/retrieve", "nucleus"),
    ("POST", "/api/v1/knowledge-bases/{kb_id}/acl", "nucleus"),
    ("DELETE", "/api/v1/knowledge-bases/{kb_id}/acl", "nucleus"),
    ("GET", "/api/v1/scheduling/bots", "nucleus"),
    ("GET", "/api/v1/scheduling/tasks", "nucleus"),
    ("POST", "/api/v1/scheduling/tasks", "nucleus"),
    ("GET", "/api/v1/scheduling/tasks/{task_id}", "nucleus"),
    ("PATCH", "/api/v1/scheduling/tasks/{task_id}", "nucleus"),
    ("POST", "/api/v1/scheduling/tasks/{task_id}/pause", "nucleus"),
    ("POST", "/api/v1/scheduling/tasks/{task_id}/resume", "nucleus"),
    ("POST", "/api/v1/scheduling/tasks/{task_id}/cancel", "nucleus"),
    ("POST", "/api/v1/scheduling/tasks/{task_id}/run-now", "nucleus"),
    ("GET", "/api/v1/scheduling/tasks/{task_id}/history", "nucleus"),
    ("GET", "/api/v1/scheduling/audit", "nucleus"),
    ("GET", "/api/v1/personal-memory", "nucleus"),
    ("DELETE", "/api/v1/personal-memory/{memory_id}", "nucleus"),
    ("GET", "/api/v1/personal-memory/export", "nucleus"),
    ("GET", "/api/v1/platform/link", "nucleus"),
    ("GET", "/api/v1/plugins", "nucleus"),
    ("PATCH", "/api/v1/plugins/enabled", "nucleus"),
    ("POST", "/api/v1/plugins/reload", "nucleus"),
    ("GET", "/api/v1/plugins/config", "nucleus"),
    ("PUT", "/api/v1/plugins/config", "nucleus"),
    ("GET", "/api/v1/plugins/readme", "nucleus"),
    ("POST", "/api/v1/plugins/install", "nucleus"),
    ("POST", "/api/v1/plugins/install/upload", "nucleus"),
    ("DELETE", "/api/v1/plugins/{plugin_id}", "nucleus"),
    ("GET", "/api/v1/plugin-sources", "nucleus"),
    ("POST", "/api/v1/plugin-sources", "nucleus"),
    ("PUT", "/api/v1/plugin-sources/{source_id}", "nucleus"),
    ("DELETE", "/api/v1/plugin-sources/{source_id}", "nucleus"),
    ("GET", "/api/v1/plugins/market", "nucleus"),
    ("GET", "/api/v1/providers/runtime", "nucleus"),
    ("GET", "/api/v1/status", "corona"),
    ("GET", "/api/v1/gravitas/status", "nucleus"),
    ("GET", "/api/v1/trace/memory", "nucleus"),
    ("GET", "/api/v1/trace/memory/{trace_id}", "nucleus"),
    ("GET", "/api/v1/trace/participation", "nucleus"),
    ("GET", "/api/v1/trace/turns", "nucleus"),
    ("GET", "/api/v1/trace/turns/{turn_id}", "nucleus"),
    ("GET", "/api/v1/trace/turns/{turn_id}/payloads", "nucleus"),
    ("POST", "/api/v1/trace/turns/{turn_id}/replay", "nucleus"),
    ("GET", "/api/v1/trace/messages", "nucleus"),
    ("GET", "/api/v1/trace/messages/{trace_id}", "nucleus"),
    ("GET", "/api/v1/trace/messages/{trace_id}/context", "nucleus"),
    ("GET", "/api/v1/trace/messages/{trace_id}/events", "nucleus"),
    ("GET", "/api/v1/trace/flow/specs/{version}", "nucleus"),
    ("GET", "/api/v1/trace/flow/spec-version", "nucleus"),
    ("GET", "/api/v1/trace/entities/{entity_type}/{entity_id}", "nucleus"),
    ("GET", "/api/v1/trace/messages/{trace_id}/entities", "nucleus"),
    ("GET", "/api/v1/trace/messages/{trace_id}/stream", "nucleus"),
    ("GET", "/api/v1/usage/today", "nucleus"),
    ("GET", "/api/v1/usage/daily", "nucleus"),
)
CONTROL_ROUTE_KEYS = frozenset(
    (method, path) for method, path, owner in ROUTE_OWNERSHIP if owner == "corona"
)
BUSINESS_ROUTE_KEYS = frozenset(
    (method, path) for method, path, owner in ROUTE_OWNERSHIP if owner == "nucleus"
)
MIXED_ROUTE_KEYS = frozenset(
    (method, path)
    for method, path, owner in ROUTE_OWNERSHIP
    if owner == "split-config-and-business"
)


@lru_cache(maxsize=256)
def _pattern(path: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^{}]+\})", path)
    expression = (
        "^"
        + "".join(
            "[^/]+" if part.startswith("{") and part.endswith("}") else re.escape(part)
            for part in parts
        )
        + "$"
    )
    return re.compile(expression)


def route_owner(method: str, path: str) -> str | None:
    """Return the frozen owner for one method/path pair, if it is catalogued."""
    method = method.upper()
    matches = {
        owner
        for candidate_method, candidate_path, owner in ROUTE_OWNERSHIP
        if candidate_method == method and _pattern(candidate_path).fullmatch(path)
    }
    if len(matches) > 1:
        raise RuntimeError("ambiguous WebUI route ownership")
    return next(iter(matches), None)


def methods_for_path(path: str) -> frozenset[str]:
    """List planned methods for a path, used to reject proxy method fallthrough."""
    return frozenset(
        method
        for method, candidate_path, _owner in ROUTE_OWNERSHIP
        if _pattern(candidate_path).fullmatch(path)
    )


def install_business_proxy(app, supervisor) -> None:
    """Install the explicit Nucleus HTTP API fallback after control routes."""
    from corona.proxy import create_business_proxy_endpoint

    methods = sorted({method for method, _path in BUSINESS_ROUTE_KEYS})
    app.add_api_route(
        "/api/v1/{business_path:path}",
        create_business_proxy_endpoint(supervisor),
        methods=methods,
        include_in_schema=False,
        name="nucleus-business-proxy",
    )
