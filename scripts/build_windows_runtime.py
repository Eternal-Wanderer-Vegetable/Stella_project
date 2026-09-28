#!/usr/bin/env python3
"""Pre-assemble a relocatable Windows embedded-Python runtime (WP07).

Goal: a normal install must never run get-pip, resolve requirements or
compile wheels on the user's machine. CI (or a developer) builds the
runtime once:

    python scripts/build_windows_runtime.py --output dist/runtime \
        [--requirements requirements.txt] [--rust-wheel <whl>] \
        [--wheelhouse <dir>] [--python-zip <zip>]

Steps:
  1. stage the embedded Python into a short, ASCII-only staging path;
  2. patch ``python*._pth`` exactly like the install-time helper does;
  3. install pip + the dependency closure INTO the staging runtime
     (pip runs here, at build time - never on the user machine);
  4. optionally unpack the bundled Rust wheel in place (same zipfile -e
     discipline as the GUI: never ``pip --target``);
  5. run build-time self-checks: ``pip check``, stdlib network stack,
     key third-party imports, Rust extension import when present;
  6. write ``runtime-manifest.json`` and a distributable zip that
     excludes build-machine paths and junk.

Relocation (中文/空格路径、外部 cwd、无 PYTHONPATH) is verified by
scripts/check_windows_runtime.py - a plain venv copy proves nothing,
so the check runs the *staged* interpreter from a different path.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from deploy import offline_payload

PYTHON_ZIP_MIRRORS = (
    "https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip",
    "https://mirrors.huaweicloud.com/python/{version}/python-{version}-embed-amd64.zip",
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
RUNTIME_DIRNAME = "runtime"

# 依赖闭包安装后必须能导入的第三方模块（最小代表性集合；完整面板走
# scripts/check_windows_runtime.py 的搬迁验证）。
CORE_IMPORT_PROBE = [
    "ssl",
    "httpx",
    "aiohttp",
    "yaml",
    "pydantic",
    "dotenv",
]

# 打包排除：launcher 可执行文件内嵌构建机的绝对 Python 路径，搬迁即死；
# 启动统一 python -m，因此 Scripts/ 里的 .exe 一律不进产物。pip 的模块
# 本体保留（显式在线修复仍可 `python -m pip`），只排其缓存目录。
EXCLUDED_SUFFIXES = (".exe", ".pyc", ".pyo")
EXCLUDED_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache", ".cache"}
EXCLUDED_FILE_NAMES = {".stella-deps-ready.bak"}


def log(message: str) -> None:
    print(f"[runtime] {message}", flush=True)


def parse_runtime_constants() -> tuple[str, str]:
    from scripts.build_offline_payload import parse_runtime_constants as parse

    return parse()


def fetch_python_zip(output: Path, version: str, expected_sha: str, prebuilt: Path | None) -> Path:
    zip_name = f"python-{version}-embed-amd64.zip"
    destination = output / zip_name
    if prebuilt is not None:
        if not prebuilt.is_file():
            raise SystemExit(f"--python-zip 指定的文件不存在：{prebuilt}")
        shutil.copyfile(prebuilt, destination)
    else:
        last_error = ""
        for mirror in PYTHON_ZIP_MIRRORS:
            url = mirror.format(version=version)
            try:
                with urllib.request.urlopen(url, timeout=300) as response:
                    destination.write_bytes(response.read())
                break
            except OSError as exc:
                last_error = f"{url}: {exc}"
        else:
            raise SystemExit(f"下载 Python 运行时失败（所有镜像均不可用）：{last_error}")
    actual = offline_payload.sha256_file(destination)
    if actual.lower() != expected_sha.lower():
        destination.unlink(missing_ok=True)
        raise SystemExit(f"Python 运行时校验失败\n期望: {expected_sha}\n实际: {actual}")
    log(f"{zip_name} 校验通过")
    return destination


def run_bundled(python: Path, args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        [str(python), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"runtime 步骤失败（退出码 {result.returncode}）：{args}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def patch_pth(runtime: Path) -> None:
    """与 deploy/nsis_bootstrap_helper.patch_pth 同口径（site + 项目根）。"""
    for entry in sorted(runtime.glob("python*._pth")):
        text = entry.read_text(encoding="utf-8")
        text = text.replace("#import site", "import site")
        if not any(line.strip() == ".." for line in text.splitlines()):
            if not text.endswith("\n"):
                text += "\n"
            text += "..\n"
        entry.write_text(text, encoding="utf-8")


def install_dependencies(
    python: Path,
    staging: Path,
    requirements: Path,
    wheelhouse: Path | None,
) -> None:
    """构建期把 pip + 依赖闭包装进 runtime（用户机器不再跑 pip）。"""
    get_pip = staging / "get-pip.py"
    with urllib.request.urlopen(GET_PIP_URL, timeout=120) as response:
        get_pip.write_bytes(response.read())
    run_bundled(python, [str(get_pip), "--no-input", "--no-warn-script-location"],
                staging)
    get_pip.unlink(missing_ok=True)

    args = ["-m", "pip", "install", "--no-input", "--disable-pip-version-check",
            "--no-warn-script-location"]
    if wheelhouse is not None:
        if not wheelhouse.is_dir():
            raise SystemExit(f"--wheelhouse 目录不存在：{wheelhouse}")
        args += ["--no-index", "--find-links", str(wheelhouse)]
    args += ["-r", str(requirements), "setuptools", "wheel"]
    run_bundled(python, args, staging)
    run_bundled(python, ["-m", "pip", "check"], staging)


def install_rust_wheel(python: Path, staging: Path, wheel: Path) -> None:
    run_bundled(python, ["-m", "zipfile", "-e", str(wheel), "."], staging)
    run_bundled(
        python,
        ["-c", "import memory_rust._native, memory_rust.selector"],
        staging,
    )


def strip_launchers(runtime: Path) -> None:
    """删除 Scripts/*.exe：launcher 内嵌构建机绝对路径，搬迁即死。

    pip 安装期产生的入口 launcher 一律不留，启动统一 ``python -m``；
    pip 的模块本体保留（显式修复仍可 ``python -m pip``）。
    """
    scripts = runtime / "Scripts"
    if not scripts.is_dir():
        return
    for launcher in scripts.glob("*.exe"):
        launcher.unlink()
        log(f"移除 launcher：{launcher.name}")


def self_check(python: Path, staging: Path) -> dict[str, object]:
    """构建期自检：网络栈初始化 + 关键第三方导入（在此目录就地运行）。"""
    probe = ";".join(f"import {module}" for module in CORE_IMPORT_PROBE)
    run_bundled(python, ["-c", probe], staging)
    # ssl 实际初始化（DLL 链接错误在 import ssl 时未必暴露）
    run_bundled(
        python,
        ["-c", "import ssl; ctx = ssl.create_default_context(); assert ctx"],
        staging,
    )
    return {"imports": CORE_IMPORT_PROBE, "ssl": "ok"}


def _excluded(relative: Path) -> bool:
    if any(part in EXCLUDED_DIR_NAMES for part in relative.parts):
        return True
    if relative.name in EXCLUDED_FILE_NAMES:
        return True
    suffix = relative.suffix.lower()
    if suffix in {".pyc", ".pyo"}:
        return True
    # .exe 只在 Scripts/ 下排除（launcher 内嵌构建机绝对路径）；
    # python.exe / pythonw.exe 等解释器本体必须保留。
    return suffix == ".exe" and "Scripts" in relative.parts


def write_runtime_zip(staging: Path, output: Path, runtime_name: str) -> Path:
    """打可分发 zip：排除 launcher/.exe、缓存与构建机痕迹。"""
    archive_path = output / f"{runtime_name}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(staging.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(staging)
            if _excluded(relative):
                continue
            bundle.write(path, (Path(runtime_name) / relative).as_posix())
    return archive_path


def build(
    output: Path,
    *,
    requirements: Path,
    rust_wheel: Path | None,
    wheelhouse: Path | None,
    python_zip: Path | None,
    skip_selfcheck: bool,
) -> Path:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8")
    version, expected_sha = parse_runtime_constants()
    output.mkdir(parents=True, exist_ok=True)
    # staging 必须短且纯 ASCII：嵌入式 Python 对超长/非 ASCII 构建路径敏感，
    # 产物（zip 内相对布局）才允许用户侧的任意路径。
    staging_parent = Path(tempfile.mkdtemp(prefix="stella-runtime-build-"))
    staging = staging_parent / "rt"
    try:
        zip_path = fetch_python_zip(output, version, expected_sha, python_zip)
        runtime = staging / RUNTIME_DIRNAME
        runtime.mkdir(parents=True)
        with zipfile.ZipFile(zip_path) as bundle:
            bundle.extractall(runtime)
        patch_pth(runtime)
        python_exe = runtime / "python.exe"
        if not python_exe.is_file():
            raise SystemExit(f"解压后缺少 {python_exe}")

        install_dependencies(python_exe, runtime, requirements, wheelhouse)
        strip_launchers(runtime)
        if rust_wheel is not None:
            if not rust_wheel.is_file():
                raise SystemExit(f"--rust-wheel 不存在：{rust_wheel}")
            install_rust_wheel(python_exe, staging, rust_wheel)

        selfcheck: dict[str, object] = {}
        if not skip_selfcheck:
            selfcheck = self_check(python_exe, staging)

        manifest = {
            "schema_version": 1,
            "python_version": version,
            "python_zip_sha256": expected_sha,
            "requirements": str(requirements),
            "rust_wheel": rust_wheel.name if rust_wheel else None,
            "wheelhouse": str(wheelhouse) if wheelhouse else None,
            "self_check": selfcheck,
        }
        (staging / "runtime-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        runtime_name = f"stella-runtime-py{version}-amd64"
        archive = write_runtime_zip(staging, output, runtime_name)
        # 保留未压缩的 staging 副本供搬迁验证（check_windows_runtime.py）
        relocated = output / runtime_name
        if relocated.exists():
            shutil.rmtree(relocated)
        shutil.move(str(staging), str(relocated))
        log(f"完成：{archive}")
        return relocated
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requirements", type=Path,
                        default=REPO_ROOT / "requirements.txt")
    parser.add_argument("--rust-wheel", type=Path,
                        help="随包 Rust wheel（oneclick-rust）")
    parser.add_argument("--wheelhouse", type=Path,
                        help="离线 wheel 仓（--no-index 安装）；缺省走在线源")
    parser.add_argument("--python-zip", type=Path,
                        help="已下载好的嵌入式 Python zip（跳过下载，仍做哈希校验）")
    parser.add_argument("--skip-selfcheck", action="store_true")
    args = parser.parse_args()
    build(
        args.output.resolve(),
        requirements=args.requirements.resolve(),
        rust_wheel=args.rust_wheel.resolve() if args.rust_wheel else None,
        wheelhouse=args.wheelhouse.resolve() if args.wheelhouse else None,
        python_zip=args.python_zip.resolve() if args.python_zip else None,
        skip_selfcheck=args.skip_selfcheck,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
