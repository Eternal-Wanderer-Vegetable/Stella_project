# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Scorer-side PITCH timing-window adaptation and placement metrics."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PitchWindow:
    candidate_id: str
    conversation_id: str
    n_turns: int
    segment_start_turn: int
    segment_end_turn: int
    acceptable_windows: tuple[tuple[int, int], ...]
    intersection: tuple[int, int] | None
    union: tuple[int, int] | None
    within_group_annotation_count: int
    within_group_windows: tuple[tuple[int, int], ...]
    within_group_intersection: tuple[int, int] | None
    annotation_count: int
    author_annotation_count: int
    do_not_surface_annotations: int
    any_do_not_surface_annotation: bool
    consensus_do_not_surface: bool
    consensus_best_turn: int | None
    accepted_best_turns: tuple[int, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pitch_windows(
    source_path: Path, *, expected_sha256: str
) -> tuple[PitchWindow, ...]:
    """Load only timing IDs and labels; transcript and candidate text are discarded."""
    actual_hash = sha256_file(source_path)
    if actual_hash != expected_sha256:
        raise ValueError(
            f"PITCH SHA-256 mismatch: expected {expected_sha256}, got {actual_hash}"
        )
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read PITCH JSON: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("PITCH source must be a non-empty array")

    rows: list[PitchWindow] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"PITCH record {index} must be an object")
        candidate_id = _required_text(item, "knowledge_item_id", index)
        conversation_id = _required_text(item, "conversation_id", index)
        if candidate_id in seen:
            raise ValueError(f"duplicate PITCH candidate id: {candidate_id}")
        seen.add(candidate_id)
        n_turns = _required_int(item, "n_turns", index, minimum=1)
        segment_start = _required_int(item, "start_turn", index, minimum=1)
        segment_end = _required_int(item, "end_turn", index, minimum=segment_start)
        if segment_end > n_turns:
            raise ValueError(f"PITCH record {index}: segment end exceeds n_turns")

        ground_truth = item.get("ground_truth")
        if not isinstance(ground_truth, dict):
            raise ValueError(f"PITCH record {index}: ground_truth must be an object")
        raw_windows = ground_truth.get("acceptable_windows")
        if not isinstance(raw_windows, list):
            raise ValueError(f"PITCH record {index}: acceptable_windows must be an array")
        windows = tuple(_interval(value, index, n_turns) for value in raw_windows)
        if windows:
            start = max(interval[0] for interval in windows)
            end = min(interval[1] for interval in windows)
            intersection = (start, end) if start <= end else None
            expected_union = (
                min(interval[0] for interval in windows),
                max(interval[1] for interval in windows),
            )
        else:
            intersection = None
            expected_union = None

        union_start = ground_truth.get("union_window_start")
        union_end = ground_truth.get("union_window_end")
        if union_start is None and union_end is None:
            union = expected_union
        elif (
            isinstance(union_start, bool) or not isinstance(union_start, int)
            or isinstance(union_end, bool) or not isinstance(union_end, int)
            or union_start < 1 or union_end < union_start or union_end > n_turns
        ):
            raise ValueError(f"PITCH record {index}: invalid official union window")
        else:
            union = (union_start, union_end)
            if expected_union is not None and union != expected_union:
                raise ValueError(f"PITCH record {index}: official union differs from intervals")

        annotations = item.get("individual_annotations")
        if not isinstance(annotations, list):
            raise ValueError(f"PITCH record {index}: individual_annotations must be an array")
        dns_count = sum(
            1 for annotation in annotations
            if isinstance(annotation, dict) and annotation.get("do_not_surface") is True
        )
        consensus_dns = ground_truth.get("do_not_surface")
        if not isinstance(consensus_dns, bool):
            raise ValueError(f"PITCH record {index}: consensus do_not_surface must be boolean")
        within_group_annotations = [
            annotation for annotation in annotations
            if isinstance(annotation, dict) and annotation.get("role") == "within_group"
        ]
        within_group_windows = tuple(
            _interval(
                [annotation["window_start"], annotation["window_end"]], index, n_turns
            )
            for annotation in within_group_annotations
            if isinstance(annotation.get("window_start"), int)
            and not isinstance(annotation.get("window_start"), bool)
            and isinstance(annotation.get("window_end"), int)
            and not isinstance(annotation.get("window_end"), bool)
        )
        if within_group_windows:
            within_start = max(interval[0] for interval in within_group_windows)
            within_end = min(interval[1] for interval in within_group_windows)
            within_intersection = (
                (within_start, within_end) if within_start <= within_end else None
            )
        else:
            within_intersection = None
        consensus_best_turn = ground_truth.get("consensus_best_turn")
        if consensus_best_turn is not None and (
            isinstance(consensus_best_turn, bool)
            or not isinstance(consensus_best_turn, int)
            or consensus_best_turn < 1
            or consensus_best_turn > n_turns
        ):
            raise ValueError(f"PITCH record {index}: invalid consensus_best_turn")
        accepted_best_turns = ground_truth.get("accepted_best_turns", [])
        if not isinstance(accepted_best_turns, list) or any(
            isinstance(turn, bool) or not isinstance(turn, int)
            or turn < 1 or turn > n_turns
            for turn in accepted_best_turns
        ):
            raise ValueError(f"PITCH record {index}: invalid accepted_best_turns")
        rows.append(
            PitchWindow(
                candidate_id=candidate_id,
                conversation_id=conversation_id,
                n_turns=n_turns,
                segment_start_turn=segment_start,
                segment_end_turn=segment_end,
                acceptable_windows=windows,
                intersection=intersection,
                union=union,
                within_group_annotation_count=len(within_group_annotations),
                within_group_windows=within_group_windows,
                within_group_intersection=within_intersection,
                annotation_count=len(annotations),
                author_annotation_count=sum(
                    1 for annotation in annotations
                    if isinstance(annotation, dict) and annotation.get("role") == "author"
                ),
                do_not_surface_annotations=dns_count,
                any_do_not_surface_annotation=dns_count > 0,
                consensus_do_not_surface=consensus_dns,
                consensus_best_turn=consensus_best_turn,
                accepted_best_turns=tuple(accepted_best_turns),
            )
        )
    return tuple(rows)


def score_pitch_placements(
    rows: tuple[PitchWindow, ...],
    placements: dict[str, int | None],
    *,
    scope: str = "intersection",
) -> dict[str, Any]:
    """Score first placement against the all-annotations intersection.

    Every candidate must be represented in ``placements``. A missing or null
    placement is a miss only when the candidate has an intersecting window;
    candidates without an intersection remain visible in the full denominator.
    """
    ids = {row.candidate_id for row in rows}
    if set(placements) != ids:
        missing = sorted(ids - set(placements))
        extra = sorted(set(placements) - ids)
        raise ValueError(f"PITCH placement ID mismatch; missing={missing[:3]}, extra={extra[:3]}")

    if scope not in {"intersection", "union", "within_group_intersection"}:
        raise ValueError(f"unsupported PITCH window scope: {scope}")
    counts: Counter[str] = Counter()
    for row in rows:
        turn = placements[row.candidate_id]
        if turn is not None and (
            isinstance(turn, bool) or not isinstance(turn, int)
            or turn < 1 or turn > row.n_turns
        ):
            raise ValueError(f"invalid placement turn for PITCH candidate {row.candidate_id}")
        if scope == "intersection":
            intervals = row.acceptable_windows
            window = row.intersection
        elif scope == "union":
            intervals = ((row.union,) if row.union is not None else ())
            window = row.union
        else:
            intervals = row.within_group_windows
            window = row.within_group_intersection
        if not intervals:
            counts["no_annotation_window"] += 1
        if window is None:
            counts["no_intersection"] += 1
            if turn is not None:
                counts["placement_on_no_intersection"] += 1
            continue
        counts["scoreable_window_denominator"] += 1
        if turn is None:
            counts["missed"] += 1
        elif turn < window[0]:
            counts["early"] += 1
        elif turn > window[1]:
            counts["late"] += 1
        else:
            counts["hit"] += 1

    total = len(rows)
    scoreable = counts["scoreable_window_denominator"]
    placed = sum(turn is not None for turn in placements.values())
    return {
        "interpretation": {
            "intersection": "score against the nonempty intersection of every official acceptable window",
            "union": "score against the outer union span of official acceptable windows",
            "within_group_intersection": "score against the intersection of within-group annotator windows",
        }[scope],
        "denominator_all_candidates": total,
        "scoreable_window_denominator": scoreable,
        "no_intersection": counts["no_intersection"],
        "no_annotation_window": counts["no_annotation_window"],
        "placements": placed,
        "placement_on_no_intersection": counts["placement_on_no_intersection"],
        "missed": counts["missed"],
        "early": counts["early"],
        "hit": counts["hit"],
        "late": counts["late"],
        "window_hit_rate": _rate(counts["hit"], scoreable),
        "early_rate": _rate(counts["early"], scoreable),
        "late_rate": _rate(counts["late"], scoreable),
        "missed_rate": _rate(counts["missed"], scoreable),
        "coverage_all_candidates": _rate(placed, total),
    }


def audit_pitch_windows(
    source_path: Path,
    *,
    expected_sha256: str,
    revision: str,
    license_name: str,
    expected_candidates: int,
    expected_conversations: int,
    expected_annotations: int,
    expected_author_annotations: int | None = None,
    expected_within_group_annotations: int | None = None,
    expected_dns_annotations: int | None = None,
    expected_dns_candidates: int | None = None,
) -> dict[str, Any]:
    """Build a scorer-only source audit with fixed, transparent diagnostics."""
    rows = load_pitch_windows(source_path, expected_sha256=expected_sha256)
    candidates = len(rows)
    conversations = len({row.conversation_id for row in rows})
    annotations = sum(row.annotation_count for row in rows)
    if (candidates, conversations, annotations) != (
        expected_candidates, expected_conversations, expected_annotations
    ):
        raise ValueError(
            "PITCH frozen count mismatch: "
            f"got {(candidates, conversations, annotations)}, expected "
            f"{(expected_candidates, expected_conversations, expected_annotations)}"
        )
    author_annotations = sum(row.author_annotation_count for row in rows)
    within_group_annotations = sum(row.within_group_annotation_count for row in rows)
    dns_annotations = sum(row.do_not_surface_annotations for row in rows)
    dns_candidates = sum(row.any_do_not_surface_annotation for row in rows)
    _check_optional_count("author annotations", author_annotations, expected_author_annotations)
    _check_optional_count(
        "within-group annotations", within_group_annotations, expected_within_group_annotations
    )
    _check_optional_count("do-not-surface annotations", dns_annotations, expected_dns_annotations)
    _check_optional_count(
        "candidates with a do-not-surface annotation", dns_candidates, expected_dns_candidates
    )

    all_ids = [row.candidate_id for row in rows]
    segment_start = {row.candidate_id: row.segment_start_turn for row in rows}
    oracle = {
        row.candidate_id: row.intersection[0] if row.intersection is not None else None
        for row in rows
    }
    eligible = sum(row.intersection is not None for row in rows)
    dns_candidates = sum(row.do_not_surface_annotations > 0 for row in rows)
    dns_annotations = sum(row.do_not_surface_annotations for row in rows)
    consensus_dns = sum(row.consensus_do_not_surface for row in rows)
    within_group_with_windows = sum(bool(row.within_group_windows) for row in rows)
    within_group_intersection = sum(row.within_group_intersection is not None for row in rows)
    segment_start = {row.candidate_id: row.segment_start_turn for row in rows}
    silent = dict.fromkeys(all_ids)
    dns_rows = tuple(row for row in rows if row.any_do_not_surface_annotation)
    dns_ids = {row.candidate_id for row in dns_rows}
    dns_placements = {key: value for key, value in segment_start.items() if key in dns_ids}
    dns_silent = dict.fromkeys(dns_ids)
    dns_oracle = {
        row.candidate_id: row.intersection[0] if row.intersection is not None else None
        for row in dns_rows
    }
    consensus_best_turn_matches = sum(
        row.consensus_best_turn is not None
        and segment_start[row.candidate_id] == row.consensus_best_turn
        for row in rows
    )
    per_candidate_results = []
    for row in rows:
        segment_turn = segment_start[row.candidate_id]
        oracle_turn = oracle[row.candidate_id]
        per_candidate_results.append(
            {
                "candidate_id": row.candidate_id,
                "conversation_id": row.conversation_id,
                "n_turns": row.n_turns,
                "window_evidence": {
                    "official_intersection": row.intersection,
                    "official_union": row.union,
                    "within_group_intersection": row.within_group_intersection,
                    "within_group_timing_annotation_count": len(row.within_group_windows),
                    "has_official_windows": bool(row.acceptable_windows),
                    "any_do_not_surface_annotation": row.any_do_not_surface_annotation,
                    "do_not_surface_annotation_count": row.do_not_surface_annotations,
                    "consensus_do_not_surface": row.consensus_do_not_surface,
                    "consensus_best_turn": row.consensus_best_turn,
                },
                "placements": {
                    "segment_start_turn": segment_turn,
                    "segment_start_intersection_status": _placement_status(
                        row.intersection, segment_turn
                    ),
                    "always_silent_intersection_status": _placement_status(
                        row.intersection, None
                    ),
                    "intersection_oracle_turn": oracle_turn,
                    "intersection_oracle_status": _placement_status(
                        row.intersection, oracle_turn
                    ),
                },
            }
        )
    return {
        "schema": "stella-pitch-window-audit/1",
        "status": "completed",
        "evidence_level": "source_native_gold_audit",
        "source": {
            "dataset_id": "pitch",
            "revision": revision,
            "license": license_name,
            "sha256": sha256_file(source_path),
            "unit": "fixed_candidate_message_with_turn_window",
            "label_side": "scorer_only",
            "actor_runs": 0,
        },
        "counts": {
            "candidates": candidates,
            "conversations": conversations,
            "individual_annotations": annotations,
            "scoreable_intersection_windows": eligible,
            "no_intersection_candidates": candidates - eligible,
            "candidates_without_official_windows": sum(not row.acceptable_windows for row in rows),
            "candidates_with_conflicting_official_windows": sum(
                bool(row.acceptable_windows) and row.intersection is None for row in rows
            ),
            "author_annotations": author_annotations,
            "within_group_annotations": within_group_annotations,
            "within_group_candidates_with_timing_windows": within_group_with_windows,
            "within_group_intersection_windows": within_group_intersection,
            "within_group_candidates_without_timing_windows": candidates - within_group_with_windows,
            "within_group_candidates_with_conflicting_windows": within_group_with_windows - within_group_intersection,
            "consensus_do_not_surface_candidates": consensus_dns,
            "candidates_with_any_do_not_surface_annotation": dns_candidates,
            "do_not_surface_annotations": dns_annotations,
            "segment_start_consensus_best_turn_exact_matches": consensus_best_turn_matches,
            "consensus_best_turn_denominator": sum(row.consensus_best_turn is not None for row in rows),
        },
        "intersection": {
            "method": "max(window_start) <= min(window_end) over official ground_truth.acceptable_windows",
            "denominator": candidates,
            "scoreable_numerator": eligible,
            "coverage": _rate(eligible, candidates),
        },
        "placement_diagnostics": {
            "segment_start": {
                "interpretation": "place at the candidate segment's first turn; deterministic timing baseline, not a learned policy",
                **score_pitch_placements(rows, segment_start),
            },
            "always_silent": {
                "interpretation": "no placement; reports all scoreable candidates as missed",
                **score_pitch_placements(rows, silent),
            },
            "intersection_oracle": {
                "interpretation": "place at each gold intersection start; noncausal diagnostic upper bound only",
                **score_pitch_placements(rows, oracle),
            },
        },
        "union_placement_diagnostics": {
            baseline: score_pitch_placements(rows, placements, scope="union")
            for baseline, placements in (
                ("segment_start", segment_start), ("always_silent", silent),
                ("intersection_oracle", oracle),
            )
        },
        "within_group_placement_diagnostics": {
            baseline: score_pitch_placements(
                rows, placements, scope="within_group_intersection"
            )
            for baseline, placements in (
                ("segment_start", segment_start), ("always_silent", silent),
                ("intersection_oracle", oracle),
            )
        },
        "do_not_surface_annotation_subgroup": {
            "candidate_definition": "candidate has at least one individual do_not_surface annotation",
            "candidate_denominator": dns_candidates,
            "do_not_surface_annotation_count": dns_annotations,
            "consensus_do_not_surface_candidates": consensus_dns,
            "intersection_diagnostics": {
                "segment_start": score_pitch_placements(dns_rows, dns_placements),
                "always_silent": score_pitch_placements(dns_rows, dns_silent),
                "intersection_oracle": score_pitch_placements(dns_rows, dns_oracle),
            },
        },
        "per_candidate_results": per_candidate_results,
        "limits": [
            "PITCH timing labels are turns; no elapsed-time ground truth is inferred.",
            "The segment-start baseline and intersection oracle are timing diagnostics, not Stella product-effectiveness claims.",
            "No actor, model, memory input, generation, or external send was run.",
            "All candidates remain in the denominator; no-intersection rows are reported separately.",
        ],
    }


def _interval(value: Any, index: int, n_turns: int) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"PITCH record {index}: each acceptable window must be [start, end]")
    start, end = value
    if (
        isinstance(start, bool) or not isinstance(start, int)
        or isinstance(end, bool) or not isinstance(end, int)
        or start < 1 or end < start or end > n_turns
    ):
        raise ValueError(f"PITCH record {index}: invalid acceptable turn window {value!r}")
    return start, end


def _required_text(item: dict[str, Any], field: str, index: int) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"PITCH record {index}: {field} must be non-empty text")
    return value


def _required_int(
    item: dict[str, Any], field: str, index: int, *, minimum: int
) -> int:
    value = item.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"PITCH record {index}: {field} must be an integer >= {minimum}")
    return value


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _placement_status(window: tuple[int, int] | None, turn: int | None) -> str:
    if window is None:
        return "NO_INTERSECTION"
    if turn is None:
        return "MISSED"
    if turn < window[0]:
        return "EARLY"
    if turn > window[1]:
        return "LATE"
    return "HIT"


def _check_optional_count(name: str, actual: int, expected: int | None) -> None:
    if expected is not None and actual != expected:
        raise ValueError(f"PITCH frozen {name} mismatch: got {actual}, expected {expected}")


__all__ = ["PitchWindow", "audit_pitch_windows", "load_pitch_windows", "score_pitch_placements"]
