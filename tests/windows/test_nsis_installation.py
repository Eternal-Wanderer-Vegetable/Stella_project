# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""tests/windows/test_nsis_installation 的最小触发器。

真正的最终 EXE 安装验收由 `scripts/test_nsis_install.ps1` 在一次性
Windows 环境（CI install-test 作业或专用测试机）执行。设置
``STELLA_INSTALL_TEST_EXE``（安装器路径）与可选
``STELLA_INSTALL_TEST_PAYLOAD``（online/offline，默认 offline）后，
本模块把该 harness 当作被测单元跑一遍并断言报告通过；未设置时跳过——
单元测试绝不默认在开发者机器上安装/卸载全局组件。

注意：本模块刻意不依赖全局 conftest 的应用夹具（浏览器禁用/空间隔离
对本测试无意义）；安装验收必须针对真实安装树，而不是测试替身。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HARNESS = REPO_ROOT / "scripts" / "test_nsis_install.ps1"

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native matrix")


def _pwsh() -> str | None:
    for candidate in ("pwsh", "powershell"):
        try:
            probe = subprocess.run(
                [candidate, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return candidate
    return None


def test_final_installer_passes_acceptance_when_requested(tmp_path):
    exe = os.environ.get("STELLA_INSTALL_TEST_EXE", "").strip()
    if not exe:
        pytest.skip(
            "未设置 STELLA_INSTALL_TEST_EXE；最终安装验收只在 CI install-test "
            "作业或显式指定的测试环境执行"
        )
    shell = _pwsh()
    if shell is None:
        pytest.skip("本机没有 pwsh/powershell 可用")
    payload = os.environ.get("STELLA_INSTALL_TEST_PAYLOAD", "offline").strip()
    profile = os.environ.get("STELLA_INSTALL_TEST_PROFILE", "").strip()
    report_dir = tmp_path / "install-report"
    command = [
        shell, "-NoProfile", "-File", str(HARNESS),
        "-InstallerPath", exe,
        "-ExpectedPayloadMode", payload,
        "-ReportDir", str(report_dir),
    ]
    if profile:
        command += ["-ExpectedProfile", profile]
    result = subprocess.run(command, timeout=4200)
    assert result.returncode == 0, "最终 EXE 安装验收失败，详见 harness 输出"
    report = json.loads(
        (report_dir / "install-test-report.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "pass"
    assert report["exit_code"] == 0
