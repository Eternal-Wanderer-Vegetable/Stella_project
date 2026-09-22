# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""前端静态托管（SPA，方案 §5 webui/static.py）。

约定：``/api`` 前缀永远到不了这里（API 路由先匹配；catch-all 里再拦一道），
其余 GET 一律落 SPA——存在的文件按文件回（带 no-cache），不存在的路径回
index.html（hash 路由天然支持深链）。dist 未构建/未随包分发时返回一张
「前端尚未构建」的引导页，而不是 404——用户第一眼要能知道差了哪一步。

路径安全：先 resolve 再要求 ``is_relative_to(dist)``，``..`` 与绝对路径
注入到不了磁盘。缓存策略对齐 AstrBot：入口文档 no-store，资产 no-cache
（文件名带 hash 的构建产物改版本即失效，不赌浏览器缓存）。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import config.settings as settings

router = APIRouter(include_in_schema=False)

# Windows 的 mimetypes 把 .svg 映射成非标准类型（AstrBot 同款修正）
mimetypes.add_type("image/svg+xml", ".svg", strict=True)
mimetypes.add_type("application/javascript", ".js", strict=True)
mimetypes.add_type("text/css", ".css", strict=True)


def dist_dir() -> Path | None:
    """dist 目录；未启用托管或目录不存在（未构建）返回 None。"""
    if not settings.WEBUI_SERVE_DIST:
        return None
    candidate = Path(settings.PROJECT_ROOT) / "webui" / "dist"
    if (candidate / "index.html").is_file():
        return candidate
    return None


def _not_built_page() -> HTMLResponse:
    html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Stella WebUI</title>
<style>body{font-family:system-ui,sans-serif;background:#171D24;color:#E8ECF1;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
main{text-align:center;max-width:32rem;padding:2rem}
code{background:#1E2732;padding:.2rem .5rem;border-radius:.3rem}</style></head>
<body><main><h1>Stella WebUI</h1>
<p>管理面前端尚未构建（缺少 webui/dist）。</p>
<p>前端开发：在仓库根执行 <code>cd dashboard &amp;&amp; pnpm install &amp;&amp; pnpm build</code>，
或开发期用 <code>pnpm dev</code>（Vite 反代本端口 API）。</p>
<p>API 本身正常：<code>/api/v1/docs</code></p></main></body></html>"""
    return HTMLResponse(html, status_code=200, headers={"Cache-Control": "no-store"})


async def _index() -> HTMLResponse:
    dist = dist_dir()
    if dist is None:
        return _not_built_page()
    return FileResponse(
        dist / "index.html", headers={"Cache-Control": "no-store"}
    )


async def _static_file(static_path: str) -> Any:
    if static_path.startswith("api") or static_path.split("/", 1)[0] == "api":
        return JSONResponse({"status": "error", "message": "Not Found"}, status_code=404)
    dist = dist_dir()
    if dist is None:
        return _not_built_page()
    candidate = (dist / static_path).resolve()
    try:
        candidate.relative_to(dist.resolve())
    except ValueError:
        return JSONResponse(
            {"status": "error", "message": "Not Found"}, status_code=404
        )
    if candidate.is_file():
        return FileResponse(
            candidate,
            media_type=mimetypes.guess_type(candidate.name)[0],
            headers={"Cache-Control": "no-cache"},
        )
    # SPA 深链（hash 路由其实不需要，但保留 history 兼容）
    return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})


def register_static(app) -> None:
    """把 SPA 托管路由挂到 webui 子应用上。必须**最后**调用——catch-all
    会吃掉之后注册的一切 GET 路由。"""
    app.add_api_route("/", _index, methods=["GET"], include_in_schema=False)
    app.add_api_route(
        "/{static_path:path}", _static_file, methods=["GET"], include_in_schema=False
    )
