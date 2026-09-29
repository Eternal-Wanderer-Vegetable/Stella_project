#!/usr/bin/env python3
"""Installer size gate (S15/WP15).

Budgets live in release_assets/toolchain.json (`installer_budget_mb`).
A measured baseline earns a hard cap; an unmeasured payload class gets
recorded in the report but never fails the build (no invented numbers -
plan rule). Warn threshold defaults to 90% of the cap.

Usage:
    python scripts/check_installer_size.py --products dist/products
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLCHAIN = REPO_ROOT / "release_assets" / "toolchain.json"
BUDGET_KEY = "installer_budget_mb"


def load_budget() -> dict[str, float | None]:
    """读取体积预算；`null` = 该类别未实测、不设限（记录但不拦截）。"""
    toolchain = json.loads(TOOLCHAIN.read_text(encoding="utf-8"))
    budget = toolchain.get(BUDGET_KEY)
    if not isinstance(budget, dict):
        raise SystemExit(f"toolchain.json 缺少 {BUDGET_KEY} 体积预算")
    return {
        str(k): (float(v) if v is not None else None)
        for k, v in budget.items()
    }


def classify(name: str) -> str:
    lowered = name.lower()
    if "offline" in lowered:
        return "offline"
    return "online"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--products", type=Path, required=True)
    args = parser.parse_args()
    budget = load_budget()

    failures: list[str] = []
    warnings: list[str] = []
    report: list[dict] = []
    installers = sorted(p for p in args.products.iterdir() if p.suffix.lower() == ".exe")
    if not installers:
        raise SystemExit(f"发布目录没有安装器：{args.products}")
    for path in installers:
        size_mb = path.stat().st_size / (1024 * 1024)
        kind = classify(path.name)
        cap = budget.get(kind)
        entry = {"name": path.name, "size_mb": round(size_mb, 1), "class": kind, "cap_mb": cap}
        report.append(entry)
        if cap is None:
            print(f"[record] {path.name}: {size_mb:.1f} MB（{kind} 无预算——实测后补录）")
            continue
        if size_mb > cap:
            failures.append(f"{path.name}: {size_mb:.1f} MB 超过 {kind} 预算 {cap} MB")
        elif size_mb > cap * 0.9:
            warnings.append(f"{path.name}: {size_mb:.1f} MB 接近 {kind} 预算 {cap} MB")
        else:
            print(f"[ok] {path.name}: {size_mb:.1f} / {cap} MB")
    for line in warnings:
        print(f"::warning::{line}")
    if failures:
        for line in failures:
            print(f"::error::{line}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
