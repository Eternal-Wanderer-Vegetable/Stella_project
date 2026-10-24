# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""AST-only schema discovery for environment values read by ``config.settings``."""

from __future__ import annotations

import ast
from collections.abc import Collection
from pathlib import Path

_INHERIT_FUNCS = frozenset({"_env_inherit", "_env_int_inherit", "_env_float_inherit"})
_ENV_FUNCS = frozenset(
    {
        "_env",
        "_env_int",
        "_env_float",
        "_env_path",
        "_env_bool",
        "_env_int_set",
        "_env_str_list",
        "_env_choice",
    }
) | _INHERIT_FUNCS
_FIELD_TYPES = {
    "_env": "string",
    "_env_int": "int",
    "_env_float": "float",
    "_env_path": "path",
    "_env_bool": "bool",
    "_env_int_set": "int_set",
    "_env_str_list": "str_list",
    "_env_choice": "choice",
    "_env_inherit": "string",
    "_env_int_inherit": "int",
    "_env_float_inherit": "float",
}


def build_schema(
    settings_path: Path, *, excluded_keys: Collection[str] = ()
) -> dict:
    """Return active environment fields without importing ``config.settings``."""
    source = settings_path.read_text(encoding="utf-8")
    lines = source.splitlines()
    sections = _sections_by_line(lines)
    tree = ast.parse(source, filename=str(settings_path))
    hidden = set(excluded_keys)
    fields = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        call = next(
            (
                child
                for child in ast.walk(node.value)
                if isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id in _ENV_FUNCS
                and _env_key(child)
            ),
            None,
        )
        if call is None:
            continue
        key = _env_key(call)
        if key in hidden:
            continue
        field = {
            "key": key,
            "section": sections[node.lineno - 1],
            "description": _description_before(lines, node.lineno),
            "default": _default_value(call),
            "type": _FIELD_TYPES.get(call.func.id, "string"),
        }
        if call.func.id == "_env_choice":
            field["choices"] = _choice_values(call)
        parent = _inherits_from(call)
        if parent:
            field["inherits"] = parent
        fields.append(field)
    return {"version": 1, "fields": fields}


def _sections_by_line(lines: list[str]) -> list[str]:
    section = "其他设置"
    sections = []
    for line in lines:
        text = line.strip()
        if text.startswith("# ----------") and text.endswith("----------"):
            section = text.removeprefix("#").strip().strip("-").strip()
        sections.append(section)
    return sections


def _description_before(lines: list[str], lineno: int) -> str:
    description: list[str] = []
    index = lineno - 2
    while index >= 0:
        line = lines[index].strip()
        if not line:
            if description:
                break
            index -= 1
            continue
        if not line.startswith("#"):
            break
        text = line[1:].strip()
        if text.startswith("----------") and text.endswith("----------"):
            break
        if text:
            description.append(text)
        index -= 1
    return " ".join(reversed(description))


def _env_key(call: ast.Call) -> str:
    if not call.args:
        return ""
    first = call.args[0]
    if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
        return ""
    key = first.value
    if not key or not key.replace("_", "").isalnum() or key.upper() != key:
        return ""
    return key


def _inherits_from(call: ast.Call) -> str:
    if not isinstance(call.func, ast.Name) or call.func.id not in _INHERIT_FUNCS:
        return ""
    if len(call.args) < 2 or not isinstance(call.args[1], ast.Name):
        return ""
    return call.args[1].id


def _default_value(call: ast.Call) -> str:
    if len(call.args) < 2:
        return ""
    try:
        value = ast.literal_eval(call.args[1])
    except (ValueError, TypeError):
        return ""
    return str(value)


def _choice_values(call: ast.Call) -> list[str]:
    if len(call.args) < 3:
        return []
    try:
        value = ast.literal_eval(call.args[2])
    except (ValueError, TypeError):
        return []
    return [str(item) for item in value]
