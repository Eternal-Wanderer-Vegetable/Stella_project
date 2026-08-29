# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""§9.1 契约测试：OpenAI 兼容端点的最小合规请求体与参数差异自适应。

**这组用例是「换一家厂商就跑不通」的防线，必须进 CI。**方案 §4.3 把厂商中立
写成硬约束，落到可测的三条：

1. **默认只发最小合规请求体**（``model`` / ``messages`` / ``temperature`` /
   ``max_tokens``，流式加 ``stream``，工具链路加 ``tools`` / ``tool_choice``）。
   每多一个字段就是「某家会 400」的风险，所以这里用一个**严格端点替身**：
   见到任何额外顶层字段就 400。它跑通，才说明我们没往请求体里塞私货。
2. **差异按错误体关键词自适应 + 记住结果**，绝不用厂商白名单。所以替身都不叫
   厂商名字，只按「行为」命名：只认 ``max_completion_tokens`` 的、不接受
   ``temperature`` 的。
3. **同一请求最多自适应重试一次，且不占用正常重试预算**。前者防「对着配置错误
   死循环」，后者防「一次学习吃掉三分之一容错额度」。

两条代码路径都要过：``LMStudioBackend``（主聊天链路）与 ``chat_completion``
（插件兼容层）。它们各有一份请求循环，改一处漏一处正是这类回归的常见来源。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import core.llm.compat as compat
import core.llm.usage_sink as usage_sink
from core.llm.lm_studio import LMStudioBackend
from core.llm.openai_client import (
    OpenAIClientError,
    chat_completion,
    chat_completion_stream,
)

# 最小合规请求体允许出现的顶层字段。**改这个集合前先想清楚「换一家还认吗」。**
_MINIMAL_FIELDS = frozenset(
    {"model", "messages", "temperature", "max_tokens", "stream", "tools", "tool_choice"}
)


@pytest.fixture(autouse=True)
def _clean_state():
    """兼容状态与用量聚合都是进程内全局的，逐例清空。"""
    compat.reset_state()
    usage_sink.reset_state()
    yield
    compat.reset_state()
    usage_sink.reset_state()


@pytest.fixture
def no_backoff(monkeypatch):
    """去掉重试退避的真实等待——本文件要断言重试**次数**，不想为此等 3 秒。"""

    async def _instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


# ---------------------------------------------------------------- 端点替身


class _Resp:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else json.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=self)


class _StreamResp(_Resp):
    def __init__(self, status: int, body, lines: list[str]):
        super().__init__(status, body)
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _StreamCtx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *_):
        return None


class _MockEndpoint:
    """可编程的 OpenAI 兼容端点替身：``handler(payload, index) -> (status, body)``。

    记录每一次收到的请求体，这样「重试了几次」「第二次发的形状对不对」都能断言。
    """

    def __init__(self, handler, stream_lines: list[str] | None = None):
        self._handler = handler
        self._stream_lines = stream_lines or []
        self.payloads: list[dict] = []

    @property
    def calls(self) -> int:
        return len(self.payloads)

    @property
    def last(self) -> dict:
        return self.payloads[-1]

    def _next(self, payload: dict):
        self.payloads.append(payload)
        return self._handler(payload, len(self.payloads) - 1)

    # --- httpx.AsyncClient 替身接口 ---
    # 参数刻意收成 **kw：httpx 是按关键字传 ``json=`` 的，显式写成形参就会遮住
    # 模块级的 json 模块，读起来像 bug 又不是 bug。
    async def post(self, _url, **kw):
        status, body = self._next(kw.get("json") or {})
        return _Resp(status, body)

    def stream(self, _method, _url, **kw):
        status, body = self._next(kw.get("json") or {})
        return _StreamCtx(_StreamResp(status, body, self._stream_lines))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


def _install(monkeypatch, endpoint: _MockEndpoint) -> _MockEndpoint:
    monkeypatch.setattr(httpx, "AsyncClient", lambda *_a, **_kw: endpoint)
    return endpoint


def _ok(content: str = "好的", finish: str = "stop", usage: dict | None = None) -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": usage if usage is not None else {"prompt_tokens": 10, "completion_tokens": 3},
    }


def _err(message: str) -> dict:
    """各家 error 结构嵌套层级不同，替身刻意包一层——自适应只做关键词匹配。"""
    return {"error": {"message": message, "type": "invalid_request_error"}}


# ---------------------------------------------------------------- 具名行为的替身


def _strict(payload: dict, _i: int):
    """最小合规端点：见到任何额外顶层字段就 400（措辞里不含可自适应的关键词）。"""
    extra = sorted(set(payload) - _MINIMAL_FIELDS)
    if extra:
        return 400, _err(f"Unrecognized request argument supplied: {extra[0]}")
    return 200, _ok()


def _length_field_only(payload: dict, _i: int):
    """只认 ``max_completion_tokens`` 的端点。"""
    if "max_tokens" in payload:
        return 400, _err(
            "Unsupported parameter: 'max_tokens' is not supported with this model. "
            "Use 'max_completion_tokens' instead."
        )
    return 200, _ok()


def _no_temperature(payload: dict, _i: int):
    """不接受 ``temperature`` 的端点（固定采样温度的模型）。"""
    if "temperature" in payload:
        return 400, _err(
            "Unsupported value: 'temperature' does not support 0.7 with this model. "
            "Only the default (1) value is supported."
        )
    return 200, _ok()


def _always_rejects_length(_payload: dict, _i: int):
    """两个字段名都不接受——用来验证自适应重试的**上限**，不能变成死循环。"""
    return 400, _err("Use 'max_completion_tokens' instead.")


# ================================================================ 1. 最小合规请求体


def test_online_payload_contains_only_minimal_fields(monkeypatch):
    """在线端点：请求体里不许出现任何最小集合之外的顶层字段。"""
    ep = _install(monkeypatch, _MockEndpoint(_strict))
    backend = LMStudioBackend(
        "http://vendor.example", model="m", api_key="k", kind="online", slot="ONLINE_CHAT"
    )
    assert asyncio.run(backend.generate("hi", "S")) == "好的"
    assert ep.calls == 1, "最小合规请求体不该触发任何重试"
    assert set(ep.last) <= _MINIMAL_FIELDS
    assert "reasoning_effort" not in ep.last


def test_local_payload_carries_reasoning_effort(monkeypatch):
    """本地端点**必须**发 ``reasoning_effort=none``：本地推理模型会把 token 全耗在
    思维链上导致 content 为空。这是唯一一个「按 kind 分流」的字段。
    """
    ep = _install(monkeypatch, _MockEndpoint(lambda _p, _i: (200, _ok())))
    backend = LMStudioBackend("http://127.0.0.1:1234", model="m", kind="local", slot="LOCAL")
    asyncio.run(backend.generate("hi"))
    assert ep.last["reasoning_effort"] == "none"


def test_kind_decides_not_the_presence_of_a_key(monkeypatch):
    """判据是 ``kind``，不是「有没有 key」。

    本地网关也可以要求 dummy key；旧判据会把它当在线端点、漏发
    ``reasoning_effort``，表现为「回复全是空」——极难查。
    """
    ep = _install(monkeypatch, _MockEndpoint(lambda _p, _i: (200, _ok())))
    backend = LMStudioBackend(
        "http://127.0.0.1:1234", model="m", api_key="dummy", kind="local", slot="LOCAL"
    )
    asyncio.run(backend.generate("hi"))
    assert ep.last["reasoning_effort"] == "none"


def test_blank_kind_keeps_the_legacy_heuristic(monkeypatch):
    """没传 kind 的旧调用点（含大量既有测试）行为必须逐字不变：有 key 即在线。"""
    ep = _install(monkeypatch, _MockEndpoint(lambda _p, _i: (200, _ok())))
    asyncio.run(LMStudioBackend("http://x", model="m", api_key="k").generate("hi"))
    assert "reasoning_effort" not in ep.last
    asyncio.run(LMStudioBackend("http://x", model="m").generate("hi"))
    assert ep.last["reasoning_effort"] == "none"


def test_plugin_path_online_payload_is_also_minimal(monkeypatch):
    """插件兼容层是**另一份**请求循环，同样受最小合规约束。"""
    ep = _install(monkeypatch, _MockEndpoint(_strict))
    data = asyncio.run(
        chat_completion(
            [{"role": "user", "content": "hi"}],
            base_url="http://vendor.example",
            model="m",
            api_key="k",
            kind="online",
            slot="ONLINE_CHAT",
        )
    )
    assert data["choices"][0]["message"]["content"] == "好的"
    assert ep.calls == 1
    assert set(ep.last) <= _MINIMAL_FIELDS


def test_plugin_path_tools_stay_within_the_minimal_set(monkeypatch):
    """function calling 只允许 ``tools`` / ``tool_choice`` 两个字段进来。"""
    ep = _install(monkeypatch, _MockEndpoint(_strict))
    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    asyncio.run(
        chat_completion(
            [{"role": "user", "content": "hi"}],
            base_url="http://vendor.example",
            model="m",
            api_key="k",
            kind="online",
            slot="ONLINE_CHAT",
            tools=tools,
        )
    )
    assert ep.last["tools"] == tools
    assert ep.last["tool_choice"] == "auto"
    assert set(ep.last) <= _MINIMAL_FIELDS


def test_extra_body_is_opt_in_only(monkeypatch):
    """私有字段只能由调用方**显式**传入，默认一个都不加。

    这就是「每个额外字段都要有开关且默认关」的落点：插件自己要发 provider 私有
    参数是它的选择，我们不代它做。
    """
    ep = _install(monkeypatch, _MockEndpoint(lambda _p, _i: (200, _ok())))
    asyncio.run(
        chat_completion(
            [{"role": "user", "content": "hi"}],
            base_url="http://vendor.example",
            model="m",
            api_key="k",
            kind="online",
            slot="ONLINE_CHAT",
            extra_body={"top_k": 20},
        )
    )
    assert ep.last["top_k"] == 20
    # 不传时一个都不多
    ep2 = _install(monkeypatch, _MockEndpoint(_strict))
    asyncio.run(
        chat_completion(
            [{"role": "user", "content": "hi"}],
            base_url="http://vendor.example",
            model="m",
            api_key="k",
            kind="online",
            slot="ONLINE_CHAT",
        )
    )
    assert set(ep2.last) <= _MINIMAL_FIELDS


def test_no_json_mode_is_ever_requested(monkeypatch):
    """**绝不依赖 ``response_format`` / JSON mode**：支持度参差，且我们的
    prompt 本来就要求纯 JSON 输出并自行容错解析。
    """
    ep = _install(monkeypatch, _MockEndpoint(lambda _p, _i: (200, _ok())))
    backend = LMStudioBackend("http://x", model="m", api_key="k", kind="online", slot="S")
    asyncio.run(backend.generate("hi"))
    assert "response_format" not in ep.last


# ================================================================ 2. 按错误体自适应


def test_learns_the_length_field_and_retries(monkeypatch):
    """只认 ``max_completion_tokens`` 的端点：第一次 400，改完立刻重试成功。"""
    ep = _install(monkeypatch, _MockEndpoint(_length_field_only))
    backend = LMStudioBackend("http://x", model="m", api_key="k", kind="online", slot="ONLINE_CHAT")
    assert asyncio.run(backend.generate("hi")) == "好的"
    assert ep.calls == 2
    assert "max_tokens" in ep.payloads[0]
    assert "max_tokens" not in ep.payloads[1]
    assert ep.payloads[1]["max_completion_tokens"] == 2000


def test_learns_to_omit_temperature_and_retries(monkeypatch):
    ep = _install(monkeypatch, _MockEndpoint(_no_temperature))
    backend = LMStudioBackend("http://x", model="m", api_key="k", kind="online", slot="ONLINE_CHAT")
    assert asyncio.run(backend.generate("hi")) == "好的"
    assert ep.calls == 2
    assert "temperature" in ep.payloads[0]
    assert "temperature" not in ep.payloads[1]


def test_the_lesson_is_remembered_for_later_requests(monkeypatch):
    """学费只交一次：第二次调用直接用对的形状，不再撞 400。"""
    ep = _install(monkeypatch, _MockEndpoint(_length_field_only))
    backend = LMStudioBackend("http://x", model="m", api_key="k", kind="online", slot="ONLINE_CHAT")
    asyncio.run(backend.generate("first"))
    assert ep.calls == 2
    asyncio.run(backend.generate("second"))
    assert ep.calls == 3, "已学到的形状必须直接生效，不该再交一次学费"
    assert "max_completion_tokens" in ep.payloads[2]


def test_the_lesson_is_shared_across_both_code_paths(monkeypatch):
    """兼容状态按端点槽归集，所以主聊天链路学到的，插件链路直接受益。

    反过来也一样。两条路径各自学一遍等于同一个槽交两次学费。
    """
    ep = _install(monkeypatch, _MockEndpoint(_length_field_only))
    backend = LMStudioBackend("http://x", model="m", api_key="k", kind="online", slot="ONLINE_CHAT")
    asyncio.run(backend.generate("hi"))
    assert ep.calls == 2
    asyncio.run(
        chat_completion(
            [{"role": "user", "content": "hi"}],
            base_url="http://x",
            model="m",
            api_key="k",
            kind="online",
            slot="ONLINE_CHAT",
        )
    )
    assert ep.calls == 3
    assert "max_completion_tokens" in ep.payloads[2]


def test_different_slots_learn_independently(monkeypatch):
    """两个槽可能是两家厂商，一个的改法绝不能套到另一个头上。"""
    _install(monkeypatch, _MockEndpoint(_length_field_only))
    a = LMStudioBackend("http://a", model="m", api_key="k", kind="online", slot="ONLINE_CHAT")
    asyncio.run(a.generate("hi"))
    assert compat.compat_for("ONLINE_CHAT").max_tokens_field == "max_completion_tokens"
    assert compat.compat_for("ONLINE_MEMORY").max_tokens_field == "max_tokens"


def test_plugin_path_adapts_too(monkeypatch):
    ep = _install(monkeypatch, _MockEndpoint(_no_temperature))
    asyncio.run(
        chat_completion(
            [{"role": "user", "content": "hi"}],
            base_url="http://x",
            model="m",
            api_key="k",
            kind="online",
            slot="ONLINE_CHAT",
        )
    )
    assert ep.calls == 2
    assert "temperature" not in ep.payloads[1]


def test_streaming_uses_the_learned_shape_but_never_learns(monkeypatch):
    """流式**只用**已学到的形状、不在这里学。

    流一旦开始产出就不能重试（下游会看到重复内容），为了学一次而重发整个流不值得；
    非流式路径先撞上 400 并学会，流式随后自动受益。
    """
    compat.compat_for("ONLINE_CHAT").max_tokens_field = "max_completion_tokens"
    lines = ['data: {"choices":[{"delta":{"content":"嗨"},"finish_reason":null}]}', "data: [DONE]"]
    ep = _install(monkeypatch, _MockEndpoint(lambda _p, _i: (200, {}), stream_lines=lines))

    async def _drain():
        return [
            c
            async for c in chat_completion_stream(
                [{"role": "user", "content": "hi"}],
                base_url="http://x",
                model="m",
                api_key="k",
                kind="online",
                slot="ONLINE_CHAT",
            )
        ]

    chunks = asyncio.run(_drain())
    assert len(chunks) == 1
    assert "max_completion_tokens" in ep.last
    assert "max_tokens" not in ep.last
    assert ep.last["stream"] is True


def test_streaming_400_does_not_teach_anything(monkeypatch):
    """流式路径撞 400 也不学：它没法重试，学了只会让状态与实际请求脱节。"""
    lines: list[str] = []
    ep = _install(
        monkeypatch,
        _MockEndpoint(
            lambda _p, _i: (400, _err("Use 'max_completion_tokens' instead.")), stream_lines=lines
        ),
    )

    async def _drain():
        return [
            c
            async for c in chat_completion_stream(
                [{"role": "user", "content": "hi"}],
                base_url="http://x",
                model="m",
                api_key="k",
                kind="online",
                slot="ONLINE_CHAT",
            )
        ]

    with pytest.raises(OpenAIClientError):
        asyncio.run(_drain())
    assert ep.calls == 1
    assert compat.compat_for("ONLINE_CHAT").max_tokens_field == "max_tokens"


# ================================================================ 3. 自适应重试的边界


def test_at_most_one_adaptive_retry(monkeypatch):
    """两个字段名都拒的端点：学一次、重试一次、放弃。**绝不能变成死循环。**

    这是「4xx 不重试」那条判据的唯一例外，例外必须有硬上限——否则一个配置错误
    会被自适应无限重试，表现为整条链路挂死而不是显式失败。
    """
    ep = _install(monkeypatch, _MockEndpoint(_always_rejects_length))
    backend = LMStudioBackend("http://x", model="m", api_key="k", kind="online", slot="ONLINE_CHAT")
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(backend.generate("hi"))
    assert ep.calls == 2


def test_at_most_one_adaptive_retry_on_the_plugin_path(monkeypatch):
    ep = _install(monkeypatch, _MockEndpoint(_always_rejects_length))
    with pytest.raises(OpenAIClientError):
        asyncio.run(
            chat_completion(
                [{"role": "user", "content": "hi"}],
                base_url="http://x",
                model="m",
                api_key="k",
                kind="online",
                slot="ONLINE_CHAT",
            )
        )
    assert ep.calls == 2


def test_adaptive_retry_does_not_consume_the_normal_budget(monkeypatch, no_backoff):
    """自适应重试不占用正常的 3 次重试预算。

    编排：400（参数差异）→ 500 → 500 → 200。正常预算完整保留时第 4 次才成功；
    若自适应吃掉了一次预算，第三个 500 就会耗尽预算而失败。所以「跑通 + 4 次请求」
    正是这条性质的判据。
    """
    seq = [
        (400, _err("Use 'max_completion_tokens' instead.")),
        (500, _err("upstream hiccup")),
        (500, _err("upstream hiccup")),
        (200, _ok()),
    ]
    ep = _install(monkeypatch, _MockEndpoint(lambda _p, i: seq[i]))
    backend = LMStudioBackend("http://x", model="m", api_key="k", kind="online", slot="ONLINE_CHAT")
    assert asyncio.run(backend.generate("hi")) == "好的"
    assert ep.calls == 4


def test_adaptive_retry_does_not_consume_the_budget_on_the_plugin_path(monkeypatch, no_backoff):
    seq = [
        (400, _err("Use 'max_completion_tokens' instead.")),
        (500, _err("upstream hiccup")),
        (500, _err("upstream hiccup")),
        (200, _ok()),
    ]
    ep = _install(monkeypatch, _MockEndpoint(lambda _p, i: seq[i]))
    data = asyncio.run(
        chat_completion(
            [{"role": "user", "content": "hi"}],
            base_url="http://x",
            model="m",
            api_key="k",
            kind="online",
            slot="ONLINE_CHAT",
        )
    )
    assert data["choices"]
    assert ep.calls == 4


def test_plain_4xx_is_still_not_retried(monkeypatch):
    """学不到改法的 4xx 照旧一次就放弃——鉴权失败重试三次只是浪费三次 401。"""
    ep = _install(monkeypatch, _MockEndpoint(lambda _p, _i: (401, _err("invalid api key"))))
    backend = LMStudioBackend("http://x", model="m", api_key="bad", kind="online", slot="ONLINE_CHAT")
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(backend.generate("hi"))
    assert ep.calls == 1


def test_a_401_never_teaches_a_payload_fix(monkeypatch):
    """401 的错误体里恰好带了关键词也不许学：它不是参数问题。"""
    ep = _install(
        monkeypatch,
        _MockEndpoint(lambda _p, _i: (401, _err("invalid key; also use max_completion_tokens"))),
    )
    backend = LMStudioBackend("http://x", model="m", api_key="bad", kind="online", slot="ONLINE_CHAT")
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(backend.generate("hi"))
    assert ep.calls == 1
    assert compat.compat_for("ONLINE_CHAT").max_tokens_field == "max_tokens"


# ================================================================ 4. 用量与截断可见


def test_usage_is_recorded_per_role_and_slot(monkeypatch):
    """记账口拿到角色 / 槽 / 模型：缓存命中率是「双 key 是否生效」的唯一验收手段。"""
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "prompt_tokens_details": {"cached_tokens": 64},
    }
    _install(monkeypatch, _MockEndpoint(lambda _p, _i: (200, _ok(usage=usage))))
    backend = LMStudioBackend(
        "http://x",
        model="v3",
        api_key="k",
        kind="online",
        slot="ONLINE_CHAT",
        role="chat",
    )
    asyncio.run(backend.generate("hi"))
    stats = usage_sink.snapshot()["chat@ONLINE_CHAT:v3"]
    assert stats["prompt_tokens"] == 100
    assert stats["completion_tokens"] == 20
    assert stats["cached_tokens"] == 64
    assert stats["cache_hit_rate"] == pytest.approx(0.64)


def test_failures_are_recorded_too(monkeypatch):
    """失败率是「该不该降级到本地」的判断依据，所以失败也要记一笔。"""
    _install(monkeypatch, _MockEndpoint(lambda _p, _i: (401, _err("nope"))))
    backend = LMStudioBackend(
        "http://x", model="v3", api_key="bad", kind="online", slot="ONLINE_CHAT", role="chat"
    )
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(backend.generate("hi"))
    assert usage_sink.snapshot()["chat@ONLINE_CHAT:v3"]["failed"] == 1


def test_truncation_is_visible(monkeypatch):
    """``finish_reason=length`` 是「输出截断 → JSON 解析失败 → 消息丢失」的唯一信号。"""
    _install(monkeypatch, _MockEndpoint(lambda _p, _i: (200, _ok(finish="length"))))
    backend = LMStudioBackend(
        "http://x", model="v3", api_key="k", kind="online", slot="ONLINE_CHAT", role="consolidation"
    )
    reply, finish = asyncio.run(backend.generate_detailed("hi"))
    assert (reply, finish) == ("好的", "length")
    assert usage_sink.snapshot()["consolidation@ONLINE_CHAT:v3"]["truncated"] == 1


def test_log_tag_stays_identical_for_legacy_call_sites(monkeypatch):
    """没有角色/槽名的旧调用点日志前缀必须还是 ``[LM Studio]``。

    改造前的日志要能和改造后对比，前缀一变历史日志就没法比了。
    """
    assert LMStudioBackend("http://x")._log_tag() == "[LM Studio]"
    assert LMStudioBackend("http://x", slot="LOCAL", role="chat")._log_tag() == "[LLM chat@LOCAL]"
