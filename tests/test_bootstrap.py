from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from deploy import bootstrap, napcat, packages, runtime


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


def test_bundled_catalog_is_used_before_network(tmp_path, monkeypatch):
    catalog, _files = _catalog(tmp_path)
    bundled = tmp_path / "package-catalog-windows-amd64.json"
    bundled.write_bytes(catalog.read_bytes())
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

    def fail(*_args, **_kwargs):
        raise AssertionError("Bundled catalog should avoid catalog network access")

    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", fail)
    profile = {
        "id": "oneclick-python",
        "catalog_url": "https://example.invalid/catalog.json",
    }

    loaded = bootstrap._load_catalog(profile, None)

    assert loaded["schema_version"] == 1
    assert len(loaded["packages"]) == 3


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
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(runtime, "INSTANCE_ID", "oneclick-test")
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
    manifest = runtime.read_manifest()
    llama = manifest["components"]["llama"]
    assert llama["enabled"] is True
    assert llama["config"]["embedding_model"]["id"] == "qwen3-embedding-0.6b"
    assert llama["config"]["embedding_model"]["path"].endswith(
        "qwen3-embedding-0.6b.gguf"
    )
    env = (data_root / ".env").read_text(encoding="utf-8")
    assert "MEMORY_EMBEDDING_ENABLED=true" in env
    assert "MEMORY_EMBEDDING_MODEL=qwen3-embedding-0.6b" in env
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


def test_completed_oneclick_refreshes_stale_catalog_components(
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

    payload = json.loads(catalog.read_text(encoding="utf-8"))
    payload["packages"][0]["version"] = "4.0.2"
    catalog.write_text(json.dumps(payload), encoding="utf-8")

    result = bootstrap.install_profile(
        "oneclick-python", data_root, catalog_path=catalog
    )

    assert result["state"] == "complete"
    assert result.get("resumed") is None
    assert calls == 4
    assert (
        data_root / ".stella" / "components" / "llama-cpu" / "4.0.2"
    ).is_dir()


def test_completed_oneclick_repair_restores_manifest_and_env(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(runtime, "STELLA_HOME", data_root)
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(runtime, "INSTANCE_ID", "repair-test")
    model = data_root / ".stella" / "packages" / "model" / "qwen.gguf"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")
    packages.write_registry(
        {
            "schema_version": 1,
            "updated_at": "now",
            "packages": [
                {
                    "kind": "model",
                    "id": "qwen3-embedding-0.6b",
                    "version": "q8_0",
                    "path": ".stella/packages/model/qwen.gguf",
                    "checksum": "a" * 64,
                    "model_role": "embedding",
                }
            ],
            "active": {"embedding": "qwen3-embedding-0.6b@q8_0"},
            "history": [],
        },
        data_root,
    )
    (data_root / ".stella" / bootstrap.PROGRESS_FILENAME).parent.mkdir(
        parents=True, exist_ok=True
    )
    bootstrap._write_progress(
        data_root,
        profile_id="oneclick-rust",
        state="complete",
        completed=["llama-cpu", "qwen3-embedding-0.6b"],
    )
    (data_root / ".env").write_text(
        "MEMORY_EMBEDDING_ENABLED=false\n"
        "MEMORY_EMBEDDING_MODEL=text-embedding-qwen3-embedding-0.6b\n",
        encoding="utf-8",
    )

    assert bootstrap.repair_oneclick_runtime(data_root) is True
    manifest = runtime.read_manifest()
    assert manifest["components"]["llama"]["enabled"] is True
    assert (
        manifest["components"]["llama"]["config"]["embedding_model"]["id"]
        == "qwen3-embedding-0.6b"
    )
    env = (data_root / ".env").read_text(encoding="utf-8")
    assert "MEMORY_EMBEDDING_ENABLED=true" in env


# ============================================================
# 随包离线仓（OneClick Offline）
# ============================================================


def _seed_offline_packages(root: Path, catalog: Path, files: dict[str, Path]) -> None:
    """把 catalog 声明的组件按 artifact 文件名预置进 <root>/offline/packages。"""
    id_to_file = {
        "llama-cpu": files["llama-cpu"],
        "napcat": files["napcat"],
        "qwen3-embedding-0.6b": files["qwen3-embedding-0.6b"],
    }
    packages_dir = root / "offline" / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    for record in json.loads(catalog.read_text(encoding="utf-8"))["packages"]:
        shutil.copyfile(id_to_file[record["id"]], packages_dir / record["artifact"])


_SOURCE_MAP_KEYS = (
    "https://example.invalid/llama-cpu.zip",
    "https://example.invalid/napcat.zip",
    "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf",
)


def _fake_downloader(source_map):
    def fake_download(source, destination, *, checksum, size=None, **_kwargs):
        source_path = source_map[source]
        assert _sha256(source_path) == checksum
        if size is not None:
            assert source_path.stat().st_size == size
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source_path.read_bytes())
        return destination

    return fake_download


def test_verify_local_artifact_accepts_matching_copy(tmp_path):
    artifact = tmp_path / "component.zip"
    artifact.write_bytes(b"payload")
    assert (
        bootstrap.acquire.verify_local_artifact(artifact, checksum=_sha256(artifact))
        == artifact
    )


def test_verify_local_artifact_rejects_tampered_copy(tmp_path):
    artifact = tmp_path / "component.zip"
    artifact.write_bytes(b"payload")
    with pytest.raises(bootstrap.acquire.AcquireError, match="checksum"):
        bootstrap.acquire.verify_local_artifact(artifact, checksum="0" * 64)


def test_verify_local_artifact_rejects_size_mismatch(tmp_path):
    artifact = tmp_path / "component.zip"
    artifact.write_bytes(b"payload")
    with pytest.raises(bootstrap.acquire.AcquireError, match="大小"):
        bootstrap.acquire.verify_local_artifact(
            artifact, checksum=_sha256(artifact), size=999
        )


def test_offline_packages_serve_components_without_network(tmp_path, monkeypatch):
    catalog, files = _catalog(tmp_path)
    _seed_offline_packages(tmp_path, catalog, files)
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)

    def fail(*_args, **_kwargs):
        raise AssertionError("Offline bundle must serve packages without network")

    monkeypatch.setattr(bootstrap.acquire, "download_verified", fail)
    data_root = tmp_path / "data"
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(runtime, "INSTANCE_ID", "oneclick-offline-test")

    result = bootstrap.install_profile(
        "oneclick-python", data_root, catalog_path=catalog
    )

    assert result["state"] == "complete"
    assert (data_root / ".stella" / "components" / "llama-cpu" / "4.0.1").is_dir()
    registry = packages.read_registry(data_root)
    assert registry["active"]["embedding"] == "qwen3-embedding-0.6b@q8_0"
    assert bootstrap.read_progress(data_root)["state"] == "complete"


def test_corrupt_offline_package_falls_back_to_download(tmp_path, monkeypatch):
    catalog, files = _catalog(tmp_path)
    _seed_offline_packages(tmp_path, catalog, files)
    # 篡改其中一个离线副本：内容不再匹配 catalog checksum，必须被拒收并回落在线
    (tmp_path / "offline" / "packages" / "llama-cpu.zip").write_bytes(b"tampered")
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    source_map = dict(zip(_SOURCE_MAP_KEYS, files.values(), strict=True))
    monkeypatch.setattr(
        bootstrap.acquire, "download_verified", _fake_downloader(source_map)
    )
    data_root = tmp_path / "data"
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(runtime, "INSTANCE_ID", "oneclick-offline-fallback-test")

    result = bootstrap.install_profile(
        "oneclick-python", data_root, catalog_path=catalog
    )

    assert result["state"] == "complete"
    assert (data_root / ".stella" / "components" / "llama-cpu" / "4.0.1").is_dir()
