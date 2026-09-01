# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""`deploy plugin-check` 的单元测试。

判断层是纯函数（只读 ``PluginFacts``），所以每条检查用 ``_facts(**overrides)``
构造即可覆盖正反两面，不需要真插件。真插件只在最后一节出现一次：拿
``docs/examples/astrbot_plugin_stella_template`` 跑完整流水并断言零 error、零 warn
——**模板同时是文档与回归夹具**，规范与校验器一旦漂移，那条用例先失败。

三条全局不变量（前两条照 ``test_deploy_checks.py``）：
1. 缺省事实（= 合规插件）跑 ``run_all`` 必须零条结论；
2. 任何非 ok 结论必须有 ``fix_hint``；
3. ``total_checks()`` 与 ``_ALL_CHECKS`` 一致（``_summarize`` 的分母靠它推 ok 数）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from capability.registry import (
    KIND_ASTRBOT_TOOL,
    SOURCE_PLUGIN,
    Capability,
    CapabilityProvider,
)
from deploy import plugin_check
from deploy.plugin_check import PluginFacts, ToolFact

# 缺省 examples：三条中文问句，刚好达到 MIN_EXAMPLES，不会误触检查 ⑦
_OK_EXAMPLES = ["这段话有多少字", "帮我数一下字数", "这段文字有几行"]


def _cap(
    cap_id: str,
    *,
    domain: str = "utility",
    examples: list[str] | None = None,
    keywords: list[str] | None = None,
    tools: tuple[str, ...] = ("get_text_stats",),
) -> Capability:
    return Capability(
        id=cap_id,
        domain=domain,
        description=f"{cap_id} 的描述",
        examples=list(_OK_EXAMPLES if examples is None else examples),
        keywords=list(keywords or []),
        providers=[
            CapabilityProvider(
                provider_id=f"{cap_id}:{tool}",
                capability_id=cap_id,
                kind=KIND_ASTRBOT_TOOL,
                tool_name=tool,
                source=SOURCE_PLUGIN,
            )
            for tool in tools
        ],
        source=SOURCE_PLUGIN,
    )


def _facts(**overrides) -> PluginFacts:
    """一份「合规插件」的事实。字段缺省值本身就是合规的，这里只补上身份信息。"""
    base = {
        "plugin_dir": Path("data/plugins/astrbot_plugin_demo"),
        "dir_name": "astrbot_plugin_demo",
        "plugin_name": "astrbot_plugin_demo",
        "plugin_version": "v1.0.0",
    }
    base.update(overrides)
    return PluginFacts(**base)


def _loaded(**overrides) -> PluginFacts:
    """已成功加载、带一个工具与一条声明的事实——依赖工具清单的检查靠它。"""
    base = {
        "executed_plugin_code": True,
        "tools": [ToolFact(name="get_text_stats", description="统计字数", required=("text",))],
        "capabilities": [_cap("text.stats")],
        "reviewed": True,
    }
    base.update(overrides)
    return _facts(**base)


# ── 全局不变量 ──


def test_default_facts_yield_no_results():
    assert plugin_check.run_all(_facts()) == []


def test_compliant_loaded_plugin_yields_no_results():
    assert plugin_check.run_all(_loaded()) == []


def test_total_checks_matches_all_checks():
    assert plugin_check.total_checks() == len(plugin_check._ALL_CHECKS)
    assert plugin_check.total_checks() == 16


def test_every_finding_carries_a_fix_hint():
    """把能同时触发的问题堆在一份事实里，逐条断言 fix_hint 非空。"""
    facts = _loaded(
        archives=["plugin.zip"],
        missing_requirements=["not_a_real_package_xyz"],
        requirements=["not_a_real_package_xyz"],
        tools=[
            ToolFact(name="get_text_stats", required=("text",)),
            ToolFact(name="orphan_tool"),
        ],
        capabilities=[
            _cap("text.stats", examples=["只有一条"], keywords=["字数", "字数统计"]),
            _cap("text.other", examples=["当用户询问字数时调用"], tools=("typo_tool",)),
        ],
        config_capability_ids=["text.stats"],
        url_image_hits=["main.py:12"],
        bare_create_task_hits=["main.py:20"],
        egress_libs=["httpx"],
        separation={"spread": 0.01, "negative_margin": -0.024},
    )
    results = plugin_check.run_all(facts)
    assert len(results) >= 8
    for r in results:
        assert r.level in ("error", "warn", "info")
        assert r.fix_hint.strip(), f"{r.id} 没有 fix_hint"
        assert r.title.strip() and r.detail.strip()


def test_run_all_sorts_errors_first():
    facts = _loaded(
        url_image_hits=["main.py:1"],  # warn
        tools=[ToolFact(name="orphan_tool")],  # error（工具没声明）
    )
    levels = [r.level for r in plugin_check.run_all(facts)]
    assert levels == sorted(levels, key=lambda lv: {"error": 0, "warn": 1, "info": 2}[lv])
    assert levels[0] == "error"


# ── ① 目录布局 ──


def test_layout_missing_main_py_is_error():
    r = plugin_check.check_layout(_facts(has_main_py=False))
    assert r is not None and r.level == "error" and r.id == "plugin_layout"
    assert "main.py" in r.title


def test_layout_unextracted_archive_names_the_archive():
    r = plugin_check.check_layout(_facts(has_main_py=False, archives=["plugin.zip"]))
    assert r is not None and r.level == "error"
    assert "压缩包" in r.title and "plugin.zip" in r.detail


def test_layout_leftover_archive_is_only_a_warning():
    """有 main.py 时压缩包只是残留：插件本身能加载。"""
    r = plugin_check.check_layout(_facts(archives=["old.zip"]))
    assert r is not None and r.level == "warn"


def test_layout_quiet_when_clean():
    assert plugin_check.check_layout(_facts()) is None


# ── ② 加载 ──


def test_load_error_is_error():
    r = plugin_check.check_load(_loaded(load_error="ModuleNotFoundError: No module named 'x'"))
    assert r is not None and r.level == "error"
    assert "No module named" in r.detail


def test_load_skipped_when_code_was_not_executed():
    """没执行过插件代码就没有加载结论可言——不能拿空事实报「加载失败」。"""
    assert plugin_check.check_load(_facts(load_error="x")) is None


# ── ③ 依赖 ──


def test_requirements_missing_is_error_with_pip_command():
    r = plugin_check.check_requirements(
        _facts(requirements=["httpx", "aiofiles"], missing_requirements=["aiofiles"])
    )
    assert r is not None and r.level == "error"
    assert "aiofiles" in r.detail and "pip install -r" in r.fix_hint


def test_requirements_quiet_when_all_installed():
    assert plugin_check.check_requirements(_facts(requirements=["httpx"])) is None


# ── ④ 工具未被声明（核心检查）──


def test_undeclared_tool_is_error():
    r = plugin_check.check_tool_undeclared(_loaded(capabilities=[]))
    assert r is not None and r.level == "error"
    assert "get_text_stats" in r.detail
    assert "不会被触发" in r.title


def test_tool_declared_by_own_capability_is_quiet():
    assert plugin_check.check_tool_undeclared(_loaded()) is None


def test_tool_declared_by_config_tier_is_quiet():
    """出厂层替插件写了声明（astrbot_plugin_bilibili 就是这样）——不该报错。"""
    facts = _loaded(capabilities=[], config_claims={"get_text_stats": "text.stats"})
    assert plugin_check.check_tool_undeclared(facts) is None


def test_tool_undeclared_skipped_when_load_failed():
    """加载失败时工具清单必然是空的，此时判「没声明」只会刷一条假 error。"""
    facts = _loaded(capabilities=[], tools=[], load_error="boom")
    assert plugin_check.check_tool_undeclared(facts) is None


# ── ⑤ provider 指向不存在的工具 ──


def test_provider_typo_is_error_and_suggests_the_real_name():
    facts = _loaded(capabilities=[_cap("text.stats", tools=("get_text_stat",))])
    r = plugin_check.check_provider_missing(facts)
    assert r is not None and r.level == "error"
    assert "get_text_stat" in r.detail
    assert "get_text_stats" in r.detail  # difflib 的近似建议


def test_provider_missing_quiet_when_names_match():
    assert plugin_check.check_provider_missing(_loaded()) is None


def test_provider_missing_skipped_when_plugin_has_no_tools():
    """插件一个工具都没登记（纯指令插件）时，声明理应指向别处，不在这里判。"""
    facts = _loaded(tools=[], capabilities=[_cap("text.stats", tools=("whatever",))])
    assert plugin_check.check_provider_missing(facts) is None


# ── ⑥ 声明文件可用性 ──


def test_declaration_parse_error_is_error():
    r = plugin_check.check_declaration(_facts(declaration_error="第 3 行: 语法错误"))
    assert r is not None and r.level == "error"
    assert "语法错误" in r.detail


def test_only_draft_is_error():
    r = plugin_check.check_declaration(_facts(declaration_present=False, draft_present=True))
    assert r is not None and r.level == "error"
    assert "capability.toml.draft" in r.title


def test_reviewed_false_is_error():
    r = plugin_check.check_declaration(_facts(reviewed=False))
    assert r is not None and r.level == "error"
    assert "reviewed" in r.title


def test_declaration_quiet_when_reviewed():
    assert plugin_check.check_declaration(_facts(reviewed=True)) is None


def test_declaration_quiet_when_key_omitted():
    """``reviewed`` 键缺省视为已审（手写声明不必写这一行）。"""
    assert plugin_check.check_declaration(_facts(reviewed=None)) is None


# ── ⑦ examples 条数 ──


def test_examples_too_few_is_warn():
    r = plugin_check.check_examples_count(
        _facts(capabilities=[_cap("text.stats", examples=["这段话有多少字", "数一下字数"])])
    )
    assert r is not None and r.level == "warn"
    assert "text.stats(2 条)" in r.detail


def test_examples_count_quiet_at_threshold():
    assert plugin_check.check_examples_count(_facts(capabilities=[_cap("text.stats")])) is None


# ── ⑧ examples 写成了指令句 ──


@pytest.mark.parametrize(
    "example",
    ["当用户询问字数时调用本工具", "用于统计文字长度", "该工具返回字数"],
)
def test_imperative_examples_are_warned(example):
    facts = _facts(capabilities=[_cap("text.stats", examples=[*_OK_EXAMPLES, example])])
    r = plugin_check.check_examples_style(facts)
    assert r is not None and r.level == "warn"
    assert example in r.detail


def test_question_examples_are_quiet():
    assert plugin_check.check_examples_style(_facts(capabilities=[_cap("text.stats")])) is None


# ── ⑨ 关键词跨能力泄漏 ──


def test_keyword_leaking_into_another_capability_is_warn():
    facts = _facts(
        capabilities=[
            _cap("anime.recommend", examples=["有什么新番推荐吗"], keywords=["番剧推荐"]),
            _cap(
                "anime.schedule",
                examples=["星期一放送哪些番剧推荐给我"],
                tools=("get_schedule",),
            ),
        ]
    )
    r = plugin_check.check_keywords_overlap(facts)
    assert r is not None and r.level == "warn"
    assert "anime.recommend" in r.detail and "anime.schedule" in r.detail


def test_keyword_overlapping_its_own_example_is_not_a_finding():
    """这条钉住与方案 §5 第 9 项的**刻意偏离**。

    方案原文写的是「keywords 里的词是某条 example 的子串 → warn」。拿本项目出厂、
    带实测标定的 ``config/capabilities/entertainment.toml`` 一量就知道那个写法会命中
    正确写法：「番剧推荐」正是它自己 example「有什么新番推荐吗」的子串，「放送」也是
    「星期一放送哪些番」的子串。会把参考标准判成违规的检查比没有这条检查更糟——它教
    用户忽略警告。要防的是跨能力串味（上一条用例），不是与自己的 example 重叠。
    """
    facts = _facts(
        capabilities=[
            _cap("anime.recommend", examples=["有什么新番推荐吗"], keywords=["番剧推荐"]),
        ]
    )
    assert plugin_check.check_keywords_overlap(facts) is None


def _factory_declaration() -> PluginFacts:
    from capability.loader import parse_declaration
    from config import PROJECT_ROOT

    path = PROJECT_ROOT / "config" / "capabilities" / "entertainment.toml"
    if not path.is_file():
        pytest.skip("出厂声明不存在（自定义布局）")
    parsed = parse_declaration(path)
    assert not parsed.error and parsed.capabilities
    return _facts(capabilities=list(parsed.capabilities))


def test_entertainment_reference_declaration_stays_clean():
    """出厂声明是 examples/keywords 的参考标准，这几条检查不许误伤它。

    ``check_keywords_short`` 不在这份名单里，理由见下一条用例。
    """
    facts = _factory_declaration()
    for check in (
        plugin_check.check_keywords_overlap,
        plugin_check.check_examples_count,
        plugin_check.check_examples_style,
    ):
        assert check(facts) is None, f"{check.__name__} 误伤了出厂声明"


def test_short_keyword_check_only_flags_the_one_deliberate_override():
    """⑩ 在出厂声明上只应命中「放送」这一处，且那一处是**有意为之**。

    ``docs/configuration.md`` 记着它的实测依据：「今天的放送表」的 L1 得分只有 0.641
    （低于 0.70 的置信线，会漏），靠 ``anime.schedule`` 的两字关键词「放送」才被零延迟
    接住。所以这条 warn 是「请复核」而不是「你写错了」——⑩ 的判据是字数，而真正决定
    一个关键词能不能用的是「说出来有没有歧义」，那没法机械判定。

    这条用例存在的意义是**钉住命中范围**：多出任何一处，就说明阈值或出厂声明动了，
    需要有人重新权衡，而不是让告警悄悄变成背景噪音。
    """
    r = plugin_check.check_keywords_short(_factory_declaration())
    assert r is not None and r.level == "warn"
    assert r.detail == "anime.schedule：「放送」"


# ── ⑩ 关键词过短 ──


def test_short_keyword_is_warn():
    facts = _facts(capabilities=[_cap("anime.recommend", keywords=["新番", "番剧推荐"])])
    r = plugin_check.check_keywords_short(facts)
    assert r is not None and r.level == "warn"
    assert "新番" in r.detail and "番剧推荐" not in r.detail


def test_long_keyword_is_quiet():
    facts = _facts(capabilities=[_cap("anime.recommend", keywords=["番剧推荐"])])
    assert plugin_check.check_keywords_short(facts) is None


# ── ⑪ 有必填参数却给了 keywords ──


def test_keywords_on_tool_with_required_args_is_warn():
    facts = _loaded(capabilities=[_cap("text.stats", keywords=["字数统计"])])
    r = plugin_check.check_keywords_required_args(facts)
    assert r is not None and r.level == "warn"
    assert "get_text_stats" in r.detail and "text" in r.detail


def test_keywords_on_tool_without_required_args_is_quiet():
    facts = _loaded(
        tools=[ToolFact(name="get_text_stats")],
        capabilities=[_cap("text.stats", keywords=["字数统计"])],
    )
    assert plugin_check.check_keywords_required_args(facts) is None


def test_no_keywords_means_nothing_to_check():
    assert plugin_check.check_keywords_required_args(_loaded()) is None


# ── ⑫ 量化指标（事实由 plugin-scaffold 带来）──


def test_separation_spread_below_threshold_is_warn():
    facts = _facts(separation={"spread": 0.058, "negative_margin": 0.141})
    r = plugin_check.check_separation(facts)
    assert r is not None and r.level == "warn"
    assert "0.058" in r.detail and "余量" not in r.detail


def test_negative_sample_margin_below_zero_is_warn():
    facts = _facts(separation={"spread": 0.20, "negative_margin": -0.024})
    r = plugin_check.check_separation(facts)
    assert r is not None and r.level == "warn"
    assert "-0.024" in r.detail


def test_separation_quiet_when_healthy():
    assert plugin_check.check_separation(_facts(separation={"spread": 0.2, "margin": 0.1})) is None


def test_separation_skipped_without_measurements():
    """校验器自己不拉起 embedding 服务，没有指标就跳过而不是报错。"""
    assert plugin_check.check_separation(_facts()) is None


# ── ⑬ 与更高优先层撞名（info）──


def test_capability_id_collision_is_info():
    facts = _facts(capabilities=[_cap("text.stats")], config_capability_ids=["text.stats"])
    r = plugin_check.check_collision(facts)
    assert r is not None and r.level == "info"
    assert "整条跳过" in r.title or "整条跳过" in r.detail


def test_tool_claimed_by_another_capability_is_info():
    facts = _facts(
        capabilities=[_cap("text.stats")],
        config_claims={"get_text_stats": "utility.wordcount"},
    )
    r = plugin_check.check_collision(facts)
    assert r is not None and r.level == "info"
    assert "utility.wordcount" in r.detail


def test_same_id_claiming_the_same_tool_is_not_a_collision():
    """用户层用同一个 id 覆盖同一个工具——这是正常的覆盖，不重复告知。"""
    facts = _facts(capabilities=[_cap("text.stats")], config_claims={"get_text_stats": "text.stats"})
    assert plugin_check.check_collision(facts) is None


# ── ⑭ url_image ──


def test_url_image_is_warn():
    r = plugin_check.check_url_image(_facts(url_image_hits=["main.py:42"]))
    assert r is not None and r.level == "warn"
    assert "main.py:42" in r.detail
    assert "fromFileSystem" in r.fix_hint


def test_url_image_quiet_when_absent():
    assert plugin_check.check_url_image(_facts()) is None


# ── ⑮ 裸 create_task ──


def test_bare_create_task_is_warn():
    r = plugin_check.check_bare_task(_facts(bare_create_task_hits=["main.py:20"]))
    assert r is not None and r.level == "warn"
    assert "register_task" in r.fix_hint


def test_bare_create_task_detail_notes_partial_adoption():
    facts = _facts(bare_create_task_hits=["worker.py:8"], uses_register_task=True)
    r = plugin_check.check_bare_task(facts)
    assert r is not None and "漏了" in r.detail


def test_register_task_only_is_quiet():
    assert plugin_check.check_bare_task(_facts(uses_register_task=True)) is None


# ── ⑯ 出网披露 ──


def test_egress_library_without_declaration_is_warn():
    r = plugin_check.check_egress(_facts(egress_libs=["httpx"]))
    assert r is not None and r.level == "warn"
    assert "httpx" in r.title and "stella" in r.fix_hint


def test_egress_declared_is_quiet():
    facts = _facts(egress_libs=["httpx"], egress_declared=["api.example.com"])
    assert plugin_check.check_egress(facts) is None


def test_no_egress_library_is_quiet():
    assert plugin_check.check_egress(_facts(egress_declared=["api.example.com"])) is None


# ── 事实采集（只读盘的那半，不 import 插件）──


def _write(plugin_dir: Path, name: str, body: str) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / name).write_text(body, encoding="utf-8")


def test_requirements_parsing_drops_versions_options_and_markers(tmp_path):
    _write(
        tmp_path,
        "requirements.txt",
        "\n".join(
            [
                "# 注释行",
                "httpx>=0.27  # 行尾注释",
                "-r other.txt",
                "--index-url https://example.com/simple",
                "aiofiles==23.1.0",
                'tomli; python_version < "3.11"',
                "mypkg @ https://example.com/mypkg.whl",
                "httpx",
                "",
            ]
        ),
    )
    assert plugin_check._read_requirements(tmp_path) == ["httpx", "aiofiles", "tomli", "mypkg"]


def test_requirements_absent_is_empty(tmp_path):
    assert plugin_check._read_requirements(tmp_path) == []


def test_literals_are_blanked_before_scanning(tmp_path):
    """docstring 里讲「别裸 create_task」不该被判成「裸 create_task 了」。

    模板插件的 ``initialize`` docstring 正是这么写的，第一次拿校验器跑它就撞上了。
    """
    _write(
        tmp_path,
        "main.py",
        '\n'.join(
            [
                "import asyncio",
                "",
                "",
                "class P:",
                '    """讲坑的文档：裸 asyncio.create_task(...) 会残留，别用 url_image(x)。"""',
                "",
                "    def a(self):",
                "        # 注释里的 asyncio.create_task(x) 也不算",
                "        self.context.register_task(self._loop(), 'x')",
                "",
                "    def b(self):",
                "        asyncio.create_task(self._loop())",
                "",
            ]
        ),
    )
    facts = _facts()
    plugin_check._scan_sources(tmp_path, facts)
    assert facts.uses_register_task is True
    assert facts.url_image_hits == []
    assert facts.bare_create_task_hits == ["main.py:12"]  # 只有真正的那一处


def test_register_task_wrapping_create_task_on_one_line_is_not_flagged(tmp_path):
    _write(
        tmp_path,
        "main.py",
        "import asyncio\nself.context.register_task(asyncio.create_task(f()))\n",
    )
    facts = _facts()
    plugin_check._scan_sources(tmp_path, facts)
    assert facts.bare_create_task_hits == []


def test_egress_imports_are_detected(tmp_path):
    _write(tmp_path, "main.py", "import httpx\nfrom aiohttp import ClientSession\n")
    facts = _facts()
    plugin_check._scan_sources(tmp_path, facts)
    assert facts.egress_libs == ["aiohttp", "httpx"]


def test_declared_egress_accepts_tables_and_bare_strings(tmp_path):
    _write(
        tmp_path,
        "metadata.yaml",
        "\n".join(
            [
                "name: demo",
                "stella:",
                "  egress:",
                "    - host: api.example.com",
                "      purpose: 查询",
                "    - cdn.example.net",
            ]
        ),
    )
    assert plugin_check._declared_egress(tmp_path) == ["api.example.com", "cdn.example.net"]


def test_declared_egress_empty_without_the_field(tmp_path):
    _write(tmp_path, "metadata.yaml", "name: demo\n")
    assert plugin_check._declared_egress(tmp_path) == []


def test_draft_only_directory_reports_the_gate(tmp_path):
    _write(tmp_path, "capability.toml.draft", 'reviewed = false\n[[capability]]\nid = "x"\n')
    facts = _facts()
    plugin_check._read_declaration(tmp_path, facts)
    assert facts.declaration_present is False and facts.draft_present is True
    assert facts.capabilities == []


def test_declaration_is_parsed_through_the_shared_loader(tmp_path):
    _write(
        tmp_path,
        "capability.toml",
        "\n".join(
            [
                "reviewed = true",
                "[[capability]]",
                'id = "text.stats"',
                'domain = "utility"',
                'description = "统计字数"',
                'examples = ["这段话有多少字", "帮我数一下字数", "这段文字有几行"]',
                'providers = ["get_text_stats"]',
            ]
        ),
    )
    facts = _facts()
    plugin_check._read_declaration(tmp_path, facts)
    assert facts.declaration_error == ""
    assert facts.reviewed is True
    assert [c.id for c in facts.capabilities] == ["text.stats"]
    assert facts.declared_tools() == {"get_text_stats"}
    assert facts.capabilities[0].source == SOURCE_PLUGIN


# ── 渲染与 CLI 契约 ──


def test_to_json_gui_contract():
    facts = _loaded()
    doc = json.loads(plugin_check.to_json(facts, plugin_check.run_all(facts)))
    assert doc["version"] == 1
    assert doc["executed_plugin_code"] is True  # 顶层也放一份：GUI 不必钻进 plugin 里找
    assert doc["plugin"]["executed_plugin_code"] is True
    assert doc["summary"]["total"] == plugin_check.total_checks()
    assert doc["summary"]["ok"] == plugin_check.total_checks()
    assert doc["summary"]["blocking"] is False
    assert doc["items"] == []
    assert doc["plugin"]["tools"] == [{"name": "get_text_stats", "required": ["text"]}]
    cap = doc["plugin"]["declaration"]["capabilities"][0]
    assert cap == {
        "id": "text.stats",
        "domain": "utility",
        "source": SOURCE_PLUGIN,
        "examples": 3,
        "keywords": 0,
        "providers": ["get_text_stats"],
    }


def test_to_json_carries_no_free_text_from_the_declaration():
    """照 ``test_status_api.py`` 那条惯例：payload 只放结构化字段。

    ``description`` / ``examples`` 原文是唯一可能夹带 URL 或凭据的字段，不放进去
    就不必再为它加一道守卫；原文本地读 TOML 就有。
    """
    facts = _loaded(
        capabilities=[
            _cap(
                "text.stats",
                examples=["把 http://example.com/?key=sk-secret 的字数数一下"],
            )
        ]
    )
    blob = plugin_check.to_json(facts, plugin_check.run_all(facts))
    for banned in ("http://", "https://", "sk-", "api_key", "Bearer"):
        assert banned not in blob, f"payload 泄漏了 {banned}"
    assert "text.stats 的描述" not in blob


def test_terminal_output_discloses_that_plugin_code_ran():
    facts = _loaded()
    text = plugin_check.to_terminal(facts, plugin_check.run_all(facts))
    assert "已 import 并实例化该插件代码" in text
    assert "共 16 项检查" in text
    assert "未发现不符合规范之处" in text


def test_terminal_output_omits_the_disclosure_when_nothing_ran():
    facts = _facts(has_main_py=False)
    text = plugin_check.to_terminal(facts, plugin_check.run_all(facts))
    assert "已 import" not in text
    assert "存在不符合规范之处" in text


@pytest.mark.parametrize(
    ("raw", "shown"),
    [("v1.6.4", "v1.6.4"), ("1.0.0", "v1.0.0"), ("", "")],
)
def test_version_prefix_is_not_doubled(raw, shown):
    """上游 metadata.yaml 的惯例是 ``version: v1.6.4``——v 已经在字符串里了。"""
    head = plugin_check._overview(_facts(plugin_version=raw))[0]
    assert head == f"插件 astrbot_plugin_demo {shown}".rstrip()


def test_tools_without_required_args_are_labelled():
    head = "\n".join(plugin_check._overview(_loaded(tools=[ToolFact(name="ping")])))
    assert "ping(无必填参数)" in head


def test_command_only_plugin_is_told_it_needs_no_declaration():
    head = "\n".join(plugin_check._overview(_loaded(tools=[], capabilities=[])))
    assert "只走指令通路的插件不需要声明" in head


# ── 模板插件：完整流水的回归夹具 ──


def test_template_plugin_passes_the_whole_pipeline():
    """`docs/examples/astrbot_plugin_stella_template` 必须零 error、零 warn。

    走子进程而不是在进程内 ``collect()``：采集会 import 并实例化插件、往全局
    ``llm_tools`` / ``star_registry`` 里登记东西，在 pytest 进程里做会污染
    ``tests/astrbot_compat`` 那些用例。顺带把 CLI 契约一起钉住——退出码与
    stdout 的可解析性（日志必须走 stderr，否则 GUI 的 json.loads 直接失败）。
    """
    from config import PROJECT_ROOT

    template = PROJECT_ROOT / "docs" / "examples" / "astrbot_plugin_stella_template"
    assert template.is_dir(), "模板插件是规范的一部分，不该缺席"

    proc = subprocess.run(
        [sys.executable, "-m", "deploy", "plugin-check", str(template), "--json"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "STELLA_HOME": str(PROJECT_ROOT)},
        timeout=300,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    doc = json.loads(proc.stdout)  # 日志混进 stdout 的话这一行就炸
    assert doc["summary"]["error"] == 0, doc["items"]
    assert doc["summary"]["warn"] == 0, doc["items"]
    assert doc["plugin"]["executed_plugin_code"] is True
    assert [t["name"] for t in doc["plugin"]["tools"]] == ["get_text_stats"]
    caps = doc["plugin"]["declaration"]["capabilities"]
    assert [c["id"] for c in caps] == ["text.stats"]
    assert caps[0]["examples"] >= plugin_check.MIN_EXAMPLES
    assert caps[0]["keywords"] == 0  # 有必填参数 text，刻意不给 keywords
    assert doc["plugin"]["egress"]["declared"] == ["api.example.com"]
