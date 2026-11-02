# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""评测用 OpenAI 兼容客户端：温度 0、零重试、usage 记账（stdlib urllib）。

与 ``core/evaluation/adapters.RealEndpointModel`` 同风格；差异：显式 model 参数、
捕获响应 usage（成本指标需要）、chat/system 双槽位。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class EvalLLMError(RuntimeError):
    pass


class EvalLLM:
    """同步串行客户端（评测不需要并发；LM Studio 端为单队列）。"""

    def __init__(
        self,
        base_url: str,
        model: str | None = None,
        api_key: str = "",
        timeout: float = 300.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._model = model
        self.ledger: dict[str, Any] = {
            "calls": 0,
            "errors": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "latency_seconds": [],
        }

    @property
    def model(self) -> str:
        if self._model:
            return self._model
        self._model = self._resolve_model()
        return self._model

    def _resolve_model(self) -> str:
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/models", timeout=min(self.timeout, 15.0)
            ) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
            if not models:
                raise EvalLLMError(f"端点未列出任何模型：{self.base_url}")
            return str(models[0])
        except EvalLLMError:
            raise
        except Exception as exc:
            raise EvalLLMError(f"解析 /v1/models 失败：{type(exc).__name__}: {exc}") from exc

    def chat(
        self,
        user: str,
        system: str | None = None,
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """一次补全；返回 {text, prompt_tokens, completion_tokens, latency}。"""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        started = time.monotonic()
        self.ledger["calls"] += 1
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            self.ledger["errors"] += 1
            raise EvalLLMError(
                f"chat 调用失败（{self.base_url} model={self.model}）："
                f"{type(exc).__name__}: {exc}"
            ) from exc
        latency = time.monotonic() - started
        self.ledger["latency_seconds"].append(latency)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = str(message.get("content") or "")
        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        reasoning_tokens = int(details.get("reasoning_tokens") or 0)
        self.ledger["prompt_tokens"] += prompt_tokens
        self.ledger["completion_tokens"] += completion_tokens
        self.ledger["reasoning_tokens"] = self.ledger.get("reasoning_tokens", 0) + reasoning_tokens
        return {
            "text": text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "latency_seconds": latency,
        }

    def cost_summary(self) -> dict[str, Any]:
        latencies = sorted(self.ledger["latency_seconds"])
        count = len(latencies)

        def _pct(q: float) -> float | None:
            if not count:
                return None
            idx = min(count - 1, max(0, round(q * (count - 1))))
            return round(latencies[idx], 3)

        return {
            "base_url": self.base_url,
            "model": self.model,
            "calls": self.ledger["calls"],
            "errors": self.ledger["errors"],
            "prompt_tokens": self.ledger["prompt_tokens"],
            "completion_tokens": self.ledger["completion_tokens"],
            "latency_p50": _pct(0.5),
            "latency_p95": _pct(0.95),
        }


class CountingBackend:
    """包装生产 LLMBackend，统计整合阶段调用次数（不改变行为）。"""

    def __init__(self, inner: Any):
        self._inner = inner
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def generate_detailed(self, prompt: str, *args: Any, **kwargs: Any):
        self.calls += 1
        return await self._inner.generate_detailed(prompt, *args, **kwargs)

    async def generate(self, prompt: str, *args: Any, **kwargs: Any):
        self.calls += 1
        return await self._inner.generate(prompt, *args, **kwargs)
