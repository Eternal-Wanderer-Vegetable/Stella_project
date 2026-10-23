# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Assemble only business WebUI routes inside the managed Nucleus process."""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.routing import APIRoute
from starlette.routing import Mount

from corona.routes import BUSINESS_ROUTE_KEYS
from nucleus.group_bindings import GroupBindingsStore
from webui.app import create_webui_app, webui_route_routers
from webui.responses import ApiError, ok


def create_nucleus_business_app(
    *, group_bindings_store: GroupBindingsStore | None = None
) -> FastAPI:
    """Build a Nucleus-only app and fail startup if the frozen route set drifts."""
    source_app = create_webui_app(include_static=False)
    app = FastAPI(
        title="Stella Nucleus Business API",
        version="1",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.exception_handlers = dict(source_app.exception_handlers)
    counts: Counter[tuple[str, str]] = Counter()

    for source_router in webui_route_routers():
        for route in source_router.routes:
            if not isinstance(route, APIRoute):
                continue
            methods = {
                method
                for method in route.methods or ()
                if (method, route.path) in BUSINESS_ROUTE_KEYS
            }
            if not methods:
                continue
            for method in methods:
                counts[(method, route.path)] += 1
            app.router.routes.append(_clone_route(route, app, methods))

    missing = BUSINESS_ROUTE_KEYS - set(counts)
    duplicates = sorted(key for key, count in counts.items() if count != 1)
    if missing or duplicates:
        raise RuntimeError(
            "Nucleus route assembly differs from the ownership contract "
            f"(missing={len(missing)}, duplicates={len(duplicates)})"
        )
    app.state.route_keys = frozenset(counts)
    app.include_router(
        _private_group_bindings_router(
            group_bindings_store or GroupBindingsStore.configured()
        )
    )
    return app


def mount_nucleus_business_routes(application: Any) -> None:
    """Mount the filtered app after adapter and status routes in managed mode."""
    for route in getattr(application, "routes", ()):
        if not isinstance(route, Mount) or route.path not in {"", "/"}:
            continue
        if route.name == "nucleus-business":
            return
        raise RuntimeError("a root WebUI mount already exists in managed Nucleus")
    application.mount("/", create_nucleus_business_app(), name="nucleus-business")


def _clone_route(route: APIRoute, app: FastAPI, methods: set[str]) -> APIRoute:
    return APIRoute(
        path=route.path,
        endpoint=route.endpoint,
        response_model=route.response_model,
        status_code=route.status_code,
        tags=route.tags,
        dependencies=route.dependencies,
        summary=route.summary,
        description=route.description,
        response_description=route.response_description,
        responses=route.responses,
        deprecated=route.deprecated,
        name=route.name,
        methods=methods,
        operation_id=route.operation_id,
        response_model_include=route.response_model_include,
        response_model_exclude=route.response_model_exclude,
        response_model_by_alias=route.response_model_by_alias,
        response_model_exclude_unset=route.response_model_exclude_unset,
        response_model_exclude_defaults=route.response_model_exclude_defaults,
        response_model_exclude_none=route.response_model_exclude_none,
        include_in_schema=route.include_in_schema,
        response_class=route.response_class,
        dependency_overrides_provider=app,
        callbacks=route.callbacks,
        openapi_extra=route.openapi_extra,
        generate_unique_id_function=route.generate_unique_id_function,
        strict_content_type=route.strict_content_type,
    )


def _private_group_bindings_router(store: GroupBindingsStore) -> APIRouter:
    router = APIRouter()

    @router.post("/_nucleus/v1/private/groups/bindings/validate")
    async def validate_bindings(request: Request, payload: dict[str, Any]):
        _require_managed_admin(request)
        bindings, snapshot = store.validate(payload.get("bindings"))
        return ok({"bindings": bindings, "snapshot": snapshot})

    @router.post("/_nucleus/v1/private/groups/bindings/apply")
    async def apply_bindings(request: Request, payload: dict[str, Any]):
        _require_managed_admin(request)
        operation_id = payload.get("operation_id")
        expected_digest = payload.get("expected_digest")
        if not isinstance(operation_id, str) or not operation_id:
            raise ApiError("operation_id_invalid")
        if not isinstance(expected_digest, str):
            raise ApiError("spaces_revision_invalid")
        result = store.apply(
            operation_id=operation_id,
            bindings=payload.get("bindings"),
            expected_digest=expected_digest,
        )
        return ok(result)

    @router.post("/_nucleus/v1/private/groups/bindings/rollback")
    async def rollback_bindings(request: Request, payload: dict[str, Any]):
        _require_managed_admin(request)
        operation_id = payload.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise ApiError("operation_id_invalid")
        return ok(store.rollback(operation_id))

    return router


def _require_managed_admin(request: Request) -> None:
    state = request.scope.get("state") or {}
    actor = state.get("stella_actor")
    if (
        state.get("stella_internal_authenticated") is not True
        or not isinstance(actor, dict)
        or actor.get("kind") != "admin"
        or actor.get("authentication") != "jwt"
    ):
        raise ApiError("unauthorized", status_code=401)
