# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""停止请求哨兵：deploy 写、Bot 读并自杀、Bot 启动时先清残留。

不引入 nonebot、不引入 asyncio——deploy/process.py 也要 import 本模块，
deploy 层不应该拉起整个 nonebot 栈。

文件是「存在即意义」：内容只供人看与审计，任何解析失败都不能阻塞停止。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _sentinel_path() -> Path:
    # 每次从 settings 读，避免模块顶层冻结（import 时快照）导致测试 monkeypatch 失效
    from config import STELLA_STOP_SENTINEL

    return STELLA_STOP_SENTINEL


def request_stop(reason: str = "") -> None:
    """写停止请求哨兵。幂等：重复调用只是覆盖，不报错。

    先写 ``.tmp`` 再 ``os.replace``，避免 watcher 读到半个文件。
    内容只供人看与审计，不影响停止判断。
    """
    path = _sentinel_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
            "reason": reason,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError as e:
        logger.debug(f"[StopSignal] 写哨兵失败: {e}")


def is_stop_requested() -> bool:
    """存在即意义：只查文件存在性，不解析内容。"""
    return _sentinel_path().exists()


def clear_stop_request() -> None:
    """清除哨兵。删不掉不应阻断启动，只留 debug 日志。"""
    try:
        _sentinel_path().unlink(missing_ok=True)
    except OSError as e:
        logger.debug(f"[StopSignal] 清哨兵失败: {e}")


def read_stop_request() -> dict[str, Any] | None:
    """读并解析哨兵内容；任何异常（含文件损坏）都返回 None。"""
    try:
        return json.loads(_sentinel_path().read_text(encoding="utf-8"))
    except Exception:
        return None
