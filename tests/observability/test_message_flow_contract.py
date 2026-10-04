# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""消息流程合同测试（计划 §8.1）：目录完整性、manifest 漂移门禁、契约。

- 目录自检：边引用存在、lane/kind 合法、入口 root 有节点（store 测试的
  超集，这里再钉 manifest 视角的合同）。
- 漂移门禁：``generate_message_flow.build_manifest`` 的 content hash 必须
  与已提交 manifest 一致——改了目录或被埋点源码而没重新生成，这里红。
- 契约：manifest 形状与 webui/services/flow.spec 及 dashboard/src/api/
  flow.ts 的 FlowSpec 读取路径对齐（字段存在性 + 类型可解析）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.observability import flow_catalog
from scripts.generate_message_flow import (
    DEFAULT_OUT,
    build_manifest,
    content_hash,
)

FLOWS_DIR = Path(__file__).resolve().parents[2] / "core" / "observability" / "flows"


@pytest.fixture(scope="module")
def manifest() -> dict:
    data, problems = build_manifest()
    assert problems == []
    return data


def _committed_manifest(manifest: dict) -> dict:
    for path in sorted(FLOWS_DIR.glob("message-flow.*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("topology_version") == manifest["topology_version"]:
            return data
    pytest.fail(
        "no committed manifest for topology_version "
        f"{manifest['topology_version']}; run scripts/generate_message_flow.py"
    )


class TestCatalogContract:
    def test_manifest_internal_consistency(self, manifest):
        assert manifest["schema_version"] == 3
        assert manifest["canonicalization"] == "stella-flow-content-v1"
        assert manifest["entry_discovery"]["undeclared"] == []
        assert manifest["entry_discovery"]["missing"] == []
        assert manifest["topology_version"] == flow_catalog.TOPOLOGY_VERSION
        ids = [n["id"] for n in manifest["nodes"]]
        assert len(ids) == len(set(ids))
        id_set = set(ids)
        for edge in manifest["edges"]:
            assert edge["src"] in id_set
            assert edge["dst"] in id_set
        lane_ids = {lane[0] for lane in manifest["lanes"]}
        for node in manifest["nodes"]:
            assert node["lane"] in lane_ids

    def test_source_closure_present_for_resolved_nodes(self, manifest):
        """计划 §6.2 第 3 点：每个源码解析节点都有语句级闭包与可达符号。"""
        closure = manifest["source_closure"]
        for node in manifest["nodes"]:
            if not node.get("source_ref"):
                continue
            assert node["id"] in closure, node["id"]
            entry = closure[node["id"]]["entry"]
            assert entry["counts"], f"{node['id']}: empty closure counts"
            assert isinstance(closure[node["id"]]["reachable_symbols"], list)
        assert manifest["coverage"]["closure_sites"] > 0
        assert manifest["coverage"]["reachable_symbols"] > 0

    def test_cross_file_helpers_carry_body_hashes(self, manifest):
        """修复计划 §6.5（R4）：可达辅助符号带真实函数体 hash——辅助函数
        实现变化即可漂移 manifest（旧实现只存名字列表，漂移不可见）。"""
        closure = manifest["source_closure"]
        private = closure["ingress.private.receive"]
        helpers = private["reachable_symbols"]
        assert helpers, "私聊主链必须有可达辅助符号"
        for h in helpers:
            assert {"file", "qualname", "body_hash", "resolution"} <= set(h)
            assert h["resolution"] == "local"
            assert len(h["body_hash"]) == 16
        # 项目内 import 目标不得再统一归 external（旧探针：跨文件调用全 external）
        assert private["boundaries"], "边界分类必须显式（dynamic/native/external）"

    def test_core_truncations_resolved(self, manifest):
        """修复计划 §6.5：四个已知核心截断收口（cap 覆盖真实闭包规模）。"""
        assert manifest["coverage"]["reachable_truncated_nodes"] == []

    def test_edge_runtime_evidence_classified(self, manifest):
        """修复计划 §6.4：边标注 explicit/static_only 运行证据。"""
        kinds = {e["runtime_evidence"] for e in manifest["edges"]}
        assert kinds == {"explicit", "static_only"}
        explicit = [e for e in manifest["edges"]
                    if e["runtime_evidence"] == "explicit"]
        assert explicit, "first-batch instrumented edges must exist"

    def test_entry_inventory_in_manifest(self, manifest):
        """计划 §6.2 第 1 点：入口 inventory/流程族/显式边界随包发布。"""
        inv = manifest["entry_inventory"]
        assert inv["entries"], "runtime entry inventory must be exported"
        assert inv["families"]
        assert inv["coverage_denominators"]["catalog"] is not None
        assert inv["coverage_denominators"]["runtime"] is not None
        assert inv["coverage_denominators"]["dataset"] is not None
        for entry in inv["entries"]:
            assert entry["family"] in {f["family_id"] for f in inv["families"]}
        for boundary in inv["boundaries"]:
            assert boundary["boundary"], "explicit boundary needs a reason tag"

    def test_core_unresolved_is_zero(self, manifest):
        """每个节点要么 source 解析成功，要么显式 derived/opaque（计划 §13.2）。"""
        coverage = manifest["coverage"]
        assert coverage["core_unresolved_allowed"] == 0
        assert coverage["source_resolved"] == coverage["total_nodes"] - sum(
            1 for n in manifest["nodes"] if not n.get("source_ref")
        )
        for node in manifest["nodes"]:
            if not node.get("source_ref"):
                assert node.get("derived") or node.get("opaque"), (
                    f"{node['id']} has no source_ref and no explicit boundary"
                )
        assert coverage["source_resolved"] > 0

    def test_entry_roots_resolve(self, manifest):
        ids = {n["id"] for n in manifest["nodes"]}
        for root_kind, node_id in manifest["entry_roots"].items():
            assert node_id in ids, root_kind

    def test_hook_mappings_in_manifest(self, manifest):
        ids = {n["id"] for n in manifest["nodes"]}
        for mapping in (manifest["hook_node_ids"],
                        manifest["post_hook_node_ids"]):
            assert mapping, "hook mappings must be exported for instrumentation"
            for node_id in mapping.values():
                assert node_id in ids


class TestDriftGate:
    def test_committed_manifest_matches_source(self, manifest):
        committed = _committed_manifest(manifest)
        assert content_hash(committed) == content_hash(manifest), (
            "flow manifest is stale: catalog or instrumented sources changed "
            "without regeneration (run python scripts/generate_message_flow.py)"
        )

    def test_manifest_has_no_line_numbers_in_identity(self, manifest):
        """ID 身份与行号无关（计划 §6.1：不用行号当 ID）。"""
        for node in manifest["nodes"]:
            ref = node.get("source_ref") or {}
            assert set(ref) <= {"file", "symbol", "body_hash", "features"}, (
                f"{node['id']}: unexpected identity fields {set(ref)}"
            )
            if "features" in ref:
                assert not any(k.startswith("line") for k in ref["features"])


class TestReaderContract:
    def test_webui_spec_reader_can_serve_manifest(self, manifest):
        """webui/services/flow.spec 的随包回退路径能读到这份 manifest。"""
        from webui.services import flow as flow_service

        served = flow_service._bundled_spec(flow_catalog.TOPOLOGY_VERSION)
        assert served is not None
        assert served["topology_version"] == flow_catalog.TOPOLOGY_VERSION
        assert isinstance(served["nodes"], list)
        assert isinstance(served["edges"], list)

    def test_dashboard_types_shape(self, manifest):
        """FlowSpec TS 侧读取路径的字段全部存在（字段级合同）。"""
        required = {"id", "label", "lane", "kind"}
        for node in manifest["nodes"]:
            missing = required - set(node)
            assert not missing, (node.get("id"), missing)
        for edge in manifest["edges"]:
            assert {"src", "dst", "kind", "label"} <= set(edge)
        for lane in manifest["lanes"]:
            assert len(lane) == 2

    def test_default_output_dir_is_flows(self):
        assert DEFAULT_OUT.name == "flows"
