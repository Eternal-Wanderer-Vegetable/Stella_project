# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Control-flow signals shared by Gravitas runtime adapters."""

from __future__ import annotations


class DeadlineExceeded(RuntimeError):  # noqa: N818 - named control signal from plan §5.3
    """A total turn deadline expired during a named runtime phase.

    The phase is a bounded internal label. It intentionally carries no chat,
    identity, or prompt data so callers can report the control outcome safely.
    """

    def __init__(self, phase: str) -> None:
        label = str(phase).strip()
        if not label:
            raise ValueError("phase must be a non-empty label")
        self.phase = label
        super().__init__(f"turn deadline exceeded during {label}")
