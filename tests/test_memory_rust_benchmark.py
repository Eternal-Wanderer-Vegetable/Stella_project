from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import memory_rust.benchmark as benchmark
from memory_rust.backend import BackendUnavailable


def _case() -> dict:
    return {
        "id": "rust-case",
        "input": "推荐游戏",
        "mode": "RECOMMEND",
        "expected_memory": ["m1"],
        "memories": {
            "m1": {
                "content": "用户喜欢合作游戏",
                "type": "PREFERENCE",
                "usage_tags": ["RECOMMEND"],
            }
        },
    }


class _FakeRustBackend:
    name = "rust"

    def retrieve(self, request):
        with sqlite3.connect(request.db_path) as conn:
            assert conn.execute(
                "SELECT version FROM schema_meta WHERE k = 'version'"
            ).fetchone() == (14,)
        return SimpleNamespace(
            mode=request.mode,
            conversation_memories=[
                {"id": "m1", "_score": 0.9, "_score_parts": {"sem": 0.9}}
            ],
            behavior_constraints=[],
            trace={"ranked_all": [{"id": "m1", "score": 0.9, "parts": {}}]},
        )


def test_run_backend_case_writes_native_schema_marker(tmp_path):
    result = benchmark._run_backend_case(
        "rust",
        _FakeRustBackend(),
        _case(),
        tmp_path,
        0,
    )

    assert result["ok"] is True
    assert result["ordered_final"] == ["m1"]
    assert result["backend"] == "rust"


def test_run_rust_benchmark_reports_native_unavailable(monkeypatch, tmp_path):
    def missing(mode):
        raise BackendUnavailable("native extension missing")

    monkeypatch.setattr(benchmark, "get_backend", missing)

    with pytest.raises(benchmark.RustBenchmarkError, match="native extension missing"):
        benchmark.run_rust_benchmark(tmp_path)


def test_main_writes_explicit_error_json(monkeypatch, tmp_path):
    def missing(mode):
        raise BackendUnavailable("native extension missing")

    monkeypatch.setattr(benchmark, "get_backend", missing)
    report = tmp_path / "rust.json"

    assert benchmark.main(["--dir", str(tmp_path), "--json", str(report)]) == 1
    assert report.read_text(encoding="utf-8").startswith('{\n  "backend": "rust"')


def test_aggregate_results_matches_python_metric_shape():
    result = benchmark.evaluate_retrieval_result(
        _case(),
        SimpleNamespace(
            mode="RECOMMEND",
            conversation_memories=[{"id": "m1", "_score": 0.9}],
            behavior_constraints=[],
            trace={"ranked_all": [{"id": "m1", "score": 0.9}]},
        ),
    )

    metrics = benchmark._aggregate_results([result])

    assert metrics["cases_total"] == 1
    assert metrics["cases_ok"] == 1
    assert metrics["memory_recall"] == 100.0
    assert metrics["forbidden_activation_rate"] == 0.0


def _evaluated_result(
    *,
    final: list[str],
    behavior: list[str] | None = None,
    mode: str = "RECOMMEND",
    scores: dict[str, float] | None = None,
    ranked_all: dict[str, dict] | None = None,
) -> dict:
    return {
        "id": "parity-case",
        "ordered_final": final,
        "ordered_behavior": behavior or [],
        "detected_mode": mode,
        "scores": scores or {},
        "ranked_all": ranked_all or {},
    }


def test_compare_separates_hard_and_diagnostic_mismatches():
    python_result = _evaluated_result(
        final=["m1"],
        scores={"m1": 0.9},
        ranked_all={"m1": {"score": 0.9}},
    )
    rust_result = _evaluated_result(
        final=["m2"],
        scores={"m1": 0.901},
        ranked_all={"m1": {"score": 0.901}},
    )

    report = benchmark._compare_case_results(python_result, rust_result)

    assert report["hard_mismatches"] == ["conversation_order"]
    assert report["diagnostic_mismatches"] == []
    assert report["max_score_delta"] == 0.001


def test_compare_report_marks_trace_only_difference_as_diagnostic():
    python_metrics = {
        "backend": "python",
        "cases_ok": 1,
        "cases_total": 1,
        "results": [
            _evaluated_result(
                final=["m1"],
                scores={"m1": 0.9},
                ranked_all={"m1": {"score": 0.9, "cut": False}},
            )
        ],
    }
    rust_metrics = {
        "backend": "rust",
        "cases_ok": 1,
        "cases_total": 1,
        "results": [
            _evaluated_result(
                final=["m1"],
                scores={"m1": 0.9},
                ranked_all={"m1": {"score": 0.9}},
            )
        ],
    }

    report = benchmark._build_compare_report(python_metrics, rust_metrics)

    assert report["cases_mismatch"] == 0
    assert report["diagnostic_mismatch_cases"] == []


def test_percentile_summary_uses_interpolated_p50_and_p95():
    summary = benchmark._performance_summary(
        [1.0, 2.0, 3.0, 4.0, 5.0],
        warmup=2,
        iterations=5,
        errors=0,
    )

    assert summary["p50_ms"] == 3.0
    assert summary["p95_ms"] == 4.8
    assert summary["min_ms"] == 1.0
    assert summary["max_ms"] == 5.0
    assert summary["throughput_per_second"] == 333.333


def test_performance_suite_counts_runtime_errors_and_keeps_successes(tmp_path):
    calls = 0

    class _FlakyBackend:
        name = "fake"

        def retrieve(self, request):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("transient")
            return SimpleNamespace(
                mode=request.mode,
                conversation_memories=[],
                behavior_constraints=[],
                trace={},
            )

    report = benchmark._run_performance_suite(
        "fake",
        _FlakyBackend(),
        [_case()],
        embedding_fixture=None,
        work_dir=tmp_path,
        warmup=1,
        iterations=2,
        clock=iter([0.0, 0.001, 0.002, 0.005]).__next__,
    )

    assert report["samples"] == 1
    assert report["errors"] == 1
    assert report["cases"][0]["errors"] == 1
