# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""skills.loader 测试：命中后正文加载、资源索引、路径三道校验。"""

from __future__ import annotations

import pytest
from skills_helpers import make_manifest

from skills.loader import load_skill, read_resource
from skills.model import SkillManifest, SkillSource

ASSET_MAX = 524288


class TestLoadSkill:
    def test_body_and_indexes(self, tmp_path, write_skill):
        write_skill(
            tmp_path,
            "pdf",
            body="完整的技能正文。",
            extra_files={
                "references/spec.md": "规范内容",
                "references/deep/nested.md": "嵌套参考",
                "scripts/run.py": "print('hi')",
            },
        )
        manifest = make_manifest(tmp_path / "pdf")
        loaded = load_skill(manifest, body_max_chars=24000, asset_max_bytes=ASSET_MAX)
        assert "完整的技能正文" in loaded.body
        assert not loaded.body_truncated
        assert {e.path for e in loaded.references} == {
            "references/spec.md",
            "references/deep/nested.md",
        }
        assert [e.path for e in loaded.scripts] == ["scripts/run.py"]
        assert loaded.scripts[0].kind == "script"

    def test_body_truncated_to_budget(self, tmp_path, write_skill):
        write_skill(tmp_path, "big", body="x" * 5000)
        loaded = load_skill(
            make_manifest(tmp_path / "big"),
            body_max_chars=100,
            asset_max_bytes=ASSET_MAX,
        )
        assert len(loaded.body) == 100
        assert loaded.body_truncated

    def test_oversize_assets_dropped_from_index(self, tmp_path, write_skill):
        write_skill(
            tmp_path,
            "mix",
            extra_files={
                "references/small.md": "ok",
                "references/huge.bin": "y" * 4096,
            },
        )
        loaded = load_skill(
            make_manifest(tmp_path / "mix"), body_max_chars=1000, asset_max_bytes=1024
        )
        assert [e.path for e in loaded.references] == ["references/small.md"]
        assert loaded.assets_oversize_dropped == ("references/huge.bin",)


class TestReadResource:
    def test_reads_within_skill_dir(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf", extra_files={"references/spec.md": "规范"})
        manifest = make_manifest(tmp_path / "pdf")
        assert (
            read_resource(manifest, "references/spec.md", asset_max_bytes=ASSET_MAX)
            == "规范".encode()
        )

    @pytest.mark.parametrize(
        "bad",
        [
            "../outside.txt",
            "a/../../b.txt",
            "/etc/passwd",
            "C:/Windows/system32",
            "scripts\\run.py",
            "",
            "references/missing.md",
        ],
    )
    def test_rejects_escape_and_missing(self, tmp_path, write_skill, bad):
        write_skill(tmp_path, "pdf", extra_files={"references/spec.md": "x"})
        manifest = make_manifest(tmp_path / "pdf")
        with pytest.raises(ValueError):
            read_resource(manifest, bad, asset_max_bytes=ASSET_MAX)

    def test_rejects_symlink_escape(self, tmp_path, write_skill):
        secret = tmp_path / "secret.txt"
        secret.write_text("机密", encoding="utf-8")
        write_skill(tmp_path, "evil", extra_files={"references/real.md": "x"})
        link = tmp_path / "evil" / "references" / "leak.md"
        try:
            link.symlink_to(secret)
        except OSError:
            pytest.skip("当前环境不允许创建符号链接")
        with pytest.raises(ValueError):
            read_resource(
                make_manifest(tmp_path / "evil"),
                "references/leak.md",
                asset_max_bytes=ASSET_MAX,
            )

    def test_rejects_oversize(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf", extra_files={"references/big.md": "y" * 4096})
        with pytest.raises(ValueError):
            read_resource(
                make_manifest(tmp_path / "pdf"),
                "references/big.md",
                asset_max_bytes=1024,
            )


class TestManifestHelpers:
    def test_make_manifest_fields(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf")
        manifest = make_manifest(tmp_path / "pdf")
        assert isinstance(manifest, SkillManifest)
        assert manifest.source is SkillSource.USER
