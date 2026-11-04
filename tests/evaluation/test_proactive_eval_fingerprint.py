# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from proactive_eval.adapters import load_registry
from proactive_eval.cli import main as proactive_eval_main


def _scenario(revision: str) -> dict:
    return {
        "schema": "stella-proactive-scenario/1",
        "scenario_id": "resume-plugin-case",
        "episode_id": "resume-plugin-episode",
        "source": {
            "dataset_id": "when2speak",
            "config": "token",
            "revision": revision,
            "adapter_version": "1",
            "unit": "decision_context",
        },
        "split": "test",
        "trusted_bot": "stella-eval",
        "connection_id": "when2speak-fixture",
        "scene": "Synthetic group conversation for the resume fingerprint contract.",
        "events": [{
            "event_id": "resume-plugin-event",
            "sequence": 0,
            "speaker_id": "speaker-1",
            "subject_key": None,
            "source_kind": "group",
            "text": "Synthetic fixture message.",
            "arrived_at": "2026-11-04T00:00:00Z",
            "time_source": "synthetic",
            "native_reply_to": None,
            "mentions": [],
        }],
        "accessible_memories": [],
        "clock": {
            "initial_wall_time": "2026-11-04T00:00:00Z",
            "initial_monotonic_ms": 0,
            "time_source": "synthetic",
        },
    }


def _gold() -> dict:
    return {
        "schema": "stella-scorer-gold/1",
        "scenario_id": "resume-plugin-case",
        "event_id": "resume-plugin-event",
        "label_origin": "synthetic_fixture",
        "source_label": "SPEAK",
        "allowed_actions": ["SPEAK"],
        "turn_window": None,
        "memory_requirement": "unknown",
        "support_evidence_ids": [],
        "forbidden_memory_ids": [],
        "annotation": {"annotator_count": 0, "agreement": None, "adjudicated": False},
    }


def _actor(scenario: dict) -> dict:
    return {"predictions": {scenario["events"][-1]["event_id"]: "SPEAK"}}


def _different_actor(scenario: dict) -> dict:
    raise AssertionError(f"replacement actor must not run during resume: {scenario['scenario_id']}")


def _scorer(gold: dict, actor_output: dict) -> dict:
    prediction = actor_output["predictions"][gold["event_id"]]
    return {"correct": prediction == gold["source_label"]}


def _write_jsonl(path: Path, rows: list[dict]) -> str:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_resume_rejects_a_different_actor_plugin(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("STELLA_HOME", str(tmp_path / "outer-home"))
    repository = Path(__file__).resolve().parents[2]
    registry = load_registry(repository / "proactive_eval" / "dataset-registry.json")
    dataset = next(row for row in registry["datasets"] if row["dataset_id"] == "when2speak")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    scenario_path = tmp_path / "scenarios.jsonl"
    gold_path = tmp_path / "gold.jsonl"
    scenario_hash = _write_jsonl(scenario_path, [_scenario(dataset["source"]["revision"])])
    gold_hash = _write_jsonl(gold_path, [_gold()])
    args = [
        "run",
        "--registry", str(registry_path),
        "--dataset-id", "when2speak",
        "--scenarios", str(scenario_path),
        "--gold", str(gold_path),
        "--expected-scenario-sha256", scenario_hash,
        "--expected-gold-sha256", gold_hash,
        "--run-dir", str(tmp_path / "run"),
        "--isolated-home", str(tmp_path / "isolated-home"),
        "--actor", "tests.evaluation.test_proactive_eval_fingerprint:_actor",
        "--scorer", "tests.evaluation.test_proactive_eval_fingerprint:_scorer",
    ]

    assert proactive_eval_main(args) == 0
    capsys.readouterr()

    args[args.index("--actor") + 1] = (
        "tests.evaluation.test_proactive_eval_fingerprint:_different_actor"
    )
    args.append("--resume")
    assert proactive_eval_main(args) == 2
    assert "run fingerprint does not match" in capsys.readouterr().err
