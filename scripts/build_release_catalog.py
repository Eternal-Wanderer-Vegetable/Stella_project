#!/usr/bin/env python3
"""Build the remote catalog consumed by the Windows OneClick bootstrap."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from deploy.profiles import ONECLICK_DEFAULT_EMBEDDING

NAPCAT = {
    "kind": "onebot",
    "id": "napcat",
    "version": "3.2.1",
    "platform": "windows-amd64",
    "source": (
        "https://github.com/NapNeko/NapCatQQ-Desktop/releases/download/"
        "v3.2.1/NapCatQQ-Desktop-3.2.1-x64.msi"
    ),
    "checksum": "1dca9b69fabe6524370f1e8df0c7384edb9f112080878bd8ec52aa38495990df",
    "license": "GPL-3.0",
    "sbom": (
        "https://github.com/NapNeko/NapCatQQ-Desktop/releases/download/"
        "v3.2.1/SHA256SUMS"
    ),
    "artifact": "NapCatQQ-Desktop-3.2.1-x64.msi",
    "status": "available",
    "remote": True,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_catalog(backend_asset: Path, *, release_ref: str, repository: str) -> dict:
    backend_asset = Path(backend_asset).resolve()
    metadata_path = backend_asset.parent / "BACKEND.json"
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    else:
        with zipfile.ZipFile(backend_asset) as bundle:
            metadata = json.loads(
                bundle.read("BACKEND.json").decode("utf-8")
            )
    if metadata.get("backend") != "cpu" or metadata.get("os") != "windows":
        raise ValueError("catalog backend asset must be the Windows CPU package")
    version = release_ref.removeprefix("v")
    backend_name = backend_asset.name
    packages = [
        {
            "kind": "component",
            "id": "llama-cpu",
            "version": version,
            "path": backend_name,
            "checksum": _sha256(backend_asset),
            "platform": "windows-amd64",
            "backend": "cpu",
            "runtime_api": metadata["runtime_api"],
            "driver_min": metadata["driver_min"],
            "abi": metadata["abi"],
            "license": metadata["license"],
            "sbom": "SBOM.json",
            "source": (
                f"https://github.com/{repository}/releases/download/"
                f"{release_ref}/{backend_name}"
            ),
            "artifact": backend_name,
            "status": metadata["status"],
            "size": backend_asset.stat().st_size,
            "remote": True,
        },
        NAPCAT,
        {
            "kind": "model",
            "id": ONECLICK_DEFAULT_EMBEDDING["id"],
            "version": ONECLICK_DEFAULT_EMBEDDING["version"],
            "path": f"models/embedding/{ONECLICK_DEFAULT_EMBEDDING['filename']}",
            "checksum": ONECLICK_DEFAULT_EMBEDDING["sha256"],
            "platform": "windows-amd64",
            "runtime_api": "llama.cpp-embedding",
            "license": ONECLICK_DEFAULT_EMBEDDING["license"],
            "source": ONECLICK_DEFAULT_EMBEDDING["source"],
            "artifact": ONECLICK_DEFAULT_EMBEDDING["filename"],
            "status": "available",
            "size": ONECLICK_DEFAULT_EMBEDDING["size"],
            "dimension": ONECLICK_DEFAULT_EMBEDDING["dimension"],
            "model_role": "embedding",
            "remote": True,
        },
    ]
    return {
        "schema_version": 1,
        "generated_at": "release-build",
        "platform": "windows-amd64",
        "packages": packages,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-asset", type=Path, required=True)
    parser.add_argument("--release-ref", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_catalog(
        args.backend_asset,
        release_ref=args.release_ref,
        repository=args.repository,
    )
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
