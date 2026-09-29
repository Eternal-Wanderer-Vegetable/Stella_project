# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""发布清单（scripts/build_release_manifest.py，WP14）的行为测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_release_manifest import (
    MANIFEST_NAME,
    SUMS_NAME,
    build_manifest,
    verify_assets_dir,
    write_sums,
)


def _asset(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


def test_build_manifest_records_hash_size_and_skips_itself(tmp_path):
    _asset(tmp_path / "Stella-OneClick-Python-v1.exe", b"installer")
    _asset(tmp_path / "package-catalog-windows-amd64.json", b"{}")
    manifest = build_manifest(
        tmp_path, release_version="1.0.0", build_id="run-1-1"
    )
    assert manifest["schema_version"] == 1
    assert manifest["release_version"] == "1.0.0"
    assert manifest["build_id"] == "run-1-1"
    names = {a["name"] for a in manifest["assets"]}
    assert names == {"Stella-OneClick-Python-v1.exe", "package-catalog-windows-amd64.json"}
    installer = next(a for a in manifest["assets"] if a["name"].endswith(".exe"))
    assert installer["sha256"] == hashlib.sha256(b"installer").hexdigest()
    assert installer["size"] == len(b"installer")


def test_build_manifest_requires_assets(tmp_path):
    with pytest.raises(SystemExit, match="资产"):
        build_manifest(tmp_path, release_version="1.0.0", build_id="")


def test_verify_round_trip_and_drift_detection(tmp_path):
    _asset(tmp_path / "a.exe", b"aaa")
    _asset(tmp_path / "b.zip", b"bb")
    manifest = build_manifest(tmp_path, release_version="1", build_id="x")
    write_sums(manifest, tmp_path / SUMS_NAME)
    verify_assets_dir(manifest, tmp_path)  # 本地复核通过

    # 模拟发布后回读：资产被截断 / 替换 / 缺失都要被抓出来
    published = tmp_path / "published"
    published.mkdir()
    _asset(published / "a.exe", b"aaa")
    _asset(published / "b.zip", b"truncated")
    with pytest.raises(SystemExit, match="不一致"):
        verify_assets_dir(manifest, published)

    (published / "b.zip").unlink()
    with pytest.raises(SystemExit, match="缺失"):
        verify_assets_dir(manifest, published)


def test_manifest_json_round_trip(tmp_path):
    _asset(tmp_path / "a.exe", b"data")
    manifest = build_manifest(tmp_path, release_version="2.0", build_id="b")
    (tmp_path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    loaded = json.loads((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
    verify_assets_dir(loaded, tmp_path)


def test_verify_mode_does_not_require_release_version(tmp_path, monkeypatch):
    """--verify 模式不传 --release-version 也能工作（v6.0.1 发布后回读步骤）。

    通过 subprocess 走真实 argparse（required 语义无法用 import 复现）。"""
    import subprocess
    import sys

    products = tmp_path / "products"
    (products / "a.exe").parent.mkdir(parents=True)
    (products / "a.exe").write_bytes(b"data")
    (products / MANIFEST_NAME).write_text(
        json.dumps(build_manifest(products, release_version="9.9.9", build_id="b")),
        encoding="utf-8",
    )
    published = tmp_path / "published"
    published.mkdir()
    (published / "a.exe").write_bytes(b"data")

    r = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "scripts" / "build_release_manifest.py"),
         "--products", str(products), "--verify", str(published)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "回读校验通过" in r.stdout
