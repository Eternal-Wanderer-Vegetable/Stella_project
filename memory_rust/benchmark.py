# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Benchmark runner for the strict Rust memory retrieval backend.

The runner deliberately uses the existing ``memory/benchmark`` cases and
keeps the Python benchmark entrypoint independent.  Native loading and runtime
errors are fatal: a fallback result is never counted as a Rust pass.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from config import (
    LONG_TERM_RELEVANCE_CANDIDATE_LIMIT,
    MEMORY_BENCHMARK_DIR,
)
from memory.benchmark import (
    evaluate_retrieval_result,
    fixture_semantic_scores,
    load_cases,
    load_embedding_fixture,
    write_case_db,
)
from memory.policy import detect_mode, mode_limit, normalize_mode
from memory_rust.backend import RetrievalRequest
from memory_rust.python_backend import PythonMemoryBackend
from memory_rust.selector import get_backend


SCORE_TOLERANCE = 1e-3


class RustBenchmarkError(RuntimeError):
    """Raised when the strict Rust benchmark cannot produce a valid result."""


def _case_request(
    case: dict[str, Any],
    db_path: Path,
    semantic_scores: dict[str, float] | None,
) -> tuple[RetrievalRequest, int, int]:
    scenario = case.get("scenario") or {}
    try:
        group_id = int(scenario.get("group_id", 1))
    except (TypeError, ValueError):
        group_id = 1
    try:
        user_id = int(scenario.get("user_id", 0))
    except (TypeError, ValueError):
        user_id = 0

    query = case.get("input") or ""
    trigger = case.get(
        "trigger",
        "proactive" if case.get("mode") == "ACTIVE_JOIN" else "reply",
    )
    resolved_mode = normalize_mode(detect_mode(query, trigger=trigger))
    request = RetrievalRequest(
        db_path=db_path,
        group_shared_space=str(group_id),
        user_id=user_id,
        query=query,
        trigger=trigger,
        mode=resolved_mode,
        pool_limit=max(
            LONG_TERM_RELEVANCE_CANDIDATE_LIMIT,
            mode_limit(resolved_mode) * 5,
        ),
        semantic_scores=semantic_scores or {},
    )
    return request, group_id, user_id


def _prepare_python_runtime(db_path: Path) -> tuple[Any, Any, Any]:
    import memory.retrieval_v2 as retrieval_v2

    old_state = (
        retrieval_v2.DB_PATH,
        retrieval_v2.MEMORY_V2_ENABLED,
        retrieval_v2.RAG_ENABLED,
    )
    retrieval_v2.DB_PATH = db_path
    retrieval_v2.MEMORY_V2_ENABLED = True
    retrieval_v2.RAG_ENABLED = False
    retrieval_v2._CACHE.clear()
    return retrieval_v2, old_state[0], old_state[1], old_state[2]


def _restore_python_runtime(
    retrieval_v2: Any,
    old_db: Any,
    old_v2: Any,
    old_rag: Any,
) -> None:
    retrieval_v2.DB_PATH = old_db
    retrieval_v2.MEMORY_V2_ENABLED = old_v2
    retrieval_v2.RAG_ENABLED = old_rag
    retrieval_v2._CACHE.clear()


def _run_backend_case(
    backend_name: str,
    backend: Any,
    case: dict[str, Any],
    work_dir: Path,
    seq: int,
    embedding_fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    semantic_scores = (
        fixture_semantic_scores(case, embedding_fixture)
        if embedding_fixture is not None
        else None
    )
    db_path = work_dir / f"{backend_name}_{seq}_{case.get('id', 'case')}.db"
    write_case_db(db_path, case, with_schema_meta=backend_name == "rust")
    request, _, _ = _case_request(case, db_path, semantic_scores)

    retrieval_v2 = None
    old_state: tuple[Any, Any, Any] | None = None
    try:
        if backend_name == "python":
            retrieval_v2, old_db, old_v2, old_rag = _prepare_python_runtime(db_path)
            old_state = (old_db, old_v2, old_rag)
        result = backend.retrieve(request)
    except Exception as exc:
        raise RustBenchmarkError(
            f"{backend_name} retrieval failed for case "
            f"{case.get('id', '?')}: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if retrieval_v2 is not None and old_state is not None:
            _restore_python_runtime(retrieval_v2, *old_state)

    evaluated = evaluate_retrieval_result(case, result)
    evaluated["backend"] = backend_name
    evaluated["ordered_final"] = [
        str(memory.get("id")) for memory in result.conversation_memories
    ]
    evaluated["ordered_behavior"] = [
        str(memory.get("id")) for memory in result.behavior_constraints
    ]
    evaluated["detected_mode"] = result.mode or evaluated["detected_mode"]
    return evaluated


def _aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    ok_count = sum(1 for result in results if result["ok"])
    cases_with_expected = sum(1 for result in results if result["expected"])
    total_expected = sum(
        len(result["expected"]) + len(result["expected_behavior"])
        for result in results
    )
    total_expected_behavior = sum(
        len(result["expected_behavior"]) for result in results
    )
    total_found_expected = sum(
        len(result["found_expected"]) + len(result["found_behavior"])
        for result in results
    )
    total_retrieved = sum(
        len(result["final"]) + len(result["behavior"]) for result in results
    )
    total_behavior_leaked = sum(
        len(result["behavior_leaked"]) for result in results
    )
    total_forbidden = sum(len(result["forbidden"]) for result in results)
    total_activated_forbidden = sum(
        len(result["activated_forbidden"]) for result in results
    )
    mode_correct = sum(
        1 for result in results
        if result["declared_mode"] == result["detected_mode"]
    )
    precision_pct = round(
        total_found_expected / max(1, total_retrieved) * 100,
        1,
    )
    margins = [
        result["separation_margin"]
        for result in results
        if result["separation_margin"] is not None
    ]

    return {
        "cases_total": total,
        "cases_ok": ok_count,
        "cases_ok_rate": round(ok_count / total * 100, 1) if total else 0.0,
        "cases_with_expected": cases_with_expected,
        "total_expected": total_expected,
        "total_expected_behavior": total_expected_behavior,
        "total_retrieved": total_retrieved,
        "total_forbidden": total_forbidden,
        "memory_precision": precision_pct,
        "memory_recall": round(
            total_found_expected / max(1, total_expected) * 100,
            1,
        ),
        "memory_pollution_rate": round(max(0.0, 100.0 - precision_pct), 1),
        "mode_accuracy": round(mode_correct / total * 100, 1) if total else 0.0,
        "behavior_guard_hit_rate": round(
            sum(len(result["found_behavior"]) for result in results)
            / max(1, total_expected_behavior)
            * 100,
            1,
        ),
        "behavior_leaks": total_behavior_leaked,
        "forbidden_activation_rate": round(
            total_activated_forbidden / max(1, total_forbidden) * 100,
            1,
        ),
        "forbidden_activations": total_activated_forbidden,
        "separation_margin": min(margins) if margins else None,
        "results": results,
    }


def _run_backend_suite(
    backend_name: str,
    backend: Any,
    cases: list[dict[str, Any]],
    *,
    embedding_fixture: dict[str, Any] | None = None,
    work_dir: Path,
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    results = [
        _run_backend_case(
            backend_name,
            backend,
            case,
            work_dir,
            index,
            embedding_fixture,
        )
        for index, case in enumerate(cases)
    ]
    metrics = _aggregate_results(results)
    metrics["backend"] = backend_name
    return metrics


def _compare_case_results(
    python_result: dict[str, Any],
    rust_result: dict[str, Any],
    *,
    score_tolerance: float = SCORE_TOLERANCE,
) -> dict[str, Any]:
    """Compare one case while separating result and diagnostic differences."""
    hard_mismatches: list[str] = []
    if python_result["ordered_final"] != rust_result["ordered_final"]:
        hard_mismatches.append("conversation_order")
    if python_result["ordered_behavior"] != rust_result["ordered_behavior"]:
        hard_mismatches.append("behavior_order")
    if python_result["detected_mode"] != rust_result["detected_mode"]:
        hard_mismatches.append("mode")

    python_scores = python_result.get("scores") or {}
    rust_scores = rust_result.get("scores") or {}
    diagnostic_mismatches: list[str] = []
    score_deltas: dict[str, float] = {}
    for memory_id in sorted(set(python_scores) | set(rust_scores)):
        python_score = python_scores.get(memory_id)
        rust_score = rust_scores.get(memory_id)
        if python_score is None or rust_score is None:
            diagnostic_mismatches.append(f"score_presence:{memory_id}")
            continue
        delta = round(abs(float(python_score) - float(rust_score)), 6)
        score_deltas[memory_id] = delta
        if delta > score_tolerance:
            diagnostic_mismatches.append(f"score_delta:{memory_id}")

    python_ranked = list((python_result.get("ranked_all") or {}).keys())
    rust_ranked = list((rust_result.get("ranked_all") or {}).keys())
    if python_ranked != rust_ranked:
        diagnostic_mismatches.append("ranked_trace_order")

    return {
        "id": rust_result.get("id", python_result.get("id", "?")),
        "ok": not hard_mismatches,
        "hard_mismatches": hard_mismatches,
        "diagnostic_mismatches": diagnostic_mismatches,
        "score_deltas": score_deltas,
        "max_score_delta": max(score_deltas.values(), default=0.0),
        "python": {
            "final": python_result["ordered_final"],
            "behavior": python_result["ordered_behavior"],
            "mode": python_result["detected_mode"],
        },
        "rust": {
            "final": rust_result["ordered_final"],
            "behavior": rust_result["ordered_behavior"],
            "mode": rust_result["detected_mode"],
        },
    }


def _build_compare_report(
    python_metrics: dict[str, Any],
    rust_metrics: dict[str, Any],
    *,
    score_tolerance: float = SCORE_TOLERANCE,
) -> dict[str, Any]:
    python_by_id = {result["id"]: result for result in python_metrics["results"]}
    rust_by_id = {result["id"]: result for result in rust_metrics["results"]}
    case_ids = sorted(set(python_by_id) | set(rust_by_id))
    parity_results: list[dict[str, Any]] = []
    for case_id in case_ids:
        python_result = python_by_id.get(case_id)
        rust_result = rust_by_id.get(case_id)
        if python_result is None or rust_result is None:
            parity_results.append(
                {
                    "id": case_id,
                    "ok": False,
                    "hard_mismatches": ["case_presence"],
                    "diagnostic_mismatches": [],
                    "score_deltas": {},
                    "max_score_delta": 0.0,
                }
            )
            continue
        parity_results.append(
            _compare_case_results(
                python_result,
                rust_result,
                score_tolerance=score_tolerance,
            )
        )

    hard_cases = [result for result in parity_results if result["hard_mismatches"]]
    diagnostic_cases = [
        result for result in parity_results if result["diagnostic_mismatches"]
    ]
    return {
        "cases_total": len(parity_results),
        "cases_match": len(parity_results) - len(hard_cases),
        "cases_mismatch": len(hard_cases),
        "cases_match_rate": round(
            (len(parity_results) - len(hard_cases))
            / max(1, len(parity_results))
            * 100,
            1,
        ),
        "hard_mismatch_cases": [result["id"] for result in hard_cases],
        "diagnostic_mismatch_cases": [result["id"] for result in diagnostic_cases],
        "score_tolerance": score_tolerance,
        "results": parity_results,
    }


def _percentile(samples: list[float], percentile: float) -> float | None:
    """Return an interpolated percentile in milliseconds."""
    if not samples:
        return None
    ordered = sorted(samples)
    if len(ordered) == 1:
        return round(ordered[0], 4)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return round(value, 4)


def _performance_summary(
    samples: list[float],
    *,
    warmup: int,
    iterations: int,
    errors: int,
) -> dict[str, Any]:
    """Aggregate backend-call timings in milliseconds."""
    total_seconds = sum(samples) / 1000.0
    return {
        "warmup": warmup,
        "iterations": iterations,
        "samples": len(samples),
        "min_ms": round(min(samples), 4) if samples else None,
        "mean_ms": round(statistics.fmean(samples), 4) if samples else None,
        "p50_ms": _percentile(samples, 50),
        "p95_ms": _percentile(samples, 95),
        "max_ms": round(max(samples), 4) if samples else None,
        "throughput_per_second": (
            round(len(samples) / total_seconds, 3) if total_seconds else 0.0
        ),
        "errors": errors,
    }


def _run_performance_suite(
    backend_name: str,
    backend: Any,
    cases: list[dict[str, Any]],
    *,
    embedding_fixture: dict[str, Any] | None,
    work_dir: Path,
    warmup: int,
    iterations: int,
    clock: Any = time.perf_counter,
) -> dict[str, Any]:
    """Time backend retrieval calls after isolated case setup."""
    if warmup < 0:
        raise ValueError("warmup must be >= 0")
    if iterations <= 0:
        raise ValueError("iterations must be > 0")

    work_dir.mkdir(parents=True, exist_ok=True)
    samples: list[float] = []
    errors = 0
    case_reports: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        semantic_scores = (
            fixture_semantic_scores(case, embedding_fixture)
            if embedding_fixture is not None
            else None
        )
        db_path = work_dir / f"{backend_name}_perf_{index}_{case.get('id', 'case')}.db"
        write_case_db(db_path, case, with_schema_meta=backend_name == "rust")
        request, _, _ = _case_request(case, db_path, semantic_scores)

        retrieval_v2 = None
        old_state: tuple[Any, Any, Any] | None = None
        case_samples: list[float] = []
        case_errors = 0
        try:
            if backend_name == "python":
                retrieval_v2, old_db, old_v2, old_rag = _prepare_python_runtime(db_path)
                old_state = (old_db, old_v2, old_rag)
            for _ in range(warmup):
                try:
                    if retrieval_v2 is not None:
                        retrieval_v2._CACHE.clear()
                    backend.retrieve(request)
                except Exception:
                    errors += 1
                    case_errors += 1
            for _ in range(iterations):
                try:
                    if retrieval_v2 is not None:
                        retrieval_v2._CACHE.clear()
                    started = clock()
                    backend.retrieve(request)
                    elapsed_ms = (clock() - started) * 1000.0
                    samples.append(elapsed_ms)
                    case_samples.append(elapsed_ms)
                except Exception:
                    errors += 1
                    case_errors += 1
        finally:
            if retrieval_v2 is not None and old_state is not None:
                _restore_python_runtime(retrieval_v2, *old_state)

        case_reports.append(
            {
                "id": case.get("id", "?"),
                "samples": len(case_samples),
                "errors": case_errors,
                "timing": _performance_summary(
                    case_samples,
                    warmup=warmup,
                    iterations=iterations,
                    errors=case_errors,
                ),
            }
        )

    summary = _performance_summary(
        samples,
        warmup=warmup,
        iterations=iterations,
        errors=errors,
    )
    summary["backend"] = backend_name
    summary["cases"] = case_reports
    return summary


def run_rust_benchmark(
    benchmark_dir: Path = MEMORY_BENCHMARK_DIR,
    *,
    embedding_fixture: dict[str, Any] | None = None,
    performance: bool = False,
    warmup: int = 1,
    iterations: int = 5,
) -> dict[str, Any]:
    """Run all cases through the strict Rust backend."""
    cases = load_cases(benchmark_dir)
    try:
        backend = get_backend("rust")
    except Exception as exc:
        raise RustBenchmarkError(
            f"Rust backend is unavailable or incompatible: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    with tempfile.TemporaryDirectory(prefix="stella_rust_benchmark_") as tmp:
        metrics = _run_backend_suite(
            "rust",
            backend,
            cases,
            embedding_fixture=embedding_fixture,
            work_dir=Path(tmp),
        )
    if performance:
        with tempfile.TemporaryDirectory(prefix="stella_rust_perf_") as tmp:
            metrics["performance"] = _run_performance_suite(
                "rust",
                backend,
                cases,
                embedding_fixture=embedding_fixture,
                work_dir=Path(tmp),
                warmup=warmup,
                iterations=iterations,
            )
    return metrics


def run_compare_benchmark(
    benchmark_dir: Path = MEMORY_BENCHMARK_DIR,
    *,
    embedding_fixture: dict[str, Any] | None = None,
    score_tolerance: float = SCORE_TOLERANCE,
    performance: bool = False,
    warmup: int = 1,
    iterations: int = 5,
) -> dict[str, Any]:
    """Run Python and strict Rust against isolated copies of every case."""
    cases = load_cases(benchmark_dir)
    try:
        rust_backend = get_backend("rust")
    except Exception as exc:
        raise RustBenchmarkError(
            f"Rust backend is unavailable or incompatible: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    python_backend = PythonMemoryBackend()

    with tempfile.TemporaryDirectory(prefix="stella_compare_benchmark_") as tmp:
        root = Path(tmp)
        python_metrics = _run_backend_suite(
            "python",
            python_backend,
            cases,
            embedding_fixture=embedding_fixture,
            work_dir=root / "python",
        )
        rust_metrics = _run_backend_suite(
            "rust",
            rust_backend,
            cases,
            embedding_fixture=embedding_fixture,
            work_dir=root / "rust",
        )

    parity = _build_compare_report(
        python_metrics,
        rust_metrics,
        score_tolerance=score_tolerance,
    )
    report = {
        "backend": "compare",
        "ok": (
            python_metrics["cases_ok"] == python_metrics["cases_total"]
            and rust_metrics["cases_ok"] == rust_metrics["cases_total"]
            and parity["cases_mismatch"] == 0
        ),
        "python": python_metrics,
        "rust": rust_metrics,
        "parity": parity,
    }
    if performance:
        with tempfile.TemporaryDirectory(prefix="stella_compare_perf_") as tmp:
            root = Path(tmp)
            report["performance"] = {
                "python": _run_performance_suite(
                    "python",
                    python_backend,
                    cases,
                    embedding_fixture=embedding_fixture,
                    work_dir=root / "python",
                    warmup=warmup,
                    iterations=iterations,
                ),
                "rust": _run_performance_suite(
                    "rust",
                    rust_backend,
                    cases,
                    embedding_fixture=embedding_fixture,
                    work_dir=root / "rust",
                    warmup=warmup,
                    iterations=iterations,
                ),
            }
    return report


def _print_summary(metrics: dict[str, Any]) -> None:
    print("=" * 56)
    print(
        f"Rust Memory Benchmark {metrics['cases_total']} cases "
        f"({metrics['cases_with_expected']} with expected)"
    )
    print("=" * 56)
    print(
        f"  Cases passed       : {metrics['cases_ok']}/"
        f"{metrics['cases_total']} ({metrics['cases_ok_rate']}%)"
    )
    print(f"  Memory Precision   : {metrics['memory_precision']}%")
    print(f"  Memory Recall      : {metrics['memory_recall']}%")
    print(f"  Pollution Rate     : {metrics['memory_pollution_rate']}%")
    print(f"  Behavior Guard     : {metrics['behavior_guard_hit_rate']}%")
    print(f"  Mode Accuracy      : {metrics['mode_accuracy']}%")
    print(
        f"  Forbidden Activation: {metrics['forbidden_activation_rate']}% "
        f"({metrics['forbidden_activations']} hits)"
    )
    if metrics.get("separation_margin") is not None:
        print(f"  Separation Margin  : {metrics['separation_margin']:+.4f}")
    print("=" * 56)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stella Rust memory benchmark")
    parser.add_argument(
        "--dir",
        type=Path,
        default=MEMORY_BENCHMARK_DIR,
        help="benchmark dataset directory",
    )
    parser.add_argument(
        "--embedding-fixture",
        type=Path,
        default=None,
        help="optional deterministic embedding fixture",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="run Python and strict Rust and emit per-case parity diagnostics",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="write the machine-readable report to this path",
    )
    parser.add_argument(
        "--performance",
        action="store_true",
        help="measure backend retrieval latency after warmup",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="warmup retrieval calls per case (default: 1)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="timed retrieval calls per case (default: 5)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print per-case results",
    )
    args = parser.parse_args(argv)

    try:
        fixture = (
            load_embedding_fixture(args.embedding_fixture)
            if args.embedding_fixture is not None
            else None
        )
        metrics = (
            run_compare_benchmark(
                args.dir,
                embedding_fixture=fixture,
                performance=args.performance,
                warmup=args.warmup,
                iterations=args.iterations,
            )
            if args.compare
            else run_rust_benchmark(
                args.dir,
                embedding_fixture=fixture,
                performance=args.performance,
                warmup=args.warmup,
                iterations=args.iterations,
            )
        )
    except Exception as exc:
        error = {
            "backend": "rust",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        if args.json is not None:
            args.json.write_text(
                json.dumps(error, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(error["error"], file=sys.stderr)
        return 1

    if args.json is not None:
        args.json.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    _print_summary(metrics["rust"] if args.compare else metrics)
    if args.compare:
        parity = metrics["parity"]
        print(
            f"Parity: {parity['cases_match']}/{parity['cases_total']} "
            f"hard matches ({parity['cases_match_rate']}%), "
            f"score tolerance={parity['score_tolerance']}"
        )
        for result in parity["results"]:
            if result["hard_mismatches"] or result["diagnostic_mismatches"]:
                print(
                    f"{result['id']}: "
                    f"hard={result['hard_mismatches']} "
                    f"diagnostic={result['diagnostic_mismatches']}"
                )
    if args.performance:
        performance = metrics["performance"]
        if args.compare:
            performance = performance["rust"]
        print(
            f"Performance {performance['backend']}: "
            f"samples={performance['samples']} "
            f"p50={performance['p50_ms']}ms "
            f"p95={performance['p95_ms']}ms "
            f"throughput={performance['throughput_per_second']}/s "
            f"errors={performance['errors']}"
        )
    if args.verbose:
        results = metrics["rust"]["results"] if args.compare else metrics["results"]
        for result in results:
            print(
                f"{'PASS' if result['ok'] else 'FAIL'} "
                f"{result['id']} mode={result['detected_mode']} "
                f"final={result['ordered_final']} "
                f"behavior={result['ordered_behavior']}"
            )
    if args.compare:
        performance_errors = sum(
            metrics.get("performance", {}).get(backend, {}).get("errors", 0)
            for backend in ("python", "rust")
        )
        return 0 if metrics["ok"] and performance_errors == 0 else 1
    performance_errors = metrics.get("performance", {}).get("errors", 0)
    return (
        0
        if metrics["cases_ok"] == metrics["cases_total"] and performance_errors == 0
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
