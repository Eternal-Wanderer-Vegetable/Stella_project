# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""consolidation_prompt.py 的离线护栏：不触网、不调模型，只断言关键条款还在。

依据：2026-08-11 修复过度生成的核心是「memory_candidates 允许为空数组」+ 三条负例
+ confidence <0.7 弃掉。任何人改动模板删掉这些条款必须能立刻被发现；
`{{` 转义写错也会在 format 测试里变红。
"""

from memory.consolidation_prompt import (
    CONSOLIDATION_PROMPT,
    format_consolidation_prompt,
)


def test_empty_array_permission_present():
    """空输出许可是 2026-08-11 修复过度生成的核心，不得被移除。"""
    assert "memory_candidates 允许为空数组" in CONSOLIDATION_PROMPT
    assert "返回空数组是正确行为，不是失败" in CONSOLIDATION_PROMPT


def test_three_negative_examples_present():
    for tag in ("负例一", "负例二", "负例三"):
        assert tag in CONSOLIDATION_PROMPT


def test_confidence_floor_present():
    assert "<0.7 不要输出这条候选" in CONSOLIDATION_PROMPT


def test_format_fills_placeholders():
    out = format_consolidation_prompt("（无）", "消息ID(1) 用户(1001): 测试")
    assert "{messages}" not in out and "{types}" not in out
    assert "BOUNDARY_PROTECTION" in out
