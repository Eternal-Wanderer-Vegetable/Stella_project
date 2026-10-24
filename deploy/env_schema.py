# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Compatibility adapter for the side-effect-free environment schema reader."""

from __future__ import annotations

from pathlib import Path

from stella_bootstrap.env_schema import build_schema as _build_schema

from . import env_keys


def build_schema(settings_path: Path) -> dict:
    """Build the legacy GUI schema, hiding retired and superseded keys."""
    schema = _build_schema(settings_path)
    schema["fields"] = [
        field
        for field in schema["fields"]
        if not env_keys.deprecation_reason(field["key"])
        and not env_keys.superseded_by(field["key"])
    ]
    schema["superseded_keys"] = sorted(env_keys.SUPERSEDED)
    return schema
