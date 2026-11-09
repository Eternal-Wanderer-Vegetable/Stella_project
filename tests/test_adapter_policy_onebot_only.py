# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Only OneBot V11 stays enabled while the other adapters are temporarily disabled."""

from __future__ import annotations

import json
from pathlib import Path

from stella_bootstrap.adapter_names import DEFAULT_ADAPTER_MODULES
from stella_bootstrap.adapter_policy import (
    TEMPORARILY_DISABLED_ADAPTERS,
    unavailable_adapter_reasons,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "webui" / "services" / "nonebot_adapter_catalog.json"


def _catalog_modules() -> list[str]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    items = data["adapters"] if isinstance(data, dict) else data
    return [item["module"] for item in items]


def test_onebot_v11_is_the_only_available_catalog_adapter() -> None:
    unavailable = unavailable_adapter_reasons()
    available = [module for module in _catalog_modules() if module not in unavailable]
    assert available == ["nonebot.adapters.onebot.v11"]
    assert DEFAULT_ADAPTER_MODULES == ("nonebot.adapters.onebot.v11",)


def test_policy_blocks_keep_their_own_reason() -> None:
    unavailable = unavailable_adapter_reasons()
    assert unavailable["nonebot.adapters.mail"] == "mailSecurityCompatibility"
    assert unavailable["nonebot.adapters.villa"] == "temporarilyDisabled"


def test_disabled_adapter_packages_are_not_runtime_requirements() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    active = [
        line.split(">")[0].split("=")[0].split(";")[0].strip()
        for line in requirements
        if line.strip().startswith("nonebot-adapter-")
    ]
    assert active == ["nonebot-adapter-onebot"]
    assert len(TEMPORARILY_DISABLED_ADAPTERS) == 28


def test_every_reason_has_dashboard_text() -> None:
    for locale in ("zh-CN", "en-US"):
        path = ROOT / "dashboard" / "src" / "i18n" / "locales" / f"{locale}.json"
        text = json.loads(path.read_text(encoding="utf-8"))
        assert "temporarilyDisabled" in json.dumps(text, ensure_ascii=False), locale
