# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Actor/scorer separated fixture runner with fingerprinted crash recovery."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from proactive_eval.adapters import (
    read_scorer_gold,
    sha256_file,
    validate_actor_files,
    verify_expected_hash,
)

RUN_SCHEMA = "stella-proactive-run-checkpoint/1"
_GOLD_ONLY_KEYS = {
    "gold", "gold_answer", "source_label", "label_origin", "turn_window",
    "support_evidence_ids", "forbidden_memory_ids", "should_abstain",
}

Actor = Callable[[dict[str, Any]], Mapping[str, Any]]
Scorer = Callable[[dict[str, Any], Mapping[str, Any]], Mapping[str, Any]]


def run_actor_stage(
    *,
    scenario_path: Path,
    run_dir: Path,
    fingerprint: str,
    actor: Actor,
    expected_scenario_sha256: str | None = None,
    resume: bool = False,
) -> dict[str, Any]:
    """Replay actor-visible scenarios and checkpoint each case atomically.

    The actor callback receives one closed-schema scenario at a time. The gold
    file is not opened or passed to this stage. A later resume must match both
    the run fingerprint and the actor-input file digest.
    """
    _validate_fingerprint(fingerprint)
    scenarios = validate_actor_files(scenario_path, expected_sha256=expected_scenario_sha256)
    scenario_hash = sha256_file(scenario_path)
    expected_ids = [str(row["scenario_id"]) for row in scenarios]
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("duplicate scenario ids are not a valid run")

    actor_dir = run_dir / "actor"
    actor_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = actor_dir / "checkpoint.json"
    results_path = actor_dir / "results.jsonl"
    if checkpoint_path.exists():
        if not resume:
            raise FileExistsError(f"run already has a checkpoint; pass resume=True: {actor_dir}")
        checkpoint = _load_json(checkpoint_path)
        if checkpoint.get("schema") != RUN_SCHEMA:
            raise ValueError("unsupported actor checkpoint schema")
        if checkpoint.get("fingerprint") != fingerprint:
            raise ValueError("resume rejected: run fingerprint does not match")
        if checkpoint.get("scenario_sha256") != scenario_hash:
            raise ValueError("resume rejected: actor scenario input hash does not match")
        if checkpoint.get("total") != len(scenarios):
            raise ValueError("resume rejected: scenario count does not match checkpoint")
    else:
        if resume:
            raise FileNotFoundError(f"resume requested but no actor checkpoint exists: {actor_dir}")
        if results_path.exists():
            raise ValueError("orphan actor results exist without a checkpoint")
        checkpoint = {
            "schema": RUN_SCHEMA,
            "fingerprint": fingerprint,
            "scenario_sha256": scenario_hash,
            "total": len(scenarios),
            "status": "running",
            "recovered_truncated_bytes": 0,
            "recovery_retries": 0,
            "attempts": {},
            "in_flight_scenario_id": None,
        }
        _atomic_json(checkpoint_path, checkpoint)

    records, recovered = _read_result_lines(results_path)
    if any(row.get("status") not in ("completed", "failed") for row in records):
        raise ValueError("actor checkpoint contains an unsupported result status")
    checkpoint["recovered_truncated_bytes"] = int(checkpoint.get("recovered_truncated_bytes", 0)) + recovered
    by_id = {str(row["scenario_id"]): row for row in records}
    unexpected = set(by_id).difference(expected_ids)
    if unexpected:
        raise ValueError(f"checkpoint contains scenarios absent from input: {sorted(unexpected)[:3]}")
    interrupted_id = checkpoint.get("in_flight_scenario_id")
    if interrupted_id in by_id:
        # A crash after the result append but before checkpoint replace is already durable.
        checkpoint["in_flight_scenario_id"] = None
        interrupted_id = None
        _atomic_json(checkpoint_path, checkpoint)

    for scenario in scenarios:
        scenario_id = str(scenario["scenario_id"])
        if scenario_id in by_id:
            continue
        attempts = dict(checkpoint.get("attempts") or {})
        attempts[scenario_id] = int(attempts.get(scenario_id, 0)) + 1
        checkpoint["attempts"] = attempts
        checkpoint["in_flight_scenario_id"] = scenario_id
        if scenario_id == interrupted_id:
            checkpoint["recovery_retries"] = int(checkpoint.get("recovery_retries", 0)) + 1
            interrupted_id = None
        _atomic_json(checkpoint_path, checkpoint)
        actor_input = json.loads(json.dumps(scenario, ensure_ascii=False))
        started = time.monotonic()
        try:
            output = actor(actor_input)
            if not isinstance(output, Mapping):
                raise TypeError("actor must return a JSON object")
            _reject_gold_only_output(output)
            # Ensure callback results are JSON-safe before committing a row.
            encoded_output = json.loads(json.dumps(output, ensure_ascii=False, sort_keys=True))
            record = {
                "scenario_id": scenario_id,
                "episode_id": str(scenario["episode_id"]),
                "split": str(scenario["split"]),
                "event_ids": [str(event["event_id"]) for event in scenario["events"]],
                "status": "completed",
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                "actor_output": encoded_output,
            }
        except Exception as exc:
            record = {
                "scenario_id": scenario_id,
                "episode_id": str(scenario["episode_id"]),
                "split": str(scenario["split"]),
                "event_ids": [str(event["event_id"]) for event in scenario["events"]],
                "status": "failed",
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
                "failure": {
                    "type": type(exc).__name__,
                    "message_sha256": hashlib.sha256(str(exc).encode("utf-8", errors="replace")).hexdigest(),
                },
            }
        _append_json_line(results_path, record)
        records.append(record)
        by_id[scenario_id] = record
        checkpoint["in_flight_scenario_id"] = None
        checkpoint.update(_count_fields(records, len(scenarios)))
        _atomic_json(checkpoint_path, checkpoint)

    counts = _count_fields(records, len(scenarios))
    if len(records) != len(scenarios) or counts["completed"] + counts["failed"] != len(scenarios):
        raise ValueError("actor checkpoint counts do not reconcile to the input sample count")
    checkpoint.update(counts)
    checkpoint["in_flight_scenario_id"] = None
    checkpoint["status"] = "partial" if counts["failed"] else "completed"
    _atomic_json(checkpoint_path, checkpoint)
    return {**checkpoint, "records": records}


def score_actor_outputs(
    *,
    gold_path: Path,
    actor_stage: Mapping[str, Any],
    run_dir: Path,
    fingerprint: str,
    scorer: Scorer,
    expected_gold_sha256: str | None = None,
) -> dict[str, Any]:
    """Load scorer-only labels after actor completion and write score rows."""
    _validate_fingerprint(fingerprint)
    gold_rows = read_scorer_gold(gold_path)
    if not gold_rows:
        raise ValueError("zero scorer gold rows are not a valid scored run")
    outputs = {
        str(row["scenario_id"]): row
        for row in actor_stage.get("records", [])
        if row.get("status") == "completed"
    }
    valid_events = {
        (scenario_id, event_id)
        for row in actor_stage.get("records", [])
        for scenario_id in [str(row["scenario_id"])]
        for event_id in row.get("event_ids", [])
    }
    for gold in gold_rows:
        key = (str(gold["scenario_id"]), str(gold["event_id"]))
        if key not in valid_events:
            raise ValueError(f"scorer gold references an event missing from actor output: {key}")
    score_dir = run_dir / "scorer"
    score_dir.mkdir(parents=True, exist_ok=True)
    meta_path = score_dir / "checkpoint.json"
    results_path = score_dir / "results.jsonl"
    score_hash = sha256_file(gold_path)
    verify_expected_hash("gold", score_hash, expected_gold_sha256)
    if meta_path.exists():
        meta = _load_json(meta_path)
        if meta.get("schema") != "stella-proactive-scorer-checkpoint/1":
            raise ValueError("unsupported scorer checkpoint schema")
        if meta.get("total") != len(gold_rows):
            raise ValueError("scorer resume rejected: gold row count does not match checkpoint")
        if meta.get("fingerprint") != fingerprint or meta.get("gold_sha256") != score_hash:
            raise ValueError("scorer resume rejected: fingerprint or gold hash does not match")
        done_rows, _ = _read_result_lines(results_path)
        done = {(str(row["scenario_id"]), str(row["event_id"])) for row in done_rows}
        expected_gold = {(str(row["scenario_id"]), str(row["event_id"])) for row in gold_rows}
        if not done.issubset(expected_gold):
            raise ValueError("scorer checkpoint contains rows absent from the pinned gold file")
    else:
        if results_path.exists():
            raise ValueError("orphan scorer results exist without a checkpoint")
        if meta_path.parent.exists() and any(meta_path.parent.iterdir()):
            raise FileExistsError(f"scorer output directory is not empty: {score_dir}")
        done = set()
        done_rows = []
        meta = {
            "schema": "stella-proactive-scorer-checkpoint/1",
            "fingerprint": fingerprint,
            "gold_sha256": score_hash,
            "status": "running",
            "total": len(gold_rows),
        }
        _atomic_json(meta_path, meta)

    for gold in gold_rows:
        key = (str(gold["scenario_id"]), str(gold["event_id"]))
        if key in done:
            continue
        actor_row = outputs.get(key[0])
        if actor_row is None:
            record = {
                "scenario_id": key[0], "event_id": key[1], "status": "not_scored",
                "reason": "actor scenario failed or is absent",
            }
        else:
            score = scorer(gold, actor_row["actor_output"])
            if not isinstance(score, Mapping):
                raise TypeError("scorer must return a JSON object")
            encoded_score = json.loads(json.dumps(score, ensure_ascii=False, sort_keys=True))
            record = {"scenario_id": key[0], "event_id": key[1], "status": "scored", "score": encoded_score}
        _append_json_line(results_path, record)
        done_rows.append(record)
        done.add(key)
        meta["completed"] = len(done_rows)
        _atomic_json(meta_path, meta)

    meta["completed"] = len(done_rows)
    meta["failed"] = sum(row["status"] == "not_scored" for row in done_rows)
    if meta["completed"] != len(gold_rows):
        raise ValueError("scorer checkpoint counts do not reconcile to the gold sample count")
    meta["status"] = "partial" if meta["failed"] else "completed"
    _atomic_json(meta_path, meta)
    return {**meta, "records": done_rows}


def _read_result_lines(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    raw = path.read_bytes()
    recovered = 0
    if raw and not raw.endswith(b"\n"):
        final_newline = raw.rfind(b"\n")
        tail = raw[final_newline + 1 :]
        try:
            json.loads(tail)
            # A complete JSON row without the final delimiter is recoverable.
            with path.open("ab") as stream:
                stream.write(b"\n")
                stream.flush()
                os.fsync(stream.fileno())
        except (json.JSONDecodeError, UnicodeDecodeError):
            recovered = len(tail)
            with path.open("r+b") as stream:
                stream.truncate(final_newline + 1)
                stream.flush()
                os.fsync(stream.fileno())
            raw = raw[: final_newline + 1]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line:
            continue
        row = json.loads(line)
        key = (str(row.get("scenario_id", "")), str(row.get("event_id")) if "event_id" in row else None)
        if key in seen:
            raise ValueError(f"duplicate checkpoint row at {path}:{line_number}: {key}")
        seen.add(key)
        rows.append(row)
    return rows, recovered


def _append_json_line(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with path.open("ab") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _count_fields(records: list[dict[str, Any]], total: int) -> dict[str, Any]:
    counts = Counter(str(row["status"]) for row in records)
    completed = counts["completed"]
    failed = counts["failed"]
    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "skipped": 0,
        "not_applicable": 0,
        "scored_coverage": (completed / total) if total else None,
    }


def _reject_gold_only_output(value: Any, path: str = "actor_output") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if key_text in _GOLD_ONLY_KEYS:
                raise ValueError(f"actor output contains scorer-only field: {path}.{key_text}")
            _reject_gold_only_output(child, f"{path}.{key_text}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_gold_only_output(child, f"{path}[{index}]")


def _validate_fingerprint(value: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("fingerprint must be a lowercase SHA-256 hex digest")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in checkpoint: {path}")
    return value


__all__ = ["run_actor_stage", "score_actor_outputs"]
