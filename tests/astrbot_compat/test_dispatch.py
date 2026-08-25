# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""分发管道：唤醒模型与 handler 执行（对齐上游 WakingCheckStage）。"""

from __future__ import annotations

import asyncio

import pytest

import astrbot_compat.filters as filter  # noqa: A004  # 插件侧惯用名，保持一致
from astrbot_compat.base import Star
from astrbot_compat.filters import EventMessageType, GreedyStr, PermissionType
from astrbot_compat.pipeline import dispatch


def make_ev(text: str, segs: list | None = None, **kw):
    """非夹具版事件构造器：should_dispatch 是纯函数，不需要夹具。"""
    from tests.astrbot_compat.conftest import FakeEvent, seg

    built = segs if segs is not None else [seg("text", text=text)]
    return FakeEvent(text, built, **kw)


def _run(nb_event, bot):
    return asyncio.run(dispatch(nb_event, bot))


@pytest.fixture
def demo_plugin(register_plugin):
    class Demo(Star):
        @filter.command("echo")
        async def echo(self, event, text: GreedyStr):
            """回显"""
            yield event.plain_result(f"echo:{text}")

        @filter.command("add")
        async def add(self, event, a: int, b: int = 1):
            yield event.plain_result(str(a + b))

        @filter.regex(r"喵+")
        async def meow(self, event):
            yield event.plain_result("喵~")

        @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
        async def counter(self, event):
            event.set_extra("counted", True)

        @filter.command("secret")
        @filter.permission_type(PermissionType.ADMIN)
        async def secret(self, event):
            yield event.plain_result("top secret")

        @filter.command("viastr")
        async def viastr(self, event):
            event.set_result("从 set_result 发出")

    register_plugin(Demo)
    return Demo


def test_slash_command_works_without_at(demo_plugin, make_event, fake_bot):
    # 这是 AstrBot 插件最标准的用法：群里直接打 /echo
    assert _run(make_event("/echo hello  world"), fake_bot) is True
    assert fake_bot.sent == ["echo:hello world"]


def test_command_works_when_at_mentioned(demo_plugin, make_event, fake_bot):
    ev = make_event("echo hi", [{"type": "at", "qq": "9"}])
    assert _run(ev, fake_bot) is True
    assert fake_bot.sent == ["echo:hi"]


def test_regex_fires_on_plain_message(demo_plugin, make_event, fake_bot):
    # 正则监听不受 @ / 唤醒前缀约束
    assert _run(make_event("喵喵喵"), fake_bot) is True
    assert fake_bot.sent == ["喵~"]


def test_no_match_is_not_handled(demo_plugin, make_event, fake_bot):
    assert _run(make_event("今天天气不错"), fake_bot) is False
    assert fake_bot.sent == []


def test_private_message_needs_no_prefix(demo_plugin, make_event, fake_bot):
    assert _run(make_event("echo hi", group_id=None), fake_bot) is True
    assert fake_bot.sent == ["echo:hi"]


def test_param_conversion_and_defaults(demo_plugin, make_event, fake_bot):
    assert _run(make_event("/add 2 3"), fake_bot) is True
    assert fake_bot.sent == ["5"]
    fake_bot.sent.clear()
    assert _run(make_event("/add 2"), fake_bot) is True
    assert fake_bot.sent == ["3"]


def test_param_error_is_reported_to_user(demo_plugin, make_event, fake_bot):
    assert _run(make_event("/add abc"), fake_bot) is True
    assert "参数 a 类型错误" in fake_bot.sent[0]


def test_permission_denied_is_reported(demo_plugin, make_event, fake_bot):
    assert _run(make_event("/secret"), fake_bot) is True
    assert "权限不足" in fake_bot.sent[0]


def test_permission_granted_for_admin(demo_plugin, make_event, fake_bot):
    assert _run(make_event("/secret", role="admin"), fake_bot) is True
    assert fake_bot.sent == ["top secret"]


def test_set_result_string_is_delivered(demo_plugin, make_event, fake_bot):
    assert _run(make_event("/viastr"), fake_bot) is True
    assert fake_bot.sent == ["从 set_result 发出"]


def test_dispatch_is_cheap_without_plugins(make_event, fake_bot):
    assert _run(make_event("/echo hi"), fake_bot) is False


def test_command_group_dispatch(register_plugin, make_event, fake_bot):
    class GroupDemo(Star):
        @filter.command_group("math")
        def math_group(self):
            pass

        @math_group.command("add")
        async def math_add(self, event, a: int, b: int):
            yield event.plain_result(str(a + b))

    register_plugin(GroupDemo)
    assert _run(make_event("/math add 2 3"), fake_bot) is True
    assert fake_bot.sent == ["5"]


def test_group_stub_alone_does_not_reply(register_plugin, make_event, fake_bot):
    class GroupDemo2(Star):
        @filter.command_group("tool")
        def tool_group(self):
            pass

        @tool_group.command("run")
        async def tool_run(self, event):
            yield event.plain_result("ran")

    register_plugin(GroupDemo2)
    assert _run(make_event("/tool"), fake_bot) is False
    assert fake_bot.sent == []


def test_stop_event_blocks_later_handlers(register_plugin, make_event, fake_bot):
    class StopDemo(Star):
        @filter.regex(r"trigger")
        async def first(self, event):
            event.stop_event()

        @filter.regex(r"trigger")
        async def second(self, event):
            yield event.plain_result("不该出现")

    register_plugin(StopDemo)
    assert _run(make_event("trigger"), fake_bot) is True
    assert fake_bot.sent == []


def test_priority_orders_handlers(register_plugin, make_event, fake_bot):
    class PriorityDemo(Star):
        @filter.regex(r"ping", priority=1)
        async def low(self, event):
            yield event.plain_result("low")

        @filter.regex(r"ping", priority=10)
        async def high(self, event):
            yield event.plain_result("high")

    register_plugin(PriorityDemo)
    assert _run(make_event("ping"), fake_bot) is True
    assert fake_bot.sent == ["high", "low"]


def test_handler_exception_does_not_break_others(register_plugin, make_event, fake_bot):
    class BoomDemo(Star):
        @filter.regex(r"boom", priority=10)
        async def boom(self, event):
            raise RuntimeError("炸了")

        @filter.regex(r"boom", priority=1)
        async def survivor(self, event):
            yield event.plain_result("still here")

    register_plugin(BoomDemo)
    assert _run(make_event("boom"), fake_bot) is True
    assert fake_bot.sent == ["still here"]


def test_llm_dependent_plugin_is_reported(register_plugin, make_event, fake_bot, monkeypatch):
    """LLM 关掉时，直接调 context.llm_generate() 的插件不该静默失败。"""
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_LLM_ENABLED", False, raising=False)

    class LLMDemo(Star):
        @filter.command("ask")
        async def ask(self, event):
            await self.context.llm_generate()

    register_plugin(LLMDemo)
    assert _run(make_event("/ask"), fake_bot) is True
    assert "大模型" in fake_bot.sent[0]


def test_forward_message_uses_forward_action(register_plugin, make_event, fake_bot):
    from astrbot_compat.components import Node, Nodes, Plain

    class ForwardDemo(Star):
        @filter.command("fwd")
        async def fwd(self, event):
            yield event.chain_result([Nodes([Node([Plain("a")], name="bot", uin="1")])])

    register_plugin(ForwardDemo)
    assert _run(make_event("/fwd"), fake_bot) is True
    assert fake_bot.actions[0][0] == "send_group_forward_msg"
    assert fake_bot.actions[0][1]["group_id"] == 1


# ---------- should_dispatch：哪些平台事件该进插件管道 ----------
# 这条规则曾把手机端分享的小程序卡片整条挡在管道外（2026-08-25 bug_report#1）：
# 卡片只有一个 json 段，get_plaintext() 返回空串，而当时的门槛是「有纯文本」。
# 后果是 @event_message_type(ALL) 这类专门处理非文本消息的 handler 永远收不到事件。


def _json_card(**kw):
    from tests.astrbot_compat.conftest import FakeEvent, seg

    payload = (
        '{"meta":{"detail_1":{"title":"哔哩哔哩",'
        '"desc":"某视频","qqdocurl":"https://b23.tv/abc"}}}'
    )
    return FakeEvent("", [seg("json", data=payload)], **kw)


def test_should_dispatch_accepts_text():
    from astrbot_compat.pipeline import should_dispatch

    assert should_dispatch(make_ev("hi"), allowed_groups={1}) is True


def test_should_dispatch_accepts_json_card_without_plaintext():
    """回归 bug_report#2026-08-25#1：卡片没有纯文本，但必须进管道。"""
    from astrbot_compat.pipeline import should_dispatch

    event = _json_card()
    assert event.get_plaintext() == ""
    assert should_dispatch(event, allowed_groups={1}) is True


def test_should_dispatch_rejects_empty_message():
    from astrbot_compat.pipeline import should_dispatch
    from tests.astrbot_compat.conftest import FakeEvent

    assert should_dispatch(FakeEvent("", []), allowed_groups={1}) is False


def test_should_dispatch_rejects_self_echo():
    """插件可以在回复里带链接/卡片，让它再被自己的 handler 解析就会自激。"""
    from astrbot_compat.pipeline import should_dispatch

    assert should_dispatch(make_ev("hi", user_id=9, self_id=9), allowed_groups={1}) is False


def test_should_dispatch_respects_group_allowlist():
    from astrbot_compat.pipeline import should_dispatch

    assert should_dispatch(make_ev("hi", group_id=2), allowed_groups={1}) is False


def test_should_dispatch_private_gated():
    from astrbot_compat.pipeline import should_dispatch

    ev = make_ev("hi", group_id=None)
    assert should_dispatch(ev, allowed_groups={1}, allow_private=False) is False
    assert should_dispatch(ev, allowed_groups={1}, allow_private=True) is True


def test_should_dispatch_survives_broken_event():
    """规则是 NoneBot Rule，抛异常会让整个 matcher 挂掉——宁可判 False。"""
    import types

    from astrbot_compat.pipeline import should_dispatch

    broken = types.SimpleNamespace(user_id=1, self_id=9, group_id=1)
    assert should_dispatch(broken, allowed_groups={1}) is False


def test_json_card_reaches_all_message_handler(register_plugin, fake_bot):
    """端到端：只有 json 段的消息要能唤醒 event_message_type(ALL) 的 handler。"""
    seen: list[str] = []

    class CardDemo(Star):
        @filter.event_message_type(EventMessageType.ALL)
        async def parse_card(self, event):
            for el in event.message_obj.message:
                if getattr(el, "type", "") == "Json":
                    seen.append("json")

    register_plugin(CardDemo)
    _run(_json_card(), fake_bot)
    assert seen == ["json"]
