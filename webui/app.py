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
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import config.settings as settings
from webui.auth import LoginRateLimiter
from webui.responses import ApiError, error
from webui.routers import auth as auth_router_module
from webui.routers import status as status_router_module
from webui.static import register_static

# importlib.metadata 查不到（源码直跑）时的回退版本号，与 status_api 同款惯例
_FALLBACK_VERSION = "4.0.0"

# 422 文案的字段标签：pydantic 的 loc 是英文键，直接拼出来用户看不懂——
# setup 页密码短一位就只看到「请求失败」是 2026-09-22 的实测教训。
_FIELD_LABELS = {
    "username": "用户名",
    "password": "密码",
    "old_password": "当前密码",
    "new_password": "新密码",
}


def _validation_message(errors: list[dict[str, Any]]) -> str:
    """把 pydantic 校验错误翻成一句人话（多错误用「；」连接）。"""
    parts: list[str] = []
    for err in errors:
        loc = [str(item) for item in err.get("loc", ()) if item != "body"]
        field = ".".join(loc)
        label = _FIELD_LABELS.get(field, field or "请求")
        etype = err.get("type", "")
        ctx = err.get("ctx") or {}
        if etype == "string_too_short":
            parts.append(f"{label}至少 {ctx.get('min_length', '?')} 个字符")
        elif etype == "string_too_long":
            parts.append(f"{label}至多 {ctx.get('max_length', '?')} 个字符")
        elif etype == "missing":
            parts.append(f"缺少{label}")
        else:
            parts.append(f"{label}格式不正确")
    return "；".join(parts) if parts else "请求参数不正确"


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
    # M1 只读面板（usage / providers / platform / plugins / conversations / trace / logs）
    from webui.routers import config as config_router_module
    from webui.routers import conversations as conversations_router_module
    from webui.routers import logs as logs_router_module
    from webui.routers import manage as manage_router_module
    from webui.routers import platform as platform_router_module
    from webui.routers import plugins as plugins_router_module
    from webui.routers import plugins_mg as plugins_mg_router_module
    from webui.routers import providers as providers_router_module
    from webui.routers import trace as trace_router_module
    from webui.routers import usage as usage_router_module

    app.include_router(usage_router_module.router)
    app.include_router(providers_router_module.router)
    app.include_router(platform_router_module.router)
    app.include_router(plugins_router_module.router)
    app.include_router(conversations_router_module.router)
    app.include_router(trace_router_module.router)
    app.include_router(logs_router_module.router)
    # M2 写入面（config/providers/platform/spaces/groups/system 一体的 config router）
    app.include_router(config_router_module.router)
    # M3 子系统管理（plugins 写侧 / mcp / skills / knowledge / scheduling）
    app.include_router(manage_router_module.mcp_router)
    app.include_router(manage_router_module.skills_router)
    app.include_router(manage_router_module.kb_router)
    app.include_router(manage_router_module.sched_router)
    app.include_router(plugins_mg_router_module.router)

    @app.exception_handler(ApiError)
    async def _api_error_handler(_request: Request, exc: ApiError):
        return JSONResponse(error(exc.message, exc.data), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(_request: Request, exc: RequestValidationError):
        # FastAPI 默认 422 是 {detail:[...]} 原生形状，前端 envelope 约定读不到
        # message——统一翻成 error envelope（契约见 openspec/openapi-v1.yaml）。
        return JSONResponse(
            error(_validation_message(exc.errors())), status_code=422
        )

    @app.exception_handler(Exception)
    async def _unhandled_handler(_request: Request, exc: Exception):
        # 兜底 500：内部细节（路径、库版本）不进响应体，只进进程日志
        return JSONResponse(
            error("服务器内部错误"), status_code=500
        )

    if settings.WEBUI_SERVE_DIST:
        register_static(app)
    return app
