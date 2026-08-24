# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Level 2 兜底与三级级联的单测。

核心不变量：**降级是唯一的失败归宿**。embedding 不可用、注册表为空、超时、
任何异常，都返回 ``chat=True, memory=True, tool=False``——路由绝不能成为
主链路的硬依赖，也绝不能因为不确定就凭空调工具。
"""

import asyncio

import pytest

from capability.registry import Capability, CapabilityProvider, CapabilityRegistry
from capability.router import route
from capability.router.fallback import build_catalog, parse_verdict, route_fallback
from capability.router.semantic import reset_prototype_cache
from capability.router.types import (
    LEVEL_DEFAULT,
    LEVEL_DISABLED,
    LEVEL_FALLBACK,
    LEVEL_RULE,
    LEVEL_SEMANTIC,
    Route,
    default_route,
)


def _run(coro):
    return asyncio.run(coro)


class FakeEmbedding:
    def __init__(self, table: dict[str, list[float]], model: str = "fake-embed"):
        self.table = table
        self.model = model

    async def embed(self, text: str):
        return self.table.get(text.strip())


class FakeBackend:
    """假 LLM 后端：按脚本返回文本，或抛异常。"""

    def __init__(self, reply: str = "", boom: bool = False):
        self.reply = reply
        self.boom = boom
        self.prompts: list[str] = []

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.prompts.append(prompt)
        if self.boom:
            raise RuntimeError("backend down")
        return self.reply


@pytest.fixture(autouse=True)
def _clear_prototype_cache():
    reset_prototype_cache()
    yield
    reset_prototype_cache()


@pytest.fixture(autouse=True)
def _router_defaults(monkeypatch):
    """把路由配置钉到已知值，免得测试跟着 .env 漂。"""
    from config import settings

    monkeypatch.setattr(settings, "CAPABILITY_ROUTER_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTER_RULE_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTER_SEMANTIC_ENABLED", True)
    monkeypatch.setattr(settings, "ROUTER_FALLBACK_ENABLED", False)
    monkeypatch.setattr(settings, "ROUTER_SEMANTIC_THRESHOLD", 0.35)
    monkeypatch.setattr(settings, "ROUTER_TOOL_THRESHOLD", 0.45)
    monkeypatch.setattr(settings, "ROUTER_UNCERTAIN_FLOOR", 0.25)
    monkeypatch.setattr(settings, "ROUTER_MAX_CAPABILITIES", 3)
    monkeypatch.setattr(settings, "ROUTER_TIMEOUT", 8.0)


def _cap(cap_id: str, examples: list[str], keywords: list[str] | None = None) -> Capability:
    return Capability(
        id=cap_id,
        description=f"{cap_id} 描述",
        examples=examples,
        keywords=keywords or [],
        providers=[
            CapabilityProvider(
                provider_id=f"{cap_id}#tool",
                capability_id=cap_id,
                tool_name=f"{cap_id}_tool",
            ),
        ],
    )


def _registry(*caps: Capability) -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for cap in caps:
        reg.register(cap)
    return reg


# ---------- Route 类型 ----------


def test_default_route_is_conservative():
    """漏调一次工具用户最多再问一遍；凭空调一次可能真的改变外部状态。"""
    r = default_route("测试")
    assert (r.chat, r.memory, r.tool) == (True, True, False)
    assert r.level == LEVEL_DEFAULT


def test_route_to_dict_is_flat_and_readable():
    from capability.router.types import CapabilityHit

    r = Route(tool=True, capabilities=[CapabilityHit("weather.query", 0.82)], elapsed=0.1234)
    snap = r.to_dict()
    # 不用 asdict：嵌套 dict 在日志里远不如 "weather.query=0.82" 直观
    assert snap["capabilities"] == ["weather.query=0.82"]
    assert snap["elapsed"] == 0.123


def test_route_repr_lists_active_labels():
    assert "chat+memory" in repr(Route())
    assert "tool" in repr(Route(tool=True))


def test_top_score_survives_capability_filtering():
    """回归：top_score 必须是过滤**之前**的最高分。

    ``capabilities`` 被 ROUTER_SEMANTIC_THRESHOLD 过滤过。若从它推最高分，
    落在 (UNCERTAIN_FLOOR, SEMANTIC_THRESHOLD) 的分数会一律读成 0，
    Level 2 的触发区间就被无声地缩窄成 [SEMANTIC_THRESHOLD, TOOL_THRESHOLD)。
    """
    r = Route(capabilities=[], top_score=0.32)
    assert r.top_score == 0.32


# ---------- Level 2 解析 ----------


def test_parse_verdict_extracts_json_from_noise():
    """本地模型常在 JSON 外裹解释文字或 markdown 代码块。"""
    assert parse_verdict('```json\n{"tool": true, "capability": "a.b"}\n```') == (True, "a.b")
    assert parse_verdict('好的：{"tool": false, "capability": ""} 以上') == (False, "")


def test_parse_verdict_accepts_string_booleans():
    assert parse_verdict('{"tool": "true", "capability": "a.b"}') == (True, "a.b")
    assert parse_verdict('{"tool": "是", "capability": "a.b"}') == (True, "a.b")
    assert parse_verdict('{"tool": "no", "capability": ""}') == (False, "")


def test_parse_verdict_returns_none_on_garbage():
    assert parse_verdict("") is None
    assert parse_verdict("完全没有 JSON") is None
    assert parse_verdict("{不是合法 json}") is None
    assert parse_verdict("[1, 2, 3]") is None


def test_build_catalog_omits_examples():
    """examples 是给 embedding 的语料，几十条塞进 prompt 会吃掉本地模型的窗口。"""
    reg = _registry(_cap("a.b", ["示例一", "示例二"]))
    catalog = build_catalog(reg)
    assert "a.b" in catalog
    assert "示例一" not in catalog


# ---------- Level 2 判定 ----------


def test_fallback_disabled_returns_none(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_FALLBACK_ENABLED", False)
    reg = _registry(_cap("a.b", ["x"]))
    assert _run(route_fallback("q", target=reg, backend=FakeBackend('{"tool": true}'))) is None


def test_fallback_picks_capability(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_FALLBACK_ENABLED", True)
    reg = _registry(_cap("weather.query", ["x"]))
    backend = FakeBackend('{"tool": true, "capability": "weather.query"}')
    r = _run(route_fallback("东京怎么样", target=reg, backend=backend))
    assert r is not None
    assert r.tool is True
    assert r.capability_ids == ["weather.query"]
    assert r.level == LEVEL_FALLBACK


def test_fallback_rejects_hallucinated_capability(monkeypatch):
    """模型编出清单外的 id 等于没选出来，按不需要工具处理。"""
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_FALLBACK_ENABLED", True)
    reg = _registry(_cap("weather.query", ["x"]))
    backend = FakeBackend('{"tool": true, "capability": "stock.price"}')
    r = _run(route_fallback("q", target=reg, backend=backend))
    assert r is not None
    assert r.tool is False
    assert r.capabilities == []


def test_fallback_returns_none_on_backend_failure(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_FALLBACK_ENABLED", True)
    reg = _registry(_cap("a.b", ["x"]))
    assert _run(route_fallback("q", target=reg, backend=FakeBackend(boom=True))) is None


def test_fallback_returns_none_on_unparseable_output(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_FALLBACK_ENABLED", True)
    reg = _registry(_cap("a.b", ["x"]))
    assert _run(route_fallback("q", target=reg, backend=FakeBackend("我觉得不需要"))) is None


def test_fallback_returns_none_when_catalog_empty(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_FALLBACK_ENABLED", True)
    backend = FakeBackend('{"tool": true, "capability": "x"}')
    assert _run(route_fallback("q", target=CapabilityRegistry(), backend=backend)) is None


# ---------- 级联 ----------


def test_router_disabled_returns_default(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "CAPABILITY_ROUTER_ENABLED", False)
    r = _run(route("帮我看看天气"))
    assert r.level == LEVEL_DISABLED
    assert r.tool is False


def test_instruction_intent_skips_routing():
    """proactive_at 下 message 是给 Stella 的指令，对它做能力路由是错的。"""
    r = _run(route("生成一句搭话，问问他要不要查天气", intent="proactive_at"))
    assert r.tool is False
    assert "指令型" in r.reason


def test_level0_short_circuits_before_embedding():
    """规则命中就不该再编码——Level 0 存在的意义就是省掉这一步。"""
    reg = _registry(_cap("weather.query", ["明天天气"], keywords=["天气"]))

    class ExplodingEmbedding:
        model = "boom"

        async def embed(self, text: str):
            raise AssertionError("Level 0 命中后不应再调用 embedding")

    r = _run(route("东京天气如何", target=reg, embedding_service=ExplodingEmbedding()))
    assert r.level == LEVEL_RULE
    assert r.capability_ids == ["weather.query"]


def test_level1_runs_when_rules_defer():
    reg = _registry(_cap("weather.query", ["天气如何"]))
    svc = FakeEmbedding({"天气如何": [1.0, 0.0], "weather.query 描述": [1.0, 0.0], "帮我查一下": [1.0, 0.0]})
    r = _run(route("帮我查一下", target=reg, embedding_service=svc))
    assert r.level == LEVEL_SEMANTIC
    assert r.tool is True


def test_semantic_unavailable_degrades():
    """编码失败 → 降级，不是「不需要工具」的结论，但行为上一样保守。"""
    reg = _registry(_cap("weather.query", ["天气如何"]))
    svc = FakeEmbedding({"天气如何": [1.0, 0.0]})  # query 编码失败
    r = _run(route("帮我查一下", target=reg, embedding_service=svc))
    assert r.level == LEVEL_DEFAULT
    assert (r.chat, r.memory, r.tool) == (True, True, False)


def test_empty_registry_degrades():
    svc = FakeEmbedding({"帮我查一下": [1.0, 0.0]})
    r = _run(route("帮我查一下", target=CapabilityRegistry(), embedding_service=svc))
    assert r.level == LEVEL_DEFAULT
    assert r.tool is False


def test_semantic_disabled_degrades(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_SEMANTIC_ENABLED", False)
    reg = _registry(_cap("weather.query", ["天气如何"]))
    r = _run(route("帮我查一下", target=reg))
    assert r.level == LEVEL_DEFAULT
    assert r.tool is False


def test_level2_only_triggers_inside_uncertain_band(monkeypatch):
    """方案第 8 节：避免浪费 27B。确定不需要工具的请求不该走到 Level 2。"""
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_FALLBACK_ENABLED", True)
    reg = _registry(_cap("weather.query", ["天气"]))
    backend = FakeBackend('{"tool": true, "capability": "weather.query"}')

    # 余弦 0.0 → 远低于 UNCERTAIN_FLOOR(0.25)，不进 Level 2
    svc_low = FakeEmbedding(
        {"天气": [1.0, 0.0], "weather.query 描述": [1.0, 0.0], "帮我查一下": [0.0, 1.0]},
    )
    r = _run(route("帮我查一下", target=reg, embedding_service=svc_low, fallback_backend=backend))
    assert r.level == LEVEL_SEMANTIC
    assert backend.prompts == []

    # 余弦 ≈0.316 → 落在 (0.25, 0.45) 不确定带，进 Level 2
    reset_prototype_cache()
    svc_mid = FakeEmbedding(
        {"天气": [1.0, 0.0], "weather.query 描述": [1.0, 0.0], "帮我查一下": [1.0, 3.0]},
    )
    r = _run(route("帮我查一下", target=reg, embedding_service=svc_mid, fallback_backend=backend))
    assert r.level == LEVEL_FALLBACK
    assert len(backend.prompts) == 1


def test_level2_failure_keeps_semantic_conclusion(monkeypatch):
    """兜底不可用时，语义层的「不需要工具」仍然是有效结论。"""
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_FALLBACK_ENABLED", True)
    reg = _registry(_cap("weather.query", ["天气"]))
    svc = FakeEmbedding(
        {"天气": [1.0, 0.0], "weather.query 描述": [1.0, 0.0], "帮我查一下": [1.0, 3.0]},
    )
    r = _run(
        route(
            "帮我查一下",
            target=reg,
            embedding_service=svc,
            fallback_backend=FakeBackend(boom=True),
        ),
    )
    assert r.level == LEVEL_SEMANTIC
    assert r.tool is False


def test_timeout_degrades(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_TIMEOUT", 0.05)
    reg = _registry(_cap("weather.query", ["天气"]))

    class SlowEmbedding:
        model = "slow"

        async def embed(self, text: str):
            await asyncio.sleep(1.0)
            return [1.0, 0.0]

    r = _run(route("帮我查一下", target=reg, embedding_service=SlowEmbedding()))
    assert r.level == LEVEL_DEFAULT
    assert "超时" in r.reason
    assert r.tool is False


def test_exception_degrades_and_never_raises():
    """路由绝不能成为主链路的硬依赖——任何异常都必须被吞成降级。"""
    reg = _registry(_cap("weather.query", ["天气"]))

    class BrokenEmbedding:
        model = "broken"

        async def embed(self, text: str):
            raise RuntimeError("boom")

    r = _run(route("帮我查一下", target=reg, embedding_service=BrokenEmbedding()))
    assert r.level == LEVEL_DEFAULT
    assert r.tool is False
    assert "异常" in r.reason


def test_elapsed_is_recorded():
    r = _run(route("在吗？", target=CapabilityRegistry()))
    assert r.elapsed >= 0.0
