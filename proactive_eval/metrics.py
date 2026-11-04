# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Source-label metrics with explicit support and denominator reporting."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

LABELS = ("SPEAK", "SILENT")


def score_participation(
    pairs: Iterable[tuple[str, str]],
) -> dict[str, Any]:
    """Score (gold, prediction) pairs without turning an empty set into PASS."""
    matrix = {gold: dict.fromkeys(LABELS, 0) for gold in LABELS}
    not_applicable = 0
    total = 0
    for gold, prediction in pairs:
        if gold == "NOT_APPLICABLE":
            not_applicable += 1
            continue
        if gold not in LABELS or prediction not in LABELS:
            raise ValueError(f"unsupported participation label pair: {gold!r}, {prediction!r}")
        matrix[gold][prediction] += 1
        total += 1
    if total == 0:
        return {
            "status": "not_applicable",
            "reason": "no eligible SPEAK/SILENT source labels",
            "numerator": None,
            "denominator": 0,
            "value": None,
            "eligible": 0,
            "not_applicable": not_applicable,
            "confusion_matrix": matrix,
            "class_metrics": {label: _class_metrics(matrix, label) for label in LABELS},
        }

    per_class = {label: _class_metrics(matrix, label) for label in LABELS}
    macro_f1 = sum(float(per_class[label]["f1"]) for label in LABELS) / len(LABELS)
    false_interruptions = matrix["SILENT"]["SPEAK"]
    missed_interventions = matrix["SPEAK"]["SILENT"]
    silent_support = sum(matrix["SILENT"].values())
    speak_support = sum(matrix["SPEAK"].values())
    return {
        "status": "scored",
        "numerator": macro_f1,
        "denominator": total,
        "value": macro_f1,
        "eligible": total,
        "not_applicable": not_applicable,
        "confusion_matrix": matrix,
        "class_metrics": per_class,
        "false_interruption_rate": _ratio(false_interruptions, silent_support),
        "false_interruption_numerator": false_interruptions,
        "false_interruption_denominator": silent_support,
        "missed_intervention_rate": _ratio(missed_interventions, speak_support),
        "missed_intervention_numerator": missed_interventions,
        "missed_intervention_denominator": speak_support,
    }


def _class_metrics(matrix: Mapping[str, Mapping[str, int]], label: str) -> dict[str, Any]:
    true_positive = matrix[label][label]
    false_positive = sum(matrix[other][label] for other in LABELS if other != label)
    false_negative = sum(matrix[label][other] for other in LABELS if other != label)
    support = sum(matrix[label].values())
    predicted = sum(matrix[other][label] for other in LABELS)
    precision = _ratio(true_positive, predicted)
    recall = _ratio(true_positive, support)
    # The preregistered zero-prediction convention is precision=N/A, F1=0.
    f1 = 0.0 if precision is None or recall is None or precision + recall == 0 else (
        2 * precision * recall / (precision + recall)
    )
    return {
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "support": support,
        "predicted": predicted,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


__all__ = ["LABELS", "score_participation"]
