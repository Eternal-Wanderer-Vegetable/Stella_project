#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
"""Check maintained Markdown, migration anchors, and agent state with stdlib only.

Dated archives are link targets, not lint inputs. Network links are not fetched.
Run directly: python scripts/check_docs.py [--root PATH].
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ARCHIVES = ("docs/plans/", "docs/reports/", "docs/migration/")
PAIRED = ("guides", "architecture", "reference", "development", "history")


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Exclude fenced examples; keep original line numbers for diagnostics."""
    result = []
    fence = ""
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match:
            marker = match[1]
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ""
            continue
        if not fence:
            result.append((number, line))
    return result


def slug(title: str) -> str:
    title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", title)
    title = re.sub(r"<[^>]*>", "", title).strip().lower()
    return "".join(
        c for c in title
        if c in "-_ " or c.isalnum() or unicodedata.category(c).startswith("M")
    ).replace(" ", "-")


def anchors(text: str) -> set[str]:
    counts: dict[str, int] = {}
    result = set()
    for _, line in prose_lines(text):
        result.update(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)["\']', line))
        match = re.match(r"^#{1,6}\s+(.+?)(?:\s+#+)?$", line)
        if match:
            base = slug(match[1])
            count = counts.get(base, 0)
            counts[base] = count + 1
            result.add(base + (f"-{count}" if count else ""))
    return result


def links(text: str) -> list[tuple[int, str]]:
    """Inline/image links with balanced parentheses and reference definitions."""
    result = []
    for number, line in prose_lines(text):
        line = re.sub(r"(`+).*?\1", "", line)
        definition = re.match(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)", line)
        if definition:
            result.append((number, definition[1].strip("<>")))
        for match in re.finditer(r"!?\[[^\]\n]*\]\(", line):
            start = match.end()
            depth = 1
            end = start
            while end < len(line) and depth:
                char = line[end]
                if char == "\\":
                    end += 2
                    continue
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                end += 1
            if depth:
                continue
            target = line[start:end-1].strip()
            if target.startswith("<") and ">" in target:
                target = target[1:target.index(">")]
            else:
                target = re.sub(r'\s+["\'].*["\']$', "", target)
            result.append((number, target))
    return result


def maintained_files(root: Path) -> list[Path]:
    fixed = [
        "AGENTS.md", "CLAUDE.md", "README.md", "README.en.md", "START_GUI.md",
        "progress.md", "session-handoff.md", ".github/CONTRIBUTING.md",
        "cli/README.md", "desktop/README.md", "stella-installer/README.md",
        "release_assets/VM-MATRIX.md", "release_assets/RELEASE_NOTES_TEMPLATE.md",
    ]
    docs = [p for p in (root / "docs").rglob("*.md")
            if not p.relative_to(root).as_posix().startswith(ARCHIVES)]
    return sorted(set(docs + [root / p for p in fixed if (root / p).is_file()]))


def check(root: Path) -> tuple[list[str], dict[str, int]]:
    root = root.resolve()
    problems: list[str] = []
    files = maintained_files(root)
    cache: dict[Path, set[str]] = {}
    link_count = 0
    for source in files:
        for number, raw in links(source.read_text(encoding="utf-8")):
            url = urlsplit(raw)
            if url.scheme or url.netloc:
                continue
            link_count += 1
            path = unquote(url.path)
            target = (root / path.lstrip("/") if path.startswith("/")
                      else source.parent / path).resolve()
            label = f"{source.relative_to(root).as_posix()}:{number}"
            if not target.is_relative_to(root):
                problems.append(f"{label}: link escapes repository: {raw}")
            elif not target.exists():
                problems.append(f"{label}: missing target: {raw}")
            elif url.fragment and target.is_file() and target.suffix == ".md":
                if target not in cache:
                    cache[target] = anchors(target.read_text(encoding="utf-8"))
                if unquote(url.fragment) not in cache[target]:
                    problems.append(f"{label}: missing anchor: {raw}")

    for folder in PAIRED:
        for page in (root / "docs" / folder).glob("*.md"):
            name = page.name
            pair = name.replace(".en.md", ".md") if name.endswith(".en.md") else name[:-3] + ".en.md"
            if not page.with_name(pair).is_file():
                problems.append(f"{page.relative_to(root)}: missing language pair: {pair}")
    agents = root / "AGENTS.md"
    if not agents.is_file():
        problems.append("AGENTS.md: missing agent entry")
    elif len(agents.read_text(encoding="utf-8").splitlines()) > 200:
        problems.append("AGENTS.md: exceeds the 200-line routing budget")

    map_path = root / "docs/documentation-map.json"
    old_anchor_count = 0
    try:
        mapping = json.loads(map_path.read_text(encoding="utf-8"))
        for old, new in mapping["redirects"].items():
            if not (root / old).is_file() or not (root / new).is_file():
                problems.append(f"{map_path.name}: missing redirect endpoint: {old} -> {new}")
        for old, entries in mapping["anchors"].items():
            source = root / old
            old_ids = anchors(source.read_text(encoding="utf-8")) if source.is_file() else set()
            for fragment, target in entries.items():
                old_anchor_count += 1
                dest = root / target["path"]
                dest_ids = anchors(dest.read_text(encoding="utf-8")) if dest.is_file() else set()
                if fragment not in old_ids or target["fragment"] not in dest_ids:
                    problems.append(f"{old}#{fragment}: migration anchor missing at source or target")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        problems.append(f"documentation-map.json: invalid or missing map: {exc}")

    try:
        state = json.loads((root / "feature_list.json").read_text(encoding="utf-8"))
        features = state["features"]
        ids = [f["id"] for f in features]
        if len(ids) != len(set(ids)):
            problems.append("feature_list.json: duplicate feature IDs")
        for feature in features:
            if feature["status"] not in {"planned", "in_progress", "blocked", "done"}:
                problems.append(f"{feature['id']}: invalid status")
            if not feature["done_criteria"]:
                problems.append(f"{feature['id']}: missing done criteria")
            if feature["status"] == "done" and not feature["evidence"]:
                problems.append(f"{feature['id']}: done without evidence")
            for dependency in feature["dependencies"]:
                if dependency not in ids or dependency == feature["id"]:
                    problems.append(f"{feature['id']}: invalid dependency {dependency}")
        running = [f["id"] for f in features if f["status"] == "in_progress"]
        active = state["active_feature"]
        if len(running) > 1 or (running and active != running[0]) or (active is not None and active not in ids):
            problems.append("feature_list.json: inconsistent active feature")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        problems.append(f"feature_list.json: invalid or missing state: {exc}")
    for path in ["progress.md", "session-handoff.md"]:
        if not (root / path).is_file():
            problems.append(f"{path}: missing session state")
    return problems, {"files": len(files), "local_links": link_count, "migration_anchors": old_anchor_count}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    problems, counts = check(args.root)
    for problem in problems:
        print(problem)
    print(json.dumps({"ok": not problems, "errors": len(problems), **counts}, ensure_ascii=False))
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
