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
