# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""deploy.nsis_bootstrap_helper 的单元测试。

模块只依赖标准库（在嵌入式 Python 未装 pip 的阶段执行），测试同样只覆盖
纯逻辑与命令编排——真实 pip/bootstrap 由安装器在用户机器上执行。
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "nsis_bootstrap_helper.py"
_spec = importlib.util.spec_from_file_location("nsis_bootstrap_helper", MODULE_PATH)
helper = importlib.util.module_from_spec(_spec)
sys.modules["nsis_bootstrap_helper"] = helper
_spec.loader.exec_module(helper)


def test_patch_pth_uncomments_site_and_adds_root(tmp_path):
    """嵌入式 ._pth 默认关 site 且无项目根；补丁后两者就位（幂等）。"""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    pth = runtime / "python312._pth"
    pth.write_text(
        "python312.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n",
        encoding="utf-8",
    )

    helper.patch_pth(runtime)
    patched = pth.read_text(encoding="utf-8")
    assert "import site" in patched
    assert "#import site" not in patched
    assert "\n..\n" in patched or patched.endswith("\n..\n")

    helper.patch_pth(runtime)  # 幂等
    patched_again = pth.read_text(encoding="utf-8")
    assert patched_again.count("import site") == 1


def test_write_deps_marker_matches_sha256(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    requirements = tmp_path / "requirements.txt"
    requirements.write_bytes(b"dep==1\ndep2==2\n")

    helper.write_deps_marker(runtime, requirements)

    marker = (runtime / helper.DEPS_MARKER).read_text(encoding="utf-8").strip()
    expected = hashlib.sha256(requirements.read_bytes()).hexdigest().upper()
    assert marker == expected


def test_bootstrap_offline_records_pipeline_in_order(tmp_path, monkeypatch):
    """装载管线按序执行：pth 补丁 → get-pip → 依赖闭包 → 依赖标记 → 组件装载。"""
    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    (install_root / "offline").mkdir()
    (install_root / "offline" / "get-pip.py").write_text("# get-pip", encoding="utf-8")
    (install_root / "offline" / "wheels").mkdir()
    (install_root / "requirements.txt").write_text("dep==1\n", encoding="utf-8")
    (install_root / ".stella-profile").write_text("oneclick-python", encoding="utf-8")
    (install_root / "package-catalog-windows-amd64.json").write_text("{}", encoding="utf-8")
    (runtime / "python312._pth").write_text(
        "python312.zip\n.\n#import site\n", encoding="utf-8"
    )
    # tar 解压后的嵌入式 Python（Windows 形态 = python.exe）
    (runtime / "python.exe").write_bytes(b"MZ")

    recorded: list[list[str]] = []
    monkeypatch.setattr(helper, "_run", lambda cmd, cwd: recorded.append(cmd))

    helper.bootstrap_offline(install_root)

    assert len(recorded) == 3
    assert recorded[0][1].endswith("get-pip.py") and "--no-index" in recorded[0]
    assert "-m" in recorded[1] and "pip" in recorded[1]
    assert recorded[2][:5] == [
        str(runtime / "python.exe"), "-m", "deploy", "bootstrap", "install",
    ]
    assert "--profile" in recorded[2] and "oneclick-python" in recorded[2]
    # 依赖标记已写（GUI 首启据此跳过装载）
    assert (runtime / helper.DEPS_MARKER).is_file()


def test_main_rejects_when_offline_manifest_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["nsis_bootstrap_helper.py", str(tmp_path)])
    assert helper.main([str(tmp_path)]) == 2
