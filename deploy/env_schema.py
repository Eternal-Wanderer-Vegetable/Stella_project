# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""从 config/settings.py 提取 .env 配置 schema，不导入运行时配置模块。

「这个键还算不算数」不在这里判断——判据统一读 ``deploy/env_keys.py`` 的登记表。
本模块曾用「注释里有没有『废弃』二字」来猜，结果把两个**在用**的键误判剔除：
``CONSOLIDATION_LM_STUDIO_BASE_URL``（注释提到 FlexiWeb 流程已弃用）与
``MEMORY_COMPRESS_LOG_PATH``（注释提到旧键登记在 ``_DEPRECATED_KEYS`` 里）——
后者恰恰是替换旧键的那个**新**键。被剔除的键在 GUI 里完全不可见，用户改不到。
"""

from __future__ import annotations

import ast
from pathlib import Path

from . import env_keys

# 继承型默认值的助手名：第二个实参不是字面量，而是「父配置项」的变量。
# 这类项的 default 无法静态求值，必须改用 inherits 告诉 GUI「留空即继承谁」。
# int / float 版与 _env_int / _env_float 行为完全相同，独立命名的唯一目的就是
# 让这里能识别出「这一项是继承型」——见 config/settings.py 里 _env_int_inherit。
_INHERIT_FUNCS = frozenset({"_env_inherit", "_env_int_inherit", "_env_float_inherit"})
_ENV_FUNCS = frozenset({"_env", "_env_int", "_env_float", "_env_path"}) | _INHERIT_FUNCS


def build_schema(settings_path: Path) -> dict:
    """返回所有 _env* 配置项的分组、说明与默认值。

    AST 能处理多行 _env 调用，避免前端按文本行解析时遗漏配置项。

    字段含 ``inherits`` 时表示「留空即继承该父键」：GUI 必须把它渲染成带提示的
    空输入框，并在用户留空时**不写入** ``.env``——写成 ``KEY=`` 会让
    ``_env_inherit`` 之外的读取方拿到空串，继承链被静默切断（见
    ``config/settings.py`` 里 ``_env_inherit`` 的说明）。
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
                and child.func.id in _ENV_FUNCS
                and _env_key(child)
            ),
            None,
        )
        if call is None:
            continue
        key = _env_key(call)
        # 废弃与否只认 env_keys 的登记表：注释是写给人看的自然语言，
        # 拿它做子串匹配会把「提到废弃」和「本身废弃」混为一谈。
        if env_keys.deprecation_reason(key):
            continue
        field = {
            "key": key,
            "section": sections[node.lineno - 1],
            "description": _description_before(lines, node.lineno),
            "default": _default_value(call),
        }
        parent = _inherits_from(call)
        if parent:
            field["inherits"] = parent
        fields.append(field)
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


def _env_key(call: ast.Call) -> str:
    """取 ``_env*(\"KEY\", ...)`` 的键名；不是合法的大写常量键则返回空串。

    合法性判据（全大写、只含字母数字下划线）与类型收窄放在一处，
    避免调用点两次重复同样的 isinstance 链。
    """
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
    """继承型配置项的父键名；非继承型返回空串。

    ``_env_inherit(\"子键\", 父键常量)`` 的第二个实参是 ``config/settings.py`` 里的
    模块级变量，而该文件里变量名与环境变量名一一对应，因此直接取变量名即是父键名。
    ``_env_int_inherit`` / ``_env_float_inherit`` 同理。
    """
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
        # 继承型默认值（父键变量）走不到字面量求值——那种情况由 _inherits_from
        # 输出 inherits 标记，default 保持空串。
        return ""
    return str(value)
