# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Provider：messages 组装、人格三态、LLMResponse 语义。"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from astrbot_compat.events import MessageChain
from astrbot_compat.llm import (
    LLMResponse,
    ProviderRequest,
    StellaChatProvider,
    ToolSet,
)


def _chat(provider, **kwargs):
    return asyncio.run(provider.text_chat(**kwargs))


@pytest.fixture
def provider() -> StellaChatProvider:
    return StellaChatProvider()


# ---------------------------------------------------------------- 人格三态


def test_plugin_system_prompt_wins(provider, fake_llm, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_LLM_SYSTEM_PROMPT", "默认人格", raising=False)
    _chat(provider, prompt="hi", system_prompt="我是插件自己的人格")
    assert fake_llm.last_messages[0] == {
        "role": "system",
        "content": "我是插件自己的人格",
    }


def test_falls_back_to_plugin_persona(provider, fake_llm, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_LLM_SYSTEM_PROMPT", "默认人格", raising=False)
    _chat(provider, prompt="hi")
    assert fake_llm.last_messages[0] == {"role": "system", "content": "默认人格"}


def test_empty_setting_sends_no_system_message(provider, fake_llm, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_LLM_SYSTEM_PROMPT", "", raising=False)
    _chat(provider, prompt="hi")
    assert all(m["role"] != "system" for m in fake_llm.last_messages)


def test_stella_persona_never_leaks(provider, fake_llm):
    """插件调用绝不能带上 Stella 的人格或记忆。"""
    _chat(provider, prompt="hi", contexts=[{"role": "user", "content": "旧话"}])
    blob = str(fake_llm.last_messages)
    assert "memories" not in blob
    assert "记忆" not in blob


# ---------------------------------------------------------------- 组装顺序


def test_message_assembly_order(provider, fake_llm):
    _chat(
        provider,
        prompt="现在的问题",
        system_prompt="S",
        contexts=[
            {"role": "user", "content": "旧问"},
            {"role": "assistant", "content": "旧答"},
        ],
    )
    assert [m["role"] for m in fake_llm.last_messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert fake_llm.last_messages[-1]["content"] == "现在的问题"


def test_image_becomes_multimodal_block(provider, fake_llm):
    _chat(provider, prompt="看图", image_urls=["https://x/y.png"])
    content = fake_llm.last_messages[-1]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "看图"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"] == "https://x/y.png"


def test_plain_prompt_stays_a_string(provider, fake_llm):
    """只有一段文本时降级成简单形式，与上游一致。"""
    _chat(provider, prompt="纯文本")
    assert fake_llm.last_messages[-1]["content"] == "纯文本"


def test_audio_is_ignored_with_warning(provider, fake_llm, caplog):
    with caplog.at_level("WARNING"):
        _chat(provider, prompt="听", audio_urls=["a.wav"])
    assert any("音频" in r.message for r in caplog.records)


# ---------------------------------------------------------------- 响应解析


def test_response_parsing(provider, fake_llm):
    fake_llm.push_text("模型的回答")
    resp = _chat(provider, prompt="q")
    assert resp.completion_text == "模型的回答"
    assert resp.role == "assistant"
    assert resp.usage.total == 2


def test_tool_call_parsing(provider, fake_llm):
    fake_llm.push_tool_call("get_weather", '{"location": "北京"}')
    resp = _chat(provider, prompt="q")
    assert resp.tools_call_name == ["get_weather"]
    assert resp.tools_call_args == [{"location": "北京"}]
    assert resp.tools_call_ids == ["call_1"]


def test_malformed_tool_arguments_degrade_to_empty(provider, fake_llm, caplog):
    fake_llm.push_tool_call("t", "这不是 json")
    with caplog.at_level("WARNING"):
        resp = _chat(provider, prompt="q")
    assert resp.tools_call_args == [{}]


# ---------------------------------------------------------------- LLMResponse


def test_completion_text_is_a_property_over_chain():
    """挂了 result_chain 时，读写都作用在链上（上游语义）。"""
    resp = LLMResponse("assistant", "第一段", MessageChain().message("旧"))
    assert resp.completion_text == "第一段"
    resp.completion_text = "第二段"
    assert resp.result_chain.get_plain_text() == "第二段"


def test_completion_text_without_chain():
    resp = LLMResponse("assistant", "裸文本")
    assert resp.completion_text == "裸文本"
    assert resp.result_chain is None


def test_to_openai_tool_calls_model():
    resp = LLMResponse(
        "assistant",
        tools_call_name=["f"],
        tools_call_args=[{"a": 1}],
        tools_call_ids=["i1"],
    )
    calls = resp.to_openai_tool_calls_model()
    assert calls[0].function.name == "f"
    assert calls[0].function.arguments == '{"a": 1}'
    # 上游拼写错误的别名也要在
    assert resp.to_openai_to_calls_model()[0].id == "i1"


# ---------------------------------------------------------------- 形状


def test_text_chat_stream_is_async_generator():
    """上游用 `if False: yield` 保证基类方法本身就是异步生成器。"""
    assert inspect.isasyncgenfunction(StellaChatProvider.text_chat_stream)


def test_provider_meta():
    meta = StellaChatProvider().meta()
    assert meta.id == "stella"
    assert meta.provider_type.value == "chat_completion"


def test_pop_record_keeps_system():
    provider = StellaChatProvider()
    ctx = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "1"},
        {"role": "assistant", "content": "2"},
        {"role": "user", "content": "3"},
    ]
    asyncio.run(provider.pop_record(ctx))
    assert [m["role"] for m in ctx] == ["system", "user"]


def test_provider_request_defaults():
    req = ProviderRequest()
    assert req.image_urls == []
    assert req.contexts == []
    assert req.func_tool is None
    # 独立实例，不共享可变默认值
    ProviderRequest().image_urls.append("x")
    assert req.image_urls == []


def test_tool_set_dedup_prefers_active():
    from astrbot_compat.llm import FunctionTool

    ts = ToolSet()
    ts.add_tool(FunctionTool(name="t", description="旧", active=True))
    ts.add_tool(FunctionTool(name="t", description="新", active=False))
    assert len(ts) == 1
    assert ts.get_tool("t").description == "旧"
