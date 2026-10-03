#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""内部流程 manifest 生成器（计划 §6.2）：目录语义 × 源码闭包 → 版本化图。

- 输入：``core/observability/flow_catalog.py``（语义身份、边、边界）与
  各节点 ``source`` 指向的源码符号（AST 解析），以及
  ``core/observability/internal_flow_catalog.py``（运行入口 inventory、
  流程族、显式边界、三层覆盖分母）。
- 输出：``core/observability/flows/message-flow.<content-hash>.json``
  （不可变归档，随包发布；生产无 Docker/Git 也可读）+ coverage 报告。
- **源码闭包**（计划 §6.2 第 3 点）：每个已解析符号自动列出调用点
  （带解析目标）、分支条件、循环、try/except/finally、return/raise、
  await、task spawn、with；同文件可达符号传递展开（递归/环去重、
  有界截断并诚实标注 ``truncated``）。行号只作导航，不参与身份。
- **边界对账**（第 4 点）：标准库/第三方调用解析为 external；本地解析
  失败的调用进 ``unresolved_calls`` 计数（不自动豁免）；动态 dispatch、
  Rust 桥接等显式 boundary 来自 inventory。
- 结构/条件语义变化 → body hash 变化 → 新 content hash；
  ``topology_version`` 由人工在目录变更时递增，二者独立。
- ``--check``：重新生成并与已提交 manifest 比对，任何漂移（源码改动、
  目录改动、符号消失、闭包变化）以退出码 1 阻断——CI 漂移门禁。

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

from core.observability import flow_catalog, internal_flow_catalog

DEFAULT_OUT = PROJECT_ROOT / "core" / "observability" / "flows"
GENERATOR_VERSION = 2
MANIFEST_SCHEMA_VERSION = 2

# 传递闭包边界：同文件可达符号数上限（超限截断并标 truncated）
_REACHABLE_CAP = 24
# 单符号闭包条目上限（超大函数的诚实截断）
_CLOSURE_CAP = 200


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
            counts["returns"] += 0  # 语句级闭包另计（保持特征计数兼容）
        elif isinstance(sub, ast.Await):
            counts["awaits"] += 1
        elif isinstance(sub, ast.Raise):
            counts["raises"] += 1
    return counts


def body_hash(node: ast.AST) -> str:
    """语义体 hash：``ast.unparse`` 归一化源码文本（与注释/空格/行号无关）。

    版本可移植性（CI 实测教训 2026-10-03）：``ast.dump`` 的输出随 Python
    版本变化（3.12 给函数节点加 ``type_params`` 等字段都会改变 dump 文本），
    本机生成、CI（3.10–3.12）校验必然漂移。``unparse`` 产出归一化源码，
    同一源码跨 3.10–3.14 文本一致（本仓无版本专属语法）。
    """
    payload = ast.unparse(node)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ============================================================
# 语句级闭包（计划 §6.2 第 3 点）：调用点解析 + 分支/异常/spawn/with 结构
# ============================================================

class _ModuleContext:
    """单文件解析上下文：顶层 def、类方法、import 映射。"""

    def __init__(self, file_rel: str, tree: ast.AST) -> None:
        self.file_rel = file_rel
        self.tree = tree
        self.top_functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.classes: dict[str, ast.ClassDef] = {
            node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
        }
        self.imports: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports[(alias.asname or alias.name).split(".")[0]] = \
                        alias.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = f"{node.module}"


def _resolve_call(target_expr: str, ctx: _ModuleContext,
                  class_name: str | None) -> str:
    """调用目标解析：local/self/external/unresolved（UNKNOWN 不豁免）。"""
    root = target_expr.split(".")[0]
    if target_expr.startswith("self."):
        attr = target_expr.split(".", 1)[1].split("(")[0].split(".")[0]
        cls = ctx.classes.get(class_name) if class_name else None
        methods = set()
        if cls is not None:
            methods = {m.name for m in cls.body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if attr in methods:
            return f"local:{class_name}.{attr}"
        return f"self:{target_expr}"
    if root in ctx.top_functions and "." not in target_expr:
        return f"local:{target_expr}"
    if root in ctx.imports:
        return f"external:{ctx.imports[root]}.{target_expr}" if "." in target_expr \
            else f"external:{ctx.imports[root]}"
    return "unresolved"


def closure_of(func_node: ast.AST, ctx: _ModuleContext,
               class_name: str | None) -> dict:
    """符号内语句级结构：调用/分支/循环/try/return/raise/await/spawn/with。"""
    items: list[dict] = []
    truncated = False

    def add(kind: str, line: int, detail: dict) -> None:
        nonlocal truncated
        if len(items) >= _CLOSURE_CAP:
            truncated = True
            return
        items.append({"kind": kind, "line": line, **detail})

    class_name_holder = class_name

    for sub in ast.walk(func_node):
        if isinstance(sub, ast.Call):
            try:
                target = ast.unparse(sub.func)
            except Exception:
                target = "<complex>"
            add("call", getattr(sub, "lineno", 0),
                {"target": target[:80],
                 "resolved": _resolve_call(target, ctx, class_name_holder)})
        elif isinstance(sub, (ast.If, ast.IfExp)):
            # If 与 IfExp 的条件都在 .test（IfExp 的 .body 是「then」值）
            add("branch", getattr(sub, "lineno", 0),
                {"condition": _safe_unparse(sub.test)[:120]})
        elif isinstance(sub, ast.Match):
            add("branch", getattr(sub, "lineno", 0),
                {"condition": _safe_unparse(sub.subject)[:120]})
        elif isinstance(sub, (ast.For, ast.AsyncFor, ast.While)):
            kind = "loop"
            detail = {}
            if isinstance(sub, ast.While):
                detail["condition"] = _safe_unparse(sub.test)[:120]
            else:
                detail["iterate"] = _safe_unparse(sub.iter)[:120]
            add(kind, getattr(sub, "lineno", 0), detail)
        elif isinstance(sub, ast.Try):
            add("try", getattr(sub, "lineno", 0),
                {"handlers": [_safe_unparse(h.type)[:60] if h.type else "bare"
                              for h in sub.handlers],
                 "finally": bool(sub.orelse) or bool(sub.finalbody)})
        elif isinstance(sub, ast.Return):
            add("return", getattr(sub, "lineno", 0), {})
        elif isinstance(sub, ast.Raise):
            add("raise", getattr(sub, "lineno", 0),
                {"exception": _safe_unparse(sub.exc)[:60] if sub.exc else "bare"})
        elif isinstance(sub, ast.Await):
            add("await", getattr(sub, "lineno", 0), {})
        elif isinstance(sub, (ast.With, ast.AsyncWith)):
            add("with", getattr(sub, "lineno", 0),
                {"async": isinstance(sub, ast.AsyncWith),
                 "context": _safe_unparse(sub.items[0].context_expr)[:80]
                 if sub.items else ""})

    # spawn 站点：create_task/ensure_future/run_in_executor
    _spawn_names = ("create_task", "ensure_future", "run_in_executor")
    spawns = [
        i for i in items if i["kind"] == "call"
        and (i["target"].split(".")[0].split("(")[0] in _spawn_names
             or i["target"].rsplit(".", 1)[-1].split("(")[0] in _spawn_names)
    ]
    return {
        "items": items,
        "counts": _count_kinds(items),
        "spawn_lines": sorted({i["line"] for i in spawns}),
        "truncated": truncated,
    }


def _safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return "<complex>"


def _count_kinds(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    return counts


def reachable_symbols(ctx: _ModuleContext, symbol: str,
                      cap: int = _REACHABLE_CAP) -> tuple[list[str], bool]:
    """同文件传递可达符号（计划 §6.2 三层目录的符号层）：递归/环去重。"""
    seen: list[str] = []
    queue: list[str] = [symbol]
    truncated = False
    while queue:
        current = queue.pop(0)
        node = _find_in_ctx(ctx, current)
        if node is None:
            continue
        class_name = current.split(".")[0] if "." in current else None
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            try:
                target = ast.unparse(sub.func)
            except Exception:
                continue
            resolved = _resolve_call(target, ctx, class_name)
            if not resolved.startswith("local:"):
                continue
            local = resolved.split(":", 1)[1]
            if local in (current, symbol) or local in seen:
                continue  # 递归/环去重
            if len(seen) >= cap:
                truncated = True
                continue
            seen.append(local)
            queue.append(local)
    return seen, truncated


def _find_in_ctx(ctx: _ModuleContext, symbol: str) -> ast.AST | None:
    if "." in symbol:
        cls_name, method = symbol.split(".", 1)
        cls = ctx.classes.get(cls_name)
        if cls is None:
            return None
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and item.name == method:
                return item
        return None
    return ctx.top_functions.get(symbol)


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
    problems += list(internal_flow_catalog.validate_inventory())
    nodes = []
    resolved = 0
    source_closure: dict[str, dict] = {}
    unresolved_calls = 0
    reachable_total = 0
    truncated_nodes: list[str] = []

    # 每文件只解析一次（125 节点共享 AST 上下文）
    ctx_cache: dict[str, _ModuleContext] = {}

    def module_ctx(file_rel: str) -> _ModuleContext | None:
        if file_rel not in ctx_cache:
            path = PROJECT_ROOT / file_rel
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                ctx_cache[file_rel] = None  # type: ignore[assignment]
                return None
            ctx_cache[file_rel] = _ModuleContext(file_rel, tree)
        return ctx_cache[file_rel]

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
            ctx = module_ctx(file_rel)
            found = find_symbol(PROJECT_ROOT / file_rel, symbol) if ctx else None
            if found is None or ctx is None:
                problems.append(
                    f"node {node_id}: symbol {symbol} not found in {file_rel}")
            else:
                resolved += 1
                class_name = symbol.split(".")[0] if "." in symbol else None
                closure = closure_of(found, ctx, class_name)
                unresolved_calls += closure["counts"].get("unresolved", 0) + sum(
                    1 for i in closure["items"]
                    if i["kind"] == "call" and i["resolved"] == "unresolved")
                reach, reach_truncated = reachable_symbols(ctx, symbol)
                if reach_truncated:
                    truncated_nodes.append(node_id)
                reachable_total += len(reach)
                entry["source_ref"] = {
                    "file": file_rel,
                    "symbol": symbol,
                    "body_hash": body_hash(found),
                    "features": structural_features(found),
                }
                source_closure[node_id] = {
                    "entry": closure,
                    "reachable_symbols": reach,
                    "reachable_truncated": reach_truncated,
                }
        nodes.append(entry)

    # 入口 inventory（计划 §6.2 第 1 点）：声明入口 + 流程族 + 显式边界
    entries_serialized = [
        {
            "entry_id": e.entry_id, "family": e.family, "root_kind": e.root_kind,
            "source": {"file": e.source[0], "symbol": e.source[1]},
            "origin": e.origin, "notes": e.notes, "boundary": e.boundary,
        }
        for e in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY
    ]
    boundaries = [
        {"entry_id": e.entry_id, "boundary": e.boundary, "reason": e.notes,
         "source": {"file": e.source[0], "symbol": e.source[1]}}
        for e in internal_flow_catalog.RUNTIME_ENTRY_INVENTORY if e.boundary
    ]

    derived_or_opaque = sum(
        1 for n in flow_catalog.NODES.values() if n.derived or n.opaque)
    coverage = {
        "total_nodes": len(flow_catalog.NODES),
        "source_resolved": resolved,
        "derived_or_opaque": derived_or_opaque,
        "edges": len(flow_catalog.EDGES),
        "lanes": len(flow_catalog.LANES),
        "core_unresolved_allowed": 0,
        "closure_sites": sum(
            sum(c["entry"]["counts"].values()) for c in source_closure.values()
        ) if source_closure else 0,
        "unresolved_calls": unresolved_calls,
        "reachable_symbols": reachable_total,
        "reachable_truncated_nodes": truncated_nodes,
        "declared_runtime_entries": len(entries_serialized),
        "explicit_boundaries": len(boundaries),
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
        "source_closure": source_closure,
        "entry_inventory": {
            "families": [
                {"family_id": f.family_id, "label": f.label,
                 "description": f.description, "milestone": f.milestone}
                for f in internal_flow_catalog.PROCESS_FAMILIES.values()
            ],
            "entries": entries_serialized,
            "boundaries": boundaries,
            "coverage_denominators":
                internal_flow_catalog.coverage_denominators(),
        },
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


def semantic_diff(old: dict, new: dict) -> dict:
    """两次 manifest 的语义差异（计划 §6.2 第 7 点）：节点/边/闭包签名。"""
    old_nodes = {n["id"]: n for n in old.get("nodes", [])}
    new_nodes = {n["id"]: n for n in new.get("nodes", [])}
    body_changed = [
        nid for nid, n in new_nodes.items()
        if nid in old_nodes
        and (n.get("source_ref") or {}).get("body_hash")
        != (old_nodes[nid].get("source_ref") or {}).get("body_hash")
    ]
    return {
        "nodes_added": sorted(set(new_nodes) - set(old_nodes)),
        "nodes_removed": sorted(set(old_nodes) - set(new_nodes)),
        "body_changed": sorted(body_changed),
        "edges_added": sorted(
            {(e["src"], e["dst"]) for e in new.get("edges", [])}
            - {(e["src"], e["dst"]) for e in old.get("edges", [])}),
        "edges_removed": sorted(
            {(e["src"], e["dst"]) for e in old.get("edges", [])}
            - {(e["src"], e["dst"]) for e in new.get("edges", [])}),
        "topology_changed": old.get("topology_version") != new.get("topology_version"),
    }


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
                diff = semantic_diff(data, manifest)
                print(
                    f"DRIFT: {path.name} does not match current source.\n"
                    f"semantic diff: {json.dumps(diff, ensure_ascii=False)}\n"
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
          f"{manifest['coverage']['source_resolved']} source-resolved, "
          f"{manifest['coverage']['closure_sites']} closure sites, "
          f"{manifest['coverage']['reachable_symbols']} reachable symbols)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
