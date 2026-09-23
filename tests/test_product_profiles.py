from __future__ import annotations

import copy
import json
import subprocess
import sys
import zipfile

import pytest

from config import PROJECT_ROOT
from config.state import program_version
from deploy.profiles import (
    ONECLICK_DEFAULT_EMBEDDING,
    PROFILE_IDS,
    ProfileError,
    load_profiles,
    validate_profile,
)
from scripts.build_release_package import (
    build_oneclick,
    build_standalone,
    stage_installer_resources,
)


def test_all_profiles_match_project_version_and_are_non_overlapping():
    profiles = load_profiles()
    version = program_version(PROJECT_ROOT)
    assert version
    assert tuple(profiles) == PROFILE_IDS
    assert {item["artifact"]["filename"] for item in profiles.values()} == {
        f"Stella-OneClick-Python-v{version}-windows-amd64.exe",
        f"Stella-OneClick-Rust-v{version}-windows-amd64.exe",
        f"Stella-Standalone-Python-v{version}-windows-amd64.zip",
        f"Stella-Standalone-Rust-v{version}-windows-amd64.zip",
    }
    for profile in profiles.values():
        assert profile["version"] == version
        assert profile["platform"] == "windows-amd64"


@pytest.mark.parametrize("profile_id", ["oneclick-python", "oneclick-rust"])
def test_oneclick_has_only_qwen_embedding_as_default_model(profile_id):
    profile = load_profiles()[profile_id]
    assert profile["default_models"] == [ONECLICK_DEFAULT_EMBEDDING]
    assert "llama-cpu" in profile["included_components"]
    assert "napcat" in profile["included_components"]


@pytest.mark.parametrize("profile_id", ["standalone-python", "standalone-rust"])
def test_standalone_has_no_downloaded_components_or_models(profile_id):
    profile = load_profiles()[profile_id]
    assert profile["default_models"] == []
    assert "llama-cpu" not in profile["included_components"]
    assert "napcat" not in profile["included_components"]


def test_profile_rejects_missing_embedding_provenance():
    profile = copy.deepcopy(load_profiles()["oneclick-python"])
    del profile["default_models"][0]["sha256"]
    with pytest.raises(ProfileError):
        validate_profile(profile)


def test_profile_metadata_tracks_project_version_when_template_is_stale():
    profile = copy.deepcopy(load_profiles()["oneclick-python"])
    version = program_version(PROJECT_ROOT)
    stale_version = "0.0.0"
    profile["version"] = stale_version
    profile["catalog_url"] = profile["catalog_url"].replace(
        f"v{version}", f"v{stale_version}"
    )
    profile["artifact"]["filename"] = profile["artifact"]["filename"].replace(
        f"v{version}", f"v{stale_version}"
    )

    normalized = validate_profile(profile)

    assert normalized["version"] == version
    assert f"v{version}" in normalized["catalog_url"]
    assert f"v{version}" in normalized["artifact"]["filename"]


def test_profile_loader_does_not_require_runtime_dependencies():
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "from deploy.profiles import load_profile; load_profile('oneclick-rust')",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_release_builder_keeps_standalone_allowlist_separate(tmp_path):
    source = tmp_path / "source"
    for relative in (
        "bot.py",
        "requirements.txt",
        "pyproject.toml",
        "LICENSE",
        "README.md",
        ".env.example",
        "start.bat",
        "doctor.bat",
        "stop.bat",
        "README-快速开始.txt",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    for directory in (
        "astrbot_compat",
        "capability",
        "config",
        "core",
        "deploy",
        "extensions",
        "memory",
        "system_prompts",
        "runtime-manager",
        "stella_project",
        "webui",
        "desktop",
    ):
        path = source / directory / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for relative in ("deploy/napcat.py", "deploy/models.py", "deploy/runtime.py"):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    (source / "runtime" / "python.exe").parent.mkdir(parents=True)
    (source / "runtime" / "python.exe").write_bytes(b"must not ship")
    (source / "models" / "chat.gguf").parent.mkdir(parents=True)
    (source / "models" / "chat.gguf").write_bytes(b"must not ship")
    (source / "runtime-manager" / "target" / "debug").mkdir(parents=True)
    (source / "runtime-manager" / "target" / "debug" / "build.bin").write_bytes(
        b"must not ship"
    )

    archive = build_standalone(
        source,
        tmp_path / "standalone",
        "standalone-python",
    )
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
    assert "bot.py" in names
    assert "astrbot_compat/__init__.py" in names
    assert "capability/__init__.py" in names
    assert "stella_project/__init__.py" in names
    assert "runtime/python.exe" not in names
    assert "models/chat.gguf" not in names
    assert "deploy/napcat.py" in names
    assert "deploy/models.py" in names
    assert "deploy/runtime.py" in names
    assert "runtime-manager/target/debug/build.bin" not in names


def test_stager_prunes_output_inside_desktop_dir(tmp_path):
    """复现 CI RecursionError：--stage-resources 的输出位于被暂存的
    desktop/ 内部（desktop/src-tauri/resources/stella）——copytree 必须
    剪掉输出目录自身，否则把输出里的自己再往里拷、无限递归。假树与
    allowlist 测试同构（bot.py 等 COMMON_FILES 齐备）。"""
    source = tmp_path / "source"
    for relative in (
        "bot.py",
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
        "astrbot_compat",
        "capability",
        "config",
        "core",
        "deploy",
        "extensions",
        "memory",
        "system_prompts",
        "runtime-manager",
        "stella_project",
        "webui",
        "desktop",
    ):
        path = source / directory / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for profile_id in PROFILE_IDS:
        path = source / "release_assets" / "product-profiles" / f"{profile_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    (source / "webui" / "dist").mkdir(parents=True, exist_ok=True)
    (source / "webui" / "dist" / "index.html").write_text("panel", encoding="utf-8")
    staged_output = source / "desktop" / "src-tauri" / "resources" / "stella"
    staged_output.mkdir(parents=True)

    result = stage_installer_resources(
        source, staged_output, "oneclick-python", offline_payload=None
    )

    # webui 被完整暂存
    assert (result / "webui" / "dist" / "index.html").is_file()
    # 输出目录自身被剪掉：暂存的 desktop/ 内不得出现嵌套的自己
    # （无剪枝时这里会无限自拷贝直至 RecursionError——CI 实测）
    assert not (result / "desktop" / "src-tauri" / "resources" / "stella" / "desktop").exists()
    # 暂存完成后可重复执行（幂等，不递归爆栈）
    stage_installer_resources(source, staged_output, "oneclick-python")


def test_release_builder_oneclick_is_single_executable(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    output = tmp_path / "oneclick"
    result = build_oneclick(installer, output, "oneclick-python")
    version = program_version(PROJECT_ROOT)
    assert result.name == f"Stella-OneClick-Python-v{version}-windows-amd64.exe"
    assert [path.name for path in output.iterdir()] == [result.name]


def test_installer_resources_are_allowlisted_and_profile_pinned(tmp_path):
    source = tmp_path / "source"
    for relative in (
        "bot.py",
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
        "astrbot_compat",
        "capability",
        "config",
        "core",
        "deploy",
        "extensions",
        "memory",
        "system_prompts",
        "runtime-manager",
        "stella_project",
        "webui",
        "desktop",
    ):
        path = source / directory / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for profile_id in PROFILE_IDS:
        path = source / "release_assets" / "product-profiles" / f"{profile_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "secret.txt").write_text("must not ship", encoding="utf-8")

    output = tmp_path / "resources"
    stage_installer_resources(source, output, "oneclick-python")

    assert (output / ".stella-profile").read_text(encoding="utf-8").strip() == (
        "oneclick-python"
    )
    assert (output / "astrbot_compat" / "__init__.py").exists()
    assert (output / "capability" / "__init__.py").exists()
    assert (output / "stella_project" / "__init__.py").exists()
    assert (output / "deploy" / "__init__.py").exists()
    assert (output / "release_assets" / "product-profiles" / "oneclick-rust.json").exists()
    assert not (output / "tests").exists()


def test_installer_resources_include_bundled_catalog_when_present(tmp_path):
    source = tmp_path / "source"
    for relative in (
        "bot.py",
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
        "package-catalog-windows-amd64.json",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    for directory in (
        "astrbot_compat",
        "capability",
        "config",
        "core",
        "deploy",
        "extensions",
        "memory",
        "system_prompts",
        "runtime-manager",
        "stella_project",
        "webui",
        "desktop",
    ):
        path = source / directory / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    for profile_id in PROFILE_IDS:
        path = source / "release_assets" / "product-profiles" / f"{profile_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    output = tmp_path / "resources"
    stage_installer_resources(source, output, "oneclick-python")

    assert (output / "package-catalog-windows-amd64.json").exists()


def test_tauri_bundles_the_stella_resource_directory():
    config_path = (
        PROJECT_ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["bundle"]["resources"] == ["resources/stella"]


def test_tauri_bundles_webview2_offline_installer():
    """WebView2 必须内嵌完整离线安装包，绝不能走需要联网的安装方式。

    2026-09 真实用户反馈：没有 WebView2 的电脑上安装器起不了前端。默认的
    downloadBootstrapper 要联网下载运行时，离线环境直接失败——「一键离线」的
    产品定义不允许这个缺口。embedBootstrapper 虽然内嵌了引导器，但引导器本身
    仍要联网下载运行时；只有 offlineInstaller 是真离线（+约 127MB，已接受的
    体积换稳定策略）。silent 默认 true，静默安装不弹窗。
    """
    config_path = (
        PROJECT_ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))

    mode = config["bundle"]["windows"]["webviewInstallMode"]
    assert mode["type"] == "offlineInstaller"
    assert mode.get("silent", True) is True
