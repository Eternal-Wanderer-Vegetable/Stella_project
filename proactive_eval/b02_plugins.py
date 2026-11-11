# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Zero-generation, zero-memory actor and scorer plugins for benchmark B02."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def always_silent(scenario: dict[str, Any]) -> dict[str, Any]:
    """Never initiate a response."""
    _require_no_memory(scenario)
    return {"action": "DROP", "method": "always-silent/1", "reason": "fixed baseline"}


def always_speak(scenario: dict[str, Any]) -> dict[str, Any]:
    """Initiate a response at every decision point."""
    _require_no_memory(scenario)
    return {"action": "SPEAK", "method": "always-speak/1", "reason": "fixed baseline"}


def last_explicit_question(scenario: dict[str, Any]) -> dict[str, Any]:
    """Speak only when the current message ends in an explicit question mark."""
    _require_no_memory(scenario)
    events = scenario["events"]
    current_text = str(events[-1]["text"]).rstrip()
    asked = current_text.endswith(("?", "？"))
    return {
        "action": "SPEAK" if asked else "DROP",
        "method": "last-explicit-question/1",
        "reason": "current message ends with a question mark" if asked else "no trailing question mark",
    }


def score_source_label(
    gold: dict[str, Any], actor_output: Mapping[str, Any]
) -> dict[str, Any]:
    """Map common SPEAK/DROP actions to each source's binary label."""
    action = actor_output.get("action")
    predicted = {"SPEAK": "SPEAK", "DROP": "SILENT"}.get(action)
    if predicted is None:
        raise ValueError(f"unsupported baseline action: {action!r}")
    expected = gold["source_label"]
    if expected not in ("SPEAK", "SILENT"):
        raise ValueError(f"unsupported scorer label: {expected!r}")
    if predicted == expected:
        error_kind = None
    elif predicted == "SPEAK":
        error_kind = "false_interruption"
    else:
        error_kind = "missed_intervention"
    return {
        "prediction": predicted,
        "expected": expected,
        "correct": predicted == expected,
        "error_kind": error_kind,
        "method": actor_output.get("method"),
    }


def _require_no_memory(scenario: dict[str, Any]) -> None:
    if scenario.get("accessible_memories"):
        raise ValueError("B02 baselines require an empty memory context")
    events = scenario.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("B02 baseline requires at least one observed event")


__all__ = [
    "always_silent",
    "always_speak",
    "last_explicit_question",
    "score_source_label",
]
