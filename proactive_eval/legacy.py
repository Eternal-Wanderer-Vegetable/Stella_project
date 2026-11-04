# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Read-only adapter for historical memory_eval reports; source files stay intact."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from proactive_eval.adapters import sha256_file

LEGACY_REPORT_SCHEMA = "memory-eval-report/1"


def read_legacy_memory_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("report_schema") != LEGACY_REPORT_SCHEMA:
        raise ValueError(f"unsupported historical memory_eval report: {path}")
    return {
        "schema": LEGACY_REPORT_SCHEMA,
        "evidence_status": "historical_reference",
        "source_path": str(path),
        "source_sha256": sha256_file(path),
        "generated_at": report.get("generated_at"),
        "git_head": report.get("git_head"),
        "dataset": report.get("dataset"),
        "channel": report.get("channel"),
        "summary": report.get("summary"),
    }


__all__ = ["LEGACY_REPORT_SCHEMA", "read_legacy_memory_report"]
