#!/usr/bin/env python3
"""Build and assemble one real llama.cpp backend package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

FLAGS = {
    "cpu": [],
    "cuda": ["-DGGML_CUDA=ON"],
    "hip": ["-DGGML_HIPBLAS=ON"],
    "metal": ["-DGGML_METAL=ON"],
    "vulkan": ["-DGGML_VULKAN=ON"],
}
WINDOWS_OPENSSL_DLLS = (
    ("libcrypto-3-x64.dll", "libcrypto-3.dll"),
    ("libssl-3-x64.dll", "libssl-3.dll"),
)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_roots(
    build_dir: Path,
    executable: Path,
    runtime_dirs: Iterable[Path],
) -> list[Path]:
    roots = [build_dir, executable.parent]
    for directory in runtime_dirs:
        roots.append(Path(directory).expanduser())
    for variable in ("OPENSSL_BIN_DIR", "OPENSSL_ROOT_DIR", "OPENSSL_DIR"):
        value = os.environ.get(variable)
        if not value:
            continue
        root = Path(value).expanduser()
        roots.append(root / "bin" if variable != "OPENSSL_BIN_DIR" else root)
    vcpkg_root = os.environ.get("VCPKG_INSTALLATION_ROOT")
    if vcpkg_root:
        roots.append(Path(vcpkg_root) / "installed" / "x64-windows" / "bin")
    roots.extend(Path(entry) for entry in os.environ.get("PATH", "").split(os.pathsep) if entry)
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = os.path.normcase(str(root))
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _find_runtime_dll(name: str, roots: Iterable[Path]) -> Path | None:
    for root in roots:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _find_openssl_dll(
    alternatives: tuple[str, ...], roots: Iterable[Path]
) -> Path | None:
    for name in alternatives:
        source = _find_runtime_dll(name, roots)
        if source is not None:
            return source
    return None


def _copy_runtime_libraries(
    build_dir: Path,
    executable: Path,
    output: Path,
    *,
    os_name: str,
    runtime_dirs: Iterable[Path],
) -> None:
    for path in build_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".dll", ".so", ".dylib"}:
            shutil.copy2(path, output / path.name)
    if os_name != "windows":
        return
    roots = _runtime_roots(build_dir, executable, runtime_dirs)
    missing: list[str] = []
    for alternatives in WINDOWS_OPENSSL_DLLS:
        if any((output / name).is_file() for name in alternatives):
            continue
        source = _find_openssl_dll(alternatives, roots)
        if source is None:
            missing.append("/".join(alternatives))
            continue
        # Preserve the filename supplied by the OpenSSL distribution. Renaming
        # an ABI-specific DLL can make the Windows loader reject it.
        shutil.copy2(source, output / source.name)
    if missing:
        raise FileNotFoundError(
            "Windows llama.cpp package is missing required OpenSSL runtime DLLs: "
            + ", ".join(missing)
            + ". Set OPENSSL_RUNTIME_DIR or pass --runtime-dir. "
            "The package keeps the DLL filename supplied by the runtime."
        )


def build(
    source: Path,
    output: Path,
    *,
    backend: str,
    commit: str,
    os_name: str,
    arch: str,
    runtime_dirs: Iterable[Path] = (),
) -> Path:
    if backend not in FLAGS:
        raise ValueError(f"unsupported backend: {backend}")
    source = Path(source).resolve()
    output = Path(output).resolve()
    normalized_os = "windows" if os_name.lower().startswith("windows") else os_name.lower()
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
    suffix = ".exe" if normalized_os == "windows" else ""
    candidates = [
        build_dir / "bin" / f"llama-server{suffix}",
        build_dir / "bin" / "Release" / f"llama-server{suffix}",
        build_dir / "Release" / f"llama-server{suffix}",
        build_dir / f"llama-server{suffix}",
    ]
    discovered = sorted(
        path
        for path in build_dir.rglob(f"llama-server{suffix}")
        if path.is_file() and path not in candidates
    )
    executable = next(
        (path for path in [*candidates, *discovered] if path.is_file()),
        None,
    )
    if executable is None:
        raise FileNotFoundError(
            f"cmake completed but llama-server was not found under {build_dir}; "
            f"searched: {', '.join(str(path) for path in [*candidates, *discovered])}"
        )
    shutil.copy2(executable, output / executable.name)
    _copy_runtime_libraries(
        build_dir,
        executable,
        output,
        os_name=normalized_os,
        runtime_dirs=runtime_dirs,
    )
    license_source = next(
        (path for path in (source / "LICENSE", source / "LICENSE.md") if path.is_file()),
        None,
    )
    if license_source is None:
        raise FileNotFoundError("llama.cpp source has no LICENSE file")
    shutil.copy2(license_source, output / "LICENSE")
    metadata = {
        "backend": backend,
        "os": normalized_os,
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
    parser.add_argument("--runtime-dir", action="append", type=Path, default=[])
    args = parser.parse_args()
    build(
        args.source,
        args.output,
        backend=args.backend,
        commit=args.commit,
        os_name=args.os_name,
        arch=args.arch,
        runtime_dirs=args.runtime_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
