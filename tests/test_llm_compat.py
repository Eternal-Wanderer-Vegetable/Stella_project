# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""core.llm.compat 参数差异自适应层的单元测试。

本模块守的是**厂商中立**这条硬约束（方案 §4.3）：差异一律做成「按错误体关键词
自适应 + 记住结果」，绝不能退化成厂商白名单。所以这里的用例都不提任何厂商名字，
只喂各家实际会返回的**措辞**——换一家只要措辞里带同样的关键词就该照样命中。

契约层面的端到端验证（真的发一次请求、真的重试一次）在 test_openai_contract.py。
"""

from __future__ import annotations

import json

import pytest

import core.llm.compat as compat


@pytest.fixture(autouse=True)
def _clean_compat():
    """每个用例前后都清空已学到的形状——它是进程内全局状态。"""
    compat.reset_state()
    yield
    compat.reset_state()


# ---------------------------------------------------------------- 状态归集


def test_compat_is_shared_per_slot():
    """兼容状态按**端点槽**归集：一个槽只交一次学费。"""
    a = compat.compat_for("ONLINE_CHAT")
    b = compat.compat_for("ONLINE_CHAT")
    c = compat.compat_for("ONLINE_MEMORY")
    assert a is b
    assert a is not c


def test_blank_slot_falls_back_to_a_shared_anonymous_bucket():
    """没传 slot 的旧调用点也要有地方放状态，不能每次新建一份（等于学不到）。"""
    assert compat.compat_for("") is compat.compat_for("")


def test_default_shape_is_the_standard_one():
    state = compat.compat_for("LOCAL")
    assert state.max_tokens_field == "max_tokens"
    assert state.omit_temperature is False
    assert state.describe() == "标准形状"


# ---------------------------------------------------------------- shape_payload


def test_shape_payload_does_not_mutate_the_original():
    """调用方每次请求都拿同一份 base_payload 过一遍，就地改会累积污染。"""
    state = compat.compat_for("X")
    state.max_tokens_field = "max_completion_tokens"
    base = {"model": "m", "max_tokens": 100, "temperature": 0.7}
    out = compat.shape_payload(base, state)
    assert base == {"model": "m", "max_tokens": 100, "temperature": 0.7}
    assert out == {"model": "m", "max_completion_tokens": 100, "temperature": 0.7}


def test_shape_payload_renames_length_field():
    state = compat.compat_for("X")
    state.max_tokens_field = "max_completion_tokens"
    out = compat.shape_payload({"max_tokens": 7}, state)
    assert "max_tokens" not in out
    assert out["max_completion_tokens"] == 7


def test_shape_payload_drops_temperature():
    state = compat.compat_for("X")
    state.omit_temperature = True
    out = compat.shape_payload({"temperature": 0.7, "max_tokens": 5}, state)
    assert "temperature" not in out
    assert out["max_tokens"] == 5


def test_shape_payload_can_apply_both_fixes():
    state = compat.compat_for("X")
    state.max_tokens_field = "max_completion_tokens"
    state.omit_temperature = True
    out = compat.shape_payload({"max_tokens": 5, "temperature": 0.1, "model": "m"}, state)
    assert out == {"max_completion_tokens": 5, "model": "m"}


def test_shape_payload_is_a_noop_without_the_field():
    """请求体里本来没有 max_tokens 时不许凭空造一个。"""
    state = compat.compat_for("X")
    state.max_tokens_field = "max_completion_tokens"
    assert compat.shape_payload({"model": "m"}, state) == {"model": "m"}


# ---------------------------------------------------------------- learn_from_error


def _body(message: str) -> str:
    """各家 error 结构的嵌套层级都不一样，所以这里刻意包一层再序列化：

    自适应只做**关键词匹配**，不解析固定结构——按结构解析等于又一份隐形白名单。

    ``ensure_ascii=False`` 是有意的：这里模拟的是**原样返回 UTF-8** 的后端。
    转义成 ``\\uXXXX`` 的那一类由 :func:`test_learns_from_ascii_escaped_body`
    单独守着——两条路都得通，否则中文厂商的错误信息等于白拿。
    """
    return json.dumps(
        {"error": {"message": message, "type": "invalid_request_error"}},
        ensure_ascii=False,
    )


@pytest.mark.parametrize(
    "message",
    [
        "Unsupported parameter: 'max_tokens' is not supported with this model. "
        "Use 'max_completion_tokens' instead.",
        "max_tokens 已弃用，请改用 max_completion_tokens",
        "invalid argument max_tokens; expected max_completion_tokens",
    ],
)
def test_learns_the_length_field_from_any_wording_mentioning_it(message):
    """判据只有一条：错误体里直接点了 ``max_completion_tokens`` 这个字段名。

    这是各家弃用 max_tokens 时都会给的提示词，不需要知道是哪一家。
    """
    state = compat.compat_for("S")
    assert compat.learn_from_error(state, 400, _body(message)) == compat.FIX_MAX_TOKENS_FIELD
    assert state.max_tokens_field == "max_completion_tokens"
    assert state.describe() == "长度字段=max_completion_tokens"


@pytest.mark.parametrize(
    "message",
    [
        "Unsupported value: 'temperature' does not support 0.7 with this model. "
        "Only the default (1) value is supported.",
        "temperature is not supported by this model",
        "该模型不支持 temperature 参数",
    ],
)
def test_learns_to_omit_temperature(message):
    state = compat.compat_for("S")
    assert compat.learn_from_error(state, 400, _body(message)) == compat.FIX_OMIT_TEMPERATURE
    assert state.omit_temperature is True
    assert state.describe() == "省略 temperature"


def test_learns_from_ascii_escaped_body():
    r"""``ensure_ascii=True`` 的后端把中文转成 ``\uXXXX``，关键词照样得命中。

    这是中文厂商（含本方案的测试厂商 DeepSeek）的常见形状：错误信息是中文、
    却按纯 ASCII 序列化。少了反转义这一步，所有中文关键词都静默失效，自适应
    退化成「只认英文厂商」——那等于又养出一份隐形白名单（见 §4.3 ②）。
    """
    state = compat.compat_for("S")
    body = json.dumps({"error": {"message": "该模型不支持 temperature 参数"}})
    assert r"\u" in body, "前提失效：这个 body 并没有被转义，本用例就白测了"
    assert compat.learn_from_error(state, 400, body) == compat.FIX_OMIT_TEMPERATURE
    assert state.omit_temperature is True


def test_temperature_alone_is_not_enough():
    """光提到 temperature 不算——「取值超出范围」这类 400 不是参数形状差异。

    要求同时出现「不支持」类措辞，避免把无关 400 也当成可自适应的差异，
    否则一个真正的配置错误会被自适应重试掩盖成「偶尔失败」。
    """
    state = compat.compat_for("S")
    body = _body("temperature must be between 0 and 2, got 9.9")
    assert compat.learn_from_error(state, 400, body) == ""
    assert state.omit_temperature is False


def test_same_fix_is_never_learned_twice():
    """同一改法学第二次说明它不是真因，继续重试只会变成对配置错误的死循环。"""
    state = compat.compat_for("S")
    body = _body("please use max_completion_tokens")
    assert compat.learn_from_error(state, 400, body) == compat.FIX_MAX_TOKENS_FIELD
    assert compat.learn_from_error(state, 400, body) == ""
    assert state.max_tokens_field == "max_completion_tokens"


def test_length_fix_wins_when_both_keywords_appear():
    """两条判据同时命中时先学长度字段：它是确定性的字段名，误判代价更低。"""
    state = compat.compat_for("S")
    body = _body("use max_completion_tokens; temperature is not supported either")
    assert compat.learn_from_error(state, 400, body) == compat.FIX_MAX_TOKENS_FIELD
    # 第二次请求再撞上，才学第二条
    assert compat.learn_from_error(state, 400, body) == compat.FIX_OMIT_TEMPERATURE
    assert state.max_tokens_field == "max_completion_tokens"
    assert state.omit_temperature is True


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 502, 503])
def test_only_400_teaches_anything(status):
    """401/403/429/5xx 不是参数问题，从它们身上「学」出改法只会改坏请求体。"""
    state = compat.compat_for("S")
    assert compat.learn_from_error(state, status, _body("use max_completion_tokens")) == ""
    assert state.max_tokens_field == "max_tokens"


def test_empty_body_teaches_nothing():
    state = compat.compat_for("S")
    assert compat.learn_from_error(state, 400, "") == ""


def test_unrecognized_extra_field_teaches_nothing():
    """最小合规请求体被拒时不该乱猜。

    比如本地专用的 reasoning_effort 误发到在线端点：那不是「参数形状差异」，
    而是我们发错了字段，应该让它显式失败并被 kind 判据修掉。
    """
    state = compat.compat_for("S")
    body = _body("Unrecognized request argument supplied: reasoning_effort")
    assert compat.learn_from_error(state, 400, body) == ""
    assert state.max_tokens_field == "max_tokens"
    assert state.omit_temperature is False


# ---------------------------------------------------------------- 可观测性


def test_snapshot_only_lists_touched_slots():
    compat.compat_for("A")
    state = compat.compat_for("B")
    state.omit_temperature = True
    assert compat.snapshot() == {"A": "标准形状", "B": "省略 temperature"}


def test_reset_state_clears_everything():
    compat.compat_for("A").omit_temperature = True
    compat.reset_state()
    assert compat.snapshot() == {}
    assert compat.compat_for("A").omit_temperature is False
