# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""pipeline._compose_prompt 指令前置顺序的回归护栏。

2026-08-13 接错话 bug 的变体：主动 @ 时 ctx.message 是任务指令而非用户输入，
若仍放在上下文之后，模型会把尾巴里的最近对话当成待回应内容、去接那句话而不是
执行指令。这里钉死两种 intent 的拼接顺序。
"""
from core.context import ChatContext
from core.pipeline import _compose_prompt


def test_normal_reply_context_before_message():
    """普通对话：上下文在前，用户这句话在最后。"""
    ctx = ChatContext(user_id=1, group_id=1, msg_id=0, message="水")
    out = _compose_prompt("摘要\n我: 你平时用手机还是电脑\n用户(2): 对", ctx)
    assert out == "摘要\n我: 你平时用手机还是电脑\n用户(2): 对\n水"


def test_proactive_at_instruction_before_context():
    """主动 @（指令型）：指令在前，上下文只是语气素材。"""
    ctx = ChatContext(
        user_id=2, group_id=1, msg_id=0,
        message="说出那句确认的话",
        trigger="reply",
        intent="proactive_at",
    )
    out = _compose_prompt("摘要\n我: 你平时用手机还是电脑\n用户(2): 手机", ctx)
    assert out.startswith("说出那句确认的话")
    assert out.index("说出那句确认的话") < out.index("摘要")


def test_proactive_at_no_context_returns_instruction():
    """指令型且无上下文：直接返回指令。"""
    ctx = ChatContext(
        user_id=2, group_id=1, msg_id=0,
        message="说出那句确认的话",
        trigger="reply",
        intent="proactive_at",
    )
    assert _compose_prompt("", ctx) == "说出那句确认的话"


def test_normal_no_context_returns_message():
    """普通对话且无上下文：直接返回消息。"""
    ctx = ChatContext(user_id=1, group_id=1, msg_id=0, message="水")
    assert _compose_prompt("", ctx) == "水"
