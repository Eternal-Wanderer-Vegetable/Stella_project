# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 端点 × 角色注册表：全项目唯一的后端构造入口。

改造前，六处代码各自 ``LMStudioBackend(base_url=..., model=...)``，
「换成在线模型」意味着六处都要动、且每处读的配置键都不一样。本模块把这件事
收成两层：

- **端点（Endpoint）** = ``base_url`` + ``api_key`` + ``kind`` + **默认模型** + 并发上限
  + 超时。
  它同时是两个东西的单位：**API key 的归属单位**（不同 key = 不同前缀缓存域，
  这是「对话域与记忆域各用一把 key」能提高缓存命中率的前提）与**闸门资源单位**
  （见 ``core.llm.scheduler``）。共四个**静态**槽位：
  ``LOCAL`` / ``ONLINE_CHAT`` / ``ONLINE_MEMORY`` / ``EXTRA``。
- **角色（Role）** = 引用某个端点槽 + ``temperature`` / ``max_tokens`` / 降级端点，
  以及一个**可选的**模型覆盖。共六个角色，对应改造前的六处构造点。

模型 ID 归端点而不是归角色：一个端点通常只对应一家服务商的一份模型清单，
「换服务商」应当只改一处，而不是在六个角色上各写一遍同一个字符串。角色仍能覆盖
（同一端点上某个角色要用更便宜的那档模型），三档解析顺序见 :func:`_resolve_role_model`。

**为什么槽位是固定四个而不是动态列表**：``deploy/env_schema.py`` 用 AST 扫
``config/settings.py`` 里的字面量 ``_env*("KEY", ...)`` 调用来生成 GUI 表单，
动态命名的端点永远不会出现在 GUI 里，用户改不到。静态声明是硬约束。

**纯本地部署逐字等价**：``LOCAL`` 槽默认继承 ``LM_STUDIO_*``、``EXTRA`` 槽默认
继承 ``CONSOLIDATION_LM_STUDIO_*``，且 ``CONSOLIDATION`` 角色默认绑到 ``EXTRA``。
于是改造前「chat 闸门（27B/GPU）与 consolidation 闸门（E4B/CPU）各自串行、彼此
并行」的拓扑被完整保留，只是资源名从 ``chat``/``consolidation`` 变成
``LOCAL``/``EXTRA``。

解析在**首次使用时一次性完成并缓存**，:func:`validate` 由 ``deploy doctor`` 与
启动流程调用，把「槽名写错 / online 缺 key / 模型为空」这类问题在启动阶段就报出来，
而不是等第一次调用才 500。:func:`log_summary` 在启动日志打一张
「角色 → 端点 → 模型 → 闸门」的表——这是「无缝切换」能被信任的前提。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from nonebot import logger

from core.llm.base import LLMBackend
from core.llm.scheduler import set_concurrency_resolver

# ---------- 角色 ----------
ROLE_CHAT = "chat"
ROLE_ROUTER = "router"
ROLE_PLUGIN = "plugin"
ROLE_COMPACT = "compact"
ROLE_CONSOLIDATION = "consolidation"
ROLE_EXTRACT = "extract"

# 顺序即启动日志里的打印顺序：先对话域，再记忆域
ROLES: tuple[str, ...] = (
    ROLE_CHAT,
    ROLE_ROUTER,
    ROLE_PLUGIN,
    ROLE_COMPACT,
    ROLE_CONSOLIDATION,
    ROLE_EXTRACT,
)

# ---------- 端点槽 ----------
SLOT_LOCAL = "LOCAL"
SLOT_ONLINE_CHAT = "ONLINE_CHAT"
SLOT_ONLINE_MEMORY = "ONLINE_MEMORY"
SLOT_EXTRA = "EXTRA"

SLOTS: tuple[str, ...] = (SLOT_LOCAL, SLOT_ONLINE_CHAT, SLOT_ONLINE_MEMORY, SLOT_EXTRA)

KIND_LOCAL = "local"
KIND_ONLINE = "online"

# 角色显式配成「不走 LLM」（ENDPOINT=none / 空）时用的闸门名。
# 为什么不返回空串：``scheduler.acquire("")`` 会建出一把名为空串的闸门，
# 在 snapshot 里显示成一个没有名字的资源，排查时完全看不出是谁。
GATE_UNBOUND = "unbound"

# 会话压缩的 max_tokens 推导系数（改造前 memory/session_compact.py 里的算法）
_COMPACT_MAX_TOKENS_FACTOR = 3


def _settings() -> Any:
    """读 ``config.settings`` 的属性而不是 ``from config import X``。

    ``from config import X`` 在导入时就把名字绑死了，测试 monkeypatch
    ``config.settings.X`` 改不动已绑定的名字。属性访问是刻意的
    （与 ``astrbot_compat.llm.provider`` 同一理由）。
    """
    from config import settings

    return settings


@dataclass(frozen=True)
class Endpoint:
    """一个端点槽的解析结果。

    既是 API key 的归属单位（前缀缓存域），也是闸门资源单位（``slot`` 即资源名）。
    """

    slot: str
    base_url: str
    api_key: str
    kind: str
    concurrency: int
    timeout: float
    # 本槽默认的模型 ID。放在端点上而不是每个角色上重复一遍：一个端点通常只对应
    # 一家服务商的一份模型清单，"换服务商" 就该只改一处。角色仍可覆盖，见
    # _resolve_role_model。
    model: str = ""

    @property
    def is_local(self) -> bool:
        return self.kind == KIND_LOCAL

    @property
    def configured(self) -> bool:
        """有地址就算配好了。``base_url`` 为空的槽等于「没启用」。"""
        return bool(self.base_url)

    def describe(self) -> dict:
        """供 doctor / GUI / 启动日志。**只报有没有 key，绝不报 key 的值。**"""
        return {
            "slot": self.slot,
            "base_url": self.base_url,
            "kind": self.kind,
            "model": self.model,
            "has_api_key": bool(self.api_key),
            "concurrency": self.concurrency,
            "timeout": self.timeout,
        }


@dataclass(frozen=True)
class RoleBinding:
    """一个角色的解析结果：绑到哪个端点、用什么模型与生成参数。"""

    role: str
    slot: str
    endpoint: Endpoint | None
    model: str
    temperature: float
    max_tokens: int
    fallback_slot: str
    fallback: Endpoint | None

    @property
    def bound(self) -> bool:
        return self.endpoint is not None

    def describe(self) -> dict:
        return {
            "role": self.role,
            "slot": self.slot,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "gate": self.slot if self.endpoint is not None else GATE_UNBOUND,
            "kind": self.endpoint.kind if self.endpoint else "",
            "fallback_slot": self.fallback_slot if self.fallback is not None else "",
        }


# ---------- 进程内缓存 ----------
_endpoints: dict[str, Endpoint] | None = None
_bindings: dict[str, RoleBinding] | None = None
_backends: dict[str, LLMBackend] = {}
# 解析期收集的问题：(级别, 文案)。级别为 "error" / "warn"，doctor 直接消费。
_issues: list[tuple[str, str]] = []


def reset_state() -> None:
    """清空全部解析缓存与已构造的后端（测试用；改配置后也需重启进程）。"""
    global _endpoints, _bindings
    _endpoints = None
    _bindings = None
    _backends.clear()
    _issues.clear()


# ---------- 端点解析 ----------


def _endpoint_from_settings(slot: str) -> Endpoint:
    """按 ``LLM_ENDPOINT_<SLOT>_*` 读一个槽；缺失/非法值就地纠正并记 issue。"""
    s = _settings()
    prefix = f"LLM_ENDPOINT_{slot}_"
    base_url = str(getattr(s, prefix + "BASE_URL", "") or "").strip()
    api_key = str(getattr(s, prefix + "API_KEY", "") or "").strip()
    model = str(getattr(s, prefix + "MODEL", "") or "").strip()
    kind = str(getattr(s, prefix + "KIND", "") or "").strip().lower()
    if kind not in (KIND_LOCAL, KIND_ONLINE):
        if kind:
            _issues.append(
                ("error", f"端点 {slot} 的 KIND={kind!r} 非法（只能是 local / online），按 online 处理")
            )
        # 空 kind 不报错：槽本身可能就没启用。按有没有 key 猜一个最不容易出错的值——
        # 有 key 说明是远程服务，没 key 说明是本机 LM Studio。
        kind = KIND_ONLINE if api_key else KIND_LOCAL

    try:
        concurrency = max(1, int(getattr(s, prefix + "CONCURRENCY", 1) or 1))
    except (TypeError, ValueError):
        _issues.append(("error", f"端点 {slot} 的 CONCURRENCY 不是整数，按 1 处理"))
        concurrency = 1
    try:
        timeout = float(getattr(s, prefix + "TIMEOUT", 120.0) or 120.0)
    except (TypeError, ValueError):
        _issues.append(("error", f"端点 {slot} 的 TIMEOUT 不是数字，按 120 秒处理"))
        timeout = 120.0
    if timeout <= 0:
        _issues.append(("error", f"端点 {slot} 的 TIMEOUT={timeout} 无效，按 120 秒处理"))
        timeout = 120.0

    if base_url and not base_url.startswith(("http://", "https://")):
        _issues.append(("error", f"端点 {slot} 的 BASE_URL 缺少 http(s):// 前缀：{base_url!r}"))
    if base_url and kind == KIND_ONLINE and not api_key:
        _issues.append(("error", f"端点 {slot} 是 online 但没配 API_KEY，调用一定 401"))
    # 本地端点放开并发是个陷阱：同一份权重上的并发推理不会排队，只会互相拖慢。
    if kind == KIND_LOCAL and concurrency > 1:
        _issues.append(
            (
                "warn",
                f"端点 {slot} 是本地服务但并发上限 {concurrency}>1，"
                "同一份模型权重上的并发推理只会互相拖慢",
            )
        )
    return Endpoint(
        slot=slot,
        base_url=base_url,
        api_key=api_key,
        kind=kind,
        concurrency=concurrency,
        timeout=timeout,
        model=model,
    )


def endpoints() -> dict[str, Endpoint]:
    """全部四个端点槽的解析结果（含未配置的空槽），懒解析并缓存。"""
    global _endpoints
    if _endpoints is None:
        _endpoints = {slot: _endpoint_from_settings(slot) for slot in SLOTS}
        _check_key_sharing(_endpoints)
    return _endpoints


def _check_key_sharing(resolved: dict[str, Endpoint]) -> None:
    """对话域与记忆域共用一把 key 时告警。

    这是 R1 的核心：**不同 key = 不同前缀缓存域**。两域共用一把 key 时，记忆整合
    那些又长又各不相同的 prompt 会不断顶掉对话域的缓存前缀，命中率反而下降——
    这正是要拆两把 key 的原因，所以配成同一把必须显式提醒。
    """
    chat = resolved.get(SLOT_ONLINE_CHAT)
    mem = resolved.get(SLOT_ONLINE_MEMORY)
    if not chat or not mem or not chat.api_key or not mem.api_key:
        return
    if chat.api_key == mem.api_key:
        _issues.append(
            (
                "warn",
                f"{SLOT_ONLINE_CHAT} 与 {SLOT_ONLINE_MEMORY} 用了同一把 API key，"
                "两域会共享同一个前缀缓存域、互相顶掉缓存，建议各用一把",
            )
        )


def endpoint(slot: str) -> Endpoint | None:
    """按槽名取端点；槽名非法或该槽没配 ``BASE_URL`` 时返回 None。"""
    name = (slot or "").strip().upper()
    if not name or name == "NONE":
        return None
    ep = endpoints().get(name)
    if ep is None or not ep.configured:
        return None
    return ep


# ---------- 角色解析 ----------


def _role_max_tokens(role: str, raw: Any) -> int:
    """角色的 max_tokens；``COMPACT`` 的 0 表示「按会话摘要上限推导」。"""
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        _issues.append(("error", f"角色 {role} 的 MAX_TOKENS 不是整数，按 1024 处理"))
        return 1024
    if value > 0:
        return value
    if role == ROLE_COMPACT:
        # 改造前 session_compact.py 就是这么算的：摘要上限 × 3。默认值写死成一个
        # 数字会静默覆盖调过 SESSION_SUMMARY_MAX_TOKENS 的用户，所以用 0 表示「推导」。
        summary = int(getattr(_settings(), "SESSION_SUMMARY_MAX_TOKENS", 300) or 300)
        return max(1, summary) * _COMPACT_MAX_TOKENS_FACTOR
    _issues.append(("error", f"角色 {role} 的 MAX_TOKENS={value} 无效，按 1024 处理"))
    return 1024


# 角色 MODEL 留空时继承的那个旧键（与 ``config/settings.py`` 里的 ``_env_inherit``
# 声明一一对应）。registry 需要这张表来回答一个 settings 层答不上来的问题：
# **用户到底有没有为这个角色单独指定模型**——``_env_inherit`` 在 settings 层就把
# 留空折叠成了旧键的值，两者到这里已经分不开。拿角色值与旧键值比一下就能分开：
# 相等 = 没单独指定（走端点的模型），不等 = 单独指定了（角色覆盖端点）。
_ROLE_MODEL_LEGACY_KEY: dict[str, str] = {
    ROLE_CHAT: "LM_STUDIO_MODEL",
    ROLE_ROUTER: "LM_STUDIO_MODEL",
    ROLE_PLUGIN: "ASTRBOT_LLM_MODEL",
    ROLE_COMPACT: "LM_STUDIO_MODEL",
    ROLE_CONSOLIDATION: "CONSOLIDATION_LM_STUDIO_MODEL",
    ROLE_EXTRACT: "MEMORY_EXTRACT_LM_STUDIO_MODEL",
}

# 每个旧键「归属」的端点槽——GUI 里那张卡的模型输入框绑的就是这个旧键
# （LOCAL 卡的模型 = LM_STUDIO_MODEL，EXTRA 卡的模型 = CONSOLIDATION_LM_STUDIO_MODEL），
# 所以哪怕用户把这张卡指到在线服务商，旧键里的值也是他**为这张卡**填的，仍然算数。
# 反过来，角色被挪到别的槽（尤其两个在线槽）时旧键就不算了：那里的值是本机模型名。
_LEGACY_MODEL_HOME_SLOT: dict[str, str] = {
    "LM_STUDIO_MODEL": SLOT_LOCAL,
    "ASTRBOT_LLM_MODEL": SLOT_LOCAL,
    "MEMORY_EXTRACT_LM_STUDIO_MODEL": SLOT_LOCAL,
    "CONSOLIDATION_LM_STUDIO_MODEL": SLOT_EXTRA,
}


def _resolve_role_model(role: str, prefix: str, ep: Endpoint | None) -> str:
    """角色最终用的模型 ID。顺序：**角色显式 MODEL → 端点 MODEL → 角色旧键**。

    三档的理由各不相同：

    1. 角色显式 MODEL 最高，因为「同一个端点上某个角色换个模型」是真实需求
       （兜底判定挑更便宜的那档），而这是唯一能表达它的地方；
    2. 端点 MODEL 第二，因为模型清单是随服务商走的——换端点就该换模型，
       而不是让人在六个角色上各写一遍同一个字符串（GUI 的端点卡片即本档）；
    3. 角色旧键垫底，保证存量 ``.env`` 逐字等价：只填了
       ``MEMORY_EXTRACT_LM_STUDIO_MODEL`` 的用户，其 EXTRACT 角色仍用那个小模型。

    为什么第 3 档不能排在第 2 档前面，以及为什么它在在线槽上会被整个跳过：旧键
    大多默认继承 ``LM_STUDIO_MODEL``，也就是**本机模型名**。把本机模型名发给在线
    服务商一律 400，而各家的报错文案还都不一样——远不如在 ``validate()`` 里直接说
    「这张卡没填模型」。所以第 3 档只在两种情况下生效：端点是本机的，或者端点正是
    这个旧键归属的那张卡（见 ``_LEGACY_MODEL_HOME_SLOT``，例如 EXTRA 卡被指到在线
    服务商、模型 ID 就填在 GUI 的「记忆整合模型 ID」里）。
    """
    s = _settings()
    role_model = str(getattr(s, prefix + "MODEL", "") or "").strip()
    legacy_key = _ROLE_MODEL_LEGACY_KEY.get(role, "")
    inherited = str(getattr(s, legacy_key, "") or "").strip() if legacy_key else ""
    if role_model and role_model != inherited:
        return role_model
    if ep is not None and ep.model:
        return ep.model
    if ep is None or ep.kind == KIND_LOCAL or ep.slot == _LEGACY_MODEL_HOME_SLOT.get(legacy_key, ""):
        return role_model
    return ""


def _binding_from_settings(role: str) -> RoleBinding:
    """按 ``LLM_ROLE_<ROLE>_*`` 读一个角色。"""
    s = _settings()
    prefix = f"LLM_ROLE_{role.upper()}_"
    slot_raw = str(getattr(s, prefix + "ENDPOINT", "") or "").strip()
    slot = slot_raw.upper()
    if slot and slot not in SLOTS and slot != "NONE":
        _issues.append(
            (
                "error",
                f"角色 {role} 绑定了不存在的端点槽 {slot_raw!r}"
                f"（合法值：{'/'.join(SLOTS)} 或 none）",
            )
        )
    ep = endpoint(slot)
    if slot and slot in SLOTS and ep is None:
        _issues.append(
            ("error", f"角色 {role} 绑到端点槽 {slot}，但该槽没配 BASE_URL，调用会失败")
        )

    model = _resolve_role_model(role, prefix, ep)
    # 在线端点必须显式给模型 ID：本地 LM Studio 留空由服务端默认路由，
    # 在线厂商留空一律 400，而且报错文案各家都不一样，不如启动就说清楚。
    if ep is not None and ep.kind == KIND_ONLINE and not model:
        _issues.append(
            (
                "error",
                f"角色 {role} 用的是在线端点 {ep.slot}，但没配 MODEL"
                f"（在 LLM_ENDPOINT_{ep.slot}_MODEL 里给该端点配一个，"
                f"或单独写 {prefix}MODEL）",
            )
        )

    try:
        temperature = float(getattr(s, prefix + "TEMPERATURE", 0.7))
    except (TypeError, ValueError):
        _issues.append(("error", f"角色 {role} 的 TEMPERATURE 不是数字，按 0.7 处理"))
        temperature = 0.7

    fallback_raw = str(getattr(s, prefix + "FALLBACK_ENDPOINT", "") or "").strip()
    fallback_slot = fallback_raw.upper()
    if fallback_slot and fallback_slot not in SLOTS and fallback_slot != "NONE":
        _issues.append(
            ("error", f"角色 {role} 的 FALLBACK_ENDPOINT={fallback_raw!r} 不是合法槽名")
        )
    fallback = endpoint(fallback_slot)
    if fallback is not None and ep is not None and fallback.slot == ep.slot:
        _issues.append(
            ("warn", f"角色 {role} 的降级端点与主端点是同一个槽（{ep.slot}），降级不会有效果")
        )
        fallback = None
    if not _fallback_enabled():
        fallback = None

    return RoleBinding(
        role=role,
        slot=ep.slot if ep is not None else "",
        endpoint=ep,
        model=model,
        temperature=temperature,
        max_tokens=_role_max_tokens(role, getattr(s, prefix + "MAX_TOKENS", 0)),
        fallback_slot=fallback.slot if fallback is not None else "",
        fallback=fallback,
    )


def _fallback_enabled() -> bool:
    return bool(getattr(_settings(), "LLM_FALLBACK_ENABLED", True))


def _fallback_cooldown() -> float:
    try:
        return max(0.0, float(getattr(_settings(), "LLM_FALLBACK_COOLDOWN", 300)))
    except (TypeError, ValueError):
        return 300.0


def bindings() -> dict[str, RoleBinding]:
    """全部六个角色的解析结果，懒解析并缓存。"""
    global _bindings
    if _bindings is None:
        endpoints()  # 先解析端点，issue 顺序才是「端点问题在前」
        _bindings = {role: _binding_from_settings(role) for role in ROLES}
    return _bindings


def binding(role: str) -> RoleBinding | None:
    """按角色名取绑定；角色名不认识时返回 None。"""
    return bindings().get(role)


def endpoint_of(role: str) -> Endpoint | None:
    """角色 → 端点；角色未绑定或所绑槽未配置时返回 None。"""
    b = binding(role)
    return b.endpoint if b else None


def gate_of(role: str) -> str:
    """角色 → 闸门资源名（即端点槽名）。

    未绑定的角色返回 :data:`GATE_UNBOUND` 而不是空串——空串会在 snapshot 里
    显示成一把没有名字的闸门，排查时看不出是谁。
    """
    ep = endpoint_of(role)
    return ep.slot if ep is not None else GATE_UNBOUND


def concurrency_of(resource: str) -> int:
    """闸门资源名 → 并发上限。装到 ``scheduler`` 上当解析器用。

    认不出的资源名返回 1（最保守）：宁可多串行，也不能因为读不到配置就放开并发。
    """
    ep = endpoints().get((resource or "").strip().upper())
    return ep.concurrency if ep is not None and ep.configured else 1


def embedding_gate() -> str:
    """embedding 该走哪把闸门；返回空串表示**不排队**。

    ``MEMORY_EMBEDDING_GATE`` 取值 ``auto`` / ``<槽名>`` / ``none``：

    - 显式槽名优先，任何时候都直接生效；
    - ``auto``：**若存在 KIND=local 且 BASE_URL 与 ``MEMORY_EMBEDDING_BASE_URL``
      相同的端点槽 → 共用该槽闸门；否则不排队。** 判定是确定性的，doctor 会打印结果。
    - 留空按 ``auto`` 处理，此时还会看旧布尔键 ``LLM_SCHEDULER_GATE_EMBEDDING``：
      它被显式设成 false 的用户是**主动**关掉排队的，不能因为换了新键就悄悄打开。

    为什么不沿用旧键的语义（挂到主聊天闸门）：旧的前提是「embedding 与主聊天同实例」。
    对话一旦切到在线端点，本地 embedding 就会去排在线调用的队、白白串行。
    """
    s = _settings()
    raw = str(getattr(s, "MEMORY_EMBEDDING_GATE", "auto") or "").strip()
    lowered = raw.lower()
    if raw and lowered not in ("auto", "none"):
        # 槽名认不出时按 auto 处理（问题由 _embedding_gate_warnings 报出来；这里
        # 刻意不记 issue：本函数每次语义检索都会被调到，往 _issues 里追加会无限累积）。
        ep = endpoint(raw.upper())
        if ep is not None:
            return ep.slot
    elif lowered == "none":
        return ""

    # auto（含留空）
    if not bool(getattr(s, "LLM_SCHEDULER_GATE_EMBEDDING", True)):
        return ""
    embed_url = str(getattr(s, "MEMORY_EMBEDDING_BASE_URL", "") or "").strip().rstrip("/")
    if not embed_url:
        return ""
    for slot in SLOTS:
        ep = endpoints()[slot]
        if ep.configured and ep.kind == KIND_LOCAL and ep.base_url.rstrip("/") == embed_url:
            return ep.slot
    return ""


# ---------- 后端构造 ----------


class RoleBackend(LLMBackend):
    """带降级链的角色后端：主端点失败时切到降级端点。

    只在角色**配了**降级端点且 ``LLM_FALLBACK_ENABLED`` 时才包这一层——没配降级的
    角色直接拿到裸 ``LMStudioBackend``，不引入任何额外间接层（现有测试大量
    monkeypatch 后端实例，多一层包装就会失配）。

    **降级调用跑在主端点的闸门里，不会再去抢第二把闸门**：同时持有两把闸门会造成
    跨资源队头阻塞（见 ``core.llm.scheduler`` 的铁律）。代价是降级期间在线端点的
    并发被主端点的上限限住——这个取舍是刻意的：正确性优先于降级时的吞吐。
    """

    backend_name = "role"

    def __init__(self, role: str, primary: LLMBackend, fallback: LLMBackend, cooldown: float):
        self.role = role
        self.primary = primary
        self.fallback = fallback
        self.cooldown = cooldown
        # 主端点连续失败后的冷却截止时间（单调时钟）。0 表示不在冷却中。
        self._cool_until = 0.0

    @property
    def is_local(self) -> bool:
        return bool(getattr(self.primary, "is_local", False))

    @property
    def model(self) -> str:
        return str(getattr(self.primary, "model", "") or "")

    def _active(self) -> tuple[LLMBackend, bool]:
        """当前该用哪个后端；返回 (后端, 是否处于降级中)。"""
        if self.cooldown > 0 and time.monotonic() < self._cool_until:
            return self.fallback, True
        return self.primary, False

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        reply, _ = await self.generate_detailed(prompt, system_prompt)
        return reply

    async def generate_detailed(self, prompt: str, system_prompt: str = "") -> tuple[str, str]:
        backend, degraded = self._active()
        try:
            result = await _detailed(backend, prompt, system_prompt)
        except Exception as e:
            if degraded:
                raise
            # 主端点失败 → 立刻用降级端点重试一次，并进入冷却期，避免每条消息
            # 都先去撞一次已经挂掉的主端点（那等于给每次回复都加上一整个超时）。
            self._cool_until = time.monotonic() + self.cooldown
            logger.warning(
                f"⚠️ [LLM] 角色 {self.role} 主端点失败（{e}），"
                f"切到降级端点并冷却 {self.cooldown:.0f}s"
            )
            return await _detailed(self.fallback, prompt, system_prompt)
        if degraded:
            # 冷却期内成功走的是降级端点，冷却到期后自动回主端点，不需要额外探活。
            logger.debug(f"[LLM] 角色 {self.role} 正在使用降级端点")
        return result


async def _detailed(backend: LLMBackend, prompt: str, system_prompt: str) -> tuple[str, str]:
    """调后端并拿到 ``(文本, finish_reason)``；后端没有 detailed 方法时补空串。"""
    fn = getattr(backend, "generate_detailed", None)
    if fn is not None:
        return await fn(prompt, system_prompt)
    return await backend.generate(prompt, system_prompt), ""


def _build_backend(ep: Endpoint, b: RoleBinding, role: str) -> LLMBackend:
    from core.llm.lm_studio import LMStudioBackend

    return LMStudioBackend(
        base_url=ep.base_url,
        model=b.model,
        max_tokens=b.max_tokens,
        temperature=b.temperature,
        api_key=ep.api_key,
        kind=ep.kind,
        slot=ep.slot,
        role=role,
        timeout=ep.timeout,
    )


def backend_for(role: str) -> LLMBackend | None:
    """角色 → 后端实例（进程内缓存）。角色未绑定端点时返回 None。

    返回 None 是**正常分支**，不是异常：调用方按「该角色不可用」优雅降级
    （``capability/router/fallback._default_backend`` 早就是这个模式）。
    """
    cached = _backends.get(role)
    if cached is not None:
        return cached
    b = binding(role)
    if b is None or b.endpoint is None:
        return None
    backend = _build_backend(b.endpoint, b, role)
    if b.fallback is not None:
        backend = RoleBackend(
            role=role,
            primary=backend,
            fallback=_build_backend(b.fallback, b, role),
            cooldown=_fallback_cooldown(),
        )
    _backends[role] = backend
    return backend


# ---------- 可观测性 ----------


def describe() -> dict:
    """端点 / 角色 / embedding 闸门的完整解析结果，供 doctor、GUI、启动日志。

    **不含任何 API key 值**，只有 ``has_api_key`` 布尔。
    """
    resolved = endpoints()
    bound = bindings()
    return {
        "endpoints": {slot: resolved[slot].describe() for slot in SLOTS},
        "roles": {role: bound[role].describe() for role in ROLES},
        "embedding_gate": embedding_gate() or "none",
        "fallback_enabled": _fallback_enabled(),
        "issues": [{"level": level, "message": msg} for level, msg in validate()],
    }


def validate() -> list[tuple[str, str]]:
    """跑一遍解析并返回问题列表 ``[(级别, 文案)]``；级别为 ``error`` / ``warn``。

    ``deploy doctor`` 与启动流程都调这里，让「槽名写错 / online 缺 key / 模型为空」
    在启动阶段就暴露，而不是等第一次调用才 500。
    """
    bindings()  # 触发解析，填充 _issues
    return list(_issues) + _embedding_gate_warnings() + _legacy_key_warnings()


def _embedding_gate_warnings() -> list[tuple[str, str]]:
    """``MEMORY_EMBEDDING_GATE`` 写了个不存在的槽名时报错。

    单独成函数是因为 :func:`embedding_gate` 每次语义检索都会被调到，
    问题不能记在那条热路径上（会无限累积）。
    """
    raw = str(getattr(_settings(), "MEMORY_EMBEDDING_GATE", "auto") or "").strip()
    if not raw or raw.lower() in ("auto", "none"):
        return []
    if endpoint(raw.upper()) is not None:
        return []
    return [("error", f"MEMORY_EMBEDDING_GATE={raw!r} 不是已配置的端点槽，按 auto 处理")]


def _legacy_key_warnings() -> list[tuple[str, str]]:
    """旧键与新端点地址不一致时告警。

    ``EXTRACT`` 与 ``PLUGIN`` 角色改造后走 ``LOCAL`` 槽，**不再读**
    ``MEMORY_EXTRACT_LM_STUDIO_BASE_URL`` / ``ASTRBOT_LLM_BASE_URL``。这两个键默认
    继承 ``LM_STUDIO_BASE_URL``，所以绝大多数人无感；但**显式改过**它们、想让提取
    或插件走另一台机器的用户，会在升级后被静默改回主地址——必须提醒。

    ``CONSOLIDATION`` 不在此列：``EXTRA`` 槽默认就继承
    ``CONSOLIDATION_LM_STUDIO_BASE_URL``，地址是跟着走的。

    另加一条**反方向**的告警，见 :func:`_local_slot_override_warning`。
    """
    s = _settings()
    local = endpoints()[SLOT_LOCAL]
    if not local.configured:
        return []
    out: list[tuple[str, str]] = []
    base = local.base_url.rstrip("/")
    checks = (
        ("MEMORY_EXTRACT_LM_STUDIO_BASE_URL", ROLE_EXTRACT, SLOT_LOCAL),
        ("ASTRBOT_LLM_BASE_URL", ROLE_PLUGIN, SLOT_LOCAL),
    )
    for key, role, slot in checks:
        b = bindings().get(role)
        if b is None or b.slot != slot:
            continue  # 用户已经把这个角色挪到别的槽了，旧键本来就不该再生效
        legacy = str(getattr(s, key, "") or "").strip().rstrip("/")
        if legacy and legacy != base:
            out.append(
                (
                    "warn",
                    f"{key}={legacy} 与端点槽 {slot} 的地址（{base}）不同，"
                    f"而角色 {role} 现在走 {slot}：旧键已不再生效，"
                    f"若确实要用另一台机器，请把 {role} 绑到 {SLOT_EXTRA} 槽",
                )
            )
    return out + _local_slot_override_warning()


def _local_slot_override_warning() -> list[tuple[str, str]]:
    """``LLM_ENDPOINT_LOCAL_BASE_URL`` 被显式改成与 ``LM_STUDIO_BASE_URL`` 不同的地址。

    这一条是上面那些告警的反方向，而且更容易踩到：``LLM_ENDPOINT_LOCAL_BASE_URL``
    留空即继承 ``LM_STUDIO_BASE_URL``，所以**换本地地址的正确做法是改后者**。
    只改前者的话，聊天立刻跟着走了，但仍由 ``LM_STUDIO_BASE_URL`` 继承下来的那一支
    ——``CONSOLIDATION_LM_STUDIO_BASE_URL`` → ``EXTRA`` 槽（整合 / 会话压缩）——
    还指着旧地址，表现是「聊天好了、整合全失败」，而两处地址长得几乎一样，
    肉眼对不出来。

    只在两者**都非空且不同**、且 ``EXTRA`` 确实还是个本地槽且没跟着改时才报：
    留空是正常的继承状态，把 EXTRA 指向第三台机器也是正常用法，都不该打扰。
    """
    s = _settings()
    override = str(getattr(s, "LLM_ENDPOINT_LOCAL_BASE_URL", "") or "").strip().rstrip("/")
    master = str(getattr(s, "LM_STUDIO_BASE_URL", "") or "").strip().rstrip("/")
    if not override or not master or override == master:
        return []
    extra = endpoints()[SLOT_EXTRA]
    if not extra.configured or not extra.is_local:
        return []
    if extra.base_url.rstrip("/") != master:
        return []  # EXTRA 已被显式改到别处，不是「忘了跟着改」
    return [
        (
            "warn",
            f"端点槽 {SLOT_LOCAL} 的地址被显式改成 {override}，但 "
            f"LM_STUDIO_BASE_URL 仍是 {master}，由它继承的 {SLOT_EXTRA} 槽"
            f"（整合 / 会话压缩）没跟着改，会打到旧地址。"
            f"换本地地址请直接改 LM_STUDIO_BASE_URL，"
            f"或把 LLM_ENDPOINT_EXTRA_BASE_URL 一并改掉",
        )
    ]


def log_summary() -> None:
    """在启动日志打一张「角色 → 端点 → 模型 → 闸门」表，并输出解析问题。

    这张表是「无缝切换」能被信任的前提：切完配置一眼就能确认到底切没切成。
    """
    info = describe()
    logger.info("[LLM] 端点与角色解析结果：")
    for slot in SLOTS:
        ep = info["endpoints"][slot]
        if not ep["base_url"]:
            continue
        logger.info(
            f"[LLM]   端点 {slot}: {ep['base_url']}（{ep['kind']}，"
            f"key={'有' if ep['has_api_key'] else '无'}，"
            f"并发 {ep['concurrency']}，超时 {ep['timeout']:.0f}s）"
        )
    for role in ROLES:
        r = info["roles"][role]
        target = r["slot"] or "（未绑定）"
        extra = f"，降级 {r['fallback_slot']}" if r["fallback_slot"] else ""
        logger.info(
            f"[LLM]   角色 {role}: → {target} / 模型 {r['model'] or '（服务端默认）'} "
            f"/ 闸门 {r['gate']}{extra}"
        )
    logger.info(f"[LLM]   embedding 闸门: {info['embedding_gate']}")
    for issue in info["issues"]:
        if issue["level"] == "error":
            logger.error(f"❌ [LLM] {issue['message']}")
        else:
            logger.warning(f"⚠️ [LLM] {issue['message']}")


# 把并发度解析装到调度器上。写在模块底部而不是函数里：闸门在第一次 acquire 时
# 就要知道并发度，而 acquire 可能发生在任何 import 之后的时刻。用间接注入而不是
# 让 scheduler 直接 import registry，是为了避开 scheduler → registry → settings 的环。
set_concurrency_resolver(concurrency_of)


__all__ = [
    "GATE_UNBOUND",
    "KIND_LOCAL",
    "KIND_ONLINE",
    "ROLES",
    "ROLE_CHAT",
    "ROLE_COMPACT",
    "ROLE_CONSOLIDATION",
    "ROLE_EXTRACT",
    "ROLE_PLUGIN",
    "ROLE_ROUTER",
    "SLOTS",
    "SLOT_EXTRA",
    "SLOT_LOCAL",
    "SLOT_ONLINE_CHAT",
    "SLOT_ONLINE_MEMORY",
    "Endpoint",
    "RoleBackend",
    "RoleBinding",
    "backend_for",
    "binding",
    "bindings",
    "concurrency_of",
    "describe",
    "embedding_gate",
    "endpoint",
    "endpoint_of",
    "endpoints",
    "gate_of",
    "log_summary",
    "reset_state",
    "validate",
]
