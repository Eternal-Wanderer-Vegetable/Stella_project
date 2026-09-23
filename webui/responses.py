# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""统一响应 envelope（对齐 AstrBot Dashboard 的响应约定，方案 §4 D4）。

所有业务接口返回 200 + ``{"status": "ok"|"error", "message": ..., "data": ...}``；
真正的 HTTP 错误码只保留给协议级语义：401（未授权/过期）、403（禁止）、
404、413（超限）、429（限流）、500。前端据此约定统一处理（http 拦截器只
看 HTTP 码，页面代码看 envelope 的 status 字段）。

业务侧抛 :class:`ApiError` 即可，由 app.py 的异常处理器统一转 envelope——
路由代码不手写错误响应。
"""

from __future__ import annotations

from typing import Any


def ok(data: Any = None, message: str | None = None) -> dict:
    """成功 envelope。data 允许为 None（写操作常无返回体）。"""
    return {"status": "ok", "message": message, "data": data}


def error(message: str, data: Any = None) -> dict:
    """失败 envelope。message 面向人（可直接 toast），不做国际化键。"""
    return {"status": "error", "message": message, "data": data}


class ApiError(Exception):
    """业务错误：抛出后由全局异常处理器转为 error envelope。

    ``status_code`` 默认 400；鉴权类错误请显式给 401/403，限流给 429——
    前端的登录态拦截器依赖这些语义码。
    """

    def __init__(self, message: str, *, status_code: int = 400, data: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data
