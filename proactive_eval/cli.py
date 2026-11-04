# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""CLI for validating a pinned dataset slice and replaying an actor-only fixture."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from proactive_eval.adapters import (
    load_registry,
    sha256_file,
    validate_actor_files,
    validate_dataset_files,
    verify_expected_hash,
)
from proactive_eval.fingerprint import canonical_sha256, make_fingerprint
from proactive_eval.plugins import PluginProcess
from proactive_eval.runner import run_actor_stage, score_actor_outputs

_REPOSITORY = Path(__file__).resolve().parents[1]
_DEFAULT_REGISTRY = Path(__file__).with_name("dataset-registry.json")
_DEFAULT_PROTOCOL = Path(__file__).with_name("protocol-lock.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m proactive_eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate actor/gold JSONL and registry")
    validate.add_argument("--registry", type=Path, default=_DEFAULT_REGISTRY)
    validate.add_argument("--dataset-id", required=True)
    validate.add_argument("--scenarios", type=Path, required=True)
    validate.add_argument("--gold", type=Path, required=True)
    validate.add_argument("--expected-scenario-sha256")
    validate.add_argument("--expected-gold-sha256")

    run = subparsers.add_parser("run", help="run an actor plugin, then a separate scorer plugin")
    run.add_argument("--registry", type=Path, default=_DEFAULT_REGISTRY)
    run.add_argument("--dataset-id", required=True)
    run.add_argument("--scenarios", type=Path, required=True)
    run.add_argument("--gold", type=Path, required=True)
    run.add_argument("--expected-scenario-sha256", required=True)
    run.add_argument("--expected-gold-sha256", required=True)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--isolated-home", type=Path, required=True)
    run.add_argument("--actor", required=True, help="Python import path module:callable(scenario)")
    run.add_argument("--scorer", required=True, help="Python import path module:callable(gold, actor_output)")
    run.add_argument("--config", type=Path, help="resolved non-secret effective config JSON")
    run.add_argument("--seed", type=int, default=20261104)
    run.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = load_registry(args.registry)
        rows = {str(row["dataset_id"]): row for row in registry["datasets"]}
        if args.dataset_id not in rows:
            raise ValueError(f"dataset_id not present in registry: {args.dataset_id}")
        dataset = rows[args.dataset_id]
        if str(dataset.get("status", "")).startswith(("BLOCKED", "DEFERRED")):
            raise ValueError(f"dataset is not runnable: {dataset['dataset_id']} ({dataset['status']})")
        if args.command == "validate":
            files = validate_dataset_files(
                args.scenarios,
                args.gold,
                expected_scenario_sha256=args.expected_scenario_sha256,
                expected_gold_sha256=args.expected_gold_sha256,
            )
            scenarios = files.scenarios
            scenario_hash = files.scenario_sha256
        else:
            # Keep gold rows unopened and out of memory until the actor stage has finished.
            scenarios = validate_actor_files(
                args.scenarios, expected_sha256=args.expected_scenario_sha256
            )
            scenario_hash = sha256_file(args.scenarios)
            gold_hash = sha256_file(args.gold)
            verify_expected_hash("gold", gold_hash, args.expected_gold_sha256)
        expected_revision = (dataset.get("source") or {}).get("revision")
        for scenario in scenarios:
            source = scenario.get("source") or {}
            if source.get("dataset_id") != args.dataset_id:
                raise ValueError(
                    f"scenario {scenario['scenario_id']!r} belongs to "
                    f"{source.get('dataset_id')!r}, not {args.dataset_id!r}"
                )
            if expected_revision and source.get("revision") != expected_revision:
                raise ValueError(
                    f"scenario {scenario['scenario_id']!r} revision does not match pinned registry revision"
                )
        if args.command == "validate":
            print(json.dumps({
                "status": "valid",
                "dataset_id": args.dataset_id,
                "scenario_count": len(files.scenarios),
                "gold_count": len(files.gold),
                "scenario_sha256": files.scenario_sha256,
                "gold_sha256": files.gold_sha256,
                "episode_splits": files.episode_splits,
            }, ensure_ascii=False, sort_keys=True))
            return 0
        return _run(args, registry, dataset, scenario_hash, gold_hash)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"evaluation rejected: {exc}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace, registry: dict[str, Any], dataset: dict[str, Any],
         scenario_hash: str, gold_hash: str) -> int:
    isolated_home = _prepare_isolated_home(args.isolated_home, resume=args.resume)
    _check_run_output(args.run_dir)
    effective_config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    if not isinstance(effective_config, dict):
        raise ValueError("effective config must be a JSON object")
    fingerprint = make_fingerprint(
        repository=_REPOSITORY,
        dataset_registry=args.registry,
        scenario_file=args.scenarios,
        gold_file=None,
        protocol_file=_DEFAULT_PROTOCOL,
        effective_config={
            "dataset_id": args.dataset_id,
            "dataset_revision": (dataset.get("source") or {}).get("revision"),
            "actor_plugin": args.actor,
            "scenario_sha256": scenario_hash,
            "seed": args.seed,
            "resolved": effective_config,
        },
        seed=args.seed,
    )

    # Set the isolated home before importing any plugin that might import config.
    os.environ["STELLA_HOME"] = str(isolated_home)
    with PluginProcess("actor", args.actor, isolated_home) as actor_process:
        actor_result = run_actor_stage(
            scenario_path=args.scenarios,
            run_dir=args.run_dir,
            fingerprint=fingerprint["sha256"],
            actor=lambda scenario: actor_process.call({"scenario": scenario}),
            expected_scenario_sha256=args.expected_scenario_sha256,
            resume=args.resume,
        )
    # The actor process has exited before the scorer process is started.
    score_fingerprint = canonical_sha256({
        "actor_fingerprint": fingerprint["sha256"],
        "gold_sha256": gold_hash,
        "scorer": args.scorer,
    })
    with PluginProcess("scorer", args.scorer, isolated_home) as scorer_process:
        score_result = score_actor_outputs(
            gold_path=args.gold,
            actor_stage=actor_result,
            run_dir=args.run_dir,
            fingerprint=score_fingerprint,
            scorer=lambda gold, actor_output: scorer_process.call({
                "gold": gold,
                "actor_output": actor_output,
            }),
            expected_gold_sha256=args.expected_gold_sha256,
        )
    print(json.dumps({
        "fingerprint": score_fingerprint,
        "actor": {key: actor_result[key] for key in ("status", "total", "completed", "failed", "scored_coverage")},
        "scorer": {key: score_result[key] for key in ("status", "total", "completed", "failed")},
    }, ensure_ascii=False, sort_keys=True))
    return 0 if actor_result["status"] == "completed" and score_result["status"] == "completed" else 1


def _prepare_isolated_home(path: Path, *, resume: bool) -> Path:
    home = path.resolve()
    if home == _REPOSITORY or _REPOSITORY in home.parents:
        raise ValueError("isolated home must be outside the repository")
    marker = home / ".stella-proactive-eval-home"
    if home.exists():
        if resume:
            if not marker.is_file():
                raise ValueError("resume isolated home lacks the evaluation marker")
        elif any(home.iterdir()):
            raise ValueError("new isolated home must be empty")
    else:
        home.mkdir(parents=True)
    marker.write_text("stella-proactive-eval-home/1\n", encoding="utf-8")
    return home


def _check_run_output(path: Path) -> None:
    output = path.resolve()
    if output == _REPOSITORY or _REPOSITORY in output.parents:
        try:
            relative = output.relative_to(_REPOSITORY)
            check = subprocess.run(
                ["git", "check-ignore", "-q", "--no-index", str(relative / "actor" / "checkpoint.json")],
                cwd=_REPOSITORY,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("cannot verify that in-repository run output is gitignored") from exc
        if check.returncode != 0:
            raise ValueError("run output inside the repository must be gitignored")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
