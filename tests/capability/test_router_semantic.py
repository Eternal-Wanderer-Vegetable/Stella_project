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

外加 2026-08-25 标定后新增的两组：
4. **相对间距裁剪**——绝对地板治不了「搭车能力」，只有相对间距能（见 select_hits）；
5. **原型缓存增量落盘**——整轮才写会在超时时丢掉全部进度。
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
    select_hits,
    warmup,
)
from capability.router.types import LEVEL_SEMANTIC, CapabilityHit


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
    svc = FakeEmbedding({"h": [1.0, 0.0], "q": [1.0, 0.0]})
    monkeypatch.setattr(settings, "ROUTER_TOOL_THRESHOLD", 0.5)
    assert _run(route_semantic("q", target=reg, service=svc)).tool is True

    reset_prototype_cache()
    monkeypatch.setattr(settings, "ROUTER_TOOL_THRESHOLD", 1.5)
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


# ---------- 相对间距裁剪（搭车能力） ----------


class _S:
    """最小化的配置替身，只带 select_hits 用到的四项。"""

    def __init__(self, floor=0.5, margin=0.12, cap=3):
        self.ROUTER_SEMANTIC_THRESHOLD = floor
        self.ROUTER_CAPABILITY_MARGIN = margin
        self.ROUTER_MAX_CAPABILITIES = cap


def _hits(*pairs):
    return [CapabilityHit(capability_id=c, score=s) for c, s in pairs]


def test_select_hits_drops_passengers_by_margin():
    """首轮实测的核心问题：搭车能力会各自执行一次并把结果当「真实数据」送进 prompt。

    分数取自 2026-08-24 的实测形状（正确能力 0.91，搭车 0.69/0.68）。
    """
    out = select_hits(_hits(("right", 0.91), ("rider1", 0.69), ("rider2", 0.68)), _S())
    assert [h.capability_id for h in out] == ["right"]


def test_select_hits_keeps_genuine_multi_capability_request():
    """两个意图都强的句子本来就该都执行——间距裁剪不能把它也砍掉。"""
    out = select_hits(_hits(("a", 0.88), ("b", 0.85)), _S())
    assert [h.capability_id for h in out] == ["a", "b"]


def test_select_hits_margin_cannot_be_replaced_by_absolute_floor():
    """回归：绝对地板治不了搭车——搭车分数(0.69)高于任何不误杀正样本(0.85)的地板。"""
    hits = _hits(("right", 0.91), ("rider", 0.69))
    # 地板必须低于正样本才不误杀，此时地板放过了搭车
    assert len(select_hits(hits, _S(floor=0.60, margin=0))) == 2
    # 换成间距就分开了
    assert len(select_hits(hits, _S(floor=0.60, margin=0.12))) == 1


def test_select_hits_margin_zero_disables_cut():
    hits = _hits(("a", 0.91), ("b", 0.69))
    assert len(select_hits(hits, _S(margin=0.0))) == 2


def test_select_hits_absolute_floor_still_applies():
    """间距放过的低分仍要被绝对地板拦住。"""
    out = select_hits(_hits(("a", 0.55), ("b", 0.49)), _S(floor=0.5, margin=0.2))
    assert [h.capability_id for h in out] == ["a"]


def test_select_hits_respects_max_capabilities():
    out = select_hits(_hits(("a", 0.9), ("b", 0.9), ("c", 0.9), ("d", 0.9)), _S(cap=2))
    assert len(out) == 2


def test_select_hits_empty():
    assert select_hits([], _S()) == []


def test_route_semantic_applies_margin(monkeypatch):
    """端到端：间距裁剪要真的作用在 Route.capabilities 上。"""
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_TOOL_THRESHOLD", 0.5)
    monkeypatch.setattr(settings, "ROUTER_SEMANTIC_THRESHOLD", 0.3)
    monkeypatch.setattr(settings, "ROUTER_CAPABILITY_MARGIN", 0.2)
    reg = _registry(_cap("right", ["h"]), _cap("rider", ["r"]))
    # query 与 right 完全同向(1.0)、与 rider 夹角 45°(≈0.707)，落差 0.29 > 0.2
    svc = FakeEmbedding(
        {"h": [1.0, 0.0], "r": [0.0, 1.0], "q": [0.9239, 0.3827]},
    )
    route = _run(route_semantic("q", target=reg, service=svc))
    assert route is not None
    assert route.tool is True
    assert route.capability_ids == ["right"]


def test_no_tool_route_lists_hits_without_margin_cut(monkeypatch):
    """不执行时列表是诊断用的——裁掉就看不出第二三名离得有多近。"""
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_TOOL_THRESHOLD", 1.5)
    monkeypatch.setattr(settings, "ROUTER_SEMANTIC_THRESHOLD", 0.3)
    monkeypatch.setattr(settings, "ROUTER_CAPABILITY_MARGIN", 0.05)
    reg = _registry(_cap("a", ["h"]), _cap("b", ["r"]))
    svc = FakeEmbedding({"h": [1.0, 0.0], "r": [0.0, 1.0], "q": [0.9239, 0.3827]})
    route = _run(route_semantic("q", target=reg, service=svc))
    assert route is not None
    assert route.tool is False
    assert len(route.capabilities) == 2


# ---------- 原型缓存的增量落盘 ----------


def test_prototypes_written_incrementally_survive_cancellation():
    """回归：整轮算完才写缓存的话，被 ROUTER_TIMEOUT 取消就一条都不留，
    下一条消息从零重来——表现为「工具连续好几轮不触发」且不报错。

    声明文件把原型语料从每个能力 1 句涨到 4~6 句，这个窗口被放大了约 5 倍。
    """
    reg = _registry(_cap("a", ["e1"]), _cap("b", ["e2"]), _cap("c", ["e3"]))
    table = {"e1": [1.0, 0.0], "e2": [0.0, 1.0], "e3": [1.0, 1.0]}

    class SlowThenCancel(FakeEmbedding):
        async def embed(self, text: str):
            if text == "e3":
                raise asyncio.CancelledError
            return await super().embed(text)

    svc = SlowThenCancel(table)
    with pytest.raises(asyncio.CancelledError):
        _run(build_prototypes(reg, svc))

    # 前两个已经落盘：换一个正常的服务接着算，只需要补 e3
    svc2 = FakeEmbedding(table)
    protos = _run(build_prototypes(reg, svc2))
    assert set(protos) == {"a", "b", "c"}
    assert svc2.calls == ["e3"]


def test_failed_capability_is_retried_next_time():
    """编码失败不该被当成「这一版算完了」——否则服务恢复后它永远匹配不上。"""
    reg = _registry(_cap("ok", ["good"]), _cap("bad", ["missing"]))
    svc = FakeEmbedding({"good": [1.0, 0.0]})
    assert set(_run(build_prototypes(reg, svc))) == {"ok"}

    svc2 = FakeEmbedding({"good": [1.0, 0.0], "missing": [0.0, 1.0]})
    assert set(_run(build_prototypes(reg, svc2))) == {"ok", "bad"}
    # 已成功的没有重算
    assert svc2.calls == ["missing"]


# ---------- 预热 ----------


def test_warmup_fills_cache():
    reg = _registry(_cap("a", ["e1"]))
    svc = FakeEmbedding({"e1": [1.0, 0.0]})
    assert _run(warmup(reg, svc)) == 1


def test_warmup_never_raises_on_timeout():
    """预热失败只是首条消息慢一点，绝不能拖累启动。"""
    reg = _registry(_cap("a", ["e1"]))

    class Hang(FakeEmbedding):
        async def embed(self, text: str):
            await asyncio.sleep(10)
            return [1.0, 0.0]

    assert _run(warmup(reg, Hang({}), timeout=0.01)) == 0


def test_warmup_never_raises_on_error():
    reg = _registry(_cap("a", ["e1"]))

    class Boom(FakeEmbedding):
        async def embed(self, text: str):
            raise RuntimeError("embedding 服务炸了")

    assert _run(warmup(reg, Boom({}))) == 0
