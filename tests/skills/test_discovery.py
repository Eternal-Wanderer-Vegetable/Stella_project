# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""skills.discovery 测试：受限 front matter、路径/大小/符号链接校验、隔离。"""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.discovery import (
    Quarantine,
    build_manifest,
    parse_front_matter,
    scan_layer,
    scan_plugins,
)
from skills.model import SkillSource

MAX_BYTES = 262144


class TestFrontMatter:
    def test_parses_allowlisted_scalars(self):
        text = "---\nname: pdf\ndescription: 处理 PDF\nlicense: MIT\n---\n\n正文"
        fields = parse_front_matter(text)
        assert fields["name"] == "pdf"
        assert fields["description"] == "处理 PDF"
        assert fields["license"] == "MIT"

    def test_drops_non_allowlisted_keys(self):
        text = "---\nname: pdf\ndescription: d\nallowed-tools: Bash\nsecret: x\n---\n"
        fields = parse_front_matter(text)
        assert "allowed-tools" not in fields
        assert "secret" not in fields

    def test_drops_nested_yaml_structures(self):
        text = "---\nname: pdf\ndescription: d\ntools:\n  - a\n  - b\n---\n"
        fields = parse_front_matter(text)
        assert fields["name"] == "pdf"
        assert "tools" not in fields

    def test_missing_block_returns_empty(self):
        assert parse_front_matter("没有 front matter 的正文") == {}
        assert parse_front_matter("---\nname: pdf\n没有闭合") == {}

    def test_unclosed_block_returns_empty(self):
        assert parse_front_matter("---\nname: pdf\ndescription: d\n") == {}

    def test_bom_tolerated(self):
        text = "﻿---\nname: pdf\ndescription: d\n---\n"
        assert parse_front_matter(text)["name"] == "pdf"

    def test_fallback_line_parser_without_yaml(self, monkeypatch):
        import skills.discovery as discovery

        monkeypatch.setattr(discovery, "_yaml", lambda: None)
        text = "---\nname: pdf\ndescription: 处理 PDF\n---\n"
        fields = parse_front_matter(text)
        assert fields == {"name": "pdf", "description": "处理 PDF"}


class TestBuildManifest:
    def test_valid_skill(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf", description="处理 PDF")
        manifest, reason = build_manifest(
            tmp_path / "pdf", source=SkillSource.USER, max_bytes=MAX_BYTES
        )
        assert reason == ""
        assert manifest is not None
        assert manifest.name == "pdf"
        assert manifest.description == "处理 PDF"
        assert manifest.body_size > 0
        assert len(manifest.content_digest) == 64
        assert manifest.trust.value == "managed"

    def test_missing_description_quarantined(self, tmp_path, write_skill):
        skill_dir = tmp_path / "pdf"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: pdf\n---\n", encoding="utf-8")
        manifest, reason = build_manifest(
            skill_dir, source=SkillSource.USER, max_bytes=MAX_BYTES
        )
        assert manifest is None
        assert "description" in reason

    def test_name_mismatch_quarantined(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf", front_matter="name: other\ndescription: d\n")
        manifest, reason = build_manifest(
            tmp_path / "pdf", source=SkillSource.USER, max_bytes=MAX_BYTES
        )
        assert manifest is None
        assert reason == Quarantine.NAME_MISMATCH

    def test_invalid_dir_name_quarantined(self, tmp_path, write_skill):
        skill_dir = tmp_path / "Bad Name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: x\ndescription: d\n---\n", encoding="utf-8"
        )
        manifest, reason = build_manifest(
            skill_dir, source=SkillSource.USER, max_bytes=MAX_BYTES
        )
        assert manifest is None
        assert reason == Quarantine.NAME_INVALID

    def test_oversized_body_quarantined(self, tmp_path, write_skill):
        write_skill(tmp_path, "big", body="x" * 4096)
        manifest, reason = build_manifest(
            tmp_path / "big", source=SkillSource.USER, max_bytes=1024
        )
        assert manifest is None
        assert reason == Quarantine.TOO_LARGE

    def test_non_utf8_quarantined(self, tmp_path, write_skill):
        skill_dir = tmp_path / "gbk"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_bytes("中文".encode("gbk"))
        manifest, reason = build_manifest(
            skill_dir, source=SkillSource.USER, max_bytes=MAX_BYTES
        )
        assert manifest is None
        assert reason == Quarantine.NOT_UTF8

    def test_symlinked_body_quarantined(self, tmp_path, write_skill):
        secret = tmp_path / "secret.txt"
        secret.write_text("机密", encoding="utf-8")
        skill_dir = tmp_path / "evil"
        skill_dir.mkdir()
        body = skill_dir / "SKILL.md"
        try:
            body.symlink_to(secret)
        except OSError:
            pytest.skip("当前环境不允许创建符号链接")
        manifest, reason = build_manifest(
            skill_dir, source=SkillSource.USER, max_bytes=MAX_BYTES
        )
        assert manifest is None
        assert reason == Quarantine.SYMLINK


class TestScanLayer:
    def test_sorted_deterministic_order(self, tmp_path, write_skill):
        for name in ("c-mail", "a-pdf", "b-zip"):
            write_skill(tmp_path, name)
        manifests, quarantined = scan_layer(
            tmp_path, source=SkillSource.USER, max_bytes=MAX_BYTES
        )
        assert quarantined == []
        assert [m.name for m in manifests] == ["a-pdf", "b-zip", "c-mail"]

    def test_invalid_entries_isolated_but_others_kept(self, tmp_path, write_skill):
        write_skill(tmp_path, "good")
        bad = tmp_path / "BAD"
        bad.mkdir()
        (bad / "SKILL.md").write_text("---\ndescription: 缺名\n---\n", encoding="utf-8")
        manifests, quarantined = scan_layer(
            tmp_path, source=SkillSource.USER, max_bytes=MAX_BYTES
        )
        assert [m.name for m in manifests] == ["good"]
        assert len(quarantined) == 1

    def test_missing_root_is_empty_not_error(self, tmp_path, write_skill):
        manifests, quarantined = scan_layer(
            tmp_path / "nope", source=SkillSource.USER, max_bytes=MAX_BYTES
        )
        assert manifests == []
        assert quarantined == []


class TestScanPlugins:
    def test_plugin_skills_discovered_with_origin(self, tmp_path, write_skill):
        write_skill(tmp_path / "plugin_a" / "skills", "tool-a")
        write_skill(tmp_path / "plugin_b" / "skills", "tool-b")
        manifests, quarantined = scan_plugins(tmp_path, max_bytes=MAX_BYTES)
        assert quarantined == []
        assert {m.origin for m in manifests} == {"plugin_a", "plugin_b"}
        assert all(m.source is SkillSource.PLUGIN for m in manifests)

    def test_plugin_without_skills_dir_ignored(self, tmp_path, write_skill):
        (tmp_path / "plain_plugin").mkdir()
        manifests, quarantined = scan_plugins(tmp_path, max_bytes=MAX_BYTES)
        assert manifests == []
        assert quarantined == []
