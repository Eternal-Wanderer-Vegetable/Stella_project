from __future__ import annotations

import json

import pytest

from deploy.upgrade import (
    UpgradeError,
    UpgradeLock,
    active_pointer,
    transactional_upgrade,
)


def _source(tmp_path, name: str, value: str):
    root = tmp_path / name
    root.mkdir()
    (root / "bot.py").write_text(value, encoding="utf-8")
    return root


def test_upgrade_stages_and_activates_without_touching_data(tmp_path):
    source = _source(tmp_path, "source", "new")
    data = tmp_path / "data"
    user_file = data / "memory" / "agent_memory.db"
    user_file.parent.mkdir(parents=True)
    user_file.write_bytes(b"user-data")

    result = transactional_upgrade(
        source,
        version="4.0.1",
        data_root=data,
        install_root=tmp_path / "install",
    )

    assert result.active_path.joinpath("bot.py").read_text(encoding="utf-8") == "new"
    assert user_file.read_bytes() == b"user-data"
    pointer = json.loads(active_pointer(data).read_text(encoding="utf-8"))
    assert pointer["version"] == "4.0.1"


def test_upgrade_postflight_failure_preserves_previous_active_pointer(tmp_path):
    first = _source(tmp_path, "first", "first")
    second = _source(tmp_path, "second", "second")
    data = tmp_path / "data"
    install = tmp_path / "install"
    transactional_upgrade(first, version="4.0.0", data_root=data, install_root=install)
    before = active_pointer(data).read_text(encoding="utf-8")

    with pytest.raises(UpgradeError, match="bad postflight"):
        transactional_upgrade(
            second,
            version="4.0.1",
            data_root=data,
            install_root=install,
            postflight=lambda _path: (_ for _ in ()).throw(RuntimeError("bad postflight")),
        )

    assert active_pointer(data).read_text(encoding="utf-8") == before
    assert not any((data / ".stella" / "upgrade-staging").iterdir())


def test_upgrade_lock_rejects_concurrent_operation(tmp_path):
    first = UpgradeLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(UpgradeError) as error:
            UpgradeLock(tmp_path).acquire()
        assert error.value.code == "upgrade_in_progress"
    finally:
        first.release()


def test_upgrade_checksum_failure_keeps_active_pointer(tmp_path):
    source = _source(tmp_path, "source", "new")
    data = tmp_path / "data"
    with pytest.raises(UpgradeError, match="checksum"):
        transactional_upgrade(
            source,
            version="4.0.1",
            data_root=data,
            install_root=tmp_path / "install",
            expected_checksum="0" * 64,
        )
    assert active_pointer(data).exists() is False
