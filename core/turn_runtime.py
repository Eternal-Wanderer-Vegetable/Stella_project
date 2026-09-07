# SPDX-License-Identifier: AGPL-3.0
"""轻量会话运行时：只维护插话门控需要的本地状态。"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class TurnState:
    state: str = "IDLE"
    last_started_at: float = 0.0
    last_finished_at: float = 0.0
    proactive_starts: int = 0


class TurnRuntime:
    """按群维护运行状态，不持有聊天内容，也不调用 LLM。"""

    def __init__(self) -> None:
        self._states: dict[int, TurnState] = {}

    def state_for(self, group_id: int) -> TurnState:
        state = self._states.setdefault(int(group_id), TurnState())
        return state

    def can_start_proactive(self, group_id: int, cooldown: float, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        state = self.state_for(group_id)
        if state.state == "RUNNING":
            return False
        if state.last_started_at and now - state.last_started_at < max(0.0, cooldown):
            return False
        return True

    def start(self, group_id: int, *, proactive: bool = False, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        state = self.state_for(group_id)
        state.state = "RUNNING"
        state.last_started_at = now
        if proactive:
            state.proactive_starts += 1

    def finish(self, group_id: int, *, waiting: bool = False, now: float | None = None) -> None:
        state = self.state_for(group_id)
        state.state = "WAITING" if waiting else "IDLE"
        state.last_finished_at = time.monotonic() if now is None else now


_runtime = TurnRuntime()


def get_turn_runtime() -> TurnRuntime:
    return _runtime
