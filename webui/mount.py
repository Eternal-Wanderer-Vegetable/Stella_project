# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""把 WebUI 挂到 NoneBot 的 ASGI app 上（方案 §4 D2）。

**挂载顺序是本模块存在的原因**：Starlette 按 routes 列表顺序匹配，把 SPA
catch-all（Mount "/"）放到最后注册，OneBot 反向 WS 与 /stella/status 就
天然优先——顺序即安全边界，不靠路径互斥的巧合。所以挂载不在 import 期做，
而是注册为**最后一个** startup 钩子（bot.py 在所有其他 on_startup 之后才
调用 setup_webui），lifespan 真正跑起来时所有路由都已就位。

四类路径的共存断言在 tests/webui/test_webui_mount.py 钉死：
OneBot WS（不被吞）→ /stella/status（行为不变）→ /api/v1/*（本包）→ /（SPA）。
"""

from __future__ import annotations

import config.settings as settings


def mount_webui(app) -> None:
    """把 WebUI 子应用挂到给定 ASGI app 的 ``/``。幂等；不依赖 NoneBot
    （app 只需是 Starlette 兼容对象），便于单测与未来复用。

    注意 Starlette 对挂载路径做 ``rstrip("/")``：挂 ``"/"`` 得到的 Mount
    ``path`` 是 **空串** 而不是 ``"/"``——判重必须两种都认，否则幂等保护
    失效、重复挂载层层套娃（实测踩过）。
    """
    from starlette.routing import Mount

    for route in getattr(app, "routes", ()):
        if isinstance(route, Mount) and route.path in ("/", ""):
            return
    from webui.app import create_webui_app

    app.mount("/", create_webui_app(), name="webui")


async def _mount_hook() -> None:
    try:
        from nonebot import get_app, get_driver, logger

        mount_webui(get_app())
        # 日志里的端口取真实值：字面量 "<PORT>" 会被 loguru 色彩解析器当成
        # 颜色标签（<> 是它的标记语法），控制台 handler 直接抛 ValueError
        # （2026-09-23 热测踩过）。
        port = getattr(get_driver().config, "port", None) or 8080
        logger.success(f"✅ WebUI 已就绪: http://127.0.0.1:{port}/ （API: /api/v1）")
    except Exception:  # WebUI 是增量能力，挂载失败不拖垮 Bot（同 status_api 取向）
        import traceback

        try:
            from nonebot import logger

            logger.error(f"WebUI 挂载失败（Bot 不受影响）: {traceback.format_exc()}")
        except Exception:
            pass


def setup_webui(*, status_source=None) -> None:
    """注册挂载钩子。必须在**所有**其他 on_startup 注册之后调用；
    WEBUI_ENABLED=false 时整体不生效（连钩子都不注册）。

    ``status_source``：宿主注入的状态聚合函数（bot.py 传
    ``status_api.collect_status``，方案 §7.1）。不注入则独立模式回退
    最小 payload（见 webui.status_source）。
    """
    if not settings.WEBUI_ENABLED:
        return
    if status_source is not None:
        from webui import status_source as status_source_module

        status_source_module.set_status_source(status_source)
    from nonebot import get_driver

    get_driver().on_startup(_mount_hook)
