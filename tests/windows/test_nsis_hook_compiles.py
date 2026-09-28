# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""NSIS 钩子的真实编译门禁（WP08/S09）。

installer-hooks.nsh 的语法错误（Goto/label 解析、寄存器笔误、LogicLib
条件拼写）只有 makensis 真编译才能抓出来——源码级断言不够。本测试用
Tauri 自带的 NSIS（%LOCALAPPDATA%/tauri/NSIS）把两个钩子宏按模板方式
展开编译；没有该工具链时跳过（CI install-test 作业上有）。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS = REPO_ROOT / "desktop" / "src-tauri" / "installer-hooks.nsh"

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows NSIS toolchain")

GATE_NSI = """\
; Hook compile gate: expands both hook macros exactly as the Tauri template would.
Unicode true
Name "stella-hook-compile-gate"
OutFile "hook-compile-gate.exe"
InstallDir "C:\\stella-hook-compile-gate"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "{hooks}"
Section "main"
  !insertmacro NSIS_HOOK_PREINSTALL
  !insertmacro NSIS_HOOK_POSTINSTALL
SectionEnd
"""


def _makensis() -> Path | None:
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "tauri" / "NSIS" / "makensis.exe"
    return candidate if candidate.is_file() else None


def test_hook_macros_compile_with_real_makensis(tmp_path):
    makensis = _makensis()
    if makensis is None:
        pytest.skip("本机没有 Tauri NSIS（%LOCALAPPDATA%/tauri/NSIS）；CI install-test 作业覆盖")
    gate = tmp_path / "hook-compile-gate.nsi"
    gate.write_text(GATE_NSI.replace("{hooks}", str(HOOKS)), encoding="utf-8")
    result = subprocess.run(
        [str(makensis), "-V2", str(gate)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"installer-hooks.nsh 编译失败：\n{result.stdout}\n{result.stderr}"
    )
    assert (tmp_path / "hook-compile-gate.exe").is_file()
