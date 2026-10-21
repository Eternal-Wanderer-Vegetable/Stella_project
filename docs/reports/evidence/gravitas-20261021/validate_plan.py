#!/usr/bin/env python3
"""Validate this dated planning artifact; never import Bot/config or open user data."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit


def validate(root: Path, inventory: Path, check_hashes: bool = True) -> dict:
    data = json.loads(inventory.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["status"] == "planning_complete_implementation_not_started"
    packages = {w["id"]: w for w in data["work_packages"]}
    assert len(packages) == len(data["work_packages"]) == 10
    visited, active = set(), set()

    def visit(key):
        assert key in packages, f"unknown package: {key}"
        assert key not in active, f"dependency cycle: {key}"
        if key in visited:
            return
        active.add(key)
        for dep in packages[key]["depends_on"]:
            visit(dep)
        active.remove(key)
        visited.add(key)

    for key, package in packages.items():
        visit(key)
        assert package["status"] == "planned" and package["done_criteria"]
        for name in package["existing_files"]:
            assert (root / name).is_file(), name
    sources = {s["path"]: s for s in data["sources"]}
    for name, source in sources.items():
        p = root / name
        assert p.is_file(), name
        assert hashlib.sha256(p.read_bytes()).hexdigest() == source["sha256"], (
            f"source drift: {name}"
        )
        lines = p.read_text().splitlines()
        for symbol in source.get("symbols", []):
            assert 1 <= symbol["line"] <= symbol["end_line"] <= len(lines)
            assert symbol["name"] in lines[symbol["line"] - 1], (name, symbol)
    entries = data["runtime_entries"]
    assert len(entries) == len({e["entry_id"] for e in entries}) == 50
    for entry in entries:
        assert entry["gravitas_package"] in packages and entry["disposition"]
        assert (root / entry["source"][0]).is_file()
    invariants = {x["id"] for x in data["invariants"]}
    assert len(invariants) == 10
    scenarios = data["scenarios"]
    assert len(scenarios) == len({s["id"] for s in scenarios}) == 16
    assert {i for s in scenarios for i in s["required_invariants"]} == invariants
    assert all(s["status"] == "planned" for s in scenarios)
    evidence = root / "docs/reports/evidence/gravitas-20261021"
    for impact in data["graph_impacts"]:
        raw = json.loads((evidence / impact["evidence"]).read_text())
        assert not raw.get("partial") and not raw.get("truncated"), impact["anchor"]
        assert raw.get("risk") == impact["raw_risk"]
        assert raw.get("impactedCount") == impact["impacted_count"]
        context = json.loads((evidence / impact["caller_evidence"]).read_text())
        assert context.get("status") == "found", impact["anchor"]
    pages = [
        json.loads((evidence / f"process-page-{n}.json").read_text())
        for n in range(0, 900, 100)
    ]
    process_ids = []
    for page in pages:
        assert page.get("row_count", 0) <= 100
        process_ids.extend(
            line.split("|")[1].strip()
            for line in page["markdown"].splitlines()[2:]
            if line.startswith("|")
        )
    assert len(process_ids) == len(set(process_ids)) == 823
    sites = json.loads((evidence / "source-call-sites.json").read_text())
    assert len(sites) == 41 and all(s["file"] in sources for s in sites)
    for p in evidence.rglob("*.json"):
        json.loads(p.read_text())  # rejected captures live in TXT, never half-JSON
    spec = importlib.util.spec_from_file_location(
        "stella_docs_check", root / "scripts/check_docs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    docs = [
        root / "docs/plans/2026-10-21-gravitas-engineering-plan.md",
        evidence / "README.md",
    ]
    checked_links = 0
    for document in docs:
        for line, raw in module.links(document.read_text()):
            u = urlsplit(raw)
            if u.scheme or u.netloc:
                continue
            dest = (document.parent / unquote(u.path)).resolve()
            assert dest.is_relative_to(root) and dest.exists(), (
                document.name,
                line,
                raw,
            )
            if u.fragment:
                assert unquote(u.fragment) in module.anchors(dest.read_text()), raw
            checked_links += 1
    for scope in ("all", "compare"):
        complete = json.loads((evidence / f"detect-{scope}-complete.json").read_text())
        native = json.loads((evidence / f"detect-{scope}-structured.json").read_text())
        assert not complete.get("partial") and not complete.get("truncated")
        assert len(complete["changed_symbols"]) == complete["summary"]["changed_count"]
        assert complete["summary"] == native["summary"], "listing harness changed summary"
    hashed = 0
    if check_hashes:
        manifest = json.loads((evidence / "SHA256SUMS.json").read_text())
        excluded = {"SHA256SUMS.json", "validation-results.json"}
        current = {
            p.relative_to(evidence).as_posix()
            for p in evidence.rglob("*")
            if p.is_file() and p.name not in excluded
        }
        assert set(manifest) == current, "evidence manifest coverage mismatch"
        for name, digest in manifest.items():
            assert (
                hashlib.sha256((evidence / name).read_bytes()).hexdigest() == digest
            ), f"evidence drift: {name}"
            hashed += 1
    return {
        "ok": True,
        "work_packages": len(packages),
        "sources": len(sources),
        "runtime_entries": len(entries),
        "scenarios": len(scenarios),
        "invariants": len(invariants),
        "processes": len(process_ids),
        "source_call_sites": len(sites),
        "archive_links": checked_links,
        "evidence_hashes": hashed,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[4])
    p.add_argument("--inventory", type=Path)
    p.add_argument("--skip-hashes", action="store_true")
    args = p.parse_args()
    root = args.root.resolve()
    inventory = args.inventory or root / "docs/plans/2026-10-21-gravitas-inventory.json"
    print(
        json.dumps(validate(root, inventory, not args.skip_hashes), ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
