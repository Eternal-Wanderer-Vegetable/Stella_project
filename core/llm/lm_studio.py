import httpx
from typing import Optional
from core.llm.base import LLMBackend


class LMStudioBackend(LLMBackend):
    def __init__(self, base_url: str, model: Optional[str] = None):
        self.api_url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self.model = model or ""

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 2000,
        }
        if self.model:
            payload["model"] = self.model

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(self.api_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
