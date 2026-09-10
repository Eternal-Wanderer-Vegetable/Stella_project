from __future__ import annotations

import sqlite3

import pytest

from memory import addressing


def test_preferences_are_isolated_by_space_and_user(tmp_path):
    db = tmp_path / "addressing.db"

    addressing.set_preference("space_a", 1001, "哥哥", db_path=db)
    addressing.set_preference("space_b", 1001, "队长", db_path=db)
    addressing.set_preference("space_a", 1002, "老师", db_path=db)

    assert addressing.get_preference("space_a", 1001, db_path=db).address_term == "哥哥"
    assert addressing.get_preference("space_b", 1001, db_path=db).address_term == "队长"
    assert addressing.get_preference("space_a", 1002, db_path=db).address_term == "老师"
    assert addressing.get_preference("space_b", 1002, db_path=db) is None


def test_setting_overwrites_and_records_operator(tmp_path):
    db = tmp_path / "addressing.db"

    first = addressing.set_preference(
        "space_a", 1001, "哥哥", source="manual", updated_by_user_id=1001, db_path=db
    )
    second = addressing.set_preference(
        "space_a", 1001, "队长", source="admin", updated_by_user_id=9001, db_path=db
    )

    assert first.address_term == "哥哥"
    assert second.address_term == "队长"
    assert second.source == "admin"
    assert second.updated_by_user_id == "9001"
    assert second.updated_at


def test_clear_preference_is_idempotent(tmp_path):
    db = tmp_path / "addressing.db"
    addressing.set_preference("space_a", 1001, "哥哥", db_path=db)

    assert addressing.clear_preference("space_a", 1001, db_path=db) is True
    assert addressing.clear_preference("space_a", 1001, db_path=db) is False
    assert addressing.get_preference("space_a", 1001, db_path=db) is None


@pytest.mark.parametrize(
    "term",
    ["", "   ", "称呼\n注入", "```段落```", "【身份段】", "x" * 33],
)
def test_invalid_address_is_rejected_without_writing(tmp_path, term):
    db = tmp_path / "addressing.db"

    with pytest.raises(ValueError):
        addressing.set_preference("space_a", 1001, term, db_path=db)

    conn = sqlite3.connect(db)
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name = 'user_address_preferences'"
        ).fetchone()
        assert table is None
    finally:
        conn.close()
