# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Result.data → Result.summary 压缩的单测。

纯逻辑、完全离线。重点：**失败与「无返回值」的条目不进摘要**——
Stella 不该向用户解释某个工具报了什么错，那是运维信息不是聊天素材。
"""

from capability.comes.summarizer import (
    from_tool_outputs,
    is_error,
    is_no_return,
    stringify,
    summarize,
    truncate,
)

NO_RETURN = "The tool has no return value, or has sent the result directly to the user."


# ---------- 判定 ----------


def test_is_error_matches_execute_tool_prefix():
    """execute_tool 失败时返回 "error: ..."（见 astrbot_compat/llm/agent.py）。"""
    assert is_error("error: boom")
    assert is_error("ERROR: tool x timed out after 60s")
    assert not is_error("东京 27℃")
    assert not is_error("")


def test_is_no_return_matches_internal_marker():
    """这是给模型看的内部占位，对 Stella 毫无意义。"""
    assert is_no_return(NO_RETURN)
    assert not is_no_return("东京 27℃")


# ---------- 截断 ----------


def test_truncate_adds_ellipsis_only_when_needed():
    assert truncate("abcdef", 10) == "abcdef"
    assert truncate("abcdef", 3) == "abc…"
    assert truncate("  abcdef  ", 10) == "abcdef"


def test_truncate_unlimited_when_limit_non_positive():
    assert truncate("abcdef", 0) == "abcdef"
    assert truncate("abcdef", -1) == "abcdef"


# ---------- 从工具输出拼摘要 ----------


def test_single_output_has_no_tool_name_prefix():
    """「东京27℃」比「get_weather: 东京27℃」自然——Stella 根本不知道有哪些工具。"""
    assert from_tool_outputs([("get_weather", "东京 27℃")], 100) == "东京 27℃"


def test_multiple_outputs_are_listed():
    out = from_tool_outputs([("a", "结果一"), ("b", "结果二")], 100)
    assert out == "- 结果一\n- 结果二" or out == "结果一\n结果二"
    assert "结果一" in out and "结果二" in out


def test_errors_and_no_return_are_dropped():
    outputs = [("a", "error: boom"), ("b", NO_RETURN), ("c", "真实结果")]
    assert from_tool_outputs(outputs, 100) == "真实结果"


def test_all_unusable_returns_empty():
    assert from_tool_outputs([("a", "error: x"), ("b", NO_RETURN)], 100) == ""
    assert from_tool_outputs([], 100) == ""


def test_budget_is_split_across_multiple_outputs():
    """回归：第一个工具的长输出不该吃掉全部额度。"""
    long_a = "甲" * 500
    long_b = "乙" * 500
    out = from_tool_outputs([("a", long_a), ("b", long_b)], 200)
    assert "乙" in out
    assert len(out) <= 210  # 总预算 + 少量分隔符/省略号


# ---------- 总入口 ----------


def test_completion_text_wins_when_present():
    """受限 agent 的结论已经读过工具输出，优先用它——且不再调模型压缩。"""
    assert summarize("东京明天 27℃，晴。", [("w", '{"temp": 27}')], 100) == "东京明天 27℃，晴。"


def test_falls_back_to_outputs_when_completion_empty():
    assert summarize("", [("w", "东京 27℃")], 100) == "东京 27℃"


def test_completion_echoing_internal_marker_is_ignored():
    """agent 有时把内部占位原样复述出来，那等于没有结论。"""
    assert summarize(NO_RETURN, [("w", "东京 27℃")], 100) == "东京 27℃"


def test_completion_is_truncated_to_budget():
    assert summarize("啊" * 500, [], 50) == "啊" * 50 + "…"


def test_everything_empty_returns_empty():
    assert summarize("", [], 100) == ""


def test_stringify_handles_non_strings():
    assert stringify(None) == ""
    assert stringify("x") == "x"
    assert stringify({"a": 1}) == "{'a': 1}"
