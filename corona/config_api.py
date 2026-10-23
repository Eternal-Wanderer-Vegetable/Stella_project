# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Corona-owned configuration and lifecycle API.

The module uses the immutable revision store plus AST-discovered settings keys.
It deliberately avoids importing ``config.settings`` and Nucleus business code.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import StreamingResponse

from corona.auth import AuthContext, require_auth
from corona.config_store import ConfigStore, ConfigStoreError
from corona.operations import OperationError, OperationManager
from stella_bootstrap.adapter_names import (
    DEFAULT_ADAPTER_MODULES,
    parse_adapter_modules,
)
from webui.responses import ApiError, ok

router = APIRouter(
    tags=["corona-config"],
    dependencies=[Depends(require_auth)],
)

_SLOTS = ("CHAT", "MEMORY", "VISION")
_SLOT_ALIASES = {
    "LOCAL": "CHAT",
    "ONLINE_CHAT": "CHAT",
    "ONLINE_MEMORY": "MEMORY",
    "EXTRA": "MEMORY",
    "EXTRA_VISION": "VISION",
}
_ENDPOINT_FIELDS = ("BASE_URL", "API_KEY", "MODEL", "KIND", "CONCURRENCY", "TIMEOUT")


@router.get("/api/v1/config/schema")
async def config_schema(request: Request) -> Any:
    store = _store(request)
    return ok({"version": 1, "fields": store.schema()})


@router.get("/api/v1/config")
async def config_current(request: Request) -> Any:
    return ok(_store(request).public_config())


@router.put("/api/v1/config")
async def config_update(
    request: Request,
    payload: dict[str, Any],
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    result = _save(
        request,
        payload,
        expected_revision=_if_match(request.headers.get("if-match")),
        idempotency_key=request.headers.get("idempotency-key"),
        auth=auth,
    )
    result["restart_required"] = True
    return ok(result)


@router.get("/api/v1/providers/endpoints")
async def providers_endpoints(request: Request) -> Any:
    store = _store(request)
    revision, _path = store.current_revision("desired")
    values = revision.values
    field_map = {field["key"]: field for field in store.schema()}
    endpoints = []
    for slot in _SLOTS:
        endpoints.append(
            {
                "slot": slot,
                "base_url": _endpoint_value(values, field_map, slot, "BASE_URL"),
                "model": _endpoint_value(values, field_map, slot, "MODEL"),
                "kind": _endpoint_value(values, field_map, slot, "KIND"),
                "concurrency": _endpoint_value(values, field_map, slot, "CONCURRENCY"),
                "timeout": _endpoint_value(values, field_map, slot, "TIMEOUT"),
                "has_api_key": bool(
                    _endpoint_value(values, field_map, slot, "API_KEY")
                ),
            }
        )
    return ok({"endpoints": endpoints, "desired_revision": revision.revision_id})


@router.put("/api/v1/providers/endpoints")
async def providers_endpoints_put(
    request: Request,
    payload: list[dict[str, Any]],
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    updates: dict[str, Any] = {}
    for item in payload:
        slot = _normalize_slot(item.get("slot"))
        if slot not in _SLOTS:
            raise ApiError(
                "provider_slot_invalid", data={"code": "provider_slot_invalid"}
            )
        fields = {str(key).upper(): value for key, value in item.items()}
        for field in _ENDPOINT_FIELDS:
            if field not in fields:
                continue
            value = fields[field]
            if field == "API_KEY" and value == "":
                continue
            updates[f"LLM_ENDPOINT_{slot}_{field}"] = value
    result = _save(
        request,
        updates,
        expected_revision=_if_match(request.headers.get("if-match")),
        idempotency_key=request.headers.get("idempotency-key"),
        auth=auth,
    )
    result["restart_required"] = True
    return ok(result)


@router.get("/api/v1/providers/roles")
async def providers_roles(request: Request) -> Any:
    store = _store(request)
    revision, _path = store.current_revision("desired")
    schema = store.schema()
    field_map = {field["key"]: field for field in schema}
    fields = set(field_map)
    roles = []
    prefixes = []
    for key in fields:
        prefix = "LLM_ROLE_"
        suffix = "_ENDPOINT"
        if (
            key.startswith(prefix)
            and key.endswith(suffix)
            and not key.endswith("_FALLBACK_ENDPOINT")
        ):
            role = key[len(prefix) : -len(suffix)]
            if role not in prefixes:
                prefixes.append(role)
    # Follow settings.py's AST order instead of set order so the old form stays stable.
    ordered = []
    for field in store.schema():
        key = field["key"]
        if (
            key.startswith("LLM_ROLE_")
            and key.endswith("_ENDPOINT")
            and not key.endswith("_FALLBACK_ENDPOINT")
        ):
            role = key.removeprefix("LLM_ROLE_").removesuffix("_ENDPOINT")
            if role not in ordered:
                ordered.append(role)
    for upper in ordered:
        if upper not in prefixes:
            continue
        prefix = f"LLM_ROLE_{upper}_"
        endpoint = _effective_value(revision.values, field_map, prefix + "ENDPOINT")
        fallback = _effective_value(
            revision.values, field_map, prefix + "FALLBACK_ENDPOINT"
        )
        roles.append(
            {
                "role": upper.lower(),
                "endpoint": _normalize_slot(endpoint)
                if endpoint.lower() != "none"
                else "none",
                "model": _effective_value(revision.values, field_map, prefix + "MODEL"),
                "temperature": _effective_value(
                    revision.values, field_map, prefix + "TEMPERATURE"
                ),
                "max_tokens": _effective_value(
                    revision.values, field_map, prefix + "MAX_TOKENS"
                ),
                "fallback_endpoint": _normalize_slot(fallback) if fallback else "",
            }
        )
    return ok({"roles": roles, "desired_revision": revision.revision_id})


@router.put("/api/v1/providers/roles")
async def providers_roles_put(
    request: Request,
    payload: list[dict[str, Any]],
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    fields = {field["key"] for field in _store(request).schema()}
    valid_roles = {
        key.removeprefix("LLM_ROLE_").removesuffix("_ENDPOINT").lower()
        for key in fields
        if key.startswith("LLM_ROLE_")
        and key.endswith("_ENDPOINT")
        and not key.endswith("_FALLBACK_ENDPOINT")
    }
    updates: dict[str, Any] = {}
    for item in payload:
        role = item.get("role")
        if not isinstance(role, str) or role.lower() not in valid_roles:
            raise ApiError(
                "provider_role_invalid", data={"code": "provider_role_invalid"}
            )
        upper = role.upper()
        prefix = f"LLM_ROLE_{upper}_"
        endpoint = item.get("endpoint")
        if endpoint not in (None, ""):
            endpoint_text = str(endpoint).strip()
            if endpoint_text.lower() != "none":
                endpoint_text = _normalize_slot(endpoint_text)
                if endpoint_text not in _SLOTS:
                    raise ApiError(
                        "provider_slot_invalid", data={"code": "provider_slot_invalid"}
                    )
            else:
                endpoint_text = "none"
            updates[prefix + "ENDPOINT"] = endpoint_text
        if "model" in item:
            updates[prefix + "MODEL"] = item.get("model", "")
        if item.get("temperature") not in (None, ""):
            try:
                temperature = float(item["temperature"])
            except (TypeError, ValueError):
                raise ApiError(
                    "provider_temperature_invalid",
                    data={"code": "provider_temperature_invalid"},
                ) from None
            if not math.isfinite(temperature):
                raise ApiError(
                    "provider_temperature_invalid",
                    data={"code": "provider_temperature_invalid"},
                )
            updates[prefix + "TEMPERATURE"] = str(item["temperature"])
        if item.get("max_tokens") not in (None, ""):
            value = item["max_tokens"]
            if isinstance(value, bool):
                raise ApiError(
                    "provider_max_tokens_invalid",
                    data={"code": "provider_max_tokens_invalid"},
                )
            try:
                if str(int(value)) != str(value).strip():
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                raise ApiError(
                    "provider_max_tokens_invalid",
                    data={"code": "provider_max_tokens_invalid"},
                ) from None
            updates[prefix + "MAX_TOKENS"] = str(value)
        fallback = item.get("fallback_endpoint")
        if fallback not in (None, ""):
            fallback_text = _normalize_slot(str(fallback).strip())
            if fallback_text not in _SLOTS:
                raise ApiError(
                    "provider_fallback_slot_invalid",
                    data={"code": "provider_fallback_slot_invalid"},
                )
            updates[prefix + "FALLBACK_ENDPOINT"] = fallback_text
    result = _save(
        request,
        updates,
        expected_revision=_if_match(request.headers.get("if-match")),
        idempotency_key=request.headers.get("idempotency-key"),
        auth=auth,
    )
    result["restart_required"] = True
    return ok(result)


@router.get("/api/v1/platform/onebot")
async def platform_onebot(request: Request) -> Any:
    revision, _path = _store(request).current_revision("desired")
    values = revision.values
    raw_urls = values.get("ONEBOT_WS_URLS", "")
    try:
        ws_urls = json.loads(raw_urls) if raw_urls else []
    except ValueError:
        ws_urls = []
    if not isinstance(ws_urls, list):
        ws_urls = []
    return ok(
        {
            "host": values.get("HOST", "0.0.0.0"),
            "port": values.get("PORT", "8080"),
            "ws_urls": ws_urls,
            "has_token": bool(values.get("ONEBOT_ACCESS_TOKEN", "")),
            "desired_revision": revision.revision_id,
        }
    )


@router.put("/api/v1/platform/onebot")
async def platform_onebot_put(
    request: Request,
    payload: dict[str, Any],
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    updates: dict[str, Any] = {}
    if "ws_urls" in payload:
        urls = payload["ws_urls"]
        if not isinstance(urls, list) or any(not isinstance(url, str) for url in urls):
            raise ApiError(
                "onebot_ws_urls_invalid", data={"code": "onebot_ws_urls_invalid"}
            )
        cleaned = [url.strip() for url in urls if url.strip()]
        if any(not url.startswith(("ws://", "wss://")) for url in cleaned):
            raise ApiError(
                "onebot_ws_url_invalid", data={"code": "onebot_ws_url_invalid"}
            )
        updates["ONEBOT_WS_URLS"] = json.dumps(cleaned, ensure_ascii=False)
    if payload.get("access_token"):
        updates["ONEBOT_ACCESS_TOKEN"] = payload["access_token"]
    if "host" in payload:
        try:
            updates["HOST"] = ipaddress.ip_address(
                str(payload["host"]).strip()
            ).compressed
        except ValueError:
            raise ApiError(
                "onebot_host_invalid", data={"code": "onebot_host_invalid"}
            ) from None
    if "port" in payload:
        updates["PORT"] = payload["port"]
    result = _save(
        request,
        updates,
        expected_revision=_if_match(request.headers.get("if-match")),
        idempotency_key=request.headers.get("idempotency-key"),
        auth=auth,
    )
    result["restart_required"] = True
    return ok(result)


@router.get("/api/v1/platform/adapters")
async def platform_adapters(request: Request) -> Any:
    store = _store(request)
    desired, _desired_path = store.current_revision("desired")
    applied, _applied_path = store.current_revision("applied")
    configured_value = desired.values.get("STELLA_ADAPTER_MODULES")
    try:
        configured = parse_adapter_modules(configured_value)
        effective = parse_adapter_modules(applied.values.get("STELLA_ADAPTER_MODULES"))
    except ValueError:
        configured = ()
        effective = ()
    if configured_value is None:
        configured = DEFAULT_ADAPTER_MODULES
    return ok(
        {
            "modules": list(configured),
            "effective_modules": list(effective),
            "process_override": "STELLA_ADAPTER_MODULES" in os.environ,
            "desired_revision": desired.revision_id,
            "applied_revision": applied.revision_id,
        }
    )


@router.put("/api/v1/platform/adapters")
async def platform_adapters_put(
    request: Request,
    payload: dict[str, Any],
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    modules = payload.get("modules")
    if not isinstance(modules, list) or any(
        not isinstance(module, str) for module in modules
    ):
        raise ApiError(
            "adapter_modules_invalid", data={"code": "adapter_modules_invalid"}
        )
    try:
        parsed = parse_adapter_modules(",".join(module.strip() for module in modules))
    except ValueError as exc:
        raise ApiError(
            "adapter_modules_invalid", data={"code": "adapter_modules_invalid"}
        ) from exc
    result = _save(
        request,
        {"STELLA_ADAPTER_MODULES": ",".join(parsed) if parsed else "none"},
        expected_revision=_if_match(request.headers.get("if-match")),
        idempotency_key=request.headers.get("idempotency-key"),
        auth=auth,
    )
    result["modules"] = list(parsed)
    result["restart_required"] = True
    return ok(result)


@router.post("/api/v1/system/apply", status_code=202)
async def system_apply(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_auth)],
    payload: Annotated[dict[str, Any] | None, Body()] = None,
) -> Any:
    manager = _operations(request)
    try:
        operation = await manager.accept(
            "apply",
            target_revision=(payload or {}).get("revision_id"),
            idempotency_key=request.headers.get("idempotency-key"),
            actor=_actor(auth),
        )
    except OperationError as exc:
        raise _operation_api_error(exc) from exc
    return ok({"ok": True, **operation})


@router.post("/api/v1/system/restart", status_code=202)
async def system_restart(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    try:
        operation = await _operations(request).accept(
            "restart",
            idempotency_key=request.headers.get("idempotency-key"),
            actor=_actor(auth),
        )
    except OperationError as exc:
        raise _operation_api_error(exc) from exc
    return ok({"ok": True, **operation})


@router.post("/api/v1/system/core/start", status_code=202)
async def core_start(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    return await _core_operation(request, "core_start", auth)


@router.post("/api/v1/system/core/stop", status_code=202)
async def core_stop(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    return await _core_operation(request, "core_stop", auth)


@router.get("/api/v1/system/operations/{operation_id}")
async def operation_snapshot(operation_id: str, request: Request) -> Any:
    operation = _operations(request).get(operation_id)
    if operation is None:
        raise ApiError(
            "operation_not_found", status_code=404, data={"code": "operation_not_found"}
        )
    return ok(operation)


@router.get("/api/v1/system/operations/{operation_id}/events")
async def operation_events(
    operation_id: str, request: Request, after: int = 0
) -> Response:
    manager = _operations(request)
    if manager.get(operation_id) is None:
        raise ApiError(
            "operation_not_found", status_code=404, data={"code": "operation_not_found"}
        )
    last_id = request.headers.get("last-event-id")
    if last_id:
        try:
            after = max(after, int(last_id))
        except ValueError:
            raise ApiError(
                "event_cursor_invalid", data={"code": "event_cursor_invalid"}
            ) from None
    if after < 0:
        raise ApiError("event_cursor_invalid", data={"code": "event_cursor_invalid"})

    async def stream():
        cursor = after
        last_heartbeat = time.monotonic()
        while not await request.is_disconnected():
            events = manager.events(operation_id, cursor)
            if events and events[0]["id"] > cursor + 1:
                snapshot = manager.get(operation_id)
                data = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
                yield f"event: snapshot-required\ndata: {data}\n\n"
                cursor = events[0]["id"] - 1
            for event in events:
                payload_text = json.dumps(
                    event, ensure_ascii=False, separators=(",", ":")
                )
                yield f"id: {event['id']}\nevent: {event['phase']}\ndata: {payload_text}\n\n"
                cursor = event["id"]
            operation = manager.get(operation_id)
            if operation is None or (operation["terminal"] and not events):
                break
            if time.monotonic() - last_heartbeat >= 15:
                yield ": keep-alive\n\n"
                last_heartbeat = time.monotonic()
            await asyncio.sleep(0.2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/v1/status")
async def control_status(
    request: Request,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    store = _store(request)
    manager = _operations(request)
    snapshot = request.app.state.supervisor.snapshot
    public = (
        snapshot.public()
        if hasattr(snapshot, "public")
        else {
            "phase": getattr(snapshot, "phase", "unknown"),
            "revision_id": getattr(snapshot, "revision_id", None),
        }
    )
    age = _age_seconds(public.get("updated_at"))
    checker = getattr(request.app.state.supervisor, "core_reachable", None)
    reachable = (
        await checker()
        if checker is not None
        else public.get("phase") == "ready"
    )
    public.update(
        {
            "stale": not reachable,
            "stale_age_seconds": 0.0 if reachable else age,
        }
    )
    state = store.state()
    bootstrap = request.app.state.supervisor.bootstrap
    return ok(
        {
            "control": {
                "phase": "ready",
                "controller_boot_id": bootstrap.controller_boot_id,
                "instance_id": bootstrap.instance_id,
                "protocol_version": 1,
            },
            "core": public,
            "desired_revision": state.desired_revision,
            "applied_revision": state.applied_revision,
            "desired_core": state.desired_core,
            "external_conflict": state.external_conflict,
            "last_operation": manager.last_operation(),
            "webui": {"username": auth.username, "via": auth.via},
        }
    )


@router.get("/api/v1/system/doctor")
async def system_doctor(request: Request) -> Any:
    store = _store(request)
    snapshot = request.app.state.supervisor.snapshot
    state = store.state()
    return ok(
        {
            "checks": [
                {"name": "control_store", "ok": True, "fix_hint": None},
                {
                    "name": "core",
                    "ok": getattr(snapshot, "phase", None) == "ready",
                    "fix_hint": None
                    if getattr(snapshot, "phase", None) == "ready"
                    else "检查核心状态或重新应用当前配置",
                },
                {
                    "name": "desired_applied_revision",
                    "ok": state.desired_revision == state.applied_revision,
                    "fix_hint": None
                    if state.desired_revision == state.applied_revision
                    else "应用待生效配置",
                },
                {
                    "name": "external_config_conflict",
                    "ok": not state.external_conflict,
                    "fix_hint": None
                    if not state.external_conflict
                    else "检查外部配置编辑并重新保存",
                },
            ]
        }
    )


async def _core_operation(request: Request, kind: str, auth: AuthContext) -> Any:
    try:
        operation = await _operations(request).accept(
            kind,
            idempotency_key=request.headers.get("idempotency-key"),
            actor=_actor(auth),
        )
    except OperationError as exc:
        raise _operation_api_error(exc) from exc
    return ok({"ok": True, **operation})


def _save(
    request: Request,
    values: dict[str, Any],
    *,
    expected_revision: str | None,
    idempotency_key: str | None,
    auth: AuthContext,
) -> dict[str, Any]:
    try:
        return _store(request).save(
            values,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            actor=_actor(auth),
        )
    except ConfigStoreError as exc:
        conflicts = {
            "revision_conflict",
            "external_edit_conflict",
            "idempotency_conflict",
            "operation_in_progress",
        }
        raise ApiError(
            exc.code,
            status_code=409 if exc.code in conflicts else 400,
            data={"code": exc.code, "current_revision": exc.current_revision},
        ) from exc


def _store(request: Request) -> ConfigStore:
    store = getattr(request.app.state, "config_store", None)
    if store is None:
        raise ApiError(
            "config_store_unavailable",
            status_code=503,
            data={"code": "config_store_unavailable"},
        )
    return store


def _operations(request: Request) -> OperationManager:
    manager = getattr(request.app.state, "operation_manager", None)
    if manager is None:
        raise ApiError(
            "operation_manager_unavailable",
            status_code=503,
            data={"code": "operation_manager_unavailable"},
        )
    return manager


def _if_match(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if value.startswith("W/"):
        value = value[2:].strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    if not value or any(char in value for char in '\r\n"'):
        raise ApiError("if_match_invalid", data={"code": "if_match_invalid"})
    return value


def _normalize_slot(value: Any) -> str:
    slot = str(value or "").strip().upper()
    return _SLOT_ALIASES.get(slot, slot)


def _endpoint_value(
    values: Any, fields: dict[str, dict[str, Any]], slot: str, field: str
) -> str:
    for candidate in {
        "CHAT": ("CHAT", "LOCAL"),
        "MEMORY": ("MEMORY", "EXTRA", "ONLINE_MEMORY"),
        "VISION": ("VISION", "EXTRA_VISION"),
    }[slot]:
        value = values.get(f"LLM_ENDPOINT_{candidate}_{field}", "")
        if value:
            return str(value)
    schema_field = fields.get(f"LLM_ENDPOINT_{slot}_{field}", {})
    return str(schema_field.get("default", ""))


def _effective_value(values: Any, fields: dict[str, dict[str, Any]], key: str) -> str:
    value = values.get(key)
    field = fields.get(key, {})
    if value not in (None, "") or not field.get("inherits"):
        if value is not None:
            return str(value)
        return str(field.get("default", ""))
    parent = field["inherits"]
    return _effective_value(values, fields, parent)


def _actor(auth: AuthContext) -> dict[str, str]:
    return {"username": auth.username, "via": auth.via}


def _operation_api_error(exc: OperationError) -> ApiError:
    conflicts = {"revision_conflict", "operation_in_progress", "idempotency_conflict"}
    return ApiError(
        exc.code,
        status_code=409 if exc.code in conflicts else 400,
        data={"code": exc.code, "active_operation": exc.active_operation},
    )


def _age_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return max(
            0.0, round((datetime.now(timezone.utc) - timestamp).total_seconds(), 3)
        )
    except ValueError:
        return None
