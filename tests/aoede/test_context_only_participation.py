# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""S2-04 context-first behaviour acceptance (2026-11-03 plan §8.2 rows 1-2).

Memory absence must never be a prerequisite for speaking: with an empty
memory store the opportunity pipeline still fires the context-only speak
path (materials come from the decision evidence, not from fabricated
memory), and with no opportunity the bot stays silent.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from aoede.budget import (
    AOEDE_BUDGET_RESERVATIONS_TABLE_DDL,
    AOEDE_PROACTIVE_BUDGET_TABLE_DDL,
)
from aoede.opportunity import OpportunityManager


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeHandle:
    def __init__(self, loop, entry) -> None:
        self._loop = loop
        self._entry = entry

    def cancel(self) -> None:
        with contextlib_suppress():
            self._loop.pending.remove(self._entry)


def contextlib_suppress():
    import contextlib

    return contextlib.suppress(ValueError)


class FakeLoop:
    def __init__(self) -> None:
        self.pending = []

    def call_later(self, delay, callback, *args):
        entry = (delay, callback, args)
        self.pending.append(entry)
        return FakeHandle(self, entry)

    def fire_all(self):
        pending, self.pending = self.pending, []
        for _delay, callback, args in pending:
            callback(*args)


def _install_host(tmp_path: Path, monkeypatch):
    """Minimal host with a spy speak path and an empty-memory store."""
    from aoede.host import ProactiveHost, install_host

    calls = []

    async def fake_speak(bot_ref, group_id, **kwargs):
        calls.append({"group_id": group_id, **kwargs})

    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY)")
    # budget: a full bucket so the context-only path is exercised (§6.5)
    from datetime import datetime, timezone

    from aoede.budget import (
        AOEDE_BUDGET_RESERVATIONS_TABLE_DDL,
        AOEDE_PROACTIVE_BUDGET_TABLE_DDL,
    )

    conn.execute(AOEDE_PROACTIVE_BUDGET_TABLE_DDL)
    conn.execute(AOEDE_BUDGET_RESERVATIONS_TABLE_DDL)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT OR REPLACE INTO aoede_proactive_budget (scope_key, tokens,"
        " last_refill_utc, config_frequency, updated_at_utc)"
        " VALUES (?, 1.0, ?, 1.0, ?)",
        ("||group:1", now_iso, now_iso),  # bot_ref=None in submit
    )
    conn.commit()
    conn.close()

    host = ProactiveHost(
        run_turn=lambda key, ctx: _noop_turn(),
        register_group_ref=lambda bot_id, group_id: SimpleNamespace(
            conversation_key=f"qq:{bot_id}:group:{group_id}",
            storage_session_id=-group_id,
            runtime_key=f"qq:{group_id}",
        ),
        proactive_speak_for_group=fake_speak,
        resolve_background_bot=lambda bot_ref: object(),
        db_path=lambda: str(db),
        get_proactive=lambda: SimpleNamespace(
            in_cooldown=lambda gid: False,
            recently_spoken=lambda gid, lines: False,
        ),
        get_participation_manager=lambda: SimpleNamespace(
            snapshot=lambda gid: {"groups": {}}
        ),
    )
    install_host(host)
    return calls, db


async def _noop_turn():
    return None


def _decision(mode="TOPIC_INTEREST"):
    return SimpleNamespace(mode=mode, should_speak=True, group_id=1,
                           breakdown=None, trigger_msg_id=42, topic_id="t1",
                           reason_flags=("interest_anchor",))


def test_opportunity_speak_invoked_without_memory_prerequisite(
    tmp_path, monkeypatch
) -> None:
    """无机会保持沉默；有机会时即记忆为空也走生成（context-only 合同）。"""
    loop = FakeLoop()

    async def _scenario():
        monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop, raising=False)
        monkeypatch.setattr(
            "aoede.opportunity.OpportunityManager._preflight_blocked_reason",
            lambda self, gid: "",
        )
        calls, _db = _install_host(tmp_path, monkeypatch)
        clock = _FakeClock()
        manager = OpportunityManager(clock=clock)

        manager._evidence_for = lambda host, opp: {
            "trigger_msg_id": 42,
            "recent_messages": [],
        }
        assert manager.submit(1, _decision(), trigger_text="大家好") == "created"
        clock.now += 3.0
        loop.fire_all()
        await asyncio.sleep(0.02)
        assert len(calls) == 1
        call = calls[0]
        # context-only contract: dice retired, evidence carries the decision
        assert call["skip_dice"] is True
        assert call["decision"].mode == "TOPIC_INTEREST"
        assert call["evidence"]["trigger_msg_id"] == 42
        # second opportunity: bucket drained (capacity 1, refill R/3600) →
        # budget keeps the bot silent even though an opportunity exists
        assert manager.submit(1, _decision(), trigger_text="x") == "created"
        clock.now += 1.0
        loop.fire_all()
        await asyncio.sleep(0.02)
        assert len(calls) == 1

    asyncio.run(_scenario())


def test_r0_budget_blocks_context_only_participation(tmp_path, monkeypatch) -> None:
    """R=0：机会在预算处被拒，不进入生成（§8.2 第 11 行的主动侧）。"""
    loop = FakeLoop()

    async def _scenario():
        monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop, raising=False)
        monkeypatch.setattr(
            "aoede.opportunity.OpportunityManager._preflight_blocked_reason",
            lambda self, gid: "",
        )
        import config

        monkeypatch.setattr(config, "PROACTIVE_FREQUENCY", 0.0, raising=False)
        calls, db = _install_host(tmp_path, monkeypatch)
        conn = sqlite3.connect(db)
        conn.execute(AOEDE_PROACTIVE_BUDGET_TABLE_DDL)
        conn.execute(AOEDE_BUDGET_RESERVATIONS_TABLE_DDL)
        conn.commit()
        conn.close()

        clock = _FakeClock()
        manager = OpportunityManager(clock=clock)
        assert manager.submit(1, _decision()) == "created"
        clock.now += 3.0
        loop.fire_all()
        await asyncio.sleep(0.02)
        assert calls == []

    asyncio.run(_scenario())
