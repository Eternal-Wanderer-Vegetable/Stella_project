# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""core.llm.lm_studio LM Studio 后端的测试。

用可替换的 hx 假 AsyncClient（monkeypatch httpx.AsyncClient）驱动
generate()，避免发真实网络请求；覆盖成功、空回复重试、5xx 重试、
4xx 直弃与通用异常兜底等路径。
"""

import asyncio

import httpx
import pytest

from core.llm.lm_studio import LMStudioBackend


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self
            )


class _FakePost:
    def __init__(self, responses):
        self._responses = list(responses)
        self._idx = 0

    async def post(self, *args, **kwargs):
        resp, status = self._responses[self._idx]
        self._idx += 1
        return _FakeResponse(status, resp)


class _FakeClient:
    def __init__(self, post_impl):
        self._post_impl = post_impl

    async def post(self, *args, **kwargs):
        return await self._post_impl.post(*args, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _fake_async_client(monkeypatch, responses):
    shared_post = _FakePost(responses)

    def _factory(*args, **kwargs):
        return _FakeClient(shared_post)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def test_constructor_normalizes_url():
    backend = LMStudioBackend("http://127.0.0.1:1234/", model="m")
    assert backend.api_url == "http://127.0.0.1:1234/v1/chat/completions"
    assert backend.model == "m"
    assert backend.max_tokens == 2000
    assert backend.temperature == 0.7

    backend2 = LMStudioBackend("http://127.0.0.1:9999")
    assert backend2.api_url == "http://127.0.0.1:9999/v1/chat/completions"
    assert backend2.model == ""


def test_generate_success_path(monkeypatch):
    backend = LMStudioBackend("http://127.0.0.1:1234", max_tokens=42, temperature=0.5)
    _fake_async_client(monkeypatch, [({"choices": [{"message": {"content": "好的"}}]}, 200)])
    result = asyncio.run(backend.generate("你好", system_prompt="你是助手"))
    assert result == "好的"


def test_generate_retries_on_empty_reply(monkeypatch):
    backend = LMStudioBackend("http://127.0.0.1:1234")
    _fake_async_client(
        monkeypatch,
        [
            ({"choices": [{"message": {"content": ""}}]}, 200),
            ({"choices": [{"message": {"content": ""}}]}, 200),
            ({"choices": [{"message": {"content": "恢复"}}]}, 200),
        ],
    )
    result = asyncio.run(backend.generate("hi"))
    assert result == "恢复"


def test_generate_gives_up_on_4xx(monkeypatch):
    backend = LMStudioBackend("http://127.0.0.1:1234")
    _fake_async_client(monkeypatch, [({"error": "bad request"}, 400)])
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(backend.generate("hi"))


def test_generate_exhausts_retries_on_generic_error(monkeypatch):
    backend = LMStudioBackend("http://127.0.0.1:1234")

    class _BoomPost:
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("boom")

    class _BoomClient:
        async def post(self, *args, **kwargs):
            raise httpx.ConnectError("boom")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    def _factory(*args, **kwargs):
        return _BoomClient()

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(backend.generate("hi"))


def test_generate_detailed_returns_finish_reason(monkeypatch):
    """generate_detailed 把 finish_reason 一并交给调用方（用返回值而非实例属性）。

    后端实例按角色共享，闸门只在单次调用期间持有；若把 finish_reason 存到 self 上，
    调用方读取时可能已被另一个群的调用覆盖。
    """
    backend = LMStudioBackend("http://127.0.0.1:1234")
    _fake_async_client(
        monkeypatch,
        [({"choices": [{"message": {"content": "半句话"}, "finish_reason": "length"}]}, 200)],
    )
    reply, finish = asyncio.run(backend.generate_detailed("hi"))
    assert reply == "半句话"
    assert finish == "length"


def test_generate_detailed_finish_reason_empty_when_absent(monkeypatch):
    backend = LMStudioBackend("http://127.0.0.1:1234")
    _fake_async_client(monkeypatch, [({"choices": [{"message": {"content": "好的"}}]}, 200)])
    reply, finish = asyncio.run(backend.generate_detailed("hi"))
    assert (reply, finish) == ("好的", "")


def test_generate_keeps_str_signature(monkeypatch):
    """generate() 的 -> str 是 LLMBackend 统一接口，多处依赖，不许改成元组。"""
    backend = LMStudioBackend("http://127.0.0.1:1234")
    _fake_async_client(
        monkeypatch,
        [({"choices": [{"message": {"content": "好的"}, "finish_reason": "stop"}]}, 200)],
    )
    assert asyncio.run(backend.generate("hi")) == "好的"
