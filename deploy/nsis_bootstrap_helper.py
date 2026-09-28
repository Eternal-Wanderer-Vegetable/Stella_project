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
   零网络；``--find-links`` 必须指向随包 wheels，pip 本体从那里解析）；
3. 离线安装依赖闭包（``pip install --no-index --find-links offline/wheels``；
   只装已校验 wheels，绝不现场构建——sdist 已在发布时构建成 wheel）；
4. 写依赖就绪标记 ``runtime/.stella-deps-ready``（requirements.txt 的
   SHA256 大写十六进制，与 GUI 侧 ``python.rs`` 的判据逐字节同口径）；
5. Rust profile：就地解包随包 Rust wheel（``pip --target`` 会先删同名包
   目录、抹掉 memory_rust Python 半边——必须用 ``zipfile -e``），验证
   ``memory_rust._native``/``selector`` 导入后写 ``.stella-rust-ready``
   （与 GUI 侧 ``ensure_rust_wheel`` 同口径）；
6. 写产品组件就绪标记 ``runtime/.stella-profile-ready-<profile>``
   （catalog 文件的 SHA256，与 GUI 侧同口径）——GUI 首启据此跳过组件装载；
7. 组件装载：子进程执行 ``python -m deploy bootstrap install --profile …``
   （NapCat / embedding 模型 / llama.cpp 后端，读 offline/packages，
   断点续装，进度直接打进安装器详情区）。

所有标记原子写入（临时文件 + replace）：装载中途被杀绝不留下「假 ready」。
pip/get-pip 子进程以受控环境执行：清除 PIP_*/代理变量，避免用户机器上的
全局 pip 配置把 ``--no-index`` 的离线解析改道；``--no-input``、
``--disable-pip-version-check`` 保证非交互。

在线变体（负载模式声明为 ``online``）不调用本脚本：保持 GUI 内
引导下载的原流程。任何一步失败都以非零码退出，NSIS 钩子 Abort，
安装器直接展示失败原因。注意：NSIS 的 Abort 只停止安装器，**不会
撤销已落盘的文件/pip 改动**——失败后的半装状态由组件账本
（deploy.bootstrap 的进度记录）如实记录并在重试时复核，而不是宣称
「Abort 即恢复原状」。

定位：本桥保留用于旧包修复。新 runtime 包（CI 预组装）启用后，常规
安装不再执行 pip——不得长期维持三份不同的安装实现。
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# 安装契约与 helper 同目录（deploy/），NSIS 以裸文件执行本脚本时脚本目录
# 已在 sys.path；经 importlib 按路径加载（如单测）时需要显式补上。
_SELF_DIR = str(Path(__file__).resolve().parent)
if _SELF_DIR not in sys.path:
    sys.path.insert(0, _SELF_DIR)

from install_contract import (
    EXIT_USAGE,
    InstallOutcome,
    exit_code_for,
    read_payload_mode,
)

RUNTIME_DIRNAME = "runtime"
OFFLINE_DIRNAME = "offline"
WHEELS_DIRNAME = "wheels"
DEPS_MARKER = ".stella-deps-ready"
RUST_MARKER = ".stella-rust-ready"
PROFILE_MARKER_PREFIX = ".stella-profile-ready-"
PROFILE_MARKER_LEGACY_TEXT = "complete"
RUST_WHEEL_PREFIX = "stella_memory_rust-"
MANIFEST_FILENAME = "MANIFEST.json"
CATALOG_FILENAME = "package-catalog-windows-amd64.json"
PROFILE_FILENAME = ".stella-profile"

# pip 子进程的受控环境：这些变量会改变目标目录/索引/代理/约束，用户机器
# 上的全局配置可能让 --no-index 的离线解析改道或把包装错位置。全部清除
# （与 GUI 侧 run_without_network_config 的 NETWORK_ENV_VARS 同口径，
# 外加 PIP_FIND_LINKS——helper 场景下 find-links 只能来自显式命令行参数）。
ISOLATED_ENV_DELTAS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
    "PIP_PROXY", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL",
    "PIP_TRUSTED_HOST", "PIP_CONFIG_FILE", "PIP_FIND_LINKS",
    "PIP_TARGET", "PIP_PREFIX", "PIP_REQUIRE_VIRTUALENV",
)


def _isolated_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in ISOLATED_ENV_DELTAS:
        env.pop(name, None)
    return env


def _atomic_write_text(path: Path, text: str) -> None:
    """临时文件 + replace：任何一步被杀都不会留下半写的「假 ready」标记。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                     dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write_deps_marker(runtime: Path, requirements: Path) -> None:
    """写依赖就绪标记（requirements.txt 的 SHA256 大写十六进制）。

    与 GUI 侧 ``python.rs`` 的比对口径一致（忽略大小写）；GUI 首启看到
    标记即跳过 pip 装载。
    """
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest().upper()
    _atomic_write_text(runtime / DEPS_MARKER, digest + "\n")


def discover_rust_wheel(install_root: Path) -> Path | None:
    """发现随包 Rust wheel：0 个 → None；多于 1 个 → 硬失败。

    与 GUI 侧 ``rust_wheel`` 同口径（stella_memory_rust- 前缀、唯一性）。
    """
    wheels_dir = install_root / WHEELS_DIRNAME
    if not wheels_dir.is_dir():
        return None
    wheels = sorted(
        path for path in wheels_dir.glob(f"{RUST_WHEEL_PREFIX}*.whl")
        if path.is_file()
    )
    if len(wheels) > 1:
        sys.exit(
            f"随包负载包含 {len(wheels)} 个 {RUST_WHEEL_PREFIX} wheel，期望恰好 1 个"
        )
    return wheels[0] if wheels else None


def ensure_rust_wheel(install_root: Path, python: Path, wheel: Path) -> None:
    """就地解包 Rust wheel 并验证扩展可导入（与 GUI ``ensure_rust_wheel`` 同口径）。

    wheel 就是 zip：``pip install --target`` 会先删目标里的同名包目录，把
    memory_rust 的 Python 半边（selector.py 等）一并抹掉；必须原地
    ``zipfile -e`` 解包。导入检查通过后才写 ``.stella-rust-ready``（wheel
    的 SHA256，GUI 据此跳过重装）。
    """
    runtime = python.parent
    _run([str(python), "-m", "zipfile", "-e", str(wheel), "."], install_root)
    _run([str(python), "-c", "import memory_rust._native, memory_rust.selector"],
         install_root)
    _atomic_write_text(runtime / RUST_MARKER, _sha256_file(wheel) + "\n")


def write_profile_ready_marker(runtime: Path, profile: str, catalog: Path) -> bool:
    """写产品组件就绪标记（catalog SHA256，与 GUI 比对口径一致）。

    返回是否新写（旧包遗留的纯文本 ``complete`` 标记与 catalog 哈希不同，
    会被 GUI 判为未就绪——本函数只在组件装载成功后调用，覆盖它是安全的）。
    """
    marker = runtime / f"{PROFILE_MARKER_PREFIX}{profile}"
    expected = _sha256_file(catalog)
    try:
        if marker.read_text(encoding="utf-8").strip().upper() == expected.upper():
            return False
    except OSError:
        pass
    _atomic_write_text(marker, expected + "\n")
    return True


def _run(cmd: list[str], cwd: Path) -> None:
    """执行装载命令（受控环境）；输出直通安装器详情区（ExecToLog 捕获）。"""
    result = subprocess.run(cmd, cwd=str(cwd), check=False, env=_isolated_env())
    if result.returncode != 0:
        sys.exit(f"装载步骤失败（退出码 {result.returncode}）：{' '.join(cmd)}")


def bootstrap_offline(install_root: Path) -> None:
    """按序执行离线装载的全部步骤；任一步失败以非零码退出。

    前置校验（Python / profile / 随包 wheel 组合）先行：配置缺陷在执行
    任何耗时步骤之前失败，绝不留下半装载状态。
    """
    runtime = install_root / RUNTIME_DIRNAME
    offline = install_root / OFFLINE_DIRNAME
    wheels = offline / WHEELS_DIRNAME
    python = runtime / "python.exe"
    if not python.is_file():
        sys.exit(f"嵌入式 Python 不存在：{python}")

    profile = (install_root / PROFILE_FILENAME).read_text(
        encoding="utf-8"
    ).strip()
    catalog = install_root / CATALOG_FILENAME
    if not catalog.is_file():
        sys.exit(f"随包 catalog 缺失：{catalog}")
    rust_wheel = discover_rust_wheel(install_root)
    if profile == "oneclick-rust":
        if rust_wheel is None:
            sys.exit(
                "oneclick-rust 产物缺少随包 Rust wheel"
                f"（{WHEELS_DIRNAME}/{RUST_WHEEL_PREFIX}*.whl）"
            )
    elif rust_wheel is not None:
        # 非 Rust 产物不应携带 Rust wheel：装上会让 GUI 的 rust_wheel_present
        # 误判成 Rust 后端（profile 切换的劫持路径）。
        sys.exit(f"{profile} 产物不应包含随包 Rust wheel：{rust_wheel}")

    # 1) ._pth 补丁（必须最先做：否则 get-pip / pip 的 import 全挂）
    patch_pth(runtime)

    # 2) 离线引导 pip：get-pip 以 --no-index 运行时，"pip" 需求必须由
    #    --find-links 里的 pip wheel 解析（负载构建时已显式带上 pip）。
    #    --no-input/--disable-pip-version-check：安装期禁止任何交互。
    _run([str(python), str(offline / "get-pip.py"), "--no-index",
          "--find-links", str(wheels), "--no-input",
          "--disable-pip-version-check", "--no-warn-script-location"],
         install_root)

    # 3) 离线安装依赖闭包：只装发布时已构建/校验过的 wheel，绝不现场构建
    #    （离线负载没有也不允许有编译工具链）。
    _run([str(python), "-m", "pip", "install", "--no-index",
          "--find-links", str(wheels), "--no-input",
          "--disable-pip-version-check",
          "-r", str(install_root / "requirements.txt"),
          "--no-warn-script-location"], install_root)

    # 4) 依赖就绪标记（GUI 首启的 prepare_runtime 据此跳过装载）
    write_deps_marker(runtime, install_root / "requirements.txt")

    # 5) Rust profile：随包 Rust wheel 的装载与自检必须在 GUI 首启**之前**
    #    完成，否则首启会重复执行安装步骤（F03）。与 GUI 同口径。
    if rust_wheel is not None:
        ensure_rust_wheel(install_root, python, rust_wheel)

    # 6) 产品组件就绪标记：全部本地装载完成后再写，GUI 首启据此跳过组件装载
    #    （只代表组件阶段，不代表整体产品 ready——依赖与组件是两个标记）。
    write_profile_ready_marker(runtime, profile, catalog)

    # 7) 组件装载：NapCat / embedding 模型 / llama.cpp 后端。
    #    数据目录解析与 GUI 运行时同源（config.home），指针/目录因此一致。
    _run([str(python), "-m", "deploy", "bootstrap", "install",
          "--profile", profile,
          "--catalog", str(catalog)],
         install_root)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法：nsis_bootstrap_helper.py <安装根目录>", file=sys.stderr)
        return EXIT_USAGE
    install_root = Path(argv[1]).resolve()

    # 负载变体按构建期声明判定（安装契约），不再猜 MANIFEST 是否存在：
    # 声明 offline 却缺清单 = 包坏了，必须硬失败；绝不能把它静默降级成
    # 「在线变体」跳过装载，让用户首启时才发现装了一半。
    declared_mode = read_payload_mode(install_root)
    manifest_present = (
        install_root / OFFLINE_DIRNAME / MANIFEST_FILENAME
    ).is_file()
    if declared_mode == "offline":
        if not manifest_present:
            print(
                "安装失败：负载声明为离线，但 offline/MANIFEST.json 缺失——"
                "安装包不完整，请重新获取安装包。",
                file=sys.stderr,
            )
            return exit_code_for(InstallOutcome.FAILED)
    elif declared_mode == "online":
        print(
            "在线变体不应调用本脚本（负载模式声明为 online）。",
            file=sys.stderr,
        )
        return EXIT_USAGE
    elif not manifest_present:
        # 旧包没有模式声明：沿用 MANIFEST 存在性判定。
        print(
            "离线负载缺失（offline/MANIFEST.json）——在线变体不应调用本脚本。",
            file=sys.stderr,
        )
        return EXIT_USAGE

    bootstrap_offline(install_root)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
