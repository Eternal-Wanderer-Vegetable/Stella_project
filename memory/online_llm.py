# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""在线 LLM 轻量客户端（FlexiWeb /api/ask_sync 的封装）。

只做一件事：把 site 站点参数与 prompt 一起 POST 到 FlexiWeb 的
ask_sync 接口并返回 JSON，用作主链路之外的在线后端调用入口。
"""

import httpx
from typing import Optional
from config import FLEXIWEB_BASE_URL


class OnlineLLM:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or FLEXIWEB_BASE_URL).rstrip("/")

    async def ask(self, site: str, prompt: str, timeout: float = 180.0) -> dict:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), trust_env=False) as client:
            resp = await client.post(
                f"{self.base_url}/api/ask_sync",
                json={"site": site, "prompt": prompt},
            )
            resp.raise_for_status()
            return resp.json()
