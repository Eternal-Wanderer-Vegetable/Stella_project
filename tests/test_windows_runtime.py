# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""预组装 runtime（WP07）的构建/排除/搬迁规则测试。

纯逻辑单测默认运行；真正下载 Python zip 并安装依赖的完整构建 +
搬迁验证是重集成，仅当显式设置 ``STELLA_BUILD_RUNTIME=1`` 时执行
（CI 专用作业或开发者手动）——单元测试绝不默认下载 GB 级依赖。
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from scripts.build_windows_runtime import (
    CORE_IMPORT_PROBE,
    _excluded,
    patch_pth,
)
from scripts.check_windows_runtime import RELOCATED_DIRNAME


def test_exclusion_rules_drop_launchers_and_caches():
    assert _excluded(Path("Scripts/pip.exe"))
    assert _excluded(Path("Scripts/fastapi.exe"))
    assert _excluded(Path("foo/__pycache__/bar.cpython-312.pyc"))
    assert _excluded(Path("x.pyc"))
    assert _excluded(Path("Lib/site-packages/pip/__init__.py")) is False
    assert _excluded(Path("python.exe")) is False, (
        "解释器本体绝不能被排除规则误伤"
    )
    assert _excluded(Path("tools/custom.exe")) is False, (
        ".exe 排除只限 Scripts/（pip launcher 的生成位置），其余 .exe 不受影响"
    )
    assert _excluded(Path("python312._pth")) is False


def test_core_import_probe_covers_network_stack():
    assert "ssl" in CORE_IMPORT_PROBE, "网络栈必须在内置探测里（DLL 链接问题早暴露）"
    assert "httpx" in CORE_IMPORT_PROBE and "aiohttp" in CORE_IMPORT_PROBE


def test_patch_pth_matches_install_time_helper(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pth = runtime / "python312._pth"
    pth.write_text("python312.zip\n.\n#import site\n", encoding="utf-8")
    patch_pth(runtime)
    text = pth.read_text(encoding="utf-8")
    assert "import site" in text and "#import site" not in text
    assert "\n..\n" in text or text.endswith("\n..\n"), (
        "runtime 的 ._pth 必须与安装期 helper 同口径：site + 项目根（..）"
    )
    patch_pth(runtime)  # 幂等
    assert pth.read_text(encoding="utf-8").count("import site") == 1


def test_relocation_target_is_hostile_path():
    assert " " in RELOCATED_DIRNAME
    assert any("\u4e00" <= char <= "\u9fff" for char in RELOCATED_DIRNAME), (
        "搬迁目标必须包含中文与空格（T15：搬迁后从外部 cwd 运行）"
    )


def _mini_runtime(tmp_path: Path) -> Path:
    """构造一个最小假 runtime（不装依赖），用于搬迁检查的负路径验证。"""
    runtime = tmp_path / "mini"
    scripts = runtime / "runtime" / "Scripts"
    scripts.mkdir(parents=True)
    (runtime / "runtime" / "python.exe").write_bytes(b"MZ")
    (scripts / "pip.exe").write_bytes(b"MZ")
    return runtime


@pytest.mark.skipif(os.name != "nt", reason="Windows runtime relocation")
def test_relocation_check_rejects_launcher_and_missing_python(tmp_path, capsys):
    from scripts import check_windows_runtime as checker

    mini = _mini_runtime(tmp_path)
    # 带 launcher → 必须失败（launcher 内嵌构建机路径，禁止分发）
    with pytest.raises(SystemExit) as exit_info:
        checker.check(mini)
    assert exit_info.value.code == 1
    assert "launcher" in capsys.readouterr().err

    (mini / "runtime" / "Scripts" / "pip.exe").unlink()
    # 缺 python.exe → 必须失败（且发生在任何执行之前）
    (mini / "runtime" / "python.exe").unlink()
    with pytest.raises(SystemExit) as exit_info:
        checker.check(mini)
    assert exit_info.value.code == 1
    assert "python.exe" in capsys.readouterr().err


def test_runtime_zip_layout_excludes_launchers(tmp_path):
    from scripts.build_windows_runtime import write_runtime_zip

    staging = tmp_path / "staging"
    runtime = staging / "runtime"
    scripts = runtime / "Scripts"
    scripts.mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"MZ")
    (scripts / "pip.exe").write_bytes(b"MZ")
    (runtime / "Lib" / "site-packages" / "httpx" / "__init__.py").parent.mkdir(
        parents=True
    )
    (runtime / "Lib" / "site-packages" / "httpx" / "__init__.py").write_bytes(b"")
    archive = write_runtime_zip(staging, tmp_path, "stella-runtime-test")
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert "stella-runtime-test/runtime/python.exe" in names
    assert not any(name.endswith(".exe") and "Scripts/" in name for name in names), (
        "Scripts launcher 绝不能进可分发产物"
    )
    assert any("site-packages/httpx/__init__.py" in name for name in names)


@pytest.mark.skipif(
    os.environ.get("STELLA_BUILD_RUNTIME", "") != "1",
    reason="完整 runtime 构建（GB 级下载/安装）仅在显式启用时运行",
)
def test_full_build_and_relocation(tmp_path):
    """完整集成：构建 → 搬迁验证（CI 专用作业运行）。"""
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable, str(Path(__file__).parents[1] / "scripts" / "build_windows_runtime.py"),
            "--output", str(tmp_path / "out"),
        ],
        check=True,
    )
    built = next((tmp_path / "out").glob("stella-runtime-py*-amd64"))
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "scripts" / "check_windows_runtime.py"),
            "--runtime-dir", str(built),
        ],
        check=True,
    )
