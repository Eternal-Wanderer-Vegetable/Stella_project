"""Verify zero-checkpoint retention with a synthetic SQLite database only."""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from loguru import logger

logger.remove()
from memory import db_cleaner

with tempfile.TemporaryDirectory(prefix="stella-gravitas-cleanup-") as d:
    p = Path(d) / "synthetic.db"
    c = sqlite3.connect(p)
    c.executescript(
        "CREATE TABLE group_messages(id INTEGER PRIMARY KEY,group_id TEXT);CREATE TABLE consolidation_state(group_id TEXT PRIMARY KEY,last_processed_id INTEGER,updated_at TEXT);"
    )
    c.executemany(
        "INSERT INTO group_messages VALUES (?,?)", [(i, "fixture") for i in range(1, 6)]
    )
    c.execute("INSERT INTO consolidation_state VALUES (?,0,NULL)", ("fixture",))
    c.commit()
    c.close()
    db_cleaner.DB_PATH = p
    db_cleaner.MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED = True
    db_cleaner._mark_cleanup_done = lambda: None
    result = db_cleaner.trim_group_messages(keep_count=2)
    c = sqlite3.connect(p)
    remaining = c.execute("SELECT id FROM group_messages ORDER BY id").fetchall()
    c.close()
    print(
        json.dumps(
            {
                "synthetic_rows_before": 5,
                "checkpoint_before": 0,
                "protect_unconsolidated": True,
                "keep_count": 2,
                "result": result,
                "remaining_ids": [r[0] for r in remaining],
            },
            indent=2,
        )
    )
    assert result["deleted"] > 0, "baseline changed: re-evaluate prerequisite"
