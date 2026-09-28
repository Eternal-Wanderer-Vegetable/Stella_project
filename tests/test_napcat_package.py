from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from types import SimpleNamespace

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

    monkeypatch.setattr(napcat, "_IS_WINDOWS", True)
    monkeypatch.setattr(
        napcat.subprocess,
        "run",
        lambda command, **kwargs: (
            calls.append((command, kwargs)) or SimpleNamespace(returncode=0)
        ),
    )

    result = napcat.install_msi(archive, manifest, tmp_path / "data")

    assert calls and calls[0][0][:3] == ["msiexec.exe", "/i", str(archive.resolve())]
    assert calls[0][0][3:5] == ["/passive", "/norestart"]
    assert calls[0][0][5] == "/L*v"
    assert calls[0][0][6].endswith("napcat-msi-install.log")
    assert result["login"] == {"unattended": False, "status": "not_logged_in"}
    assert result["reboot_required"] is False


def test_msi_exit_code_policy_matrix(monkeypatch, tmp_path):
    """0/1602/1603/1618/1641/3010 各有具名语义：成功/取消/忙/待重启/具名失败。"""
    archive = _archive(tmp_path, name="napcat.msi")
    manifest = _manifest(archive)
    monkeypatch.setattr(napcat, "_IS_WINDOWS", True)
    monkeypatch.setattr(napcat.time, "sleep", lambda _s: None)
    data_root = tmp_path / "data"
    metadata_path = data_root / ".stella" / "napcat.json"

    # 3010/1641：成功 + reboot_required 持久化
    def make_runner(returncode):
        def run(command, **kwargs):
            return SimpleNamespace(returncode=returncode)
        return run

    for code in (3010, 1641):
        shutil.rmtree(data_root, ignore_errors=True)
        monkeypatch.setattr(napcat.subprocess, "run", make_runner(code))
        result = napcat.install_msi(archive, manifest, data_root)
        assert result["reboot_required"] is True, f"退出码 {code} 必须记录待重启"
        stored = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert stored["reboot_required"] is True

    # 1602 用户取消：具名失败，且绝不写 metadata（无假成功）
    shutil.rmtree(data_root, ignore_errors=True)
    monkeypatch.setattr(
        napcat.subprocess, "run",
        lambda command, **kwargs: SimpleNamespace(returncode=1602),
    )
    with pytest.raises(napcat.NapCatError) as error:
        napcat.install_msi(archive, manifest, data_root)
    assert error.value.code == "msi_cancelled"
    assert not metadata_path.exists()

    # 1603：保留日志的具名失败；silent 模式**不自动弹完整 UI**（无第二次调用）
    shutil.rmtree(data_root, ignore_errors=True)
    calls: list[tuple] = []

    def record_call(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1603)

    monkeypatch.setattr(napcat.subprocess, "run", record_call)
    with pytest.raises(napcat.NapCatError) as error:
        napcat.install_msi(archive, manifest, data_root)
    assert error.value.code == "msi_install_failed"
    assert "日志" in error.value.message
    assert len(calls) == 1, "1603 不得自动以完整 UI 重试（F10）"

    # 1603 + 显式 allow_interactive_retry：才允许交互重试（首次 1603 → UI 重试 0）
    calls.clear()
    retry_codes = iter([1603, 0])

    def retry_runner(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=next(retry_codes))

    monkeypatch.setattr(napcat.subprocess, "run", retry_runner)
    result = napcat.install_msi(
        archive, manifest, data_root, allow_interactive_retry=True
    )
    assert len(calls) == 2
    assert calls[1][3] == "/norestart"
    assert result["reboot_required"] is False


def test_msi_busy_backs_off_with_bound_then_succeeds(monkeypatch, tmp_path):
    """1618：有界退避重试，服务空闲后成功。"""
    archive = _archive(tmp_path, name="napcat.msi")
    manifest = _manifest(archive)
    monkeypatch.setattr(napcat, "_IS_WINDOWS", True)
    sleeps: list[float] = []
    monkeypatch.setattr(napcat.time, "sleep", lambda s: sleeps.append(s))
    codes = iter([1618, 1618, 0])
    monkeypatch.setattr(
        napcat.subprocess, "run",
        lambda command, **kwargs: SimpleNamespace(returncode=next(codes)),
    )
    result = napcat.install_msi(archive, manifest, tmp_path / "data")
    assert result["reboot_required"] is False
    assert sleeps == [napcat.MSI_BUSY_BACKOFF_SECONDS] * 2


def test_msi_busy_exhaustion_is_named_failure(monkeypatch, tmp_path):
    """1618 退避耗尽：msi_busy 具名失败，不无限等待、不写 metadata。"""
    archive = _archive(tmp_path, name="napcat.msi")
    manifest = _manifest(archive)
    monkeypatch.setattr(napcat, "_IS_WINDOWS", True)
    monkeypatch.setattr(napcat.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        napcat.subprocess, "run",
        lambda command, **kwargs: SimpleNamespace(returncode=1618),
    )
    with pytest.raises(napcat.NapCatError) as error:
        napcat.install_msi(archive, manifest, tmp_path / "data")
    assert error.value.code == "msi_busy"
    assert not (tmp_path / "data" / ".stella" / "napcat.json").exists()


def test_msi_timeout_does_not_fake_success(monkeypatch, tmp_path):
    """超时：msi_timeout 具名失败并提示确认 msiexec 状态，不写 metadata。"""
    archive = _archive(tmp_path, name="napcat.msi")
    manifest = _manifest(archive)
    monkeypatch.setattr(napcat, "_IS_WINDOWS", True)

    def timeout_run(command, **kwargs):
        raise subprocess.TimeoutExpired(cmd=command, timeout=1)

    monkeypatch.setattr(napcat.subprocess, "run", timeout_run)
    with pytest.raises(napcat.NapCatError) as error:
        napcat.install_msi(archive, manifest, tmp_path / "data")
    assert error.value.code == "msi_timeout"
    assert not (tmp_path / "data" / ".stella" / "napcat.json").exists()


def test_msi_failure_reports_exit_code_and_log(monkeypatch, tmp_path):
    archive = _archive(tmp_path, name="napcat.msi")
    manifest = _manifest(archive)

    monkeypatch.setattr(napcat, "_IS_WINDOWS", True)
    monkeypatch.setattr(
        napcat.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1603),
    )

    with pytest.raises(napcat.NapCatError, match="退出码 1603"):
        napcat.install_msi(archive, manifest, tmp_path / "data")
