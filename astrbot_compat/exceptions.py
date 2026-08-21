# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""兼容层异常定义。"""

from __future__ import annotations


class StellaCompatError(Exception):
    """兼容层基础异常。"""


class StellaCompatNotSupported(StellaCompatError):
    """请求的功能在 Stella 兼容层中尚未实现。"""

    def __init__(self, name: str = "", msg: str | None = None) -> None:
        if msg is None:
            msg = f"{name} 尚未在 Stella 兼容层中实现" if name else "该功能尚未在 Stella 兼容层中实现"
        super().__init__(msg)
        self.name = name
