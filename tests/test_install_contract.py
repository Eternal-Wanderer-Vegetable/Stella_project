# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""安装契约（deploy/install_contract）与其消费方的行为测试。

覆盖 S01/WP01：
- outcome → 退出码稳定映射；
- 负载模式声明（.stella-payload-mode）的写入与判定；
- staging 写 release 元数据（版本 / build_id / 运行时指纹 / catalog 摘要）；
- helper / CLI 的契约退出码；
- CI release 工作流的版本统一。

F03/F04/F07/F09/F13 是计划的已知缺陷复现用例：断言的是**目标行为**，
当前实现尚不满足，因此标记 xfail(strict=False)——对应修复落地后这些
用例转为 XPASS，届时应移除标记使其成为常规回归。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import sys
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from deploy import install_contract
from deploy.install_contract import InstallOutcome

REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "deploy" / "nsis_bootstrap_helper.py"
HOOK_PATH = REPO_ROOT / "desktop" / "src-tauri" / "installer-hooks.nsh"
GUI_PYTHON_RS = REPO_ROOT / "desktop" / "src-tauri" / "src" / "python.rs"

import importlib.util


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


def _load_helper():
    spec = importlib.util.spec_from_file_location("nsis_bootstrap_helper", HELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["nsis_bootstrap_helper"] = module
    spec.loader.exec_module(module)
    return module


# ============================================================
# 契约本体
# ============================================================


def test_outcome_exit_code_mapping_is_stable():
    """退出码是跨 NSIS/CLI/GUI 的公共接口，值一经发布不得变更。"""
    assert install_contract.OUTCOME_EXIT_CODES == {
        InstallOutcome.READY: 0,
        InstallOutcome.FAILED: 1,
        InstallOutcome.REBOOT_REQUIRED: 3,
        InstallOutcome.CANCELLED: 4,
        InstallOutcome.INTERRUPTED: 5,
        InstallOutcome.REPAIR_REQUIRED: 6,
    }
    assert install_contract.EXIT_USAGE == 2


def test_payload_mode_roundtrip(tmp_path):
    mode_path = install_contract.write_payload_mode(tmp_path, "offline")
    assert mode_path.name == ".stella-payload-mode"
    assert install_contract.read_payload_mode(tmp_path) == "offline"
    install_contract.write_payload_mode(tmp_path, "online")
    assert install_contract.read_payload_mode(tmp_path) == "online"
    with pytest.raises(ValueError):
        install_contract.write_payload_mode(tmp_path, "sideload")
    # 旧包 / 损坏声明 → None（调用方按兼容路径处理）
    assert install_contract.read_payload_mode(tmp_path / "absent") is None
    (tmp_path / ".stella-payload-mode").write_text("bogus\n", encoding="utf-8")
    assert install_contract.read_payload_mode(tmp_path) is None


def test_release_metadata_roundtrip(tmp_path):
    install_contract.write_release_metadata(
        tmp_path, {"schema_version": 1, "release_version": "5.1.2"}
    )
    payload = install_contract.read_release_metadata(tmp_path)
    assert payload == {"schema_version": 1, "release_version": "5.1.2"}
    assert install_contract.read_release_metadata(tmp_path / "absent") is None
    (tmp_path / ".stella-release-metadata.json").write_text("{broken", encoding="utf-8")
    assert install_contract.read_release_metadata(tmp_path) is None


# ============================================================
# staging：负载模式声明 + release 元数据
# ============================================================

_PY_RS_CONSTANTS = (
    "const PY_VER: &str = \"3.12.10\";\n"
    "const PY_SHA256: &str =\n"
    "        \"4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3\";\n"
)


def _source_tree(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    for relative in (
        "bot.py",
        "deploy/nsis_bootstrap_helper.py",
        "requirements.txt",
        "pyproject.toml",
        "LICENSE",
        "README.md",
        ".env.example",
        "start.bat",
        "doctor.bat",
        "stop.bat",
        "README-快速开始.txt",
        "runtime-manager/schemas/runtime-manifest.schema.json",
        "runtime-manager/schemas/runtime-state.schema.json",
        "runtime-manager/schemas/package-catalog.schema.json",
        "runtime-manager/schemas/package-registry.schema.json",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    for directory in (
        "astrbot_compat", "capability", "config", "core", "deploy",
        "extensions", "memory", "system_prompts", "runtime-manager",
        "stella_project", "knowledge", "skills", "assets", "webui",
        "desktop",
    ):
        path = source / directory / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    from deploy.profiles import PROFILE_IDS

    for profile_id in PROFILE_IDS:
        path = source / "release_assets" / "product-profiles" / f"{profile_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    dist = source / "webui" / "dist" / "index.html"
    dist.parent.mkdir(parents=True, exist_ok=True)
    dist.write_text("panel", encoding="utf-8")
    # 两份壳的 python.rs 常量（构建期指纹一致性校验的输入）
    for shell in ("desktop", "stella-installer"):
        path = source / shell / "src-tauri" / "src" / "python.rs"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_PY_RS_CONSTANTS, encoding="utf-8")
    return source


def _offline_payload(tmp_path: Path, *, with_manifest: bool = True) -> Path:
    payload = tmp_path / "payload"
    (payload / "packages").mkdir(parents=True, exist_ok=True)
    (payload / "packages" / "llama-cpu.zip").write_bytes(b"zip")
    if with_manifest:
        (payload / "MANIFEST.json").write_text(
            json.dumps({"schema_version": 1, "files": {}}), encoding="utf-8"
        )
    return payload


def test_stage_writes_online_payload_mode(tmp_path):
    from scripts.build_release_package import stage_installer_resources

    source = _source_tree(tmp_path)
    output = tmp_path / "resources"
    stage_installer_resources(source, output, "oneclick-python")
    assert install_contract.read_payload_mode(output) == "online"


def test_stage_offline_requires_manifest_and_declares_mode(tmp_path):
    from scripts.build_release_package import stage_installer_resources

    source = _source_tree(tmp_path)
    output = tmp_path / "resources"
    with pytest.raises(FileNotFoundError, match="MANIFEST"):
        stage_installer_resources(
            source, output, "oneclick-python",
            offline_payload=_offline_payload(tmp_path, with_manifest=False),
        )
    # 构建失败不留下半成品声明
    assert not (output / install_contract.PAYLOAD_MODE_FILENAME).exists()

    stage_installer_resources(
        source, output, "oneclick-python",
        offline_payload=_offline_payload(tmp_path),
    )
    assert install_contract.read_payload_mode(output) == "offline"
    assert (output / "offline" / "MANIFEST.json").is_file()


def test_stage_writes_release_metadata_with_runtime_fingerprint(tmp_path):
    from scripts.build_release_package import stage_installer_resources

    source = _source_tree(tmp_path)
    catalog = source / "package-catalog-windows-amd64.json"
    catalog.write_text('{"schema_version": 1}', encoding="utf-8")
    output = tmp_path / "resources"
    stage_installer_resources(
        source, output, "oneclick-rust",
        offline_payload=_offline_payload(tmp_path),
        release_version="5.1.2",
        build_id="run-42-1",
    )
    metadata = install_contract.read_release_metadata(output)
    assert metadata["schema_version"] == 1
    assert metadata["release_version"] == "5.1.2"
    assert metadata["build_id"] == "run-42-1"
    assert metadata["profile"] == "oneclick-rust"
    assert metadata["payload_mode"] == "offline"
    assert metadata["arch"] == "windows-amd64"
    assert metadata["runtime"]["python_version"] == "3.12.10"
    assert metadata["runtime"]["python_zip_sha256"] == (
        "4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3"
    )
    assert metadata["catalog_sha256"] == hashlib.sha256(
        catalog.read_bytes()
    ).hexdigest()


def test_stage_rejects_runtime_fingerprint_drift_between_shells(tmp_path):
    from scripts.build_release_package import stage_installer_resources

    source = _source_tree(tmp_path)
    drifted = source / "stella-installer" / "src-tauri" / "src" / "python.rs"
    drifted.write_text(
        _PY_RS_CONSTANTS.replace("4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3", "0" * 64),
        encoding="utf-8",
    )
    output = tmp_path / "resources"
    with pytest.raises(ValueError, match="运行时常量不一致"):
        stage_installer_resources(
            source, output, "oneclick-python", release_version="5.1.2"
        )


# ============================================================
# helper：按声明判定负载变体
# ============================================================


def test_helper_hard_fails_when_offline_declared_but_payload_missing(tmp_path):
    helper = _load_helper()
    install_contract.write_payload_mode(tmp_path, "offline")
    assert helper.main(["nsis_bootstrap_helper.py", str(tmp_path)]) == (
        install_contract.exit_code_for(InstallOutcome.FAILED)
    )


def test_helper_rejects_invocation_on_online_variant(tmp_path):
    helper = _load_helper()
    install_contract.write_payload_mode(tmp_path, "online")
    assert helper.main(["nsis_bootstrap_helper.py", str(tmp_path)]) == (
        install_contract.EXIT_USAGE
    )


def test_helper_legacy_packages_still_gate_on_manifest(tmp_path, monkeypatch):
    helper = _load_helper()
    # 无模式声明的旧包：缺 MANIFEST → 拒绝（沿用历史行为）
    assert helper.main(["nsis_bootstrap_helper.py", str(tmp_path)]) == (
        install_contract.EXIT_USAGE
    )
    # 有声明且负载齐备 → 正常执行装载管线
    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    (install_root / "offline").mkdir()
    (install_root / "offline" / "get-pip.py").write_text("# get-pip", encoding="utf-8")
    (install_root / "offline" / "wheels").mkdir()
    (install_root / "requirements.txt").write_text("dep==1\n", encoding="utf-8")
    (install_root / ".stella-profile").write_text("oneclick-python", encoding="utf-8")
    (install_root / "package-catalog-windows-amd64.json").write_text(
        "{}", encoding="utf-8"
    )
    (runtime / "python.exe").write_bytes(b"MZ")
    _write_payload_manifest(install_root / "offline")
    install_contract.write_payload_mode(install_root, "offline")
    monkeypatch.setattr(helper, "_run", lambda cmd, cwd, **_kwargs: None)
    assert helper.main(["nsis_bootstrap_helper.py", str(install_root)]) == 0


# ============================================================
# CLI：bootstrap 命令的契约退出码
# ============================================================


def _run_cmd_bootstrap(monkeypatch, install_result=None, exc=None):
    from deploy import __main__ as deploy_main
    from deploy import bootstrap

    if exc is not None:
        def fake_install(*_args, **_kwargs):
            raise exc
    else:
        def fake_install(*_args, **_kwargs):
            return install_result

    monkeypatch.setattr(
        bootstrap, "install_profile",
        fake_install,
    )
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = deploy_main._cmd_bootstrap(
            argparse.Namespace(
                profile="oneclick-python", catalog=None,
                allow_online_fallback=False,
            )
        )
    return code, buffer.getvalue()


def test_cli_bootstrap_success_maps_to_ready_exit_zero(monkeypatch):
    code, output = _run_cmd_bootstrap(
        monkeypatch, install_result={"ok": True, "profile": "oneclick-python",
                                     "state": "complete", "installed": []}
    )
    assert code == install_contract.exit_code_for(InstallOutcome.READY)
    assert json.loads(output)["outcome"] == "ready"


def test_cli_bootstrap_error_maps_to_failed_exit_one(monkeypatch):
    from deploy.bootstrap import BootstrapError

    code, output = _run_cmd_bootstrap(
        monkeypatch, exc=BootstrapError("download_failed", "网络不可用")
    )
    assert code == install_contract.exit_code_for(InstallOutcome.FAILED)
    payload = json.loads(output)
    assert payload["outcome"] == "failed"
    assert payload["error"]["code"] == "download_failed"


def test_cli_bootstrap_unexpected_exception_still_has_terminal_state(monkeypatch):
    """非 BootstrapError 的意外异常也必须有 failed 终态与稳定退出码。"""
    code, output = _run_cmd_bootstrap(monkeypatch, exc=RuntimeError("disk exploded"))
    assert code == install_contract.exit_code_for(InstallOutcome.FAILED)
    payload = json.loads(output)
    assert payload["outcome"] == "failed"
    assert payload["error"]["code"] == "unexpected_error"


# ============================================================
# CI release 工作流：版本统一
# ============================================================


def test_release_workflow_resolves_version_once():
    import yaml

    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    jobs = workflow["jobs"]
    assert "resolve-release" in jobs
    assert jobs["resolve-release"]["outputs"]["version"]
    for job_name in (
        "build-dashboard",
        "build-oneclick-catalog-backend",
        "build-offline-payload",
        "build-installer",
        "build-cli-linux-binary",
        "build-cli-windows-binary",
        "build",
    ):
        assert "resolve-release" in jobs[job_name].get("needs", []), job_name
    # Dashboard marker 必须消费统一解析的版本（F17：手工发布曾取错来源）
    dashboard_steps = json.dumps(jobs["build-dashboard"]["steps"])
    assert "needs.resolve-release.outputs.version" in dashboard_steps
    # 安装资源 staging 必须把版本与 build_id 写入安装契约元数据
    installer_steps = json.dumps(jobs["build-installer"]["steps"])
    assert "--release-version" in installer_steps
    assert "--build-id" in installer_steps
    # WP02：最终 EXE 安装验收是发布硬门禁——构建与发布之间必须有 install-test，
    # 且发布作业必须核对发布字节与验收字节一致。
    assert "install-test" in jobs, "缺少最终 EXE 安装验收作业"
    assert "install-test" in jobs["build"]["needs"], "发布作业不得绕过安装验收"
    build_steps = json.dumps(jobs["build"]["steps"], ensure_ascii=False)
    assert "check_release_hashes.py" in build_steps, (
        "发布作业必须核对安装器字节与验收报告一致"
    )
    # WP14：发布清单 + 发布后回读校验
    assert "build_release_manifest.py" in build_steps, (
        "发布作业必须生成 release-manifest / SHA256SUMS"
    )
    assert "发布后回读校验" in build_steps, (
        "tag 发布后必须从公开地址回读资产并逐字节核对"
    )
    install_test = jobs["install-test"]
    assert install_test["strategy"]["matrix"]["payload"] == ["online", "offline"]
    steps_text = json.dumps(install_test["steps"])
    assert "test_nsis_install.ps1" in steps_text
    assert "ExpectedPayloadMode" in steps_text


# ============================================================
# F03/F04/F07/F09/F13 已知缺陷复现（xfail，修复后转正）
# ============================================================


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _zip(tmp_path: Path, name: str, member: str, content: bytes) -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(member, content)
    return path


def _catalog(tmp_path: Path):
    """与 tests/test_bootstrap.py 同构的最小 catalog（llama + napcat + embedding）。"""
    files = {
        "llama-cpu": _zip(tmp_path, "llama.zip", "llama-server", b"llama"),
        "napcat": _zip(tmp_path, "napcat.zip", "NapCat/napcat.exe", b"napcat"),
        "qwen3-embedding-0.6b": tmp_path / "embedding.gguf",
    }
    files["qwen3-embedding-0.6b"].write_bytes(b"embedding")
    records = [
        {
            "kind": "component", "id": "llama-cpu", "version": "4.0.1",
            "path": "llama-cpu.zip", "checksum": _sha256(files["llama-cpu"]),
            "platform": "windows-amd64", "backend": "cpu",
            "runtime_api": "openai-compatible", "driver_min": "none",
            "abi": "documented", "license": "llama.cpp", "sbom": "llama-sbom.json",
            "source": "https://example.invalid/llama-cpu.zip",
            "artifact": "llama-cpu.zip", "status": "available",
        },
        {
            "kind": "onebot", "id": "napcat", "version": "1.0.0",
            "path": "napcat.zip", "checksum": _sha256(files["napcat"]),
            "platform": "windows-amd64", "license": "NapCat", "sbom": "napcat-sbom.json",
            "source": "https://example.invalid/napcat.zip",
            "artifact": "napcat.zip", "status": "available",
        },
        {
            "kind": "model", "id": "qwen3-embedding-0.6b", "version": "q8_0",
            "path": "models/embedding/Qwen3-Embedding-0.6B-Q8_0.gguf",
            "checksum": _sha256(files["qwen3-embedding-0.6b"]),
            "platform": "windows-amd64", "model_role": "embedding",
            "runtime_api": "llama.cpp-embedding", "license": "Apache-2.0",
            "source": "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf",
            "artifact": "Qwen3-Embedding-0.6B-Q8_0.gguf", "status": "available",
            "size": files["qwen3-embedding-0.6b"].stat().st_size,
            "dimension": 1024, "remote": True,
        },
    ]
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-09-28T00:00:00+00:00",
                "platform": "windows-amd64",
                "profile": "oneclick-python",
                "packages": records,
            }
        ),
        encoding="utf-8",
    )
    return catalog, files


def test_helper_installs_bundled_rust_wheel_for_rust_products(tmp_path, monkeypatch):
    """F03 修复：离线装载必须在 GUI 首启前完成 Rust wheel 装载与自检。"""
    helper = _load_helper()
    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    offline = install_root / "offline"
    offline.mkdir()
    (offline / "get-pip.py").write_text("# get-pip", encoding="utf-8")
    (offline / "wheels").mkdir()
    (install_root / "requirements.txt").write_text("dep==1\n", encoding="utf-8")
    (install_root / ".stella-profile").write_text("oneclick-rust", encoding="utf-8")
    (install_root / "package-catalog-windows-amd64.json").write_text(
        "{}", encoding="utf-8"
    )
    (runtime / "python.exe").write_bytes(b"MZ")
    _write_payload_manifest(offline)
    # 随包 Rust wheel（OneClick Rust 的资源树带 wheels/）
    wheel = install_root / "wheels" / "stella_memory_rust-1.0-cp312-cp312-win_amd64.whl"
    wheel.parent.mkdir()
    with zipfile.ZipFile(wheel, "w") as bundle:
        bundle.writestr("memory_rust/__init__.py", "")
    recorded: list[list[str]] = []
    monkeypatch.setattr(helper, "_run", lambda cmd, cwd, **_kwargs: recorded.append(cmd))

    helper.bootstrap_offline(install_root)

    joined = "\n".join(" ".join(cmd) for cmd in recorded)
    assert "stella_memory_rust" in joined, "离线装载必须就地解包随包 Rust wheel"
    assert "memory_rust._native" in joined, "装载后必须验证 Rust 扩展可导入"


def test_component_failure_lands_in_failed_terminal_state(tmp_path, monkeypatch):
    """F04 修复：NapCatError 也必须落到 failed 终态（归一化为 BootstrapError，
    原始异常保留在异常链上）。"""
    from deploy import bootstrap, napcat

    def fake_download(record, data_root, **_kwargs):
        target = tmp_path / f"{record['id']}.zip"
        with zipfile.ZipFile(target, "w") as bundle:
            bundle.writestr("payload", b"x")
        return target

    monkeypatch.setattr(bootstrap, "_download_record", fake_download)

    def explode(*_args, **_kwargs):
        raise napcat.NapCatError("install_failed", "MSI 爆炸")

    monkeypatch.setattr(bootstrap.acquire, "install_napcat", explode)
    data_root = tmp_path / "data"
    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.install_profile(
            "oneclick-python", data_root, catalog_path=_catalog(tmp_path)[0]
        )
    assert error.value.__cause__ is not None, "原始异常必须保留在异常链上"
    progress = bootstrap.read_progress(data_root)
    assert progress is not None
    assert progress["state"] == "failed", "任何组件失败都必须落到 failed 终态"


def test_failed_run_retry_skips_healthy_components(tmp_path, monkeypatch):
    """F04 修复：failed 重试复核真实状态，健康组件（llama-cpu）直接复用。"""
    from deploy import acquire, bootstrap, napcat, runtime

    catalog, _files = _catalog(tmp_path)
    downloads: list[str] = []

    def fake_download(record, data_root, **_kwargs):
        downloads.append(record["id"])
        target = tmp_path / f"{record['id']}.zip"
        with zipfile.ZipFile(target, "w") as bundle:
            bundle.writestr("payload", b"x")
        return target

    monkeypatch.setattr(bootstrap, "_download_record", fake_download)
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", tmp_path / "gui-runtime")
    monkeypatch.setattr(runtime, "INSTANCE_ID", "contract-retry-test")
    napcat_calls = {"count": 0}

    def flaky_napcat(manifest, root, **kwargs):
        napcat_calls["count"] += 1
        if napcat_calls["count"] == 1:
            raise napcat.NapCatError("install_failed", "MSI 爆炸")
        return manifest

    monkeypatch.setattr(acquire, "install_napcat", flaky_napcat)
    monkeypatch.setattr(
        acquire, "install_default_embedding",
        lambda model, root, **kwargs: {"id": model["id"]},
    )
    data_root = tmp_path / "data"
    with pytest.raises(bootstrap.BootstrapError):
        bootstrap.install_profile("oneclick-python", data_root, catalog_path=catalog)

    downloads.clear()
    result = bootstrap.install_profile(
        "oneclick-python", data_root, catalog_path=catalog
    )
    assert result["state"] == "complete"
    # 已健康的 llama-cpu 不得重新下载（复核通过即复用）
    assert "llama-cpu" not in downloads, (
        f"重试不应重新下载健康组件，实际下载了 {downloads}"
    )


def test_hook_separates_find_handle_from_exit_code():
    """F07 修复：FindFirst 句柄寄存器不得被 nsExec 的 Pop 复用。"""
    text = HOOK_PATH.read_text(encoding="utf-8")
    match = re.search(r"FindFirst \$(\w+) \$\w+", text)
    assert match, "POSTINSTALL 钩子必须用 FindFirst 定位 Python zip"
    handle = match.group(1)
    pops = re.findall(r"Pop \$(\w+)", text)
    assert handle not in pops, (
        f"FindFirst 句柄寄存器 ${handle} 不得被 nsExec 的 Pop 复用"
    )
    assert re.search(rf"FindClose\s+\${handle}\b", text), (
        f"FindClose 必须关闭 FindFirst 的句柄 ${handle}"
    )


def test_hook_requires_exactly_one_python_zip():
    """通配符必须恰好命中一个 zip：0 个或多个都要 Abort，不解压「随便哪个」。"""
    text = HOOK_PATH.read_text(encoding="utf-8")
    assert "FindNext" in text, "必须用 FindNext 检查是否存在第二个匹配"
    assert text.count("Abort") >= 3, "缺 zip / 多 zip / 校验失败都必须 Abort"


def test_uninstall_hooks_preserve_user_data():
    """S10b：卸载钩子只留痕不删数据；journal 必须在 INSTDIR 之外。"""
    text = HOOK_PATH.read_text(encoding="utf-8")
    pre_pos = text.find("!macro NSIS_HOOK_PREUNINSTALL")
    post_pos = text.find("!macro NSIS_HOOK_POSTUNINSTALL")
    assert pre_pos != -1 and post_pos != -1, "PREUNINSTALL/POSTUNINSTALL 钩子必须存在"
    pre_block = text[pre_pos:post_pos]
    assert "uninstall-journal.txt" in pre_block, "卸载必须写外置 journal 留痕"
    assert "home.txt" in pre_block, "journal 必须指明外置数据根指针位置"
    assert "RMDir" not in pre_block and "Delete " not in pre_block, (
        "卸载契约钩子绝不删除任何文件"
    )
    # journal 落在 $LOCALAPPDATA\Stella\（INSTDIR 之外，旧卸载器/重装碰不到）
    assert "$LOCALAPPDATA\\Stella\\" in pre_block


def test_hook_preinstall_runs_expensive_steps_first_gates():
    """WP08：预检查必须在文件释放前完成——路径长度、目标卷空间、可写性。"""
    text = HOOK_PATH.read_text(encoding="utf-8")
    pre_pos = text.find("!macro NSIS_HOOK_PREINSTALL")
    post_pos = text.find("!macro NSIS_HOOK_POSTINSTALL")
    assert pre_pos != -1 and post_pos != -1
    pre_block = text[pre_pos:post_pos]
    # 空间检查用 FileFunc DriveSpace 的 free/GB 语义（对照 NSIS 源码核实）
    assert "/D=F /S=G" in pre_block, (
        "DriveSpace 必须显式取剩余空间（/D=F）并以 GB 为单位（/S=G）"
    )
    assert "STELLA_PREINSTALL_MIN_GB" in pre_block, (
        "空间下限必须是具名 define（保守值，注释说明非精确峰值模型）"
    )
    assert "StrLen" in pre_block and "120" in pre_block, (
        "必须做安装路径长度护栏（深层运行时文件受 MAX_PATH 约束）"
    )
    assert "__stella_wtest" in pre_block, (
        "必须做目标目录可写探测（只读位置在解压前暴露）"
    )
    assert pre_block.count("Abort") >= 3, "每个预检查失败都必须 Abort 并解释"


def test_hook_verifies_python_zip_hash_before_extraction():
    """解压前校验：期望哈希来自构建期文件，certutil+find 系统工具完成校验。"""
    text = HOOK_PATH.read_text(encoding="utf-8")
    hash_check_pos = text.find("python-zip.sha256")
    tar_pos = text.find("tar.exe")
    assert hash_check_pos != -1, "必须读取构建期写下的 python-zip.sha256"
    assert tar_pos != -1
    assert hash_check_pos < tar_pos, "哈希校验必须发生在 tar 解压之前"
    assert "certutil" in text and "find /i" in text, (
        "校验必须用系统自带 certutil + find（安装期不依赖随包工具）"
    )


def test_offline_payload_writes_nsis_readable_zip_hash(tmp_path, monkeypatch):
    """python-zip.sha256 必须是恰好 64 位十六进制、无换行（NSIS FileRead 按行读）。"""
    import scripts.build_offline_payload as payload_builder

    payload = tmp_path / "payload"
    payload.mkdir()
    zip_path = payload / "python-3.12.10-embed-amd64.zip"
    zip_path.write_bytes(b"fake-zip")
    hash_path = payload_builder.write_python_zip_hash(payload, zip_path)
    raw = hash_path.read_bytes()
    assert len(raw) == 64
    assert raw.decode("ascii").isalnum()
    assert raw.decode("ascii").upper() == raw.decode("ascii")
    assert raw == hashlib.sha256(b"fake-zip").hexdigest().upper().encode("ascii")


def test_cli_bootstrap_reboot_required_maps_to_exit_three(monkeypatch):
    """MSI 3010/1641 的待重启语义必须穿透组件 → 结果 → CLI 退出码（WP09）。"""
    code, output = _run_cmd_bootstrap(
        monkeypatch,
        install_result={
            "ok": True, "profile": "oneclick-python", "state": "complete",
            "installed": [], "reboot_required": True,
        },
    )
    assert code == install_contract.exit_code_for(InstallOutcome.REBOOT_REQUIRED)
    assert json.loads(output)["outcome"] == "reboot_required"


def test_offline_corruption_fails_fast_without_silent_online_fallback(
    tmp_path, monkeypatch
):
    """F09 修复：离线副本损坏必须快速失败并指认文件，不得静默联网重下。"""
    from deploy import bootstrap

    catalog, files = _catalog(tmp_path)
    # 打包侧：离线仓里的 llama 副本被篡改（内容与 catalog checksum 不符）
    packages_dir = tmp_path / "offline" / "packages"
    packages_dir.mkdir(parents=True)
    (packages_dir / "llama-cpu.zip").write_bytes(b"tampered")
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", tmp_path)
    shutil.copyfile(catalog, tmp_path / "package-catalog-windows-amd64.json")

    source_map = {
        "https://example.invalid/llama-cpu.zip": files["llama-cpu"],
        "https://example.invalid/napcat.zip": files["napcat"],
        "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf": files[
            "qwen3-embedding-0.6b"
        ],
    }

    def fake_download(source, destination, *, checksum, size=None, **_kwargs):
        source_path = source_map[source]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source_path.read_bytes())
        return destination

    monkeypatch.setattr(bootstrap.acquire, "download_verified", fake_download)

    with pytest.raises(bootstrap.BootstrapError) as error:
        bootstrap.install_profile(
            "oneclick-python", tmp_path / "data", catalog_path=None
        )
    assert error.value.code == "payload_corrupt", (
        "声明的离线负载损坏必须快速失败并指认文件，不得静默联网重下"
    )
    # 显式在线修复入口才允许回落（错误信息必须指路）
    result = bootstrap.install_profile(
        "oneclick-python", tmp_path / "data", catalog_path=None,
        allow_online_fallback=True,
    )
    assert result["state"] == "complete"


def test_gui_offline_getpip_uses_find_links():
    """F13 修复：GUI 离线 get-pip 必须与 helper 同参（--find-links）。"""
    text = GUI_PYTHON_RS.read_text(encoding="utf-8")
    branch = re.search(
        r"verify_offline_file\(root, OFFLINE_GET_PIP\)([\s\S]{0,2000}?)let get_pip",
        text,
    )
    assert branch, "离线 get-pip 分支必须存在"
    assert "--find-links" in branch.group(1), (
        "GUI 离线 get-pip 必须与 helper 同参：--find-links 指向随包 wheels，"
        "否则 pip 本体无法离线解析"
    )
