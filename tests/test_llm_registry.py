# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""core.llm.registry 端点 × 角色注册表的测试。

这组用例守的是 P1 的两条硬要求：

1. **纯本地部署逐字等价今天**——闸门拓扑必须还是「主聊天一把、整合一把、
   两者并行」，只是资源名从 ``chat``/``consolidation`` 改成了 ``LOCAL``/``EXTRA``。
   这条是整次改造唯一不可协商的回归面：跑挂了用户就会看到「回复被整合堵住」。
2. **配置问题在启动阶段就报出来**（``validate()``），而不是等第一次调用才 500。

外加一条安全性质：``describe()`` / ``log_summary()`` **绝不输出 API key 的值**，
只报有没有。doctor 报告与启动日志都会被用户贴到 issue 里。

配置一律用 monkeypatch 打在 ``config.settings`` 的属性上——registry 是按属性
访问读配置的（不是 ``from config import X``），这正是为了让测试能改动它。
用例因此不依赖开发机上那份 ``.env``。
"""

from __future__ import annotations

import asyncio
import json

import pytest

import core.llm.registry as registry
from core.llm.lm_studio import LMStudioBackend

# 地址一律**不带** /v1：``LMStudioBackend`` 自己拼 ``/v1/chat/completions``，
# 全项目的 BASE_URL 键（LM_STUDIO_BASE_URL 等）都是这个约定。写成 .../v1 会拼出
# 双 /v1 —— 用例里也照约定写，免得把错的形状当成对的记下来。
_LOCAL_URL = "http://127.0.0.1:1234"
_ONLINE_URL = "https://api.example.com"
_OTHER_URL = "http://192.168.1.9:1234"
# 故意用一个一眼能认出来的值：任何把它带进 describe()/日志的路径都会被下面的
# 用例抓住。真实 key 泄漏一次就是永久泄漏。
_SECRET = "sk-do-not-leak-0123456789"

# 纯本地部署的出厂配置。EXTRA 与 LOCAL 同地址、独立闸门，这就是改造前
# 「27B 一把锁、E4B 一把锁」在新模型下的写法。
_BASELINE: dict[str, object] = {
    "LLM_ENDPOINT_LOCAL_BASE_URL": _LOCAL_URL,
    "LLM_ENDPOINT_LOCAL_API_KEY": "",
    "LLM_ENDPOINT_LOCAL_KIND": "local",
    "LLM_ENDPOINT_LOCAL_CONCURRENCY": 1,
    "LLM_ENDPOINT_LOCAL_TIMEOUT": 120.0,
    "LLM_ENDPOINT_ONLINE_CHAT_BASE_URL": "",
    "LLM_ENDPOINT_ONLINE_CHAT_API_KEY": "",
    "LLM_ENDPOINT_ONLINE_CHAT_KIND": "online",
    "LLM_ENDPOINT_ONLINE_CHAT_CONCURRENCY": 4,
    "LLM_ENDPOINT_ONLINE_CHAT_TIMEOUT": 120.0,
    "LLM_ENDPOINT_ONLINE_MEMORY_BASE_URL": "",
    "LLM_ENDPOINT_ONLINE_MEMORY_API_KEY": "",
    "LLM_ENDPOINT_ONLINE_MEMORY_KIND": "online",
    "LLM_ENDPOINT_ONLINE_MEMORY_CONCURRENCY": 2,
    "LLM_ENDPOINT_ONLINE_MEMORY_TIMEOUT": 120.0,
    "LLM_ENDPOINT_EXTRA_BASE_URL": _LOCAL_URL,
    "LLM_ENDPOINT_EXTRA_API_KEY": "",
    "LLM_ENDPOINT_EXTRA_KIND": "local",
    "LLM_ENDPOINT_EXTRA_CONCURRENCY": 1,
    "LLM_ENDPOINT_EXTRA_TIMEOUT": 120.0,
    "LLM_ROLE_CHAT_ENDPOINT": "LOCAL",
    "LLM_ROLE_CHAT_MODEL": "local-27b",
    "LLM_ROLE_CHAT_TEMPERATURE": 0.7,
    "LLM_ROLE_CHAT_MAX_TOKENS": 2000,
    "LLM_ROLE_CHAT_FALLBACK_ENDPOINT": "",
    "LLM_ROLE_ROUTER_ENDPOINT": "LOCAL",
    "LLM_ROLE_ROUTER_MODEL": "local-27b",
    "LLM_ROLE_ROUTER_TEMPERATURE": 0.7,
    "LLM_ROLE_ROUTER_MAX_TOKENS": 2000,
    "LLM_ROLE_ROUTER_FALLBACK_ENDPOINT": "",
    "LLM_ROLE_PLUGIN_ENDPOINT": "LOCAL",
    "LLM_ROLE_PLUGIN_MODEL": "local-27b",
    "LLM_ROLE_PLUGIN_TEMPERATURE": 0.7,
    "LLM_ROLE_PLUGIN_MAX_TOKENS": 2000,
    "LLM_ROLE_PLUGIN_FALLBACK_ENDPOINT": "",
    "LLM_ROLE_COMPACT_ENDPOINT": "LOCAL",
    "LLM_ROLE_COMPACT_MODEL": "local-27b",
    "LLM_ROLE_COMPACT_TEMPERATURE": 0.3,
    "LLM_ROLE_COMPACT_MAX_TOKENS": 0,
    "LLM_ROLE_COMPACT_FALLBACK_ENDPOINT": "",
    "LLM_ROLE_CONSOLIDATION_ENDPOINT": "EXTRA",
    "LLM_ROLE_CONSOLIDATION_MODEL": "local-e4b",
    "LLM_ROLE_CONSOLIDATION_TEMPERATURE": 0.3,
    "LLM_ROLE_CONSOLIDATION_MAX_TOKENS": 1500,
    "LLM_ROLE_CONSOLIDATION_FALLBACK_ENDPOINT": "",
    "LLM_ROLE_EXTRACT_ENDPOINT": "LOCAL",
    "LLM_ROLE_EXTRACT_MODEL": "local-27b",
    "LLM_ROLE_EXTRACT_TEMPERATURE": 0.3,
    "LLM_ROLE_EXTRACT_MAX_TOKENS": 800,
    "LLM_ROLE_EXTRACT_FALLBACK_ENDPOINT": "",
    "LLM_FALLBACK_ENABLED": True,
    "LLM_FALLBACK_COOLDOWN": 300,
    "MEMORY_EMBEDDING_GATE": "auto",
    "MEMORY_EMBEDDING_BASE_URL": _LOCAL_URL,
    "LLM_SCHEDULER_GATE_EMBEDDING": True,
    "SESSION_SUMMARY_MAX_TOKENS": 300,
    # 旧键：与 LOCAL 同址，纯本地用户不该看到「旧键已失效」告警
    "MEMORY_EXTRACT_LM_STUDIO_BASE_URL": _LOCAL_URL,
    # 继承主键：LLM_ENDPOINT_LOCAL_* / EXTRA_* 留空时都从它继承，
    # 而 _local_slot_override_warning() 直接读它。不钉住就会读开发机的 .env。
    "LM_STUDIO_BASE_URL": _LOCAL_URL,
    "ASTRBOT_LLM_BASE_URL": _LOCAL_URL,
}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """把 settings 钉在「纯本地出厂配置」上，并逐例清空注册表缓存。

    返回一个 ``set(**kw)`` 闭包供用例覆盖某几个键；每次覆盖都会重置缓存，
    因为端点/角色是**首次使用时**一次性解析并缓存的。
    """
    from config import settings

    for key, value in _BASELINE.items():
        monkeypatch.setattr(settings, key, value, raising=False)
    registry.reset_state()

    def _set(**kw):
        for key, value in kw.items():
            monkeypatch.setattr(settings, key, value, raising=False)
        registry.reset_state()

    yield _set
    registry.reset_state()


def _issues(level: str | None = None) -> list[str]:
    return [msg for lv, msg in registry.validate() if level is None or lv == level]


class _FakeLogger:
    """收集日志行，用来断言「日志里绝不出现 key 的值」。"""

    def __init__(self):
        self.lines: list[str] = []

    def _add(self, msg):
        self.lines.append(str(msg))

    info = warning = error = debug = _add


# ============================================================
# 纯本地拓扑等价性（P1 唯一不可协商的回归面）
# ============================================================


def test_pure_local_gate_topology_matches_the_old_two_lock_layout():
    """五个角色一把闸门、整合单独一把——与改造前 chat/consolidation 两把锁同构。"""
    assert registry.gate_of(registry.ROLE_CHAT) == registry.SLOT_LOCAL
    assert registry.gate_of(registry.ROLE_ROUTER) == registry.SLOT_LOCAL
    assert registry.gate_of(registry.ROLE_PLUGIN) == registry.SLOT_LOCAL
    assert registry.gate_of(registry.ROLE_COMPACT) == registry.SLOT_LOCAL
    assert registry.gate_of(registry.ROLE_EXTRACT) == registry.SLOT_LOCAL
    assert registry.gate_of(registry.ROLE_CONSOLIDATION) == registry.SLOT_EXTRA
    # 两把闸门必须是不同资源，否则一次 20~60 秒的整合会把每条回复都堵住
    assert registry.SLOT_LOCAL != registry.SLOT_EXTRA


def test_embedding_shares_the_local_gate_by_default():
    """embedding 与主聊天同实例时共用同一把闸门（改造前的行为）。"""
    assert registry.embedding_gate() == registry.SLOT_LOCAL


def test_pure_local_gates_are_all_exclusive():
    """本地两把闸门并发度都是 1 = 改造前的两把 asyncio.Lock。"""
    assert registry.concurrency_of(registry.SLOT_LOCAL) == 1
    assert registry.concurrency_of(registry.SLOT_EXTRA) == 1


def test_extra_defaults_to_the_same_address_as_local():
    """同一台机器、同一个 LM Studio，但仍是两个独立闸门。

    这是「一台机器两块算力（GPU 跑 27B、CPU 跑 E4B）」的表达方式；
    把它们合成一个槽会静默退化成串行。
    """
    local = registry.endpoint(registry.SLOT_LOCAL)
    extra = registry.endpoint(registry.SLOT_EXTRA)
    assert local is not None
    assert extra is not None
    assert local.base_url == extra.base_url
    assert local.slot != extra.slot


def test_pure_local_config_has_no_errors():
    """出厂配置必须干干净净——启动时刷一屏红字等于让人学会忽略它。"""
    assert _issues("error") == []


def test_issue_levels_are_only_error_or_warn():
    """doctor 按级别渲染，出现第三种级别会被静默丢掉。"""
    assert {lv for lv, _ in registry.validate()} <= {"error", "warn"}


# ============================================================
# 端点解析
# ============================================================


def test_unconfigured_slot_is_none_not_an_empty_endpoint():
    """没配地址的槽 = 没启用。返回空 Endpoint 会让调用方拿它去发请求。"""
    assert registry.endpoint(registry.SLOT_ONLINE_CHAT) is None
    # 但它仍出现在 endpoints() 里——GUI 要能画出这张空卡片
    assert registry.SLOT_ONLINE_CHAT in registry.endpoints()
    assert registry.endpoints()[registry.SLOT_ONLINE_CHAT].configured is False


@pytest.mark.parametrize("name", ["", "   ", "none", "NONE", "NOT_A_SLOT"])
def test_endpoint_rejects_nonslots(name):
    assert registry.endpoint(name) is None


def test_endpoint_lookup_is_case_insensitive():
    assert registry.endpoint("local") is registry.endpoint("LOCAL")


def test_illegal_kind_is_reported_and_treated_as_online(env):
    """KIND 写错时按 online 处理：多带一个 Authorization 头无害，
    反过来把在线端点当本地会漏掉鉴权、并且发出本地专用参数。"""
    env(LLM_ENDPOINT_LOCAL_KIND="cloud", LLM_ENDPOINT_LOCAL_API_KEY=_SECRET)
    ep = registry.endpoint(registry.SLOT_LOCAL)
    assert ep is not None
    assert ep.kind == registry.KIND_ONLINE
    assert any("KIND" in m for m in _issues("error"))


@pytest.mark.parametrize(
    ("api_key", "expected"),
    [("", registry.KIND_LOCAL), (_SECRET, registry.KIND_ONLINE)],
)
def test_blank_kind_is_guessed_from_the_key(env, api_key, expected):
    """KIND 留空不报错（槽可能就没启用），按有没有 key 猜最不容易出错的值。"""
    env(LLM_ENDPOINT_EXTRA_KIND="", LLM_ENDPOINT_EXTRA_API_KEY=api_key)
    ep = registry.endpoint(registry.SLOT_EXTRA)
    assert ep is not None
    assert ep.kind == expected
    assert not any("KIND" in m for m in _issues("error"))


@pytest.mark.parametrize("bad", [0, -3, "abc", None])
def test_bad_concurrency_falls_back_to_one(env, bad):
    """并发度非法一律按 1。Semaphore(0) 会把闸门锁死，绝不能放过去。"""
    env(LLM_ENDPOINT_LOCAL_CONCURRENCY=bad)
    ep = registry.endpoint(registry.SLOT_LOCAL)
    assert ep is not None
    assert ep.concurrency == 1


@pytest.mark.parametrize("bad", ["abc", -1])
def test_bad_timeout_falls_back_to_120(env, bad):
    env(LLM_ENDPOINT_LOCAL_TIMEOUT=bad)
    ep = registry.endpoint(registry.SLOT_LOCAL)
    assert ep is not None
    assert ep.timeout == 120.0
    assert any("TIMEOUT" in m for m in _issues("error"))


def test_a_zero_timeout_is_read_as_unset(env):
    """0 走的是「留空即用默认」那条路（``... or 120.0``），不是配置错误。

    单独成例是因为它与 -1 / "abc" 的行为**不同**：那两个要报错，这个不报。
    """
    env(LLM_ENDPOINT_LOCAL_TIMEOUT=0)
    ep = registry.endpoint(registry.SLOT_LOCAL)
    assert ep is not None
    assert ep.timeout == 120.0
    assert not any("TIMEOUT" in m for m in _issues("error"))


def test_base_url_without_scheme_is_an_error(env):
    """httpx 对没有 scheme 的地址会抛一个跟配置毫无关系的异常，先拦下来。"""
    env(LLM_ENDPOINT_LOCAL_BASE_URL="127.0.0.1:1234")
    assert any("http" in m for m in _issues("error"))


def test_online_endpoint_without_a_key_is_an_error(env):
    """在线端点缺 key 一定 401，等到第一次回复才发现太晚了。"""
    env(
        LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_CHAT_API_KEY="",
    )
    assert any("API_KEY" in m for m in _issues("error"))


def test_local_endpoint_with_concurrency_above_one_warns(env):
    """本地放开并发是个陷阱：同一份权重上的并发推理不排队，只互相拖慢。"""
    env(LLM_ENDPOINT_LOCAL_CONCURRENCY=4)
    assert any("并发" in m for m in _issues("warn"))
    # 只是告警，不该拦住启动
    assert not any("并发上限" in m for m in _issues("error"))


def test_endpoints_are_resolved_once_and_cached():
    assert registry.endpoints() is registry.endpoints()
    assert registry.bindings() is registry.bindings()


# ============================================================
# R1：两域各用一把 key
# ============================================================


def test_sharing_one_key_across_the_two_online_slots_warns(env):
    """R1 的核心：不同 key = 不同前缀缓存域。共用一把会互相顶掉缓存。"""
    env(
        LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_CHAT_API_KEY=_SECRET,
        LLM_ENDPOINT_ONLINE_MEMORY_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_MEMORY_API_KEY=_SECRET,
    )
    warns = _issues("warn")
    assert any("同一把 API key" in m for m in warns)
    # 告警文案里也不许出现 key 本身
    assert not any(_SECRET in msg for _, msg in registry.validate())


def test_two_different_keys_do_not_warn(env):
    env(
        LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_CHAT_API_KEY=_SECRET + "-chat",
        LLM_ENDPOINT_ONLINE_MEMORY_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_MEMORY_API_KEY=_SECRET + "-mem",
    )
    assert not any("同一把 API key" in m for m in _issues("warn"))


# ============================================================
# 角色解析
# ============================================================


def test_role_bound_to_a_nonexistent_slot_is_an_error(env):
    env(LLM_ROLE_CHAT_ENDPOINT="ONLINE")  # 少了 _CHAT 后缀，最常见的手改错误
    assert any("不存在的端点槽" in m for m in _issues("error"))


def test_role_bound_to_an_unconfigured_slot_is_an_error(env):
    env(LLM_ROLE_CHAT_ENDPOINT="ONLINE_CHAT")  # 槽名合法但没配地址
    assert any("没配 BASE_URL" in m for m in _issues("error"))
    assert registry.gate_of(registry.ROLE_CHAT) == registry.GATE_UNBOUND


def test_online_role_without_a_model_is_an_error(env):
    """本地 LM Studio 留空可以让服务端默认路由，在线厂商留空一律 400。"""
    env(
        LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_CHAT_API_KEY=_SECRET,
        LLM_ROLE_CHAT_ENDPOINT="ONLINE_CHAT",
        LLM_ROLE_CHAT_MODEL="",
    )
    assert any("没配 MODEL" in m for m in _issues("error"))


def test_local_role_without_a_model_is_fine(env):
    env(LLM_ROLE_CHAT_MODEL="")
    assert not any("MODEL" in m for m in _issues("error"))


@pytest.mark.parametrize("value", ["", "none", "NONE"])
def test_role_can_be_unbound_on_purpose(env, value):
    """显式关掉某个角色是合法配置，不该报错。"""
    env(LLM_ROLE_ROUTER_ENDPOINT=value)
    b = registry.binding(registry.ROLE_ROUTER)
    assert b is not None
    assert b.bound is False
    assert registry.gate_of(registry.ROLE_ROUTER) == registry.GATE_UNBOUND
    assert registry.backend_for(registry.ROLE_ROUTER) is None
    assert _issues("error") == []


def test_unknown_role_resolves_to_none():
    assert registry.binding("nonexistent") is None
    assert registry.endpoint_of("nonexistent") is None
    assert registry.gate_of("nonexistent") == registry.GATE_UNBOUND


def test_bad_temperature_falls_back(env):
    env(LLM_ROLE_CHAT_TEMPERATURE="warm")
    b = registry.binding(registry.ROLE_CHAT)
    assert b is not None
    assert b.temperature == 0.7
    assert any("TEMPERATURE" in m for m in _issues("error"))


# ---------- COMPACT 的 max_tokens 推导 ----------


def test_compact_max_tokens_is_derived_from_the_summary_cap(env):
    """改造前 session_compact.py 就是「摘要上限 × 3」。

    默认写死一个数字会静默覆盖调过 SESSION_SUMMARY_MAX_TOKENS 的用户，
    所以用 0 表示「按推导算」。
    """
    env(LLM_ROLE_COMPACT_MAX_TOKENS=0, SESSION_SUMMARY_MAX_TOKENS=300)
    b = registry.binding(registry.ROLE_COMPACT)
    assert b is not None
    assert b.max_tokens == 900


def test_compact_derivation_follows_a_tuned_summary_cap(env):
    env(LLM_ROLE_COMPACT_MAX_TOKENS=0, SESSION_SUMMARY_MAX_TOKENS=500)
    b = registry.binding(registry.ROLE_COMPACT)
    assert b is not None
    assert b.max_tokens == 1500


def test_compact_explicit_value_wins(env):
    env(LLM_ROLE_COMPACT_MAX_TOKENS=4096, SESSION_SUMMARY_MAX_TOKENS=300)
    b = registry.binding(registry.ROLE_COMPACT)
    assert b is not None
    assert b.max_tokens == 4096


def test_compact_derivation_is_never_zero(env):
    """摘要上限被配成 0 也不能推出 max_tokens=0（那是「不许输出」）。"""
    env(LLM_ROLE_COMPACT_MAX_TOKENS=0, SESSION_SUMMARY_MAX_TOKENS=0)
    b = registry.binding(registry.ROLE_COMPACT)
    assert b is not None
    assert b.max_tokens >= 1


@pytest.mark.parametrize("bad", [0, -1, "abc"])
def test_other_roles_reject_a_zero_max_tokens(env, bad):
    """只有 COMPACT 的 0 有特殊含义，别的角色 0 就是配错了。"""
    env(LLM_ROLE_CHAT_MAX_TOKENS=bad)
    b = registry.binding(registry.ROLE_CHAT)
    assert b is not None
    assert b.max_tokens == 1024
    assert any("MAX_TOKENS" in m for m in _issues("error"))


# ---------- 降级端点 ----------


def _with_online_fallback(env):
    env(
        LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_CHAT_API_KEY=_SECRET,
        LLM_ROLE_CHAT_ENDPOINT="ONLINE_CHAT",
        LLM_ROLE_CHAT_FALLBACK_ENDPOINT="LOCAL",
    )


def test_fallback_endpoint_is_resolved(env):
    """典型用法：在线为主、本地兜底——断网时还能说话。"""
    _with_online_fallback(env)
    b = registry.binding(registry.ROLE_CHAT)
    assert b is not None
    assert b.slot == registry.SLOT_ONLINE_CHAT
    assert b.fallback is not None
    assert b.fallback.slot == registry.SLOT_LOCAL
    assert b.describe()["fallback_slot"] == registry.SLOT_LOCAL


def test_fallback_to_the_same_slot_is_pointless_and_dropped(env):
    env(LLM_ROLE_CHAT_FALLBACK_ENDPOINT="LOCAL")  # 主端点也是 LOCAL
    b = registry.binding(registry.ROLE_CHAT)
    assert b is not None
    assert b.fallback is None
    assert any("同一个槽" in m for m in _issues("warn"))


def test_fallback_can_be_switched_off_globally(env):
    _with_online_fallback(env)
    env(LLM_FALLBACK_ENABLED=False)
    b = registry.binding(registry.ROLE_CHAT)
    assert b is not None
    assert b.fallback is None
    assert b.describe()["fallback_slot"] == ""


def test_illegal_fallback_slot_is_an_error(env):
    env(LLM_ROLE_CHAT_FALLBACK_ENDPOINT="BACKUP")
    assert any("FALLBACK_ENDPOINT" in m for m in _issues("error"))


def test_fallback_to_an_unconfigured_slot_is_silently_ignored(env):
    """槽名合法但没启用：降级链就是空的，主端点照常工作，不该拦住启动。"""
    env(LLM_ROLE_CHAT_FALLBACK_ENDPOINT="ONLINE_MEMORY")
    b = registry.binding(registry.ROLE_CHAT)
    assert b is not None
    assert b.fallback is None


# ============================================================
# embedding 闸门（R2：embedding 恒定本地）
# ============================================================


def test_auto_picks_the_local_slot_with_the_matching_address():
    assert registry.embedding_gate() == registry.SLOT_LOCAL


def test_auto_ignores_a_trailing_slash(env):
    env(MEMORY_EMBEDDING_BASE_URL=_LOCAL_URL + "/")
    assert registry.embedding_gate() == registry.SLOT_LOCAL


def test_auto_does_not_queue_when_no_local_slot_matches(env):
    """embedding 跑在另一台机器上时排本机的队毫无意义，只会白白串行。"""
    env(MEMORY_EMBEDDING_BASE_URL=_OTHER_URL)
    assert registry.embedding_gate() == ""


def test_auto_never_queues_behind_an_online_endpoint(env):
    """R2：地址凑巧相同也不行——只认 KIND=local 的槽。

    对话切到在线端点后，本地 embedding 若还排在线调用的队，就会被网络往返拖住。
    """
    env(
        LLM_ENDPOINT_LOCAL_KIND="online",
        LLM_ENDPOINT_LOCAL_API_KEY=_SECRET,
        LLM_ENDPOINT_EXTRA_KIND="online",
        LLM_ENDPOINT_EXTRA_API_KEY=_SECRET + "-x",
    )
    assert registry.embedding_gate() == ""


def test_auto_falls_back_to_extra_when_only_it_matches(env):
    """LOCAL 切到在线、EXTRA 仍是本地时，embedding 该跟 EXTRA 共用闸门。"""
    env(
        LLM_ENDPOINT_LOCAL_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_LOCAL_KIND="online",
        LLM_ENDPOINT_LOCAL_API_KEY=_SECRET,
        LLM_ROLE_CHAT_MODEL="online-model",
        LLM_ROLE_ROUTER_MODEL="online-model",
        LLM_ROLE_PLUGIN_MODEL="online-model",
        LLM_ROLE_COMPACT_MODEL="online-model",
        LLM_ROLE_EXTRACT_MODEL="online-model",
    )
    assert registry.embedding_gate() == registry.SLOT_EXTRA


def test_an_explicit_slot_wins(env):
    env(MEMORY_EMBEDDING_GATE="extra")
    assert registry.embedding_gate() == registry.SLOT_EXTRA


def test_none_means_do_not_queue(env):
    env(MEMORY_EMBEDDING_GATE="none")
    assert registry.embedding_gate() == ""


def test_blank_is_treated_as_auto(env):
    env(MEMORY_EMBEDDING_GATE="")
    assert registry.embedding_gate() == registry.SLOT_LOCAL


def test_an_unknown_slot_name_is_reported_and_treated_as_auto(env):
    env(MEMORY_EMBEDDING_GATE="GPU")
    assert registry.embedding_gate() == registry.SLOT_LOCAL
    assert any("MEMORY_EMBEDDING_GATE" in m for m in _issues("error"))


def test_the_hot_path_never_accumulates_issues(env):
    """``embedding_gate()`` 每次语义检索都会被调到；往 _issues 里追加会无限累积。"""
    env(MEMORY_EMBEDDING_GATE="GPU")
    before = len(registry.validate())
    for _ in range(20):
        registry.embedding_gate()
    assert len(registry.validate()) == before


def test_a_legacy_false_still_means_do_not_queue(env):
    """显式关掉排队的用户是**主动**这么做的，不能因为换了新键就悄悄打开。"""
    env(MEMORY_EMBEDDING_GATE="auto", LLM_SCHEDULER_GATE_EMBEDDING=False)
    assert registry.embedding_gate() == ""


def test_an_explicit_slot_overrides_the_legacy_flag(env):
    """新键写了具体槽名 = 新意图，比旧布尔更明确。"""
    env(MEMORY_EMBEDDING_GATE="LOCAL", LLM_SCHEDULER_GATE_EMBEDDING=False)
    assert registry.embedding_gate() == registry.SLOT_LOCAL


def test_no_embedding_address_means_no_queueing(env):
    env(MEMORY_EMBEDDING_BASE_URL="")
    assert registry.embedding_gate() == ""


# ============================================================
# 旧键失效告警
# ============================================================


def test_a_diverging_legacy_extract_address_warns(env):
    """显式把提取指到另一台机器的用户，升级后会被静默改回主地址——必须提醒。"""
    env(MEMORY_EXTRACT_LM_STUDIO_BASE_URL=_OTHER_URL)
    warns = _issues("warn")
    assert any("MEMORY_EXTRACT_LM_STUDIO_BASE_URL" in m for m in warns)
    # 告警要给出可执行的出路，而不只是「已失效」
    assert any(registry.SLOT_EXTRA in m for m in warns)


def test_a_diverging_legacy_plugin_address_warns(env):
    env(ASTRBOT_LLM_BASE_URL=_OTHER_URL)
    assert any("ASTRBOT_LLM_BASE_URL" in m for m in _issues("warn"))


def test_no_warning_once_the_role_has_moved_off_local(env):
    """用户已经把角色挪到别的槽了，旧键本来就不该再生效，提醒纯属噪音。"""
    env(
        MEMORY_EXTRACT_LM_STUDIO_BASE_URL=_OTHER_URL,
        LLM_ROLE_EXTRACT_ENDPOINT="EXTRA",
    )
    assert not any("MEMORY_EXTRACT_LM_STUDIO_BASE_URL" in m for m in _issues("warn"))


def test_trailing_slashes_do_not_trigger_a_false_warning(env):
    env(MEMORY_EXTRACT_LM_STUDIO_BASE_URL=_LOCAL_URL + "/")
    assert not any("MEMORY_EXTRACT_LM_STUDIO_BASE_URL" in m for m in _issues("warn"))


def _override_warns() -> list[str]:
    """只挑 _local_slot_override_warning() 那一条。

    不能按 ``"LM_STUDIO_BASE_URL" in m`` 筛：改了 LOCAL 地址会同时触发上面那条
    ``MEMORY_EXTRACT_LM_STUDIO_BASE_URL`` 旧键告警（键名里也含这个子串），
    否定用例会被它假通过。
    """
    return [m for m in _issues("warn") if "被显式改成" in m]


def test_overriding_only_the_local_slot_address_warns_that_extra_stayed_behind(env):
    """只改 LLM_ENDPOINT_LOCAL_BASE_URL：聊天跟着走了，整合还打在旧地址。

    这是 GUI 隐患 #4：两个地址长得几乎一样，表现是「聊天好了、整合全失败」，
    肉眼对不出来——没有这条告警就只能靠看日志里的连接失败反推。
    """
    env(LLM_ENDPOINT_LOCAL_BASE_URL=_OTHER_URL)
    warns = _override_warns()
    assert warns, "改了 LOCAL 没改主键，必须报"
    # 告警要把两个地址都报出来，否则用户无法确认到底差在哪
    assert any(_OTHER_URL in m and _LOCAL_URL in m for m in warns)
    # 以及可执行的出路：改主键，或把 EXTRA 一并改掉
    assert any("LLM_ENDPOINT_EXTRA_BASE_URL" in m for m in warns)


def test_no_override_warning_when_extra_was_changed_too(env):
    """两边都改了就不是「忘了跟着改」，不该打扰。"""
    env(
        LLM_ENDPOINT_LOCAL_BASE_URL=_OTHER_URL,
        LLM_ENDPOINT_EXTRA_BASE_URL=_OTHER_URL,
    )
    assert not _override_warns()


def test_no_override_warning_on_the_factory_local_config():
    """出厂配置里两者同址（留空即继承的等价形式），不能先吓人一跳。"""
    assert not _override_warns()


def test_no_override_warning_when_extra_points_at_a_third_machine(env):
    """把整合挤到第三台机器是正当用法，不是漏改。"""
    env(
        LLM_ENDPOINT_LOCAL_BASE_URL=_OTHER_URL,
        LLM_ENDPOINT_EXTRA_BASE_URL="http://192.168.1.50:1234",
    )
    assert not _override_warns()


def test_no_override_warning_when_extra_has_moved_online(env):
    """EXTRA 已经是在线端点时，本地地址怎么改都与它无关。"""
    env(
        LLM_ENDPOINT_LOCAL_BASE_URL=_OTHER_URL,
        LLM_ENDPOINT_EXTRA_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_EXTRA_KIND="online",
        LLM_ENDPOINT_EXTRA_API_KEY=_SECRET,
    )
    assert not _override_warns()


# ============================================================
# 后端构造
# ============================================================


def test_backend_carries_every_resolved_field():
    """构造点从此只说「我是哪个角色」，其余全由这里填。"""
    backend = registry.backend_for(registry.ROLE_CHAT)
    assert isinstance(backend, LMStudioBackend)
    # 后端自己拼 /v1/chat/completions，所以这里核对的是拼完的地址
    assert backend.api_url == _LOCAL_URL + "/v1/chat/completions"
    assert backend.model == "local-27b"
    assert backend.max_tokens == 2000
    assert backend.temperature == 0.7
    assert backend.timeout == 120.0
    assert backend.api_key == ""
    assert backend.kind == registry.KIND_LOCAL
    assert backend.is_local is True


def test_backend_knows_its_slot_and_role():
    """槽名与角色名要一路带到后端：日志前缀与用量归集都靠它们分辨是谁在说话。

    漏传不会报错，只会让多端点部署下的日志和账单全部归到同一个匿名桶里。
    """
    backend = registry.backend_for(registry.ROLE_CONSOLIDATION)
    assert isinstance(backend, LMStudioBackend)
    assert backend.slot == registry.SLOT_EXTRA
    assert backend.role == registry.ROLE_CONSOLIDATION
    assert backend._log_tag() == "[LLM consolidation@EXTRA]"


def test_backends_are_cached_per_role():
    assert registry.backend_for(registry.ROLE_CHAT) is registry.backend_for(registry.ROLE_CHAT)
    assert registry.backend_for(registry.ROLE_CHAT) is not registry.backend_for(
        registry.ROLE_CONSOLIDATION
    )


def test_reset_state_rebuilds_backends():
    first = registry.backend_for(registry.ROLE_CHAT)
    registry.reset_state()
    assert registry.backend_for(registry.ROLE_CHAT) is not first


def test_a_role_without_a_fallback_gets_a_bare_backend():
    """不配降级就不包 RoleBackend。

    大量现有测试直接 monkeypatch 后端实例的方法，多一层包装就会失配——
    这是刻意不做「统一包一层」的原因。
    """
    assert type(registry.backend_for(registry.ROLE_CHAT)) is LMStudioBackend


def test_a_role_with_a_fallback_gets_the_wrapper(env):
    _with_online_fallback(env)
    backend = registry.backend_for(registry.ROLE_CHAT)
    assert isinstance(backend, registry.RoleBackend)
    assert isinstance(backend.primary, LMStudioBackend)
    assert isinstance(backend.fallback, LMStudioBackend)
    assert backend.primary.api_url.startswith(_ONLINE_URL)
    assert backend.fallback.api_url.startswith(_LOCAL_URL)
    # 降级端点是本地的，所以它不带 key、也不发在线专用形状
    assert backend.primary.kind == registry.KIND_ONLINE
    assert backend.fallback.kind == registry.KIND_LOCAL


def test_unbound_role_has_no_backend(env):
    env(LLM_ROLE_ROUTER_ENDPOINT="none")
    assert registry.backend_for(registry.ROLE_ROUTER) is None


# ============================================================
# RoleBackend：降级链与冷却
# ============================================================


class _Boom:
    """总是失败的后端。"""

    def __init__(self):
        self.calls = 0

    async def generate_detailed(self, _prompt, _system_prompt=""):
        self.calls += 1
        raise RuntimeError("端点挂了")

    async def generate(self, prompt, system_prompt=""):
        # 必然抛异常；写成转发是为了让两个入口的失败计数一致
        return await self.generate_detailed(prompt, system_prompt)


class _Echo:
    """成功的后端；**只有** ``generate``，用来覆盖 detailed 缺失时的补空串分支。"""

    backend_name = "echo"
    is_local = True
    model = "echo-model"

    def __init__(self, reply="ok"):
        self.calls = 0
        self.reply = reply

    async def generate(self, _prompt, _system_prompt=""):
        self.calls += 1
        return self.reply


class _Clock:
    """替换 registry 命名空间里的 time 模块，把冷却期变成可控的。

    不直接 patch ``time.monotonic``：那会改到全局的 time 模块，
    连 pytest 自己的计时都一起骗过去。
    """

    def __init__(self, now=1000.0):
        self.now = now

    def monotonic(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(registry, "time", c)
    return c


def _role_backend(primary, fallback, cooldown=300.0):
    return registry.RoleBackend(
        role="chat", primary=primary, fallback=fallback, cooldown=cooldown
    )


def test_primary_failure_immediately_retries_on_the_fallback():
    """主端点挂了当轮就要有回复，不能等下一条消息才降级。"""
    primary, fallback = _Boom(), _Echo("兜底回复")
    rb = _role_backend(primary, fallback)
    reply, finish = asyncio.run(rb.generate_detailed("hi"))
    assert reply == "兜底回复"
    assert finish == ""  # _Echo 没有 generate_detailed，补空串
    assert primary.calls == 1
    assert fallback.calls == 1


def test_the_cooldown_stops_hammering_a_dead_primary(clock):
    """不冷却的话，每条消息都要先撞一次挂掉的主端点——等于给每次回复加一个超时。"""
    primary, fallback = _Boom(), _Echo()
    rb = _role_backend(primary, fallback, cooldown=300.0)
    asyncio.run(rb.generate("first"))
    assert primary.calls == 1
    clock.now += 10  # 仍在冷却期内
    asyncio.run(rb.generate("second"))
    assert primary.calls == 1  # 没有再去撞
    assert fallback.calls == 2


def test_the_primary_is_retried_after_the_cooldown(clock):
    """冷却到期自动回主端点，不需要额外探活逻辑。"""
    primary, fallback = _Boom(), _Echo()
    rb = _role_backend(primary, fallback, cooldown=300.0)
    asyncio.run(rb.generate("first"))
    clock.now += 301
    asyncio.run(rb.generate("second"))
    assert primary.calls == 2


def test_a_failure_while_degraded_propagates(clock):
    """降级端点也挂了就该报错，绝不能在两个死端点之间来回重试。"""
    primary, fallback = _Boom(), _Boom()
    rb = _role_backend(primary, fallback, cooldown=300.0)
    with pytest.raises(RuntimeError):
        asyncio.run(rb.generate("first"))
    assert primary.calls == 1
    assert fallback.calls == 1
    # 冷却期内直接走降级端点，失败原样抛出，不再回头撞主端点
    clock.now += 10
    with pytest.raises(RuntimeError):
        asyncio.run(rb.generate("second"))
    assert primary.calls == 1
    assert fallback.calls == 2


def test_zero_cooldown_always_tries_the_primary_first():
    """冷却期配成 0 = 每次都先试主端点（可用于本地调试，代价是每轮多一次超时）。"""
    primary, fallback = _Boom(), _Echo()
    rb = _role_backend(primary, fallback, cooldown=0.0)
    asyncio.run(rb.generate("first"))
    asyncio.run(rb.generate("second"))
    assert primary.calls == 2


def test_a_healthy_primary_never_touches_the_fallback():
    primary, fallback = _Echo("主端点回复"), _Echo("兜底回复")
    rb = _role_backend(primary, fallback)
    assert asyncio.run(rb.generate("hi")) == "主端点回复"
    assert fallback.calls == 0


def test_the_wrapper_proxies_identity_to_the_primary():
    """日志与 usage 统计都读 model/is_local，包一层后必须还是主端点的身份。"""
    rb = _role_backend(_Echo(), _Boom())
    assert rb.model == "echo-model"
    assert rb.is_local is True


# ============================================================
# 可观测性与保密
# ============================================================


def test_describe_covers_every_slot_and_role():
    info = registry.describe()
    assert set(info["endpoints"]) == set(registry.SLOTS)
    assert set(info["roles"]) == set(registry.ROLES)
    assert info["embedding_gate"] == registry.SLOT_LOCAL
    assert info["fallback_enabled"] is True
    assert isinstance(info["issues"], list)


def test_describe_reports_the_gate_per_role():
    """GUI 的角色矩阵直接渲染这一列——它就是「切没切成」的答案。"""
    roles = registry.describe()["roles"]
    assert roles[registry.ROLE_CHAT]["gate"] == registry.SLOT_LOCAL
    assert roles[registry.ROLE_CONSOLIDATION]["gate"] == registry.SLOT_EXTRA


def test_describe_reports_an_unbound_role_as_such(env):
    env(LLM_ROLE_ROUTER_ENDPOINT="none")
    role = registry.describe()["roles"][registry.ROLE_ROUTER]
    assert role["gate"] == registry.GATE_UNBOUND
    assert role["slot"] == ""


def test_embedding_gate_is_reported_as_none_not_blank(env):
    """空串在 GUI 上就是一个空格，用户看不出是「不排队」还是「读失败」。"""
    env(MEMORY_EMBEDDING_GATE="none")
    assert registry.describe()["embedding_gate"] == "none"


def test_endpoint_describe_reports_only_whether_a_key_exists(env):
    env(
        LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_CHAT_API_KEY=_SECRET,
        LLM_ROLE_CHAT_ENDPOINT="ONLINE_CHAT",
        LLM_ROLE_CHAT_MODEL="online-model",
    )
    ep = registry.endpoints()[registry.SLOT_ONLINE_CHAT]
    described = ep.describe()
    assert described["has_api_key"] is True
    assert "api_key" not in described
    assert _SECRET not in json.dumps(described, ensure_ascii=False)


def test_describe_never_leaks_a_key(env):
    """doctor 报告与 GUI 都吃这份 dict，用户会把它整段贴到 issue 里。"""
    env(
        LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_CHAT_API_KEY=_SECRET,
        LLM_ENDPOINT_ONLINE_MEMORY_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_MEMORY_API_KEY=_SECRET,
        LLM_ROLE_CHAT_ENDPOINT="ONLINE_CHAT",
        LLM_ROLE_CHAT_MODEL="online-model",
        LLM_ROLE_CONSOLIDATION_ENDPOINT="ONLINE_MEMORY",
        LLM_ROLE_CONSOLIDATION_MODEL="online-model",
    )
    blob = json.dumps(registry.describe(), ensure_ascii=False, default=str)
    assert _SECRET not in blob
    # 同时确认这份配置真的有 key（否则断言是空跑）
    assert '"has_api_key": true' in blob


def test_log_summary_prints_the_table_without_the_key(env, monkeypatch):
    env(
        LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=_ONLINE_URL,
        LLM_ENDPOINT_ONLINE_CHAT_API_KEY=_SECRET,
        LLM_ROLE_CHAT_ENDPOINT="ONLINE_CHAT",
        LLM_ROLE_CHAT_MODEL="online-model",
    )
    fake = _FakeLogger()
    monkeypatch.setattr(registry, "logger", fake)
    registry.log_summary()
    text = "\n".join(fake.lines)
    assert _SECRET not in text
    # 这张表是「无缝切换可被信任」的前提：角色、端点、闸门都要能一眼看到
    assert registry.ROLE_CHAT in text
    assert registry.SLOT_ONLINE_CHAT in text
    assert "embedding 闸门" in text


def test_log_summary_skips_unconfigured_slots(monkeypatch):
    fake = _FakeLogger()
    monkeypatch.setattr(registry, "logger", fake)
    registry.log_summary()
    text = "\n".join(fake.lines)
    assert f"端点 {registry.SLOT_ONLINE_CHAT}" not in text
    assert f"端点 {registry.SLOT_LOCAL}" in text
