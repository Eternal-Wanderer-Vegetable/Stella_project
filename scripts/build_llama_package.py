#!/usr/bin/env python3
"""Build and assemble one real llama.cpp backend package."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

FLAGS = {
    "cpu": [],
    "cuda": ["-DGGML_CUDA=ON"],
    "hip": ["-DGGML_HIPBLAS=ON"],
    "metal": ["-DGGML_METAL=ON"],
    "vulkan": ["-DGGML_VULKAN=ON"],
}


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(source: Path, output: Path, *, backend: str, commit: str, os_name: str, arch: str) -> Path:
    if backend not in FLAGS:
        raise ValueError(f"unsupported backend: {backend}")
    source = Path(source).resolve()
    output = Path(output).resolve()
    build_dir = output.parent / f".llama-build-{backend}"
    if not (source / "CMakeLists.txt").is_file():
        raise FileNotFoundError(f"llama.cpp source is missing CMakeLists.txt: {source}")
    output.mkdir(parents=True, exist_ok=True)
    configure = [
        "cmake",
        "-S",
        str(source),
        "-B",
        str(build_dir),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DGGML_NATIVE=OFF",
        *FLAGS[backend],
    ]
    subprocess.run(configure, check=True)
    subprocess.run(
        ["cmake", "--build", str(build_dir), "--config", "Release", "--target", "llama-server"],
        check=True,
    )
    suffix = ".exe" if os_name.lower().startswith("windows") else ""
    candidates = [
        build_dir / "bin" / f"llama-server{suffix}",
        build_dir / "Release" / f"llama-server{suffix}",
        build_dir / f"llama-server{suffix}",
    ]
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise FileNotFoundError(f"cmake completed but llama-server was not found under {build_dir}")
    shutil.copy2(executable, output / executable.name)
    for path in build_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".dll", ".so", ".dylib"}:
            shutil.copy2(path, output / path.name)
    license_source = next(
        (path for path in (source / "LICENSE", source / "LICENSE.md") if path.is_file()),
        None,
    )
    if license_source is None:
        raise FileNotFoundError("llama.cpp source has no LICENSE file")
    shutil.copy2(license_source, output / "LICENSE")
    metadata = {
        "backend": backend,
        "os": os_name,
        "arch": arch,
        "abi": "documented",
        "runtime_api": "openai-compatible",
        "driver_min": "none" if backend == "cpu" else "runner-documented",
        "license": "llama.cpp",
        "sbom": "SBOM.json",
        "source_commit": commit,
        "status": "build-only",
    }
    (output / "BACKEND.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sbom = {
        "format": "stella-sbom-v1",
        "source_commit": commit,
        "files": [],
    }
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name not in {"SBOM.json", "SHA256SUMS.txt"}:
            sbom["files"].append(
                {"path": path.name, "sha256": _digest(path)}
            )
    (output / "SBOM.json").write_text(
        json.dumps(sbom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        f"{_digest(path)}  {path.name}"
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend", choices=sorted(FLAGS), required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--os", dest="os_name", required=True)
    parser.add_argument("--arch", required=True)
    args = parser.parse_args()
    build(
        args.source,
        args.output,
        backend=args.backend,
        commit=args.commit,
        os_name=args.os_name,
        arch=args.arch,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
