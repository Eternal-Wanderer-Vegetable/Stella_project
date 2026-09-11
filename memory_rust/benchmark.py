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
import sys
import tempfile
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


def run_rust_benchmark(
    benchmark_dir: Path = MEMORY_BENCHMARK_DIR,
    *,
    embedding_fixture: dict[str, Any] | None = None,
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
        work_dir = Path(tmp)
        results = [
            _run_backend_case(
                "rust",
                backend,
                case,
                work_dir,
                index,
                embedding_fixture,
            )
            for index, case in enumerate(cases)
        ]
    metrics = _aggregate_results(results)
    metrics["backend"] = "rust"
    return metrics


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
        "--json",
        type=Path,
        default=None,
        help="write the machine-readable report to this path",
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
        metrics = run_rust_benchmark(args.dir, embedding_fixture=fixture)
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
    _print_summary(metrics)
    if args.verbose:
        for result in metrics["results"]:
            print(
                f"{'PASS' if result['ok'] else 'FAIL'} "
                f"{result['id']} mode={result['detected_mode']} "
                f"final={result['ordered_final']} "
                f"behavior={result['ordered_behavior']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
