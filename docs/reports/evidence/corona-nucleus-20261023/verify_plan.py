"""Validate the dated planning deliverables; run from the repository root.
No Bot imports, user configuration reads, network calls, or business data writes.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import re
import runpy
from pathlib import Path
from urllib.parse import unquote, urlsplit

PLAN = "docs/plans/2026-10-23-corona-nucleus-engineering-plan.md"
INVENTORY = "docs/plans/2026-10-23-corona-nucleus-inventory.json"
EVIDENCE = "docs/reports/evidence/corona-nucleus-20261023"


def validate_dag(data):
    packages = data["work_packages"]
    ids = {p["id"] for p in packages}
    assert len(ids) == len(packages), "duplicate work package"
    visited, stack = set(), set()

    def visit(ident):
        assert ident in ids, f"unknown dependency: {ident}"
        assert ident not in stack, f"dependency cycle: {ident}"
        if ident in visited:
            return
        stack.add(ident)
        package = next(p for p in packages if p["id"] == ident)
        for dep in package["depends_on"]:
            visit(dep)
        stack.remove(ident)
        visited.add(ident)

    for ident in ids:
        visit(ident)
    return len(ids)


def collect_routes(root):
    result = set()
    for path in sorted((root / "webui/routers").glob("*.py")):
        tree = ast.parse(path.read_text())
        prefixes = {}
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "APIRouter"
            ):
                prefix = next(
                    (
                        ast.literal_eval(k.value)
                        for k in node.value.keywords
                        if k.arg == "prefix"
                    ),
                    "",
                )
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        prefixes[target.id] = prefix
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in node.decorator_list:
                if (
                    not isinstance(d, ast.Call)
                    or not isinstance(d.func, ast.Attribute)
                    or d.func.attr
                    not in {"get", "post", "put", "patch", "delete", "websocket"}
                ):
                    continue
                if d.args and isinstance(d.args[0], ast.Constant):
                    route = (
                        prefixes.get(getattr(d.func.value, "id", ""), "")
                        + d.args[0].value
                    )
                    result.add(
                        (
                            d.func.attr.upper(),
                            route,
                            path.relative_to(root).as_posix(),
                            node.name,
                            node.lineno,
                        )
                    )
    return result


def verify(root):
    data = json.loads((root / INVENTORY).read_text())
    count = validate_dag(data)
    plan = (root / PLAN).read_text()
    for package in data["work_packages"]:
        assert f'<a id="{package["id"].lower()}"></a>' in plan, package["id"]
        for file in package["existing_files"]:
            assert (root / file).is_file(), file
        assert package["status"] == "planned", (
            "planning must not claim implementation complete"
        )
    for source in data["source_inventory"]:
        assert (
            hashlib.sha256((root / source["path"]).read_bytes()).hexdigest()
            == source["sha256"]
        ), f"source drift: {source['path']}"
    actual = collect_routes(root)
    routes = data["webui_routes"]
    expected = {
        (r["method"], r["path"], r["source"], r["symbol"], r["line"]) for r in routes
    }
    assert len(expected) == len(routes), "duplicate endpoint record"
    assert expected == actual, {
        "missing": sorted(actual - expected),
        "extra": sorted(expected - actual),
    }
    assert all(
        r["proposed_owner"] in {"corona", "nucleus", "split-config-and-business"}
        for r in routes
    )
    keys = [r["key"] for r in data["configuration_keys"]]
    assert len(set(keys)) == len(keys) and all(
        re.fullmatch("[A-Z][A-Z0-9_]*", k) for k in keys
    )
    assert not any(k.endswith("_") for k in keys), (
        "endpoint prefix mistaken for complete configuration key"
    )
    scenarios = data["acceptance_scenarios"]
    assert len({s["id"] for s in scenarios}) == len(scenarios)
    assert all(s["status"] == "not_run_for_new_architecture" for s in scenarios)
    checks = runpy.run_path(str(root / "scripts/check_docs.py"))
    link_count = 0
    for rel in [PLAN, EVIDENCE + "/README.md"]:
        source = root / rel
        for line, target in checks["links"](source.read_text()):
            url = urlsplit(target)
            if url.scheme or url.netloc:
                continue
            dest = (source.parent / unquote(url.path)).resolve()
            assert dest.is_relative_to(root), f"link escapes root: {rel}:{line}"
            assert dest.exists(), f"broken link: {rel}:{line} {target}"
            if url.fragment:
                assert unquote(url.fragment) in checks["anchors"](dest.read_text()), (
                    f"broken anchor: {target}"
                )
            link_count += 1
    manifest = json.loads((root / EVIDENCE / "manifest.json").read_text())
    for record in manifest["files"]:
        path = (root / EVIDENCE / record["path"]).resolve()
        assert path.is_relative_to(root / EVIDENCE), (
            "evidence path escapes evidence root"
        )
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"], (
            f"evidence hash mismatch: {record['path']}"
        )
    commands = json.loads((root / EVIDENCE / "graph-commands.json").read_text())
    records = {r["name"]: r for r in commands}
    for record in commands:
        if record.get("superseded_by"):
            assert record["superseded_by"] in records
            continue
        summary = record.get("summary", {})
        assert not summary.get("partial") and not summary.get("truncated"), (
            f"incomplete graph result: {record['name']}"
        )
        assert record.get("output_complete", True), record["name"]
    for result in ["config-probe-result.json", "framework-probe-result.json"]:
        assert isinstance(json.loads((root / EVIDENCE / result).read_text()), dict)
    negative = copy.deepcopy(data)
    negative["work_packages"][0]["depends_on"] = [negative["work_packages"][-1]["id"]]
    try:
        validate_dag(negative)
    except AssertionError:
        negative_cycle_rejected = True
    else:
        raise AssertionError("validator accepted a dependency cycle")
    return {
        "ok": True,
        "work_packages": count,
        "source_fingerprints": len(data["source_inventory"]),
        "webui_routes": len(routes),
        "configuration_keys": len(keys),
        "acceptance_scenarios": len(scenarios),
        "archive_links_checked": link_count,
        "evidence_hashes": len(manifest["files"]),
        "negative_dependency_cycle_rejected": negative_cycle_rejected,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(verify(args.root.resolve()), ensure_ascii=False, indent=2))
