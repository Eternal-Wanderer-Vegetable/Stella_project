# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""check_release_hashes 的行为测试：发布字节必须等于验收字节。"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.check_release_hashes import load_accepted_hashes, verify_products


def _write_report(reports_dir: Path, subdir: str, sha: str, status: str = "pass") -> Path:
    report_dir = reports_dir / subdir
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / "install-test-report.json"
    report.write_text(
        json.dumps(
            {
                "status": status,
                "installer": f"{subdir}-setup.exe",
                "installer_sha256": sha,
                "exit_code": 0,
            }
        ),
        encoding="utf-8",
    )
    return report


def _exe(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_accepted_hashes_requires_pass_status(tmp_path):
    sha = _sha(b"installer-bytes")
    _write_report(tmp_path / "reports", "oneclick-python-offline", sha)
    accepted = load_accepted_hashes(tmp_path / "reports")
    assert sha in accepted
    assert accepted[sha]["exit_code"] == 0

    _write_report(
        tmp_path / "reports2", "oneclick-python-offline", sha, status="fail"
    )
    with pytest.raises(SystemExit, match="pass"):
        load_accepted_hashes(tmp_path / "reports2")


def test_accepted_hashes_rejects_missing_digest_or_empty_dir(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "stale.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match=r"installer_sha256|通过"):
        load_accepted_hashes(reports)
    _write_report(reports, "job", "tooshort")
    with pytest.raises(SystemExit, match=r"installer_sha256"):
        load_accepted_hashes(reports)


def test_verify_products_accepts_tested_bytes_and_rejects_drift(tmp_path):
    tested = b"accepted-installer-bytes"
    untested = b"rebuilt-installer-bytes"
    reports = tmp_path / "reports"
    _write_report(reports, "oneclick-python-offline", _sha(tested))
    _write_report(reports, "oneclick-rust-offline", _sha(untested))
    accepted = load_accepted_hashes(reports)

    products = tmp_path / "products"
    _exe(products / "Stella-OneClick-Python-Offline-v1.exe", tested)
    verify_products(products, ".exe", accepted)  # 全部匹配，不抛

    _exe(products / "Stella-OneClick-Rust-Offline-v1.exe", b"drifted")
    with pytest.raises(SystemExit, match="拒绝发布"):
        verify_products(products, ".exe", accepted)


def test_verify_products_requires_installers_present(tmp_path):
    reports = tmp_path / "reports"
    _write_report(reports, "job", "a" * 64)
    accepted = load_accepted_hashes(reports)
    products = tmp_path / "products"
    shutil.rmtree(products, ignore_errors=True)
    products.mkdir()
    with pytest.raises(SystemExit, match="没有"):
        verify_products(products, ".exe", accepted)
