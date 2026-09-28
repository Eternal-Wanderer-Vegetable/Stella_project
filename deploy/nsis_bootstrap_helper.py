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

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# 安装契约与 helper 同目录（deploy/），NSIS 以裸文件执行本脚本时脚本目录
# 已在 sys.path；经 importlib 按路径加载（如单测）时需要显式补上。
_SELF_DIR = str(Path(__file__).resolve().parent)
if _SELF_DIR not in sys.path:
    sys.path.insert(0, _SELF_DIR)

from install_contract import (
    EXIT_USAGE,
    RELEASE_METADATA_FILENAME,
    InstallOutcome,
    exit_code_for,
    read_payload_mode,
    read_release_metadata,
)
from offline_payload import PayloadError, read_manifest, verify_payload

RUNTIME_DIRNAME = "runtime"
OFFLINE_DIRNAME = "offline"
# 安装会话日志（WP13）：装载期结构化事件流，落在程序树根（安装器写入
# 的目录必然可写）。安装器被关闭后日志仍在，用户无需截图即可定位失败。
SESSION_LOG_FILENAME = ".stella-install-session.jsonl"
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


def cleanup_stale_rust_activation(install_root: Path, profile: str) -> bool:
    """python 产物清除残留的 Rust 激活状态（T12：静默覆盖升级的遗留）。

    静默 /S 升级不卸载旧树：Rust→Python 切换后，旧 `wheels/` wheel 与
    `runtime\\.stella-rust-ready` 标记仍会留在盘上，GUI 的
    `rust_wheel_present` 据此把后端劫持成 Rust。这里按声明 profile 清理
    （装到用户盘上的残留，无法在构建期发现）。注意：runtime 内已解包的
    memory_rust .pyd 不动——后端选择由 wheels/ 与 marker 决定，清掉即可。
    构建期的打包缺陷由 staging 校验（stage 只给 rust profile 拷 wheels/）
    与产品 profile 测试把守，不依赖这条运行期路径。
    """
    if profile == "oneclick-rust":
        return False
    removed = False
    wheel_dir = install_root / WHEELS_DIRNAME
    if wheel_dir.is_dir():
        for wheel in list(wheel_dir.glob(f"{RUST_WHEEL_PREFIX}*.whl")):
            with contextlib.suppress(OSError):
                wheel.unlink()
                removed = True
    marker = install_root / RUNTIME_DIRNAME / RUST_MARKER
    if marker.is_file():
        with contextlib.suppress(OSError):
            marker.unlink()
            removed = True
    return removed


def _append_upgrade_journal(outcome: str, detail: str) -> None:
    """升级 journal（S11a）：与 NSIS 侧 PREINSTALL 的「升级开始」配对。

    写 ``%LOCALAPPDATA%\\Stella\\upgrade-journal.txt``（INSTDIR 之外）；
    失败静默忽略——诊断流绝不阻断安装。
    """
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        return
    payload = {"ts": round(time.time(), 3), "outcome": outcome, "detail": detail[:300]}
    try:
        path = Path(local) / "Stella" / "upgrade-journal.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
            )
    except OSError:
        pass


def _installed_version(install_root: Path) -> str:
    """本包版本（release 元数据；旧包无元数据记 unknown）。"""
    metadata_file = install_root / RELEASE_METADATA_FILENAME
    if not metadata_file.is_file():
        return "unknown"
    metadata = read_release_metadata(install_root) or {}
    version = metadata.get("release_version")
    return str(version) if version else "unknown"


def ensure_rust_wheel(install_root: Path, python: Path, wheel: Path) -> None:
    """就地解包 Rust wheel 并验证扩展可导入（与 GUI ``ensure_rust_wheel`` 同口径）。

    wheel 就是 zip：``pip install --target`` 会先删目标里的同名包目录，把
    memory_rust 的 Python 半边（selector.py 等）一并抹掉；必须原地
    ``zipfile -e`` 解包。导入检查通过后才写 ``.stella-rust-ready``（wheel
    的 SHA256，GUI 据此跳过重装）。
    """
    runtime = python.parent
    _run([str(python), "-m", "zipfile", "-e", str(wheel), "."], install_root,
         install_root=install_root, step="rust-wheel-unpack")
    _run([str(python), "-c", "import memory_rust._native, memory_rust.selector"],
         install_root, install_root=install_root, step="rust-wheel-verify")
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


def _append_session(install_root: Path, event: dict) -> None:
    """追加一条会话事件；日志失败静默忽略，绝不阻断安装。"""
    payload = {"ts": round(time.time(), 3), **event}
    try:
        path = install_root / SESSION_LOG_FILENAME
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
            )
    except OSError:
        pass


# ============================================================
# 数据根显式接入（S10a）：新装默认树外，已有数据根一律不动
# ============================================================

DEFAULT_DATA_DIR_NAME = "StellaData"
# 与 config/home.py 的 LEGACY_MARKERS 同口径（镜像而非 import：helper 必须
# 保持零重依赖，嵌入式 Python 还没有 site-packages）。
LEGACY_DATA_MARKERS = (".env", "memory/agent_memory.db", "deploy.answers.toml")


def data_pointer_path() -> Path:
    """机器级数据根指针文件位置（与 config/home.pointer_path 同口径）。"""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Stella" / "home.txt"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "stella" / "home.txt"


def read_data_pointer() -> Path | None:
    """读指针；不存在/为空/指向不存在的目录都返回 None（home.py 同口径）。"""
    path = data_pointer_path()
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    candidate = Path(text)
    return candidate if candidate.is_dir() else None


def write_data_pointer(home: Path) -> bool:
    """把数据根写进指针文件；失败返回 False（调用方退化为现状默认）。"""
    path = data_pointer_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(home.resolve()) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def resolve_data_root(install_root: Path) -> tuple[Path | None, str]:
    """为离线装载决定数据根；返回（需注入子进程的 STELLA_HOME 或 None, 来源）。

    优先级与 config/home.py 逐条对应（镜像实现，语义一致）：
    环境变量 > 便携 StellaData > 旧布局痕迹 > 已有指针 > 新默认（树外）。
    只有「全新安装」才落新默认并写指针——已有数据根一律不动、不迁移。
    """
    env_home = os.environ.get("STELLA_HOME", "").strip()
    if env_home:
        return None, "env"
    if (install_root / DEFAULT_DATA_DIR_NAME).is_dir():
        return None, "portable"
    if any((install_root / marker).exists() for marker in LEGACY_DATA_MARKERS):
        return None, "legacy"
    if read_data_pointer() is not None:
        return None, "pointer"
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None, "no-localappdata"
    new_home = Path(local) / "Stella" / "Data"
    if not write_data_pointer(new_home):
        # 指针写失败（权限/只读盘）：退化为现状树内默认，不阻断安装。
        return None, "pointer-write-failed"
    return new_home, "new-default"


def _run(cmd: list[str], cwd: Path, *, install_root: Path | None = None,
         step: str = "command", env_extra: dict[str, str] | None = None) -> None:
    """执行装载命令（受控环境）；输出直通安装器详情区（ExecToLog 捕获）。"""
    env = _isolated_env()
    if env_extra:
        env.update(env_extra)
    started = time.monotonic()
    result = subprocess.run(cmd, cwd=str(cwd), check=False, env=env)
    duration = round(time.monotonic() - started, 3)
    if install_root is not None:
        _append_session(
            install_root,
            {
                "stage": "helper_step",
                "step": step,
                "exit_code": result.returncode,
                "duration_s": duration,
            },
        )
    if result.returncode != 0:
        if install_root is not None:
            _append_session(
                install_root,
                {
                    "stage": "helper_failed",
                    "step": step,
                    "exit_code": result.returncode,
                    "duration_s": duration,
                    "detail": " ".join(cmd)[:500],
                },
            )
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
    elif cleanup_stale_rust_activation(install_root, profile):
        # T12：静默覆盖升级留下的旧 Rust wheel/marker 会让 GUI 把后端
        # 劫持成 Rust（本包声明 python）。构建期缺陷由 staging 校验把守，
        # 这里的语义是安装期清理用户盘上的残留。
        rust_wheel = None  # 残留已清除，后续装载不得再引用
        _append_session(
            install_root,
            {
                "stage": "t12_cleanup",
                "detail": "removed stale rust wheel/marker for python profile",
            },
        )

    # 0) 负载全量校验（在使用负载之前，WP05）：MANIFEST 结构 + 逐文件
    #    哈希/大小。任何缺失/损坏都在 pip 步骤之前具名失败——绝不让
    #    --no-index 安装在半路收到「No matching distribution」才暴露。
    _append_session(
        install_root,
        {
            "stage": "helper_start",
            "detail": f"profile={profile} mode={read_payload_mode(install_root)}",
        },
    )
    try:
        verify_payload(offline, read_manifest(offline))
    except PayloadError as exc:
        _append_session(
            install_root,
            {
                "stage": "helper_failed",
                "step": "payload_verify",
                "detail": f"{exc.code}: {exc.message}"[:500],
            },
        )
        sys.exit(f"离线负载校验失败（{exc.code}）：{exc.message}")

    # 1) ._pth 补丁（必须最先做：否则 get-pip / pip 的 import 全挂）
    patch_pth(runtime)

    # 2) 离线引导 pip：get-pip 以 --no-index 运行时，"pip" 需求必须由
    #    --find-links 里的 pip wheel 解析（负载构建时已显式带上 pip）。
    #    --no-input/--disable-pip-version-check：安装期禁止任何交互。
    _run([str(python), str(offline / "get-pip.py"), "--no-index",
          "--find-links", str(wheels), "--no-input",
          "--disable-pip-version-check", "--no-warn-script-location"],
         install_root, install_root=install_root, step="get-pip")

    # 3) 离线安装依赖闭包：只装发布时已构建/校验过的 wheel，绝不现场构建
    #    （离线负载没有也不允许有编译工具链）。
    _run([str(python), "-m", "pip", "install", "--no-index",
          "--find-links", str(wheels), "--no-input",
          "--disable-pip-version-check",
          "-r", str(install_root / "requirements.txt"),
          "--no-warn-script-location"],
         install_root, install_root=install_root, step="pip-install-deps")

    # 4) 依赖就绪标记（GUI 首启的 prepare_runtime 据此跳过装载）
    write_deps_marker(runtime, install_root / "requirements.txt")

    # 5) Rust profile：随包 Rust wheel 的装载与自检必须在 GUI 首启**之前**
    #    完成，否则首启会重复执行安装步骤（F03）。与 GUI 同口径。
    if rust_wheel is not None:
        ensure_rust_wheel(install_root, python, rust_wheel)

    # 6) 产品组件就绪标记：全部本地装载完成后再写，GUI 首启据此跳过组件装载
    #    （只代表组件阶段，不代表整体产品 ready——依赖与组件是两个标记）。
    write_profile_ready_marker(runtime, profile, catalog)

    # 7) 数据根显式接入（S10a）：全新安装默认树外（$LOCALAPPDATA\Stella\Data，
    #    经机器指针接入，config.home 原有解析零改动）；便携/旧布局/已有指针/
    #    环境变量一律沿用，绝不迁移。决策必须先于组件装载——NapCat/模型/
    #    账本/事件流都要落进最终数据根。
    data_root, data_source = resolve_data_root(install_root)
    _append_session(
        install_root,
        {
            "stage": "data_root",
            "detail": f"source={data_source} root={data_root or '(按现有规则解析)'}",
        },
    )
    env_extra = {"STELLA_HOME": str(data_root)} if data_root is not None else None

    # 8) 组件装载：NapCat / embedding 模型 / llama.cpp 后端。
    #    数据目录由上一步显式决定（指针/沿用），与 GUI 运行时同源（config.home）。
    _run([str(python), "-m", "deploy", "bootstrap", "install",
          "--profile", profile,
          "--catalog", str(catalog)],
         install_root,
         install_root=install_root, step="deploy-bootstrap-install",
         env_extra=env_extra)
    _append_session(install_root, {"stage": "helper_done", "step": "all"})
    _append_upgrade_journal(
        "ready",
        f"profile={profile} version={_installed_version(install_root)}",
    )


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

    try:
        bootstrap_offline(install_root)
    except SystemExit:
        # 失败也必须有终态 journal（与 NSIS 侧「升级开始」配对，S11a）
        _append_upgrade_journal(
            "failed",
            f"version={_installed_version(install_root)}（详情见安装目录会话日志）",
        )
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
