# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

from webui import status_source


def test_standalone_status_explicitly_reports_gravitas_unavailable(monkeypatch):
    monkeypatch.setattr(status_source, "_source", None)
    assert status_source.collect_status()["gravitas"] is None
