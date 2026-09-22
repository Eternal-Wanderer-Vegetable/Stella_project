# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""skills.catalog 测试：四层优先级、原子快照、插件局部刷新、失败保留旧版。"""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.catalog import SkillCatalog
from skills.model import SkillSource

MAX_BYTES = 262144


@pytest.fixture
def roots(tmp_path: Path) -> dict[str, Path]:
    """四层根目录：builtin/user/plugins/workspace 均指向夹具子目录。"""
    dirs = {
        "builtin": tmp_path / "builtin",
        "user": tmp_path / "user",
        "plugins": tmp_path / "plugins",
        "workspace": tmp_path / "workspace",
    }
    for d in dirs.values():
        d.mkdir()
    return dirs


@pytest.fixture
def catalog(roots: dict[str, Path]) -> SkillCatalog:
    return SkillCatalog(
        builtin_dir=roots["builtin"],
        user_dir=roots["user"],
        plugins_dir=roots["plugins"],
        manifest_max_bytes=MAX_BYTES,
    )


def _plugin_skill(
    roots: dict[str, Path], plugin: str, name: str, description: str = "插件技能"
) -> None:
    (roots["plugins"] / plugin / "skills" / name).mkdir(parents=True, exist_ok=True)
    (roots["plugins"] / plugin / "skills" / name / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n正文\n",
        encoding="utf-8",
    )


class TestLayerPriority:
    def test_four_layers_all_present(self, roots, catalog, skill_tree):
        skill_tree("builtin", "b-skill")
        skill_tree("user", "u-skill")
        skill_tree("workspace", "w-skill")
        _plugin_skill(roots, "some_plugin", "p-skill")
        assert catalog.refresh()
        assert set(catalog.snapshot.by_name) == {"b-skill", "u-skill", "p-skill"}

    def test_workspace_layer_only_in_workspace_view(
        self, roots, catalog, skill_tree, write_skill
    ):
        skill_tree("user", "pdf")
        write_skill(roots["workspace"] / "skills", "w-pdf")
        assert catalog.refresh()
        assert catalog.snapshot.get("w-pdf") is None
        merged = catalog.snapshot_with_workspace(roots["workspace"])
        assert merged.get("w-pdf") is not None
        assert merged.get("pdf").source is SkillSource.USER

    def test_same_name_higher_layer_wins(self, roots, catalog, skill_tree, write_skill):
        skill_tree("builtin", "pdf", description="builtin 版")
        skill_tree("user", "pdf", description="user 版")
        write_skill(roots["workspace"] / "skills", "pdf", description="workspace 版")
        assert catalog.refresh()
        assert catalog.snapshot.get("pdf").source is SkillSource.USER
        merged = catalog.snapshot_with_workspace(roots["workspace"])
        assert merged.get("pdf").source is SkillSource.WORKSPACE

    def test_priority_descends_when_higher_layer_removed(
        self, roots, catalog, skill_tree
    ):
        skill_tree("builtin", "pdf", description="builtin 版")
        skill_tree("user", "pdf", description="user 版")
        assert catalog.refresh()
        assert catalog.snapshot.get("pdf").description == "user 版"
        (roots["user"] / "pdf" / "SKILL.md").unlink()
        assert catalog.refresh()
        assert catalog.snapshot.get("pdf").description == "builtin 版"

    def test_same_layer_conflict_is_deterministic(self, roots, catalog):
        _plugin_skill(roots, "plugin_a", "dup", description="来自 a")
        _plugin_skill(roots, "plugin_b", "dup", description="来自 b")
        assert catalog.refresh()
        winners = {catalog.snapshot.get("dup").origin for _ in range(2)}
        assert catalog.refresh()
        winners.add(catalog.snapshot.get("dup").origin)
        assert len(winners) == 1  # 每次刷新结果一致，不随扫描顺序漂移


class TestAtomicSnapshot:
    def test_old_snapshot_serves_inflight_requests(self, roots, catalog, skill_tree):
        skill_tree("user", "pdf")
        assert catalog.refresh()
        old = catalog.snapshot
        skill_tree("user", "zip")
        assert catalog.refresh()
        # 旧快照对象不被原地修改：进行中的请求各持一致的旧视图
        assert set(old.by_name) == {"pdf"}
        assert set(catalog.snapshot.by_name) == {"pdf", "zip"}
        assert old.version != catalog.snapshot.version

    def test_refresh_failure_keeps_old_snapshot(
        self, roots, catalog, skill_tree, monkeypatch
    ):
        skill_tree("user", "pdf")
        assert catalog.refresh()
        old = catalog.snapshot

        import skills.catalog as catalog_mod

        def _boom(*args, **kwargs):
            raise RuntimeError("磁盘抽风")

        monkeypatch.setattr(catalog_mod, "scan_plugins", _boom)
        assert not catalog.refresh()
        assert catalog.snapshot is old
        assert "磁盘抽风" in catalog.status()["last_error"]
        assert catalog.snapshot.get("pdf") is not None


class TestPluginRefresh:
    def test_refresh_plugin_only_touches_that_origin(self, roots, catalog):
        _plugin_skill(roots, "plugin_a", "a-old")
        _plugin_skill(roots, "plugin_b", "b-old")
        assert catalog.refresh()
        before = catalog.snapshot

        import shutil

        _plugin_skill(roots, "plugin_a", "a-new")
        shutil.rmtree(roots["plugins"] / "plugin_a" / "skills" / "a-old")
        assert catalog.refresh_plugin(roots["plugins"] / "plugin_a")
        snap = catalog.snapshot
        assert snap.get("a-new") is not None
        assert snap.get("a-old") is None  # 该插件旧条目被替换
        assert snap.get("b-old") is not None
        assert snap.version != before.version

    def test_refresh_removed_plugin_clears_entries(self, roots, catalog):
        _plugin_skill(roots, "plugin_a", "a-old")
        assert catalog.refresh()
        gone = roots["plugins"] / "plugin_a"
        import shutil

        shutil.rmtree(gone)
        assert catalog.refresh_plugin(gone)
        assert catalog.snapshot.get("a-old") is None

    def test_refresh_plugin_failure_keeps_current(self, roots, catalog, monkeypatch):
        _plugin_skill(roots, "plugin_a", "a-old")
        assert catalog.refresh()
        before = catalog.snapshot

        import skills.catalog as catalog_mod

        def _boom(*args, **kwargs):
            raise RuntimeError("扫描炸了")

        monkeypatch.setattr(catalog_mod, "scan_layer", _boom)
        assert not catalog.refresh_plugin(roots["plugins"] / "plugin_a")
        assert catalog.snapshot is before


class TestWorkspaceCache:
    def test_cache_hits_until_mtime_changes(self, roots, catalog, write_skill):
        write_skill(roots["workspace"] / "skills", "pdf")
        view1 = catalog.snapshot_with_workspace(roots["workspace"])
        view2 = catalog.snapshot_with_workspace(roots["workspace"])
        assert view1.version == view2.version
        # 新增技能后 mtime 摘要变化 → 重扫
        write_skill(roots["workspace"] / "skills", "zip")
        view3 = catalog.snapshot_with_workspace(roots["workspace"])
        assert view3.get("zip") is not None
        assert view3.version != view1.version


class TestStatus:
    def test_status_summary_is_metadata_only(self, roots, catalog, skill_tree):
        skill_tree("builtin", "b-skill")
        bad = roots["user"] / "BAD NAME"
        bad.mkdir()
        (bad / "SKILL.md").write_text("---\ndescription: x\n---\n", encoding="utf-8")
        assert catalog.refresh()
        status = catalog.status()
        assert status["total"] == 1
        assert status["layer_counts"] == {"builtin": 1, "plugin": 0, "user": 0}
        assert status["quarantined"] == 1
        assert status["last_error"] == ""
        # 状态摘要不得携带正文或磁盘路径明细
        assert "使用说明" not in str(status)
        assert str(roots["user"]) not in str(status)


class TestShippedBuiltinSample:
    def test_doc_lookup_sample_discoverable(self, tmp_path):
        """仓库自带的 builtin 样例技能必须能被默认配置发现（防样例腐化）。"""
        from config import settings

        catalog = SkillCatalog(
            builtin_dir=Path(settings.SKILLS_BUILTIN_DIR),
            user_dir=tmp_path / "user",
            plugins_dir=tmp_path / "plugins",
            manifest_max_bytes=MAX_BYTES,
        )
        assert catalog.refresh()
        manifest = catalog.snapshot.get("doc-lookup")
        assert manifest is not None
        assert manifest.source is SkillSource.BUILTIN
        assert manifest.trust.value == "controlled"
        assert "docs/" in (Path(manifest.root) / "SKILL.md").read_text(encoding="utf-8")
