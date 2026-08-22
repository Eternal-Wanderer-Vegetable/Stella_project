# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""事件与结果对象：与上游 AstrMessageEvent / MessageChain 的语义对齐。"""

from __future__ import annotations

import asyncio

import pytest

from astrbot_compat.components import At, AtAll, Plain
from astrbot_compat.events import (
    AstrBotMessage,
    AstrMessageEvent,
    CommandResult,
    EventResultType,
    MessageChain,
    MessageEventResult,
    MessageType,
    ResultContentType,
    build_event,
)


def test_get_plain_text_joins_with_space():
    # 上游用空格连接，Stella 早期用空串，会把 "a" "b" 粘成 "ab"
    assert MessageChain().message("a").message("b").get_plain_text() == "a b"


def test_get_plain_text_with_marks():
    chain = MessageChain().message("a").at_all()
    assert chain.get_plain_text(with_other_comps_mark=True) == "a [AtAll]"


def test_at_accepts_both_upstream_and_legacy_forms():
    chain = MessageChain().at("张三", 123).at(456)
    first, second = chain.chain
    assert (first.qq, first.name) == ("123", "张三")
    assert second.qq == "456"


def test_at_all_and_derive_and_squash():
    chain = MessageChain().message("a").at_all().message("b")
    assert isinstance(chain.chain[1], AtAll)
    derived = chain.use_t2i(True).derive([Plain("c")])
    assert derived.use_t2i_ is True
    assert chain.squash_plain().get_plain_text() == "ab"


def test_result_type_helpers():
    r = MessageEventResult().message("x")
    assert r.is_stopped() is False
    assert r.stop_event().is_stopped() is True
    assert r.continue_event().result_type is EventResultType.CONTINUE
    assert r.set_result_content_type(ResultContentType.LLM_RESULT).is_llm_result()
    assert r.is_model_result() is True


def test_result_content_type_has_all_upstream_members():
    assert {m.name for m in ResultContentType} == {
        "LLM_RESULT",
        "AGENT_RUNNER_ERROR",
        "GENERAL_RESULT",
        "STREAMING_RESULT",
        "STREAMING_FINISH",
    }


def test_command_result_is_message_event_result_alias():
    assert CommandResult is MessageEventResult


def test_set_result_wraps_plain_string():
    # 上游 set_result 会把 str 包成 MessageEventResult；不包会导致消息静默丢失
    ev = AstrMessageEvent(message_str="hi")
    ev.set_result("hello")
    assert isinstance(ev.get_result(), MessageEventResult)
    assert ev.get_result().get_plain_text() == "hello"


def test_stop_event_reflects_in_result():
    ev = AstrMessageEvent(message_str="hi")
    ev.stop_event()
    assert ev.is_stopped() is True
    assert ev.get_result().is_stopped() is True
    ev.continue_event()
    assert ev.is_stopped() is False


def test_writable_flags_and_umo():
    ev = AstrMessageEvent(message_str="hi")
    ev.is_at_or_wake_command = True  # 上游是普通属性，不能是只读 property
    ev.unified_msg_origin = "aiocqhttp:FriendMessage:99"
    assert ev.session_id == "99"
    assert ev.get_session_id() == "99"
    assert ev.get_message_type() is MessageType.GROUP_MESSAGE
    ev.session_id = "100"
    assert ev.unified_msg_origin.endswith(":100")


def test_extras_api():
    ev = AstrMessageEvent(message_str="hi")
    ev.set_extra("a", 1)
    assert ev.get_extra() == {"a": 1}  # 无参返回整个字典
    assert ev.get_extra("a") == 1
    assert ev.get_extra("missing", "dft") == "dft"
    ev.clear_extra()
    assert ev.get_extra() == {}


def test_should_call_llm_setter_and_getter():
    ev = AstrMessageEvent(message_str="hi")
    assert ev.should_call_llm() is None
    ev.should_call_llm(False)
    assert ev.call_llm is False


def test_message_outline():
    obj = AstrBotMessage(message=[Plain("hi"), At(qq=5)])
    ev = AstrMessageEvent(message_str="hi", message_obj=obj)
    assert ev.get_message_outline() == "hi@5"


@pytest.mark.parametrize(
    ("text", "segs", "group_id", "expected"),
    [
        ("/help", None, 1, True),  # 唤醒前缀
        ("help", None, 1, False),  # 群里裸文本不唤醒
        ("help", [{"type": "at", "qq": "9"}], 1, True),  # @ 机器人
        ("help", [{"type": "at", "qq": "all"}], 1, True),  # @ 全体
        ("help", [{"type": "at", "qq": "8"}], 1, False),  # @ 的是别人
        ("help", None, None, True),  # 私聊
    ],
)
def test_wake_resolution(text, segs, group_id, expected, make_event):
    ev = asyncio.run(build_event(make_event(text, segs, group_id), None))
    assert ev.is_at_or_wake_command is expected


def test_wake_prefix_is_stripped(make_event):
    ev = asyncio.run(build_event(make_event("/echo hi", None, 1), None))
    assert ev.message_str == "echo hi"


def test_admin_role_from_group_role(make_event):
    nb = make_event("hi", None, 1)
    nb.sender.role = "admin"
    ev = asyncio.run(build_event(nb, None))
    assert ev.is_admin() is True
