# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""webui 测试夹具。

要点：
- 目录**不带 __init__.py**——tests/<pkg>/ 带 __init__.py 会在 pytest prepend
  模式下遮蔽顶层同名包（tests/knowledge 的历史教训）；
- webui 是叶子包，不 import ``plugins.bot_main``（依赖方向见
  webui/status_source.py），因此这里**不需要** tests/test_status_api.py 那套
  伪包注册与 sys.path 处理；
- 所有 webui 模块在**调用时**读 config.settings 属性，因此夹具只需
  monkeypatch settings 的 STELLA_HOME / PROJECT_ROOT / LOG_DIR 即可把
  凭据、dist 与审计日志整体隔离进临时目录。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config.settings as settings
from webui.app import create_webui_app


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 STELLA_HOME / PROJECT_ROOT / LOG_DIR 全部指到临时目录：
    auth.json、webui/dist 探测、审计日志互不串扰，也不碰开发机真实数据。"""
    monkeypatch.setattr(settings, "STELLA_HOME", tmp_path)
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "LOG_DIR", tmp_path / "logs")
    return tmp_path


@pytest.fixture
def client(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """关闭静态托管的纯 API 客户端；每个用例独立 app（限流桶随 app 重建）。"""
    monkeypatch.setattr(settings, "WEBUI_SERVE_DIST", False)
    return TestClient(create_webui_app())


@pytest.fixture
def make_dist(isolated_home: Path):
    """造一个最小 dist：index.html + 一个资产文件。返回 dist 目录路径。"""

    def _make(marker: str = "stella-m0-dist") -> Path:
        dist = isolated_home / "webui" / "dist"
        (dist / "assets").mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text(f"<html>{marker}</html>", encoding="utf-8")
        (dist / "assets" / "app.js").write_text("/*app*/", encoding="utf-8")
        return dist

    return _make
