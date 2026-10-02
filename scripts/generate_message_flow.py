#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""消息流程 manifest 生成器（计划 §6.1）：目录语义 × 源码 AST → 版本化图。

- 输入：``core/observability/flow_catalog.py``（语义身份、边、边界）与
  各节点 ``source`` 指向的源码符号（AST 解析）。
- 输出：``core/observability/flows/message-flow.<content-hash>.json``
  （不可变归档，随包发布；生产无 Docker/Git 也可读）+ coverage 报告。
- 结构/条件语义变化 → body hash 变化 → 新 content hash；``topology_version``
  由人工在目录变更时递增，二者独立（rename 显式迁移 ID，见计划 §6.1）。
- ``--check``：重新生成并与已提交 manifest 比对，任何漂移（源码改动、
  目录改动、符号消失）以退出码 1 阻断——CI 漂移门禁。

用法::

    python scripts/generate_message_flow.py --check           # CI 门禁
    python scripts/generate_message_flow.py                   # 重新生成
    python scripts/generate_message_flow.py --output <dir>    # 自定义输出
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.observability import flow_catalog

DEFAULT_OUT = PROJECT_ROOT / "core" / "observability" / "flows"
GENERATOR_VERSION = flow_catalog.GENERATOR_VERSION
MANIFEST_SCHEMA_VERSION = 1


# ============================================================
# AST 解析
# ============================================================

def _iter_named_defs(tree: ast.AST) -> Iterator[tuple[str, ast.AST]]:
    """(qualified-ish name, def) 对：模块级函数/类方法。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node


def find_symbol(file_path: Path, symbol: str) -> ast.AST | None:
    """在文件里定位符号：顶层函数、``Class.method``、或装饰器包裹的 handler。"""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    if "." in symbol:
        cls_name, method = symbol.split(".", 1)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and item.name == method:
                        return item
        return None
    for name, node in _iter_named_defs(tree):
        if name == symbol:
            return node
    return None


def structural_features(node: ast.AST) -> dict:
    """符号内结构特征：call/分支/循环/异常/返回/await/spawn/raise 计数。"""
    counts = {
        "calls": 0, "branches": 0, "loops": 0, "try": 0,
        "returns": 0, "awaits": 0, "spawns": 0, "raises": 0,
    }
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            counts["calls"] += 1
            func = sub.func
            name = getattr(func, "attr", "") or getattr(func, "id", "")
            if name in ("create_task", "ensure_future", "run_in_executor"):
                counts["spawns"] += 1
        elif isinstance(sub, (ast.If, ast.IfExp, ast.Match)):
            counts["branches"] += 1
        elif isinstance(sub, (ast.For, ast.While, ast.AsyncFor)):
            counts["loops"] += 1
        elif isinstance(sub, ast.Try):
            counts["try"] += 1
        elif isinstance(sub, ast.Return):
            counts["returns"] += 1
        elif isinstance(sub, ast.Await):
            counts["awaits"] += 1
        elif isinstance(sub, ast.Raise):
            counts["raises"] += 1
    return counts


def body_hash(node: ast.AST) -> str:
    """语义体 hash：``ast.dump`` 归一化（与注释/空格/行号无关）。"""
    payload = ast.dump(node, annotate_fields=False, include_attributes=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ============================================================
# Manifest 组装
# ============================================================

def git_revision() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def build_manifest() -> tuple[dict, list[str]]:
    """返回 (manifest, problems)。problems 非空 = 核心 unresolved，阻断。"""
    problems = list(flow_catalog.validate())
    nodes = []
    resolved = 0
    for node_id, spec in sorted(flow_catalog.NODES.items()):
        entry: dict = {
            "id": node_id,
            "label": spec.label,
            "lane": spec.lane,
            "kind": spec.kind,
        }
        if spec.derived:
            entry["derived"] = True
        if spec.opaque:
            entry["opaque"] = True
        if spec.source:
            file_rel, symbol = spec.source
            path = PROJECT_ROOT / file_rel
            found = find_symbol(path, symbol)
            if found is None:
                problems.append(
                    f"node {node_id}: symbol {symbol} not found in {file_rel}")
            else:
                resolved += 1
                entry["source_ref"] = {
                    "file": file_rel,
                    "symbol": symbol,
                    "body_hash": body_hash(found),
                    "features": structural_features(found),
                }
        nodes.append(entry)

    derived_or_opaque = sum(
        1 for n in flow_catalog.NODES.values() if n.derived or n.opaque)
    coverage = {
        "total_nodes": len(flow_catalog.NODES),
        "source_resolved": resolved,
        "derived_or_opaque": derived_or_opaque,
        "edges": len(flow_catalog.EDGES),
        "lanes": len(flow_catalog.LANES),
        "core_unresolved_allowed": 0,
    }

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "topology_version": flow_catalog.TOPOLOGY_VERSION,
        "generator_version": GENERATOR_VERSION,
        "lanes": [list(lane) for lane in flow_catalog.LANES],
        "nodes": nodes,
        "edges": [
            {"src": e.src, "dst": e.dst, "kind": e.kind, "label": e.label}
            for e in flow_catalog.EDGES
        ],
        "entry_roots": dict(flow_catalog.ENTRY_ROOTS),
        "hook_node_ids": dict(flow_catalog.HOOK_NODE_IDS),
        "post_hook_node_ids": dict(flow_catalog.POST_HOOK_NODE_IDS),
        "coverage": coverage,
    }
    return manifest, problems


def content_hash(manifest: dict) -> str:
    """内容 hash：排除 source_revision（每次构建独立标识，计划 §6.1）。"""
    payload = {k: v for k, v in manifest.items() if k != "source_revision"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def with_revision(manifest: dict) -> dict:
    manifest["source_revision"] = git_revision()
    return manifest


# ============================================================
# 命令行
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="与已提交 manifest 比对；漂移时退出码 1")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT,
                        help="manifest 输出目录")
    args = parser.parse_args()

    manifest, problems = build_manifest()
    if problems:
        for p in problems:
            print(f"COVERAGE PROBLEM: {p}", file=sys.stderr)
        print(f"generation blocked: {len(problems)} problem(s)", file=sys.stderr)
        return 2
    manifest = with_revision(manifest)
    digest = content_hash(manifest)

    if args.check:
        existing = sorted(args.output.glob("message-flow.*.json"))
        for path in existing:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("topology_version") == manifest["topology_version"]:
                if content_hash(data) == digest:
                    print(f"check ok: {path.name} matches current source")
                    return 0
                print(
                    f"DRIFT: {path.name} does not match current source.\n"
                    "The flow catalog or instrumented sources changed; "
                    "regenerate with `python scripts/generate_message_flow.py` "
                    "and commit the new manifest.",
                    file=sys.stderr,
                )
                return 1
        print(
            f"DRIFT: no manifest for topology_version "
            f"{manifest['topology_version']} under {args.output}.\n"
            "Regenerate with `python scripts/generate_message_flow.py`.",
            file=sys.stderr,
        )
        return 1

    args.output.mkdir(parents=True, exist_ok=True)
    out_path = args.output / f"message-flow.{digest[:12]}.json"
    out_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"generated {out_path.relative_to(PROJECT_ROOT)} "
          f"(topology {manifest['topology_version']}, content {digest[:12]}, "
          f"{manifest['coverage']['total_nodes']} nodes, "
          f"{manifest['coverage']['source_resolved']} source-resolved)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
