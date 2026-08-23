# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""上下文与工具的 token 预算。

本地模型只有 8192 窗口，插件的对话历史与工具 schema 都能把它撑爆。
这里守住「宁可截断老对话，也不要让请求被模型拒绝」。
"""

from __future__ import annotations

import asyncio

import pytest

from astrbot_compat.llm import FunctionTool, StellaChatProvider, ToolSet, trim_messages
from astrbot_compat.llm.provider import _estimate_messages_tokens


def _long_history(rounds: int) -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "这是一段中文内容" * 20}
        for i in range(rounds)
    ]


# ---------------------------------------------------------------- trim_messages


def test_trim_keeps_within_budget():
    msgs = [{"role": "system", "content": "S"}, *_long_history(200)]
    kept, dropped = trim_messages(msgs, budget=2000)
    assert dropped > 0
    assert _estimate_messages_tokens(kept) <= 2000


def test_trim_never_drops_system():
    msgs = [{"role": "system", "content": "系统提示" * 10}, *_long_history(100)]
    kept, _ = trim_messages(msgs, budget=500)
    assert kept[0]["role"] == "system"
    assert sum(1 for m in kept if m["role"] == "system") == 1


def test_trim_keeps_the_latest_message():
    """丢掉当前这轮的输入，请求就没意义了。"""
    msgs = [*_long_history(100), {"role": "user", "content": "当前问题"}]
    kept, _ = trim_messages(msgs, budget=200)
    assert kept[-1]["content"] == "当前问题"


def test_trim_drops_oldest_first():
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "最老的" * 100},
        {"role": "assistant", "content": "中间的" * 100},
        {"role": "user", "content": "最新的"},
    ]
    kept, dropped = trim_messages(msgs, budget=120)
    assert dropped >= 1
    assert not any("最老的" in str(m.get("content")) for m in kept)


def test_trim_drops_in_pairs():
    """成对丢弃：别把一问一答拆散，也别让 tool 消息变成孤儿。"""
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "一" * 400},
        {"role": "assistant", "content": "二" * 400},
        {"role": "user", "content": "三" * 400},
        {"role": "assistant", "content": "四" * 400},
        {"role": "user", "content": "最新的"},
    ]
    # 预算刚好只装得下一对，所以应当只丢掉最早那一对
    kept, dropped = trim_messages(msgs, budget=1500)
    assert dropped == 2
    assert kept[0]["role"] == "system"
    assert not any("一" in str(m.get("content")) for m in kept)
    assert not any("二" in str(m.get("content")) for m in kept)
    # 后面那一对与当前输入都还在
    assert [str(m["content"])[0] for m in kept[1:]] == ["三", "四", "最"]


def test_trim_noop_when_within_budget():
    msgs = [{"role": "user", "content": "短"}]
    kept, dropped = trim_messages(msgs, budget=8192)
    assert kept == msgs
    assert dropped == 0


def test_trim_reserves_room_for_reply():
    msgs = _long_history(50)
    with_reserve, dropped_a = trim_messages(msgs, budget=3000, reserved=2500)
    without, dropped_b = trim_messages(msgs, budget=3000, reserved=0)
    assert dropped_a > dropped_b
    assert len(with_reserve) < len(without)


def test_image_blocks_are_not_estimated_as_text():
    """base64 图片按经验值计，不能把正文当文本估爆。"""
    huge = "A" * 200_000
    msgs = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "看图"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{huge}"}},
            ],
        },
    ]
    assert _estimate_messages_tokens(msgs) < 2000


# ---------------------------------------------------------------- 端到端预算


def test_context_is_trimmed_before_send(fake_llm, monkeypatch, caplog):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_LLM_MAX_CONTEXT_TOKENS", 1500, raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_LLM_MAX_TOKENS", 200, raising=False)
    provider = StellaChatProvider()
    with caplog.at_level("WARNING"):
        asyncio.run(provider.text_chat(prompt="现在的问题", contexts=_long_history(200)))
    assert _estimate_messages_tokens(fake_llm.last_messages) <= 1500
    assert any("超预算" in r.message for r in caplog.records)


def test_tools_are_truncated_over_limit(fake_llm, monkeypatch, caplog):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_LLM_MAX_TOOLS", 3, raising=False)
    ts = ToolSet(
        tools=[FunctionTool(name=f"t{i}", description="d") for i in range(10)],
    )
    provider = StellaChatProvider()
    with caplog.at_level("WARNING"):
        asyncio.run(provider.text_chat(prompt="q", func_tool=ts))
    assert len(fake_llm.last_tools) == 3
    assert any("超过 ASTRBOT_LLM_MAX_TOOLS" in r.message for r in caplog.records)


def test_inactive_tools_are_not_sent(fake_llm):
    ts = ToolSet(
        tools=[
            FunctionTool(name="on", description="d", active=True),
            FunctionTool(name="off", description="d", active=False),
        ],
    )
    provider = StellaChatProvider()
    asyncio.run(provider.text_chat(prompt="q", func_tool=ts))
    assert [t["function"]["name"] for t in fake_llm.last_tools] == ["on"]


def test_empty_tool_set_sends_no_tools(fake_llm):
    provider = StellaChatProvider()
    asyncio.run(provider.text_chat(prompt="q", func_tool=ToolSet()))
    assert fake_llm.last_tools is None


def test_token_estimate_is_logged(fake_llm, caplog):
    provider = StellaChatProvider()
    with caplog.at_level("INFO"):
        asyncio.run(provider.text_chat(prompt="q"))
    assert any("请求估算" in r.message and "token" in r.message for r in caplog.records)


@pytest.mark.parametrize("budget", [512, 2048, 8192])
def test_budget_setting_is_respected(fake_llm, monkeypatch, budget):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_LLM_MAX_CONTEXT_TOKENS", budget, raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_LLM_MAX_TOKENS", 0, raising=False)
    provider = StellaChatProvider()
    asyncio.run(provider.text_chat(prompt="q", contexts=_long_history(300)))
    assert _estimate_messages_tokens(fake_llm.last_messages) <= budget
