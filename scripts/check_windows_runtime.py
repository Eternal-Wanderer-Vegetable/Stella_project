#!/usr/bin/env python3
"""Relocation verification for the pre-assembled Windows runtime (WP07).

A venv copy proves nothing: dynamic DLL loading, ._pth relative paths and
console launchers only break once the tree moves to a real install
location. This checker copies the built runtime to a hostile target path
(Chinese characters + spaces by default), runs the interpreter from an
unrelated cwd with PYTHONPATH cleared, and requires:

  * stdlib + network stack to initialize;
  * the key third-party imports to resolve from the moved site-packages;
  * the Rust memory extension to import when the runtime carries it;
  * NO console-script .exe to be present (launchers embed absolute build
    paths - startup must go through ``python -m``).

Usage:
    python scripts/check_windows_runtime.py --runtime-dir dist/stella-runtime-py3.12.10-amd64
Exit code 0 = relocation-safe; non-zero = the runtime is not portable.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.build_windows_runtime import (
    CORE_IMPORT_PROBE,
    RUNTIME_DIRNAME,
)

RELOCATED_DIRNAME = "Stella 搬迁测试 目录"
EXTRA_PROBES = [
    # memory_rust 存在时才检查（在探测列表里单独判）
    ("memory_rust", "import memory_rust._native, memory_rust.selector"),
]


def fail(message: str) -> None:
    print(f"[relocation] FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def run_from(python: Path, cwd: Path, code: str) -> None:
    result = subprocess.run(
        [str(python), "-c", code],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        env=_clean_env(),
    )
    if result.returncode != 0:
        fail(f"自检失败（退出码 {result.returncode}）：{code}\n{result.stdout}\n{result.stderr}")


def _clean_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    # 搬迁的铁律：不允许任何检出路径通过 PYTHONPATH 泄漏进解释器
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def check(runtime_dir: Path, *, keep_target: bool = False) -> int:
    runtime_dir = runtime_dir.resolve()
    python = runtime_dir / RUNTIME_DIRNAME / "python.exe"
    if not python.is_file():
        fail(f"runtime 目录缺少 {python}")

    # launcher 禁令最先检查（任何执行之前）：Scripts/*.exe 内嵌构建机
    # 绝对路径，搬迁即死，必须在搬运前就拒绝。构建期 strip_launchers
    # 应已删除它们；这里发现即拒绝。
    for script in (runtime_dir / RUNTIME_DIRNAME / "Scripts").glob("*.exe"):
        fail(f"runtime 携带 launcher {script.name}（内嵌构建机路径，禁止分发）")

    # 拷贝（而非移动）到中文+空格路径：模拟「安装到任意目标盘/目录」
    target = Path(tempfile.mkdtemp(prefix="stella-relocate-")) / RELOCATED_DIRNAME
    print(f"[relocation] 复制到 {target} …")
    shutil.copytree(runtime_dir, target)
    moved_python = target / RUNTIME_DIRNAME / "python.exe"
    external_cwd = Path(tempfile.mkdtemp(prefix="stella-relocate-cwd-"))

    try:
        # 1. 基本解释器 + ssl 栈（初始化，不只 import）
        run_from(moved_python, external_cwd,
                 "import ssl, sys; ssl.create_default_context(); print(sys.executable)")
        # 2. 关键第三方导入（从搬迁后的 site-packages 解析）
        probe = ";".join(f"import {module}" for module in CORE_IMPORT_PROBE)
        run_from(moved_python, external_cwd, probe)
        # 3. Rust 扩展（负载带 memory_rust 时）
        if (target / RUNTIME_DIRNAME / "memory_rust").is_dir():
            run_from(moved_python, external_cwd,
                     "import memory_rust._native, memory_rust.selector")
            print("[relocation] Rust 扩展搬迁后导入通过")
        print("[relocation] 全部搬迁检查通过")
        return 0
    finally:
        if not keep_target:
            shutil.rmtree(target.parent, ignore_errors=True)
            shutil.rmtree(external_cwd, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runtime-dir", type=Path, required=True,
                        help="build_windows_runtime.py 产出的 runtime 目录")
    parser.add_argument("--keep-target", action="store_true",
                        help="保留搬迁目标目录（调试失败现场）")
    args = parser.parse_args()
    return check(args.runtime_dir.resolve(), keep_target=args.keep_target)


if __name__ == "__main__":
    sys.exit(main())
