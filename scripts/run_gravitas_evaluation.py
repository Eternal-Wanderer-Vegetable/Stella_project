#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Run the isolated Gravitas V1 scenario matrix and deterministic state trace.

Both ``--suite`` and ``--workdir`` are required. The runner sets ``STELLA_HOME``
to a fresh directory under the explicit workdir for every scenario process. It
never reads the caller's Stella data directory or connects to live services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 3
MIN_STEPS = 100
MAX_STEPS = 1000
DEFAULT_STEPS = 256
DEFAULT_TRACE_SEEDS = 10
MAX_TRACE_SEEDS = 100
DEFAULT_TIMEOUT = 180.0
SCENARIO_IDS = tuple(f"S{index:02}" for index in range(1, 13))
REQUIRED_INVARIANTS = {f"I{index:02}" for index in range(1, 11)}
FINGERPRINT_PATHS = (
    "gravitas/config.py",
    "gravitas/controller.py",
    "gravitas/deadlines.py",
    "gravitas/model_calls.py",
    "gravitas/policy.py",
    "core/evaluation/report.py",
    "core/llm/scheduler.py",
    "core/runtime/facade.py",
    "core/runtime/turn_service.py",
    "core/social/delivery.py",
    "core/transport/outbound.py",
    "memory/capture_gate.py",
    "memory/consolidator.py",
    "memory/db_cleaner.py",
    "memory/pre_processors.py",
    "memory/session_compact.py",
    "scripts/run_gravitas_evaluation.py",
    "scripts/build_release_package.py",
    "deploy/profiles.py",
)

from core.evaluation.report import (
    DimensionStatus,
    ExperimentReport,
    SampleRecord,
    StabilityReport,
)
from gravitas.config import default_config
from gravitas.policy import (
    PressureState,
    ResourcePolicyState,
    ResourceSignals,
    evaluate_pressure,
)


class SuiteError(ValueError):
    """The explicit scenario suite is invalid or escapes its declared roots."""


class TraceViolationError(AssertionError):
    """A generated event prefix violates one of the modeled hard invariants."""

    def __init__(self, invariant: str, seed: int, trace: list[dict[str, Any]], detail: str):
        self.invariant = invariant
        self.seed = seed
        self.trace = trace
        self.detail = detail
        super().__init__(f"{invariant} violated at event {len(trace) - 1}")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256(payload.encode("utf-8"))


def _load_suite(suite_dir: Path, *, root: Path = ROOT) -> tuple[dict[str, Any], Path]:
    suite_dir = suite_dir.resolve()
    if not suite_dir.is_relative_to(root.resolve()):
        raise SuiteError("suite must live inside the repository")
    suite_path = (suite_dir / "suite.json").resolve()
    if not suite_path.is_relative_to(suite_dir) or not suite_path.is_file():
        raise SuiteError("suite must be a directory containing suite.json")
    try:
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SuiteError(f"cannot read scenario suite: {exc}") from exc
    if not isinstance(suite, dict) or suite.get("schema_version") != 1 or not isinstance(suite.get("scenarios"), list):
        raise SuiteError("unsupported or malformed suite schema")
    expected_policy_version = f"gravitas-config-schema-v{default_config().schema_version}"
    if suite.get("policy_version") != expected_policy_version:
        raise SuiteError(f"policy_version must be {expected_policy_version}")
    scenarios = suite["scenarios"]
    if tuple(item.get("id") for item in scenarios) != SCENARIO_IDS:
        raise SuiteError("suite must declare the required V1 scenarios S01 through S12 in order")
    for scenario in scenarios:
        invariants = scenario.get("required_invariants")
        tests = scenario.get("tests")
        if not isinstance(invariants, list) or not set(invariants) <= REQUIRED_INVARIANTS:
            raise SuiteError(f"{scenario['id']} has invalid required_invariants")
        if not isinstance(tests, list) or not tests:
            raise SuiteError(f"{scenario['id']} must map to at least one pytest node")
        for nodeid in tests:
            if not isinstance(nodeid, str) or "::" not in nodeid:
                raise SuiteError(f"{scenario['id']} has invalid pytest node: {nodeid!r}")
            relative_test = nodeid.split("::", 1)[0]
            source = (root / relative_test).resolve()
            if not source.is_relative_to(root.resolve()) or not source.is_file():
                raise SuiteError(f"{scenario['id']} test path is missing or outside the repository")
            test_name = nodeid.rsplit("::", 1)[-1].split("[", 1)[0]
            source_text = source.read_text(encoding="utf-8")
            if not re.search(rf"\b(?:async\s+)?def\s+{re.escape(test_name)}\s*\(", source_text):
                raise SuiteError(f"{scenario['id']} test selector is not declared: {nodeid}")
    external = suite.get("external_acceptance")
    if not isinstance(external, list) or not external:
        raise SuiteError("live and VM acceptance boundaries must be explicit")
    if {item.get("id") for item in external} != {"live_model_platform", "clean_vm_release"}:
        raise SuiteError("suite must declare live_model_platform and clean_vm_release")
    if any(item.get("status") != "SKIPPED" for item in external):
        raise SuiteError("the offline runner cannot claim live or clean-VM acceptance")
    return suite, suite_path


def _source_fingerprint(suite: dict[str, Any], suite_path: Path) -> dict[str, str]:
    paths = set(FINGERPRINT_PATHS)
    paths.add(suite_path.relative_to(ROOT).as_posix())
    for scenario in suite["scenarios"]:
        paths.update(nodeid.split("::", 1)[0] for nodeid in scenario["tests"])
    result: dict[str, str] = {}
    for relative in sorted(paths):
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise SuiteError(f"source fingerprint target is missing: {relative}")
        result[relative] = _sha256(path.read_bytes())
    return result


def _trace_model(seed: int, steps: int, mode: str) -> dict[str, Any]:
    """Replay a bounded resource, deadline, receipt and memory-watermark model."""
    if not MIN_STEPS <= steps <= MAX_STEPS:
        raise ValueError(f"steps must be between {MIN_STEPS} and {MAX_STEPS}")
    if mode not in {"off", "shadow"}:
        raise ValueError("model mode must be off or shadow")

    rng = random.Random(seed)
    config = default_config()
    capacity, queue_limit = 3, 24
    requests: dict[str, dict[str, Any]] = {}
    queue: list[str] = []
    holders: set[str] = set()
    rows: dict[int, str] = {}
    row_id = 0
    watermark = 0
    gap_ledger: list[str] = []
    now = 0
    pressure = ResourcePolicyState(
        state=PressureState.NORMAL,
        background_tokens=0,
    )
    trace: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    would_deny_count = 0
    actions = (
        "submit", "submit", "grant", "cancel", "release", "advance", "send",
        "retry_unknown", "pressure", "capture", "compact", "cleanup",
    )

    for step in range(steps):
        now += rng.choice((0, 0, 1, 2))
        action = rng.choice(actions)
        event: dict[str, Any] = {"step": step, "action": action}
        effect: dict[str, Any] = {"step": step, "action": action}

        if action == "submit":
            request_id = f"r{step:04d}"
            conversation = f"session-{rng.randrange(4)}"
            authorized = rng.random() >= 0.12
            configured_endpoint = rng.random() >= 0.12
            request = {
                "conversation": conversation,
                "actor": conversation,
                "authorized": authorized,
                "configured_endpoint": configured_endpoint,
                "work_class": rng.choice(("interactive", "background")),
                "created": now,
                "deadline": now + rng.randint(1, 8),
                "status": "new",
                "attempts": 0,
                "outcome": None,
            }
            requests[request_id] = request
            if not authorized or not configured_endpoint:
                request["status"] = "denied"
                result = "denied_before_queue"
            elif len(queue) >= queue_limit:
                request["status"] = "queue_rejected"
                result = "queue_full"
            else:
                request["status"] = "queued"
                queue.append(request_id)
                result = "queued"
            event.update({"request": request_id, "result": result})
            effect.update({"request": request_id, "result": result})

        elif action == "grant":
            for request_id in tuple(queue):
                if requests[request_id]["deadline"] <= now:
                    queue.remove(request_id)
                    requests[request_id]["status"] = "expired"
            eligible = [request_id for request_id in queue if requests[request_id]["authorized"]]
            if len(holders) < capacity and eligible:
                def priority(request_id: str, now: int = now) -> tuple[int, float, str]:
                    request = requests[request_id]
                    aged_background = (
                        request["work_class"] == "background"
                        and now - request["created"] >= 4
                    )
                    rank = -1 if aged_background else 0 if request["work_class"] == "interactive" else 1
                    return rank, request["created"], request_id

                request_id = min(eligible, key=priority)
                queue.remove(request_id)
                request = requests[request_id]
                request["status"] = "holding"
                holders.add(request_id)
                result = "granted"
            else:
                request_id, result = None, "no_capacity_or_work"
            event.update({"request": request_id, "result": result})
            effect.update({"request": request_id, "result": result})

        elif action == "cancel":
            candidates = queue + sorted(holders)
            if candidates:
                request_id = rng.choice(candidates)
                if request_id in queue:
                    queue.remove(request_id)
                holders.discard(request_id)
                requests[request_id]["status"] = "cancelled"
                result = "cancelled_and_released"
            else:
                request_id, result = None, "no_pending_request"
            event.update({"request": request_id, "result": result})
            effect.update({"request": request_id, "result": result})

        elif action == "release":
            if holders:
                request_id = rng.choice(sorted(holders))
                holders.remove(request_id)
                request = requests[request_id]
                request["status"] = request["outcome"] or "completed"
                result = "released"
            else:
                request_id, result = None, "no_holder"
            event.update({"request": request_id, "result": result})
            effect.update({"request": request_id, "result": result})

        elif action == "advance":
            now += rng.randint(1, 4)
            expired = []
            for request_id in tuple(queue):
                if requests[request_id]["deadline"] <= now:
                    queue.remove(request_id)
                    requests[request_id]["status"] = "expired"
                    expired.append(request_id)
            event.update({"now": now, "expired": expired})
            effect.update({"now": now, "expired": expired})

        elif action == "send":
            if holders:
                request_id = rng.choice(sorted(holders))
                request = requests[request_id]
                actor = rng.choice((request["conversation"], f"session-{rng.randrange(4)}"))
                if actor != request["conversation"]:
                    result = "wrong_session_denied"
                elif request["deadline"] <= now:
                    result = "expired_side_effect_denied"
                elif request["outcome"] is not None:
                    result = "duplicate_send_denied"
                elif request["attempts"] >= 3:
                    result = "attempt_budget_denied"
                else:
                    request["attempts"] += 1
                    request["actor"] = actor
                    request["outcome"] = rng.choice(("accepted", "partial", "unknown"))
                    result = request["outcome"]
                event.update({"request": request_id, "actor": actor, "result": result})
                effect.update({"request": request_id, "actor": actor, "result": result})
            else:
                request_id, result = None, "no_holder"
                event.update({"request": request_id, "result": result})
                effect.update({"request": request_id, "result": result})

        elif action == "retry_unknown":
            unknown = [
                request_id for request_id, request in requests.items()
                if request["outcome"] == "unknown"
            ]
            if unknown:
                request_id = rng.choice(unknown)
                before = requests[request_id]["outcome"]
                result = "unknown_replay_blocked"
                assert requests[request_id]["outcome"] == before
            else:
                request_id, result = None, "no_unknown_receipt"
            event.update({"request": request_id, "result": result})
            effect.update({"request": request_id, "result": result})

        elif action == "pressure":
            signal_kind = rng.choice(("high", "high", "low", "missing"))
            if signal_kind == "high":
                signals = ResourceSignals(
                    queue_depth=config.pressure.enter_queue_depth,
                    oldest_wait_seconds=config.pressure.enter_oldest_wait_seconds,
                )
            elif signal_kind == "low":
                signals = ResourceSignals(queue_depth=0, oldest_wait_seconds=0.0)
            else:
                signals = ResourceSignals(queue_depth=None, oldest_wait_seconds=None)
            pressure = evaluate_pressure(
                pressure,
                signals,
                config.pressure,
                now=float(now),
                background_token_limit=config.limits.background_queue,
            ).next_state
            would_deny = pressure.state in {PressureState.CONSTRAINED, PressureState.UNKNOWN}
            if mode == "shadow" and would_deny:
                would_deny_count += 1
            event.update({"signal": signal_kind, "state": pressure.state.value})
            # Diagnostic facts never alter the business result in off or shadow.
            effect.update({"signal": signal_kind, "result": "observed_only"})

        elif action == "capture":
            pending_rows = sum(state == "pending" for state in rows.values())
            if pending_rows >= 8:
                gap_ledger.append("session_backlog_high")
                result = "not_captured_pressure"
            else:
                row_id += 1
                rows[row_id] = "pending"
                result = "captured"
            event.update({"result": result, "pending_rows": pending_rows})
            effect.update({"result": result, "pending_rows": pending_rows})

        elif action == "compact":
            pending_ids = [row for row, state in rows.items() if state == "pending"]
            if pending_ids and rng.random() >= 0.15:
                selected = min(pending_ids)
                rows[selected] = "complete"
                while rows.get(watermark + 1) in {"complete", "cleaned"}:
                    watermark += 1
                result = "checkpoint_advanced"
            elif pending_ids:
                selected, result = min(pending_ids), "source_retained"
            else:
                selected, result = None, "no_pending_source"
            event.update({"row": selected, "watermark": watermark, "result": result})
            effect.update({"row": selected, "watermark": watermark, "result": result})

        else:  # cleanup
            deleted = []
            for current_row, state in tuple(rows.items()):
                if current_row <= watermark and state != "pending":
                    rows[current_row] = "cleaned"
                    deleted.append(current_row)
            event.update({"deleted": deleted, "watermark": watermark})
            effect.update({"deleted": deleted, "watermark": watermark})

        trace.append(event)
        effects.append(effect)
        try:
            assert len(holders) <= capacity, "I02: holder limit exceeded"
            assert len(queue) <= queue_limit, "I02: queue limit exceeded"
            assert len(set(queue)) == len(queue), "I02: duplicate waiter"
            assert not (set(queue) & holders), "I02: request both queued and holding"
            assert all(requests[item]["status"] == "queued" for item in queue), "I02: stale waiter"
            assert all(requests[item]["status"] == "holding" for item in holders), "I02: stale holder"
            assert all(
                requests[item]["authorized"] and requests[item]["configured_endpoint"]
                for item in holders
            ), "I01/I10: unauthorized or unconfigured holder"
            assert all(
                request["attempts"] <= 3 for request in requests.values()
            ), "I02: attempt limit exceeded"
            assert all(
                rows.get(deleted_row) == "cleaned" and deleted_row <= watermark
                for deleted_row in event.get("deleted", [])
            ), "I05: cleanup passed the successful watermark"
            assert all("content" not in entry and "message" not in entry for entry in gap_ledger), (
                "I08: capture gap ledger contains message data"
            )
        except AssertionError as exc:
            raise TraceViolationError(
                str(exc).split(":", 1)[0], seed, trace, detail=str(exc)
            ) from exc

    return {
        "seed": seed,
        "steps": steps,
        "mode": mode,
        "trace_digest": _canonical_digest(trace),
        "effect_digest": _canonical_digest(effects),
        "would_deny_count": would_deny_count,
        "events": trace,
    }


def _evaluate_seeded_traces(seed: int, steps: int, seed_count: int) -> dict[str, Any]:
    """Check a fixed contiguous seed set in off and shadow modes."""
    if not 1 <= seed_count <= MAX_TRACE_SEEDS:
        raise ValueError(f"trace seed count must be between 1 and {MAX_TRACE_SEEDS}")
    results: list[dict[str, Any]] = []
    for current_seed in range(seed, seed + seed_count):
        off = _trace_model(current_seed, steps, "off")
        shadow = _trace_model(current_seed, steps, "shadow")
        results.append({
            "seed": current_seed,
            "off_trace_digest": off["trace_digest"],
            "shadow_trace_digest": shadow["trace_digest"],
            "effect_digest": off["effect_digest"],
            "effect_equivalent": off["effect_digest"] == shadow["effect_digest"],
            "would_deny_count": shadow["would_deny_count"],
        })
    return {
        "first_seed": seed,
        "seed_count": seed_count,
        "steps_per_seed": steps,
        "results": results,
        "all_effects_equivalent": all(item["effect_equivalent"] for item in results),
    }


def _child_env(home: Path, *, pythonpath: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("GRAVITAS_") or key in {
            "STELLA_HOME", "STELLA_EVAL_MODEL_ENDPOINT", "PYTEST_ADDOPTS", "PYTHONPATH",
        }:
            env.pop(key, None)
    env["STELLA_HOME"] = str(home)
    env["PYTHONHASHSEED"] = "0"
    env["NO_COLOR"] = "1"
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    return env


def _run_scenario(
    scenario: dict[str, Any], *, run_dir: Path, timeout: float
) -> dict[str, Any]:
    scenario_id = scenario["id"]
    log_path = run_dir / f"{scenario_id}.log"
    home = run_dir / "stella-home" / scenario_id
    home.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--tb=short",
        *scenario["tests"],
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=_child_env(home),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        log_path.write_text(output, encoding="utf-8")
        return {
            "id": scenario_id,
            "status": "INCOMPLETE",
            "detail": "scenario pytest command exceeded its configured timeout",
            "log": log_path.relative_to(run_dir.parent).as_posix(),
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
    log_path.write_text(completed.stdout, encoding="utf-8")
    return {
        "id": scenario_id,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "detail": "mapped pytest selectors passed" if completed.returncode == 0 else "mapped pytest selectors failed",
        "returncode": completed.returncode,
        "log": log_path.relative_to(run_dir.parent).as_posix(),
        "duration_ms": round((time.monotonic() - started) * 1000),
    }


def _run_package_checks(workdir: Path, *, timeout: float) -> dict[str, Any]:
    package_root = workdir / "packages"
    standalone = package_root / "standalone-python"
    oneclick = package_root / "oneclick-python" / "resources"
    package_root.mkdir(parents=True, exist_ok=True)
    home = workdir / "package-staging-home"
    home.mkdir(parents=True, exist_ok=True)
    env = _child_env(home)
    commands = (
        (
            "standalone",
            [
                sys.executable,
                str(ROOT / "scripts" / "build_release_package.py"),
                "standalone-python",
                "--source",
                str(ROOT),
                "--output",
                str(standalone),
            ],
        ),
        (
            "oneclick-resources",
            [
                sys.executable,
                str(ROOT / "scripts" / "build_release_package.py"),
                "oneclick-python",
                "--source",
                str(ROOT),
                "--output",
                str(package_root / "oneclick-python" / "installer.exe"),
                "--stage-resources",
                str(oneclick),
            ],
        ),
    )
    logs: dict[str, str] = {}
    for label, command in commands:
        log = package_root / f"{label}.log"
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            log.write_text(output, encoding="utf-8")
            return {"status": "INCOMPLETE", "detail": f"{label} staging timed out", "logs": logs}
        log.write_text(result.stdout, encoding="utf-8")
        logs[label] = log.relative_to(workdir).as_posix()
        if result.returncode != 0:
            return {
                "status": "FAIL",
                "detail": f"{label} staging failed with exit code {result.returncode}",
                "logs": logs,
            }

    imported: list[str] = []
    for label, staged_root in (("standalone", standalone), ("oneclick-resources", oneclick)):
        if not (staged_root / "gravitas" / "__init__.py").is_file():
            return {
                "status": "FAIL",
                "detail": f"{label} staging omitted the Gravitas package",
                "logs": logs,
            }
        import_code = (
            "import pathlib, gravitas, gravitas.controller, core.runtime.facade; "
            "root=pathlib.Path(__import__('os').environ['PYTHONPATH']).resolve(); "
            "assert pathlib.Path(gravitas.__file__).resolve().is_relative_to(root); "
            "print('staged import ok')"
        )
        log = package_root / f"{label}-import.log"
        try:
            result = subprocess.run(
                [sys.executable, "-c", import_code],
                cwd=workdir,
                env=_child_env(home, pythonpath=staged_root),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            log.write_text(output, encoding="utf-8")
            logs[f"{label}-import"] = log.relative_to(workdir).as_posix()
            return {
                "status": "INCOMPLETE",
                "detail": f"{label} staged import timed out",
                "logs": logs,
            }
        log.write_text(result.stdout, encoding="utf-8")
        logs[f"{label}-import"] = log.relative_to(workdir).as_posix()
        if result.returncode != 0:
            return {
                "status": "FAIL",
                "detail": f"{label} staged import failed with exit code {result.returncode}",
                "logs": logs,
            }
        imported.append(label)
    return {
        "status": "PASS",
        "detail": "Standalone Python and OneClick Python resources staged and imported Gravitas/runtime modules",
        "imported": imported,
        "logs": logs,
    }


def _make_report(
    *,
    seed: int,
    dataset_digest: str,
    run_index: int,
    outcomes: list[dict[str, Any]],
    model_status: str,
    package_result: dict[str, Any],
) -> ExperimentReport:
    base_sequence = len(outcomes)
    rows = [
        SampleRecord(
            event_id=result["id"],
            sequence=index,
            group_id="gravitas-v1",
            status="ok" if result["status"] == "PASS" else "dropped",
            drop_reason=None if result["status"] == "PASS" else result["status"].lower(),
            decision_level=result["status"],
            flags=["scenario"],
        )
        for index, result in enumerate(outcomes, start=1)
    ]
    rows.extend(
        (
            SampleRecord(
                event_id="MODEL-TRACE",
                sequence=base_sequence + 1,
                group_id="gravitas-v1",
                status="ok" if model_status == "PASS" else "dropped",
                drop_reason=None if model_status == "PASS" else "model_trace_failed",
                decision_level=model_status,
                flags=["state_model"],
            ),
            SampleRecord(
                event_id="PACKAGE-IMPORT",
                sequence=base_sequence + 2,
                group_id="gravitas-v1",
                status="ok" if package_result["status"] == "PASS" else "dropped",
                drop_reason=None if package_result["status"] == "PASS" else package_result["status"].lower(),
                decision_level=package_result["status"],
                flags=["release_layout"],
            ),
        )
    )
    completed = (
        all(result["status"] == "PASS" for result in outcomes)
        and model_status == "PASS"
        and package_result["status"] == "PASS"
    )
    report = ExperimentReport(
        run_id=f"gravitas-v1-{seed}-replay-{run_index}",
        mode="v1_fake_acceptance",
        status="completed" if completed else "failed",
        seed=seed,
        dataset_digest=dataset_digest,
        model_calls=0,
        send_calls=0,
        started_utc=datetime.now(timezone.utc).isoformat(),
        workdir="<explicit-workdir>",
        samples=rows,
        stability=StabilityReport.build(rows),
    )
    for result in outcomes:
        report.stability.add_dimension(
            result["id"],
            DimensionStatus[result["status"]],
            result["detail"],
            [] if result["status"] == "PASS" else [result["id"]],
        )
    report.stability.add_dimension(
        "generated_state_trace",
        DimensionStatus[model_status],
        "seeded trace checked resource, deadline, receipt, capture-watermark and shadow-model invariants",
        [] if model_status == "PASS" else ["MODEL-TRACE"],
    )
    report.stability.add_dimension(
        "release_package_layout_and_import",
        DimensionStatus[package_result["status"]],
        package_result["detail"],
        [] if package_result["status"] == "PASS" else ["PACKAGE-IMPORT"],
    )
    report.stability.add_dimension(
        "live_model_and_platform",
        DimensionStatus.SKIPPED,
        "Not run; requires a separately authorized external environment.",
    )
    report.stability.add_dimension(
        "clean_vm_and_release_acceptance",
        DimensionStatus.SKIPPED,
        "Not run; offline package staging/import is not a clean-VM release test.",
    )
    report.finalize()
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="run_gravitas_evaluation")
    parser.add_argument("--suite", type=Path, required=True, help="explicit directory containing suite.json")
    parser.add_argument("--workdir", type=Path, required=True, help="new or empty report/work directory")
    parser.add_argument("--seed", type=int, required=True, help="deterministic replay seed")
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS, help="model trace length (100–1000)")
    parser.add_argument(
        "--trace-seeds",
        type=int,
        default=DEFAULT_TRACE_SEEDS,
        help=f"consecutive deterministic trace seeds to evaluate (1–{MAX_TRACE_SEEDS})",
    )
    parser.add_argument("--repeat", type=int, default=2, help="same-seed suite replays; minimum 2")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--json", action="store_true", help="write the complete JSON report to stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not 2 <= args.repeat <= 10:
        print("[gravitas-evaluation] --repeat must be between 2 and 10", file=sys.stderr)
        return EXIT_FAILED
    if not MIN_STEPS <= args.steps <= MAX_STEPS:
        print(f"[gravitas-evaluation] --steps must be between {MIN_STEPS} and {MAX_STEPS}", file=sys.stderr)
        return EXIT_FAILED
    if not 1 <= args.trace_seeds <= MAX_TRACE_SEEDS:
        print(
            f"[gravitas-evaluation] --trace-seeds must be between 1 and {MAX_TRACE_SEEDS}",
            file=sys.stderr,
        )
        return EXIT_FAILED
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        print("[gravitas-evaluation] --timeout-seconds must be positive", file=sys.stderr)
        return EXIT_FAILED

    workdir = args.workdir.expanduser().resolve()
    try:
        if workdir.exists() and (not workdir.is_dir() or any(workdir.iterdir())):
            raise ValueError("workdir must be new or empty; existing data will not be overwritten")
        workdir.mkdir(parents=True, exist_ok=True)
        suite, suite_path = _load_suite(args.suite)
        fingerprint = _source_fingerprint(suite, suite_path)
        try:
            trace_evaluation = _evaluate_seeded_traces(
                args.seed, args.steps, args.trace_seeds
            )
        except TraceViolationError as exc:
            failure = {
                "seed": exc.seed,
                "policy_version": suite["policy_version"],
                "invariant": exc.invariant,
                "violation": exc.detail,
                "minimal_failing_prefix": exc.trace,
                "source_fingerprint": fingerprint,
            }
            (workdir / "model-trace-failure.json").write_text(
                json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"[gravitas-evaluation] {exc}; minimal trace saved to "
                f"{workdir / 'model-trace-failure.json'}",
                file=sys.stderr,
            )
            return EXIT_FAILED
        model_status = (
            "PASS" if trace_evaluation["all_effects_equivalent"] else "FAIL"
        )
        package_result = _run_package_checks(workdir, timeout=args.timeout_seconds)
    except (OSError, SuiteError, ValueError) as exc:
        print(f"[gravitas-evaluation] {exc}", file=sys.stderr)
        return EXIT_FAILED

    model_meta = {
        "first_seed": args.seed,
        "seed_count": args.trace_seeds,
        "steps_per_seed": args.steps,
        "seed_results": trace_evaluation["results"],
        "policy_version": suite["policy_version"],
        "effect_equivalent": trace_evaluation["all_effects_equivalent"],
    }
    dataset_digest = _canonical_digest({
        "suite_sha256": _sha256(suite_path.read_bytes()),
        "source_fingerprint": fingerprint,
        "model": model_meta,
    })

    run_reports: list[ExperimentReport] = []
    run_outcomes: list[list[dict[str, Any]]] = []
    for run_index in range(1, args.repeat + 1):
        run_dir = workdir / "runs" / f"replay-{run_index}"
        run_dir.mkdir(parents=True, exist_ok=False)
        outcomes = [
            _run_scenario(scenario, run_dir=run_dir, timeout=args.timeout_seconds)
            for scenario in suite["scenarios"]
        ]
        run_outcomes.append(outcomes)
        report = _make_report(
            seed=args.seed,
            dataset_digest=dataset_digest,
            run_index=run_index,
            outcomes=outcomes,
            model_status=model_status,
            package_result=package_result,
        )
        run_reports.append(report)

    replay_digests = [report.semantic_digest() for report in run_reports]
    replay_equal = len(set(replay_digests)) == 1
    final_report = run_reports[-1]
    final_report.stability.add_dimension(
        "same_seed_semantic_digest",
        DimensionStatus.PASS if replay_equal else DimensionStatus.FAIL,
        "same seed and source fingerprint produced matching semantic digests"
        if replay_equal
        else "repeated runs produced different semantic digests",
        [] if replay_equal else ["MODEL-TRACE"],
    )
    final_report.status = (
        "completed"
        if replay_equal and all(report.status == "completed" for report in run_reports)
        else "failed"
    )
    final_report.finished_utc = datetime.now(timezone.utc).isoformat()
    report_dict = final_report.to_dict()
    report_dict["seed_trace"] = {
        **model_meta,
        "generated_event_count_per_seed": args.steps,
        "generated_event_count_total": args.steps * args.trace_seeds,
        "source_fingerprint": fingerprint,
        "invariants_checked_by_model": ["I01", "I02", "I03", "I04", "I05", "I09", "I10"],
    }
    report_dict["replay_digests"] = replay_digests
    report_dict["scenario_runs"] = run_outcomes
    report_dict["package_checks"] = package_result
    report_path = workdir / "report.json"
    report_path.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not replay_equal:
        failure = {
            "seed": args.seed,
            "policy_version": suite["policy_version"],
            "source_fingerprint": fingerprint,
            "replay_digests": replay_digests,
            "model_trace_digest": _canonical_digest(
                [item["off_trace_digest"] for item in trace_evaluation["results"]]
            ),
        }
        (workdir / "determinism-failure.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(report_dict, ensure_ascii=False, indent=2))
    else:
        print(
            f"[gravitas-evaluation] status={final_report.status} seed={args.seed}"
            f" seeds={args.trace_seeds} scenarios={len(suite['scenarios'])}"
            f" steps_per_seed={args.steps}"
            f" digest={final_report.semantic_digest()} report={report_path}"
        )
        for dimension in final_report.stability.dimensions:
            print(f"  - {dimension.name}: {dimension.status.value}")
    return EXIT_OK if final_report.status == "completed" else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
