#!/usr/bin/env python3
"""Verify a llama.cpp backend package before it reaches a release asset."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BACKENDS = {"cpu", "cuda", "hip", "metal", "vulkan"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(root: Path) -> list[str]:
    root = Path(root).resolve()
    problems: list[str] = []
    metadata_path = root / "BACKEND.json"
    if not metadata_path.is_file():
        return ["missing BACKEND.json"]
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["BACKEND.json is not valid JSON"]
    backend = metadata.get("backend")
    for key in ("backend", "os", "arch", "abi", "runtime_api", "license", "sbom", "status"):
        if not str(metadata.get(key, "")).strip():
            problems.append(f"missing metadata: {key}")
    if backend not in BACKENDS:
        problems.append(f"unsupported backend: {backend}")
    if metadata.get("status") not in {"build-only", "hardware-verified", "unavailable"}:
        problems.append("status must distinguish build-only and hardware-verified")
    for relative in ("LICENSE", str(metadata.get("sbom", ""))):
        if relative and not (root / relative).is_file():
            problems.append(f"missing provenance file: {relative}")
    executable = root / ("llama-server.exe" if metadata.get("os") == "windows" else "llama-server")
    if not executable.is_file():
        problems.append(f"missing executable: {executable.name}")
    sums = root / "SHA256SUMS.txt"
    if not sums.is_file():
        problems.append("missing SHA256SUMS.txt")
    else:
        for line in sums.read_text(encoding="utf-8").splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                problems.append("malformed SHA256SUMS.txt entry")
                continue
            expected, relative = parts
            target = root / relative.lstrip("*")
            if not target.is_file() or _sha256(target) != expected.lower():
                problems.append(f"checksum mismatch: {relative}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    problems = verify(args.package)
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print(f"verified llama package: {args.package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
