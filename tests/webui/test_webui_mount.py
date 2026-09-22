# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""挂载顺序与 SPA 托管测试（方案 §14 挂载回归）。

四类路径共存是 webui 挂载的安全边界：OneBot WS 不被吞、/stella/status
行为不变、/api/v1/* 进子应用、/ 落 SPA。Starlette 按注册顺序匹配——
「Mount / 必须排在既有路由之后」是结构性约束，这里连顺序带行为一起钉死。
"""

from __future__ import annotations

import asyncio
import re
import sys
import types

from fastapi import FastAPI, WebSocket
from starlette.routing import Mount

import config.settings as settings
from webui.mount import mount_webui


def _main_app() -> FastAPI:
    """模拟宿主 app：OneBot WS + 状态路由先注册（与 bot.py 顺序一致）。"""
    app = FastAPI()

    @app.get("/stella/status")
    async def fake_status():
        return {"fake": True}

    @app.websocket("/onebot/v11/ws")
    async def fake_ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.close()

    return app


def _mount_index(app: FastAPI) -> int:
    routes = app.router.routes
    # Starlette 对根挂载做 rstrip("/")，path 落库为空串（见 mount_webui 注释）
    for i, route in enumerate(routes):
        if isinstance(route, Mount) and route.path in ("/", ""):
            return i
    raise AssertionError("WebUI Mount 未注册")


def test_mount_adds_root_catchup_and_is_idempotent(isolated_home):
    app = _main_app()
    mount_webui(app)
    mount_webui(app)  # 幂等：重复挂载不叠加
    mounts = [
        r for r in app.router.routes if isinstance(r, Mount) and r.path in ("/", "")
    ]
    assert len(mounts) == 1
    status_idx = next(
        i for i, r in enumerate(app.router.routes) if getattr(r, "path", None) == "/stella/status"
    )
    # 顺序即安全边界：catch-all 必须在既有路由之后
    assert _mount_index(app) > status_idx


def test_mount_hook_log_has_no_loguru_markup(isolated_home, monkeypatch):
    """就绪日志不得含 loguru 色彩标记形状的尖括号（<PORT> 实测炸掉控制台 handler）。"""
    captured = {}
    fake_logger = types.SimpleNamespace(
        success=lambda m: captured.setdefault("msg", m),
        error=lambda m: captured.setdefault("err", m),
    )
    fake_nonebot = types.ModuleType("nonebot")
    fake_nonebot.get_app = lambda: FastAPI()
    fake_nonebot.get_driver = lambda: types.SimpleNamespace(
        config=types.SimpleNamespace(port=8080)
    )
    fake_nonebot.logger = fake_logger
    monkeypatch.setitem(sys.modules, "nonebot", fake_nonebot)

    import asyncio as _asyncio

    from webui import mount as webui_mount

    _asyncio.run(webui_mount._mount_hook())

    msg = captured.get("msg", "")
    assert "8080" in msg  # 端口取真实值，而不是 <PORT> 字面量
    assert not re.search(r"<[A-Z][A-Z_]*>", msg)  # 无色彩标记形状的尖括号


def test_four_path_classes_coexist(isolated_home, monkeypatch):
    monkeypatch.setattr(settings, "WEBUI_SERVE_DIST", False)
    app = _main_app()
    mount_webui(app)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    # 1) v1 状态路由行为不变（主 app 路由优先于 catch-all）
    resp = client.get("/stella/status")
    assert resp.status_code == 200
    assert resp.json() == {"fake": True}
    # 2) API 进子应用
    resp = client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["data"]["setup_required"] is True
    # 3) SERVE_DIST=false 时 / 无静态路由 → 子应用 404（挂载本身已生效）
    assert client.get("/").status_code == 404
    # 4) OneBot WS 路由仍在（连接级验证留给真实启动；这里验证路由可接受连接）
    with client.websocket_connect("/onebot/v11/ws") as ws:
        assert ws is not None


def test_spa_hosting(isolated_home, monkeypatch, make_dist):
    monkeypatch.setattr(settings, "WEBUI_SERVE_DIST", True)
    make_dist()
    app = _main_app()
    mount_webui(app)
    from fastapi.testclient import TestClient

    client = TestClient(app)
    # 根路径 → index
    resp = client.get("/")
    assert resp.status_code == 200
    assert "stella-m0-dist" in resp.text
    assert resp.headers["cache-control"] == "no-store"
    # 资产文件按文件回
    resp = client.get("/assets/app.js")
    assert resp.status_code == 200
    assert "/*app*/" in resp.text
    # 深链 → SPA 回落 index
    resp = client.get("/some/deep/link")
    assert resp.status_code == 200
    assert "stella-m0-dist" in resp.text
    # /api 前缀永不被静态托管吞掉
    resp = client.get("/api/unknown-endpoint")
    assert resp.status_code == 404
    assert resp.json()["status"] == "error"
    # dist 缺失 → 引导页而不是 404
    import shutil

    shutil.rmtree(isolated_home / "webui" / "dist")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "尚未构建" in resp.text


def test_static_path_traversal_blocked(isolated_home, monkeypatch, make_dist):
    monkeypatch.setattr(settings, "WEBUI_SERVE_DIST", True)
    make_dist()
    from webui.static import _static_file

    secret = isolated_home / "secret.txt"
    secret.write_text("top-secret", encoding="utf-8")
    # ``..`` 越界：resolve + is_relative_to 守卫必须拦下（404），绝不回文件内容
    result = asyncio.run(_static_file("../secret.txt"))
    assert result.status_code == 404
    deep = asyncio.run(_static_file("a/b/../../../../secret.txt"))
    assert deep.status_code == 404
    assert secret.read_text(encoding="utf-8") == "top-secret"  # 文件未被触碰
