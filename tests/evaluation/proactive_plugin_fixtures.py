# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Stdlib-only plugin entry points for isolated proactive_eval worker processes.

Worker subprocesses run with ``PYTHONNOUSERSITE=1`` and a minimal environment,
so the modules named in ``--actor`` / ``--scorer`` specifications must stay
importable without third-party packages. Test modules import pytest and
jsonschema at module level, which fails on hosts that keep those in the user
site-packages; these fixtures therefore live in their own module.
"""

from __future__ import annotations


def _subprocess_fixture_actor(scenario: dict) -> dict:
    assert "source_label" not in scenario
    return {"predictions": {event["event_id"]: "SPEAK" for event in scenario["events"]}}


def _subprocess_fixture_scorer(gold: dict, actor_output: dict) -> dict:
    return {"correct": actor_output["predictions"][gold["event_id"]] == gold["source_label"]}


def _actor(scenario: dict) -> dict:
    return {"predictions": {scenario["events"][-1]["event_id"]: "SPEAK"}}


def _different_actor(scenario: dict) -> dict:
    raise AssertionError(f"replacement actor must not run during resume: {scenario['scenario_id']}")


def _scorer(gold: dict, actor_output: dict) -> dict:
    prediction = actor_output["predictions"][gold["event_id"]]
    return {"correct": prediction == gold["source_label"]}
