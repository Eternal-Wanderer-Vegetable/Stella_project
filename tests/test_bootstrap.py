from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from deploy import bootstrap, napcat, packages


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _archive(path: Path, member: str, content: bytes) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(member, content)
    return path


def _catalog(tmp_path: Path) -> tuple[Path, dict[str, Path]]:
    files = {
        "llama-cpu": _archive(tmp_path / "llama.zip", "llama-server", b"llama"),
        "napcat": _archive(tmp_path / "napcat.zip", "NapCat/napcat.exe", b"napcat"),
        "qwen3-embedding-0.6b": tmp_path / "embedding.gguf",
    }
    files["qwen3-embedding-0.6b"].write_bytes(b"embedding")
    records = [
        {
            "kind": "component",
            "id": "llama-cpu",
            "version": "4.0.1",
            "path": "llama-cpu.zip",
            "checksum": _sha256(files["llama-cpu"]),
            "platform": "windows-amd64",
            "backend": "cpu",
            "runtime_api": "openai-compatible",
            "driver_min": "none",
            "abi": "documented",
            "license": "llama.cpp",
            "sbom": "llama-sbom.json",
            "source": "https://example.invalid/llama-cpu.zip",
            "artifact": "llama-cpu.zip",
            "status": "available",
        },
        {
            "kind": "onebot",
            "id": "napcat",
            "version": "1.0.0",
            "path": "napcat.zip",
            "checksum": _sha256(files["napcat"]),
            "platform": "windows-amd64",
            "license": "NapCat",
            "sbom": "napcat-sbom.json",
            "source": "https://example.invalid/napcat.zip",
            "artifact": "napcat.zip",
            "status": "available",
        },
        {
            "kind": "model",
            "id": "qwen3-embedding-0.6b",
            "version": "q8_0",
            "path": "models/embedding/Qwen3-Embedding-0.6B-Q8_0.gguf",
            "checksum": _sha256(files["qwen3-embedding-0.6b"]),
            "platform": "windows-amd64",
            "model_role": "embedding",
            "runtime_api": "llama.cpp-embedding",
            "license": "Apache-2.0",
            "source": "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf",
            "artifact": "Qwen3-Embedding-0.6B-Q8_0.gguf",
            "status": "available",
            "size": files["qwen3-embedding-0.6b"].stat().st_size,
            "dimension": 1024,
            "remote": True,
        },
    ]
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-09-12T00:00:00+00:00",
                "platform": "windows-amd64",
                "profile": "oneclick-python",
                "packages": records,
            }
        ),
        encoding="utf-8",
    )
    return catalog, files


def test_standalone_bootstrap_skips_network(tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("Standalone must not acquire remote packages")

    monkeypatch.setattr(bootstrap.acquire, "download_verified", fail)
    result = bootstrap.install_profile("standalone-python", tmp_path / "data")
    assert result["state"] == "skipped"
    assert bootstrap.read_progress(tmp_path / "data")["state"] == "skipped"


def test_oneclick_installs_declared_components_and_only_embedding(
    tmp_path, monkeypatch
):
    catalog, files = _catalog(tmp_path)
    source_map = {
        "https://example.invalid/llama-cpu.zip": files["llama-cpu"],
        "https://example.invalid/napcat.zip": files["napcat"],
        "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf": files[
            "qwen3-embedding-0.6b"
        ],
    }

    def fake_download(source, destination, *, checksum, size=None, **_kwargs):
        source_path = source_map[source]
        assert _sha256(source_path) == checksum
        if size is not None:
            assert source_path.stat().st_size == size
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source_path.read_bytes())
        return destination

    monkeypatch.setattr(bootstrap.acquire, "download_verified", fake_download)
    data_root = tmp_path / "data"
    result = bootstrap.install_profile(
        "oneclick-python", data_root, catalog_path=catalog
    )

    assert result["state"] == "complete"
    assert (data_root / ".stella" / "components" / "llama-cpu" / "4.0.1").is_dir()
    assert napcat.status(data_root)["state"] == "not_logged_in"
    assert napcat.status(data_root)["unattended"] is False
    registry = packages.read_registry(data_root)
    assert registry["active"]["embedding"] == "qwen3-embedding-0.6b@q8_0"
    assert not any(
        item.get("model_role") in {"chat", "consolidation", "reranker"}
        for item in registry["packages"]
    )
    assert bootstrap.read_progress(data_root)["state"] == "complete"


def test_oneclick_failure_records_failed_progress(tmp_path, monkeypatch):
    catalog, _files = _catalog(tmp_path)

    def fail(*_args, **_kwargs):
        raise bootstrap.acquire.AcquireError("download_failed", "offline")

    monkeypatch.setattr(bootstrap.acquire, "download_verified", fail)
    with pytest.raises(bootstrap.BootstrapError, match="下载失败"):
        bootstrap.install_profile(
            "oneclick-python", tmp_path / "data", catalog_path=catalog
        )
    progress = bootstrap.read_progress(tmp_path / "data")
    assert progress["state"] == "failed"
    assert progress["completed"] == []


def test_oneclick_is_idempotent_without_redownloading(tmp_path, monkeypatch):
    catalog, files = _catalog(tmp_path)
    source_map = {
        "https://example.invalid/llama-cpu.zip": files["llama-cpu"],
        "https://example.invalid/napcat.zip": files["napcat"],
        "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf": files[
            "qwen3-embedding-0.6b"
        ],
    }
    calls = 0

    def fake_download(source, destination, *, checksum, size=None, **_kwargs):
        nonlocal calls
        calls += 1
        source_path = source_map[source]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source_path.read_bytes())
        return destination

    monkeypatch.setattr(bootstrap.acquire, "download_verified", fake_download)
    data_root = tmp_path / "data"
    bootstrap.install_profile("oneclick-python", data_root, catalog_path=catalog)
    result = bootstrap.install_profile(
        "oneclick-python", data_root, catalog_path=catalog
    )

    assert result["resumed"] is True
    assert calls == 3
