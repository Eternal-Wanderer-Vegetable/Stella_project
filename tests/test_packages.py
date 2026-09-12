# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from deploy import __main__ as deploy_main
from deploy import packages, runtime


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_model_import_uses_atomic_target_and_records_active_package(
    monkeypatch, tmp_path
):
    source = tmp_path / "model.gguf"
    source.write_bytes(b"model-v1")
    data_root = tmp_path / "StellaData"
    runtime_dir = tmp_path / "instance"
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(runtime, "INSTANCE_ID", "test")

    record = packages.import_model(
        source,
        model_id="demo-model",
        version="1.0.0",
        checksum=_checksum(source),
        data_root=data_root,
    )

    installed = data_root / record["path"]
    assert installed.read_bytes() == b"model-v1"
    registry = packages.read_registry(data_root)
    assert registry["active"]["model"] == "demo-model@1.0.0"
    assert registry["history"][-1]["previous"] is None
    manifest = runtime.read_manifest()
    assert (
        manifest["components"]["llama"]["config"]["model"]["package"]
        == "demo-model@1.0.0"
    )
    assert (
        manifest["components"]["llama"]["config"]["model"]["checksum"]
        == record["checksum"]
    )
    assert not list(installed.parent.glob("*.tmp"))


def test_checksum_failure_does_not_change_active_model(monkeypatch, tmp_path):
    data_root = tmp_path / "StellaData"
    first = tmp_path / "first.gguf"
    second = tmp_path / "second.gguf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    runtime_dir = tmp_path / "instance"
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(runtime, "INSTANCE_ID", "test")

    packages.import_model(
        first,
        model_id="first",
        version="1.0.0",
        checksum=_checksum(first),
        data_root=data_root,
    )
    with pytest.raises(packages.PackageError, match="active model 未改变"):
        packages.import_model(
            second,
            model_id="second",
            version="1.0.0",
            checksum="0" * 64,
            data_root=data_root,
        )

    registry = packages.read_registry(data_root)
    assert registry["active"]["model"] == "first@1.0.0"
    assert not (data_root / ".stella" / "packages" / "model" / "second").exists()


def test_embedding_import_has_separate_active_slot(monkeypatch, tmp_path):
    data_root = tmp_path / "StellaData"
    source = tmp_path / "embedding.gguf"
    source.write_bytes(b"embedding")
    runtime_dir = tmp_path / "instance"
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(runtime, "INSTANCE_ID", "test")

    record = packages.import_model(
        source,
        model_id="qwen3-embedding-0.6b",
        version="q8_0",
        checksum=_checksum(source),
        data_root=data_root,
        model_role="embedding",
        model_metadata={"dimension": 1024, "license": "Apache-2.0"},
    )

    registry = packages.read_registry(data_root)
    assert registry["active"]["embedding"] == "qwen3-embedding-0.6b@q8_0"
    assert registry["packages"][0]["model_role"] == "embedding"
    assert record["dimension"] == 1024
    assert not registry["active"].get("model")


def test_model_rollback_restores_previous_version(monkeypatch, tmp_path):
    data_root = tmp_path / "StellaData"
    first = tmp_path / "first.gguf"
    second = tmp_path / "second.gguf"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    runtime_dir = tmp_path / "instance"
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(runtime, "INSTANCE_ID", "test")

    packages.import_model(
        first,
        model_id="demo",
        version="1.0.0",
        checksum=_checksum(first),
        data_root=data_root,
    )
    packages.import_model(
        second,
        model_id="demo",
        version="2.0.0",
        checksum=_checksum(second),
        data_root=data_root,
    )
    restored = packages.rollback_model(data_root)

    assert restored["version"] == "1.0.0"
    assert packages.read_registry(data_root)["active"]["model"] == "demo@1.0.0"
    assert packages.read_registry(data_root)["history"][-1]["reason"] == "rollback"
    assert (
        runtime.read_manifest()["components"]["llama"]["config"]["model"]["package"]
        == "demo@1.0.0"
    )


def test_embedding_rollback_uses_embedding_history_without_touching_chat_model(
    tmp_path,
):
    data_root = tmp_path / "StellaData"
    first = tmp_path / "embedding-first.gguf"
    second = tmp_path / "embedding-second.gguf"
    first.write_bytes(b"embedding-first")
    second.write_bytes(b"embedding-second")

    packages.import_model(
        first,
        model_id="qwen3-embedding-0.6b",
        version="q8_0",
        checksum=_checksum(first),
        data_root=data_root,
        model_role="embedding",
    )
    packages.import_model(
        second,
        model_id="qwen3-embedding-0.6b",
        version="q6_k",
        checksum=_checksum(second),
        data_root=data_root,
        model_role="embedding",
    )

    restored = packages.rollback_model(data_root, model_role="embedding")

    registry = packages.read_registry(data_root)
    assert restored["version"] == "q8_0"
    assert registry["active"]["embedding"] == "qwen3-embedding-0.6b@q8_0"
    assert "model" not in registry["active"]
    assert registry["history"][-1]["kind"] == "embedding"


def test_catalog_records_versions_and_verifies_checksums(tmp_path):
    (tmp_path / "start.bat").write_text("start", encoding="utf-8")
    (tmp_path / "bot.py").write_text("bot", encoding="utf-8")
    schema = tmp_path / "runtime-manager" / "schemas"
    schema.mkdir(parents=True)
    (schema / "runtime-manifest.schema.json").write_text("{}", encoding="utf-8")
    link = tmp_path / "extensions" / "link_monitor"
    link.mkdir(parents=True)
    (link / "__init__.py").write_text("link", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "stella_project"\nversion = "4.0.0"\n',
        encoding="utf-8",
    )

    catalog = packages.build_catalog(tmp_path, platform="windows-amd64")
    packages.write_catalog(tmp_path, platform="windows-amd64")
    assert {item["kind"] for item in catalog["packages"]} == {
        "runtime",
        "component",
        "onebot",
    }
    assert all(item["version"] in {"4.0.0", "1"} for item in catalog["packages"])
    assert packages.verify_catalog(tmp_path) == []

    (tmp_path / "bot.py").write_text("changed", encoding="utf-8")
    assert any(
        "bot.py checksum 不匹配" in problem
        for problem in packages.verify_catalog(tmp_path)
    )


def test_registry_rejects_path_escape_and_invalid_checksum():
    payload = packages.default_registry()
    payload["packages"] = [
        {
            "kind": "model",
            "id": "demo",
            "version": "1.0.0",
            "path": "../outside.gguf",
            "checksum": "0" * 64,
        }
    ]
    with pytest.raises(packages.PackageError):
        packages.validate_registry(payload)


def test_catalog_is_json_and_does_not_include_model_bytes(tmp_path):
    (tmp_path / "start.bat").write_text("start", encoding="utf-8")
    catalog_path = packages.write_catalog(tmp_path)
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert not any(item["kind"] == "model" for item in payload["packages"])


def test_profile_catalog_includes_only_declared_default_embedding(tmp_path):
    (tmp_path / "start.bat").write_text("start", encoding="utf-8")
    catalog = packages.build_catalog(
        tmp_path,
        platform="windows-amd64",
        profile_id="oneclick-python",
    )
    assert catalog["profile"] == "oneclick-python"
    models = [item for item in catalog["packages"] if item["kind"] == "model"]
    assert [item["id"] for item in models] == ["qwen3-embedding-0.6b"]
    assert models[0]["status"] == "available"
    assert models[0]["remote"] is True


def test_profile_catalog_is_available_from_cli(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(packages, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(deploy_main, "PROJECT_ROOT", tmp_path)
    (tmp_path / "start.bat").write_text("start", encoding="utf-8")
    assert (
        deploy_main.main(
            [
                "packages",
                "catalog",
                "--platform",
                "windows-amd64",
                "--profile",
                "oneclick-python",
            ]
        )
        == 0
    )
    payload = json.loads(
        (tmp_path / packages.CATALOG_FILENAME).read_text(encoding="utf-8")
    )
    assert payload["profile"] == "oneclick-python"


def test_packages_list_is_a_json_cli_surface(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(packages, "STELLA_HOME", tmp_path)
    assert deploy_main.main(["packages", "list"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["packages"] == []
