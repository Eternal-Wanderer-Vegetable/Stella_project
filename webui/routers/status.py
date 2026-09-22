# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""状态聚合路由：``GET /api/v1/status``（方案 §7.1）。

数据与 v1 的 ``GET /stella/status`` 同源——都走 ``status_api.collect_status()``，
不复制聚合逻辑。区别在访问控制与可见范围：v1 面向本机进程（回环守卫 +
刻意最小化的脱敏 payload），本路由面向已登录的管理员，允许附加 webui 段
（登录身份）。响应同样不含凭据与消息内容（红线见方案 §9.5，测试钉死）。

导入的双路径与 bot.py 同因：源码直跑时 NoneBot 把 ``stella_project/plugins``
挂上了 sys.path（``plugins.bot_main`` 可导入），打包/测试环境则未必——
两条路都试，先通先用。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from webui.auth import AuthContext, require_auth
from webui.responses import ok

try:  # 与 bot.py 一致的双路径导入，理由见模块 docstring
    from plugins.bot_main import status_api
except ImportError as _e:  # pragma: no cover - 打包环境走这条
    import sys as _sys

    print(f"[webui][status] plugins.bot_main 导入失败: {_e!r}", file=_sys.stderr)
    from stella_project.plugins.bot_main import status_api

router = APIRouter(tags=["status"])


def _payload(auth: AuthContext) -> dict:
    data = status_api.collect_status()
    data["webui"] = {"username": auth.username, "via": auth.via}
    return data


@router.get("/api/v1/status")
async def status(auth: Annotated[AuthContext, Depends(require_auth)]) -> Any:
    return ok(_payload(auth))
