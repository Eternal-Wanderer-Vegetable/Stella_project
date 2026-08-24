# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Level 1 语义路由的单测。

EmbeddingService 全程打桩（``FakeEmbedding``），不发真实 HTTP 请求。
向量刻意用低维手写值，方便直接推算余弦。
异步用例走 ``asyncio.run``（沿用 tests/test_embeddings.py 的惯例，不引 pytest-asyncio）。

重点钉三件事：
1. **原型向量取均值**——个别跑偏的 example 不该把整个能力的召回拉歪；
2. **原型缓存按注册表版本失效**——不失效会让新装的插件永远路由不到（静默）；
3. **None 与「打了分但都很低」是两种情形**——前者降级，后者是有效结论。
"""

import asyncio

import pytest

from capability.registry import Capability, CapabilityProvider, CapabilityRegistry
from capability.router.semantic import (
    _mean_vector,
    build_prototypes,
    reset_prototype_cache,
    route_semantic,
    score_capabilities,
)
from capability.router.types import LEVEL_SEMANTIC


def _run(coro):
    return asyncio.run(coro)


class FakeEmbedding:
    """按文本查表返回向量；查不到返回 None（模拟编码失败）。"""

    def __init__(self, table: dict[str, list[float]], model: str = "fake-embed"):
        self.table = table
        self.model = model
        self.calls: list[str] = []

    async def embed(self, text: str):
        self.calls.append(text)
        return self.table.get(text.strip())


@pytest.fixture(autouse=True)
def _clear_prototype_cache():
    """原型缓存是模块级的，用例之间必须清——否则上一个用例的向量会串味。"""
    reset_prototype_cache()
    yield
    reset_prototype_cache()


def _cap(cap_id: str, examples: list[str], description: str = "") -> Capability:
    return Capability(
        id=cap_id,
        description=description,
        examples=examples,
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


# ---------- 向量工具 ----------


def test_mean_vector_averages_and_normalizes():
    out = _mean_vector([[1.0, 0.0], [0.0, 1.0]])
    assert out is not None
    # 均值 (0.5, 0.5) 归一化后每维 ≈ 0.7071
    assert out[0] == pytest.approx(0.7071, abs=1e-3)
    assert out[1] == pytest.approx(0.7071, abs=1e-3)


def test_mean_vector_drops_mismatched_dimensions():
    """换过 embedding 模型留下的脏缓存不能污染均值。"""
    out = _mean_vector([[1.0, 0.0], [1.0, 0.0, 0.0]])
    assert out == pytest.approx([1.0, 0.0])


def test_mean_vector_handles_empty_and_zero():
    assert _mean_vector([]) is None
    assert _mean_vector([[]]) is None
    assert _mean_vector([[0.0, 0.0]]) is None


# ---------- 原型构建 ----------


def test_prototypes_average_examples_and_description():
    reg = _registry(_cap("a.b", ["e1", "e2"], description="d"))
    svc = FakeEmbedding({"e1": [1.0, 0.0], "e2": [0.0, 1.0], "d": [1.0, 0.0]})
    protos = _run(build_prototypes(reg, svc))
    # 三条语料都被编码（examples + description）
    assert set(svc.calls) == {"e1", "e2", "d"}
    # 均值 (2/3, 1/3) 归一化 → 第一维更大
    assert protos["a.b"][0] > protos["a.b"][1]


def test_capability_with_all_encodings_failed_is_dropped():
    """编码失败的能力只是这一次匹配不上，不该把整个路由拖垮。"""
    reg = _registry(_cap("ok", ["good"]), _cap("bad", ["missing"]))
    svc = FakeEmbedding({"good": [1.0, 0.0]})
    protos = _run(build_prototypes(reg, svc))
    assert set(protos) == {"ok"}


def test_prototype_cache_reused_when_registry_unchanged():
    reg = _registry(_cap("a.b", ["e1"]))
    svc = FakeEmbedding({"e1": [1.0, 0.0]})
    _run(build_prototypes(reg, svc))
    calls = len(svc.calls)
    _run(build_prototypes(reg, svc))
    assert len(svc.calls) == calls  # 未重新编码


def test_prototype_cache_invalidated_on_registry_change():
    """回归：不按版本失效会让新装的插件永远路由不到——静默，只表现为「插件没用」。"""
    reg = _registry(_cap("a.b", ["e1"]))
    svc = FakeEmbedding({"e1": [1.0, 0.0], "e2": [0.0, 1.0]})
    _run(build_prototypes(reg, svc))
    reg.register(_cap("c.d", ["e2"]))
    protos = _run(build_prototypes(reg, svc))
    assert set(protos) == {"a.b", "c.d"}


def test_prototype_cache_invalidated_on_model_change():
    """换了 embedding 模型，旧模型的向量不能继续用（维度/语义空间都不同）。"""
    reg = _registry(_cap("a.b", ["e1"]))
    _run(build_prototypes(reg, FakeEmbedding({"e1": [1.0, 0.0]}, model="m1")))
    svc2 = FakeEmbedding({"e1": [0.0, 1.0]}, model="m2")
    protos = _run(build_prototypes(reg, svc2))
    assert protos["a.b"] == pytest.approx([0.0, 1.0])


# ---------- 打分 ----------


def test_score_capabilities_sorted_desc():
    reg = _registry(_cap("near", ["n"]), _cap("far", ["f"]))
    svc = FakeEmbedding({"n": [1.0, 0.0], "f": [0.0, 1.0], "q": [0.9, 0.1]})
    hits = _run(score_capabilities("q", reg, svc))
    assert hits is not None
    assert [h.capability_id for h in hits] == ["near", "far"]
    assert hits[0].score > hits[1].score


def test_score_returns_none_when_query_encoding_fails():
    """None 表示语义层不可用 → 调用方降级；不是「分数都很低」。"""
    reg = _registry(_cap("a.b", ["e1"]))
    svc = FakeEmbedding({"e1": [1.0, 0.0]})
    assert _run(score_capabilities("unknown-query", reg, svc)) is None


def test_score_returns_none_when_no_routable_capability():
    svc = FakeEmbedding({"q": [1.0, 0.0]})
    assert _run(score_capabilities("q", CapabilityRegistry(), svc)) is None


def test_score_returns_none_for_blank_message():
    reg = _registry(_cap("a.b", ["e1"]))
    assert _run(score_capabilities("  ", reg, FakeEmbedding({}))) is None


def test_score_is_deterministic_on_ties():
    """同分按 id 排序，保证 benchmark 可比对。"""
    reg = _registry(_cap("b.b", ["x"]), _cap("a.a", ["y"]))
    svc = FakeEmbedding({"x": [1.0, 0.0], "y": [1.0, 0.0], "q": [1.0, 0.0]})
    hits = _run(score_capabilities("q", reg, svc))
    assert hits is not None
    assert [h.capability_id for h in hits] == ["a.a", "b.b"]


# ---------- 路由判定 ----------


def test_route_semantic_flags_tool_above_threshold():
    reg = _registry(_cap("hit", ["h"]))
    svc = FakeEmbedding({"h": [1.0, 0.0], "q": [1.0, 0.0]})
    route = _run(route_semantic("q", target=reg, service=svc))
    assert route is not None
    assert route.tool is True
    assert route.capability_ids == ["hit"]
    assert route.level == LEVEL_SEMANTIC


def test_route_semantic_reports_no_tool_below_threshold():
    """低分是**有效结论**（不需要工具），不是不可用——不能返回 None。"""
    reg = _registry(_cap("hit", ["h"]))
    svc = FakeEmbedding({"h": [1.0, 0.0], "q": [0.0, 1.0]})
    route = _run(route_semantic("q", target=reg, service=svc))
    assert route is not None
    assert route.tool is False
    assert route.level == LEVEL_SEMANTIC
    assert "未达工具置信线" in route.reason


def test_route_semantic_respects_max_capabilities(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_MAX_CAPABILITIES", 2)
    reg = _registry(_cap("a", ["x"]), _cap("b", ["x2"]), _cap("c", ["x3"]))
    svc = FakeEmbedding(
        {"x": [1.0, 0.0], "x2": [1.0, 0.0], "x3": [1.0, 0.0], "q": [1.0, 0.0]},
    )
    route = _run(route_semantic("q", target=reg, service=svc))
    assert route is not None
    assert len(route.capabilities) == 2


def test_route_semantic_threshold_is_configurable(monkeypatch):
    """回归：配置必须在调用时读 config.settings，否则测试改不动它。"""
    from config import settings

    reg = _registry(_cap("hit", ["h"]))
    # 余弦 ≈ 0.7071，默认 TOOL_THRESHOLD=0.45 会命中
    svc = FakeEmbedding({"h": [1.0, 0.0], "q": [0.7071, 0.7071]})
    assert _run(route_semantic("q", target=reg, service=svc)).tool is True

    reset_prototype_cache()
    monkeypatch.setattr(settings, "ROUTER_TOOL_THRESHOLD", 0.9)
    assert _run(route_semantic("q", target=reg, service=svc)).tool is False


def test_route_semantic_passes_memory_through():
    """语义层不改 memory：embedding 相似度对「要不要回忆」没有区分力。"""
    reg = _registry(_cap("hit", ["h"]))
    svc = FakeEmbedding({"h": [1.0, 0.0], "q": [1.0, 0.0]})
    route = _run(route_semantic("q", target=reg, service=svc, memory=False))
    assert route is not None
    assert route.memory is False


def test_route_semantic_returns_none_when_unusable():
    reg = _registry(_cap("hit", ["h"]))
    svc = FakeEmbedding({"h": [1.0, 0.0]})  # query 编码失败
    assert _run(route_semantic("q", target=reg, service=svc)) is None
