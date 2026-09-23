# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""插件清单路由（M1 只读；启停/重载/配置/安装属 M3）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from webui.auth import require_auth
from webui.responses import ok
from webui.services import plugins as plugins_service

router = APIRouter(
    tags=["plugins"], dependencies=[Depends(require_auth)]
)


@router.get("/api/v1/plugins")
async def list_plugins() -> Any:
    return ok(plugins_service.plugin_inventory())
