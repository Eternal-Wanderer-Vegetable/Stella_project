# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""shim 里 LLM 相关假模块的导入面。

插件的 import 语句是硬契约：少绑一个名字，插件就在 import 阶段直接崩，
连日志都跑不到。所以这里逐个断言，而不是抽样。
"""

from __future__ import annotations

import importlib

import pytest

# conftest 里已经 install_shim()

_MODULES = [
    "astrbot.core.provider",
    "astrbot.core.provider.entities",
    # 上游的历史拼写错误，老插件在 import 它
    "astrbot.core.provider.entites",
    "astrbot.core.agent",
    "astrbot.core.agent.tool",
    "astrbot.core.agent.message",
    "astrbot.core.agent.run_context",
    "astrbot.core.agent.hooks",
    "astrbot.core.db",
    "astrbot.core.db.po",
]


@pytest.mark.parametrize("name", _MODULES)
def test_module_is_importable(name):
    assert importlib.import_module(name) is not None


@pytest.mark.parametrize(
    "module_name",
    ["astrbot.api.provider", "astrbot.core.provider", "astrbot.core.provider.entites"],
)
def test_provider_entities_are_the_real_classes(module_name):
    from astrbot_compat import llm as real

    mod = importlib.import_module(module_name)
    for attr in ("Provider", "ProviderRequest", "LLMResponse", "ProviderType", "TokenUsage"):
        assert getattr(mod, attr) is getattr(real, attr), attr
    # Personality 在 po 里，不在 llm 包里
    from astrbot_compat.po import Personality

    assert mod.Personality is Personality


def test_agent_modules_expose_tools_and_messages():
    from astrbot_compat import llm as real

    tool_mod = importlib.import_module("astrbot.core.agent.tool")
    assert tool_mod.FunctionTool is real.FunctionTool
    assert tool_mod.ToolSet is real.ToolSet
    assert tool_mod.FuncCall is real.FunctionToolManager

    msg_mod = importlib.import_module("astrbot.core.agent.message")
    assert msg_mod.AssistantMessageSegment is real.AssistantMessageSegment
    assert msg_mod.ToolCall is real.ToolCall

    assert importlib.import_module("astrbot.core.agent.run_context").ContextWrapper is (
        real.ContextWrapper
    )
    assert importlib.import_module("astrbot.core.agent.hooks").BaseAgentRunHooks is (
        real.BaseAgentRunHooks
    )


def test_db_po_exposes_conversation():
    from astrbot_compat.po import Conversation, Personality

    po = importlib.import_module("astrbot.core.db.po")
    assert po.Conversation is Conversation
    assert po.Personality is Personality
    # astrbot.core.db.po 也要能当属性访问（插件写 db.po.Conversation）
    assert importlib.import_module("astrbot.core.db").po is po


def test_llm_tools_singleton_is_shared():
    """全局工具表必须是同一个对象，否则注册与读取会分裂到两张表。"""
    from astrbot_compat.llm.tool import llm_tools

    assert importlib.import_module("astrbot.core.provider").llm_tools is llm_tools


def test_api_sp_and_llm_tool_are_real():
    import astrbot
    import astrbot.core

    import astrbot_compat.filters as filters
    from astrbot_compat.preferences import sp

    api = importlib.import_module("astrbot.api")
    assert api.sp is sp
    assert api.llm_tool is filters.llm_tool
    # 上游把 sp 也挂在顶层与 core 上
    assert astrbot.sp is sp
    assert astrbot.core.sp is sp
