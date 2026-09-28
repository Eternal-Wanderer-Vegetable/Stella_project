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
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def _write_payload_manifest(offline_dir):
    """给种子负载写 v2 MANIFEST（按文件位置推断用途），供装载校验。"""
    import json

    from deploy import offline_payload as op

    purposes = {}
    for path in sorted(offline_dir.rglob("*")):
        if not path.is_file() or path.name == "MANIFEST.json":
            continue
        rel = path.relative_to(offline_dir).as_posix()
        if rel == "get-pip.py":
            purpose = "pip-bootstrap"
        elif rel.startswith("wheels/"):
            purpose = "dependency"
        elif rel.startswith("packages/"):
            purpose = "component"
        else:
            purpose = "metadata"
        purposes[rel] = purpose
    manifest = op.build_manifest(offline_dir, purposes)
    (offline_dir / "MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def test_bootstrap_offline_records_pipeline_in_order(tmp_path, monkeypatch):
    """装载管线按序执行：pth 补丁 → get-pip → 依赖闭包 → 依赖标记 →
    profile 组件标记 → 组件装载。"""
    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    (install_root / "offline").mkdir()
    (install_root / "offline" / "get-pip.py").write_text("# get-pip", encoding="utf-8")
    (install_root / "offline" / "wheels").mkdir()
    (install_root / "requirements.txt").write_text("dep==1\n", encoding="utf-8")
    (install_root / ".stella-profile").write_text("oneclick-python", encoding="utf-8")
    (install_root / "package-catalog-windows-amd64.json").write_text("{}", encoding="utf-8")
    _write_payload_manifest(install_root / "offline")
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
    # get-pip 必须带 --find-links 指向随包 wheels（--no-index 下 pip 本体
    # 只能从那里解析），且安装期禁止交互
    assert "--find-links" in recorded[0] and "--no-input" in recorded[0]
    assert "-m" in recorded[1] and "pip" in recorded[1]
    assert "--disable-pip-version-check" in recorded[1]
    assert recorded[2][:5] == [
        str(runtime / "python.exe"), "-m", "deploy", "bootstrap", "install",
    ]
    assert "--profile" in recorded[2] and "oneclick-python" in recorded[2]
    # 依赖标记已写（GUI 首启据此跳过装载）
    assert (runtime / helper.DEPS_MARKER).is_file()
    # 产品组件就绪标记已写（catalog SHA256，与 GUI 同口径）——GUI 首启
    # 据此跳过组件装载（F03 的另一半）
    marker = runtime / f"{helper.PROFILE_MARKER_PREFIX}oneclick-python"
    expected = hashlib.sha256(b"{}").hexdigest().upper()
    assert marker.read_text(encoding="utf-8").strip() == expected


def _seed_offline_tree(tmp_path, profile="oneclick-python"):
    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    offline = install_root / "offline"
    offline.mkdir(parents=True, exist_ok=True)
    (offline / "get-pip.py").write_text("# get-pip", encoding="utf-8")
    (offline / "wheels").mkdir(exist_ok=True)
    (install_root / "requirements.txt").write_text("dep==1\n", encoding="utf-8")
    (install_root / ".stella-profile").write_text(profile, encoding="utf-8")
    (install_root / "package-catalog-windows-amd64.json").write_text(
        "{}", encoding="utf-8"
    )
    (runtime / "python.exe").write_bytes(b"MZ")
    _write_payload_manifest(install_root / "offline")
    return install_root


def _seed_rust_wheel(install_root, name="stella_memory_rust-1.0-cp312-cp312-win_amd64.whl"):
    wheel = install_root / "wheels" / name
    wheel.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel, "w") as bundle:
        bundle.writestr("memory_rust/__init__.py", "")
    return wheel


def test_bootstrap_offline_installs_rust_wheel_before_components(tmp_path, monkeypatch):
    """oneclick-rust：随包 wheel 原地解包 → 扩展导入自检 → 写 .stella-rust-ready。"""
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-rust")
    wheel = _seed_rust_wheel(install_root)
    recorded: list[list[str]] = []
    monkeypatch.setattr(helper, "_run", lambda cmd, cwd: recorded.append(cmd))

    helper.bootstrap_offline(install_root)

    unzip_at = next(
        index for index, cmd in enumerate(recorded)
        if cmd[1:4] == ["-m", "zipfile", "-e"] and cmd[4] == str(wheel)
    )
    import_check_at = next(
        index for index, cmd in enumerate(recorded)
        if "import memory_rust._native, memory_rust.selector" in cmd
    )
    deploy_at = next(
        index for index, cmd in enumerate(recorded) if "deploy" in cmd
    )
    assert unzip_at < import_check_at < deploy_at, (
        "Rust wheel 必须在组件装载前完成解包与导入自检"
    )
    marker = install_root / "runtime" / helper.RUST_MARKER
    expected = hashlib.sha256(wheel.read_bytes()).hexdigest().upper()
    assert marker.read_text(encoding="utf-8").strip() == expected


def test_bootstrap_offline_rejects_multiple_rust_wheels(tmp_path, monkeypatch):
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-rust")
    _seed_rust_wheel(install_root, "stella_memory_rust-1.0-cp312.whl")
    _seed_rust_wheel(install_root, "stella_memory_rust-2.0-cp312.whl")
    with pytest.raises(SystemExit, match="恰好 1 个"):
        helper.bootstrap_offline(install_root)


def test_bootstrap_offline_requires_rust_wheel_for_rust_profile(tmp_path):
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-rust")
    with pytest.raises(SystemExit, match="缺少随包 Rust wheel"):
        helper.bootstrap_offline(install_root)


def test_bootstrap_offline_rejects_stray_rust_wheel_for_python_profile(tmp_path):
    """python 产物混入 Rust wheel 会让 GUI 误判后端（profile 劫持），必须硬失败。"""
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-python")
    _seed_rust_wheel(install_root)
    with pytest.raises(SystemExit, match="不应包含随包 Rust wheel"):
        helper.bootstrap_offline(install_root)


def test_run_isolates_pip_environment(tmp_path, monkeypatch):
    """pip 子进程必须在受控环境执行：PIP_*/代理变量全部清除。"""
    monkeypatch.setenv("PIP_INDEX_URL", "https://attacker.example/simple")
    monkeypatch.setenv("PIP_CONFIG_FILE", "C:/Users/x/pip/pip.ini")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("PATH", "keep-me")
    captured: dict[str, object] = {}

    def fake_run(cmd, cwd, env=None, **_kwargs):
        captured["env"] = env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    helper._run(["python", "-c", "pass"], tmp_path)

    env = captured["env"]
    for name in ("PIP_INDEX_URL", "PIP_CONFIG_FILE", "HTTPS_PROXY"):
        assert name not in env
    assert env["PATH"] == "keep-me"


def test_markers_are_written_atomically(tmp_path, monkeypatch):
    """标记写入走临时文件 + replace：写入中途被杀不留假 ready。"""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    calls: list[str] = []

    real_replace = Path.replace

    def spy_replace(self, target):
        calls.append(str(target))
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", spy_replace)
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("dep==1\n", encoding="utf-8")
    helper.write_deps_marker(runtime, requirements)

    assert calls, "标记必须经临时文件 replace 落盘"
    assert (runtime / helper.DEPS_MARKER).is_file()


def test_main_rejects_when_offline_manifest_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["nsis_bootstrap_helper.py", str(tmp_path)])
    assert helper.main([str(tmp_path)]) == 2
