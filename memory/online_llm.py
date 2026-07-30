import httpx
from typing import Optional
from config import FLEXIWEB_BASE_URL


class OnlineLLM:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or FLEXIWEB_BASE_URL).rstrip("/")

    async def ask(self, site: str, prompt: str, timeout: float = 180.0) -> dict:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.post(
                f"{self.base_url}/api/ask_sync",
                json={"site": site, "prompt": prompt},
            )
            resp.raise_for_status()
            return resp.json()
