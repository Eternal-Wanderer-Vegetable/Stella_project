# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""``config/capabilities/*.toml`` 载入的单测。

沿用 config/spaces.py 的容错契约：单个文件坏了只跳过该文件，不中断其余加载，
也绝不抛异常打断启动——能力声明是可选的加分项，缺了只是路由质量下降。
"""

from capability.loader import load_capabilities, load_capability_file
from capability.registry import KIND_ASTRBOT_TOOL, CapabilityRegistry


def _write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_capability_with_string_providers(tmp_path):
    reg = CapabilityRegistry()
    path = _write(
        tmp_path,
        "information.toml",
        """
[[capability]]
id = "weather.query"
description = "查询天气信息"
examples = ["明天天气怎么样", "会不会下雨"]
providers = ["get_weather", "weather_forecast"]
""",
    )
    assert load_capability_file(path, reg) == 1

    cap = reg.get("weather.query")
    assert cap is not None
    # 文件名即 domain
    assert cap.domain == "information"
    assert cap.description == "查询天气信息"
    assert cap.examples == ["明天天气怎么样", "会不会下雨"]
    assert [p.tool_name for p in cap.providers] == ["get_weather", "weather_forecast"]
    assert all(p.kind == KIND_ASTRBOT_TOOL for p in cap.providers)
    assert all(p.source == "config" for p in cap.providers)


def test_loads_table_providers_with_priority(tmp_path):
    reg = CapabilityRegistry()
    path = _write(
        tmp_path,
        "search.toml",
        """
[[capability]]
id = "web.search"
description = "联网搜索"
providers = [{ tool = "bing_search", priority = 10 }, { tool = "google_search" }]
""",
    )
    load_capability_file(path, reg)
    providers = reg.find_providers("web.search")
    assert [p.tool_name for p in providers] == ["bing_search", "google_search"]
    assert providers[0].priority == 10


def test_provider_priority_falls_back_on_bad_value(tmp_path):
    reg = CapabilityRegistry()
    path = _write(
        tmp_path,
        "x.toml",
        """
[[capability]]
id = "a.b"
providers = [{ tool = "t", priority = "high" }]
""",
    )
    load_capability_file(path, reg)
    assert reg.find_providers("a.b")[0].priority == 0


def test_skips_providers_without_tool_name(tmp_path):
    reg = CapabilityRegistry()
    path = _write(
        tmp_path,
        "x.toml",
        """
[[capability]]
id = "a.b"
providers = ["", { priority = 3 }, "good"]
""",
    )
    load_capability_file(path, reg)
    assert [p.tool_name for p in reg.find_providers("a.b")] == ["good"]


def test_skips_capability_without_id(tmp_path):
    reg = CapabilityRegistry()
    path = _write(
        tmp_path,
        "x.toml",
        """
[[capability]]
description = "无 id"

[[capability]]
id = "ok.one"
""",
    )
    assert load_capability_file(path, reg) == 1
    assert reg.ids() == ["ok.one"]


def test_accepts_single_table_form(tmp_path):
    """写成 [capability] 而不是 [[capability]] 是常见笔误，直接收下。"""
    reg = CapabilityRegistry()
    path = _write(
        tmp_path,
        "x.toml",
        """
[capability]
id = "solo.cap"
description = "单表写法"
""",
    )
    assert load_capability_file(path, reg) == 1
    assert reg.get("solo.cap") is not None


def test_broken_toml_is_skipped_not_raised(tmp_path):
    reg = CapabilityRegistry()
    path = _write(tmp_path, "bad.toml", "this is not = = toml [[[")
    assert load_capability_file(path, reg) == 0
    assert not reg


def test_missing_capability_section_is_skipped(tmp_path):
    reg = CapabilityRegistry()
    path = _write(tmp_path, "x.toml", 'title = "no capability here"\n')
    assert load_capability_file(path, reg) == 0


def test_non_list_capability_section_is_skipped(tmp_path):
    reg = CapabilityRegistry()
    path = _write(tmp_path, "x.toml", 'capability = "wrong type"\n')
    assert load_capability_file(path, reg) == 0


def test_load_directory_merges_all_files_deterministically(tmp_path):
    reg = CapabilityRegistry()
    _write(
        tmp_path,
        "b_second.toml",
        '[[capability]]\nid = "z.cap"\ndescription = "后者"\n',
    )
    _write(
        tmp_path,
        "a_first.toml",
        '[[capability]]\nid = "z.cap"\ndescription = "先者"\n\n[[capability]]\nid = "a.cap"\n',
    )
    assert load_capabilities(tmp_path, reg) == 3
    # 按文件名排序遍历，先者的描述胜出（register 是合并语义，已有值优先）
    cap = reg.get("z.cap")
    assert cap is not None
    assert cap.description == "先者"
    assert cap.domain == "a_first"


def test_missing_directory_returns_zero(tmp_path):
    reg = CapabilityRegistry()
    assert load_capabilities(tmp_path / "nope", reg) == 0


def test_empty_directory_returns_zero(tmp_path):
    reg = CapabilityRegistry()
    assert load_capabilities(tmp_path, reg) == 0


def test_input_schema_is_kept_only_when_dict(tmp_path):
    reg = CapabilityRegistry()
    path = _write(
        tmp_path,
        "x.toml",
        """
[[capability]]
id = "a.b"
input_schema = { type = "object" }

[[capability]]
id = "c.d"
input_schema = "nope"
""",
    )
    load_capability_file(path, reg)
    a = reg.get("a.b")
    c = reg.get("c.d")
    assert a is not None and a.input_schema == {"type": "object"}
    assert c is not None and c.input_schema == {}
