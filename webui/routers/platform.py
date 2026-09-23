# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""平台链路路由（M1 只读：OneBot 心跳/探活/健康度；连接配置编辑属 M2）。

``link_status()`` 的键在未连接时是显式 ``None``（link_monitor 契约并警告过
消费方），原样透传，前端按可空渲染。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from webui.auth import require_auth
from webui.responses import ok
from webui.services import runtime as runtime_service

router = APIRouter(
    tags=["platform"], dependencies=[Depends(require_auth)]
)


@router.get("/api/v1/platform/link")
async def platform_link() -> Any:
    return ok(runtime_service.platform_link())
