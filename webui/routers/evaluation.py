# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""隔离验证执行器路由（计划 §6.7 / M5：Dashboard 实验入口）。

固定 schema body（计划 §6.7.2：不接任意代码/pickle/shell）；service 只以
固定参数启动评测 CLI。全部端点走 ``require_auth``，风格照抄 trace router。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from webui.auth import require_auth
from webui.responses import ApiError, ok
from webui.services import evaluation as evaluation_service

router = APIRouter(
    tags=["evaluation"], dependencies=[Depends(require_auth)]
)


class EvaluationRunRequest(BaseModel):
    """POST /runs 的固定 schema：只有这几个字段，多了不带、少了不行。"""

    mode: str = Field(..., description="trace_playback/decision_recompute/isolated_pipeline/model_validation")
    dataset: str = Field(..., description="数据集目录（绝对路径，必须已存在）")
    snapshot: str | None = Field(None, description="可选快照目录")
    seed: int | None = Field(None, description="随机种子（仅记录）")
    budget_max_calls: int | None = Field(None, ge=0, description="模型调用预算上限")
    budget_timeout: float | None = Field(None, gt=0, description="墙钟预算（秒）")


def _map_service_error(exc: Exception) -> ApiError:
    message = str(exc)
    if isinstance(exc, FileNotFoundError):
        return ApiError(message, status_code=404)
    return ApiError(message, status_code=400)


@router.post("/api/v1/evaluation/runs")
async def create_evaluation_run(payload: EvaluationRunRequest) -> Any:
    """启动一次隔离实验（并发上限 1；重复启动返回 400）。"""
    try:
        handle = evaluation_service.start_run(
            payload.mode,
            payload.dataset,
            snapshot=payload.snapshot,
            seed=payload.seed,
            budget_max_calls=payload.budget_max_calls,
            budget_timeout=payload.budget_timeout,
        )
    except (ValueError, RuntimeError) as exc:
        raise _map_service_error(exc) from None
    return ok(handle)


@router.get("/api/v1/evaluation/runs")
async def list_evaluation_runs(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Any:
    return ok({"items": evaluation_service.list_runs(limit=limit)})


@router.get("/api/v1/evaluation/runs/{run_id}")
async def evaluation_run_detail(run_id: str) -> Any:
    detail = evaluation_service.get_run(run_id)
    if detail is None:
        raise ApiError("实验不存在", status_code=404)
    return ok(detail)


@router.post("/api/v1/evaluation/runs/{run_id}/cancel")
async def cancel_evaluation_run(run_id: str) -> Any:
    try:
        handle = evaluation_service.cancel_run(run_id)
    except ValueError:
        raise ApiError("实验不存在", status_code=404) from None
    return ok(handle)
