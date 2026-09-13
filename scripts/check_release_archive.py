#!/usr/bin/env python3
"""Reject runtime payloads from a standalone release archive."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path, PurePosixPath

FORBIDDEN_COMPONENTS = frozenset(
    {"runtime", "napcat", "models", "llama-server"}
)


def forbidden_members(archive: Path) -> list[str]:
    """Return archive members containing a forbidden path component."""
    with zipfile.ZipFile(archive) as bundle:
        return [
            info.filename
            for info in bundle.infolist()
            if set(PurePosixPath(info.filename).parts) & FORBIDDEN_COMPONENTS
        ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()

    matches = forbidden_members(args.archive)
    if not matches:
        return 0
    print(f"forbidden release content in {args.archive}:")
    for member in matches:
        print(f"  {member}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
