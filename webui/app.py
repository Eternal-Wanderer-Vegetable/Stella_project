# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""WebUI 子应用装配（方案 §5 webui/app.py）。

被 mount.py 挂到 NoneBot ASGI app 的 ``/`` 上；也可独立实例化（测试、
未来的带外管理形态）。路由注册顺序是本文件的隐性契约：API 路由在前，
静态 catch-all 最后（见 static.register_static 的注释）。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import config.settings as settings
from webui.auth import LoginRateLimiter
from webui.responses import ApiError, error
from webui.routers import auth as auth_router_module
from webui.routers import status as status_router_module
from webui.static import register_static

# importlib.metadata 查不到（源码直跑）时的回退版本号，与 status_api 同款惯例
_FALLBACK_VERSION = "4.0.0"


def _project_version() -> str:
    try:
        return version("stella_project")
    except PackageNotFoundError:
        return _FALLBACK_VERSION


def create_webui_app() -> FastAPI:
    app = FastAPI(
        title="Stella WebUI API",
        version=_project_version(),
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.state.rate_limiter = LoginRateLimiter(
        int(settings.WEBUI_LOGIN_RATELIMIT_PER_MIN)
    )
    app.include_router(auth_router_module.router)
    app.include_router(status_router_module.router)

    @app.exception_handler(ApiError)
    async def _api_error_handler(_request: Request, exc: ApiError):
        return JSONResponse(error(exc.message, exc.data), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled_handler(_request: Request, exc: Exception):
        # 兜底 500：内部细节（路径、库版本）不进响应体，只进进程日志
        return JSONResponse(
            error("服务器内部错误"), status_code=500
        )

    if settings.WEBUI_SERVE_DIST:
        register_static(app)
    return app
