# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""从 config/settings.py 提取 .env 配置 schema，不导入运行时配置模块。"""

from __future__ import annotations

import ast
from pathlib import Path


def build_schema(settings_path: Path) -> dict:
    """返回所有 _env* 配置项的分组、说明与默认值。

    AST 能处理多行 _env 调用，避免前端按文本行解析时遗漏配置项。
    """
    source = settings_path.read_text(encoding="utf-8")
    lines = source.splitlines()
    sections = _sections_by_line(lines)
    tree = ast.parse(source, filename=str(settings_path))
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
                and child.func.id in {"_env", "_env_int", "_env_float", "_env_path"}
                and child.args
                and isinstance(child.args[0], ast.Constant)
                and isinstance(child.args[0].value, str)
            ),
            None,
        )
        if call is None:
            continue
        key = call.args[0].value
        if not key or not key.replace("_", "").isalnum() or key.upper() != key:
            continue
        description = _description_before(lines, node.lineno)
        if _is_deprecated(description):
            continue
        fields.append(
            {
                "key": key,
                "section": sections[node.lineno - 1],
                "description": description,
                "default": _default_value(call),
            }
        )
    return {"version": 1, "fields": fields}


def _sections_by_line(lines: list[str]) -> list[str]:
    """为每一行记录它所属的最近配置章节。"""
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


def _is_deprecated(description: str) -> bool:
    """兼容读取但已废弃的键不应被 GUI 重置或重新写入。"""
    return (
        "废弃" in description
        or "DEPRECATED" in description
        or ("取代" in description and "兼容既有 .env" in description)
    )


def _default_value(call: ast.Call) -> str:
    if len(call.args) < 2:
        return ""
    try:
        value = ast.literal_eval(call.args[1])
    except (ValueError, TypeError):
        return ""
    return str(value)
