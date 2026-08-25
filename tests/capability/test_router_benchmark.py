# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Router benchmark 与 provider 健康度退避的单测。

benchmark 的价值在于**四类错误分开计数**：合成单一准确率会把高代价错误
（记忆假阴、工具假阳）藏在平均值里，而它们恰恰是决定「能不能打开门控」的依据。
"""

import asyncio
import json

import pytest

from capability.registry import Capability, CapabilityProvider, CapabilityRegistry
from capability.router.benchmark import (
    BUILTIN_CASES,
    Case,
    load_cases,
    run,
)


def _run(coro):
    return asyncio.run(coro)


def _cap(cap_id: str, keywords: list[str]) -> Capability:
    return Capability(
        id=cap_id,
        description=f"{cap_id} 描述",
        examples=["示例"],
        keywords=keywords,
        providers=[
            CapabilityProvider(
                provider_id=f"{cap_id}#t", capability_id=cap_id, tool_name=f"{cap_id}_tool",
            ),
        ],
    )


# ---------- 内置用例集自洽 ----------


def test_builtin_cases_pass_rules_only():
    """内置用例集必须能被 Level 0 规则全部判对——它是规则表的回归护栏。

    跑 rules_only 不需要 embedding 服务，因此可以进 CI。
    """
    reg = CapabilityRegistry()
    reg.register(_cap("weather.query", ["天气"]))
    report = _run(run(list(BUILTIN_CASES), target=reg, rules_only=True))

    assert report.total == len(BUILTIN_CASES)
    assert report.memory_false_negative == []
    assert report.tool_false_positive == []
    assert report.memory_false_positive == []
    assert report.tool_false_negative == []


def test_builtin_cases_cover_the_known_traps():
    """陷阱用例是评审规则时最容易错的地方，必须一直留在集合里。"""
    messages = [c.message for c in BUILTIN_CASES]
    assert "你好，还记得我的旅行计划吗" in messages   # 整句匹配护栏
    assert "在吗，帮我查一下东京天气" in messages     # 寒暄 + 工具意图
    assert "我不会用这个软件" in messages             # 切词坏词护栏
    assert "这个游戏怎么样" in messages               # 停用词护栏


def test_gate_safe_requires_zero_memory_false_negative():
    """记忆假阴没有可接受的非零比例——它无声、且用户能直接感觉到人格断裂。"""
    reg = CapabilityRegistry()
    # 「在吗？」期望 memory=True，而规则会判 False → 制造一个假阴
    report = _run(run([Case("在吗？", memory=True, tool=False)], target=reg, rules_only=True))
    assert len(report.memory_false_negative) == 1
    assert report.gate_safe is False


def test_gate_safe_ignores_low_cost_errors():
    """工具假阴属低代价，不该阻塞门控决策。"""
    reg = CapabilityRegistry()
    report = _run(
        run([Case("今天心情不好", memory=True, tool=True)], target=reg, rules_only=True),
    )
    assert len(report.tool_false_negative) == 1
    assert report.gate_safe is True


def test_capability_miss_detected():
    reg = CapabilityRegistry()
    reg.register(_cap("weather.query", ["天气"]))
    report = _run(
        run(
            [Case("东京天气", memory=True, tool=True, capability="stock.price")],
            target=reg,
            rules_only=True,
        ),
    )
    assert len(report.capability_misses) == 1


def test_capability_not_checked_when_unspecified():
    reg = CapabilityRegistry()
    reg.register(_cap("weather.query", ["天气"]))
    report = _run(
        run([Case("东京天气", memory=True, tool=True)], target=reg, rules_only=True),
    )
    assert report.capability_misses == []


def test_by_level_counts_decisions():
    reg = CapabilityRegistry()
    report = _run(run([Case("在吗？", memory=False, tool=False)], target=reg, rules_only=True))
    assert report.by_level() == {"rule": 1}


def test_render_lists_high_cost_failures():
    reg = CapabilityRegistry()
    report = _run(run([Case("在吗？", memory=True, tool=False)], target=reg, rules_only=True))
    text = report.render()
    assert "记忆假阴" in text
    assert "不可以" in text
    assert "在吗？" in text


def test_render_on_clean_report():
    reg = CapabilityRegistry()
    report = _run(run([Case("在吗？", memory=False, tool=False)], target=reg, rules_only=True))
    text = report.render()
    assert "可以" in text
    assert "明细" not in text


# ---------- 用例载入 ----------


def test_load_cases_from_file(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            [
                {"message": "查天气", "memory": False, "tool": True, "capability": "weather.query"},
                {"message": "你好"},
                {"not_a_case": 1},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cases = load_cases(path)
    assert len(cases) == 2
    assert cases[0].capability == "weather.query"
    # 缺省值：memory=True（保守）、tool=False（保守）
    assert cases[1].memory is True
    assert cases[1].tool is False


def test_load_cases_rejects_non_array(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"message": "x"}', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 数组"):
        load_cases(path)


def test_load_cases_falls_back_to_builtin(monkeypatch, tmp_path):
    """没有外部用例文件时也要能跑一遍。"""
    import capability.router.benchmark as bm

    monkeypatch.setattr(bm, "CASES_DIR", tmp_path / "nope")
    assert load_cases() == list(BUILTIN_CASES)


def test_load_cases_merges_builtin_with_files(monkeypatch, tmp_path):
    """回归：加一个领域用例文件不能把内置集（规则表的回归地板）静默撤掉。

    合并前的写法是「有外部文件就只用外部文件」，于是新增 acg.json 之后
    记忆信号、寒暄整句匹配、切词坏词这些护栏就再也不被检查了——benchmark 依然
    通过，但已经不测规则表。
    """
    import capability.router.benchmark as bm

    (tmp_path / "domain.json").write_text(
        json.dumps([{"message": "领域用例", "tool": True}], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(bm, "CASES_DIR", tmp_path)
    messages = [c.message for c in load_cases()]
    assert "领域用例" in messages
    for builtin in BUILTIN_CASES:
        assert builtin.message in messages


def test_explicit_path_does_not_merge_builtin(tmp_path):
    """显式 --cases 时调用方明确只想跑自己那一组。"""
    path = tmp_path / "only.json"
    path.write_text(
        json.dumps([{"message": "只有我"}], ensure_ascii=False), encoding="utf-8",
    )
    assert [c.message for c in load_cases(path)] == ["只有我"]


def test_shipped_acg_cases_are_wellformed():
    """随仓库发的用例文件必须能被解析，且期望命中的能力 id 要真的在声明里。

    对不上的话 benchmark 会一直报「能力选错」，而人会以为是路由变差了。
    """
    from pathlib import Path

    import capability.router.benchmark as bm
    from capability.loader import load_capability_file

    path = bm.CASES_DIR / "acg.json"
    if not path.is_file():
        pytest.skip("本部署没有 acg.json")
    cases = load_cases(path)
    assert cases

    reg = CapabilityRegistry()
    decl_dir = Path(__file__).resolve().parents[2] / "config" / "capabilities"
    for toml in sorted(decl_dir.glob("*.toml")):
        load_capability_file(toml, reg)
    declared = set(reg.ids())
    for case in cases:
        if case.capability:
            assert case.capability in declared, f"{case.message!r} 期望的能力未声明"


# ---------- Provider 健康度退避 ----------


def test_provider_available_by_default():
    p = CapabilityProvider(provider_id="p", capability_id="c", tool_name="t")
    assert p.available() is True


def test_manual_disable_beats_health():
    p = CapabilityProvider(provider_id="p", capability_id="c", tool_name="t", enabled=False)
    p.mark_success()
    assert p.available() is False


def test_backoff_triggers_at_threshold():
    p = CapabilityProvider(provider_id="p", capability_id="c", tool_name="t")
    assert p.mark_failure(3, 600.0, now=1000.0) is False
    assert p.mark_failure(3, 600.0, now=1000.0) is False
    assert p.available(now=1000.0) is True
    assert p.mark_failure(3, 600.0, now=1000.0) is True
    assert p.available(now=1000.0) is False


def test_backoff_is_a_time_window_not_permanent():
    """外部 API 抖动是常态；永久禁用会让一次网络波动永久关掉一个能力。"""
    p = CapabilityProvider(provider_id="p", capability_id="c", tool_name="t")
    for _ in range(3):
        p.mark_failure(3, 600.0, now=1000.0)
    assert p.available(now=1500.0) is False
    assert p.available(now=1600.0) is True


def test_success_clears_failures_and_backoff():
    """一次成功说明服务恢复了，没理由继续记着之前的失败。"""
    p = CapabilityProvider(provider_id="p", capability_id="c", tool_name="t")
    for _ in range(3):
        p.mark_failure(3, 600.0, now=1000.0)
    p.mark_success()
    assert p.failures == 0
    assert p.available(now=1000.0) is True


def test_threshold_zero_disables_backoff():
    p = CapabilityProvider(provider_id="p", capability_id="c", tool_name="t")
    for _ in range(10):
        assert p.mark_failure(0, 600.0, now=1000.0) is False
    # 计数仍在累积（供诊断），但不退避
    assert p.failures == 10
    assert p.available(now=1000.0) is True


def test_backed_off_provider_excluded_from_selection():
    good = CapabilityProvider(provider_id="good", capability_id="c", tool_name="g", priority=1)
    bad = CapabilityProvider(provider_id="bad", capability_id="c", tool_name="b", priority=9)
    for _ in range(3):
        bad.mark_failure(3, 600.0)
    cap = Capability(id="c", providers=[bad, good])
    # 尽管 bad 的 priority 更高，退避期内应选 good
    assert [p.provider_id for p in cap.enabled_providers()] == ["good"]


def test_repr_shows_backoff_state():
    p = CapabilityProvider(provider_id="p", capability_id="c", tool_name="t")
    for _ in range(3):
        p.mark_failure(3, 600.0)
    assert "backoff" in repr(p)
