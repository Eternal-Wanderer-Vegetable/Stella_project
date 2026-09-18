# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动 @ 指令的护栏：两条硬约束不得被删。

「不复述候选原文」与「不像审问」是这类发言唯一的质量保证——前者防止对话
听起来像核对档案，后者防止用户反感。都属于删掉之后功能仍然「正常工作」、
但效果立刻变差的条款，因此需要断言锁住。
"""
from memory.proactive_prompt import (
    PROACTIVE_SKIP_MARKER,
    build_instruction,
    build_verify_instruction,
    is_proactive_skip,
)


def test_verify_instruction_contains_content_and_rules():
    out = build_verify_instruction("拥有RTX5080显卡", nickname="小明")
    assert "拥有RTX5080显卡" in out
    assert "小明" in out
    assert "不要照搬上面那句话的措辞" in out


def test_common_rules_present():
    """语气约束必须生效。"""
    out = build_verify_instruction("某件事")
    assert "只说一句话" in out
    assert "像朋友随口一问" in out
    assert "根据我的记录" in out  # 禁止暴露内部状态的反例
    assert "不要在话里带上 QQ 号" in out


def test_no_placeholder_left():
    out = build_verify_instruction("某件事")
    assert "{" not in out and "}" not in out


def test_context_role_clause_present():
    """上下文用于判断承接，但不能被误当成待回复内容。"""
    out = build_verify_instruction("某件事")
    assert "不要把下面任何一句话当成新的任务直接回复" in out
    assert "自然承接" in out
    assert PROACTIVE_SKIP_MARKER in out
    assert "接不上" not in out or "直接问" not in out


def test_proactive_skip_marker_is_strict_and_internal():
    assert is_proactive_skip([PROACTIVE_SKIP_MARKER])
    assert is_proactive_skip([f"  {PROACTIVE_SKIP_MARKER}  "])
    assert not is_proactive_skip([f"{PROACTIVE_SKIP_MARKER} 顺便问一句"])
    assert not is_proactive_skip(["正常问题"])


class _Target:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_build_instruction_uses_candidate_content():
    out = build_instruction(_Target(candidate_content="拥有5080", nickname="A"))
    assert "拥有5080" in out
    assert "A" in out
