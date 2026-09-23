# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""OneBot 连接配置（方案 §6.4 平台页的编辑面）。

两种连接形态：reverse（Bot 监听 HOST:PORT，NapCat 反向接进来，默认）与
forward（Bot 主动连 ONEBOT_WS_URLS 列表）。写侧落 .env，重启生效；
token 掩码契约与 providers 相同。
"""

from __future__ import annotations

import json

from webui.responses import ApiError
from webui.services import envfile


def onebot() -> dict:
    # HOST/PORT/ONEBOT_* 不在 settings._env 体系（NoneBot 直读环境变量），
    # 所以这里读 .env 原文而不是 settings 属性——那几个属性根本不存在。
    from webui.services.envfile import read_values

    raw = read_values()
    ws_raw = raw.get("ONEBOT_WS_URLS", "")
    try:
        ws_urls = json.loads(ws_raw) if ws_raw else []
    except ValueError:
        ws_urls = []
    return {
        "host": raw.get("HOST", "0.0.0.0"),
        "port": raw.get("PORT", "8080"),
        "ws_urls": ws_urls,
        "has_token": bool(raw.get("ONEBOT_ACCESS_TOKEN", "")),
    }


def update(payload: dict) -> dict:
    updates: dict[str, str] = {}
    if "ws_urls" in payload:
        urls = [str(u).strip() for u in payload["ws_urls"] if str(u).strip()]
        for u in urls:
            if not u.startswith(("ws://", "wss://")):
                raise ApiError(f"正向 WS 地址必须以 ws:// 或 wss:// 开头: {u}")
        updates["ONEBOT_WS_URLS"] = json.dumps(urls, ensure_ascii=False)
    if payload.get("access_token"):
        updates["ONEBOT_ACCESS_TOKEN"] = str(payload["access_token"])
    if "host" in payload:
        updates["HOST"] = str(payload["host"]).strip()
    if "port" in payload:
        try:
            port = int(payload["port"])
        except (TypeError, ValueError):
            raise ApiError("PORT 需要整数") from None
        if not (1 <= port <= 65535):
            raise ApiError("PORT 超出范围")
        updates["PORT"] = str(port)
    report = envfile.write_values(updates)
    return {**report, "restart_required": True}
