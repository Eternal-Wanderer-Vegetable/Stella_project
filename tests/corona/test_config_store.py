# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Isolated revision commit, CAS, secret and crash-recovery contracts."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from corona.config_store import ConfigStore, ConfigStoreError
from stella_bootstrap.config import build_config_revision

ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "cn05-config-test"


def _new_store(tmp_path: Path, *, fault_hook=None):
    home = tmp_path / "stella-home"
    home.mkdir(parents=True)
    (home / ".env").write_text(
        "WEBUI_ENABLED=true\nHOST=127.0.0.1\nPORT=18765\n",
        encoding="utf-8",
    )
    external = {"DB_PATH": str(tmp_path / "isolated.db")}
    initial = build_config_revision(
        project_root=ROOT,
        stella_home=home,
        external_environment=external,
    )
    store = ConfigStore(
        stella_home=home,
        instance_id=INSTANCE,
        project_root=ROOT,
        external_environment=external,
        fault_hook=fault_hook,
    )
    store.initialize(initial)
    return store, initial, home, external


def test_config_save_uses_cas_and_idempotency_and_redacts_secrets(
    tmp_path: Path,
) -> None:
    store, initial, home, _external = _new_store(tmp_path)
    values = {
        "MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 3,
        "LLM_ENDPOINT_CHAT_API_KEY": "cn05-secret-value",
    }
    first = store.save(
        values,
        expected_revision=initial.revision_id,
        idempotency_key="save-1",
        actor={"username": "admin", "via": "jwt"},
    )
    repeated = store.save(
        values,
        expected_revision=initial.revision_id,
        idempotency_key="save-1",
    )

    assert repeated == first
    assert first["changed_keys"] == [
        "LLM_ENDPOINT_CHAT_API_KEY",
        "MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE",
    ]
    with pytest.raises(ConfigStoreError, match="revision_conflict"):
        store.save(
            {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 4},
            expected_revision=initial.revision_id,
            idempotency_key="save-2",
        )
    with pytest.raises(ConfigStoreError, match="idempotency_conflict"):
        store.save(
            {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 4},
            expected_revision=None,
            idempotency_key="save-1",
        )

    public = store.public_config()
    api_key = next(
        field
        for field in public["fields"]
        if field["key"] == "LLM_ENDPOINT_CHAT_API_KEY"
    )
    assert api_key["current_value"] is None
    assert api_key["has_value"] is True
    assert "cn05-secret-value" not in str(public)
    assert (home / ".env").read_text(encoding="utf-8").count(
        "LLM_ENDPOINT_CHAT_API_KEY="
    ) == 1
    if os.name != "nt":
        assert stat.S_IMODE((home / ".env").stat().st_mode) == 0o600
        assert stat.S_IMODE(store.database_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(store.database_path.parent.stat().st_mode) == 0o700


def test_empty_inherited_value_deletes_and_external_edits_are_not_overwritten(
    tmp_path: Path,
) -> None:
    store, initial, home, _external = _new_store(tmp_path)
    saved = store.save(
        {"ADDRESSING_INTENT_TIMEOUT": "8.5"},
        expected_revision=initial.revision_id,
        idempotency_key="inherit-save",
    )
    removed = store.save(
        {"ADDRESSING_INTENT_TIMEOUT": ""},
        expected_revision=saved["revision_id"],
        idempotency_key="inherit-delete",
    )
    text = (home / ".env").read_text(encoding="utf-8")
    assert "ADDRESSING_INTENT_TIMEOUT=" not in text
    deleted_revision, _ = store.get_revision(removed["revision_id"])
    assert "ADDRESSING_INTENT_TIMEOUT" not in deleted_revision.values

    with (home / ".env").open("a", encoding="utf-8") as stream:
        stream.write("MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE=7\n")
    external_bytes = (home / ".env").read_bytes()
    with pytest.raises(ConfigStoreError, match="external_edit_conflict"):
        store.save(
            {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 8},
            expected_revision=removed["revision_id"],
            idempotency_key="external-edit",
        )
    assert (home / ".env").read_bytes() == external_bytes
    assert store.state().desired_revision != removed["revision_id"]


def test_new_active_profile_overlay_is_treated_as_an_external_edit(
    tmp_path: Path,
) -> None:
    home = tmp_path / "profile-home"
    home.mkdir()
    (home / ".env").write_text(
        "ENVIRONMENT=dev\nWEBUI_ENABLED=true\nHOST=127.0.0.1\nPORT=18765\n",
        encoding="utf-8",
    )
    external = {"DB_PATH": str(tmp_path / "profile.db")}
    initial = build_config_revision(
        project_root=ROOT,
        stella_home=home,
        external_environment=external,
    )
    store = ConfigStore(
        stella_home=home,
        instance_id=INSTANCE,
        project_root=ROOT,
        external_environment=external,
    )
    store.initialize(initial)
    (home / ".env.dev").write_text(
        "MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE=2\n", encoding="utf-8"
    )

    with pytest.raises(ConfigStoreError, match="external_edit_conflict"):
        store.save(
            {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 3},
            expected_revision=initial.revision_id,
            idempotency_key="profile-external-edit",
        )

    assert (
        store.current_revision("desired")[0].values[
            "MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE"
        ]
        == "2"
    )


@pytest.mark.parametrize(
    ("boundary", "expected_value", "expected_tx_state"),
    [
        ("transaction_prepared", None, "ABORTED"),
        ("env_replaced", "3", "COMMITTED"),
    ],
)
def test_prepared_transaction_recovers_from_before_or_after_digest(
    tmp_path: Path,
    boundary: str,
    expected_value: str | None,
    expected_tx_state: str,
) -> None:
    def fault(point: str) -> None:
        if point == boundary:
            raise RuntimeError("simulated process interruption")

    store, initial, home, external = _new_store(tmp_path, fault_hook=fault)
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        store.save(
            {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 3},
            expected_revision=initial.revision_id,
            idempotency_key="faulted-save",
        )

    recovering = ConfigStore(
        stella_home=home,
        instance_id=INSTANCE,
        project_root=ROOT,
        external_environment=external,
    )
    recovering.initialize(initial)
    actual = recovering.current_revision("desired")[0].values.get(
        "MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE"
    )
    assert actual == expected_value
    tx = recovering._one(
        "SELECT state FROM config_transactions WHERE state != 'ROLLED_BACK'"
    )
    assert tx[0] == expected_tx_state


@pytest.mark.parametrize(
    ("boundary", "expected_value", "expected_tx_state"),
    [
        ("transaction_prepared", None, "ABORTED"),
        ("env_replaced", "3", "COMMITTED"),
    ],
)
def test_os_process_exit_at_commit_boundary_recovers_without_replay(
    tmp_path: Path,
    boundary: str,
    expected_value: str | None,
    expected_tx_state: str,
) -> None:
    store, initial, home, external = _new_store(tmp_path)
    initial_path = store.get_revision(initial.revision_id)[1]
    child = r"""
import os
import sys
from pathlib import Path
from corona.config_store import ConfigStore
from stella_bootstrap.config import load_revision

home, instance, project, revision_path, db_path, boundary = sys.argv[1:]
def stop_at(point):
    if point == boundary:
        os._exit(77)
store = ConfigStore(
    stella_home=Path(home),
    instance_id=instance,
    project_root=Path(project),
    external_environment={"DB_PATH": db_path},
    fault_hook=stop_at,
)
initial = load_revision(Path(revision_path))
store.initialize(initial)
store.save(
    {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 3},
    expected_revision=initial.revision_id,
    idempotency_key="killed-process-save",
)
raise SystemExit(90)
"""
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT),
    }
    child_result = subprocess.run(
        [
            sys.executable,
            "-c",
            child,
            str(home),
            INSTANCE,
            str(ROOT),
            str(initial_path),
            external["DB_PATH"],
            boundary,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert child_result.returncode == 77, child_result.stderr

    recovering = ConfigStore(
        stella_home=home,
        instance_id=INSTANCE,
        project_root=ROOT,
        external_environment=external,
    )
    recovering.initialize(initial)
    actual = recovering.current_revision("desired")[0].values.get(
        "MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE"
    )
    assert actual == expected_value
    tx = recovering._one(
        "SELECT state FROM config_transactions WHERE state NOT IN ('ROLLED_BACK')"
    )
    assert tx[0] == expected_tx_state


def test_previous_environment_restore_is_conditional_and_journaled(
    tmp_path: Path,
) -> None:
    store, initial, home, _external = _new_store(tmp_path)
    before = (home / ".env").read_bytes()
    saved = store.save(
        {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 3},
        expected_revision=initial.revision_id,
        idempotency_key="rollback-save",
    )
    transaction_id = store.transaction_for_revision(saved["revision_id"])
    assert transaction_id is not None

    result = store.restore_transaction_if_unchanged(transaction_id)
    assert result["restored"] is True
    assert (home / ".env").read_bytes() == before
    assert store.state().desired_revision == initial.revision_id
    assert store.transaction_for_revision(saved["revision_id"]) is None
    row = store._one(
        "SELECT purpose,state FROM config_transactions WHERE transaction_id != ? ORDER BY created_at DESC LIMIT 1",
        (transaction_id,),
    )
    assert tuple(row) == ("rollback", "COMMITTED")


def test_previous_environment_restore_never_overwrites_a_later_edit(
    tmp_path: Path,
) -> None:
    store, initial, home, _external = _new_store(tmp_path)
    saved = store.save(
        {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 3},
        expected_revision=initial.revision_id,
        idempotency_key="rollback-conflict-save",
    )
    transaction_id = store.transaction_for_revision(saved["revision_id"])
    assert transaction_id is not None
    with (home / ".env").open("a", encoding="utf-8") as stream:
        stream.write("CUSTOM_USER_VALUE=keep-me\n")
    external_bytes = (home / ".env").read_bytes()

    result = store.restore_transaction_if_unchanged(transaction_id)

    assert result == {
        "restored": False,
        "reason": "external_env_edit",
        "desired_revision": saved["revision_id"],
    }
    assert (home / ".env").read_bytes() == external_bytes
