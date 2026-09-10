# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Deterministic extraction and validation for capability inputs.

The parser deliberately has no NLP or model fallback.  A capability may declare
an extraction rule in ``input_schema``; tool JSON schema remains the final
required-field boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InputParseResult:
    values: dict[str, Any] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    ambiguous: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing and not self.ambiguous and not self.errors


def merge_schemas(
    capability_schema: dict[str, Any] | None,
    tool_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge capability extraction declarations with a tool JSON schema."""
    capability_schema = capability_schema or {}
    tool_schema = tool_schema or {}
    properties: dict[str, Any] = {}
    properties.update(capability_schema.get("properties") or {})
    for name, spec in (tool_schema.get("properties") or {}).items():
        current = dict(properties.get(name) or {})
        current.update(spec or {})
        properties[name] = current
    required = list(dict.fromkeys([
        *(capability_schema.get("required") or []),
        *(tool_schema.get("required") or []),
    ]))
    merged = dict(capability_schema)
    merged["properties"] = properties
    merged["required"] = required
    return merged


def _patterns(spec: dict[str, Any]) -> list[str]:
    raw = spec.get("regex", spec.get("pattern", spec.get("extract")))
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw if item]
    if isinstance(raw, dict):
        value = raw.get("regex") or raw.get("pattern")
        return [str(value)] if value else []
    return []


def _convert(value: Any, spec: dict[str, Any]) -> Any:
    value = value.strip() if isinstance(value, str) else value
    kind = str(spec.get("type") or "string").lower()
    if kind in ("string", "str"):
        return str(value)
    if kind in ("integer", "int"):
        return int(value)
    if kind in ("number", "float"):
        return float(value)
    if kind in ("boolean", "bool"):
        if isinstance(value, bool):
            return value
        lowered = str(value).lower()
        if lowered in {"true", "1", "yes", "是", "有"}:
            return True
        if lowered in {"false", "0", "no", "否", "无"}:
            return False
        raise ValueError(f"无法将 {value!r} 转换为布尔值")
    return value


def _extract_one(message: str, name: str, spec: dict[str, Any]) -> tuple[Any, str | None]:
    patterns = _patterns(spec)
    matches: list[str] = []
    for pattern in patterns:
        try:
            found = list(re.finditer(pattern, message, flags=re.IGNORECASE))
        except re.error as exc:
            return None, f"{name} 的 regex 无效: {exc}"
        for match in found:
            if match.groupdict().get(name):
                matches.append(match.group(name))
            elif match.groups():
                matches.append(match.group(1))
            else:
                matches.append(match.group(0))
    unique = list(dict.fromkeys(item.strip() for item in matches if item and item.strip()))
    if len(unique) > 1:
        return None, "ambiguous"
    if not unique:
        if "default" in spec:
            return spec["default"], None
        return None, None
    try:
        value = _convert(unique[0], spec)
    except (TypeError, ValueError) as exc:
        return None, f"{name} 类型转换失败: {exc}"
    enum = spec.get("enum")
    if enum and value not in enum:
        return None, f"{name} 不在允许值中"
    return value, None


def parse_input(message: str, schema: dict[str, Any] | None) -> InputParseResult:
    """Extract and validate only values explicitly described by ``schema``."""
    schema = schema or {}
    values: dict[str, Any] = {}
    missing: list[str] = []
    ambiguous: list[str] = []
    errors: list[str] = []
    properties = schema.get("properties") or {}
    for name, raw_spec in properties.items():
        spec = raw_spec if isinstance(raw_spec, dict) else {}
        value, error = _extract_one(message or "", str(name), spec)
        if error == "ambiguous":
            ambiguous.append(str(name))
        elif error:
            errors.append(error)
        elif value is not None:
            values[str(name)] = value
    for name in schema.get("required") or []:
        if name not in values:
            if name not in ambiguous and not any(str(name) in error for error in errors):
                missing.append(str(name))
    return InputParseResult(
        values=values,
        missing=tuple(missing),
        ambiguous=tuple(ambiguous),
        errors=tuple(errors),
    )


__all__ = ["InputParseResult", "merge_schemas", "parse_input"]
