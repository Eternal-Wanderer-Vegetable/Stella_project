# SPDX-License-Identifier: AGPL-3.0
"""零 token 的回复必要性门控。"""

from __future__ import annotations

from dataclasses import dataclass, field

from config import REPLY_GATE_PROACTIVE_COOLDOWN_SECONDS
from core.turn_runtime import get_turn_runtime


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    path: str
    score: float
    reasons: tuple[str, ...] = field(default_factory=tuple)


class ReplyGate:
    """硬触发直通；主动插话只增加本地状态与冷却约束。"""

    def __init__(self) -> None:
        self._runtime = get_turn_runtime()

    def evaluate(
        self,
        group_id: int,
        *,
        trigger: str,
        intent: str = "",
        now: float | None = None,
    ) -> GateDecision:
        # @ 回复、主动 @ 用户属于硬触发，不能被插话节奏门控吞掉。
        if trigger == "reply":
            return GateDecision(True, "hard_trigger", 1.0, ("explicit_reply",))

        allowed = self._runtime.can_start_proactive(
            group_id,
            REPLY_GATE_PROACTIVE_COOLDOWN_SECONDS,
            now=now,
        )
        if not allowed:
            return GateDecision(
                False,
                "silent",
                0.0,
                ("runtime_busy_or_proactive_cooldown", intent or "proactive"),
            )
        return GateDecision(True, "proactive", 0.5, ("local_gate", intent or "proactive"))

    def start(self, group_id: int, *, proactive: bool) -> None:
        self._runtime.start(group_id, proactive=proactive)

    def finish(self, group_id: int, *, waiting: bool = False) -> None:
        self._runtime.finish(group_id, waiting=waiting)


_gate = ReplyGate()


def get_reply_gate() -> ReplyGate:
    return _gate
