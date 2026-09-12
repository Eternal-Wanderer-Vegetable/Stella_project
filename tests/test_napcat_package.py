from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from deploy import acquire, napcat


def _archive(tmp_path, name="napcat.zip", unsafe=False):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("../escape.txt" if unsafe else "NapCat/napcat.exe", b"binary")
    return path


def _manifest(archive):
    return {
        "id": "napcat",
        "version": "1.0.0",
        "digest": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "source": "https://example.invalid/napcat-1.0.0.zip",
        "license": "NapCat license notice",
        "sbom": "napcat-1.0.0.spdx.json",
        "platform": "windows-amd64",
    }


def test_install_is_pinned_and_keeps_qq_data(tmp_path):
    archive = _archive(tmp_path)
    data_root = tmp_path / "data"
    qq = data_root / "napcat" / "QQ"
    qq.mkdir(parents=True)
    (qq / "session.json").write_text("secret", encoding="utf-8")
    result = napcat.install_archive(archive, _manifest(archive), data_root)
    assert result["login"]["unattended"] is False
    assert napcat.status(data_root)["state"] == "not_logged_in"
    removed = napcat.uninstall(data_root)
    assert removed["qq_data_removed"] is False
    assert (qq / "session.json").read_text(encoding="utf-8") == "secret"


def test_digest_license_and_source_are_required(tmp_path):
    archive = _archive(tmp_path)
    manifest = _manifest(archive)
    manifest["license"] = ""
    with pytest.raises(napcat.NapCatError) as error:
        napcat.install_archive(archive, manifest, tmp_path / "data")
    assert error.value.code == "provenance_missing"


def test_archive_path_traversal_is_rejected(tmp_path):
    archive = _archive(tmp_path, unsafe=True)
    with pytest.raises(napcat.NapCatError) as error:
        napcat.install_archive(archive, _manifest(archive), tmp_path / "data")
    assert error.value.code == "unsafe_archive"


def test_windows_drive_path_is_rejected(tmp_path):
    archive = tmp_path / "drive.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("C:/escape.exe", b"unsafe")
    with pytest.raises(napcat.NapCatError) as error:
        napcat.install_archive(archive, _manifest(archive), tmp_path / "data")
    assert error.value.code == "unsafe_archive"


def test_status_is_an_enum_and_never_contains_login_secret(tmp_path):
    archive = _archive(tmp_path)
    napcat.install_archive(archive, _manifest(archive), tmp_path / "data")
    metadata = json.loads((tmp_path / "data" / ".stella" / "napcat.json").read_text())
    metadata["login"] = {"status": "connected", "token": "do-not-export"}
    (tmp_path / "data" / ".stella" / "napcat.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    result = napcat.status(tmp_path / "data")
    assert result["state"] == "connected"
    assert "token" not in result


def test_remote_napcat_acquisition_verifies_before_activation(monkeypatch, tmp_path):
    archive = _archive(tmp_path)
    manifest = _manifest(archive)
    monkeypatch.setattr(
        acquire.urllib.request,
        "urlopen",
        lambda url, timeout: archive.open("rb"),
    )
    result = acquire.install_napcat(manifest, tmp_path / "data")
    assert result["login"]["unattended"] is False
    assert napcat.status(tmp_path / "data")["state"] == "not_logged_in"


def test_remote_napcat_checksum_failure_does_not_activate(monkeypatch, tmp_path):
    archive = _archive(tmp_path)
    manifest = _manifest(archive)
    manifest["digest"] = "0" * 64
    monkeypatch.setattr(
        acquire.urllib.request,
        "urlopen",
        lambda url, timeout: archive.open("rb"),
    )
    with pytest.raises(acquire.AcquireError) as error:
        acquire.install_napcat(manifest, tmp_path / "data")
    assert error.value.code == "checksum_mismatch"
    assert not (tmp_path / "data" / ".stella" / "napcat.json").exists()


def test_pinned_msi_installs_without_attempting_login(monkeypatch, tmp_path):
    archive = _archive(tmp_path, name="napcat.msi")
    manifest = _manifest(archive)
    calls = []

    monkeypatch.setattr(napcat.os, "name", "nt")
    monkeypatch.setattr(
        napcat.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    result = napcat.install_msi(archive, manifest, tmp_path / "data")

    assert calls and calls[0][0][:3] == ["msiexec.exe", "/i", str(archive.resolve())]
    assert calls[0][0][3:] == ["/qn", "/norestart"]
    assert result["login"] == {"unattended": False, "status": "not_logged_in"}
