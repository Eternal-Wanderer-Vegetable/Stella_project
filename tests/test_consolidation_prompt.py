# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""consolidation_prompt.py 的离线护栏：不触网、不调模型，只断言关键条款还在。


依据（2026-08-12 架构调整）：过滤分两层——捕获层宽（允许错误，留待验证），
晋升层严（Gate 1 三档 + 交叉验证 + 每用户配额）。因此 prompt 里不再做
置信度硬过滤与低价值排除，那属于晋升层的职责，且在 prompt 里过滤不可审计、
不留数据、无法改进。


本文件保护的是**防编造**条款——它们与松紧无关，任何情况下都不能删：
候选必须有出处、归属必须正确、不得推断。
"""
from memory.consolidation_prompt import (
    CONSOLIDATION_PROMPT,
    format_consolidation_prompt,
)


def test_no_fabrication_clauses_present():
    """防编造是捕获层放宽后唯一的底线，三条都不得移除。"""
    assert "不要补充推断" in CONSOLIDATION_PROMPT
    assert "需要推测才能得出结论" in CONSOLIDATION_PROMPT
    assert "严禁张冠李戴" in CONSOLIDATION_PROMPT
    assert "不要编造" in CONSOLIDATION_PROMPT


def test_attribution_clause_present():
    """归属正确性：user_id 必须是实际发送者（配合代码层的发送者白名单）。"""
    assert "user_id 必须是该消息实际的发送者" in CONSOLIDATION_PROMPT


def test_empty_array_permission_present():
    """「没有就是没有」：放宽捕获不等于强行产出，空数组仍是合法且正确的输出。"""
    assert "memory_candidates 允许为空数组" in CONSOLIDATION_PROMPT
    assert "返回空数组是正确行为，不是失败" in CONSOLIDATION_PROMPT


def test_describes_whom_criterion_present():
    """判据是「这句话在描述谁」，而不是列举具体案例（避免过拟合到少数示例）。"""
    assert "这句话在描述谁" in CONSOLIDATION_PROMPT


def test_no_hard_confidence_floor():
    """回归：低置信候选必须照常输出，由晋升闸门决定去留。


    2026-08-12 之前 prompt 里有「<0.7 不要输出这条候选」，导致低置信信息
    根本到不了 Gate 1——过滤发生在不可审计的一层。这条断言防止它被写回来。
    """
    assert "<0.7 不要输出这条候选" not in CONSOLIDATION_PROMPT
    assert "低置信就弃掉" not in CONSOLIDATION_PROMPT


def test_no_negative_example_blocks():
    """回归：三条负例已移除（它们挡的是低价值而非虚假，属于晋升层职责）。


    其中「讨论第三方事物」那条曾导致「我的显卡是 RTX5080」被判为讨论产品，
    实测 10 次运行仅 1 次命中。
    """
    for tag in ("负例一", "负例二", "负例三"):
        assert tag not in CONSOLIDATION_PROMPT


def test_format_fills_placeholders():
    out = format_consolidation_prompt("（无）", "消息ID(1) 用户(1001): 测试")
    assert "{messages}" not in out and "{types}" not in out
    assert "BOUNDARY_PROTECTION" in out
