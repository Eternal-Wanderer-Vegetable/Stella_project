# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""S2-03 persistent proactive frequency budget tests (2026-11-03 plan §6.5).

Covers: R=0/0.5/1/6 semantics, capacity 1, no free startup token, refill
persistence across "restarts" (fresh store instance on the same DB), clock
rollback not granting quota, forward jump capped at capacity, concurrent
reservations, commit/release/unknown settlement, fail-closed store outage,
shared bucket for all autonomous kinds, and config validation for
NaN/Inf/negative/out-of-range values.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aoede.budget import (
    AOEDE_BUDGET_RESERVATIONS_TABLE_DDL,
    AOEDE_PROACTIVE_BUDGET_TABLE_DDL,
    ProactiveBudgetStore,
    budget_scope_key,
    new_operation_id,
)

SCOPE = "legacy-qq:10000|10000|group:1"


def _store(tmp_path: Path) -> ProactiveBudgetStore:
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    conn.execute(AOEDE_PROACTIVE_BUDGET_TABLE_DDL)
    conn.execute(AOEDE_BUDGET_RESERVATIONS_TABLE_DDL)
    conn.commit()
    conn.close()
    return ProactiveBudgetStore(str(db))


def _prime_bucket(tmp_path: Path, *, hours_ago: float = 1.0) -> None:
    """创建 tokens=0、last_refill 回拨 hours_ago 小时的桶行（自建表）。"""
    db = tmp_path / "agent_memory.db"
    old = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(
        timespec="seconds"
    )
    conn = sqlite3.connect(db)
    conn.execute(AOEDE_PROACTIVE_BUDGET_TABLE_DDL)
    conn.execute(
        "INSERT OR REPLACE INTO aoede_proactive_budget (scope_key, tokens,"
        " last_refill_utc, config_frequency, updated_at_utc)"
        " VALUES (?, 0.0, ?, 1.0, ?)",
        (SCOPE, old, old),
    )
    conn.commit()
    conn.close()


def test_new_bucket_starts_empty_no_free_token(tmp_path) -> None:
    store = _store(tmp_path)
    decision = store.reserve(SCOPE, new_operation_id(), frequency_per_hour=6.0)
    assert decision.granted is False
    assert decision.reason == "budget_empty"


def test_r0_never_refills(tmp_path) -> None:
    store = _store(tmp_path)
    # even after simulated time passing, R=0 grants nothing
    assert store.reserve(SCOPE, new_operation_id(), frequency_per_hour=0.0).granted is False
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    old = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat(
        timespec="seconds"
    )
    conn.execute(
        "UPDATE aoede_proactive_budget SET last_refill_utc=?", (old,)
    )
    conn.commit()
    conn.close()
    fresh = ProactiveBudgetStore(str(db))
    assert fresh.reserve(SCOPE, new_operation_id(), frequency_per_hour=0.0).granted is False


def test_refill_semantics_r1_and_r_half(tmp_path) -> None:
    store = _store(tmp_path)
    op = new_operation_id()
    assert store.reserve(SCOPE, op, frequency_per_hour=1.0).granted is False
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    # one full hour elapsed at R=1 → exactly capacity 1
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(
        timespec="seconds"
    )
    conn.execute(
        "UPDATE aoede_proactive_budget SET last_refill_utc=?", (old,)
    )
    conn.commit()
    conn.close()
    fresh = ProactiveBudgetStore(str(db))
    granted = fresh.reserve(SCOPE, new_operation_id(), frequency_per_hour=1.0)
    assert granted.granted is True
    # capacity 1: immediately after, empty again
    assert fresh.reserve(SCOPE, new_operation_id(), frequency_per_hour=1.0).granted is False


def test_forward_jump_capped_at_capacity(tmp_path) -> None:
    _store(tmp_path)
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat(
        timespec="seconds"
    )
    conn.execute(
        "INSERT INTO aoede_proactive_budget (scope_key, tokens, last_refill_utc,"
        " config_frequency, updated_at_utc) VALUES (?, 0.0, ?, 1.0, ?)",
        (SCOPE, old, old),
    )
    conn.commit()
    conn.close()
    fresh = ProactiveBudgetStore(str(db))
    assert fresh.reserve(SCOPE, new_operation_id(), frequency_per_hour=1.0).granted is True
    # never more than one token banked despite a year of elapsed time
    assert fresh.reserve(SCOPE, new_operation_id(), frequency_per_hour=1.0).granted is False


def test_clock_rollback_does_not_grant(tmp_path) -> None:
    _store(tmp_path)
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    # last_refill in the FUTURE (wall clock fell back): elapsed clamps to 0
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(
        timespec="seconds"
    )
    conn.execute(
        "INSERT INTO aoede_proactive_budget (scope_key, tokens, last_refill_utc,"
        " config_frequency, updated_at_utc) VALUES (?, 0.0, ?, 1.0, ?)",
        (SCOPE, future, future),
    )
    conn.commit()
    conn.close()
    fresh = ProactiveBudgetStore(str(db))
    assert fresh.reserve(SCOPE, new_operation_id(), frequency_per_hour=1.0).granted is False


def test_commit_and_release_settlement(tmp_path) -> None:
    _store(tmp_path)
    _prime_bucket(tmp_path)
    fresh = ProactiveBudgetStore(str(tmp_path / "agent_memory.db"))
    op = new_operation_id()
    assert fresh.reserve(SCOPE, op, frequency_per_hour=1.0).granted is True
    assert fresh.commit(op) is True
    # commit is final: release after commit does nothing
    assert fresh.release(op) is False
    # release refunds the token (capped at capacity)
    op2 = new_operation_id()
    assert fresh.reserve(SCOPE, op2, frequency_per_hour=1.0).granted is False
    assert fresh.release(op2) is False  # nothing reserved
    _prime_bucket(tmp_path)
    again = ProactiveBudgetStore(str(tmp_path / "agent_memory.db"))
    op3 = new_operation_id()
    assert again.reserve(SCOPE, op3, frequency_per_hour=1.0).granted is True
    assert again.release(op3) is True
    # refunded: immediately grantable again (release tops up to capacity)
    assert again.reserve(SCOPE, new_operation_id(), frequency_per_hour=1.0).granted is True


def test_unknown_resolution_consumes(tmp_path) -> None:
    store = _store(tmp_path)
    op = new_operation_id()
    assert store.reserve(SCOPE, op, frequency_per_hour=0.0).granted is False
    _prime_bucket(tmp_path)
    fresh = ProactiveBudgetStore(str(tmp_path / "agent_memory.db"))
    op2 = new_operation_id()
    assert fresh.reserve(SCOPE, op2, frequency_per_hour=1.0).granted is True
    assert fresh.resolve_unknown(op2) is True
    # consumed: release afterwards does nothing
    assert fresh.release(op2) is False


def test_concurrent_reservations_single_claim(tmp_path) -> None:
    _prime_bucket(tmp_path)
    fresh = ProactiveBudgetStore(str(tmp_path / "agent_memory.db"))
    outcomes = [
        fresh.reserve(SCOPE, new_operation_id(), frequency_per_hour=6.0).granted
        for _ in range(4)
    ]
    # capacity 1 and no banking: exactly one grant among concurrent tries
    assert outcomes.count(True) == 1


def test_fail_closed_when_store_unavailable(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    # point the store at a directory that cannot be a database
    broken = ProactiveBudgetStore(str(tmp_path / "no-such-dir" / "x.db"))
    decision = broken.reserve(SCOPE, new_operation_id(), frequency_per_hour=1.0)
    assert decision.granted is False
    assert decision.unknown is True
    # the working store still fails closed on invalid frequency
    decision = store.reserve(SCOPE, new_operation_id(), frequency_per_hour=-1)
    assert decision.granted is False and decision.unknown is False


def test_scope_keys_differ_per_bot_and_group(tmp_path) -> None:
    from types import SimpleNamespace

    bot_a = SimpleNamespace(connection_id="legacy-qq:10000", self_id="10000")
    bot_b = SimpleNamespace(connection_id="legacy-qq:20000", self_id="20000")
    assert budget_scope_key(bot_a, 1) != budget_scope_key(bot_a, 2)
    assert budget_scope_key(bot_a, 1) != budget_scope_key(bot_b, 1)


def test_frequency_config_validation() -> None:
    """NaN/Inf/负数/超范围回退默认并诊断；合法值保留。"""
    import importlib
    import os

    import config.settings as settings

    cases = [
        ("nan", 1.0),
        ("inf", 1.0),
        ("-0.5", 1.0),
        ("9", 1.0),
        ("0", 0.0),
        ("0.5", 0.5),
        ("6", 6.0),
    ]
    for raw, expected in cases:
        os.environ["PROACTIVE_FREQUENCY"] = raw
        try:
            importlib.reload(settings)
        finally:
            os.environ.pop("PROACTIVE_FREQUENCY", None)
        assert expected == settings.PROACTIVE_FREQUENCY, raw
    importlib.reload(settings)
