# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Private JSONL worker entry point for :mod:`proactive_eval.plugins`."""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import sys
from collections.abc import Callable, Mapping
from typing import Any


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] not in ("actor", "scorer"):
        return 2
    role, specification = args
    try:
        with contextlib.redirect_stdout(sys.stderr):
            callback = _load_callable(specification)
    except Exception as exc:
        _write({"ok": False, "error": _error(exc)})
        return 2

    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request == {"__stop__": True}:
                break
            if not isinstance(request, dict):
                raise ValueError("request must be an object")
            with contextlib.redirect_stdout(sys.stderr):
                result = _invoke(role, callback, request)
            if not isinstance(result, Mapping):
                raise TypeError("plugin result must be an object")
            safe_result = json.loads(json.dumps(result, ensure_ascii=False, sort_keys=True))
            _write({"ok": True, "result": safe_result})
        except Exception as exc:
            _write({"ok": False, "error": _error(exc)})
    return 0


def _invoke(role: str, callback: Callable[..., Any], request: dict[str, Any]) -> Mapping[str, Any]:
    if role == "actor":
        if set(request) != {"scenario"}:
            raise ValueError("actor IPC accepts only the scenario field")
        scenario = request["scenario"]
        if not isinstance(scenario, dict):
            raise TypeError("actor scenario must be an object")
        return callback(scenario)
    if set(request) != {"gold", "actor_output"}:
        raise ValueError("scorer IPC accepts only gold and actor_output fields")
    gold = request["gold"]
    actor_output = request["actor_output"]
    if not isinstance(gold, dict) or not isinstance(actor_output, dict):
        raise TypeError("scorer inputs must be objects")
    return callback(gold, actor_output)


def _load_callable(specification: str) -> Callable[..., Any]:
    module_name, separator, attribute = specification.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("plugin must use module:callable syntax")
    value = getattr(importlib.import_module(module_name), attribute)
    if not callable(value):
        raise TypeError(f"plugin is not callable: {specification}")
    return value


def _error(exc: Exception) -> dict[str, str]:
    message = str(exc).encode("utf-8", errors="replace")
    return {
        "type": type(exc).__name__,
        "message_sha256": hashlib.sha256(message).hexdigest(),
    }


def _write(response: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
