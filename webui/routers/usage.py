# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""用量路由（契约见 openspec/openapi-v1.yaml 的 usage tag，M1）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from webui.auth import require_auth
from webui.responses import ok
from webui.services import usage as usage_service

router = APIRouter(
    tags=["usage"], dependencies=[Depends(require_auth)]
)


@router.get("/api/v1/usage/today")
async def usage_today() -> Any:
    return ok(usage_service.today())


@router.get("/api/v1/usage/daily")
async def usage_daily(
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> Any:
    return ok(usage_service.daily(days))
