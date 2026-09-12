#!/usr/bin/env python3
"""Assemble the four v4.0.1 release products from an explicit allowlist."""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from deploy.profiles import load_profile

COMMON_FILES = (
    "bot.py",
    "requirements.txt",
    "pyproject.toml",
    "LICENSE",
    "README.md",
    ".env.example",
    "start.bat",
    "doctor.bat",
    "stop.bat",
    "README-快速开始.txt",
)
COMMON_DIRS = (
    "config",
    "core",
    "deploy",
    "extensions",
    "memory",
    "system_prompts",
    "runtime-manager",
)
RUST_DIRS = ("memory_rust",)
INSTALLER_FILES = COMMON_FILES + (
    "runtime-manager/schemas/runtime-manifest.schema.json",
    "runtime-manager/schemas/runtime-state.schema.json",
    "runtime-manager/schemas/package-catalog.schema.json",
    "runtime-manager/schemas/package-registry.schema.json",
)
INSTALLER_DIRS = COMMON_DIRS
FORBIDDEN_PARTS = (
    "StellaData",
    "runtime",
    "napcat",
    "models",
    "logs",
    "tests",
    ".git",
    ".gitnexus",
    "design_docs",
    "stella-installer",
    "benchmark",
)


def _copy_tree(source: Path, destination: Path, relative: str) -> None:
    source_path = source / relative
    if not source_path.exists() and relative in {
        "start.bat",
        "doctor.bat",
        "stop.bat",
        "README-快速开始.txt",
    }:
        source_path = source / "release_assets" / relative
    if not source_path.exists():
        raise FileNotFoundError(f"allowlist entry is missing: {relative}")
    target = destination / relative
    if source_path.is_dir():
        shutil.copytree(
            source_path,
            target,
            dirs_exist_ok=True,
            ignore=_ignore_release_entries,
        )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)


def _ignore_release_entries(_path: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if (
            name in FORBIDDEN_PARTS
            or name in {".env", ".env.dev", ".env.prod", ".env.bak"}
            or name.endswith((".db", ".log", ".jsonl", ".pyc"))
        ):
            ignored.add(name)
    return ignored


def _assert_clean(root: Path) -> None:
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        parts = set(relative.split("/"))
        if parts.intersection(FORBIDDEN_PARTS) or path.name.endswith((".db", ".log", ".jsonl")):
            raise ValueError(f"forbidden release content: {relative}")
        if path.name in {".env", ".env.dev", ".env.prod", ".env.bak", "deploy.answers.toml"}:
            raise ValueError(f"secret or user data in release content: {relative}")


def build_standalone(
    source: Path,
    output: Path,
    profile_id: str,
    *,
    rust_wheel: Path | None = None,
) -> Path:
    profile = load_profile(profile_id)
    if profile["distribution"] != "standalone":
        raise ValueError(f"{profile_id} is not a standalone profile")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for relative in COMMON_FILES + COMMON_DIRS:
        _copy_tree(source, output, relative)
    if profile["core_flavor"] == "rust":
        for relative in RUST_DIRS:
            _copy_tree(source, output, relative)
        if rust_wheel is not None:
            wheel = Path(rust_wheel).resolve()
            if not wheel.is_file() or wheel.suffix.lower() != ".whl":
                raise FileNotFoundError(f"Rust wheel is missing: {wheel}")
            target = output / "wheels" / wheel.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wheel, target)
    _assert_clean(output)
    archive = output.parent / profile["artifact"]["filename"]
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(output).as_posix())
    return archive


def build_oneclick(installer: Path, output: Path, profile_id: str) -> Path:
    profile = load_profile(profile_id)
    if profile["distribution"] != "oneclick":
        raise ValueError(f"{profile_id} is not a one-click profile")
    if not installer.is_file():
        raise FileNotFoundError(f"installer is missing: {installer}")
    output.mkdir(parents=True, exist_ok=True)
    target = output / profile["artifact"]["filename"]
    shutil.copy2(installer, target)
    siblings = [path for path in output.iterdir() if path.is_file() and path != target]
    for sibling in siblings:
        sibling.unlink()
    return target


def stage_installer_resources(source: Path, output: Path, profile_id: str) -> Path:
    """Stage the allowlisted program tree embedded by the Tauri installer."""
    profile = load_profile(profile_id)
    if profile["distribution"] != "oneclick":
        raise ValueError(f"{profile_id} is not a one-click profile")
    source = Path(source).resolve()
    output = Path(output).resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for relative in INSTALLER_FILES + INSTALLER_DIRS:
        _copy_tree(source, output, relative)
    wheels = source / "wheels"
    if profile["core_flavor"] == "rust" and wheels.is_dir():
        shutil.copytree(wheels, output / "wheels", dirs_exist_ok=True)
    (output / ".stella-profile").write_text(profile_id + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile", choices=(
        "oneclick-python",
        "oneclick-rust",
        "standalone-python",
        "standalone-rust",
    ))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--stage-resources", type=Path)
    parser.add_argument("--rust-wheel", type=Path)
    args = parser.parse_args()
    if args.stage_resources is not None:
        stage_installer_resources(args.source, args.stage_resources, args.profile)
        return 0
    if args.profile.startswith("oneclick-"):
        if args.installer is None:
            parser.error("--installer is required for one-click profiles")
        result = build_oneclick(args.installer, args.output, args.profile)
    else:
        result = build_standalone(
            args.source.resolve(),
            args.output.resolve(),
            args.profile,
            rust_wheel=args.rust_wheel,
        )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
