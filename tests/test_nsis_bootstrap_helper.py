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
import json
import os
import shutil
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
    monkeypatch.setattr(helper, "_run", lambda cmd, cwd, **_kwargs: recorded.append(cmd))

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
    """oneclick-rust：随包 wheel 原地解包 → 扩展导入自检 → 写 .stella-rust-ready。

    重试实现直接走 subprocess.run，mock 那一层并让每步首试成功。
    """
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-rust")
    wheel = _seed_rust_wheel(install_root)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))  # journal 隔离
    recorded: list[list[str]] = []

    def fake_run(cmd, cwd=None, **_kwargs):
        recorded.append([str(a) for a in cmd])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper.subprocess, "run", fake_run)

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


# ============================================================
# 升级 journal（S11a）
# ============================================================


def test_write_record_command_writes_record_and_gcs(tmp_path, monkeypatch):
    """write-record：写激活记录 + GC 旧树（保留当前+最近一代）。

    搬移后形态：树根位于 <安装目录>\\app\\5.0.0\\resources\\stella。
    """
    fake_local = tmp_path / "la"
    fake_local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
    seeded = _seed_offline_tree(tmp_path, profile="oneclick-python")
    staged = tmp_path / "staged"
    version = "5.0.0"
    tree = staged / "app" / version / "resources" / "stella"
    tree.parent.mkdir(parents=True)
    shutil.move(str(seeded), str(tree))
    (tree / ".stella-version").write_text(version, encoding="utf-8")
    # 旧树两代：4.9.0（最近一代，保留为回滚目标）与 4.8.0（被 GC）
    for old in ("4.9.0", "4.8.0"):
        old_tree = staged / "app" / old / "resources" / "stella"
        old_tree.mkdir(parents=True)
        (old_tree / "bot.py").write_text("", encoding="utf-8")

    code = helper.main(["nsis_bootstrap_helper.py", str(tree), "write-record"])
    assert code == 0
    record = json.loads(
        (fake_local / "Stella" / "active-install.json").read_text(encoding="utf-8")
    )
    assert record["version"] == version
    assert record["path"] == str(tree.resolve())
    remaining = sorted(p.name for p in (staged / "app").iterdir())
    assert remaining == ["4.9.0", "5.0.0"]  # 当前 + 最近一代；4.8.0 已 GC


def test_bootstrap_offline_journals_ready(tmp_path, monkeypatch):
    fake_local = tmp_path / "la"
    fake_local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-python")
    monkeypatch.setattr(
        helper.subprocess, "run",
        lambda cmd, cwd=None, **_kwargs: SimpleNamespace(returncode=0),
    )

    helper.bootstrap_offline(install_root)

    journal = fake_local / "Stella" / "upgrade-journal.txt"
    lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["outcome"] == "ready"
    assert "profile=oneclick-python" in lines[-1]["detail"]


def test_main_journals_failed_and_reraises(tmp_path, monkeypatch):
    fake_local = tmp_path / "la"
    fake_local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-python")
    monkeypatch.setattr(
        helper.subprocess, "run",
        lambda cmd, cwd=None, **_kwargs: SimpleNamespace(returncode=2),
    )

    with pytest.raises(SystemExit):
        helper.main(["nsis_bootstrap_helper.py", str(install_root)])

    journal = fake_local / "Stella" / "upgrade-journal.txt"
    lines = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["outcome"] == "failed"


def test_bootstrap_offline_writes_session_log(tmp_path, monkeypatch):
    """装载期会话日志：步骤级事件 + 终态事件，安装器关闭后仍可取。"""
    fake_local = tmp_path / "la"
    fake_local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(fake_local))  # upgrade-journal 隔离
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-python")
    manifest = install_root / "offline" / "MANIFEST.json"

    # mock subprocess 层（不是 _run），让真实 _run 写出会话事件
    monkeypatch.setattr(
        helper.subprocess, "run",
        lambda cmd, cwd=None, **_kwargs: SimpleNamespace(returncode=0),
    )

    helper.bootstrap_offline(install_root)
    assert manifest.is_file()
    session = install_root / helper.SESSION_LOG_FILENAME
    lines = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
    stages = [line["stage"] for line in lines]
    assert stages[0] == "helper_start"
    assert stages[-1] == "helper_done"
    step_events = [line for line in lines if line["stage"] == "helper_step"]
    step_names = [line["step"] for line in step_events]
    assert step_names[0] == "get-pip"
    assert step_names[-1] == "deploy-bootstrap-install"
    assert all("duration_s" in line and "exit_code" in line for line in step_events)


def test_bootstrap_offline_session_log_records_failure(tmp_path, monkeypatch):
    """装载步骤失败 → 会话日志留下 helper_failed 终态事件。"""
    fake_local = tmp_path / "la"
    fake_local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(fake_local))  # journal 写本目录
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-python")

    def failing_run(cmd, cwd, **_kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(helper.subprocess, "run", failing_run)
    with pytest.raises(SystemExit, match="退出码 2"):
        helper.bootstrap_offline(install_root)
    session = install_root / helper.SESSION_LOG_FILENAME
    lines = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
    failures = [line for line in lines if line["stage"] == "helper_failed"]
    assert failures and failures[-1]["step"] == "get-pip"
    assert failures[-1]["exit_code"] == 2


# ============================================================
# 数据根显式接入（S10a）
# ============================================================


def _isolate_user_dirs(monkeypatch, tmp_path):
    """把 LOCALAPPDATA / STELLA_HOME / XDG_CONFIG_HOME 全部隔离到临时目录。"""
    fake_local = tmp_path / "localappdata"
    fake_local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
    monkeypatch.delenv("STELLA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return fake_local


def test_resolve_data_root_fresh_defaults_out_of_tree(tmp_path, monkeypatch):
    fake_local = _isolate_user_dirs(monkeypatch, tmp_path)
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-python")

    data_root, source = helper.resolve_data_root(install_root)

    assert source == "new-default"
    assert data_root == fake_local / "Stella" / "Data"
    pointer = fake_local / "Stella" / "home.txt"
    assert pointer.is_file()
    assert pointer.read_text(encoding="utf-8").strip() == str(data_root)


def test_resolve_data_root_env_wins_and_never_writes(tmp_path, monkeypatch):
    fake_local = _isolate_user_dirs(monkeypatch, tmp_path)
    monkeypatch.setenv("STELLA_HOME", str(tmp_path / "custom-home"))
    data_root, source = helper.resolve_data_root(tmp_path)
    assert (data_root, source) == (None, "env")
    assert not (fake_local / "Stella" / "home.txt").exists()


def test_resolve_data_root_portable_and_legacy_and_pointer(tmp_path, monkeypatch):
    _isolate_user_dirs(monkeypatch, tmp_path)
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-python")

    # 便携：树内 StellaData 优先于新默认
    (install_root / "StellaData").mkdir()
    assert helper.resolve_data_root(install_root) == (None, "portable")
    (install_root / "StellaData").rmdir()

    # 旧布局痕迹
    (install_root / ".env").write_text("X=1", encoding="utf-8")
    assert helper.resolve_data_root(install_root) == (None, "legacy")
    (install_root / ".env").unlink()

    # 已有指针
    pointer = Path(os.environ["LOCALAPPDATA"]) / "Stella" / "home.txt"
    pointer.parent.mkdir(parents=True)
    existing = tmp_path / "existing-home"
    existing.mkdir()
    pointer.write_text(str(existing) + "\n", encoding="utf-8")
    assert helper.resolve_data_root(install_root) == (None, "pointer")


def test_resolve_data_root_pointer_write_failure_degrades(tmp_path, monkeypatch):
    # LOCALAPPDATA 指向一个文件 → mkdir 必败 → 退化为现状默认，不抛异常
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    monkeypatch.delenv("STELLA_HOME", raising=False)
    data_root, source = helper.resolve_data_root(tmp_path)
    assert (data_root, source) == (None, "pointer-write-failed")


def test_bootstrap_offline_injects_data_root_env_and_logs(tmp_path, monkeypatch):
    fake_local = _isolate_user_dirs(monkeypatch, tmp_path)
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-python")
    captured: dict[str, object] = {}

    def fake_run(cmd, cwd, env=None, **_kwargs):
        captured["cmd"] = cmd
        captured["env"] = env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    helper.bootstrap_offline(install_root)

    expected_root = fake_local / "Stella" / "Data"
    assert captured["env"]["STELLA_HOME"] == str(expected_root)
    session = install_root / helper.SESSION_LOG_FILENAME
    events = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
    data_events = [e for e in events if e["stage"] == "data_root"]
    assert data_events and "source=new-default" in data_events[0]["detail"]


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


def test_bootstrap_offline_cleans_stale_rust_activation(tmp_path, monkeypatch):
    """T12：静默覆盖升级残留的 Rust wheel/marker 必须被清理（python 声明）。"""
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-python")
    wheel = _seed_rust_wheel(install_root)
    marker = install_root / "runtime" / helper.RUST_MARKER
    marker.write_text("stale", encoding="utf-8")
    monkeypatch.setattr(
        helper.subprocess, "run",
        lambda cmd, cwd=None, **_kwargs: SimpleNamespace(returncode=0),
    )

    helper.bootstrap_offline(install_root)

    assert not wheel.exists(), "残留 Rust wheel 必须被清理（GUI 后端劫持路径）"
    assert not marker.exists(), "残留 .stella-rust-ready 必须被清理"
    session = (install_root / helper.SESSION_LOG_FILENAME).read_text(encoding="utf-8")
    assert "t12_cleanup" in session


def test_rust_profile_never_triggers_t12_cleanup(tmp_path):
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-rust")
    assert helper.cleanup_stale_rust_activation(install_root, "oneclick-rust") is False


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


def test_rust_wheel_steps_retry_transient_failures(tmp_path, monkeypatch):
    """解包/导入瞬态失败（Defender 锁）→ 有界重试后成功，不留假失败。"""
    fake_local = tmp_path / "la"
    fake_local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-rust")
    wheel = _seed_rust_wheel(install_root)
    sleeps: list[float] = []
    monkeypatch.setattr(helper.time, "sleep", lambda s: sleeps.append(s))
    attempts: dict[str, int] = {"unpack": 0, "verify": 0}

    def flaky_run(cmd, cwd=None, **_kwargs):
        cmd_str = " ".join(str(a) for a in cmd)
        if "zipfile" in cmd_str:
            attempts["unpack"] += 1
            # 解包首试失败 → 重试成功
            return SimpleNamespace(returncode=1 if attempts["unpack"] == 1 else 0)
        attempts["verify"] += 1
        # 导入前两试失败 → 第三次成功
        return SimpleNamespace(returncode=0 if attempts["verify"] >= 3 else 1)

    monkeypatch.setattr(helper.subprocess, "run", flaky_run)
    helper.ensure_rust_wheel(install_root, install_root / "runtime" / "python.exe", wheel)
    marker = install_root / "runtime" / helper.RUST_MARKER
    assert marker.is_file(), "重试成功后必须写 ready 标记"
    session = (install_root / helper.SESSION_LOG_FILENAME).read_text(encoding="utf-8")
    assert "rust_wheel_retry" in session, "重试必须留痕（会话日志）"
    assert sleeps == [2.0, 2.0, 5.0], f"解包 1 次重试(2s) + 导入 2 次重试(2s/5s)，实际 {sleeps}"


def test_rust_wheel_deterministic_failure_exits_after_retries(tmp_path, monkeypatch):
    """确定性失败（架构不匹配等）：退避耗尽 → 具名失败退出。"""
    fake_local = tmp_path / "la"
    fake_local.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(fake_local))
    install_root = _seed_offline_tree(tmp_path, profile="oneclick-rust")
    wheel = _seed_rust_wheel(install_root)
    monkeypatch.setattr(helper.time, "sleep", lambda _s: None)
    monkeypatch.setattr(
        helper.subprocess, "run",
        lambda cmd, cwd=None, **_kwargs: SimpleNamespace(returncode=1),
    )
    with pytest.raises(SystemExit, match="重试 3 次仍失败"):
        helper.ensure_rust_wheel(
            install_root, install_root / "runtime" / "python.exe", wheel
        )
    session = (install_root / helper.SESSION_LOG_FILENAME).read_text(encoding="utf-8")
    assert session.count("rust_wheel_attempt_failed") == 3, "每次失败尝试都要留痕"
