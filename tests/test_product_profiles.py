from __future__ import annotations

import copy
import zipfile

import pytest

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


def test_all_profiles_are_v401_and_non_overlapping():
    profiles = load_profiles()
    assert tuple(profiles) == PROFILE_IDS
    assert {item["artifact"]["filename"] for item in profiles.values()} == {
        "Stella-OneClick-Python-v4.0.1-windows-amd64.exe",
        "Stella-OneClick-Rust-v4.0.1-windows-amd64.exe",
        "Stella-Standalone-Python-v4.0.1-windows-amd64.zip",
        "Stella-Standalone-Rust-v4.0.1-windows-amd64.zip",
    }
    for profile in profiles.values():
        assert profile["version"] == "4.0.1"
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


def test_release_builder_keeps_standalone_allowlist_separate(tmp_path):
    source = tmp_path / "source"
    for relative in (
        "bot.py",
        "requirements.txt",
        "pyproject.toml",
        "LICENSE",
        "README.md",
        ".env.example",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    for directory in ("config", "core", "deploy", "extensions", "memory", "system_prompts"):
        path = source / directory / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (source / "runtime" / "python.exe").parent.mkdir(parents=True)
    (source / "runtime" / "python.exe").write_bytes(b"must not ship")
    (source / "models" / "chat.gguf").parent.mkdir(parents=True)
    (source / "models" / "chat.gguf").write_bytes(b"must not ship")

    archive = build_standalone(
        source,
        tmp_path / "standalone",
        "standalone-python",
    )
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
    assert "bot.py" in names
    assert "runtime/python.exe" not in names
    assert "models/chat.gguf" not in names


def test_release_builder_oneclick_is_single_executable(tmp_path):
    installer = tmp_path / "installer.exe"
    installer.write_bytes(b"installer")
    output = tmp_path / "oneclick"
    result = build_oneclick(installer, output, "oneclick-python")
    assert result.name == "Stella-OneClick-Python-v4.0.1-windows-amd64.exe"
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
        "runtime-manager/schemas/runtime-manifest.schema.json",
        "runtime-manager/schemas/runtime-state.schema.json",
        "runtime-manager/schemas/package-catalog.schema.json",
        "runtime-manager/schemas/package-registry.schema.json",
    ):
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    for directory in (
        "config",
        "core",
        "deploy",
        "extensions",
        "memory",
        "system_prompts",
        "runtime-manager",
    ):
        path = source / directory / "__init__.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (source / "tests").mkdir()
    (source / "tests" / "secret.txt").write_text("must not ship", encoding="utf-8")

    output = tmp_path / "resources"
    stage_installer_resources(source, output, "oneclick-python")

    assert (output / ".stella-profile").read_text(encoding="utf-8").strip() == (
        "oneclick-python"
    )
    assert (output / "deploy" / "__init__.py").exists()
    assert not (output / "tests").exists()
