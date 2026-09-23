# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""WebUI 只读 SQLite 访问。

统一 ``mode=ro`` URI 连接：WebUI 是数据的**读者**，写侧永远归业务模块
（usage_store / consolidator / memory.schema）。库不存在返回 None——面板
少一块，不该 500。查询超时兜底 ``busy timeout``，避免与业务写入争锁时
把请求挂死。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_ro(path: Path) -> sqlite3.Connection | None:
    """只读连接；文件不存在返回 None。调用方负责 finally 关闭。"""
    if not Path(path).exists():
        return None
    try:
        return sqlite3.connect(
            f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=2.0
        )
    except sqlite3.Error:
        return None
