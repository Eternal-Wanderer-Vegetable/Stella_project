from __future__ import annotations

from scripts.build_llama_package import build
from scripts.verify_llama_package import verify


def test_build_finds_multiconfig_windows_server_output(tmp_path, monkeypatch):
    source = tmp_path / "llama"
    source.mkdir()
    (source / "CMakeLists.txt").write_text("project(llama)", encoding="utf-8")
    (source / "LICENSE").write_text("license", encoding="utf-8")
    output = tmp_path / "dist" / "package"
    build_dir = output.parent / ".llama-build-cpu"
    executable = build_dir / "bin" / "Release" / "llama-server.exe"

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
    )

    assert result == output
    assert (output / "llama-server.exe").read_bytes() == b"server"
    assert verify(output) == []
