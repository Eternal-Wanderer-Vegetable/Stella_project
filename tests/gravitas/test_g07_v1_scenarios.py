# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

import json

from gravitas.config import default_config
from scripts.run_gravitas_evaluation import (
    ROOT,
    SCENARIO_IDS,
    _evaluate_seeded_traces,
    _load_suite,
    _source_fingerprint,
    _trace_model,
)


def test_v1_scenario_matrix_matches_the_immutable_plan():
    suite_dir = ROOT / "tests" / "gravitas" / "fixtures" / "v1"
    suite, suite_path = _load_suite(suite_dir)
    assert suite["policy_version"] == f"gravitas-config-schema-v{default_config().schema_version}"
    inventory = json.loads(
        (ROOT / "docs" / "plans" / "2026-10-21-gravitas-inventory.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        scenario["id"]: scenario
        for scenario in inventory["scenarios"]
        if scenario["id"] in SCENARIO_IDS
    }
    assert [scenario["id"] for scenario in suite["scenarios"]] == list(SCENARIO_IDS)
    for scenario in suite["scenarios"]:
        planned = expected[scenario["id"]]
        assert scenario["required_invariants"] == planned["required_invariants"]
        assert planned["release"] == "v1"
        assert scenario["tests"]
    fingerprint = _source_fingerprint(suite, suite_path)
    assert fingerprint["scripts/run_gravitas_evaluation.py"]
    assert fingerprint["tests/gravitas/fixtures/v1/suite.json"]


def test_generated_state_trace_is_seeded_bounded_and_shadow_equivalent():
    off_a = _trace_model(20261021, 256, "off")
    off_b = _trace_model(20261021, 256, "off")
    shadow = _trace_model(20261021, 256, "shadow")
    other_seed = _trace_model(20261022, 256, "off")

    assert off_a["trace_digest"] == off_b["trace_digest"]
    assert off_a["effect_digest"] == shadow["effect_digest"]
    assert off_a["trace_digest"] != other_seed["trace_digest"]
    assert len(off_a["events"]) == 256
    assert any(event["action"] == "pressure" for event in off_a["events"])


def test_generated_state_trace_accepts_plan_step_bounds():
    assert len(_trace_model(3, 100, "off")["events"]) == 100
    assert len(_trace_model(3, 1000, "shadow")["events"]) == 1000


def test_ci_seed_set_is_fixed_replayable_and_shadow_equivalent():
    first = _evaluate_seeded_traces(20261021, 256, 10)
    second = _evaluate_seeded_traces(20261021, 256, 10)
    assert first == second
    assert first["first_seed"] == 20261021
    assert first["seed_count"] == 10
    assert [item["seed"] for item in first["results"]] == list(range(20261021, 20261031))
    assert first["all_effects_equivalent"]
