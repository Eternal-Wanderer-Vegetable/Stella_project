# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""会话压缩状态的行为基线。

核心不变量：摘要覆盖范围严格早于尾巴。区间计算错一位就会造成同一段对话
出现两个版本，模型接错话题（2026-08-13 缺陷）。
"""
import pytest

from memory import session_context as sc


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sc.reset_state()
    monkeypatch.setattr(sc, "SESSION_CONTEXT_ENABLED", True)
    yield
    sc.reset_state()


def test_uninitialized_has_no_pending():
    """未初始化时不产生待压缩区间——否则会把全部历史当成待压缩内容。"""
    assert sc.pending_bounds(1, 100) is None


def test_initialize_aligns_to_tail_start():
    sc.ensure_initialized(1, 100)
    assert sc.session_stats(1)["summarized_up_to_id"] == 100
    # 尾巴起点未前进 → 无待压缩
    assert sc.pending_bounds(1, 100) is None


def test_initialize_is_idempotent():
    sc.ensure_initialized(1, 100)
    sc.ensure_initialized(1, 200)
    assert sc.session_stats(1)["summarized_up_to_id"] == 100


def test_pending_bounds_excludes_both_ends():
    """区间左开右开：不重复压缩已压缩的，也不与尾巴重叠。"""
    sc.ensure_initialized(1, 100)
    assert sc.pending_bounds(1, 101) is None      # 相邻，无中间消息
    assert sc.pending_bounds(1, 102) == (100, 102)
    assert sc.pending_bounds(1, 150) == (100, 150)


def test_apply_summary_advances_position():
    sc.ensure_initialized(1, 100)
    sc.apply_summary(1, "聊了显卡选购", up_to_id=140, message_count=30)
    stats = sc.session_stats(1)
    assert stats["summarized_up_to_id"] == 140
    assert stats["compact_count"] == 1
    assert stats["compacted_messages"] == 30
    assert sc.get_summary(1) == "聊了显卡选购"
    # 推进后原区间不再待压缩
    assert sc.pending_bounds(1, 140) is None


def test_empty_summary_does_not_advance():
    """压缩产出为空时保留区间待重试，不得静默跳过这批消息。"""
    sc.ensure_initialized(1, 100)
    sc.apply_summary(1, "   ", up_to_id=140)
    assert sc.session_stats(1)["summarized_up_to_id"] == 100
    assert sc.pending_bounds(1, 140) == (100, 140)


def test_position_never_goes_backwards():
    sc.ensure_initialized(1, 100)
    sc.apply_summary(1, "第一段", up_to_id=200)
    sc.apply_summary(1, "第二段", up_to_id=150)
    assert sc.session_stats(1)["summarized_up_to_id"] == 200


def test_should_compact_by_token_threshold(monkeypatch):
    monkeypatch.setattr(sc, "SESSION_COMPACT_THRESHOLD_TOKENS", 20)
    assert not sc.should_compact("")
    assert not sc.should_compact("短")
    assert sc.should_compact("这是一段足够长的中文文本" * 5)


def test_idle_detection_and_end():
    sc.touch(1)
    assert not sc.is_idle(1, timeout=999.0)
    assert sc.is_idle(1, timeout=0.0)
    assert 1 in sc.idle_groups(timeout=0.0)


def test_end_session_reports_only_real_sessions():
    """只有压缩过或有摘要的会话才算「进行中」，避免静默群反复报告结束。"""
    sc.touch(1)
    assert sc.end_session(1) is False        # 有状态但无内容
    assert sc.end_session(999) is False      # 无状态

    sc.ensure_initialized(2, 100)
    sc.apply_summary(2, "有内容", up_to_id=140)
    assert sc.end_session(2) is True
    assert sc.session_stats(2)["active"] is False


def test_sessions_are_per_group():
    sc.ensure_initialized(1, 100)
    sc.ensure_initialized(2, 500)
    sc.apply_summary(1, "群一的摘要", up_to_id=140)
    assert sc.get_summary(1) == "群一的摘要"
    assert sc.get_summary(2) == ""


def test_skip_range_advances_keeps_summary():
    """模型判定无可摘要内容 → 推进位置但保留原摘要。"""
    sc.ensure_initialized(1, 100)
    sc.apply_summary(1, "先前的摘要", up_to_id=100)
    sc.skip_range(1, up_to_id=140, message_count=30)
    assert sc.get_summary(1) == "先前的摘要"
    assert sc.session_stats(1)["summarized_up_to_id"] == 140


def test_skip_range_does_not_bump_compact_count():
    """跳过不算一次压缩：compact_count 只在真正产出摘要时递增。"""
    sc.ensure_initialized(1, 100)
    sc.apply_summary(1, "第一段", up_to_id=140)
    sc.skip_range(1, up_to_id=200, message_count=20)
    stats = sc.session_stats(1)
    assert stats["compact_count"] == 1
    assert stats["compacted_messages"] == 20


def test_disabled_switch_short_circuits(monkeypatch):
    monkeypatch.setattr(sc, "SESSION_CONTEXT_ENABLED", False)
    sc.touch(1)
    sc.ensure_initialized(1, 100)
    assert sc.pending_bounds(1, 200) is None
    assert sc.get_summary(1) == ""
    assert not sc.should_compact("很长的文本" * 100)
    assert sc.idle_groups(timeout=0.0) == []
