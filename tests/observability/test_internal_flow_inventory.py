# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""运行入口 inventory 合同（计划 §6.2 第 1 点 / §8.3）。

入口发现、动态/跨语言显式边界、流程族归类、root_kind 映射与三层
覆盖分母——UNKNOWN 不得静默豁免；新增入口未归类必须在此红。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.observability import flow_catalog, internal_flow_catalog
from scripts.generate_message_flow import build_manifest, semantic_diff

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestRuntimeEntryInventory:
    def test_inventory_validates(self):
        """入口自检：流程族存在、源码文件存在、root_kind 已登记。"""
        problems = internal_flow_catalog.validate_inventory()
        assert problems == []

    def test_every_entry_has_family_and_origin(self):
        for entry in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY:
            assert entry.family in internal_flow_catalog.PROCESS_FAMILIES
            assert entry.origin in ("message", "timer", "worker", "spawn",
                                    "startup", "api"), entry.entry_id
            assert entry.source[0] and entry.source[1]

    def test_explicit_boundaries_are_not_silently_waived(self):
        """动态 dispatch / Rust 桥接必须显式 boundary + 说明（计划 §6.2.4）。"""
        boundary_ids = {e.entry_id for e in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY
                        if e.boundary}
        assert "nonebot.matcher_dispatch" in boundary_ids
        assert "rust.promotion" in boundary_ids
        for entry in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY:
            if entry.boundary:
                assert entry.notes, f"{entry.entry_id}: boundary without reason"

    def test_root_kinds_resolve_to_entry_nodes(self):
        """已接入 root 的入口，其 root_kind 必须映射到目录入口节点。"""
        for entry in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY:
            if not entry.root_kind:
                continue
            node_id = flow_catalog.ENTRY_ROOTS.get(entry.root_kind)
            assert node_id, f"{entry.entry_id}: root_kind {entry.root_kind} unregistered"
            assert node_id in flow_catalog.NODES

    def test_anchor_symbols_exist_in_source(self):
        """Python 锚点符号必须真实可解析（生成器会硬失败，这里给友好定位）。

        Rust/其它语言锚点（如 memory_rust/native/src/promotion.rs）是显式
        跨语言边界，不走 Python AST 解析（计划 §6.2 第 4 点）。
        """
        from scripts.generate_message_flow import find_symbol

        missing = []
        for entry in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY:
            path = PROJECT_ROOT / entry.source[0]
            if not path.exists() or path.suffix != ".py":
                continue
            if find_symbol(path, entry.source[1]) is None:
                missing.append(f"{entry.entry_id}: {entry.source[1]} not in "
                               f"{entry.source[0]}")
        assert missing == []

    def test_three_coverage_denominators_are_distinct(self):
        """三层完整度分母分别报告，任何一层不冒充其他两层（计划 §13.3）。"""
        coverage = internal_flow_catalog.coverage_denominators()
        assert {"catalog", "runtime", "dataset"} <= set(coverage)
        assert coverage["runtime"]["declared_entries"] == len(
            internal_flow_catalog.RUNTIME_ENTRY_INVENTORY)
        assert coverage["catalog"]["nodes"] == len(flow_catalog.NODES)
        assert "0 样本" in coverage["dataset"]["note"]


class TestManifestIntegration:
    @pytest.fixture(scope="class")
    def manifest(self):
        data, problems = build_manifest()
        assert problems == []
        return data

    def test_manifest_carries_inventory(self, manifest):
        inv = manifest["entry_inventory"]
        assert len(inv["entries"]) == len(
            internal_flow_catalog.RUNTIME_ENTRY_INVENTORY)
        assert inv["coverage_denominators"] == \
            internal_flow_catalog.coverage_denominators()

    def test_semantic_diff_detects_node_and_body_change(self, manifest):
        """语义 diff：节点增删、body hash 变化、拓扑变化可检（计划 §6.2.7）。"""
        import copy

        same = semantic_diff(manifest, copy.deepcopy(manifest))
        assert same["nodes_added"] == [] and same["nodes_removed"] == []
        assert same["body_changed"] == []
        modified = copy.deepcopy(manifest)
        modified["nodes"].append({"id": "fake.new_node", "label": "x",
                                  "lane": "web", "kind": "state"})
        diff = semantic_diff(manifest, modified)
        assert diff["nodes_added"] == ["fake.new_node"]
        stripped = copy.deepcopy(manifest)
        for node in stripped["nodes"]:
            node.get("source_ref", {}).pop("body_hash", None)
        diff2 = semantic_diff(manifest, stripped)
        assert diff2["body_changed"], "body_hash removal must be detected"
