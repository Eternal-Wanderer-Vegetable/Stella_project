# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Adapter module selection and fail-closed registration checks."""

from __future__ import annotations

import types

import pytest
from nonebot.adapters import Adapter

from core.transport import adapter_loader


class _TestAdapter(Adapter):
    @classmethod
    def get_name(cls) -> str:
        return "Test Adapter"


class _Driver:
    def __init__(self, failure: Exception | None = None) -> None:
        self._adapters: dict[str, type[Adapter]] = {}
        self.registered: list[type[Adapter]] = []
        self.config = types.SimpleNamespace(driver="~fastapi")
        self.failure = failure

    def register_adapter(self, adapter_class: type[Adapter]) -> None:
        if self.failure:
            raise self.failure
        self.registered.append(adapter_class)
        self._adapters[adapter_class.get_name()] = adapter_class


def _module(adapter_class: type | None = _TestAdapter) -> types.ModuleType:
    module = types.ModuleType("fake_adapter")
    if adapter_class is not None:
        module.Adapter = adapter_class
    return module


def test_parse_defaults_and_explicit_disable_values():
    assert adapter_loader.parse_adapter_modules(None) == (
        "nonebot.adapters.onebot.v11",
    )
    for value in ("", "   ", "none", "OFF", "disabled"):
        assert adapter_loader.parse_adapter_modules(value) == ()


def test_parse_comma_separated_module_paths():
    assert adapter_loader.parse_adapter_modules(
        " onebot.v11 , custom.adapter "
    ) == ("onebot.v11", "custom.adapter")
    assert adapter_loader.parse_adapter_modules("adapter_plugin") == (
        "adapter_plugin",
    )


@pytest.mark.parametrize(
    "raw, message",
    [
        ("onebot.v11,onebot.v11", "duplicate"),
        ("not-a-module", "valid Python module paths"),
    ],
)
def test_parse_rejects_ambiguous_paths(raw: str, message: str):
    with pytest.raises(ValueError, match=message):
        adapter_loader.parse_adapter_modules(raw)


def test_registers_only_selected_modules(monkeypatch):
    driver = _Driver()
    monkeypatch.setattr(
        adapter_loader.importlib,
        "import_module",
        lambda path: _module() if path == "selected.adapter" else pytest.fail(path),
    )

    names = adapter_loader.register_enabled_adapters(driver, ("selected.adapter",))

    assert names == ("Test Adapter",)
    assert driver.registered == [_TestAdapter]


def test_existing_same_class_registration_is_idempotent(monkeypatch):
    driver = _Driver()
    driver._adapters["Test Adapter"] = _TestAdapter
    monkeypatch.setattr(adapter_loader.importlib, "import_module", lambda _: _module())

    names = adapter_loader.register_enabled_adapters(driver, ("selected.adapter",))

    assert names == ("Test Adapter",)
    assert driver.registered == []


@pytest.mark.parametrize("missing", ["selected.adapter", "optional_dependency"])
def test_missing_adapter_or_dependency_has_actionable_error(monkeypatch, missing: str):
    def _import(_path: str):
        raise ModuleNotFoundError("missing", name=missing)

    monkeypatch.setattr(adapter_loader.importlib, "import_module", _import)

    with pytest.raises(adapter_loader.AdapterRegistrationError) as exc:
        adapter_loader.register_enabled_adapters(_Driver(), ("selected.adapter",))

    assert missing in str(exc.value)
    assert "Install that adapter package" in str(exc.value)
    assert "STELLA_ADAPTER_MODULES" in str(exc.value)


def test_module_must_expose_nonebot_adapter_subclass(monkeypatch):
    monkeypatch.setattr(adapter_loader.importlib, "import_module", lambda _: _module(str))

    with pytest.raises(adapter_loader.AdapterRegistrationError, match="derived from"):
        adapter_loader.register_enabled_adapters(_Driver(), ("selected.adapter",))


def test_registration_failure_names_adapter_and_driver(monkeypatch):
    monkeypatch.setattr(adapter_loader.importlib, "import_module", lambda _: _module())
    driver = _Driver(RuntimeError("unsupported transport"))

    with pytest.raises(adapter_loader.AdapterRegistrationError) as exc:
        adapter_loader.register_enabled_adapters(driver, ("selected.adapter",))

    message = str(exc.value)
    assert "Test Adapter" in message
    assert "_Driver" in message
    assert "DRIVER='~fastapi'" in message
    assert "unsupported transport" in message
