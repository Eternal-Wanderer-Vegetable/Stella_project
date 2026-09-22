# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""鉴权路由（契约见 openspec/openapi-v1.yaml 的 auth tag）。

本路由是唯一含公开端点的路由（setup-status / setup / login /
desktop-session）——它们是鉴权的入口，其余端点一律要求已登录。公开端点
共同的防线：登录限流（app.state.rate_limiter，见 webui.auth）+ 各自的
状态校验（未初始化不能登录、已初始化不能重复 setup、secret 不对不能换
desktop-session）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from webui import audit, security
from webui.auth import AuthContext, client_host, require_auth, verify_desktop_session
from webui.responses import ApiError, ok

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class CredentialsBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class AccountBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    username: str | None = Field(default=None, min_length=1, max_length=64)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


def _issue_response(request: Request, record: dict, *, via: str) -> JSONResponse:
    """签发 token 并组装响应（附 HttpOnly Cookie 补充通道）。

    不设 Secure 标志：Stella 的部署形态是明文 HTTP（TLS 由反代负责，见方案
    §9.2），设了 Secure 会让 Cookie 通道在所有现有部署下失效。
    """
    token, expires_at = security.create_token(record)
    response = JSONResponse(
        ok(
            {
                "token": token,
                "expires_at": expires_at,
                "username": record["username"],
            }
        )
    )
    response.set_cookie(
        security.COOKIE_NAME,
        token,
        max_age=security.token_ttl_hours() * 3600,
        httponly=True,
        samesite="strict",
        path="/",
    )
    audit.record(
        request=request,
        username=record["username"],
        via=via,
        action=f"auth.{via}",
        detail={"client": client_host(request)},
    )
    return response


@router.get("/setup-status")
async def setup_status() -> dict:
    return ok({"setup_required": security.setup_required()})


@router.post("/setup")
async def setup(body: CredentialsBody, request: Request) -> Any:
    request.app.state.rate_limiter.check("setup")
    record = security.setup_admin(body.username, body.password)
    return _issue_response(request, record, via="setup")


@router.post("/login")
async def login(body: CredentialsBody, request: Request) -> Any:
    request.app.state.rate_limiter.check("login")
    if not security.verify_credentials(body.username, body.password):
        audit.record(
            request=request,
            username=body.username,
            via="login",
            action="auth.login",
            result="denied",
        )
        raise ApiError("用户名或密码错误", status_code=401)
    record = security.load_record()
    assert record is not None  # verify 通过则记录必然存在
    return _issue_response(request, record, via="login")


@router.post("/desktop-session")
async def desktop_session(request: Request) -> Any:
    request.app.state.rate_limiter.check("desktop")
    verify_desktop_session(request)
    record = security.load_record()
    if record is None:
        raise ApiError("尚未初始化，请先完成 setup", status_code=401)
    return _issue_response(request, record, via="desktop")


@router.get("/me")
async def me(auth: Annotated[AuthContext, Depends(require_auth)]) -> dict:
    return ok({"username": auth.username, "via": auth.via})


@router.post("/logout")
async def logout() -> JSONResponse:
    """清 Cookie。JWT 无状态，服务端没有会话可删；前端自行清除本地 token。"""
    response = JSONResponse(ok())
    response.delete_cookie(security.COOKIE_NAME, path="/")
    return response


@router.patch("/account")
async def update_account(
    body: AccountBody,
    request: Request,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    if not security.verify_credentials(auth.username, body.old_password):
        raise ApiError("当前密码错误", status_code=401)
    record = security.load_record()
    if record is None:
        raise ApiError("管理员凭据缺失", status_code=401)
    if not body.username and not body.new_password:
        raise ApiError("没有需要修改的内容")
    record = security.update_credentials(
        record,
        new_username=body.username,
        new_password=body.new_password,
    )
    # 改密码已轮换 jwt_secret，旧 token 全部失效——响应里必须带新 token
    return _issue_response(request, record, via="account")
