import httpx
from typing import Optional
from nonebot import logger
from core.llm.base import LLMBackend


class LMStudioBackend(LLMBackend):
    backend_name = "lm_studio"

    def __init__(self, base_url: str, model: Optional[str] = None, max_tokens: int = 2000):
        self.api_url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self.model = model or ""
        self.max_tokens = max_tokens

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": self.max_tokens,
        }
        if self.model:
            payload["model"] = self.model
        # 推理模型（如 gemma-4-e4b）会把 token 全耗在思维链上导致 content 为空，禁用推理
        payload["reasoning_effort"] = "none"

        logger.info(f"[LM Studio] 发送请求（prompt {len(prompt)} 字符）")
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                    resp = await client.post(self.api_url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    reply = data["choices"][0]["message"]["content"]
                if reply:
                    logger.info(f"[LM Studio] 收到回复（{len(reply)} 字符）")
                    return reply
                last_error = RuntimeError("LM Studio 返回空回复")
                logger.warning(f"[LM Studio] 第 {attempt + 1} 次尝试返回空回复，重试...")
            except httpx.HTTPStatusError as e:
                body = e.response.text[:800]
                logger.error(f"[LM Studio] HTTP {e.response.status_code}\n{body}")
                last_error = e
                break
            except Exception as e:
                last_error = e
                logger.warning(f"[LM Studio] 第 {attempt + 1} 次尝试异常: {e}")
        raise last_error or RuntimeError("LM Studio 请求失败")
