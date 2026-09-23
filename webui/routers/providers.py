# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""提供商运行态路由（M1 只读：调度器闸门 + 降级状态；配置读写属 M2）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from webui.auth import require_auth
from webui.responses import ok
from webui.services import runtime as runtime_service

router = APIRouter(
    tags=["providers"], dependencies=[Depends(require_auth)]
)


@router.get("/api/v1/providers/runtime")
async def providers_runtime() -> Any:
    return ok(runtime_service.providers_runtime())
