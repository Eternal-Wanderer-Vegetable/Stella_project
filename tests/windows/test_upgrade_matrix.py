from __future__ import annotations

import hashlib
import os
import subprocess
import sys

import pytest

from deploy.upgrade import UpgradeError, active_pointer, transactional_upgrade

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native matrix")


def _tree(tmp_path, name, value):
    root = tmp_path / name
    root.mkdir()
    (root / "bot.py").write_text(value, encoding="utf-8")
    return root


def _digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(root).as_posix().encode()
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_idle_upgrade_and_retry_preserve_user_data(tmp_path):
    first = _tree(tmp_path, "first", "first")
    second = _tree(tmp_path, "second", "second")
    data = tmp_path / "data"
    user = data / "memory" / "user.db"
    user.parent.mkdir(parents=True)
    user.write_bytes(b"unchanged")
    transactional_upgrade(first, version="4.0.0", data_root=data, install_root=tmp_path / "install")
    before = user.read_bytes()
    with pytest.raises(UpgradeError):
        transactional_upgrade(
            second,
            version="4.0.1",
            data_root=data,
            install_root=tmp_path / "install",
            expected_checksum="0" * 64,
        )
    result = transactional_upgrade(
        second,
        version="4.0.1",
        data_root=data,
        install_root=tmp_path / "install",
        expected_checksum=_digest(second),
    )
    assert result.active_path.joinpath("bot.py").read_text() == "second"
    assert user.read_bytes() == before
    assert active_pointer(data).is_file()


def test_running_process_does_not_change_user_data_on_postflight_failure(tmp_path):
    source = _tree(tmp_path, "source", "new")
    data = tmp_path / "data"
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        before = b"user"
        user = data / "napcat" / "QQ" / "session"
        user.parent.mkdir(parents=True)
        user.write_bytes(before)
        with pytest.raises(UpgradeError):
            transactional_upgrade(
                source,
                version="4.0.1",
                data_root=data,
                install_root=tmp_path / "install",
                postflight=lambda _path: (_ for _ in ()).throw(RuntimeError("failed")),
            )
        assert user.read_bytes() == before
    finally:
        process.terminate()
        process.wait()
