#!/usr/bin/env python3
"""Verify published installer bytes are the bytes the install gate tested.

The install-test jobs install the actual EXE artifacts and record their
SHA-256 in `install-test-report.json`. Before publishing, this script
re-hashes the candidate release assets and requires every installer to
appear in an accepted report. Otherwise a rebuilt/clobbered EXE could be
published although only a different byte stream ever passed acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_accepted_hashes(reports_dir: Path) -> dict[str, dict]:
    """Collect {sha256: report_meta} from every install-test report found."""
    accepted: dict[str, dict] = {}
    for report in sorted(reports_dir.rglob("install-test-report.json")):
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"验收报告无法读取：{report}（{exc}）") from exc
        digest = str(payload.get("installer_sha256", "")).lower()
        if len(digest) != 64:
            raise SystemExit(f"验收报告缺少 installer_sha256：{report}")
        if payload.get("status") != "pass":
            raise SystemExit(f"验收报告状态不是 pass：{report}（{payload.get('status')}）")
        accepted[digest] = {
            "report": str(report),
            "installer": payload.get("installer", ""),
            "exit_code": payload.get("exit_code"),
        }
    if not accepted:
        raise SystemExit(f"未找到任何通过的安装验收报告：{reports_dir}")
    return accepted


def verify_products(products_dir: Path, suffix: str, accepted: dict[str, dict]) -> None:
    installers = sorted(
        path for path in products_dir.iterdir()
        if path.is_file() and path.name.lower().endswith(suffix)
    )
    if not installers:
        raise SystemExit(f"发布目录没有 {suffix} 安装器：{products_dir}")
    failures = []
    for installer in installers:
        digest = _sha256(installer)
        record = accepted.get(digest)
        if record is None:
            failures.append(installer.name)
            print(f"::error::{installer.name} 的 SHA-256 不在任何通过的验收报告中")
        else:
            print(
                f"[ok] {installer.name} == 验收字节"
                f"（{record['report']}，exit_code={record['exit_code']}）"
            )
    if failures:
        raise SystemExit(
            f"以下安装器的字节未通过安装验收，拒绝发布：{failures}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports", type=Path, required=True,
                        help="install-test 报告根目录（含各 matrix 子目录）")
    parser.add_argument("--products", type=Path, required=True,
                        help="发布产物目录（dist/products）")
    parser.add_argument("--suffix", default=".exe",
                        help="需要核对的安装器扩展名（默认 .exe）")
    args = parser.parse_args()
    accepted = load_accepted_hashes(args.reports)
    verify_products(args.products, args.suffix.lower(), accepted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
