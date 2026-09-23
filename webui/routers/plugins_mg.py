# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""插件管理路由（M3 写侧：启停/重载/配置/安装/卸载/市场源/市场）。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from webui import audit
from webui.auth import AuthContext, require_auth
from webui.responses import ApiError, ok
from webui.services import plugins_manage as mg

router = APIRouter(
    tags=["plugins"], dependencies=[Depends(require_auth)]
)


@router.patch("/api/v1/plugins/enabled")
async def plugins_enabled(
    request: Request,
    payload: dict,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    result = mg.set_enabled(payload["plugin_id"], enabled=bool(payload["enabled"]))
    audit.record(request=request, username=auth.username, via=auth.via,
                 action="plugins.enabled", detail=dict(payload))
    return ok(result)


@router.post("/api/v1/plugins/reload")
async def plugins_reload(
    request: Request,
    payload: dict,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    result = await mg.reload(payload["plugin_id"])
    audit.record(request=request, username=auth.username, via=auth.via,
                 action="plugins.reload", detail=dict(payload))
    return ok(result)


@router.get("/api/v1/plugins/config")
async def plugins_config(plugin_id: str) -> Any:
    return ok(mg.plugin_config(plugin_id))


@router.put("/api/v1/plugins/config")
async def plugins_config_put(
    request: Request,
    payload: dict,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    result = mg.save_plugin_config(payload["plugin_id"], payload.get("config", {}))
    audit.record(request=request, username=auth.username, via=auth.via,
                 action="plugins.config", detail={"plugin_id": payload["plugin_id"]})
    return ok(result)


@router.get("/api/v1/plugins/readme")
async def plugins_readme(plugin_id: str) -> Any:
    return ok({"plugin_id": plugin_id, "readme": mg.readme(plugin_id)})


@router.post("/api/v1/plugins/install")
async def plugins_install(
    request: Request,
    payload: dict,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    source = payload.get("source")
    if source == "github":
        result = mg.install_from_github(payload.get("repo", ""))
    elif source == "url":
        result = mg.install_from_url(payload.get("url", ""))
    else:
        raise ApiError("source 必须是 github 或 url（上传走 /plugins/install/upload）")
    audit.record(request=request, username=auth.username, via=auth.via,
                 action="plugins.install", detail={"source": source, "ok": result.get("ok")})
    return ok(result)


@router.post("/api/v1/plugins/install/upload")
async def plugins_install_upload(
    request: Request,
    payload: dict,
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> Any:
    """M3 简化：上传通道接收服务端已落盘的 zip 路径（由 /api/v1/files 上传），
    避免在路由层重复处理 multipart 流。"""
    zip_path = Path(payload.get("upload_path", ""))
    if not zip_path.is_file():
        raise ApiError("上传文件不存在", status_code=404)
    result = mg.install_from_zip_bytes(zip_path.read_bytes())
    audit.record(request=request, username=auth.username, via=auth.via,
                 action="plugins.install", detail={"source": "upload"})
    return ok(result)


@router.delete("/api/v1/plugins/{plugin_id}")
async def plugins_uninstall(
    request: Request,
    plugin_id: str,
    remove_config: bool = False,
    remove_data: bool = False,
    auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    result = mg.uninstall(plugin_id, remove_config=remove_config, remove_data=remove_data)
    audit.record(request=request, username=auth.username, via=auth.via,
                 action="plugins.uninstall", detail={"plugin_id": plugin_id})
    return ok(result)


# ---------- 市场多源 ----------

@router.get("/api/v1/plugin-sources")
async def sources_list() -> Any:
    return ok({"sources": mg.list_sources()})


@router.post("/api/v1/plugin-sources")
async def sources_add(payload: dict) -> Any:
    sources = mg.list_sources()
    sources.append(
        {
            "id": payload.get("id", ""),
            "name": payload.get("name", payload.get("id", "")),
            "url": payload.get("url", ""),
            "enabled": bool(payload.get("enabled", True)),
        }
    )
    return ok(mg.save_sources(sources))


@router.put("/api/v1/plugin-sources/{source_id}")
async def sources_update(source_id: str, payload: dict) -> Any:
    sources = mg.list_sources()
    for src in sources:
        if src["id"] == source_id:
            src.update({k: v for k, v in payload.items() if k in ("name", "url", "enabled")})
            return ok(mg.save_sources(sources))
    raise ApiError("源不存在", status_code=404)


@router.delete("/api/v1/plugin-sources/{source_id}")
async def sources_delete(source_id: str) -> Any:
    sources = [s for s in mg.list_sources() if s["id"] != source_id]
    return ok(mg.save_sources(sources))


@router.get("/api/v1/plugins/market")
async def market(source_id: str | None = None) -> Any:
    return ok(mg.fetch_market(source_id))
