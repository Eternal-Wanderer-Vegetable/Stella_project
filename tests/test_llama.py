# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors

from __future__ import annotations

from pathlib import Path

from deploy import llama, runtime


def _embedding_manifest(monkeypatch, tmp_path: Path) -> Path:
    runtime_dir = tmp_path / "runtime"
    model_path = tmp_path / "embedding.gguf"
    model_path.write_bytes(b"model")
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(runtime, "INSTANCE_ID", "llama-test")
    payload = runtime.default_manifest()
    config = payload["components"]["llama"]["config"]
    payload["components"]["llama"]["enabled"] = True
    config["embedding_model"] = {
        "path": str(model_path),
        "package": "qwen3-embedding-0.6b@q8_0",
        "id": "qwen3-embedding-0.6b",
        "checksum": "a" * 64,
    }
    runtime.write_manifest(payload)
    return model_path


def test_existing_local_embedding_endpoint_is_reused(monkeypatch, tmp_path):
    _embedding_manifest(monkeypatch, tmp_path)
    ready = iter((False, True))
    monkeypatch.setattr(llama, "_endpoint_ready", lambda _url: next(ready))
    monkeypatch.setattr(
        llama,
        "_launch_local",
        lambda _endpoint: (_ for _ in ()).throw(
            AssertionError("ready local service must not be relaunched")
        ),
    )

    result = llama.ensure_local_embedding_service(preferred_url="http://lm:1234")

    assert result["ok"] is True
    assert result["source"] == "local"
    assert result["endpoint"] == "http://127.0.0.1:8081"


def test_unavailable_primary_starts_bundled_llama_server(monkeypatch, tmp_path):
    model_path = _embedding_manifest(monkeypatch, tmp_path)
    executable = tmp_path / "llama-server.exe"
    executable.write_bytes(b"server")
    commands = []

    class _Process:
        pid = 1234

    ready = iter((False, False, True))
    monkeypatch.setattr(llama, "_endpoint_ready", lambda _url: next(ready))
    monkeypatch.setattr(llama, "_server_path", lambda: executable)
    monkeypatch.setattr(llama, "_pid_alive", lambda _pid: True)

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return _Process()

    monkeypatch.setattr(llama.subprocess, "Popen", fake_popen)

    result = llama.ensure_local_embedding_service(preferred_url="http://lm:1234")

    assert result["ok"] is True
    assert result["source"] == "local"
    assert result["model"] == "qwen3-embedding-0.6b"
    assert commands == [
        [
            str(executable),
            "--model",
            str(model_path),
            "--host",
            "127.0.0.1",
            "--port",
            "8081",
            "--embedding",
            "--pooling",
            "mean",
            "--ctx-size",
            "4096",
            "--alias",
            "qwen3-embedding-0.6b",
        ]
    ]
    assert runtime.read_state()["components"]["llama"]["state"] == "healthy"


def test_missing_server_is_reported_without_starting(monkeypatch, tmp_path):
    _embedding_manifest(monkeypatch, tmp_path)
    monkeypatch.setattr(llama, "_endpoint_ready", lambda _url: False)
    monkeypatch.setattr(llama, "_server_path", lambda: None)

    result = llama.ensure_local_embedding_service(preferred_url="http://lm:1234")

    assert result == {"ok": False, "message": "未找到已安装的 llama-server。"}
