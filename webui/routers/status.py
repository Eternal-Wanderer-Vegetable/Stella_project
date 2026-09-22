# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""状态聚合路由：``GET /api/v1/status``（方案 §7.1）。

数据来自 :mod:`webui.status_source`——宿主（bot.py）注入 v1 的
``collect_status``，独立模式回退最小 payload。webui 自身不 import
``plugins.bot_main``（依赖方向见 status_source 模块注释）。区别于 v1
``/stella/status``（回环 + 无凭据）：本路由面向已登录管理员，附 webui
身份段。响应同样不含凭据与消息内容（红线见方案 §9.5，测试钉死）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from webui.auth import AuthContext, require_auth
from webui.responses import ok
from webui.status_source import collect_status

router = APIRouter(tags=["status"])


def _payload(auth: AuthContext) -> dict:
    data = collect_status()
    data["webui"] = {"username": auth.username, "via": auth.via}
    return data


@router.get("/api/v1/status")
async def status(auth: Annotated[AuthContext, Depends(require_auth)]) -> Any:
    return ok(_payload(auth))
