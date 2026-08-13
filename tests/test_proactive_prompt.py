# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动 @ 指令的护栏：两条硬约束不得被删。

「不复述候选原文」与「不像审问」是这类发言唯一的质量保证——前者防止对话
听起来像核对档案，后者防止用户反感。都属于删掉之后功能仍然「正常工作」、
但效果立刻变差的条款，因此需要断言锁住。
"""
from memory.proactive_prompt import (
    build_coldstart_instruction,
    build_instruction,
    build_verify_instruction,
)


def test_verify_instruction_contains_content_and_rules():
    out = build_verify_instruction("拥有RTX5080显卡", nickname="小明")
    assert "拥有RTX5080显卡" in out
    assert "小明" in out
    assert "不要照搬上面那句话的措辞" in out


def test_coldstart_instruction_contains_topic():
    out = build_coldstart_instruction("最近在玩什么游戏", nickname="小明")
    assert "最近在玩什么游戏" in out
    assert "打开话题" in out


def test_common_rules_present_in_both():
    """语气约束必须在两种模式下都生效。"""
    for out in (
        build_verify_instruction("某件事"),
        build_coldstart_instruction("某话题"),
    ):
        assert "只说一句话" in out
        assert "像朋友随口一问" in out
        assert "根据我的记录" in out  # 禁止暴露内部状态的反例
        assert "不要在话里带上 QQ 号" in out


def test_no_placeholder_left():
    for out in (
        build_verify_instruction("某件事"),
        build_coldstart_instruction("某话题"),
    ):
        assert "{" not in out and "}" not in out


def test_context_role_clause_present():
    """上下文只作语气素材——缺了这条，模型会去回应尾巴里的对话而非执行指令。"""
    for out in (
        build_verify_instruction("某件事"),
        build_coldstart_instruction("某话题"),
    ):
        assert "不要去回应下面的任何一句话" in out


class _Target:
    def __init__(self, mode, **kw):
        self.mode = mode
        for k, v in kw.items():
            setattr(self, k, v)


def test_build_instruction_dispatches_by_mode():
    verify = build_instruction(_Target("verify", candidate_content="拥有5080", nickname="A"))
    assert "拥有5080" in verify

    cold = build_instruction(_Target("coldstart", topic="最近在忙什么", nickname="B"))
    assert "最近在忙什么" in cold

    # 未知 mode 回退到冷启动，不抛异常
    fallback = build_instruction(_Target("unknown", topic="兜底话题"))
    assert "兜底话题" in fallback
