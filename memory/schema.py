# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Compatibility alias: canonical implementation is :mod:`mneme.schema`.

导入时自替换为规范模块，保证新旧导入路径得到同一 module 对象
（2026-11-03 计划 §3.1 兼容策略）。本模块含 CLI 入口：以
``python -m memory.{name}`` 运行时转发到 ``python -m mneme.{name}``，
退出码与输出保持一致。不要在这里重复实现任何业务逻辑。
"""

from __future__ import annotations

import sys as _sys

from mneme import schema as _canonical

if __name__ == "__main__":  # CLI trampoline: forward, preserve exit code
    import runpy as _runpy

    _runpy.run_module("mneme.schema", run_name="__main__", alter_sys=True)
else:
    _sys.modules[__name__] = _canonical
