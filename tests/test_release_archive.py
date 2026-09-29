from __future__ import annotations

import zipfile

from scripts.check_release_archive import forbidden_members


def test_archive_guard_uses_exact_path_components(tmp_path):
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("deploy/napcat.py", "source")
        bundle.writestr("deploy/models.py", "source")
        bundle.writestr("runtime-manager/schemas/runtime-state.schema.json", "schema")
        bundle.writestr("models/chat.gguf", "payload")

    assert forbidden_members(archive) == ["models/chat.gguf"]


def test_archive_guard_rejects_top_level_runtime_but_keeps_core_runtime(tmp_path):
    """runtime 仅在归档顶层拒绝（开发机嵌入式运行时）；core/runtime/ 是
    runtime-manager 工作的 Python 包，属于正常发布内容（v6.0.1 实测：
    未锚定的组件匹配把 Standalone 归档剥成跑不起来的空壳）。"""
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("runtime/python.exe", "embedded runtime")
        bundle.writestr("core/runtime/turn_service.py", "package")
        bundle.writestr("core/runtime/__init__.py", "package")
        bundle.writestr("llama-server.exe", "backend binary")

    assert forbidden_members(archive) == [
        "runtime/python.exe",
        "llama-server.exe",
    ]
