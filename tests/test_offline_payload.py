# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""离线负载清单（deploy.offline_payload）的行为测试：结构校验、逐文件
验证、构建期清单生成与构建缓存一致性（WP05/F14）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from deploy import offline_payload
from deploy.offline_payload import PayloadError


def _seed_file(root: Path, relative: str, content: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _make_payload(tmp_path: Path) -> Path:
    payload = tmp_path / "payload"
    _seed_file(payload, "python-3.12.10-embed-amd64.zip", b"zip-bytes")
    _seed_file(payload, "get-pip.py", b"get-pip")
    _seed_file(payload, "python-zip.sha256", b"A" * 64)
    _seed_file(payload, "wheels/dep-1.0-py3-none-any.whl", b"wheel")
    _seed_file(payload, "packages/llama-cpu.zip", b"llama")
    manifest = {
        "schema_version": 2,
        "python_version": "3.12.10",
        "browser_revision": "1181",
        "files": {
            "python-3.12.10-embed-amd64.zip": _sha(b"zip-bytes"),
            "get-pip.py": _sha(b"get-pip"),
            "python-zip.sha256": _sha(b"A" * 64),
            "wheels/dep-1.0-py3-none-any.whl": _sha(b"wheel"),
            "packages/llama-cpu.zip": _sha(b"llama"),
        },
        "sizes": {"get-pip.py": 7, "packages/llama-cpu.zip": 5},
        "purposes": {
            "python-3.12.10-embed-amd64.zip": "runtime",
            "get-pip.py": "pip-bootstrap",
            "python-zip.sha256": "metadata",
            "wheels/dep-1.0-py3-none-any.whl": "dependency",
            "packages/llama-cpu.zip": "component",
        },
    }
    (payload / "MANIFEST.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return payload


# ============================================================
# 结构校验：清单条目是不可信输入
# ============================================================


@pytest.mark.parametrize(
    "name",
    [
        "/abs/path.zip",
        "C:/escape.zip",
        "C:\\escape.zip",
        "../escape.zip",
        "wheels/../../escape.zip",
        "stream.zip:ads",
        "",
    ],
)
def test_validate_rejects_unsafe_entry_names(name):
    manifest = {"schema_version": 2, "files": {name: "a" * 64}}
    with pytest.raises(PayloadError, match=r"payload_corrupt|条目"):
        offline_payload.validate_manifest(manifest)


def test_validate_rejects_case_conflicts_and_bad_digests():
    manifest = {
        "schema_version": 2,
        "files": {"Wheels/x.whl": "a" * 64, "wheels/x.whl": "a" * 64},
    }
    with pytest.raises(PayloadError, match="大小写冲突"):
        offline_payload.validate_manifest(manifest)
    manifest = {"schema_version": 2, "files": {"ok.zip": "zz" * 32}}
    with pytest.raises(PayloadError, match="SHA-256"):
        offline_payload.validate_manifest(manifest)
    manifest = {"schema_version": 2, "files": {}}
    with pytest.raises(PayloadError, match="files"):
        offline_payload.validate_manifest(manifest)


def test_validate_accepts_v1_flat_files():
    manifest = {"schema_version": 1, "files": {"get-pip.py": "a" * 64}}
    normalized = offline_payload.validate_manifest(manifest)
    assert normalized == {"get-pip.py": "a" * 64}


# ============================================================
# 逐文件验证：缺失/损坏/大小不符都具名失败
# ============================================================


def test_verify_payload_passes_on_intact_bundle(tmp_path):
    payload = _make_payload(tmp_path)
    offline_payload.verify_payload(payload)  # 不抛 = 通过


def test_verify_payload_names_missing_and_corrupt_files(tmp_path):
    payload = _make_payload(tmp_path)
    (payload / "packages" / "llama-cpu.zip").unlink()
    with pytest.raises(PayloadError) as error:
        offline_payload.verify_payload(payload)
    assert error.value.code == "payload_missing"
    assert "llama-cpu.zip" in error.value.message

    (payload / "packages" / "llama-cpu.zip").write_bytes(b"tampered!")
    with pytest.raises(PayloadError) as error:
        offline_payload.verify_payload(payload)
    assert error.value.code == "payload_corrupt"

    # 大小不符（sizes 里登记了 get-pip.py）
    (payload / "packages" / "llama-cpu.zip").write_bytes(b"llama")
    (payload / "get-pip.py").write_bytes(b"get-pip-tampered")
    with pytest.raises(PayloadError) as error:
        offline_payload.verify_payload(payload)
    assert error.value.code == "payload_corrupt"
    assert "大小" in error.value.message


def test_read_manifest_rejects_missing_or_broken_manifest(tmp_path):
    with pytest.raises(PayloadError) as error:
        offline_payload.read_manifest(tmp_path)
    assert error.value.code == "payload_missing"
    (tmp_path / "MANIFEST.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(PayloadError) as error:
        offline_payload.read_manifest(tmp_path)
    assert error.value.code == "payload_corrupt"
    (tmp_path / "MANIFEST.json").write_text(
        json.dumps({"schema_version": 99, "files": {}}), encoding="utf-8"
    )
    with pytest.raises(PayloadError) as error:
        offline_payload.read_manifest(tmp_path)
    assert "schema" in error.value.message


# ============================================================
# 构建期清单生成
# ============================================================


def test_build_manifest_derives_hashes_sizes_and_purposes(tmp_path):
    payload = tmp_path / "payload"
    _seed_file(payload, "get-pip.py", b"get-pip")
    _seed_file(payload, "wheels/dep.whl", b"wheel")
    manifest = offline_payload.build_manifest(
        payload,
        {"get-pip.py": "pip-bootstrap", "wheels/dep.whl": "dependency"},
        python_version="3.12.10",
        browser_revision="1181",
    )
    assert manifest["schema_version"] == 2
    assert manifest["files"]["get-pip.py"] == _sha(b"get-pip")
    assert manifest["sizes"]["wheels/dep.whl"] == 5
    assert manifest["purposes"]["wheels/dep.whl"] == "dependency"
    assert manifest["python_version"] == "3.12.10"
    assert manifest["browser_revision"] == "1181"
    # 清单必须通过同一条安装期验证路径（构建后边界校验）
    (payload / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    offline_payload.verify_payload(payload)
    with pytest.raises(PayloadError, match="用途"):
        offline_payload.build_manifest(payload, {"get-pip.py": "bogus"})


# ============================================================
# 构建缓存一致性（F14）：缓存命中也必须校验，损坏先隔离再重取
# ============================================================


def test_fetch_catalog_packages_quarantines_corrupt_cache(tmp_path, monkeypatch):
    import scripts.build_offline_payload as builder

    record = {
        "kind": "component", "id": "llama-cpu", "version": "1.0",
        "path": "llama-cpu.zip", "checksum": _sha(b"good-content"),
        "platform": "windows-amd64", "source": "https://example.invalid/x.zip",
        "artifact": "llama-cpu.zip", "license": "l", "sbom": "s",
        "backend": "cpu", "runtime_api": "openai-compatible",
        "driver_min": "none", "abi": "documented", "status": "available",
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"schema_version": 1, "packages": [record]}),
                       encoding="utf-8")
    packages_dir = tmp_path / "packages"
    packages_dir.mkdir()

    def fake_download(source, destination, *, checksum, size=None):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"good-content")
        return destination

    monkeypatch.setattr(builder, "download_verified", fake_download)

    # 1) 缓存损坏（内容与 checksum 不符）→ 隔离 + 重新下载正确内容
    destination = packages_dir / "llama-cpu.zip"
    destination.write_bytes(b"corrupt-cache")
    builder.fetch_catalog_packages(catalog, packages_dir)
    assert destination.read_bytes() == b"good-content"
    quarantined = list(packages_dir.glob(".corrupt-*"))
    assert len(quarantined) == 1

    # 2) 缓存命中且校验通过 → 不再下载
    downloads = {"count": 0}

    def counting_download(source, destination, *, checksum, size=None):
        downloads["count"] += 1
        return fake_download(source, destination, checksum=checksum, size=size)

    monkeypatch.setattr(builder, "download_verified", counting_download)
    builder.fetch_catalog_packages(catalog, packages_dir)
    assert downloads["count"] == 0


def test_helper_verifies_payload_before_pip(tmp_path, monkeypatch):
    """helper 在 pip 步骤之前全量校验负载；损坏即退出，不执行任何命令。"""
    import importlib.util
    import sys

    helper_path = Path(__file__).resolve().parents[1] / "deploy" / "nsis_bootstrap_helper.py"
    spec = importlib.util.spec_from_file_location("nsis_bootstrap_helper_v", helper_path)
    helper = importlib.util.module_from_spec(spec)
    sys.modules["nsis_bootstrap_helper_v"] = helper
    spec.loader.exec_module(helper)

    install_root = tmp_path / "install"
    runtime = install_root / "runtime"
    runtime.mkdir(parents=True)
    offline = install_root / "offline"
    offline.mkdir(parents=True)
    (offline / "get-pip.py").write_text("# get-pip", encoding="utf-8")
    (offline / "wheels").mkdir()
    (install_root / "requirements.txt").write_text("dep==1\n", encoding="utf-8")
    (install_root / ".stella-profile").write_text("oneclick-python", encoding="utf-8")
    (install_root / "package-catalog-windows-amd64.json").write_text("{}", encoding="utf-8")
    (runtime / "python.exe").write_bytes(b"MZ")
    # 清单声明了 wheels/dep.whl，但文件缺失 → 装载必须在任何子进程前失败
    manifest = {
        "schema_version": 2,
        "files": {"wheels/dep.whl": "a" * 64, "get-pip.py": "b" * 64},
    }
    (offline / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")

    executed: list[list[str]] = []
    monkeypatch.setattr(helper, "_run", lambda cmd, cwd: executed.append(cmd))
    with pytest.raises(SystemExit, match="payload_missing"):
        helper.bootstrap_offline(install_root)
    assert executed == [], "负载校验失败后不得执行任何装载命令"
