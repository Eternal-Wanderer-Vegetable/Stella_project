# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Strict JSONL boundary for actor-only scenarios and scorer-only labels."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

_SCHEMA_DIR = Path(__file__).with_name("schemas")


@dataclass(frozen=True)
class DatasetFiles:
    scenarios: tuple[dict[str, Any], ...]
    gold: tuple[dict[str, Any], ...]
    scenario_sha256: str
    gold_sha256: str
    episode_splits: dict[str, str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_registry(path: Path) -> dict[str, Any]:
    registry = _read_json(path)
    schema = _read_json(_SCHEMA_DIR / "dataset-registry-1.schema.json")
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(registry)
    ids = [str(row["dataset_id"]) for row in registry["datasets"]]
    if len(ids) != len(set(ids)):
        raise ValueError("dataset registry contains duplicate dataset_id values")
    return registry


def read_actor_scenarios(path: Path) -> tuple[dict[str, Any], ...]:
    """Load only the actor-visible file; this function never opens scorer gold."""
    return _read_jsonl(path, "stella-proactive-scenario-1.schema.json")


def read_scorer_gold(path: Path) -> tuple[dict[str, Any], ...]:
    """Load the scorer sidecar separately, after actor execution has finished."""
    return _read_jsonl(path, "stella-scorer-gold-1.schema.json")


def validate_dataset_files(
    scenario_path: Path,
    gold_path: Path,
    *,
    expected_scenario_sha256: str | None = None,
    expected_gold_sha256: str | None = None,
) -> DatasetFiles:
    scenario_hash = sha256_file(scenario_path)
    gold_hash = sha256_file(gold_path)
    verify_expected_hash("scenario", scenario_hash, expected_scenario_sha256)
    verify_expected_hash("gold", gold_hash, expected_gold_sha256)
    scenarios = read_actor_scenarios(scenario_path)
    gold = read_scorer_gold(gold_path)
    if not scenarios:
        raise ValueError("zero actor scenarios are not a valid evaluation")
    if not gold:
        raise ValueError("zero scorer gold rows are not a valid evaluation")
    _validate_actor_identity_and_splits(scenarios)
    _validate_gold_references(scenarios, gold)
    return DatasetFiles(
        scenarios=scenarios,
        gold=gold,
        scenario_sha256=scenario_hash,
        gold_sha256=gold_hash,
        episode_splits={
            str(row["episode_id"]): str(row["split"]) for row in scenarios
        },
    )


def validate_actor_files(
    scenario_path: Path, *, expected_sha256: str | None = None
) -> tuple[dict[str, Any], ...]:
    """Validate actor scenarios without reading or hashing the gold sidecar."""
    verify_expected_hash("scenario", sha256_file(scenario_path), expected_sha256)
    scenarios = read_actor_scenarios(scenario_path)
    if not scenarios:
        raise ValueError("zero actor scenarios are not a valid evaluation")
    _validate_actor_identity_and_splits(scenarios)
    return scenarios


def _validate_actor_identity_and_splits(scenarios: tuple[dict[str, Any], ...]) -> None:
    scenario_ids: set[str] = set()
    event_ids: set[tuple[str, str]] = set()
    episode_splits: dict[str, str] = {}
    for scenario in scenarios:
        scenario_id = str(scenario["scenario_id"])
        episode_id = str(scenario["episode_id"])
        split = str(scenario["split"])
        if scenario_id in scenario_ids:
            raise ValueError(f"duplicate scenario_id: {scenario_id}")
        scenario_ids.add(scenario_id)
        previous = episode_splits.setdefault(episode_id, split)
        if previous != split:
            raise ValueError(
                f"derived scenarios from episode {episode_id!r} cross splits: "
                f"{previous!r} and {split!r}"
            )
        for event in scenario["events"]:
            key = (scenario_id, str(event["event_id"]))
            if key in event_ids:
                raise ValueError(f"duplicate event id in scenario {scenario_id!r}: {key[1]}")
            event_ids.add(key)


def _validate_gold_references(
    scenarios: tuple[dict[str, Any], ...], gold: tuple[dict[str, Any], ...]
) -> None:
    valid = {
        (str(scenario["scenario_id"]), str(event["event_id"]))
        for scenario in scenarios
        for event in scenario["events"]
    }
    seen: set[tuple[str, str]] = set()
    for row in gold:
        key = (str(row["scenario_id"]), str(row["event_id"]))
        if key not in valid:
            raise ValueError(f"gold references an unknown actor event: {key}")
        if key in seen:
            raise ValueError(f"duplicate scorer gold row: {key}")
        seen.add(key)


def _read_jsonl(path: Path, schema_name: str) -> tuple[dict[str, Any], ...]:
    if not path.is_file():
        raise FileNotFoundError(path)
    schema = _read_json(_SCHEMA_DIR / schema_name)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(f"blank JSONL row at {path}:{line_number}")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {exc.msg}") from exc
            errors = sorted(validator.iter_errors(row), key=lambda err: list(err.path))
            if errors:
                error = errors[0]
                location = "/".join(str(part) for part in error.path) or "<root>"
                raise ValueError(
                    f"schema violation at {path}:{line_number} ({location}): {error.message}"
                )
            rows.append(row)
    return tuple(rows)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def verify_expected_hash(name: str, actual: str, expected: str | None) -> None:
    if expected is None:
        return
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError(f"expected {name} SHA-256 must be 64 lowercase hexadecimal characters")
    if actual != expected:
        raise ValueError(f"{name} SHA-256 mismatch: expected {expected}, got {actual}")


__all__ = [
    "DatasetFiles",
    "load_registry",
    "read_actor_scenarios",
    "read_scorer_gold",
    "sha256_file",
    "validate_actor_files",
    "validate_dataset_files",
    "verify_expected_hash",
]
