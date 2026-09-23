# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""M2 写入面路由：config / providers 编辑 / platform 编辑 / spaces / groups / system。

共同约定：所有写操作过审计（webui.audit）；配置类写返回
``restart_required: true``（settings import 期冻结，方案 §4 D6）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from webui import audit
from webui.auth import AuthContext, require_auth
from webui.responses import ok
from webui.services import config as config_service
from webui.services import groups as groups_service
from webui.services import platformcfg as platformcfg_service
from webui.services import providers as providers_service
from webui.services import spaces as spaces_service

router = APIRouter(tags=["config"], dependencies=[Depends(require_auth)])


def _audited(request: Any, auth: AuthContext, action: str, **detail: Any) -> None:
    audit.record(request=request, username=auth.username, via=auth.via, action=action,
                 detail=detail or None)


# ---------- 配置（.env schema 驱动） ----------

@router.get("/api/v1/config/schema")
async def config_schema() -> Any:
    return ok(config_service.current())


@router.get("/api/v1/config")
async def config_current() -> Any:
    return ok(config_service.current())


@router.put("/api/v1/config")
async def config_update(
    request: Request,
    payload: dict[str, str],
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    result = config_service.update(payload)
    _audited(request, auth, "config.update", keys=result.get("written", []))
    return ok(result)


# ---------- 提供商（端点槽 × 角色绑定） ----------

@router.get("/api/v1/providers/endpoints")
async def providers_endpoints() -> Any:
    return ok({"endpoints": providers_service.endpoints()})


@router.put("/api/v1/providers/endpoints")
async def providers_endpoints_put(
    request: Request,
    payload: list[dict],
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    result = providers_service.update_endpoints(payload)
    _audited(request, auth, "providers.endpoints", slots=[p.get("slot") for p in payload])
    return ok(result)


@router.get("/api/v1/providers/roles")
async def providers_roles() -> Any:
    return ok({"roles": providers_service.roles()})


@router.put("/api/v1/providers/roles")
async def providers_roles_put(
    request: Request,
    payload: list[dict],
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    result = providers_service.update_roles(payload)
    _audited(request, auth, "providers.roles")
    return ok(result)


@router.get("/api/v1/providers/models")
async def providers_models(
    base_url: str,
    api_key: str = "",
) -> Any:
    return ok(await providers_service.fetch_models(base_url, api_key))


@router.post("/api/v1/providers/test")
async def providers_test(payload: dict) -> Any:
    return ok(
        await providers_service.test_endpoint(
            payload.get("base_url", ""), payload.get("api_key", ""), payload.get("model", "")
        )
    )


# ---------- 平台（OneBot 连接配置） ----------

@router.get("/api/v1/platform/onebot")
async def platform_onebot() -> Any:
    return ok(platformcfg_service.onebot())


@router.put("/api/v1/platform/onebot")
async def platform_onebot_put(
    request: Request,
    payload: dict,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    result = platformcfg_service.update(payload)
    _audited(request, auth, "platform.onebot")
    return ok(result)


# ---------- 空间（人格） ----------

@router.get("/api/v1/spaces")
async def spaces_list() -> Any:
    return ok({"spaces": spaces_service.list_spaces()})


@router.post("/api/v1/spaces")
async def spaces_create(payload: dict) -> Any:
    return ok(spaces_service.create_space(payload.get("name", ""), system_prompt=payload.get("system_prompt", "")))


@router.get("/api/v1/spaces/default")
async def spaces_default() -> Any:
    return ok(spaces_service.default_prompt())


@router.get("/api/v1/spaces/{name}/prompt")
async def space_prompt(name: str) -> Any:
    return ok({"name": name, "text": spaces_service.get_prompt(name)})


@router.put("/api/v1/spaces/{name}/prompt")
async def space_prompt_put(name: str, payload: dict) -> Any:
    return ok(spaces_service.put_prompt(name, payload.get("text", "")))


@router.put("/api/v1/spaces/{name}/bindings")
async def space_bindings_put(name: str, payload: dict) -> Any:
    return ok(spaces_service.put_bindings(name, [int(g) for g in payload.get("qq_groups", [])]))


@router.delete("/api/v1/spaces/{name}")
async def space_delete(name: str) -> Any:
    spaces_service.delete_space(name)
    return ok({"name": name})


# ---------- 群组 ----------

@router.get("/api/v1/groups")
async def groups_list() -> Any:
    return ok({"groups": groups_service.list_groups()})


@router.put("/api/v1/groups/bindings")
async def groups_bindings(payload: list[dict]) -> Any:
    return ok(groups_service.set_bindings(payload))


@router.post("/api/v1/groups/{group_id}/mute")
async def group_mute(group_id: int) -> Any:
    return ok(groups_service.set_mute(group_id, muted=True, actor="webui"))


@router.post("/api/v1/groups/{group_id}/unmute")
async def group_unmute(group_id: int) -> Any:
    return ok(groups_service.set_mute(group_id, muted=False, actor="webui"))


# ---------- 系统（重启 / doctor） ----------

@router.post("/api/v1/system/restart")
async def system_restart() -> Any:
    from webui.services.system import restart

    return ok(restart())


@router.get("/api/v1/system/doctor")
async def system_doctor() -> Any:
    from webui.services.system import run_doctor

    return ok(await run_doctor())
