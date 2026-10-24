# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Corona's auth routes, sharing the established password/JWT file contract."""

from __future__ import annotations

import json
import os
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from webui import security
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


def _record_auth(
    request: Request, *, username: str, via: str, action: str, result: str = "ok"
) -> None:
    """Write a password-free Corona-owned audit line with private file mode."""
    path = request.app.state.auth_audit_path
    entry = {
        "ts": time.time(),
        "username": username,
        "via": via,
        "action": action,
        "result": result,
        "method": request.method,
        "path": request.url.path,
        "client": client_host(request) or None,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY
        descriptor = os.open(path, flags, 0o600)
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return


def _issue_response(request: Request, record: dict, *, via: str) -> JSONResponse:
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
    _record_auth(
        request,
        username=record["username"],
        via=via,
        action=f"auth.{via}",
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
        _record_auth(
            request,
            username=body.username,
            via="login",
            action="auth.login",
            result="denied",
        )
        raise ApiError("用户名或密码错误", status_code=401)
    record = security.load_record()
    assert record is not None
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
    return _issue_response(request, record, via="account")
