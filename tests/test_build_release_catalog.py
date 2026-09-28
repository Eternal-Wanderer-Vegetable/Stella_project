# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""build_release_catalog 的行为测试：候选通道与不可变来源（S14/WP14）。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_release_catalog import build_catalog


@pytest.fixture()
def backend_asset(tmp_path: Path) -> Path:
    asset = tmp_path / "Stella-llama-v5.0.0-windows-x86_64-cpu.zip"
    with zipfile.ZipFile(asset, "w") as bundle:
        bundle.writestr(
            "BACKEND.json",
            json.dumps(
                {
                    "backend": "cpu",
                    "os": "windows",
                    "runtime_api": "openai-compatible",
                    "driver_min": "none",
                    "abi": "documented",
                    "license": "llama.cpp",
                    "status": "available",
                }
            ),
        )
    return asset


def test_catalog_default_source_points_at_release(backend_asset):
    payload = build_catalog(
        backend_asset, release_ref="v5.0.0", repository="owner/repo"
    )
    llama = next(p for p in payload["packages"] if p["id"] == "llama-cpu")
    assert llama["source"] == (
        "https://github.com/owner/repo/releases/download/v5.0.0/"
        "Stella-llama-v5.0.0-windows-x86_64-cpu.zip"
    )


def test_catalog_candidate_channel_overrides_source(backend_asset):
    """--asset-base-url：llama source 指向不可变候选，其余包不动（WP14）。"""
    payload = build_catalog(
        backend_asset,
        release_ref="v5.0.0",
        repository="owner/repo",
        asset_base_url=(
            "https://github.com/owner/repo/releases/download/"
            "candidate-123-1"
        ),
    )
    llama = next(p for p in payload["packages"] if p["id"] == "llama-cpu")
    assert llama["source"] == (
        "https://github.com/owner/repo/releases/download/"
        "candidate-123-1/Stella-llama-v5.0.0-windows-x86_64-cpu.zip"
    )
    # 候选通道只改自指来源：NapCat（固定上游）与 embedding（钉提交）不变
    napcat = next(p for p in payload["packages"] if p["id"] == "napcat")
    assert "candidate" not in napcat["source"]
    embedding = next(
        p for p in payload["packages"] if p["id"] == "qwen3-embedding-0.6b"
    )
    assert "candidate" not in embedding["source"]
    assert "370f27d7550e0def9b39c1f16d3fbaa13aa67728" in embedding["source"]
