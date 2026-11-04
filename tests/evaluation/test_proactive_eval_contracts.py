# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import ValidationError

from core.evaluation.clock import VirtualClock
from core.evaluation.events import ReplayEvent, replay_events
from proactive_eval.adapters import (
    validate_actor_files,
    validate_dataset_files,
)
from proactive_eval.fingerprint import canonical_sha256, effective_config_sha256
from proactive_eval.legacy import read_legacy_memory_report
from proactive_eval.metrics import score_participation
from proactive_eval.plugins import PluginProcess
from proactive_eval.report import validate_proactive_report, write_proactive_report
from proactive_eval.runner import run_actor_stage, score_actor_outputs


def _subprocess_fixture_actor(scenario: dict) -> dict:
    assert "source_label" not in scenario
    return {"predictions": {event["event_id"]: "SPEAK" for event in scenario["events"]}}


def _subprocess_fixture_scorer(gold: dict, actor_output: dict) -> dict:
    return {"correct": actor_output["predictions"][gold["event_id"]] == gold["source_label"]}


def _scenario(scenario_id: str, episode_id: str = "episode-1", split: str = "test") -> dict:
    return {
        "schema": "stella-proactive-scenario/1",
        "scenario_id": scenario_id,
        "episode_id": episode_id,
        "source": {
            "dataset_id": "fixture",
            "config": "tiny",
            "revision": "fixture-r1",
            "adapter_version": "1",
            "unit": "decision_context",
        },
        "split": split,
        "trusted_bot": "bot-1",
        "connection_id": "connection-1",
        "scene": "fixture scene",
        "events": [
            {
                "event_id": "event-1",
                "sequence": 0,
                "speaker_id": "speaker-1",
                "subject_key": None,
                "source_kind": "group",
                "text": "fixture text",
                "arrived_at": "2026-11-04T00:00:00Z",
                "time_source": "synthetic",
                "native_reply_to": None,
                "mentions": [],
            }
        ],
        "accessible_memories": [],
        "clock": {
            "initial_wall_time": "2026-11-04T00:00:00Z",
            "initial_monotonic_ms": 0,
            "time_source": "synthetic",
        },
    }


def _gold(scenario_id: str = "case-1") -> dict:
    return {
        "schema": "stella-scorer-gold/1",
        "scenario_id": scenario_id,
        "event_id": "event-1",
        "label_origin": "synthetic_fixture",
        "source_label": "SPEAK",
        "allowed_actions": ["SPEAK"],
        "turn_window": None,
        "memory_requirement": "unknown",
        "support_evidence_ids": [],
        "forbidden_memory_ids": [],
        "annotation": {"annotator_count": 0, "agreement": None, "adjudicated": False},
    }


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def _valid_report() -> dict:
    fingerprint = {
        "sha256": "a" * 64,
        "components": {
            "code_commit": "fixture",
            "dirty_tree_digest": None,
            "dataset_registry_sha256": "b" * 64,
            "scenario_schema": "stella-proactive-scenario/1",
            "report_schema": "stella-proactive-report/1",
            "effective_config_sha256": None,
            "prompt_hashes": {},
            "model": {},
            "tokenizer": None,
            "backend": {},
            "dependencies": {},
            "platform_hardware": {},
            "seed": 20261104,
        },
    }
    metric = {
        "status": "scored", "numerator": 1, "denominator": 1, "value": 1.0,
        "reason": None, "confidence_interval_95": None,
    }
    return {
        "schema": "stella-proactive-report/1",
        "run_id": "fixture-run",
        "status": "pass",
        "evidence_level": "L0",
        "metric_definitions_version": "1",
        "fingerprint": fingerprint,
        "dataset": {
            "dataset_id": "fixture", "config": "tiny", "revision": "fixture-r1",
            "split": "fixture", "unit": "decision", "adapter_version": "1",
            "file_hashes": [], "raw_count": 1, "adapted_count": 1,
            "excluded_count": 0, "license": "local synthetic fixture",
        },
        "baseline": {"baseline_id": "none", "source_ref": "fixture", "condition": "fixture", "paired": False},
        "counts": {"total": 1, "completed": 1, "failed": 0, "skipped": 0, "not_applicable": 0},
        "metrics": {"macro_f1": metric},
        "traces": [],
        "cost": {"model_calls": 0, "input_tokens": 0, "output_tokens": 0, "wall_time_ms": 0, "peak_rss_bytes": None},
        "artifacts": [],
        "panels": {"aoede_participation": {"macro_f1": metric}, "mneme_memory": {}, "aoede_mneme_joint": {}},
    }


def test_actor_and_scorer_files_validate_and_preserve_episode_split(tmp_path: Path):
    scenarios = _write_jsonl(tmp_path / "scenarios.jsonl", [_scenario("case-1"), _scenario("case-2")])
    gold = _write_jsonl(tmp_path / "gold.jsonl", [_gold("case-1"), {**_gold("case-2"), "event_id": "event-1"}])

    loaded = validate_dataset_files(scenarios, gold)

    assert len(loaded.scenarios) == 2
    assert loaded.episode_splits == {"episode-1": "test"}
    assert len(loaded.scenario_sha256) == 64
    assert len(loaded.gold_sha256) == 64


def test_derived_episode_cannot_cross_dataset_splits(tmp_path: Path):
    path = _write_jsonl(tmp_path / "scenarios.jsonl", [_scenario("case-1", split="dev"), _scenario("case-2", split="test")])

    with pytest.raises(ValueError, match="cross splits"):
        validate_actor_files(path)


def test_actor_schema_rejects_gold_fields_and_zero_sample_runs(tmp_path: Path):
    leaked = _scenario("case-1")
    leaked["source_label"] = "SPEAK"
    path = _write_jsonl(tmp_path / "leaked.jsonl", [leaked])
    with pytest.raises(ValueError, match="schema violation"):
        validate_actor_files(path)

    empty = _write_jsonl(tmp_path / "empty.jsonl", [])
    with pytest.raises(ValueError, match="zero actor scenarios"):
        validate_actor_files(empty)

    valid_actor = _write_jsonl(tmp_path / "valid-actor.jsonl", [_scenario("case-1")])
    empty_gold = _write_jsonl(tmp_path / "empty-gold.jsonl", [])
    with pytest.raises(ValueError, match="zero scorer gold rows"):
        validate_dataset_files(valid_actor, empty_gold)


def test_expected_source_hash_mismatch_is_rejected(tmp_path: Path):
    actor = _write_jsonl(tmp_path / "scenarios.jsonl", [_scenario("case-1")])
    gold = _write_jsonl(tmp_path / "gold.jsonl", [_gold()])
    with pytest.raises(ValueError, match="scenario SHA-256 mismatch"):
        validate_dataset_files(actor, gold, expected_scenario_sha256="0" * 64)
    with pytest.raises(ValueError, match="gold SHA-256 mismatch"):
        validate_dataset_files(actor, gold, expected_gold_sha256="0" * 64)


def test_actor_run_never_receives_gold_and_scorer_runs_after_actor(tmp_path: Path):
    scenarios = _write_jsonl(tmp_path / "scenarios.jsonl", [_scenario("case-1")])
    gold = _write_jsonl(tmp_path / "gold.jsonl", [_gold()])
    order: list[str] = []

    def actor(scenario: dict) -> dict:
        order.append("actor")
        assert "source_label" not in scenario
        assert "gold" not in scenario
        assert "gold" not in scenario["events"][0]
        return {"predictions": {"event-1": "SPEAK"}}

    actor_result = run_actor_stage(
        scenario_path=scenarios,
        run_dir=tmp_path / "run",
        fingerprint="a" * 64,
        actor=actor,
    )

    def scorer(gold_row: dict, actor_output: dict) -> dict:
        order.append("scorer")
        return {"correct": actor_output["predictions"][gold_row["event_id"]] == gold_row["source_label"]}

    score_result = score_actor_outputs(
        gold_path=gold, actor_stage=actor_result, run_dir=tmp_path / "run",
        fingerprint="a" * 64, scorer=scorer,
    )

    assert order == ["actor", "scorer"]
    assert score_result["records"][0]["score"] == {"correct": True}


def test_actor_and_scorer_plugins_run_in_separate_processes(tmp_path: Path):
    scenario = _scenario("case-1")
    gold = _gold()
    home = tmp_path / "isolated-home"
    home.mkdir()

    with PluginProcess(
        "actor", "tests.evaluation.test_proactive_eval_contracts:_subprocess_fixture_actor", home
    ) as actor:
        output = actor.call({"scenario": scenario})
    with PluginProcess(
        "scorer", "tests.evaluation.test_proactive_eval_contracts:_subprocess_fixture_scorer", home
    ) as scorer:
        result = scorer.call({"gold": gold, "actor_output": output})

    assert result == {"correct": True}


def test_resume_rejects_fingerprint_mismatch(tmp_path: Path):
    scenarios = _write_jsonl(tmp_path / "scenarios.jsonl", [_scenario("case-1")])
    run_dir = tmp_path / "run"
    run_actor_stage(scenario_path=scenarios, run_dir=run_dir, fingerprint="a" * 64, actor=lambda _: {})

    with pytest.raises(ValueError, match="fingerprint does not match"):
        run_actor_stage(
            scenario_path=scenarios, run_dir=run_dir, fingerprint="b" * 64,
            actor=lambda _: pytest.fail("must reject before actor call"), resume=True,
        )


def test_resume_rejects_changed_actor_input_hash(tmp_path: Path):
    scenario = _scenario("case-1")
    path = _write_jsonl(tmp_path / "scenarios.jsonl", [scenario])
    run_dir = tmp_path / "run"
    run_actor_stage(scenario_path=path, run_dir=run_dir, fingerprint="d" * 64, actor=lambda _: {})
    scenario["scene"] = "changed after the first run"
    _write_jsonl(path, [scenario])

    with pytest.raises(ValueError, match="actor scenario input hash does not match"):
        run_actor_stage(
            scenario_path=path, run_dir=run_dir, fingerprint="d" * 64,
            actor=lambda _: pytest.fail("must reject changed input before actor"), resume=True,
        )


def test_resume_recovers_a_crash_and_discards_only_incomplete_tail(tmp_path: Path):
    scenarios = _write_jsonl(tmp_path / "scenarios.jsonl", [
        _scenario("case-1", "episode-1"),
        _scenario("case-2", "episode-2"),
        _scenario("case-3", "episode-3"),
    ])
    run_dir = tmp_path / "run"
    calls: list[str] = []

    def crashing_actor(scenario: dict) -> dict:
        calls.append(scenario["scenario_id"])
        if scenario["scenario_id"] == "case-2":
            raise KeyboardInterrupt
        return {"decision": "WAIT"}

    with pytest.raises(KeyboardInterrupt):
        run_actor_stage(scenario_path=scenarios, run_dir=run_dir, fingerprint="c" * 64, actor=crashing_actor)

    result_path = run_dir / "actor" / "results.jsonl"
    with result_path.open("ab") as stream:
        stream.write(b'{"scenario_id":"partial')

    calls.clear()
    result = run_actor_stage(
        scenario_path=scenarios,
        run_dir=run_dir,
        fingerprint="c" * 64,
        actor=lambda scenario: calls.append(scenario["scenario_id"]) or {"decision": "WAIT"},
        resume=True,
    )

    assert calls == ["case-2", "case-3"]
    assert result["status"] == "completed"
    assert (result["completed"], result["failed"], result["total"]) == (3, 0, 3)
    assert result["recovered_truncated_bytes"] > 0
    assert result["recovery_retries"] == 1


def test_two_fixture_replays_have_the_same_event_trace(tmp_path: Path):
    scenarios = _write_jsonl(tmp_path / "scenarios.jsonl", [
        _scenario("case-1", "episode-1"), _scenario("case-2", "episode-2")
    ])
    def actor(scenario: dict) -> dict:
        return {
            "event_trace": [event["event_id"] for event in scenario["events"]],
            "final_action": "WAIT",
        }
    first = run_actor_stage(
        scenario_path=scenarios, run_dir=tmp_path / "run-1", fingerprint="e" * 64, actor=actor
    )
    second = run_actor_stage(
        scenario_path=scenarios, run_dir=tmp_path / "run-2", fingerprint="e" * 64, actor=actor
    )
    def project(result: dict) -> list[tuple]:
        return [
            (row["scenario_id"], row["event_ids"], row["actor_output"])
            for row in result["records"]
        ]

    assert project(first) == project(second)


def test_source_label_metrics_match_frozen_hand_calculation():
    result = score_participation([
        ("SILENT", "SILENT"), ("SILENT", "SPEAK"), ("SPEAK", "SPEAK"),
        ("SPEAK", "SILENT"), ("SILENT", "SPEAK"), ("SPEAK", "SILENT"),
    ])

    assert result["confusion_matrix"] == {
        "SPEAK": {"SPEAK": 1, "SILENT": 2},
        "SILENT": {"SPEAK": 2, "SILENT": 1},
    }
    assert result["value"] == pytest.approx(1 / 3)
    assert result["false_interruption_rate"] == pytest.approx(2 / 3)
    assert result["missed_intervention_rate"] == pytest.approx(2 / 3)
    assert score_participation([])["status"] == "not_applicable"


def test_event_timeline_orders_timers_before_equal_time_messages():
    start = datetime(2026, 11, 4, tzinfo=timezone.utc)
    clock = VirtualClock(start)
    seen: list[str] = []
    events = [
        ReplayEvent("message-late-seq", start + timedelta(seconds=2), "message", 1, {}),
        ReplayEvent("timer", start + timedelta(seconds=2), "timer", 9, {}),
        ReplayEvent("message-first", start + timedelta(seconds=2), "message", 0, {}),
        ReplayEvent("early", start + timedelta(seconds=1), "message", 4, {}),
    ]

    dispatched = replay_events(events, clock=clock, handle=lambda event: seen.append(event.event_id))

    assert dispatched == ["early", "timer", "message-first", "message-late-seq"]
    assert seen == dispatched
    assert clock.now() == start + timedelta(seconds=2)


def test_fingerprint_config_is_canonical_and_rejects_secrets():
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})
    assert effective_config_sha256({"seed": 7, "mode": "fixture"}) == effective_config_sha256({"mode": "fixture", "seed": 7})
    with pytest.raises(ValueError, match="secret-bearing"):
        effective_config_sha256({"llm_api_key": "must-not-enter-config-fingerprint"})


def test_report_schema_validation_and_atomic_write(tmp_path: Path):
    report = _valid_report()
    validate_proactive_report(report)
    digest = write_proactive_report(tmp_path / "report.json", report)
    assert (tmp_path / "report.json").is_file()
    assert len(digest) == 64

    invalid = _valid_report()
    invalid["counts"]["total"] = 0
    invalid["metrics"]["macro_f1"]["denominator"] = 0
    with pytest.raises(ValidationError):
        validate_proactive_report(invalid)


def test_legacy_report_adapter_reads_without_rewriting_source(tmp_path: Path):
    path = tmp_path / "old-report.json"
    path.write_text(json.dumps({
        "report_schema": "memory-eval-report/1",
        "generated_at": "2026-10-31T00:00:00Z",
        "git_head": "old-commit",
        "dataset": {"name": "locomo"},
        "channel": "rule",
        "summary": {"total": 1},
    }), encoding="utf-8")
    before = path.read_bytes()

    result = read_legacy_memory_report(path)

    assert result["evidence_status"] == "historical_reference"
    assert path.read_bytes() == before
