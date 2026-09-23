#!/usr/bin/env python3
"""Assemble the four release products from an explicit allowlist."""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from deploy.profiles import PROFILE_IDS, load_profile

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
# 常见运行目录。⚠️ 新增顶层包（如 skills/knowledge/webui）时必须同步这里，
# 否则 payload 缺包：轻则功能 404（webui 挂载被 manage 路由的模块级导入连坐，
# 2026-09-24 实测），重则启动期 ModuleNotFoundError。
COMMON_DIRS = (
    "astrbot_compat",
    "capability",
    "config",
    "core",
    "deploy",
    "extensions",
    "knowledge",
    "memory",
    "skills",
    "system_prompts",
    "runtime-manager",
    "stella_project",
    # 内置技能在 assets/skills 下（SKILLS_BUILTIN_DIR 默认指这里）
    "assets",
    # M6：v2 桌面壳 + WebUI 前端产物（方案 §12.3）
    "desktop",
    "webui",
)
RUST_DIRS = ("memory_rust",)
INSTALLER_FILES = (
    *COMMON_FILES,
    "runtime-manager/schemas/runtime-manifest.schema.json",
    "runtime-manager/schemas/runtime-state.schema.json",
    "runtime-manager/schemas/package-catalog.schema.json",
    "runtime-manager/schemas/package-registry.schema.json",
    *(f"release_assets/product-profiles/{profile_id}.json" for profile_id in PROFILE_IDS),
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
    "dashboard",
    "openspec",
    "benchmark",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "venv",
)


def _copy_tree(
    source: Path,
    destination: Path,
    relative: str,
    *,
    prune: Path | None = None,
) -> None:
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
        # 剪掉「阶段产物目录自身」：M6 起桌面壳目录（desktop/）进入发布清单，
        # 而 --stage-resources 的输出恰在 desktop/ 内部——不剪就会把输出目录
        # 里的自己再往里拷，copytree 无限递归（CI RecursionError 实测）。
        prune_resolved = prune.resolve() if prune is not None else None

        def _ignore(dir_path: str, names: list[str]) -> set[str]:
            blocked = _ignore_release_entries(dir_path, names)
            if prune_resolved is not None:
                for name in names:
                    if (Path(dir_path) / name).resolve() == prune_resolved:
                        blocked.add(name)
            return blocked

        shutil.copytree(
            source_path,
            target,
            dirs_exist_ok=True,
            ignore=_ignore,
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


def build_oneclick(
    installer: Path,
    output: Path,
    profile_id: str,
    *,
    artifact_name: str | None = None,
) -> Path:
    profile = load_profile(profile_id)
    if profile["distribution"] != "oneclick":
        raise ValueError(f"{profile_id} is not a one-click profile")
    if not installer.is_file():
        raise FileNotFoundError(f"installer is missing: {installer}")
    output.mkdir(parents=True, exist_ok=True)
    # artifact_name：Offline 变体与在线版同一 profile，只靠产物文件名区分
    # （payload 是否存在决定行为，profile id 保持不变）。
    target = output / (artifact_name or profile["artifact"]["filename"])
    shutil.copy2(installer, target)
    siblings = [path for path in output.iterdir() if path.is_file() and path != target]
    for sibling in siblings:
        sibling.unlink()
    return target


def stage_installer_resources(
    source: Path,
    output: Path,
    profile_id: str,
    *,
    offline_payload: Path | None = None,
) -> Path:
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
        _copy_tree(source, output, relative, prune=output)
    # webui/dist 兜底：CI 漏拷（或本地源码树没构建前端）时，回退使用桌面壳的
    # dashboard-dist——两处是同一份产物，缺一不可（面板由 Bot 同端口托管）。
    webui_dist = output / "webui" / "dist"
    shell_dist = source / "desktop" / "dashboard-dist"
    if not webui_dist.exists() and shell_dist.is_dir():
        shutil.copytree(shell_dist, webui_dist)
    bundled_catalog = source / "package-catalog-windows-amd64.json"
    if bundled_catalog.is_file():
        _copy_tree(source, output, bundled_catalog.name)
    wheels = source / "wheels"
    if profile["core_flavor"] == "rust" and wheels.is_dir():
        shutil.copytree(wheels, output / "wheels", dirs_exist_ok=True)
    (output / ".stella-profile").write_text(profile_id + "\n", encoding="utf-8")
    if offline_payload is not None:
        offline_payload = Path(offline_payload).resolve()
        if not offline_payload.is_dir():
            raise FileNotFoundError(f"offline payload is missing: {offline_payload}")
        # 整仓原样进 resources/stella/offline：安装器（python.rs）按
        # <程序根>/offline 寻址，deploy 按 catalog 的 artifact 文件名寻址。
        shutil.copytree(offline_payload, output / "offline", dirs_exist_ok=True)
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
    parser.add_argument("--offline-payload", type=Path,
                        help="build_offline_payload.py 的产物，随 resources 嵌入（Offline 变体）")
    parser.add_argument("--artifact-name",
                        help="覆盖 oneclick 产物文件名（Offline 变体用）")
    args = parser.parse_args()
    if args.offline_payload is not None and not args.stage_resources:
        parser.error("--offline-payload 只能与 --stage-resources 搭配")
    if args.artifact_name is not None and not args.profile.startswith("oneclick-"):
        parser.error("--artifact-name 只适用于 oneclick profile")
    if args.stage_resources is not None:
        stage_installer_resources(
            args.source, args.stage_resources, args.profile,
            offline_payload=args.offline_payload,
        )
        return 0
    if args.profile.startswith("oneclick-"):
        if args.installer is None:
            parser.error("--installer is required for one-click profiles")
        result = build_oneclick(
            args.installer, args.output, args.profile,
            artifact_name=args.artifact_name,
        )
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
