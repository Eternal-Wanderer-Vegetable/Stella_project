from __future__ import annotations

import copy

import pytest

from deploy.profiles import (
    ONECLICK_DEFAULT_EMBEDDING,
    PROFILE_IDS,
    ProfileError,
    load_profiles,
    validate_profile,
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
