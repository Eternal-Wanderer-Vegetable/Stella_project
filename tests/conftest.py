# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""pytest 全局夹具。

默认把 MEMORY_V2_ENABLED 关掉（回到旧记忆系统路径），保证既有 v1 测试
（test_full_workflow / test_short_term_attribution 等）行为稳定；专门测试
记忆系统 v2 的用例（test_policy / test_retrieval_v2 等）在各自用例里显式开启。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _force_v1_memory_path(monkeypatch):
    """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
    import core.pipeline
    import memory.pre_processors
    import memory.retrieval_v2

    monkeypatch.setattr(core.pipeline, "MEMORY_V2_ENABLED", False)
    monkeypatch.setattr(memory.pre_processors, "MEMORY_V2_ENABLED", False)
    monkeypatch.setattr(memory.retrieval_v2, "MEMORY_V2_ENABLED", False)


@pytest.fixture(autouse=True)
def _isolate_space_config(tmp_path, monkeypatch):
    """把共享空间的自动命名账本与 TOML 目录隔离到每个用例独立的临时目录。

    否则测试里 ChatContext.__post_init__ / consolidate_group 触发 resolve_space
    自动分配时，会往仓库真实 memory/ 下写 .space_assignments.json。每用例独立 +
    reload() 清空缓存，保证命名确定性且互不串扰。
    """
    import config.spaces as spaces

    monkeypatch.setattr(spaces, "_AUTO_FILE", tmp_path / ".space_assignments.json")
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")
    spaces.reload()


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch):
    """测试**永远**不许碰真实的渲染后端。

    2026-08-26 的 CI 卡死就出在这里：``playwright`` 在 requirements.txt 里，所以 CI
    装了它，但浏览器内核没装。于是 test_base 的降级用例会真的去起 playwright 驱动
    （spawn 一个 node 进程）→ 启动浏览器失败 → 判定「内核缺失」→ 后台 spawn
    ``playwright install`` 去拉 270MB。事件循环结束时 task 被取消，但**已经 spawn
    出去的下载进程不会被带走**，它继续占着继承来的管道，xdist worker 于是永远退不掉：
    既不报错也不通过。3.10 侥幸通过只是因为那个 task 常在跑第一步之前就被取消了
    ——纯粹的时序运气。

    两道锁：
    1. ``RENDER_AUTO_INSTALL=False``——任何情况下测试都不许触发下载；
    2. 断开 import seam，让 ``_get_browser`` 确定性地走「没装 playwright」分支，
       于是连驱动进程都不会起。

    需要测编排的用例自己打桩 ``_get_browser``（见 tests/astrbot_compat/test_render.py
    的 fake_browser），需要测 ``_get_browser`` 本身的用例直接注入 ``_playwright``
    ——两者都不经过这个 seam，所以不受影响。
    """
    from astrbot_compat import render
    from config import settings

    monkeypatch.setattr(settings, "RENDER_AUTO_INSTALL", False, raising=False)
    monkeypatch.setattr(render, "_load_async_playwright", lambda: None)
