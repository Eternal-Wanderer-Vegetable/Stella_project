from __future__ import annotations

import hashlib
import json

import pytest

from deploy import packages
from scripts.verify_llama_package import verify


def _write_backend(root, backend="cpu", status="build-only"):
    artifact = root / "llama-server"
    artifact.write_bytes(b"server")
    (root / "LICENSE").write_text("license", encoding="utf-8")
    (root / "SBOM.json").write_text("{}", encoding="utf-8")
    metadata = {
        "backend": backend,
        "os": "linux",
        "arch": "x86_64",
        "abi": "gnu",
        "runtime_api": "openai-compatible",
        "license": "MIT",
        "sbom": "SBOM.json",
        "status": status,
    }
    (root / "BACKEND.json").write_text(json.dumps(metadata), encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (root / "SHA256SUMS.txt").write_text(f"{digest}  llama-server\n", encoding="utf-8")


def test_backend_package_verifier_requires_provenance_and_checksums(tmp_path):
    _write_backend(tmp_path)
    assert verify(tmp_path) == []
    (tmp_path / "llama-server").write_bytes(b"changed")
    assert any("checksum mismatch" in item for item in verify(tmp_path))


def test_catalog_accepts_all_backend_metadata(tmp_path):
    (tmp_path / "start.bat").write_text("start", encoding="utf-8")
    records = []
    for backend in ("cpu", "cuda", "hip", "metal", "vulkan"):
        artifact = tmp_path / f"llama-{backend}.zip"
        artifact.write_bytes(backend.encode())
        records.append(
            {
                "kind": "component",
                "id": f"llama-{backend}",
                "version": "4.0.0",
                "path": artifact.name,
                "checksum": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "platform": "any",
                "backend": backend,
                "runtime_api": "openai-compatible",
                "driver_min": "none" if backend == "cpu" else "documented",
                "abi": "test",
                "dependencies": [],
                "license": "MIT",
                "sbom": f"{backend}.spdx.json",
                "source": "llama.cpp pinned commit",
                "artifact": artifact.name,
                "status": "build-only",
            }
        )
        (tmp_path / f"{backend}.spdx.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".stella-llama-catalog.json").write_text(
        json.dumps({"packages": records}), encoding="utf-8"
    )
    catalog = packages.build_catalog(tmp_path)
    assert {item["backend"] for item in catalog["packages"] if "backend" in item} == {
        "cpu", "cuda", "hip", "metal", "vulkan"
    }
    packages.write_catalog(tmp_path)
    assert packages.verify_catalog(tmp_path) == []


def test_catalog_rejects_invalid_backend(tmp_path):
    artifact = tmp_path / "x.zip"
    artifact.write_bytes(b"x")
    (tmp_path / ".stella-llama-catalog.json").write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "kind": "component",
                        "id": "llama-x",
                        "version": "1",
                        "path": "x.zip",
                        "checksum": hashlib.sha256(b"x").hexdigest(),
                        "backend": "directml",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(packages.PackageError):
        packages.build_catalog(tmp_path)
