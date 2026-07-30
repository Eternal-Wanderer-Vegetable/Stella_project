from typing import Optional
from nonebot import logger
import httpx
from core.llm.base import LLMBackend


class FlexiWebBackend(LLMBackend):
    def __init__(self, base_url: str, site: str = "deepseek"):
        self.base_url = base_url.rstrip("/")
        self.site = site

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            resp = await client.post(
                f"{self.base_url}/api/ask_sync",
                json={"site": self.site, "prompt": prompt},
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data.get("reply", "")
            if not reply:
                raise ValueError("FlexiWeb 返回空 reply")
            return reply
