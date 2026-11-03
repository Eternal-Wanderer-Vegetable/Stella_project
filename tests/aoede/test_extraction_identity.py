# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""S1-02 extraction identity tests (2026-11-03 plan §3.1 compat strategy).

``memory.*`` must be explicit aliases of the canonical ``aoede.*`` modules:
same module objects (monkeypatch/singletons hit one implementation), same
classes through submodules, and single-subprocess import with no duplicate
scheduler/task registries.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_PAIRS = [
    ("memory.proactive", "aoede.controller"),
    ("memory.proactive_gate", "aoede.gate"),
    ("memory.proactive_state", "aoede.storage.legacy_state"),
    ("memory.proactive_target", "aoede.verification.target"),
    ("memory.proactive_prompt", "aoede.prompts"),
    ("memory.proactive_contract", "aoede.contract"),
    ("memory.participation", "aoede.participation"),
    ("memory.participation.buffer", "aoede.participation.buffer"),
    ("memory.participation.decision", "aoede.participation.decision"),
    ("memory.participation.observability", "aoede.participation.observability"),
    ("memory.participation.scorer", "aoede.participation.scorer"),
    ("memory.participation.signals", "aoede.participation.signals"),
    ("memory.participation.state", "aoede.participation.state"),
    ("memory.participation.tables", "aoede.participation.tables"),
]


def test_legacy_and_canonical_modules_are_same_objects() -> None:
    """Every legacy alias module must BE the canonical module object."""
    code = [
        "import sys",
        f"pairs = {_PAIRS!r}",
        "for legacy, canonical in pairs:",
        "    __import__(legacy)",
        "    __import__(canonical)",
        "    assert sys.modules[legacy] is sys.modules[canonical], legacy",
        "print('IDENTITY OK')",
    ]
    proc = subprocess.run(
        [sys.executable, "-c", "\n".join(code)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**__import__("os").environ},
    )
    assert proc.returncode == 0, proc.stderr
    assert "IDENTITY OK" in proc.stdout


def test_classes_resolve_identically_through_both_paths() -> None:
    from memory.participation.buffer import BufferedMessage as LegacyBuffered
    from memory.participation.decision import DecisionTracker as LegacyTracker

    from aoede.controller import ProactiveController as CanonicalController
    from aoede.participation.buffer import BufferedMessage as CanonicalBuffered
    from aoede.participation.decision import DecisionTracker as CanonicalTracker
    from memory.proactive import ProactiveController as LegacyController

    assert LegacyController is CanonicalController
    assert LegacyBuffered is CanonicalBuffered
    assert LegacyTracker is CanonicalTracker


def test_gateway_singleton_alias_reaches_canonical() -> None:
    """ai_gateway imports the canonical singletons (one instance, no dupes)."""
    from aoede.controller import get_proactive as canonical_get_proactive
    from aoede.participation import (
        get_participation_manager as canonical_get_manager,
    )
    from aoede.storage.legacy_state import record_at as canonical_record_at
    from stella_project.plugins.bot_main import ai_gateway

    assert ai_gateway.get_proactive is canonical_get_proactive
    assert ai_gateway.get_participation_manager is canonical_get_manager
    assert ai_gateway.record_at is canonical_record_at


def test_gateway_host_forwards_module_attributes() -> None:
    """The host registers proactive tasks into the gateway's own registry,
    shared with the shutdown drain (old ``_reply_check_tasks`` semantics)."""
    from unittest.mock import Mock

    from stella_project.plugins.bot_main.ai_gateway import (
        _reply_check_tasks,
        get_proactive_host,
    )

    host = get_proactive_host()
    probe = Mock()
    host.register_task(probe)
    assert probe in _reply_check_tasks
