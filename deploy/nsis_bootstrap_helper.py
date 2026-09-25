# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""OneClick 离线装载辅助脚本（NSIS 安装钩子的执行体）。

背景（2026-09-25 用户方案）：离线包的全部原料（Python 运行时 / get-pip /
依赖 wheel 闭包 / NapCat / embedding 模型 / llama.cpp 后端）在 NSIS 解压时
就已落盘，过去却把「装载」推迟到 GUI 首启——失败点暴露在反馈最差的阶段，
用户看到的是「后端未运行」和假卡死。本脚本由 NSIS ``POSTINSTALL`` 钩子以
**嵌入式 Python** 执行，在安装阶段一次完成全部装载：

1. 就地补丁 ``runtime/python*._pth``（启用 site、补项目根——嵌入式发行版
   默认关 site，不补丁则 get-pip / pip / deploy 全部 import 失败）；
2. 离线引导 pip（``offline/get-pip.py`` 内嵌完整 pip wheel，``--no-index``
   零网络）；
3. 离线安装依赖闭包（``pip install --no-index --find-links offline/wheels``）；
4. 写依赖就绪标记 ``runtime/.stella-deps-ready``（requirements.txt 的
   SHA256 大写十六进制，与 GUI 侧 ``python.rs`` 的判据逐字节同口径）——
   GUI 首启的 ``prepare_runtime`` 看到标记即跳过已完成的装载；
5. 组件装载：子进程执行 ``python -m deploy bootstrap install --profile …``
   （NapCat / embedding 模型 / llama.cpp 后端，读 offline/packages，
   断点续装，进度直接打进安装器详情区）。

在线变体（安装树无 ``offline/MANIFEST.json``）不调用本脚本：保持 GUI 内
引导下载的原流程。任何一步失败都以非零码退出，NSIS 钩子 Abort，
安装器直接展示失败原因——绝不产出「装好了但坏了」的模糊状态。
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

RUNTIME_DIRNAME = "runtime"
OFFLINE_DIRNAME = "offline"
DEPS_MARKER = ".stella-deps-ready"


def patch_pth(runtime: Path) -> None:
    """就地补丁嵌入式 Python 的 ``python*._pth``。

    嵌入式发行版默认关闭 site 且不含项目根；不补丁则 get-pip、pip、deploy
    的 import 全部失败。与 GUI 侧 ``python.rs`` 的 ``patch_pth`` 同口径：
    ``#import site`` → ``import site``，并确保项目根（``..``）在列。
    """
    for entry in sorted(runtime.glob("python*._pth")):
        text = entry.read_text(encoding="utf-8")
        text = text.replace("#import site", "import site")
        if not any(line.strip() == ".." for line in text.splitlines()):
            if not text.endswith("\n"):
                text += "\n"
            text += "..\n"
        entry.write_text(text, encoding="utf-8")


def write_deps_marker(runtime: Path, requirements: Path) -> None:
    """写依赖就绪标记（requirements.txt 的 SHA256 大写十六进制）。

    与 GUI 侧 ``python.rs`` 的比对口径一致（忽略大小写）；GUI 首启看到
    标记即跳过 pip 装载。
    """
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest().upper()
    (runtime / DEPS_MARKER).write_text(digest + "\n", encoding="utf-8")


def _run(cmd: list[str], cwd: Path) -> None:
    """执行装载命令；输出直通安装器详情区（ExecToLog 捕获）。"""
    result = subprocess.run(cmd, cwd=str(cwd), check=False)
    if result.returncode != 0:
        sys.exit(f"装载步骤失败（退出码 {result.returncode}）：{' '.join(cmd)}")


def bootstrap_offline(install_root: Path) -> None:
    """按序执行离线装载的全部步骤；任一步失败以非零码退出。"""
    runtime = install_root / RUNTIME_DIRNAME
    offline = install_root / OFFLINE_DIRNAME
    python = runtime / "python.exe"
    if not python.is_file():
        sys.exit(f"嵌入式 Python 不存在：{python}")

    # 1) ._pth 补丁（必须最先做：否则 get-pip / pip 的 import 全挂）
    patch_pth(runtime)

    # 2) 离线引导 pip（get-pip.py 内嵌完整 pip wheel）
    _run([str(python), str(offline / "get-pip.py"), "--no-index",
          "--no-warn-script-location"], install_root)

    # 3) 离线安装依赖闭包
    _run([str(python), "-m", "pip", "install", "--no-index",
          "--find-links", str(offline / "wheels"),
          "-r", str(install_root / "requirements.txt"),
          "--no-warn-script-location"], install_root)

    # 4) 依赖就绪标记（GUI 首启的 prepare_runtime 据此跳过装载）
    write_deps_marker(runtime, install_root / "requirements.txt")

    # 5) 组件装载：NapCat / embedding 模型 / llama.cpp 后端。
    #    数据目录解析与 GUI 运行时同源（config.home），指针/目录因此一致。
    profile = (install_root / ".stella-profile").read_text(
        encoding="utf-8"
    ).strip()
    _run([str(python), "-m", "deploy", "bootstrap", "install",
          "--profile", profile,
          "--catalog", str(install_root / "package-catalog-windows-amd64.json")],
         install_root)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法：nsis_bootstrap_helper.py <安装根目录>", file=sys.stderr)
        return 2
    install_root = Path(argv[1]).resolve()
    if not (install_root / "offline" / "MANIFEST.json").is_file():
        print("离线负载缺失（offline/MANIFEST.json）——在线变体不应调用本脚本。",
              file=sys.stderr)
        return 2
    bootstrap_offline(install_root)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
