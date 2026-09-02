# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""`deploy plugin-scaffold` 的单元测试。

模型与 embedding 服务全部打桩：这条命令的价值不在「模型写得好不好」，而在
**它把模型输出收进了哪些约束里**——那些约束是可断言的纯逻辑：

1. 产物必须是 `.draft` 且 `reviewed = false`（两道闸门，见方案 §2.2）；
2. `keywords` 一律不写进声明，候选词只出现在注释里；
3. 手写的那套 TOML 转义必须能被 `capability.loader.parse_declaration` 原样读回；
4. 量化报告的 `separation` 半边**只有数字与能力 id**——它会被
   `plugin_check._plugin_section()` 原样序列化进 `--json`，而路由基准的负样本里有
   真实群聊原文（`tests/test_status_api.py` 那条「响应体不含聊天内容」的同款约束）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from capability.loader import (
    PLUGIN_DECL_DOMAIN,
    PLUGIN_DECL_DRAFT_FILENAME,
    parse_declaration,
)
from capability.registry import (
    KIND_ASTRBOT_TOOL,
    SOURCE_PLUGIN,
    Capability,
    CapabilityProvider,
)
from capability.router import semantic
from deploy import plugin_check, plugin_scaffold
from deploy.plugin_check import PluginFacts, ToolFact
from deploy.plugin_scaffold import Draft

# ---------- 夹具 ----------


def _run(coro):
    """异步用例走 asyncio.run（沿用 tests/test_embeddings.py 的惯例，不引 pytest-asyncio）。"""
    return asyncio.run(coro)


class FakeBackend:
    """`core.llm.registry` 那些后端在本模块眼里只有两件事：`model` 与 `generate`。"""

    def __init__(self, replies: list[str] | str, *, model: str = "fake-chat") -> None:
        self.replies = [replies] if isinstance(replies, str) else list(replies)
        self.model = model
        self.prompts: list[str] = []

    async def generate(self, prompt: str, system: str = "") -> str:
        self.prompts.append(prompt)
        if not self.replies:
            raise RuntimeError("桩里没有更多回复了")
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


class FakeEmbedding:
    """按子串给向量的假 embedding。命中不了就落到 `default`（与谁都不像）。"""

    model = "fake-embed"

    def __init__(
        self,
        table: dict[str, tuple[float, ...]] | None = None,
        *,
        default: tuple[float, ...] = (0.0, 0.0, 1.0),
        available: bool = True,
    ) -> None:
        self.table = table or {}
        self.default = default
        self.available = available

    async def embed(self, text: str) -> list[float] | None:
        if not self.available:
            return None
        for key, vec in self.table.items():
            if key in text:
                return list(vec)
        return list(self.default)


def _tool(name: str = "get_text_stats", **kw) -> ToolFact:
    base = {"description": "统计一段文本的字数与行数", "required": ("text",)}
    base.update(kw)
    return ToolFact(name=name, **base)


def _facts(tmp_path: Path | None = None, **overrides) -> PluginFacts:
    base = {
        "plugin_dir": tmp_path or Path("data/plugins/astrbot_plugin_demo"),
        "dir_name": "astrbot_plugin_demo",
        "plugin_name": "astrbot_plugin_demo",
        "executed_plugin_code": True,
        "tools": [_tool()],
    }
    base.update(overrides)
    return PluginFacts(**base)


def _reply(**overrides) -> str:
    """一份「模型正常作答」的 JSON。"""
    body = {
        "id": "text.stats",
        "domain": "utility",
        "description": "文本字数与行数统计",
        "examples": ["这段话有多少字", "帮我数一下字数", "这段文字有几行", "统计一下行数"],
        "keyword_candidates": ["字数统计"],
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


def _cap(
    cap_id: str,
    *,
    domain: str = "utility",
    examples: list[str],
    tool: str = "get_text_stats",
) -> Capability:
    return Capability(
        id=cap_id,
        domain=domain,
        description="",
        examples=list(examples),
        providers=[
            CapabilityProvider(
                provider_id=f"{cap_id}:{tool}",
                capability_id=cap_id,
                kind=KIND_ASTRBOT_TOOL,
                tool_name=tool,
                source=SOURCE_PLUGIN,
            ),
        ],
        source=SOURCE_PLUGIN,
    )


@pytest.fixture(autouse=True)
def _clean_prototype_cache():
    """原型缓存按 `(registry.version, model)` 作键，而每个用例都新建临时注册表
    ——版本号会撞，不清就会读到上一条用例的原型。"""
    semantic.reset_prototype_cache()
    yield
    semantic.reset_prototype_cache()


# ---------- 解析模型输出 ----------


@pytest.mark.parametrize(
    "raw",
    [
        '{"id": "a.b"}',
        '```json\n{"id": "a.b"}\n```',
        '好的，这是结果：\n{"id": "a.b"}\n希望有帮助',
    ],
)
def test_parse_json_object_tolerates_fences_and_chatter(raw):
    assert plugin_scaffold._parse_json_object(raw) == {"id": "a.b"}


@pytest.mark.parametrize("raw", ["", "没有 JSON", "[1, 2]", '{"未闭合": ', None])
def test_parse_json_object_rejects_non_objects(raw):
    assert plugin_scaffold._parse_json_object(raw) is None


def test_sanitize_id_refuses_the_auto_derived_prefix():
    """`tool.` 是自动派生能力的标记：手写声明用上它，能力清单会把它报成
    「无声明（自动派生）」——用户看到的结论与事实相反，而这不报错。"""
    assert plugin_scaffold._sanitize_id("tool.get_text_stats", "get_text_stats") == (
        f"{PLUGIN_DECL_DOMAIN}.get_text_stats"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Weather.Query", "weather.query"),
        ("  天气查询  ", f"{PLUGIN_DECL_DOMAIN}.get_text_stats"),
        ("", f"{PLUGIN_DECL_DOMAIN}.get_text_stats"),
        ("...", f"{PLUGIN_DECL_DOMAIN}.get_text_stats"),
    ],
)
def test_sanitize_id_normalizes_or_falls_back(raw, expected):
    assert plugin_scaffold._sanitize_id(raw, "get_text_stats") == expected


def test_clean_examples_drops_imperative_duplicates_and_long_ones():
    kept = plugin_scaffold._clean_examples(
        [
            "这段话有多少字",
            "当用户询问字数时调用本工具",  # 指令句（与校验器共用同一判据）
            "这段话有多少字",  # 重复
            "帮" * (plugin_scaffold.MAX_EXAMPLE_CHARS + 1),  # 太长
            "  帮我数一下  字数  ",  # 空白压平
            "",
        ],
    )
    assert kept == ["这段话有多少字", "帮我数一下 字数"]


def test_clean_examples_caps_at_max():
    kept = plugin_scaffold._clean_examples([f"第{i}种问法" for i in range(20)])
    assert len(kept) == plugin_scaffold.MAX_EXAMPLES


def test_clean_keywords_is_empty_when_the_tool_has_required_args():
    """Level 0 只做字面命中、不抽取参数——拍板执行只会让 Comes 去猜必填值。"""
    assert plugin_scaffold._clean_keywords(["字数统计"], [], required=True) == []


def test_clean_keywords_drops_short_words_and_example_slices():
    kept = plugin_scaffold._clean_keywords(
        ["字数统计", "字数", "有多少字", "字数统计", "行数统计"],
        ["这段话有多少字"],
        required=False,
    )
    # 「字数」太短；「有多少字」是 example 的片段（切词坏词的机械化判据）
    assert kept == ["字数统计", "行数统计"]


# ---------- 生成 ----------


def test_generate_drafts_maps_model_output_onto_the_declaration():
    backend = FakeBackend(_reply())
    drafts = _run(plugin_scaffold.generate_drafts(_facts(), backend))
    assert len(drafts) == 1
    draft = drafts[0]
    assert (draft.tool, draft.id, draft.domain) == ("get_text_stats", "text.stats", "utility")
    assert draft.description == "文本字数与行数统计"
    assert draft.examples == ["这段话有多少字", "帮我数一下字数", "这段文字有几行", "统计一下行数"]
    # 工具有必填参数 text → 候选词一并清空，连注释里都不列
    assert draft.keyword_candidates == []
    assert draft.error == ""


def test_keyword_candidates_survive_for_a_no_arg_tool():
    backend = FakeBackend(_reply())
    facts = _facts(tools=[_tool("daily_schedule", required=())])
    drafts = _run(plugin_scaffold.generate_drafts(facts, backend))
    assert drafts[0].keyword_candidates == ["字数统计"]


def test_generate_retries_once_with_a_tighter_instruction():
    backend = FakeBackend(["解释一堆但没有 JSON", _reply()])
    drafts = _run(plugin_scaffold.generate_drafts(_facts(), backend))
    assert drafts[0].error == ""
    assert len(backend.prompts) == 2
    assert plugin_scaffold._RETRY_SUFFIX in backend.prompts[1]
    assert plugin_scaffold._RETRY_SUFFIX not in backend.prompts[0]


def test_generate_gives_up_after_two_tries_and_says_why():
    backend = FakeBackend("完全不是 JSON")
    drafts = _run(plugin_scaffold.generate_drafts(_facts(), backend))
    assert len(backend.prompts) == 2
    assert drafts[0].examples == []
    assert "JSON" in drafts[0].error
    # 失败也要给一个合法 id：草稿要能被 TOML 解析器读回去（否则量化都跑不了）
    assert drafts[0].id == f"{PLUGIN_DECL_DOMAIN}.get_text_stats"


def test_all_imperative_examples_count_as_a_failure():
    backend = FakeBackend(_reply(examples=["当用户询问字数时调用", "用于统计字数"]))
    drafts = _run(plugin_scaffold.generate_drafts(_facts(), backend))
    assert "示例问句" in drafts[0].error


def test_backend_exception_only_costs_that_one_capability():
    class Boom:
        model = "boom"

        async def generate(self, prompt, system=""):
            raise RuntimeError("端点 503")

    facts = _facts(tools=[_tool(), _tool("other_tool")])
    drafts = _run(plugin_scaffold.generate_drafts(facts, Boom()))
    assert [d.tool for d in drafts] == ["get_text_stats", "other_tool"]
    assert all("端点 503" in d.error for d in drafts)


def test_domain_outside_the_allowlist_falls_back_to_plugin():
    """`memory` 是记忆系统自己的域，插件能力挤进去会和「你还记得我说过的话吗」抢判定。"""
    backend = FakeBackend(_reply(domain="memory"))
    drafts = _run(plugin_scaffold.generate_drafts(_facts(), backend))
    assert drafts[0].domain == PLUGIN_DECL_DOMAIN


# ---------- 渲染草稿 ----------


def _render_one(draft: Draft, tool: ToolFact | None = None) -> str:
    facts = _facts(tools=[tool or _tool()])
    return plugin_scaffold.render_draft(facts, [draft])


def _ok_draft(**kw) -> Draft:
    base = {
        "tool": "get_text_stats",
        "id": "text.stats",
        "domain": "utility",
        "description": "文本字数与行数统计",
        "examples": ["这段话有多少字", "帮我数一下字数", "这段文字有几行"],
    }
    base.update(kw)
    return Draft(**base)


def test_draft_carries_both_gates():
    """`.draft` 后缀由文件名给，`reviewed = false` 由内容给——两道都要在。"""
    text = _render_one(_ok_draft())
    assert "reviewed = false" in text
    assert "未经人审" in text.splitlines()[0]


def test_keywords_never_appear_as_a_key():
    """候选词只进注释：Level 0 命中即拍板执行，那个开关只能由人按。"""
    text = _render_one(
        _ok_draft(keyword_candidates=["字数统计", "行数统计"]),
        _tool(required=()),
    )
    assert '# keywords = ["字数统计", "行数统计"]' in text
    assert not any(line.startswith("keywords") for line in text.splitlines())


def test_required_args_suppress_even_the_candidate_list():
    text = _render_one(_ok_draft(keyword_candidates=["字数统计"]), _tool(required=("text",)))
    assert "本条**刻意不给**，也不列候选" in text
    assert "字数统计" not in text


def test_draft_round_trips_through_the_loader(tmp_path):
    """本模块手写 TOML（tomllib 只读不写），所以转义必须靠加载器自己验回来。"""
    draft = _ok_draft(examples=["这段话有多少字", '他说"你好"呢', "路径 C:\\temp 多长"])
    path = tmp_path / PLUGIN_DECL_DRAFT_FILENAME
    path.write_text(_render_one(draft), encoding="utf-8")

    parsed = parse_declaration(path, source=SOURCE_PLUGIN, domain=PLUGIN_DECL_DOMAIN)
    assert parsed.error == ""
    assert parsed.reviewed is False  # 闸门二：改了文件名也仍然不载入
    assert len(parsed.capabilities) == 1
    cap = parsed.capabilities[0]
    assert (cap.id, cap.domain) == ("text.stats", "utility")
    assert cap.examples == draft.examples
    assert cap.keywords == []
    assert [p.tool_name for p in cap.providers] == ["get_text_stats"]


def test_failed_draft_renders_an_inert_shell(tmp_path):
    """生成失败的空壳必须**没有任何原型语料**。

    ``prototype_texts()`` 在没有 examples 时会退到 description，所以留着工具描述的空壳
    一旦被人审通过，就正好是「拿工具描述当语料」那种配置——本模块存在的理由。
    """
    draft = Draft(
        tool="get_text_stats",
        id="plugin.get_text_stats",
        domain=PLUGIN_DECL_DOMAIN,
        description="统计一段文本的字数与行数",
        error="模型输出不是 JSON 对象",
    )
    path = tmp_path / PLUGIN_DECL_DRAFT_FILENAME
    path.write_text(_render_one(draft), encoding="utf-8")
    text = path.read_text(encoding="utf-8")

    assert "⚠ 这条没能生成出来：模型输出不是 JSON 对象" in text
    # 工具描述只出现在注释里，供人参考
    assert "#   工具自己的描述是：统计一段文本的字数与行数" in text

    cap = parse_declaration(path, source=SOURCE_PLUGIN, domain=PLUGIN_DECL_DOMAIN).capabilities[0]
    assert cap.examples == []
    assert cap.description == ""
    assert cap.prototype_texts() == []


# ---------- 量化报告（方案 §2.3） ----------

_A = (1.0, 0.0, 0.0)
_B = (0.0, 1.0, 0.0)


def test_measure_flags_two_capabilities_that_mean_the_same_thing():
    """同域原型挤在一起时，路由基本是在掷骰子——⑫ 那条检查报的就是这个。"""
    service = FakeEmbedding({"多少字": _A, "几个字": (1.0, 0.02, 0.0)})
    result = _run(
        plugin_scaffold.measure(
            [
                _cap("text.count", examples=["这段话有多少字"]),
                _cap("text.length", examples=["这段文字有几个字"], tool="other_tool"),
            ],
            service=service,
        ),
    )
    assert result is not None
    assert result.separation["spread"] < plugin_check.SEPARATION_MIN_SPREAD
    assert result.separation["closest_pair"] == ["text.count", "text.length"]
    verdict = plugin_check.check_separation(PluginFacts(separation=result.separation))
    assert verdict is not None
    assert verdict.level == "warn"
    assert "间距" in verdict.detail


def test_measure_omits_spread_when_nothing_shares_a_domain():
    """键**不写**而不是填个 1.0：假值会让 ⑫ 那条检查以为量过了。"""
    result = _run(
        plugin_scaffold.measure(
            [_cap("text.count", examples=["这段话有多少字"])],
            service=FakeEmbedding({"多少字": _A}),
        ),
    )
    assert "spread" not in result.separation
    assert "不适用" in "\n".join(result.lines)
    assert plugin_check.check_separation(PluginFacts(separation=result.separation)) is None


def test_negative_margin_turns_negative_when_an_unrelated_request_scores_high():
    """`帮我查一下今天的天气` 是基准里的负样本；让它和本能力原型撞成同一个向量，
    余量就该是负数——那正是「工具描述当语料」那一行 −0.024 的形态。"""
    service = FakeEmbedding({"多少字": _A, "今天的天气": _A})
    result = _run(
        plugin_scaffold.measure(
            [_cap("text.count", examples=["这段话有多少字"])],
            service=service,
        ),
    )
    assert result.separation["negative_margin"] < plugin_check.NEGATIVE_MARGIN_MIN
    assert result.separation["negatives_checked"] >= 15
    verdict = plugin_check.check_separation(PluginFacts(separation=result.separation))
    assert verdict is not None and "余量" in verdict.detail


def test_measure_points_at_an_example_that_belongs_to_a_sibling():
    """一条 example 在兄弟能力上得分更高 = 两条的语料串味了。

    ``score_capabilities`` 顺带给出全部能力的得分，所以这个诊断不额外花 embedding。
    """
    service = FakeEmbedding({"多少字": _A, "动画": _B, "新番": _B})
    result = _run(
        plugin_scaffold.measure(
            [
                _cap("text.count", examples=["这段话有多少字", "今天更新什么动画"]),
                _cap("anime.schedule", domain="entertainment",
                     examples=["有什么新番推荐"], tool="anime_tool"),
            ],
            service=service,
        ),
    )
    joined = "\n".join(result.lines)
    assert "串味" in joined
    assert "anime.schedule" in joined
    ids = [row["id"] for row in result.separation["per_capability"]]
    assert ids == ["anime.schedule", "text.count"] or ids == ["text.count", "anime.schedule"]


def test_measure_returns_none_when_embedding_is_unavailable():
    """服务不可用与「量过了、指标不好」是两件事：前者不能变成一份看着达标的报告。"""
    assert _run(
        plugin_scaffold.measure(
            [_cap("text.count", examples=["这段话有多少字"])],
            service=FakeEmbedding(available=False),
        ),
    ) is None


def test_separation_payload_carries_no_benchmark_text():
    """``plugin_check._plugin_section()`` 把 ``facts.separation`` 原样序列化进
    ``--json``，而基准负样本里有真实群聊语料（`主管，这是？` 这类）。所以
    ``separation`` 只许放数字与能力 id——与 ``tests/test_status_api.py`` 同一条约束。

    人要看的那句「哪条负样本最高」放在 ``lines`` 里，只打到终端。
    """
    service = FakeEmbedding({"多少字": _A, "今天的天气": _A})
    result = _run(
        plugin_scaffold.measure(
            [_cap("text.count", examples=["这段话有多少字"])],
            service=service,
        ),
    )
    payload = json.dumps(result.separation, ensure_ascii=False)
    for message, note in plugin_scaffold._negative_messages():
        assert message not in payload
        assert not note or note not in payload
    assert "主管" not in payload
    # 反面：终端那份确实带原文，否则这条约束是靠「报告本来就是空的」蒙过去的
    assert "帮我查一下今天的天气" in "\n".join(result.lines)


def test_report_prints_the_verdict_and_exits_zero():
    """指标不达标是**告警**不是失败：草稿本来就等着人改，退出码得留给真错误。"""
    service = FakeEmbedding({"多少字": _A, "今天的天气": _A})
    code = _run(
        plugin_scaffold._measure_and_report(
            [_cap("text.count", examples=["这段话有多少字"])],
            service=service,
        ),
    )
    assert code == 0


def test_report_says_so_when_it_could_not_measure(capsys):
    service = FakeEmbedding(available=False)
    code = _run(plugin_scaffold._measure_and_report([], service=service))
    assert code == 0
    assert "没有量化报告" in capsys.readouterr().out


# ---------- 命令行的早退分支 ----------


def test_run_rejects_a_path_that_is_not_a_directory(tmp_path):
    assert plugin_scaffold.run(tmp_path / "nope") == 1


def test_run_refuses_to_clobber_an_existing_draft(tmp_path, capsys):
    """草稿是人审过程的载体，改到一半被覆盖就白改了。"""
    (tmp_path / PLUGIN_DECL_DRAFT_FILENAME).write_text("x", encoding="utf-8")
    assert plugin_scaffold.run(tmp_path) == 1
    assert "--force" in capsys.readouterr().out


def test_measure_only_needs_a_declaration_to_measure(tmp_path, capsys):
    assert plugin_scaffold.run(tmp_path, measure_only=True) == 1
    assert PLUGIN_DECL_DRAFT_FILENAME in capsys.readouterr().out


def test_measure_only_reads_the_draft_without_calling_the_model(tmp_path, monkeypatch):
    """``--measure`` 是人审的复算入口：改完 examples 再跑一次看指标动没动，
    这一步不该再花一次模型调用。
    """
    service = FakeEmbedding({"多少字": _A})
    monkeypatch.setattr(semantic, "_get_service", lambda: service)
    monkeypatch.setattr(
        plugin_scaffold, "_resolve_backend",
        lambda endpoint: pytest.fail("--measure 不该碰模型"),
    )
    (tmp_path / PLUGIN_DECL_DRAFT_FILENAME).write_text(
        plugin_scaffold.render_draft(_facts(tmp_path), [_ok_draft(examples=["这段话有多少字"])]),
        encoding="utf-8",
    )
    assert plugin_scaffold.run(tmp_path, measure_only=True) == 0
