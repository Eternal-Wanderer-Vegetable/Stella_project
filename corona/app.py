# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Control-only Corona ASGI app; business APIs remain in the Nucleus process."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from corona.auth import router as auth_router
from corona.bootstrap import CoronaBootstrap
from corona.config_api import router as config_api_router
from corona.config_store import ConfigStore
from corona.local_control import create_local_control_app, create_local_control_record
from corona.operations import OperationManager
from corona.supervisor import CoreSupervisor
from stella_contracts.control import CONTROL_PROTOCOL_VERSION
from webui.responses import ApiError, error, ok
from webui.security import configure_auth_runtime, reset_auth_runtime

logger = logging.getLogger("corona")


def create_corona_app(
    bootstrap: CoronaBootstrap,
    supervisor: CoreSupervisor,
    *,
    config_store: ConfigStore | None = None,
    operation_manager: OperationManager | None = None,
    startup_decision=None,
) -> FastAPI:
    local_control_record = create_local_control_record(bootstrap)
    configure_auth_runtime(
        stella_home=bootstrap.stella_home,
        token_ttl_hours=bootstrap.token_ttl_hours,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks: list[asyncio.Task] = []
        app.state.rate_limiter = _rate_limiter(bootstrap.login_ratelimit_per_min)
        decision = app.state.startup_decision
        if decision is None or decision.action == "normal":
            if decision is None or decision.start_core:
                await supervisor.start()
            else:
                await supervisor.stop()
        elif decision.start_core:
            await supervisor.start_once()
        else:
            await supervisor.stop()
        if operation_manager is not None:
            await operation_manager.finalize_startup_recovery(
                decision, supervisor.snapshot
            )
        if bootstrap.webui_enabled and bootstrap.serve_dist:
            tasks.append(asyncio.create_task(_build_dashboard(bootstrap)))
        try:
            yield
        finally:
            await supervisor.stop()
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            reset_auth_runtime()

    app = FastAPI(
        title="Stella Corona Control API",
        version="1",
        openapi_url="/api/v1/openapi.json" if bootstrap.webui_enabled else None,
        docs_url="/api/v1/docs" if bootstrap.webui_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.supervisor = supervisor
    app.state.config_store = config_store
    app.state.operation_manager = operation_manager
    app.state.startup_decision = startup_decision
    app.state.auth_audit_path = bootstrap.log_dir / "corona_auth_audit.jsonl"
    app.state.local_control_record = local_control_record
    app.state.local_control_app = create_local_control_app(
        bootstrap, supervisor, local_control_record
    )

    @app.api_route(
        "/_corona/local",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    @app.api_route(
        "/_corona/local/{local_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def local_control_is_not_public(_request: Request):
        return JSONResponse({"error": {"code": "not_found"}}, status_code=404)

    if bootstrap.webui_enabled:
        app.state.rate_limiter = _rate_limiter(bootstrap.login_ratelimit_per_min)
        app.include_router(auth_router)
        if config_store is not None and operation_manager is not None:
            app.include_router(config_api_router)

        @app.get("/api/v1/system/core")
        async def core_status(request: Request):
            _require_admin(request)
            return ok(supervisor.snapshot.public())

        if bootstrap.serve_dist:
            from webui.static import register_static_from_directory

            register_static_from_directory(
                app, bootstrap.project_root / "webui" / "dist"
            )

    @app.get("/_corona/v1/health")
    async def corona_health(request: Request):
        _require_loopback(request)
        return ok(
            {
                "controller_boot_id": bootstrap.controller_boot_id,
                "instance_id": bootstrap.instance_id,
                "control_protocol_version": CONTROL_PROTOCOL_VERSION,
                "revision_id": bootstrap.revision.revision_id,
                "core_phase": supervisor.snapshot.phase,
                "generation_id": getattr(supervisor.snapshot, "generation_id", None),
                "webui_enabled": bootstrap.webui_enabled,
            }
        )

    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError):
        return JSONResponse(error(exc.message, exc.data), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, _exc: Exception):
        logger.exception("unhandled Corona request error")
        return JSONResponse(error("服务器内部错误"), status_code=500)

    return app


def _rate_limiter(capacity: int):
    from webui.auth import LoginRateLimiter

    return LoginRateLimiter(capacity)


async def _build_dashboard(bootstrap: CoronaBootstrap) -> None:
    from webui.source_build import rebuild_source_dashboard

    try:
        await asyncio.to_thread(
            rebuild_source_dashboard, bootstrap.project_root, bootstrap.serve_dist
        )
    except Exception as exc:
        logger.warning(
            "Dashboard source build failed (%s); Corona control API remains available",
            type(exc).__name__,
        )


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host.lower() == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ApiError("仅允许本机访问", status_code=403)


def _require_admin(request: Request) -> None:
    from webui.auth import require_auth

    require_auth(request)
