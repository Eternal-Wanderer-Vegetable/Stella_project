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
