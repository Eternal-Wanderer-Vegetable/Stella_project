"""Stable sample matrix and strict oracle handling for the P6 evaluator."""

import pytest

from scripts.evaluate_dialogue_attribution import (
    BATCH_ABLATION_SCENARIOS,
    BATCH_SCENARIOS,
    build_batch_jobs,
    load_batch_fixtures,
    resolve_fixture_oracle,
)


def test_oracle_uses_top_level_when_only_top_level_is_present():
    oracle = {"task": "answer the current user", "acceptable": ["sender"], "critical_fail": []}
    assert resolve_fixture_oracle({"fixture_id": "case", "oracle": oracle}) == oracle


def test_oracle_falls_back_to_evaluation_then_failing_round():
    oracle = {"task": "answer the current user", "acceptable": ["sender"], "critical_fail": []}
    assert resolve_fixture_oracle({"fixture_id": "case", "evaluation": {"oracle": oracle}}) == oracle
    assert resolve_fixture_oracle({"fixture_id": "case", "failing_round": {"oracle": oracle}}) == oracle


def test_oracle_rejects_conflict_or_missing_contract():
    first = {"task": "one", "acceptable": ["a"], "critical_fail": []}
    second = {"task": "two", "acceptable": ["a"], "critical_fail": []}
    with pytest.raises(ValueError, match="oracle conflict"):
        resolve_fixture_oracle({
            "fixture_id": "case", "oracle": first,
            "evaluation": {"oracle": second},
        })
    with pytest.raises(ValueError, match="oracle missing"):
        resolve_fixture_oracle({"fixture_id": "case"})
    with pytest.raises(ValueError, match="oracle is incomplete"):
        resolve_fixture_oracle({"fixture_id": "case", "oracle": {"task": "missing lists"}})


def test_frozen_fixture_set_has_26_valid_oracles():
    fixtures = load_batch_fixtures("tests/fixtures/dialogue_attribution")
    assert len(BATCH_SCENARIOS) == len(fixtures) == 26
    assert [entry["scenario_number"] for entry in fixtures] == list(range(1, 27))
    assert all(entry["oracle"]["task"] for entry in fixtures)


def test_batch_denominator_and_ablation_job_ids_are_fixed_and_stable():
    fixtures = [
        {"fixture": {"fixture_id": f"fixture-{index + 1}"}}
        for index in range(26)
    ]
    jobs = build_batch_jobs(fixtures)
    assert len(jobs) == 440
    assert sum(job["variant"] == "C" for job in jobs) == 260
    for variant in ("A", "B", "D"):
        selected = [job for job in jobs if job["variant"] == variant]
        assert len(selected) == 60
        assert {job["scenario_number"] for job in selected} == {
            scenario_index + 1 for scenario_index in BATCH_ABLATION_SCENARIOS
        }
    assert jobs[0]["job_id"] == "C:01:01"
    assert jobs[-1]["job_id"] == "D:21:10"
    assert [job["job_id"] for job in jobs] == [job["job_id"] for job in build_batch_jobs(fixtures)]
    with pytest.raises(ValueError, match="fixed at 10"):
        build_batch_jobs(fixtures, repeats=9)
