# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Convert pinned public participation datasets into B01 actor/gold JSONL."""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from proactive_eval.adapters import sha256_file

ADAPTER_VERSION = "proactive-source-adapters/1"
_BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
_LABELS = {"SPEAK", "SILENT"}


@dataclass(frozen=True)
class AdaptedCorpus:
    """Actor-only scenarios, scorer-only labels, and report-only metadata."""

    scenarios: tuple[dict[str, Any], ...]
    gold: tuple[dict[str, Any], ...]
    raw_records: int
    label_counts: dict[str, int]
    category_by_scenario: dict[str, str]


def adapt_when2speak_token(
    source_path: Path,
    *,
    expected_sha256: str,
    revision: str,
) -> AdaptedCorpus:
    """Adapt only the frozen token test file; the final assistant token stays in gold."""
    source_hash = _verify_source(source_path, expected_sha256, revision)
    scenarios: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    labels: Counter[str] = Counter()

    for row_number, row in _read_jsonl(source_path):
        messages = row.get("messages")
        if not isinstance(messages, list) or not 2 <= len(messages) <= 9:
            raise ValueError(
                f"When2Speak row {row_number}: expected 1–8 context messages and a final label"
            )
        label_row = messages[-1]
        if not isinstance(label_row, dict) or label_row.get("role") != "assistant":
            raise ValueError(f"When2Speak row {row_number}: final item must be assistant label")
        token = label_row.get("content")
        if token not in ("<", ">"):
            raise ValueError(f"When2Speak row {row_number}: unsupported token label {token!r}")
        prefix = messages[:-1]
        if any(not isinstance(message, dict) or message.get("role") != "user" for message in prefix):
            raise ValueError(f"When2Speak row {row_number}: context must contain user turns only")
        if any(not isinstance(message.get("content"), str) for message in prefix):
            raise ValueError(f"When2Speak row {row_number}: message content must be text")

        scenario_id = f"when2speak-token-test-{row_number - 1:06d}"
        events = [
            _event(
                sequence=index,
                event_id=f"turn-{index:02d}",
                speaker_id=_speaker_id(message["content"], index),
                text=message["content"],
            )
            for index, message in enumerate(prefix)
        ]
        scenario = _scenario(
            scenario_id=scenario_id,
            episode_id=scenario_id,
            dataset_id="when2speak",
            config="token",
            revision=revision,
            file_sha256=source_hash,
            unit="decision_context",
            split="test",
            events=events,
        )
        source_label = "SPEAK" if token == "<" else "SILENT"
        scenarios.append(scenario)
        gold.append(_gold(scenario_id, events[-1]["event_id"], source_label))
        labels[source_label] += 1

    return AdaptedCorpus(
        scenarios=tuple(scenarios),
        gold=tuple(gold),
        raw_records=len(scenarios),
        label_counts={label: labels[label] for label in ("SPEAK", "SILENT")},
        category_by_scenario={},
    )


def adapt_social_ai_ambient(
    source_path: Path,
    *,
    expected_sha256: str,
    revision: str,
) -> AdaptedCorpus:
    """Create one actor-only prefix per labeled turn; category and labels stay scorer-side."""
    source_hash = _verify_source(source_path, expected_sha256, revision)
    scenarios: list[dict[str, Any]] = []
    gold: list[dict[str, Any]] = []
    labels: Counter[str] = Counter()
    category_by_scenario: dict[str, str] = {}
    seen_episode_ids: set[str] = set()

    for row_number, row in _read_jsonl(source_path):
        episode_id = row.get("id")
        category = row.get("category")
        turns = row.get("turns")
        if not isinstance(episode_id, str) or not episode_id:
            raise ValueError(f"Social AI row {row_number}: missing scene id")
        if episode_id in seen_episode_ids:
            raise ValueError(f"Social AI row {row_number}: duplicate scene id {episode_id!r}")
        seen_episode_ids.add(episode_id)
        if not isinstance(category, str) or not category:
            raise ValueError(f"Social AI row {row_number}: missing category")
        if not isinstance(turns, list) or not turns:
            raise ValueError(f"Social AI row {row_number}: turns must be a non-empty array")
        if row.get("num_turns") != len(turns):
            raise ValueError(f"Social AI row {row_number}: num_turns does not match turns")

        scene_labels: Counter[str] = Counter()
        for position, turn in enumerate(turns):
            if not isinstance(turn, dict) or turn.get("turn_index") != position:
                raise ValueError(
                    f"Social AI row {row_number}: turn_index must be contiguous from zero"
                )
            speaker = turn.get("speaker")
            message = turn.get("message")
            native_label = turn.get("expected_output")
            if not isinstance(speaker, str) or not speaker:
                raise ValueError(f"Social AI row {row_number}, turn {position}: missing speaker")
            if not isinstance(message, str):
                raise ValueError(f"Social AI row {row_number}, turn {position}: message must be text")
            if native_label not in ("RESPOND", "SILENT"):
                raise ValueError(
                    f"Social AI row {row_number}, turn {position}: unsupported label {native_label!r}"
                )

            scenario_id = f"social-ai:{episode_id}:turn-{position:04d}"
            events = [
                _event(
                    sequence=index,
                    event_id=f"turn-{index:04d}",
                    speaker_id=str(prior["speaker"]),
                    text=str(prior["message"]),
                )
                for index, prior in enumerate(turns[: position + 1])
            ]
            scenario = _scenario(
                scenario_id=scenario_id,
                episode_id=episode_id,
                dataset_id="social-ai-ambient-bench",
                config="default",
                revision=revision,
                file_sha256=source_hash,
                unit="scene_turn",
                split="test",
                events=events,
            )
            source_label = "SPEAK" if native_label == "RESPOND" else "SILENT"
            scenarios.append(scenario)
            gold.append(_gold(scenario_id, events[-1]["event_id"], source_label))
            labels[source_label] += 1
            scene_labels[source_label] += 1
            category_by_scenario[scenario_id] = category

        if row.get("num_respond") != scene_labels["SPEAK"]:
            raise ValueError(f"Social AI row {row_number}: num_respond does not match labels")
        if row.get("num_silent") != scene_labels["SILENT"]:
            raise ValueError(f"Social AI row {row_number}: num_silent does not match labels")

    return AdaptedCorpus(
        scenarios=tuple(scenarios),
        gold=tuple(gold),
        raw_records=len(seen_episode_ids),
        label_counts={label: labels[label] for label in ("SPEAK", "SILENT")},
        category_by_scenario=category_by_scenario,
    )


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> str:
    """Atomically write derived rows and return the exact file digest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temp_name).replace(path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return sha256_file(path)


def _verify_source(path: Path, expected_sha256: str, revision: str) -> str:
    if not revision:
        raise ValueError("a pinned source revision is required")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise ValueError(f"source SHA-256 mismatch for {path}: {actual}")
    return actual


def _read_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        for row_number, line in enumerate(stream, 1):
            if not line.strip():
                raise ValueError(f"blank source JSONL row at {path}:{row_number}")
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid source JSON at {path}:{row_number}: {exc.msg}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"source row at {path}:{row_number} must be an object")
            yield row_number, row


def _scenario(
    *,
    scenario_id: str,
    episode_id: str,
    dataset_id: str,
    config: str,
    revision: str,
    file_sha256: str,
    unit: str,
    split: str,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": "stella-proactive-scenario/1",
        "scenario_id": scenario_id,
        "episode_id": episode_id,
        "source": {
            "dataset_id": dataset_id,
            "config": config,
            "revision": revision,
            "file_sha256": file_sha256,
            "adapter_version": ADAPTER_VERSION,
            "unit": unit,
        },
        "split": split,
        "trusted_bot": "assistant",
        "connection_id": "benchmark",
        "scene": "group_chat",
        "events": events,
        "accessible_memories": [],
        "clock": {
            "initial_wall_time": _BASE_TIME.isoformat().replace("+00:00", "Z"),
            "initial_monotonic_ms": 0,
            "time_source": "synthetic",
        },
    }


def _event(*, sequence: int, event_id: str, speaker_id: str, text: str) -> dict[str, Any]:
    arrived_at = (_BASE_TIME + timedelta(seconds=sequence)).isoformat().replace("+00:00", "Z")
    return {
        "event_id": event_id,
        "sequence": sequence,
        "speaker_id": speaker_id,
        "subject_key": None,
        "source_kind": "user_message",
        "text": text,
        "arrived_at": arrived_at,
        "time_source": "synthetic",
        "native_reply_to": None,
        "mentions": [],
    }


def _gold(scenario_id: str, event_id: str, source_label: str) -> dict[str, Any]:
    if source_label not in _LABELS:
        raise ValueError(f"unsupported source label: {source_label!r}")
    return {
        "schema": "stella-scorer-gold/1",
        "scenario_id": scenario_id,
        "event_id": event_id,
        "label_origin": "official",
        "source_label": source_label,
        "allowed_actions": ["SPEAK"] if source_label == "SPEAK" else ["DROP"],
        "turn_window": None,
        "do_not_surface": None,
        "memory_requirement": "unknown",
        "support_evidence_ids": [],
        "forbidden_memory_ids": [],
        "should_abstain": None,
        "annotation": {"annotator_count": 0, "agreement": None, "adjudicated": False},
    }


def _speaker_id(text: str, fallback: int) -> str:
    prefix, separator, _ = text.partition(":")
    if separator and prefix.strip() and len(prefix) <= 80:
        return prefix.strip()
    return f"speaker-{fallback}"


__all__ = [
    "ADAPTER_VERSION",
    "AdaptedCorpus",
    "adapt_social_ai_ambient",
    "adapt_when2speak_token",
    "write_jsonl",
]
