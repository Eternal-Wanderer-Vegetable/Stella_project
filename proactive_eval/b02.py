# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Run the pinned B02 public participation holdouts with local baselines only."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proactive_eval.adapters import (
    load_registry,
    sha256_file,
    validate_dataset_files,
)
from proactive_eval.cli import main as evaluation_main
from proactive_eval.fingerprint import canonical_sha256, make_fingerprint
from proactive_eval.metrics import score_participation
from proactive_eval.report import write_proactive_report
from proactive_eval.source_adapters import (
    ADAPTER_VERSION,
    AdaptedCorpus,
    adapt_social_ai_ambient,
    adapt_when2speak_token,
    write_jsonl,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REGISTRY_PATH = Path(__file__).with_name("dataset-registry.json")
_DEFAULT_OUTPUT_ROOT = (
    _REPO_ROOT / "memory/benchmark/_public/proactive_eval/runs/B02-2026-11-04"
)
_DEFAULT_HOME_ROOT = (
    Path(tempfile.gettempdir()) / "stella-proactive-eval" / "B02-2026-11-04"
)
_BASELINES = (
    {
        "baseline_id": "always-silent",
        "plugin": "proactive_eval.b02_plugins:always_silent",
        "condition": "Always return DROP; no memory, generation, or model call.",
    },
    {
        "baseline_id": "always-speak",
        "plugin": "proactive_eval.b02_plugins:always_speak",
        "condition": "Always return SPEAK; no memory, generation, or model call.",
    },
    {
        "baseline_id": "last-explicit-question",
        "plugin": "proactive_eval.b02_plugins:last_explicit_question",
        "condition": (
            "Return SPEAK only when the current message ends in '?' or '？'; "
            "no memory, generation, or model call."
        ),
    },
)


@dataclass(frozen=True)
class SourceInput:
    dataset_id: str
    config: str
    revision: str
    license: str
    source_path: Path
    source_sha256: str
    source_bytes: int
    source_records: int
    unit: str
    expected_raw_count: int
    expected_sample_count: int
    expected_labels: dict[str, int]
    adapter: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m proactive_eval.b02",
        description="Adapt frozen public test files and run deterministic no-memory baselines.",
    )
    parser.add_argument("--registry", type=Path, default=_REGISTRY_PATH)
    parser.add_argument("--output-root", type=Path, default=_DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--home-root", type=Path, default=_DEFAULT_HOME_ROOT)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run_b02(
            registry_path=args.registry,
            output_root=args.output_root,
            home_root=args.home_root,
            resume=args.resume,
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        print(f"B02 evaluation rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"] == "completed" else 1


def run_b02(
    *,
    registry_path: Path = _REGISTRY_PATH,
    output_root: Path = _DEFAULT_OUTPUT_ROOT,
    home_root: Path = _DEFAULT_HOME_ROOT,
    resume: bool = False,
) -> dict[str, Any]:
    """Adapt, validate, and score both full test holdouts without a model call."""
    registry_path = registry_path.resolve()
    output_root = output_root.resolve()
    home_root = home_root.resolve()
    registry = load_registry(registry_path)
    _ensure_safe_output_root(output_root)
    if home_root == _REPO_ROOT or _REPO_ROOT in home_root.parents:
        raise ValueError("isolated STELLA_HOME root must be outside the repository")

    inputs = _source_inputs(registry)
    head = _git_head()
    run_summaries: list[dict[str, Any]] = []
    for source in inputs:
        if not source.source_path.is_file():
            raise FileNotFoundError(
                f"pinned public input is missing; B02 does not download data: {source.source_path}"
            )
        if source.source_path.stat().st_size != source.source_bytes:
            raise ValueError(f"pinned source byte count mismatch: {source.source_path}")
        corpus = _adapt(source)
        _check_expected_counts(source, corpus)

        dataset_dir = output_root / "adapted" / source.dataset_id
        scenario_path = dataset_dir / "actor-scenarios.jsonl"
        gold_path = dataset_dir / "scorer-gold.jsonl"
        scenario_hash = write_jsonl(scenario_path, corpus.scenarios)
        gold_hash = write_jsonl(gold_path, corpus.gold)
        category_path = dataset_dir / "source-categories.json"
        _write_json_atomic(category_path, corpus.category_by_scenario)
        category_by_scenario = corpus.category_by_scenario
        raw_records = corpus.raw_records
        label_counts = dict(corpus.label_counts)
        del corpus
        gc.collect()

        # Validate the generated boundary files before any actor process starts.
        validate_dataset_files(
            scenario_path,
            gold_path,
            expected_scenario_sha256=scenario_hash,
            expected_gold_sha256=gold_hash,
        )
        _verify_b01_actor_boundary(scenario_path, source.dataset_id)

        baseline_summaries: list[dict[str, Any]] = []
        for baseline in _BASELINES:
            run_dir = output_root / source.dataset_id / baseline["baseline_id"]
            home_path = home_root / source.dataset_id / baseline["baseline_id"]
            run_summary = _run_baseline(
                source=source,
                baseline=baseline,
                scenario_path=scenario_path,
                gold_path=gold_path,
                scenario_hash=scenario_hash,
                gold_hash=gold_hash,
                category_path=category_path,
                category_by_scenario=category_by_scenario,
                run_dir=run_dir,
                home_path=home_path,
                registry_path=registry_path,
                raw_records=raw_records,
                label_counts=label_counts,
                head=head,
                resume=resume,
            )
            baseline_summaries.append(run_summary)
        run_summaries.append(
            {
                "dataset_id": source.dataset_id,
                "config": source.config,
                "revision": source.revision,
                "license": source.license,
                "source_sha256": source.source_sha256,
                "source_bytes": source.source_bytes,
                "raw_records": raw_records,
                "adapted_count": source.expected_sample_count,
                "gold_label_counts": label_counts,
                "stella_persona_labels": 0,
                "baselines": baseline_summaries,
            }
        )

    status = (
        "completed"
        if all(run["status"] == "completed" for dataset in run_summaries for run in dataset["baselines"])
        else "partial"
    )
    summary = {
        "schema": "stella-proactive-b02-summary/1",
        "status": status,
        "source_ref": head,
        "adapter_version": ADAPTER_VERSION,
        "datasets": run_summaries,
        "model_calls": 0,
        "generated_outputs": 0,
        "memory_inputs": 0,
        "stella_persona_labels": 0,
    }
    summary_path = output_root / "summary.json"
    _write_json_atomic(summary_path, summary)
    summary["summary_path"] = _repo_relative(summary_path)
    summary["summary_sha256"] = sha256_file(summary_path)
    return summary


def _source_inputs(registry: dict[str, Any]) -> tuple[SourceInput, SourceInput]:
    datasets = {row["dataset_id"]: row for row in registry["datasets"]}
    when = datasets["when2speak"]
    token = next(config for config in when["configs"] if config["name"] == "token")
    when_file = token["files"][0]
    when_path = _repo_path(when_file["path"])
    when_input = SourceInput(
        dataset_id="when2speak",
        config="token",
        revision=when["source"]["revision"],
        license=when["license"],
        source_path=when_path,
        source_sha256=when_file["sha256"],
        source_bytes=when_file["bytes"],
        source_records=when_file["records"],
        unit=when["unit"],
        expected_raw_count=when["test_counts"]["decision_contexts"],
        expected_sample_count=when["test_counts"]["decision_contexts"],
        expected_labels={"SPEAK": when["test_counts"]["speak"], "SILENT": when["test_counts"]["silent"]},
        adapter="when2speak",
    )

    social = datasets["social-ai-ambient-bench"]
    social_file = social["files"][0]
    social_path = _repo_path(social_file["path"])
    social_input = SourceInput(
        dataset_id="social-ai-ambient-bench",
        config="default",
        revision=social["source"]["revision"],
        license=social["license"],
        source_path=social_path,
        source_sha256=social_file["sha256"],
        source_bytes=social_file["bytes"],
        source_records=social_file["records"],
        unit=social["unit"],
        expected_raw_count=social["counts"]["scenes"],
        expected_sample_count=social["counts"]["turns"],
        expected_labels={"SPEAK": social["counts"]["respond"], "SILENT": social["counts"]["silent"]},
        adapter="social-ai-ambient-bench",
    )
    return when_input, social_input


def _adapt(source: SourceInput) -> AdaptedCorpus:
    adapter = {
        "when2speak": adapt_when2speak_token,
        "social-ai-ambient-bench": adapt_social_ai_ambient,
    }[source.adapter]
    return adapter(
        source.source_path,
        expected_sha256=source.source_sha256,
        revision=source.revision,
    )


def _check_expected_counts(source: SourceInput, corpus: AdaptedCorpus) -> None:
    if source.source_records != source.expected_raw_count:
        raise ValueError(
            f"registry raw row count does not match expected unit for {source.dataset_id}"
        )
    if corpus.raw_records != source.expected_raw_count:
        raise ValueError(f"adapted raw record count mismatch for {source.dataset_id}")
    if len(corpus.scenarios) != source.expected_sample_count:
        raise ValueError(f"adapted actor scenario count mismatch for {source.dataset_id}")
    if len(corpus.gold) != source.expected_sample_count:
        raise ValueError(f"adapted scorer gold count mismatch for {source.dataset_id}")
    if corpus.label_counts != source.expected_labels:
        raise ValueError(
            f"source label counts differ from frozen registry for {source.dataset_id}: "
            f"expected {source.expected_labels}, got {corpus.label_counts}"
        )


def _run_baseline(
    *,
    source: SourceInput,
    baseline: dict[str, str],
    scenario_path: Path,
    gold_path: Path,
    scenario_hash: str,
    gold_hash: str,
    category_path: Path,
    category_by_scenario: dict[str, str],
    run_dir: Path,
    home_path: Path,
    registry_path: Path,
    raw_records: int,
    label_counts: dict[str, int],
    head: str,
    resume: bool,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "effective-config.json"
    resolved_config = {
        "baseline_id": baseline["baseline_id"],
        "baseline_version": baseline["plugin"].rsplit(":", 1)[-1],
        "memory_inputs": 0,
        "model_calls": 0,
        "generated_outputs": 0,
        "seed": 20261104,
    }
    _write_json_atomic(config_path, resolved_config)
    actor_fingerprint = make_fingerprint(
        repository=_REPO_ROOT,
        dataset_registry=registry_path,
        scenario_file=scenario_path,
        gold_file=None,
        protocol_file=Path(__file__).with_name("protocol-lock.json"),
        effective_config={
            "dataset_id": source.dataset_id,
            "dataset_revision": source.revision,
            "actor_plugin": baseline["plugin"],
            "scenario_sha256": scenario_hash,
            "seed": 20261104,
            "resolved": resolved_config,
        },
        seed=20261104,
    )
    args = [
        "run",
        "--registry",
        str(registry_path),
        "--dataset-id",
        source.dataset_id,
        "--scenarios",
        str(scenario_path),
        "--gold",
        str(gold_path),
        "--expected-scenario-sha256",
        scenario_hash,
        "--expected-gold-sha256",
        gold_hash,
        "--run-dir",
        str(run_dir),
        "--isolated-home",
        str(home_path),
        "--actor",
        baseline["plugin"],
        "--scorer",
        "proactive_eval.b02_plugins:score_source_label",
        "--config",
        str(config_path),
        "--seed",
        "20261104",
    ]
    actor_dir = run_dir / "actor"
    actor_dir.mkdir(parents=True, exist_ok=True)
    actor_fingerprint_path = actor_dir / "fingerprint-components.json"
    actor_checkpoint_path = actor_dir / "checkpoint.json"
    scorer_checkpoint_path = run_dir / "scorer" / "checkpoint.json"
    aggregation_recovered = False
    elapsed_ms: float | None
    exit_code: int
    if resume and actor_checkpoint_path.is_file() and scorer_checkpoint_path.is_file():
        saved_actor = _read_json(actor_checkpoint_path)
        saved_scorer = _read_json(scorer_checkpoint_path)
        saved_fingerprint = (
            _read_json(actor_fingerprint_path) if actor_fingerprint_path.is_file() else None
        )
        if saved_actor.get("status") == "completed" and saved_scorer.get("status") == "completed":
            if not isinstance(saved_fingerprint, dict):
                raise ValueError("completed run lacks the actor fingerprint components needed for report recovery")
            expected_scorer_fingerprint = canonical_sha256(
                {
                    "actor_fingerprint": saved_actor.get("fingerprint"),
                    "gold_sha256": gold_hash,
                    "scorer": "proactive_eval.b02_plugins:score_source_label",
                }
            )
            if (
                saved_fingerprint.get("sha256") != saved_actor.get("fingerprint")
                or saved_actor.get("scenario_sha256") != scenario_hash
                or saved_actor.get("total") != source.expected_sample_count
                or saved_scorer.get("gold_sha256") != gold_hash
                or saved_scorer.get("total") != source.expected_sample_count
                or saved_scorer.get("fingerprint") != expected_scorer_fingerprint
            ):
                raise ValueError("completed actor/scorer artifacts do not match the frozen B02 inputs")
            actor_fingerprint = saved_fingerprint
            aggregation_recovered = True
            elapsed_ms = None
            exit_code = 0
        elif not isinstance(saved_fingerprint, dict):
            raise ValueError("resume rejected: partial run lacks actor fingerprint components")
        elif saved_fingerprint.get("sha256") != actor_fingerprint["sha256"]:
            raise ValueError("resume rejected: code fingerprint changed before the partial run completed")
        else:
            elapsed_ms, exit_code = _invoke_evaluator([*args, "--resume"])
    else:
        if actor_fingerprint_path.is_file() and actor_checkpoint_path.is_file():
            saved_fingerprint = _read_json(actor_fingerprint_path)
            if saved_fingerprint.get("sha256") != actor_fingerprint["sha256"]:
                raise ValueError("resume rejected: code fingerprint changed for an existing actor run")
        else:
            _write_json_atomic(actor_fingerprint_path, actor_fingerprint)
        elapsed_ms, exit_code = _invoke_evaluator(args)
    actor_path = run_dir / "actor" / "results.jsonl"
    score_path = run_dir / "scorer" / "results.jsonl"
    if not actor_path.is_file() or not score_path.is_file():
        raise RuntimeError(
            f"B01 runner exited {exit_code} without complete actor/scorer result files for "
            f"{source.dataset_id}/{baseline['baseline_id']}"
        )

    actor_rows = _read_jsonl(actor_path)
    scorer_rows = _read_jsonl(score_path)
    gold_rows = _read_jsonl(gold_path)
    actor_by_id = {str(row["scenario_id"]): row for row in actor_rows}
    score_by_key = {(str(row["scenario_id"]), str(row["event_id"])): row for row in scorer_rows}
    pairs: list[tuple[str, str]] = []
    category_pairs: dict[str, list[tuple[str, str]]] = {}
    error_rows: list[dict[str, Any]] = []
    error_counts: Counter[str] = Counter()
    for gold in gold_rows:
        scenario_id = str(gold["scenario_id"])
        event_id = str(gold["event_id"])
        score = score_by_key.get((scenario_id, event_id))
        actor = actor_by_id.get(scenario_id)
        category = category_by_scenario.get(scenario_id)
        if score is None or score.get("status") != "scored":
            actor_failure = (actor or {}).get("failure")
            failure = {
                "scenario_id": scenario_id,
                "episode_id": (actor or {}).get("episode_id"),
                "event_id": event_id,
                "category": category,
                "error_kind": "actor_or_scorer_failure",
                "failure": actor_failure or {"type": "NotScored", "reason": (score or {}).get("reason")},
            }
            error_rows.append(failure)
            error_counts["actor_or_scorer_failure"] += 1
            continue
        detail = score["score"]
        expected = str(gold["source_label"])
        predicted = str(detail["prediction"])
        pairs.append((expected, predicted))
        if category:
            category_pairs.setdefault(category, []).append((expected, predicted))
        if not detail["correct"]:
            error_kind = str(detail["error_kind"])
            error_counts[error_kind] += 1
            error_rows.append(
                {
                    "scenario_id": scenario_id,
                    "episode_id": (actor or {}).get("episode_id"),
                    "event_id": event_id,
                    "category": category,
                    "expected": expected,
                    "predicted": predicted,
                    "error_kind": error_kind,
                }
            )

    participation = score_participation(pairs)
    accuracy = sum(gold == predicted for gold, predicted in pairs) / len(pairs) if pairs else None
    total = len(gold_rows)
    completed = len(pairs)
    failed = total - completed
    errors_path = run_dir / "errors.jsonl"
    errors_hash = write_jsonl(errors_path, error_rows)
    category_metrics = {
        category: _metrics_summary(score_participation(values), values)
        for category, values in sorted(category_pairs.items())
    }
    metrics_summary = _metrics_summary(participation, pairs)
    metrics_summary["category_metrics"] = category_metrics
    metrics_summary["label_counts"] = label_counts
    metrics_summary["error_counts"] = dict(sorted(error_counts.items()))
    metrics_summary["error_count"] = len(error_rows)
    metrics_summary["scored_count"] = completed
    metrics_summary["total_count"] = total
    metrics_summary["accuracy"] = accuracy
    metrics_summary["aggregation_recovered_from_completed_run"] = aggregation_recovered
    metrics_path = run_dir / "metrics.json"
    _write_json_atomic(metrics_path, metrics_summary)

    actor_checkpoint = _read_json(run_dir / "actor" / "checkpoint.json")
    scorer_checkpoint = _read_json(run_dir / "scorer" / "checkpoint.json")
    if actor_checkpoint.get("fingerprint") != actor_fingerprint["sha256"]:
        raise ValueError("B01 actor checkpoint fingerprint differs from the report inputs")
    source_baseline_ref = f"{_git_branch()}@{head} (B02 worktree; runner fingerprint records dirty state)"
    report_path = run_dir / "report.json"
    report_metrics = _report_metrics(participation, pairs, accuracy)
    report_status = "pass" if failed == 0 and exit_code == 0 else "partial"
    partial_reasons = [] if report_status == "pass" else [
        f"runner_exit_code={exit_code}", f"scored={completed}/{total}"
    ]
    report = {
        "schema": "stella-proactive-report/1",
        "run_id": f"B02-{source.dataset_id}-{baseline['baseline_id']}",
        "status": report_status,
        "evidence_level": "L1",
        "metric_definitions_version": "proactive-eval-metrics/1",
        "fingerprint": actor_fingerprint,
        "dataset": {
            "dataset_id": source.dataset_id,
            "config": source.config,
            "revision": source.revision,
            "split": "test",
            "unit": source.unit,
            "adapter_version": ADAPTER_VERSION,
            "file_hashes": [source.source_sha256, scenario_hash, gold_hash],
            "raw_count": raw_records,
            "adapted_count": total,
            "excluded_count": 0,
            "license": source.license,
        },
        "baseline": {
            "baseline_id": baseline["baseline_id"],
            "source_ref": source_baseline_ref,
            "condition": baseline["condition"],
            "paired": False,
        },
        "counts": {
            "total": total,
            "completed": completed,
            "failed": failed,
            "skipped": 0,
            "not_applicable": 0,
            "scored_coverage": completed / total if total else None,
        },
        "metrics": report_metrics,
        "traces": [],
        "cost": {
            "model_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "wall_time_ms": elapsed_ms,
            "peak_rss_bytes": None,
            "by_role": {"actor": {"model_calls": 0}, "scorer": {"model_calls": 0}},
            "estimated_price": 0,
            "price_currency": "USD",
        },
        "artifacts": [
            _artifact("actor-scenarios.jsonl", scenario_path, restricted=True),
            _artifact("scorer-gold.jsonl", gold_path, restricted=True),
            _artifact("source-categories.json", category_path, restricted=True),
            _artifact("actor/fingerprint-components.json", actor_fingerprint_path, restricted=False),
            _artifact("actor/results.jsonl", actor_path, restricted=True),
            _artifact("scorer/results.jsonl", score_path, restricted=True),
            _artifact("errors.jsonl", errors_path, restricted=True),
            _artifact("metrics.json", metrics_path, restricted=False),
        ],
        "partial_reasons": partial_reasons,
        "panels": {
            "aoede_participation": report_metrics,
            "mneme_memory": {},
            "aoede_mneme_joint": {},
        },
    }
    report_hash = write_proactive_report(report_path, report)
    return {
        "baseline_id": baseline["baseline_id"],
        "status": "completed" if report_status == "pass" else "partial",
        "total": total,
        "completed": completed,
        "failed": failed,
        "label_counts": label_counts,
        "metrics": metrics_summary,
        "runner_exit_code": exit_code,
        "aggregation_recovered_from_completed_run": aggregation_recovered,
        "actor_fingerprint": actor_fingerprint["sha256"],
        "scorer_fingerprint": scorer_checkpoint["fingerprint"],
        "report_path": _repo_relative(report_path),
        "report_sha256": report_hash,
        "scenario_sha256": scenario_hash,
        "gold_sha256": gold_hash,
        "errors_path": _repo_relative(errors_path),
        "errors_sha256": errors_hash,
    }


def _invoke_evaluator(args: list[str]) -> tuple[float, int]:
    started = time.perf_counter()
    exit_code = evaluation_main(args)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return elapsed_ms, int(exit_code or 0)


def _metrics_summary(result: dict[str, Any], pairs: list[tuple[str, str]]) -> dict[str, Any]:
    matrix = result["confusion_matrix"]
    return {
        "status": result["status"],
        "macro_f1": result["value"],
        "false_interruption_rate": result.get("false_interruption_rate"),
        "false_interruption_numerator": result.get("false_interruption_numerator"),
        "false_interruption_denominator": result.get("false_interruption_denominator"),
        "missed_intervention_rate": result.get("missed_intervention_rate"),
        "missed_intervention_numerator": result.get("missed_intervention_numerator"),
        "missed_intervention_denominator": result.get("missed_intervention_denominator"),
        "confusion_matrix": matrix,
        "class_metrics": result["class_metrics"],
        "accuracy": sum(gold == predicted for gold, predicted in pairs) / len(pairs) if pairs else None,
        "scored_count": len(pairs),
    }


def _report_metrics(
    result: dict[str, Any], pairs: list[tuple[str, str]], accuracy: float | None
) -> dict[str, dict[str, Any]]:
    if result["status"] != "scored":
        not_scored = {"status": "not_applicable", "numerator": None, "denominator": 0, "value": None}
        return {name: dict(not_scored) for name in (
            "macro_f1", "false_interruption_rate", "missed_intervention_rate", "accuracy"
        )}
    class_metrics = result["class_metrics"]
    return {
        "macro_f1": {
            "status": "scored",
            "numerator": result["value"],
            "denominator": len(pairs),
            "value": result["value"],
        },
        "false_interruption_rate": {
            "status": "scored" if result["false_interruption_denominator"] else "not_applicable",
            "numerator": result["false_interruption_numerator"],
            "denominator": result["false_interruption_denominator"],
            "value": result["false_interruption_rate"],
        },
        "missed_intervention_rate": {
            "status": "scored" if result["missed_intervention_denominator"] else "not_applicable",
            "numerator": result["missed_intervention_numerator"],
            "denominator": result["missed_intervention_denominator"],
            "value": result["missed_intervention_rate"],
        },
        "accuracy": {
            "status": "scored" if accuracy is not None else "not_applicable",
            "numerator": sum(gold == predicted for gold, predicted in pairs),
            "denominator": len(pairs),
            "value": accuracy,
        },
        "f1_speak": {
            "status": "scored",
            "numerator": class_metrics["SPEAK"]["f1"],
            "denominator": len(pairs),
            "value": class_metrics["SPEAK"]["f1"],
        },
        "f1_silent": {
            "status": "scored",
            "numerator": class_metrics["SILENT"]["f1"],
            "denominator": len(pairs),
            "value": class_metrics["SILENT"]["f1"],
        },
    }


def _artifact(name: str, path: Path, *, restricted: bool) -> dict[str, Any]:
    return {
        "path": name,
        "sha256": sha256_file(path),
        "restricted": restricted,
        "media_type": "application/json" if path.suffix == ".json" else "application/x-ndjson",
    }


def _verify_b01_actor_boundary(scenario_path: Path, dataset_id: str) -> None:
    """Check the source adapter output is closed-schema and contains no gold-only keys."""
    forbidden = {"source_label", "expected_output", "gold", "label_origin", "future"}
    for row_number, scenario in enumerate(_read_jsonl(scenario_path), 1):
        if scenario["source"]["dataset_id"] != dataset_id:
            raise ValueError(f"actor scenario {row_number} has the wrong dataset id")
        if scenario["accessible_memories"]:
            raise ValueError(f"B02 actor scenario {row_number} unexpectedly contains memory")
        if any(forbidden.intersection(event) for event in scenario["events"]):
            raise ValueError(f"actor scenario {row_number} contains a gold-only field")


def _repo_path(relative: str) -> Path:
    path = (_REPO_ROOT / relative).resolve()
    if path == _REPO_ROOT or _REPO_ROOT not in path.parents:
        raise ValueError(f"registry path escapes the repository: {relative}")
    return path


def _ensure_safe_output_root(path: Path) -> None:
    if path == _REPO_ROOT:
        raise ValueError("B02 output root cannot be the repository root")
    if _REPO_ROOT not in path.parents:
        return
    probe = path / "adapted" / ".b02-output-probe.jsonl"
    relative = probe.relative_to(_REPO_ROOT)
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", str(relative)],
        cwd=_REPO_ROOT,
        check=False,
        timeout=10,
    )
    if result.returncode != 0:
        raise ValueError("B02 output inside the repository must be gitignored")


def _write_json_atomic(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    import tempfile as _tempfile

    fd, temporary_name = _tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return hashlib.sha256(payload).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        for row_number, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(f"blank generated JSONL row at {path}:{row_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"generated JSONL row at {path}:{row_number} must be an object")
            rows.append(value)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def _repo_relative(path: Path) -> str:
    resolved = path.resolve()
    if resolved == _REPO_ROOT or _REPO_ROOT in resolved.parents:
        return resolved.relative_to(_REPO_ROOT).as_posix()
    return resolved.as_posix()


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _git_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main", "run_b02"]
