# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""鉴权共享层：JWT 校验依赖、登录限流、desktop-session 校验（方案 §9）。

限流放在验证**之前**：爆破攻击观察不到「密码对不对」的差异响应，三次
试错之后的请求连验证函数都进不去。桶按客户端 IP 分键、进程内计数——
单进程部署（Stella 的唯一形态）下这就是完整语义，不需要外部存储。
"""

from __future__ import annotations

import time

from fastapi import Request

import config.settings as settings
from webui import security
from webui.responses import ApiError


class AuthContext:
    """一次已认证请求的身份。via 区分正常登录与桌面壳免登录（审计用）。"""

    def __init__(self, username: str, via: str):
        self.username = username
        self.via = via


class LoginRateLimiter:
    """令牌桶限流（按分钟补充）。容量与速率在构造时从配置读取。

    挂在 ``app.state`` 上（见 app.py）——每个 app 实例独立一只桶，测试
    天然隔离；重启清零是可接受的（限流防的是分钟级爆破，不是记账）。
    """

    def __init__(self, capacity: int):
        self.capacity = max(1, int(capacity))
        self._tokens = float(self.capacity)
        self._refill_per_second = self.capacity / 60.0
        self._updated = time.monotonic()

    def _take(self) -> bool:
        now = time.monotonic()
        self._tokens = min(
            float(self.capacity),
            self._tokens + (now - self._updated) * self._refill_per_second,
        )
        self._updated = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def check(self, key: str) -> None:
        """超限抛 429。key 建议带端点前缀（login:/setup: 各算各的桶）。"""
        if not self._take():
            raise ApiError(
                "尝试过于频繁，请稍后再试",
                status_code=429,
            )


def client_host(request: Request) -> str:
    """客户端地址；取不到按「未知」处理（各端点自己决定放不放行）。"""
    return request.client.host if request.client else ""


def require_auth(request: Request) -> AuthContext:
    """FastAPI 依赖：校验 Bearer 头或 Cookie 中的 JWT。

    Cookie 是补充通道：图片直链、文件下载这类没法带自定义头的请求用。
    desktop-session 换发的 token 与普通 token 形状一致，这里不区分——
    区分只在签发时刻记审计。
    """
    token = ""
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        token = request.cookies.get(security.COOKIE_NAME, "").strip()
    if not token:
        raise ApiError("未授权", status_code=401)
    username = security.decode_token(token)
    return AuthContext(username=username, via="jwt")


def verify_desktop_session(request: Request) -> None:
    """desktop-session 端点的三道门：secret 配置存在 → secret 恒定时间相等
    → 客户端来自回环。任一不过一律 401/403，不给探测空间。"""
    expected = security.desktop_session_secret()
    provided = request.headers.get("X-Stella-Desktop-Session", "").strip()
    if expected is None:
        raise ApiError("桌面免登录未启用", status_code=401)
    import hmac as _hmac

    if not _hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    ):
        raise ApiError("桌面免登录凭证无效", status_code=401)
    host = client_host(request)
    if not _is_loopback(host):
        raise ApiError("桌面免登录仅限本机", status_code=403)


def _is_loopback(host: str | None) -> bool:
    """回环判断。与 status_api._is_loopback 同语义但不跨模块复用——那是
    v1 只读面的守卫，这里是鉴权面的一部分，各自独立演化（宁重十条，不锁死）。"""
    if not host:
        return False
    import ipaddress

    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def rate_limit_capacity() -> int:
    return int(settings.WEBUI_LOGIN_RATELIMIT_PER_MIN)
