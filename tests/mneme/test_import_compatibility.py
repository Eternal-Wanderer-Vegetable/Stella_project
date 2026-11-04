# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""S1-03 import compatibility tests (2026-11-03 plan §3.1/§8.2).

Legacy ``memory.*`` and canonical ``mneme.*`` must resolve to the same
module objects (one global state, one monkeypatch target, one DB_PATH), the
CLI trampolines must preserve exit codes in fresh subprocesses, and the
compat layer must not duplicate import side effects.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_PAIRS = [
    ("memory.schema", "mneme.schema"),
    ("memory.consolidator", "mneme.consolidator"),
    ("memory.retrieval_v2", "mneme.retrieval_v2"),
    ("memory.pre_processors", "mneme.pre_processors"),
    ("memory.post_processors", "mneme.post_processors"),
    ("memory.evidence_contract", "mneme.evidence_contract"),
    ("memory.expression_learning", "mneme.expression_learning"),
    ("memory.embeddings", "mneme.embeddings"),
    ("memory.ownership", "mneme.ownership"),
    ("memory.policy", "mneme.policy"),
    ("memory.timeutil", "mneme.timeutil"),
    ("memory.trace", "mneme.trace"),
    ("memory.memory_manager", "mneme.memory_manager"),
    ("memory.benchmark", "mneme.benchmark"),
    ("memory.session_compact", "mneme.session_compact"),
    ("memory.session_context", "mneme.session_context"),
    ("memory.social_store", "mneme.social_store"),
]


def test_legacy_and_canonical_are_same_module_objects() -> None:
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
    )
    assert proc.returncode == 0, proc.stderr
    assert "IDENTITY OK" in proc.stdout


def test_monkeypatch_db_path_reaches_one_implementation() -> None:
    """Patching the legacy alias must hit the canonical module (same object)."""
    import memory.schema as legacy_schema
    import mneme.schema as canonical_schema

    assert legacy_schema is canonical_schema
    sentinel = object()
    original = canonical_schema.DB_PATH
    try:
        legacy_schema.DB_PATH = sentinel  # type: ignore[attr-defined]
        assert canonical_schema.DB_PATH is sentinel
    finally:
        canonical_schema.DB_PATH = original


def test_single_global_state_through_both_paths() -> None:
    """Legacy accessor returns the canonical singleton, not a second one."""
    from memory.consolidator import get_consolidator as legacy_get
    from memory.proactive import get_proactive as legacy_proactive
    from mneme.consolidator import get_consolidator as canonical_get
    from mneme.consolidator import get_consolidator as canonical_get2

    assert legacy_get() is canonical_get()
    assert canonical_get() is canonical_get2()
    assert legacy_proactive() is legacy_proactive()


def test_cli_trampoline_exit_codes_match_in_fresh_subprocess() -> None:
    """``python -m memory.schema`` and ``python -m mneme.schema`` must agree."""
    for args in (["--help"], ["--version"]):
        old = subprocess.run(
            [sys.executable, "-m", "memory.schema", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        new = subprocess.run(
            [sys.executable, "-m", "mneme.schema", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert old.returncode == new.returncode, (args, old.stderr, new.stderr)


def test_importing_legacy_package_does_not_eagerly_load_mneme() -> None:
    """``import memory`` stays light: only the package object, no mneme import."""
    code = (
        "import sys; import memory; "
        "loaded = [m for m in sys.modules if m == 'mneme' or m.startswith('mneme.')]; "
        "print(loaded); assert not loaded, loaded"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
