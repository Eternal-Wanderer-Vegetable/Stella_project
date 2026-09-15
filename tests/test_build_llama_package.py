from __future__ import annotations

import pytest

from scripts.build_llama_package import build
from scripts.verify_llama_package import verify


def test_build_finds_multiconfig_windows_server_output(tmp_path, monkeypatch):
    source = tmp_path / "llama"
    source.mkdir()
    (source / "CMakeLists.txt").write_text("project(llama)", encoding="utf-8")
    (source / "LICENSE").write_text("license", encoding="utf-8")
    output = tmp_path / "dist" / "package"
    build_dir = output.parent / ".llama-build-cpu"
    executable = build_dir / "bin" / "Release" / "x64" / "llama-server.exe"
    runtime_dir = tmp_path / "openssl" / "bin"
    runtime_dir.mkdir(parents=True)
    for name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll"):
        (runtime_dir / name).write_bytes(name.encode())

    def fake_run(command, *, check):
        assert check is True
        if "--build" in command:
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"server")

    monkeypatch.setattr("scripts.build_llama_package.subprocess.run", fake_run)

    result = build(
        source,
        output,
        backend="cpu",
        commit="test-commit",
        os_name="windows",
        arch="windows-amd64",
        runtime_dirs=[runtime_dir],
    )

    assert result == output
    assert (output / "llama-server.exe").read_bytes() == b"server"
    assert (output / "libcrypto-3-x64.dll").read_bytes() == b"libcrypto-3-x64.dll"
    assert (output / "libssl-3-x64.dll").read_bytes() == b"libssl-3-x64.dll"
    assert verify(output) == []


def test_build_rejects_windows_package_without_openssl_runtime(tmp_path, monkeypatch):
    source = tmp_path / "llama"
    source.mkdir()
    (source / "CMakeLists.txt").write_text("project(llama)", encoding="utf-8")
    (source / "LICENSE").write_text("license", encoding="utf-8")
    output = tmp_path / "dist" / "package"
    executable = output.parent / ".llama-build-cpu" / "llama-server.exe"

    def fake_run(command, *, check):
        if "--build" in command:
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"server")

    monkeypatch.setattr("scripts.build_llama_package.subprocess.run", fake_run)
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    for variable in (
        "OPENSSL_BIN_DIR",
        "OPENSSL_ROOT_DIR",
        "OPENSSL_DIR",
        "VCPKG_INSTALLATION_ROOT",
    ):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(
        FileNotFoundError,
        match=r"libcrypto-3-x64\.dll/libcrypto-3\.dll",
    ):
        build(
            source,
            output,
            backend="cpu",
            commit="test-commit",
            os_name="windows-latest",
            arch="windows-amd64",
        )
