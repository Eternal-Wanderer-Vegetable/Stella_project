# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""M1 新维度指标判别力测试：每个新指标都必须有「能变红」的构造性证明。

一个指标若在任何错误行为下都保持绿色，它就没有区分度、进不了质量门禁。
本文件对每个 M1 指标构造必失败用例（synthetic result / 临时数据集），
验证指标随错误行为变红。
"""

from __future__ import annotations

from types import SimpleNamespace

import memory.benchmark as benchmark


def _result(final_ids: list[str], behavior_ids: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        mode="CASUAL_REPLY",
        conversation_memories=[{"id": i, "_score": 0.9} for i in final_ids],
        behavior_constraints=[{"id": i, "_score": 0.9} for i in (behavior_ids or [])],
        trace={},
    )


def test_cross_scope_leak_metric_discriminates():
    """跨空间泄漏：外部空间记忆被激活 → 逐例 leak + 指标非零 + ok 变红。"""
    case = {
        "id": "xleak",
        "category": "scope-privacy",
        "scenario": {"group_id": 1, "user_id": 10},
        "input": "q",
        "memories": {
            "good": {"content": "本空间记忆"},
            "intruder": {"content": "外部空间记忆", "group_shared_space": 99},
        },
        "expected_memory": ["good"],
    }
    clean = benchmark.evaluate_retrieval_result(case, _result(["good"]))
    assert clean["cross_scope_leak"] == []
    assert clean["ok"] is True

    leaked = benchmark.evaluate_retrieval_result(case, _result(["good", "intruder"]))
    assert leaked["cross_scope_leak"] == ["intruder"]
    assert leaked["ok"] is False

    dims = benchmark._dimension_metrics([clean, leaked])
    assert dims["scope_privacy"]["out_of_scope_total"] == 2
    assert dims["scope_privacy"]["leaked"] == 1
    assert dims["scope_privacy"]["cross_scope_leak_rate"] == 50.0


def test_abstain_metric_discriminates():
    """abstain：expect_empty 用例召回任何内容 → over_recall + 指标变红。"""
    case = {
        "id": "abstain-x",
        "category": "abstain",
        "input": "q",
        "expect_empty": True,
        "memories": {},
        "expected_memory": [],
    }
    empty = benchmark.evaluate_retrieval_result(case, _result([]))
    assert empty["ok"] is True

    noisy = benchmark.evaluate_retrieval_result(case, _result(["noise"]))
    assert noisy["over_recall"] is True
    assert noisy["ok"] is False

    dims = benchmark._dimension_metrics([empty, noisy])
    assert dims["abstain"]["abstain_correct_rate"] == 50.0


def test_temporal_metric_discriminates():
    """temporal：类目内 ok 率随失败用例下降（期望新事实未召回即红）。"""
    ok_case = {
        "id": "t-ok", "category": "temporal", "input": "q",
        "memories": {}, "expected_memory": [],
    }
    bad_case = {
        "id": "t-bad", "category": "temporal", "input": "q",
        "memories": {}, "expected_memory": ["R_new"],
    }
    ok = benchmark.evaluate_retrieval_result(ok_case, _result([]))
    bad = benchmark.evaluate_retrieval_result(bad_case, _result(["R_old"]))
    assert ok["ok"] is True and bad["ok"] is False

    dims = benchmark._dimension_metrics([ok, bad])
    assert dims["temporal"]["cases_total"] == 2
    assert dims["temporal"]["temporal_accuracy"] == 50.0


def test_lineage_metric_discriminates(tmp_path):
    """血缘：expect_evidence 用例被激活的记忆缺少合法来源行 → lineage_missing 变红。

    走真实 evaluate_case 路径：用例声明 expect_evidence 但不写 evidence 行，
    记忆被召回后 claim_links 查无来源 → lineage_missing 非空。
    """
    case = {
        "id": "lineage-x",
        "category": "lineage",
        "scenario": {"group_id": 30, "user_id": 30},
        "input": "求推荐",
        "mode": "RECOMMEND",
        "memories": {
            "M1": {"content": "用户喜欢的美食是火锅", "type": "PREFERENCE",
                   "usage_tags": ["RECOMMEND"], "visibility": "OPEN"},
        },
        "expected_memory": ["M1"],
        "expect_evidence": True,  # 但 memories 没有声明 evidence 行
    }
    result = benchmark.evaluate_case(case, tmp_path, 0)
    assert result["final"] == ["M1"]  # 记忆本身可召回
    assert result["lineage_missing"] == ["M1"]
    assert result["ok"] is False

    # 反例（合法 evidence 行）→ 血缘绿
    case_ok = dict(case, id="lineage-ok")
    case_ok["memories"] = {
        "M1": dict(case["memories"]["M1"],
                   evidence=[{"fact_key": "favorite_food", "source_row_id": 7}]),
    }
    result_ok = benchmark.evaluate_case(case_ok, tmp_path, 1)
    assert result_ok["lineage_missing"] == []
    assert result_ok["ok"] is True

    dims = benchmark._dimension_metrics([result, result_ok])
    assert dims["lineage"]["lineage_completeness"] == 50.0


def test_superseded_status_excluded_from_candidates(tmp_path):
    """status=superseded 的记忆行不得进入候选（SQL active 过滤）。"""
    case = {
        "id": "sup-x",
        "scenario": {"group_id": 31, "user_id": 31},
        "input": "现在喝几分糖",
        "mode": "CASUAL_REPLY",
        "memories": {
            "V_new": {"content": "现在只喝三分糖", "type": "PREFERENCE",
                      "usage_tags": ["TOPIC_CONTINUE"], "visibility": "OPEN",
                      "last_accessed_at_offset_minutes": -60},
            "V_old": {"content": "以前只喝全糖", "type": "PREFERENCE",
                      "usage_tags": ["TOPIC_CONTINUE"], "visibility": "OPEN",
                      "status": "superseded",
                      "last_accessed_at_offset_minutes": -60},
        },
        "expected_memory": ["V_new"],
        "forbidden_memory": ["V_old"],
    }
    result = benchmark.evaluate_case(case, tmp_path, 0)
    assert result["final"] == ["V_new"]
    assert result["activated_forbidden"] == []


def test_offset_timestamp_resolution():
    """时间偏移字段按 CLOCK_ANCHOR 换算；绝对值字段优先级不受影响。"""
    from memory.benchmark import _resolve_memory_timestamp

    mem = {"last_accessed_at_offset_minutes": -60}
    assert _resolve_memory_timestamp(mem, "last_accessed_at", "d") == "2026-08-09 11:00:00"
    mem2 = {"last_accessed_at_offset_minutes": -86400}
    assert _resolve_memory_timestamp(mem2, "last_accessed_at", "d") == "2026-06-10 12:00:00"
    mem3 = {"last_accessed_at": "2020-01-01 00:00:00",
            "last_accessed_at_offset_minutes": -60}
    # 偏移字段更具体：与绝对值同现时偏移优先
    assert _resolve_memory_timestamp(mem3, "last_accessed_at", "d") == "2026-08-09 11:00:00"
    assert _resolve_memory_timestamp({}, "last_accessed_at", "d") == "d"
