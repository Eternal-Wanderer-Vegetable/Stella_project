# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""兼容层异常定义。"""

from __future__ import annotations


class StellaCompatError(Exception):
    """兼容层基础异常。"""


# 名字不带 Error 后缀是刻意的：插件侧按这个名字捕获，改名会破坏兼容。
class StellaCompatNotSupported(StellaCompatError):  # noqa: N818
    """请求的功能在 Stella 兼容层中尚未实现。"""

    def __init__(self, name: str = "", msg: str | None = None) -> None:
        if msg is None:
            msg = (
                f"{name} 尚未在 Stella 兼容层中实现"
                if name
                else "该功能尚未在 Stella 兼容层中实现"
            )
        super().__init__(msg)
        self.name = name


class StellaCompatUnsupportedAttribute(StellaCompatNotSupported, AttributeError):  # noqa: N818
    """属性形态的「未实现」。

    同时是 AttributeError，这样 `hasattr(obj, "x")` 会返回 False——插件靠 hasattr
    做特性探测时能优雅降级，而直接访问仍抛可识别的 StellaCompatNotSupported。
    """
