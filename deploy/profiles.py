# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Product profile contracts used by release assembly and bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROFILE_ROOT = Path(__file__).resolve().parent.parent / "release_assets" / "product-profiles"
PROFILE_IDS = (
    "oneclick-python",
    "oneclick-rust",
    "standalone-python",
    "standalone-rust",
)
SUPPORTED_PLATFORMS = ("windows-amd64",)
SUPPORTED_FLAVORS = ("python", "rust")
ONECLICK_DEFAULT_EMBEDDING = {
    "id": "qwen3-embedding-0.6b",
    "version": "q8_0",
    "filename": "Qwen3-Embedding-0.6B-Q8_0.gguf",
    "source": (
        "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/"
        "resolve/main/Qwen3-Embedding-0.6B-Q8_0.gguf"
    ),
    "license": "Apache-2.0",
    "sha256": "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439",
    "size": 639150592,
    "dimension": 1024,
    "role": "embedding",
}
FORBIDDEN_DEFAULT_MODEL_ROLES = ("chat", "consolidation", "reranker")


class ProfileError(ValueError):
    """Raised when a release profile is incomplete or internally inconsistent."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProfileError(f"无法读取产品 profile：{path}") from exc
    if not isinstance(payload, dict):
        raise ProfileError(f"产品 profile 必须是对象：{path}")
    return payload


def validate_profile(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProfileError("产品 profile 必须是对象")
    required = {
        "id",
        "version",
        "platform",
        "core_flavor",
        "distribution",
        "included_components",
        "default_models",
        "optional_components",
        "artifact",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
    profile_id = str(payload["id"]).strip()
    if profile_id not in PROFILE_IDS:
        raise ProfileError(f"未知产品 profile：{profile_id}")
    if str(payload["version"]).strip() != "4.0.1":
        raise ProfileError("产品 profile 当前必须是 4.0.1")
    if str(payload["platform"]).strip() not in SUPPORTED_PLATFORMS:
        raise ProfileError("产品 profile platform 不受支持")
    flavor = str(payload["core_flavor"]).strip()
    if flavor not in SUPPORTED_FLAVORS:
        raise ProfileError("产品 profile core_flavor 不受支持")
    distribution = str(payload["distribution"]).strip()
    expected_distribution = "oneclick" if profile_id.startswith("oneclick-") else "standalone"
    if distribution != expected_distribution:
        raise ProfileError("产品 profile distribution 与 id 不一致")
    components = payload["included_components"]
    models = payload["default_models"]
    optional = payload["optional_components"]
    artifact = payload["artifact"]
    if not isinstance(components, list) or not all(isinstance(item, str) for item in components):
        raise ProfileError("included_components 必须是字符串数组")
    if not isinstance(models, list) or not all(isinstance(item, dict) for item in models):
        raise ProfileError("default_models 必须是对象数组")
    if not isinstance(optional, list) or not all(isinstance(item, str) for item in optional):
        raise ProfileError("optional_components 必须是字符串数组")
    if not isinstance(artifact, dict):
        raise ProfileError("artifact 必须是对象")
    for key in ("filename", "kind"):
        if not str(artifact.get(key, "")).strip():
            raise ProfileError(f"artifact 缺少 {key}")
    model_ids = {str(model.get("id", "")).strip() for model in models}
    if distribution == "oneclick":
        if model_ids != {ONECLICK_DEFAULT_EMBEDDING["id"]}:
            raise ProfileError("OneClick 必须且只能默认安装 qwen3-embedding-0.6b")
        model = models[0]
        for key, expected in ONECLICK_DEFAULT_EMBEDDING.items():
            if model.get(key) != expected:
                raise ProfileError(f"默认 embedding 元数据不匹配：{key}")
        if "llama-cpu" not in components or "napcat" not in components:
            raise ProfileError("OneClick 必须声明 llama-cpu 和 napcat")
    else:
        if models:
            raise ProfileError("Standalone 不得声明默认模型")
        if any(item in components for item in ("llama-cpu", "napcat")):
            raise ProfileError("Standalone 不得包含 llama-cpu 或 napcat")
    if any(str(model.get("role", "")).strip() in FORBIDDEN_DEFAULT_MODEL_ROLES for model in models):
        raise ProfileError("禁止默认安装 chat/consolidation/reranker 模型")
    normalized = dict(payload)
    normalized["id"] = profile_id
    normalized["version"] = "4.0.1"
    normalized["platform"] = str(payload["platform"]).strip()
    normalized["core_flavor"] = flavor
    normalized["distribution"] = distribution
    return normalized


def profile_path(profile_id: str) -> Path:
    if profile_id not in PROFILE_IDS:
        raise ProfileError(f"未知产品 profile：{profile_id}")
    return PROFILE_ROOT / f"{profile_id}.json"


def load_profile(profile_id: str, root: Path | None = None) -> dict[str, Any]:
    path = (Path(root) if root else PROFILE_ROOT) / f"{profile_id}.json"
    return validate_profile(_load_json(path))


def load_profiles(root: Path | None = None) -> dict[str, dict[str, Any]]:
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}


__all__ = [
    "FORBIDDEN_DEFAULT_MODEL_ROLES",
    "ONECLICK_DEFAULT_EMBEDDING",
    "PROFILE_IDS",
    "PROFILE_ROOT",
    "ProfileError",
    "load_profile",
    "load_profiles",
    "profile_path",
    "validate_profile",
]
