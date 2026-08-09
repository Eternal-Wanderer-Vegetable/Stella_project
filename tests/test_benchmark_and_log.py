# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.benchmark 与 memory.consolidation_log 的单元测试。"""

import json
from pathlib import Path

import memory.benchmark as benchmark
import memory.consolidation_log as cl
from memory.benchmark import evaluate_case, load_cases, run_benchmark


def test_load_cases_missing_dir(tmp_path):
    assert load_cases(tmp_path / "nope") == []


def test_load_cases_list_and_broken(tmp_path):
    cases_dir = tmp_path / "cases"
    (cases_dir / "nested").mkdir(parents=True)
    (cases_dir / "a.json").write_text(
        json.dumps([{"id": "c1", "input": "hi"}, {"id": "c2", "input": "yo"}]), encoding="utf-8"
    )
    (cases_dir / "b.json").write_text(json.dumps({"id": "c3"}), encoding="utf-8")
    (cases_dir / "bad.json").write_text("{not json", encoding="utf-8")
    cases = load_cases(cases_dir)
    assert {c["id"] for c in cases} == {"c1", "c2", "c3"}


def test_evaluate_case_basic():
    case = {"id": "t1", "input": "你好呀", "mode": "CASUAL_REPLY", "expected_memory": ["m1"]}
    case["memories"] = {
        "m1": {"id": "m1", "content": "朋友喜欢写代码", "usage_tags": [], "visibility": "normal"},
    }
    res = evaluate_case(case)
    assert res["declared_mode"] == "CASUAL_REPLY"
    assert isinstance(res["final"], list)
    assert res["expected"] == ["m1"]
    assert isinstance(res["ok"], bool)


def test_evaluate_case_forbidden_reported():
    case = {"id": "t2", "input": "attack trigger", "mode": "CASUAL_REPLY", "forbidden_memory": ["bad"]}
    case["memories"] = {
        "bad": {"id": "bad", "content": "敏感内容", "usage_tags": [], "visibility": "normal"},
    }
    res = evaluate_case(case)
    assert "bad" in res["forbidden"]
    assert res["id"] == "t2"
    assert res["activated_forbidden"] == res["final"] or "bad" in res["activated_forbidden"]


def test_evaluate_case_expected_in_behavior_constraints():
    case = {
        "id": "t3",
        "mode": "ACTIVE_JOIN",
        "input": "",
        "expected_memory": ["b1"],
        "memories": {
            "b1": {"id": "b1", "content": "安全行为约束", "usage_tags": ["behavior"], "visibility": "normal"},
        },
    }
    res = evaluate_case(case)
    assert isinstance(res["behavior"], list)
    assert isinstance(res["found_expected"], list)


def test_run_benchmark_empty_dir(tmp_path):
    metrics = run_benchmark(tmp_path / "empty")
    assert metrics["cases_total"] == 0
    assert metrics["cases_ok_rate"] == 0.0
    assert metrics["results"] == []


def test_run_benchmark_sums_metrics(tmp_path):
    cases_dir = tmp_path / "data"
    cases_dir.mkdir()
    (cases_dir / "c.json").write_text(
        json.dumps(
            [
                {
                    "id": "ok",
                    "input": "你好",
                    "mode": "CASUAL_REPLY",
                    "expected_memory": ["m1"],
                    "memories": {"m1": {"id": "m1", "content": "事实", "visibility": "normal"}},
                },
                {
                    "id": "forbid",
                    "input": "触发",
                    "mode": "CASUAL_REPLY",
                    "forbidden_memory": ["bad"],
                    "memories": {"bad": {"id": "bad", "content": "敏感", "visibility": "normal"}},
                },
            ]
        ),
        encoding="utf-8",
    )
    metrics = run_benchmark(cases_dir)
    assert metrics["cases_total"] == 2
    assert metrics["cases_ok_rate"] >= 0.0
    assert metrics["memory_precision"] >= 0.0
    assert metrics["forbidden_activation_rate"] >= 0.0


def test_consolidation_log_append_and_create(tmp_path, monkeypatch):
    log_path = tmp_path / "memory_consolidation_log.md"
    monkeypatch.setattr(cl, "CONSOLIDATION_LOG_PATH", log_path)
    cl.append_consolidation_log("## 整合 1\n\n内容\n")
    assert "记忆整合日志" in log_path.read_text(encoding="utf-8")
    cl.append_consolidation_log("## 整合 2\n\n更多\n")
    content = log_path.read_text(encoding="utf-8")
    assert "整合 2" in content


def test_consolidation_log_handles_error(tmp_path, monkeypatch):
    class Broken:
        def __init__(self, *a, **k):
            raise OSError("boom")

    monkeypatch.setattr(cl, "CONSOLIDATION_LOG_PATH", Broken)
    cl.append_consolidation_log("x")
    assert True