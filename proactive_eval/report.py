# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Schema-checked, atomic report output for proactive evaluation runs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def validate_proactive_report(report: dict[str, Any]) -> None:
    schema_dir = Path(__file__).with_name("schemas")
    common = json.loads((schema_dir / "evaluation-report-common.schema.json").read_text(encoding="utf-8"))
    schema = json.loads((schema_dir / "stella-proactive-report-1.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(common["$id"], Resource.from_contents(common))
    Draft202012Validator(schema, registry=registry).validate(report)


def write_proactive_report(path: Path, report: dict[str, Any]) -> str:
    """Validate and atomically write JSON; return its SHA-256 digest."""
    validate_proactive_report(report)
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
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
    return hashlib.sha256(payload).hexdigest()


__all__ = ["validate_proactive_report", "write_proactive_report"]
