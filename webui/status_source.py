# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""状态聚合的可注入来源（方案 §7.1）。

**依赖方向**：webui 是叶子包，绝不 import ``plugins.bot_main``——真包的
``__init__`` 会拉起 ai_gateway，而那要求 NoneBot 已初始化（独立模式必炸，
实测）。宿主（bot.py）在挂载时把 v1 的 ``collect_status`` 注入进来；
没有宿主注入时（``scripts/dev_webui.py`` 独立跑），回退到最小 payload。

取数失败回退最小 payload 而不是 500：状态页宁可少几块，不能整个挂掉。
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version

_FALLBACK_VERSION = "4.0.0"

_STARTED_AT = time.time()

StatusSource = Callable[[], dict]

_source: StatusSource | None = None


def set_status_source(source: StatusSource) -> None:
    """宿主注入 v1 聚合函数（bot.py 挂载时调用；测试可注入桩）。"""
    global _source
    _source = source


def _project_version() -> str:
    try:
        return version("stella_project")
    except PackageNotFoundError:
        return _FALLBACK_VERSION


def _minimal_payload() -> dict:
    """独立模式的回退聚合：只有进程事实，没有 Bot 域数据。"""
    return {
        "version": _project_version(),
        "pid": os.getpid(),
        "uptime_seconds": time.time() - _STARTED_AT,
        "allowed_group_count": 0,
        "link": None,
        "scheduler": {},
        "usage": None,
        "capabilities": None,
        "skills": None,
        "runtime": None,
        "standalone": True,
    }


def collect_status() -> dict:
    """状态聚合唯一入口（webui 的 /api/v1/status 用）。"""
    if _source is not None:
        try:
            return _source()
        except Exception:
            # 宿主聚合失败回退最小 payload：绝不让状态接口 500
            pass
    return _minimal_payload()
