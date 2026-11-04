# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Compatibility alias: canonical implementation is :mod:`aoede.participation`.

2026-11-03 计划 §3.1：``memory.participation`` 及其全部子模块在导入时
替换为 ``aoede.participation`` 的同一批 module 对象——`from
memory.participation.buffer import X`` 与 ``from aoede.participation.buffer
import X`` 得到同一个类，monkeypatch 只命中一份实现。不要在这里重复实现
任何业务逻辑。
"""

from __future__ import annotations

import sys as _sys

from aoede import participation as _canonical

_submodules = (
    "buffer",
    "decision",
    "observability",
    "scorer",
    "signals",
    "state",
    "tables",
)

_sys.modules[__name__] = _canonical
for _name in _submodules:
    _sys.modules[f"{__name__}.{_name}"] = _sys.modules[f"aoede.participation.{_name}"]
