# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""scheduling 子系统的测试夹具。

调度包位于 NoneBot 插件包 ``stella_project.plugins.bot_main`` 之下，import 它会
触发插件包入口的 ``get_plugin_config(Config)``——那要求 NoneBot 已初始化。本
conftest 在收集本目录用例**之前**完成 ``nonebot.init()``，让各测试模块可以放心
在模块顶层 import 调度子包（与 test_proactive_at_flow 的 module fixture 同一
招数，只是提前到 conftest，免去每个测试模块都写一遍惰性导入）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import nonebot
import pytest


def _ensure_nonebot_ready() -> None:
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()


_ensure_nonebot_ready()


class FakeClock:
    """调度子系统统一的假时钟。

    全子系统的「现在」都从 :func:`.models.utc_now` 读，patch 它即可全链路可控。
    """

    def __init__(self, start: datetime, module) -> None:
        self._module = module
        self.now = start

    def advance(self, seconds: float) -> datetime:
        self.now = self.now + timedelta(seconds=seconds)
        return self.set(self.now)

    def set(self, value: datetime) -> datetime:
        self.now = value
        self._module.utc_now = lambda: self.now  # type: ignore[method-assign]
        return self.now


@pytest.fixture()
def fake_clock(monkeypatch):
    from stella_project.plugins.bot_main.scheduling import models

    clock = FakeClock(datetime(2026, 9, 22, 8, 0, 0, tzinfo=timezone.utc), models)
    monkeypatch.setattr(models, "utc_now", lambda: clock.now)
    return clock
