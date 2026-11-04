# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Canonical run fingerprints over effective inputs, not only CLI overrides."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from proactive_eval.adapters import sha256_file


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def effective_config_sha256(config: Mapping[str, Any]) -> str:
    """Hash the fully resolved config while rejecting credential material."""
    _reject_secrets(config)
    return canonical_sha256(config)


def make_fingerprint(
    *,
    repository: Path,
    dataset_registry: Path,
    scenario_file: Path,
    gold_file: Path | None,
    protocol_file: Path,
    effective_config: Mapping[str, Any],
    model: Mapping[str, Any] | None = None,
    tokenizer: Mapping[str, Any] | None = None,
    backend: Mapping[str, Any] | None = None,
    dependencies: Mapping[str, Any] | None = None,
    platform_hardware: Mapping[str, Any] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Return the frozen report-schema fingerprint shape plus its digest."""
    components = {
        "code_commit": _git(repository, "rev-parse", "HEAD") or "UNKNOWN",
        "dirty_tree_digest": working_tree_digest(repository),
        "dataset_registry_sha256": sha256_file(dataset_registry),
        "scenario_schema": "stella-proactive-scenario/1",
        "report_schema": "stella-proactive-report/1",
        "effective_config_sha256": effective_config_sha256(effective_config),
        "prompt_hashes": {},
        "model": dict(model or {}),
        "tokenizer": dict(tokenizer) if tokenizer is not None else None,
        "backend": dict(backend or {}),
        "dependencies": dict(dependencies or {}),
        "platform_hardware": dict(platform_hardware or {}),
        "seed": seed,
        "protocol_sha256": sha256_file(protocol_file),
        "scenario_sha256": sha256_file(scenario_file),
    }
    if gold_file is not None:
        components["gold_sha256"] = sha256_file(gold_file)
    return {"sha256": canonical_sha256(components), "components": components}


def working_tree_digest(repository: Path) -> str | None:
    """Hash tracked diffs and non-ignored untracked files without printing them."""
    try:
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--"],
            cwd=repository,
            capture_output=True,
            timeout=30,
            check=True,
        ).stdout
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=repository,
            capture_output=True,
            timeout=30,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    digest = hashlib.sha256()
    digest.update(diff)
    for raw_path in filter(None, untracked.split(b"\0")):
        relative = Path(raw_path.decode("utf-8", errors="strict"))
        relative_text = relative.as_posix()
        # Avoid traversing unrelated local data, logs, extensions, or operator scripts.
        if not relative_text.startswith((
            "proactive_eval/", "core/evaluation/", "memory_eval/", "tests/evaluation/"
        )):
            continue
        candidate = repository / relative
        if not candidate.is_file():
            continue
        digest.update(raw_path)
        digest.update(bytes.fromhex(sha256_file(candidate)))
    return digest.hexdigest()


def _reject_secrets(value: Any, prefix: str = "config") -> None:
    forbidden = ("api_key", "apikey", "password", "secret", "credential", "access_token")
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(marker in key_text for marker in forbidden):
                raise ValueError(f"secret-bearing config key must be omitted from fingerprint: {prefix}.{key}")
            _reject_secrets(child, f"{prefix}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{prefix}[{index}]")


def _git(repository: Path, *args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=repository, capture_output=True, text=True,
            timeout=10, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


__all__ = [
    "canonical_sha256",
    "effective_config_sha256",
    "make_fingerprint",
    "working_tree_digest",
]
