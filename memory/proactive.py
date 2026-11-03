# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Compatibility alias: canonical implementation is :mod:`aoede.controller`.

2026-11-03 计划 §3.1：正式实现只有 ``aoede``/``mneme`` 一份；``memory.*``
是显式别名。本模块在导入时把 ``sys.modules`` 中的自己替换为规范模块，
保证 ``import memory.proactive`` 与 ``import aoede.controller`` 得到**同一个
module 对象**——monkeypatch、单例、模块级缓存都只有一份。不要在这里
重复实现任何业务逻辑。
"""

from __future__ import annotations

import sys as _sys

from aoede import controller as _canonical

_sys.modules[__name__] = _canonical
