#!/usr/bin/env python3
"""Build the release manifest and SHA256SUMS for the final products (WP14).

Binds every published asset to its exact bytes: release-manifest.json
records schema, release version, build id and per-asset {sha256, size};
SHA256SUMS.txt is the classic user-verifiable companion. The manifest
does NOT sign anything - it makes the "published bytes == acceptance
bytes == user bytes" chain checkable by scripts and end users.

Usage:
    python scripts/build_release_manifest.py \
        --products dist/products --release-version 5.1.2 \
        --build-id run-123-1 [--out-dir dist/products]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

MANIFEST_NAME = "release-manifest.json"
SUMS_NAME = "SHA256SUMS.txt"
# 这些文件由本脚本生成，不进入资产清单本身
GENERATED_NAMES = {MANIFEST_NAME, SUMS_NAME}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    products_dir: Path, *, release_version: str, build_id: str
) -> dict:
    assets = []
    for path in sorted(products_dir.iterdir()):
        if not path.is_file() or path.name in GENERATED_NAMES:
            continue
        assets.append(
            {
                "name": path.name,
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    if not assets:
        raise SystemExit(f"发布目录没有任何资产：{products_dir}")
    return {
        "schema_version": 1,
        "release_version": release_version,
        "build_id": build_id,
        "assets": assets,
    }


def write_sums(manifest: dict, out_path: Path) -> None:
    lines = [
        f"{asset['sha256']}  {asset['name']}" for asset in manifest["assets"]
    ]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_assets_dir(manifest: dict, assets_dir: Path) -> None:
    """校验一个目录里的资产与清单逐字节一致（发布后回读 / 本地复核通用）。"""
    failures = []
    for asset in manifest["assets"]:
        path = assets_dir / asset["name"]
        if not path.is_file():
            failures.append(f"{asset['name']}：缺失")
            continue
        actual_size = path.stat().st_size
        if actual_size != asset["size"]:
            failures.append(f"{asset['name']}：大小 {actual_size} ≠ {asset['size']}")
            continue
        actual = sha256_file(path)
        if actual != asset["sha256"]:
            failures.append(f"{asset['name']}：SHA-256 {actual} ≠ {asset['sha256']}")
    if failures:
        raise SystemExit(
            "资产与发布清单不一致：\n" + "\n".join(failures)
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--release-version",
                        help="写入清单（生成模式必需；verify 模式不需要——"
                             "版本已在清单文件里）")
    parser.add_argument("--build-id", default="")
    parser.add_argument("--out-dir", type=Path,
                        help="清单与 SHA256SUMS 输出目录（默认 --products）")
    parser.add_argument("--verify", type=Path, metavar="DIR",
                        help="不生成，只校验 DIR 里的资产是否与清单一致")
    args = parser.parse_args()
    products = args.products.resolve()
    manifest_path = products / MANIFEST_NAME
    if args.verify is not None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verify_assets_dir(manifest, args.verify.resolve())
        print(f"[manifest] 回读校验通过：{args.verify}")
        return 0
    if not args.release_version:
        parser.error("生成模式需要 --release-version")
    manifest = build_manifest(
        products, release_version=args.release_version, build_id=args.build_id
    )
    out_dir = args.out_dir.resolve() if args.out_dir else products
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_sums(manifest, out_dir / SUMS_NAME)
    print(
        f"[manifest] {len(manifest['assets'])} 个资产已登记"
        f"（{MANIFEST_NAME} / {SUMS_NAME}）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
