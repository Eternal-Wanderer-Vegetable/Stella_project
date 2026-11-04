# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""One-way JSONL IPC to isolated actor and scorer plugin processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Any

from typing_extensions import Self


class PluginProcess:
    """Persistent, serial worker. The caller chooses which data crosses IPC."""

    def __init__(self, role: str, specification: str, isolated_home: Path):
        if role not in ("actor", "scorer"):
            raise ValueError(f"unsupported plugin role: {role}")
        environment = _worker_environment(isolated_home)
        self._process = subprocess.Popen(
            [sys.executable, "-m", "proactive_eval.worker", role, specification],
            cwd=isolated_home,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self.role = role

    def call(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        process = self._process
        if process.poll() is not None or process.stdin is None or process.stdout is None:
            raise RuntimeError(f"{self.role} plugin process is not running")
        process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        process.stdin.flush()
        response_line = process.stdout.readline()
        if not response_line:
            raise RuntimeError(f"{self.role} plugin exited without a response")
        response = json.loads(response_line)
        if not isinstance(response, dict) or not response.get("ok"):
            error = response.get("error", {}) if isinstance(response, dict) else {}
            raise RuntimeError(
                f"{self.role} plugin failed: {error.get('type', 'ProtocolError')} "
                f"({error.get('message_sha256', 'no-digest')})"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise TypeError(f"{self.role} plugin must return a JSON object")
        return result

    def close(self) -> None:
        process = self._process
        if process.poll() is None and process.stdin is not None:
            try:
                process.stdin.write('{"__stop__":true}\n')
                process.stdin.flush()
                process.stdin.close()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                # Only the child created by this object is terminated.
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        for stream in (process.stdin, process.stdout):
            if stream is not None and not stream.closed:
                stream.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _worker_environment(isolated_home: Path) -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT")
    environment = {key: os.environ[key] for key in keep if key in os.environ}
    environment.update({
        "STELLA_HOME": str(isolated_home.resolve()),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
    })
    return environment


__all__ = ["PluginProcess"]
