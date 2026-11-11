# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Run B03's PITCH turn-window audit and synthetic mechanism timing replay."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from aoede.opportunity import (
    DEFAULT_DEBOUNCE_SECONDS,
    DEFAULT_TTL_SECONDS,
    OpportunityManager,
)
from config import PROACTIVE_COOLDOWN
from mneme.verification import DEFAULT_VERIFICATION_WINDOW_SECONDS
from proactive_eval.adapters import load_registry
from proactive_eval.pitch_windows import audit_pitch_windows, sha256_file
from proactive_eval.virtual_time import VirtualTimeDriver

_ROOT = Path(__file__).resolve().parents[1]
_REGISTRY = Path(__file__).with_name("dataset-registry.json")
_DEFAULT_OUTPUT = (
    _ROOT / "memory/benchmark/_public/proactive_eval/runs/B03/pitch-window-audit.json"
)


async def simulate_arrival_interval(
    interval_seconds: float, *, turns: int = 10
) -> dict[str, Any]:
    """Replay fixed-turn arrivals through the production opportunity manager.

    Intervals are synthetic engineering sensitivity inputs. They are not
    derived from PITCH turns or presented as PITCH elapsed-time labels.
    """
    if not math.isfinite(interval_seconds) or interval_seconds <= 0:
        raise ValueError("synthetic interval must be a finite positive duration")
    if turns < 1:
        raise ValueError("turns must be positive")
    driver = VirtualTimeDriver()
    manager = OpportunityManager(
        clock=driver.monotonic,
        debounce_seconds=DEFAULT_DEBOUNCE_SECONDS,
        ttl_seconds=DEFAULT_TTL_SECONDS,
    )
    manager._preflight_blocked_reason = lambda _group_id: ""
    manager._cooldown_blocked = lambda _group_id: False
    decision = SimpleNamespace(mode="TOPIC_INTEREST", should_speak=True, group_id=1)
    submitted = 0
    fire_after_submitted: list[int] = []

    async def record_speak(_opportunity) -> None:
        if manager._inflight.get(_opportunity.group_id) is _opportunity:
            manager._inflight.pop(_opportunity.group_id, None)
        fire_after_submitted.append(submitted)

    manager._speak = record_speak
    outcomes: list[str] = []
    with patch.object(asyncio, "get_running_loop", return_value=driver):
        for turn in range(turns):
            if turn:
                await driver.advance(interval_seconds)
            outcomes.append(manager.submit(1, decision))
            submitted += 1
        await driver.advance(DEFAULT_DEBOUNCE_SECONDS)

    return {
        "interval_seconds": interval_seconds,
        "interval_source": "synthetic",
        "turns": turns,
        "created": outcomes.count("created"),
        "merged": outcomes.count("merged"),
        "dropped": sum(value.startswith("dropped:") for value in outcomes),
        "speak_actions": len(fire_after_submitted),
        "timer_fires_after_submitted_turn_count": fire_after_submitted,
    }


async def simulate_ttl_merge_boundary() -> dict[str, Any]:
    """Prove continuous merges do not extend the original opportunity TTL."""
    driver = VirtualTimeDriver()
    manager = OpportunityManager(
        clock=driver.monotonic,
        debounce_seconds=DEFAULT_DEBOUNCE_SECONDS,
        ttl_seconds=DEFAULT_TTL_SECONDS,
    )
    manager._preflight_blocked_reason = lambda _group_id: ""
    manager._cooldown_blocked = lambda _group_id: False
    decision = SimpleNamespace(mode="TOPIC_INTEREST", should_speak=True, group_id=1)
    sends = 0

    async def record_speak(_opportunity) -> None:
        nonlocal sends
        if manager._inflight.get(_opportunity.group_id) is _opportunity:
            manager._inflight.pop(_opportunity.group_id, None)
        sends += 1

    manager._speak = record_speak
    with patch.object(asyncio, "get_running_loop", return_value=driver):
        manager.submit(1, decision)
        first = manager._inflight[1]
        for _ in range(int(DEFAULT_TTL_SECONDS) - 1):
            await driver.advance(1.0)
            assert manager.submit(1, decision) == "merged"
        original_expiry = first.expires_at
        await driver.advance(1.0)
        result = manager.submit(1, decision)
        replacement = manager._inflight[1]
        await driver.advance(DEFAULT_DEBOUNCE_SECONDS)

    return {
        "merge_interval_seconds": 1.0,
        "original_ttl_seconds": DEFAULT_TTL_SECONDS,
        "original_expiry_monotonic": original_expiry,
        "replacement_created_at_monotonic": replacement.created_at,
        "expired_opportunity_replaced_at_ttl": first is not replacement and result == "created",
        "replacement_submit_result": result,
        "replacement_speak_actions": sends,
    }


async def build_synthetic_timing_sensitivity() -> dict[str, Any]:
    intervals = [
        {"profile": "dense", **await simulate_arrival_interval(1.0)},
        {"profile": "debounce_boundary", **await simulate_arrival_interval(DEFAULT_DEBOUNCE_SECONDS)},
        {"profile": "long_pause", **await simulate_arrival_interval(10.0)},
    ]
    return {
        "intervals": intervals,
        "ttl_merge_boundary": await simulate_ttl_merge_boundary(),
    }


def run_pitch_b03(
    *, registry_path: Path = _REGISTRY, output_path: Path = _DEFAULT_OUTPUT
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    datasets = {row["dataset_id"]: row for row in registry["datasets"]}
    pitch = datasets["pitch"]
    file = pitch["files"][0]
    source_path = _resolve_repo_path(str(file["path"]))
    expected = pitch["counts"]
    report = audit_pitch_windows(
        source_path,
        expected_sha256=str(file["sha256"]),
        revision=str(pitch["source"]["revision"]),
        license_name=str(pitch["license"]),
        expected_candidates=int(expected["candidates"]),
        expected_conversations=int(expected["conversations"]),
        expected_annotations=int(expected["individual_annotations"]),
        expected_author_annotations=int(expected["author_annotations"]),
        expected_within_group_annotations=int(expected["within_group_annotations"]),
        expected_dns_annotations=int(expected["do_not_surface_annotations"]),
        expected_dns_candidates=int(expected["candidates_with_any_do_not_surface_annotation"]),
    )
    report["timing_contract"] = {
        "opportunity_debounce_seconds": DEFAULT_DEBOUNCE_SECONDS,
        "opportunity_ttl_seconds": DEFAULT_TTL_SECONDS,
        "proactive_cooldown_seconds": PROACTIVE_COOLDOWN,
        "verification_window_seconds": DEFAULT_VERIFICATION_WINDOW_SECONDS,
        "pitch_window_unit": "turn",
        "synthetic_arrivals_used_as_pitch_truth": False,
    }
    report["synthetic_timing_sensitivity"] = asyncio.run(
        build_synthetic_timing_sensitivity()
    )
    report["limits"].extend(
        [
            "Synthetic interval profiles exercise the opportunity timer; they are not mapped onto PITCH conversations.",
            "The synthetic opportunity replay stubs cooldown admission to isolate debounce/TTL ordering; the production cooldown value is recorded separately.",
            "Budget and Mneme verification persistence are covered by isolated integration tests using the same virtual time driver.",
        ]
    )
    _write_json(output_path, report)
    return {
        "report_path": str(output_path.resolve()),
        "report_sha256": sha256_file(output_path),
        "candidates": report["counts"]["candidates"],
        "scoreable_windows": report["counts"]["scoreable_intersection_windows"],
        "no_intersection_candidates": report["counts"]["no_intersection_candidates"],
        "status": report["status"],
    }


def _resolve_repo_path(relative: str) -> Path:
    candidate = (_ROOT / relative).resolve()
    if _ROOT not in candidate.parents:
        raise ValueError(f"dataset path escapes repository root: {relative}")
    return candidate


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=_REGISTRY)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = run_pitch_b03(registry_path=args.registry, output_path=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
