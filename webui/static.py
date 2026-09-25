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

import logging
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import config.settings as settings

router = APIRouter(include_in_schema=False)

logger = logging.getLogger(__name__)

# Windows 的 mimetypes 把 .svg 映射成非标准类型（AstrBot 同款修正）
mimetypes.add_type("image/svg+xml", ".svg", strict=True)
mimetypes.add_type("application/javascript", ".js", strict=True)
mimetypes.add_type("text/css", ".css", strict=True)

# dist 健康报告每进程至多告警一次：静态托管每个页面加载都会走到这里，
# 不设一次性闸门的话，一条告警会在日志里刷屏。
_dist_health_reported = False


def _read_dist_version(dist: Path) -> str | None:
    """读 dist 自带的版本标记（CI 构建时写入 assets/version）。本地手搓的
    dist 可能没有——返回 None 表示「版本未知」，不参与版本比对告警。"""
    try:
        return (dist / "assets" / "version").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _dist_missing_entries(dist: Path) -> list[str]:
    """index.html 引用的本地 js/css 里缺失的文件清单（空 = 引用完整）。

    灵感来自 AstrBot 的 _is_dist_complete：一个引用了不存在 chunk 的 dist
    就是「客户端白屏」的直接原因（2026-09-25 白屏实测），在服务端就能发现。
    """
    try:
        html = (dist / "index.html").read_text(encoding="utf-8")
    except OSError:
        return []
    missing: list[str] = []
    for match in re.finditer(
        r"\b(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", html, flags=re.IGNORECASE
    ):
        reference = match.group(1).strip()
        if not reference or reference.startswith(("#", "//", "data:")):
            continue
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc:
            continue
        relative = unquote(parsed.path).replace("\\", "/").lstrip("/")
        if not relative.lower().endswith((".js", ".css")):
            continue
        if not (dist / relative).is_file():
            missing.append(relative)
    return missing


def _report_dist_health_once(dist: Path) -> None:
    """对 dist 做一次「版本标记 + 引用完整性」体检并告警（每进程一次）。

    只告警不拦截：版本不匹配/不完整的 dist 依然照常服务——页面能用多少算
    多少，但问题在日志里立即可见，而不是等用户白屏后投诉。
    """
    global _dist_health_reported
    if _dist_health_reported:
        return
    _dist_health_reported = True

    missing = _dist_missing_entries(dist)
    if missing:
        logger.warning(
            "⚠️ WebUI 前端 dist 不完整：index.html 引用的 %s 缺失——"
            "客户端可能白屏。请完整重建前端并覆盖 webui/dist。",
            ", ".join(missing[:5]),
        )

    dist_version = _read_dist_version(dist)
    if not dist_version:
        return  # 本地手搓的 dist 没有版本标记：未知版本不告警
    try:
        from config.state import program_version

        core_version = program_version(Path(settings.PROJECT_ROOT))
    except Exception:
        return
    if core_version and dist_version.lstrip("vV") != core_version.lstrip("vV"):
        logger.warning(
            "⚠️ WebUI 前端版本 (%s) 与程序版本 (%s) 不一致——"
            "若页面行为异常，请核对发布包里的 webui/dist 是否与程序同期构建。",
            dist_version,
            core_version,
        )


def dist_dir() -> Path | None:
    """dist 目录；未启用托管或目录不存在（未构建）返回 None。"""
    if not settings.WEBUI_SERVE_DIST:
        return None
    candidate = Path(settings.PROJECT_ROOT) / "webui" / "dist"
    if (candidate / "index.html").is_file():
        _report_dist_health_once(candidate)
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
    if static_path.startswith("assets/"):
        # 带 hash 的构建产物缺失 = 客户端拿着过期入口页（或部署残缺）。
        # 必须响亮地 404：回落 index.html 会把 HTML 当 JS 发回去（200 +
        # text/html），浏览器只报一行 MIME 错然后白屏，原因被彻底藏住
        # （2026-09-24 实测：webui/dist 重建换 hash 后，旧入口页白屏）。
        return JSONResponse(
            {"status": "error", "message": "Not Found"}, status_code=404
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
