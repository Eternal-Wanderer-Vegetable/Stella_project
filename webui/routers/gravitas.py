# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Dedicated read-only status endpoint for the Gravitas controller."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from webui.auth import AuthContext, require_auth
from webui.responses import ok
from webui.status_source import collect_status

router = APIRouter(tags=["gravitas"])


@router.get("/api/v1/gravitas/status")
async def gravitas_status(
    _auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    """Return only the sanitized Gravitas DTO from the Nucleus status source."""
    payload = collect_status()
    gravitas = payload.get("gravitas") if isinstance(payload, dict) else None
    return ok({"gravitas": gravitas})
