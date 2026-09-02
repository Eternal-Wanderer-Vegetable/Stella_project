# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""本地状态接口（plugins.bot_main.status_api）纯函数测试。

只测不依赖 NoneBot 运行时的部分：回环判断与 payload 组装。
setup_status_api 涉及 FastAPI app 注册，留给真实启动验证。

import 方式：bot_main/__init__.py 会 ``from . import ai_gateway``——那会建
Pipeline、跑 schema 迁移等副作用，单元测试不需要。这里先占位 plugins.bot_main
跳过 __init__，再按包路径导入 status_api。
"""

from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

_PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJ / "stella_project"))

_fake_bot_main = types.ModuleType("plugins.bot_main")
_fake_bot_main.__path__ = [str(_PROJ / "stella_project" / "plugins" / "bot_main")]
sys.modules.setdefault("plugins.bot_main", _fake_bot_main)

from plugins.bot_main import status_api


def test_is_loopback_true():
    for host in ("127.0.0.1", "::1", "127.0.0.5", "localhost"):
        assert status_api._is_loopback(host) is True


def test_is_loopback_false():
    for host in ("192.168.1.10", "0.0.0.0", "abc", ""):
        assert status_api._is_loopback(host) is False


def test_build_payload_fields_complete():
    link = {"healthy": True}
    sched = {"chat": {"waiting": 2}}
    payload = status_api.build_payload(link, sched, pid=123, started_at=time.time())
    assert set(payload) == {
        "version",
        "pid",
        "uptime_seconds",
        "allowed_group_count",
        "link",
        "scheduler",
        "usage",
        "capabilities",
    }
    assert payload["pid"] == 123
    assert payload["link"] is link
    assert payload["scheduler"] is sched
    assert isinstance(payload["version"], str) and payload["version"]


def test_build_payload_omits_secrets(monkeypatch):
    """安全护栏：序列化后的 JSON 不得出现凭据或具体群号。"""
    monkeypatch.setattr(status_api, "ALLOWED_GROUPS", {123456789, 987654321})
    monkeypatch.setenv("ONEBOT_ACCESS_TOKEN", "super-secret-token")
    text = json.dumps(
        status_api.build_payload({}, {}, pid=1, started_at=time.time()),
        ensure_ascii=False,
    )
    assert "super-secret-token" not in text
    assert "123456789" not in text
    assert "987654321" not in text


def test_build_payload_accepts_none_link():
    """扩展未加载时 link 为 None，不崩。"""
    payload = status_api.build_payload(None, {}, pid=1, started_at=time.time())
    assert payload["link"] is None
    assert payload["scheduler"] == {}
    assert payload["allowed_group_count"] >= 0


def test_build_payload_reports_group_count(monkeypatch):
    monkeypatch.setattr(status_api, "ALLOWED_GROUPS", {1, 2, 3})
    payload = status_api.build_payload(None, {}, pid=1, started_at=time.time())
    assert payload["allowed_group_count"] == 3


def test_build_payload_usage_defaults_to_none():
    """取数失败时 usage 为 None——面板据此整块隐藏，而不是显示一堆 0。"""
    payload = status_api.build_payload(None, {}, pid=1, started_at=time.time())
    assert payload["usage"] is None


def test_build_payload_passes_usage_through():
    usage = {"accounting": True, "used_tokens": 120, "budget": 1000}
    payload = status_api.build_payload(
        None, {}, pid=1, started_at=time.time(), usage=usage
    )
    assert payload["usage"] is usage


def test_usage_snapshot_shape_carries_no_credentials_or_chat_content():
    """约束：用量面板只暴露计数与比率。

    这里直接拿 ``usage_snapshot()`` 的真实输出过一遍序列化——status_api 是它
    唯一的出口，字段一旦长出 prompt / base_url / key，泄漏就是全网可见的
    （虽然接口只绑回环，但诊断包会被用户贴到 issue 里）。
    """
    import core.llm.usage_store as store

    store.reset_state()
    try:
        snap = store.usage_snapshot()
        text = json.dumps(
            status_api.build_payload(None, {}, pid=1, started_at=time.time(), usage=snap),
            ensure_ascii=False,
        )
        for banned in ("api_key", "Bearer", "sk-", "prompt_text", "http://", "https://"):
            assert banned not in text
    finally:
        store.reset_state()


def test_capabilities_defaults_to_none():
    """取数失败时 capabilities 为 None——面板据此整块隐藏，而不是显示一个空清单。"""
    payload = status_api.build_payload(None, {}, pid=1, started_at=time.time())
    assert payload["capabilities"] is None


def test_capabilities_passes_through():
    caps = {"version": 1, "total": 3, "routable": 2, "items": []}
    payload = status_api.build_payload(
        None, {}, pid=1, started_at=time.time(), capabilities=caps
    )
    assert payload["capabilities"] is caps


def test_capability_snapshot_carries_no_free_text_from_declarations():
    """约束：能力清单只暴露结构化字段。

    ``description`` 与 ``examples`` 原文是声明里唯一可能夹带 URL 与密钥的字段
    （用户自己写的 TOML，插件作者写的 TOML，谁都可能往里贴一条带 token 的接口地址）。
    不放进响应体就不必为它加一道守卫——这条断言就是那个「不放进去」的机械保证。

    真实数据：现装的三层声明载进一个独立注册表，再过一遍 ``snapshot()`` 与序列化。
    """
    from pathlib import Path

    from capability.inventory import snapshot
    from capability.loader import load_capabilities
    from capability.registry import CapabilityRegistry

    reg = CapabilityRegistry()
    load_capabilities(Path(__file__).resolve().parents[1] / "config" / "capabilities", target=reg)
    assert len(reg) > 0, "出厂声明应当至少有一份，否则这条断言什么都没验到"

    descriptions = [c.description for c in reg.all() if c.description]
    examples = [e for c in reg.all() for e in c.examples]
    assert descriptions and examples, "样本里得同时有描述与例句，才说明确实被排除了"

    text = json.dumps(
        status_api.build_payload(
            None, {}, pid=1, started_at=time.time(), capabilities=snapshot(target=reg)
        ),
        ensure_ascii=False,
    )
    for banned in ("api_key", "Bearer", "sk-", "prompt_text", "http://", "https://"):
        assert banned not in text
    for free_text in descriptions + examples:
        assert free_text not in text, f"自由文本泄漏进响应体：{free_text!r}"
