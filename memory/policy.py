# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Memory Policy Engine（记忆策略引擎）。

对应设计文档《Memory Policy Matrix Specification v1.0》。核心解决三件事：
1. **Stella Mode 检测**：判断当前行为模式（主动插话/技术回答/推荐/玩梗/情绪…）；
2. **权限过滤**：Mode → Usage 兼容 → Visibility 访问控制 三层过滤，
   保证“语义相关 ≠ 应该使用”，敏感记忆（RESTRICTED/INTERNAL）不会进入聊天素材；
3. **Memory Ranking**：Policy 优先于 Similarity 的加权排序，
   并按 Mode 给出动态条数上限。

同时提供 Policy Validator（对应 Consolidation 的 Gate 3）：对 Consolidator 生成的
记忆候选做 Usage / Visibility 自动修正，把「用户不喜欢摸头 + TOPIC_START」这类
错误分类修正为 BOUNDARY_PROTECTION + RESTRICTED。

本模块是纯逻辑，不依赖数据库，便于单测。
"""

from __future__ import annotations

import re
from typing import Any, Optional

from config import (
    MEMORY_LIMIT_ACTIVE_JOIN,
    MEMORY_LIMIT_CASUAL_REPLY,
    MEMORY_LIMIT_CONFLICT_AVOID,
    MEMORY_LIMIT_EMOTIONAL,
    MEMORY_LIMIT_GROUP_EVENT,
    MEMORY_LIMIT_HUMOR,
    MEMORY_LIMIT_RECOMMEND,
    MEMORY_LIMIT_TECH_HELP,
    MEMORY_SCORE_W_CONFIDENCE,
    MEMORY_SCORE_W_CONTEXT,
    MEMORY_SCORE_W_IMPORTANCE,
    MEMORY_SCORE_W_SEMANTIC,
    MEMORY_SCORE_W_USAGE,
)

# ── 枚举常量 ─────────────────────────────────────────────

# Stella 行为模式
MODE_CASUAL_REPLY = "CASUAL_REPLY"
MODE_ACTIVE_JOIN = "ACTIVE_JOIN"
MODE_HUMOR = "HUMOR"
MODE_TECH_HELP = "TECH_HELP"
MODE_RECOMMEND = "RECOMMEND"
MODE_EMOTIONAL = "EMOTIONAL"
MODE_CONFLICT_AVOID = "CONFLICT_AVOID"
MODE_GROUP_EVENT = "GROUP_EVENT"

ALL_MODES = frozenset(
    {
        MODE_CASUAL_REPLY,
        MODE_ACTIVE_JOIN,
        MODE_HUMOR,
        MODE_TECH_HELP,
        MODE_RECOMMEND,
        MODE_EMOTIONAL,
        MODE_CONFLICT_AVOID,
        MODE_GROUP_EVENT,
    }
)

# Usage 标签
USAGE_TOPIC_START = "TOPIC_START"
USAGE_TOPIC_CONTINUE = "TOPIC_CONTINUE"
USAGE_ANSWER_CONTEXT = "ANSWER_CONTEXT"
USAGE_RECOMMEND = "RECOMMEND"
USAGE_PERSONALIZE = "PERSONALIZE"
USAGE_RELATION_CONTEXT = "RELATION_CONTEXT"
USAGE_GROUP_CONTEXT = "GROUP_CONTEXT"
USAGE_HUMOR = "HUMOR"
USAGE_EMOTIONAL_SUPPORT = "EMOTIONAL_SUPPORT"
USAGE_BOUNDARY_PROTECTION = "BOUNDARY_PROTECTION"
USAGE_CONFLICT_AVOID = "CONFLICT_AVOID"

ALL_USAGES = frozenset(
    {
        USAGE_TOPIC_START,
        USAGE_TOPIC_CONTINUE,
        USAGE_ANSWER_CONTEXT,
        USAGE_RECOMMEND,
        USAGE_PERSONALIZE,
        USAGE_RELATION_CONTEXT,
        USAGE_GROUP_CONTEXT,
        USAGE_HUMOR,
        USAGE_EMOTIONAL_SUPPORT,
        USAGE_BOUNDARY_PROTECTION,
        USAGE_CONFLICT_AVOID,
    }
)

# Visibility 访问等级
VISIBILITY_OPEN = "OPEN"
VISIBILITY_CONTEXTUAL = "CONTEXTUAL"
VISIBILITY_RESTRICTED = "RESTRICTED"
VISIBILITY_INTERNAL = "INTERNAL"

# CONTEXTUAL 记忆需要“主题匹配”才能被调用（Schema 4.4）：
# 与查询几乎没有共享词元的 CONTEXTUAL 记忆不被激活，避免把“用户不吃榴莲”
# 这类信息在聊游戏时被误调用。关键词检索/FTS 命中本身已视为主题匹配，
# 因此这里用很低的阈值只拦截“完全无关联”的记忆。
CONTEXTUAL_MIN_SIMILARITY = 0.05

ALL_VISIBILITIES = frozenset(
    {
        VISIBILITY_OPEN,
        VISIBILITY_CONTEXTUAL,
        VISIBILITY_RESTRICTED,
        VISIBILITY_INTERNAL,
    }
)

# Memory 类型
TYPE_FACT = "FACT"
TYPE_PREFERENCE = "PREFERENCE"
TYPE_EVENT = "EVENT"
TYPE_PLAN = "PLAN"
TYPE_RELATION = "RELATION"
TYPE_STYLE = "STYLE"
TYPE_GROUP_CONTEXT = "GROUP_CONTEXT"

ALL_MEMORY_TYPES = frozenset(
    {
        TYPE_FACT,
        TYPE_PREFERENCE,
        TYPE_EVENT,
        TYPE_PLAN,
        TYPE_RELATION,
        TYPE_STYLE,
        TYPE_GROUP_CONTEXT,
    }
)

# ── 第一张表：Mode → Usage 权限矩阵 ──────────────────────
# 值域：★★★★★=5（强烈允许）~ ★=1；0 表示“允许但不加分”。
# 不在表中的 usage 视为“谨慎/禁用”。
_MODE_USAGE_SCORE: dict[str, dict[str, int]] = {
    MODE_CASUAL_REPLY: {
        USAGE_PERSONALIZE: 5,
        USAGE_TOPIC_CONTINUE: 5,
        USAGE_RELATION_CONTEXT: 3,
        USAGE_TOPIC_START: 3,
        USAGE_EMOTIONAL_SUPPORT: 3,
        USAGE_HUMOR: 2,
    },
    MODE_ACTIVE_JOIN: {
        USAGE_TOPIC_START: 5,
        USAGE_TOPIC_CONTINUE: 5,
        USAGE_GROUP_CONTEXT: 5,
        USAGE_HUMOR: 4,
        USAGE_RELATION_CONTEXT: 3,
    },
    MODE_HUMOR: {
        USAGE_HUMOR: 5,
        USAGE_RELATION_CONTEXT: 5,
        USAGE_GROUP_CONTEXT: 5,
        USAGE_TOPIC_CONTINUE: 4,
    },
    MODE_TECH_HELP: {
        USAGE_ANSWER_CONTEXT: 5,
        USAGE_PERSONALIZE: 5,
        USAGE_TOPIC_CONTINUE: 3,
        USAGE_TOPIC_START: 3,
    },
    MODE_RECOMMEND: {
        USAGE_RECOMMEND: 5,
        USAGE_PERSONALIZE: 4,
        USAGE_ANSWER_CONTEXT: 3,
        USAGE_TOPIC_CONTINUE: 2,
    },
    MODE_EMOTIONAL: {
        USAGE_EMOTIONAL_SUPPORT: 5,
        USAGE_PERSONALIZE: 5,
        USAGE_RELATION_CONTEXT: 3,
        USAGE_TOPIC_CONTINUE: 3,
    },
    MODE_CONFLICT_AVOID: {
        USAGE_BOUNDARY_PROTECTION: 5,
        USAGE_CONFLICT_AVOID: 5,
        USAGE_RELATION_CONTEXT: 4,
    },
    MODE_GROUP_EVENT: {
        USAGE_GROUP_CONTEXT: 5,
        USAGE_TOPIC_CONTINUE: 4,
        USAGE_RELATION_CONTEXT: 4,
        USAGE_TOPIC_START: 3,
    },
}

# 各模式“禁止”的 usage：进入这些 usage 的记忆必须被挡在聊天素材之外
_MODE_FORBIDDEN_USAGE: dict[str, frozenset[str]] = {
    MODE_CASUAL_REPLY: frozenset({USAGE_BOUNDARY_PROTECTION, USAGE_CONFLICT_AVOID}),
    MODE_ACTIVE_JOIN: frozenset(
        {USAGE_BOUNDARY_PROTECTION, USAGE_CONFLICT_AVOID, USAGE_EMOTIONAL_SUPPORT}
    ),
    MODE_HUMOR: frozenset({USAGE_BOUNDARY_PROTECTION, USAGE_CONFLICT_AVOID}),
    MODE_TECH_HELP: frozenset({USAGE_HUMOR, USAGE_BOUNDARY_PROTECTION}),
    MODE_RECOMMEND: frozenset({USAGE_BOUNDARY_PROTECTION, USAGE_CONFLICT_AVOID}),
    MODE_EMOTIONAL: frozenset({USAGE_HUMOR, USAGE_RECOMMEND}),
    MODE_CONFLICT_AVOID: frozenset({USAGE_TOPIC_START, USAGE_HUMOR}),
    MODE_GROUP_EVENT: frozenset({USAGE_BOUNDARY_PROTECTION, USAGE_CONFLICT_AVOID}),
}

# ── 第二张表：Usage → Memory Type 兼容 ───────────────────
_USAGE_TYPE_MATRIX: dict[str, frozenset[str]] = {
    USAGE_TOPIC_START: frozenset({TYPE_GROUP_CONTEXT, TYPE_PREFERENCE, TYPE_EVENT}),
    USAGE_TOPIC_CONTINUE: frozenset({TYPE_EVENT, TYPE_GROUP_CONTEXT, TYPE_PLAN}),
    USAGE_ANSWER_CONTEXT: frozenset({TYPE_FACT, TYPE_EVENT, TYPE_PLAN}),
    USAGE_RECOMMEND: frozenset({TYPE_PREFERENCE, TYPE_FACT, TYPE_EVENT}),
    USAGE_PERSONALIZE: frozenset({TYPE_STYLE, TYPE_PREFERENCE}),
    USAGE_RELATION_CONTEXT: frozenset({TYPE_RELATION, TYPE_EVENT}),
    USAGE_HUMOR: frozenset({TYPE_RELATION, TYPE_GROUP_CONTEXT, TYPE_EVENT}),
    USAGE_EMOTIONAL_SUPPORT: frozenset({TYPE_EVENT, TYPE_RELATION, TYPE_STYLE}),
    USAGE_BOUNDARY_PROTECTION: frozenset({TYPE_PREFERENCE, TYPE_RELATION}),
    USAGE_CONFLICT_AVOID: frozenset({TYPE_RELATION, TYPE_EVENT, TYPE_PREFERENCE}),
}

# ── 第三张表：Visibility Access Matrix ───────────────────
# 值域：True=完全允许；None=条件允许（△）；False=禁止
_VISIBILITY_ACCESS: dict[str, dict[str, Optional[bool]]] = {
    MODE_CASUAL_REPLY: {
        VISIBILITY_OPEN: True,
        VISIBILITY_CONTEXTUAL: True,
        VISIBILITY_RESTRICTED: False,
        VISIBILITY_INTERNAL: False,
    },
    MODE_ACTIVE_JOIN: {
        VISIBILITY_OPEN: True,
        VISIBILITY_CONTEXTUAL: None,
        VISIBILITY_RESTRICTED: False,
        VISIBILITY_INTERNAL: False,
    },
    MODE_HUMOR: {
        VISIBILITY_OPEN: True,
        VISIBILITY_CONTEXTUAL: None,
        VISIBILITY_RESTRICTED: False,
        VISIBILITY_INTERNAL: False,
    },
    MODE_TECH_HELP: {
        VISIBILITY_OPEN: True,
        VISIBILITY_CONTEXTUAL: True,
        VISIBILITY_RESTRICTED: None,
        VISIBILITY_INTERNAL: False,
    },
    MODE_RECOMMEND: {
        VISIBILITY_OPEN: True,
        VISIBILITY_CONTEXTUAL: True,
        VISIBILITY_RESTRICTED: False,
        VISIBILITY_INTERNAL: False,
    },
    MODE_EMOTIONAL: {
        VISIBILITY_OPEN: True,
        VISIBILITY_CONTEXTUAL: True,
        VISIBILITY_RESTRICTED: None,
        VISIBILITY_INTERNAL: False,
    },
    MODE_GROUP_EVENT: {
        VISIBILITY_OPEN: True,
        VISIBILITY_CONTEXTUAL: True,
        VISIBILITY_RESTRICTED: False,
        VISIBILITY_INTERNAL: False,
    },
    MODE_CONFLICT_AVOID: {
        VISIBILITY_OPEN: True,
        VISIBILITY_CONTEXTUAL: True,
        VISIBILITY_RESTRICTED: True,
        VISIBILITY_INTERNAL: None,
    },
}

# 各模式的动态条数上限
_MODE_LIMITS: dict[str, int] = {
    MODE_CASUAL_REPLY: MEMORY_LIMIT_CASUAL_REPLY,
    MODE_ACTIVE_JOIN: MEMORY_LIMIT_ACTIVE_JOIN,
    MODE_HUMOR: MEMORY_LIMIT_HUMOR,
    MODE_TECH_HELP: MEMORY_LIMIT_TECH_HELP,
    MODE_RECOMMEND: MEMORY_LIMIT_RECOMMEND,
    MODE_EMOTIONAL: MEMORY_LIMIT_EMOTIONAL,
    MODE_CONFLICT_AVOID: MEMORY_LIMIT_CONFLICT_AVOID,
    MODE_GROUP_EVENT: MEMORY_LIMIT_GROUP_EVENT,
}

# ── Mode 检测（规则，不依赖 LLM，高频操作） ──────────────
_TECH_KEYWORDS = (
    "cuda", "gpu", "显卡", "显存", "rtx", "显卡驱动", "报错", "error", "代码",
    "python", "pip", "conda", "模型", "部署", "训练", "服务器", "linux", "windows",
    "安装", "配置", "为什么不能", "运行不了", "编译",
)
_RECOMMEND_KEYWORDS = (
    "推荐", "哪个好", "买什么", "选什么", "有什么好", "求推荐", "给我推荐",
    "选哪个", "怎么选", "值得买", "入手",
)
_EMOTIONAL_KEYWORDS = (
    "累", "难过", "压力", "心情", "不开心", "烦", "哭", "焦虑", "抑郁",
    "孤独", "撑不住", "好难", "难受",
)
_CONFLICT_KEYWORDS = (
    "冒犯", "生气", "别这样", "停下", "不喜欢", "讨厌", "边界", "别碰",
    "过分", "忍不了", "别开玩笑", "自重",
)
_GROUP_EVENT_KEYWORDS = (
    "活动", "组织", "比赛", "聚会", "开黑", "组队", "拼车", "团建", "报名",
    "下周", "约一下",
)
_HUMOR_KEYWORDS = (
    "梗", "玩笑", "哈哈", "笑死", "演", "戏精", "玩梗", "段子", "沙雕",
    "偶像剧",
)


def normalize_mode(mode: str) -> str:
    """把任意字符串规范成合法 Mode；非法值回退为 CASUAL_REPLY。"""
    m = (mode or "").strip().upper()
    return m if m in ALL_MODES else MODE_CASUAL_REPLY


def detect_mode(
    message: str,
    trigger: str = "reply",
    recent_topic: str = "",
) -> str:
    """根据当前消息与触发方式判断 Stella 行为模式（规则 + 小模型，高频）。

    ACTIVE_JOIN（主动插话）优先：主动发言的目的是“找一个自然切入口”，
    而不是回答问题，因此单独走最特殊的路径。
    """
    if trigger == "proactive":
        # 主动插话：若话题本身带玩梗意味，进入 HUMOR；否则 ACTIVE_JOIN
        if any(k in (recent_topic or "") for k in _HUMOR_KEYWORDS):
            return MODE_HUMOR
        return MODE_ACTIVE_JOIN

    text = (message or "").lower()

    def _hit(keywords: tuple[str, ...]) -> bool:
        return any(k in text for k in keywords)

    # 冲突规避优先级最高（安全优先）：宁可先保护边界
    if _hit(_CONFLICT_KEYWORDS):
        return MODE_CONFLICT_AVOID
    if _hit(_EMOTIONAL_KEYWORDS):
        return MODE_EMOTIONAL
    if _hit(_TECH_KEYWORDS):
        return MODE_TECH_HELP
    if _hit(_RECOMMEND_KEYWORDS):
        return MODE_RECOMMEND
    if _hit(_GROUP_EVENT_KEYWORDS):
        return MODE_GROUP_EVENT
    if _hit(_HUMOR_KEYWORDS):
        return MODE_HUMOR
    return MODE_CASUAL_REPLY


# ── 可见性 / Usage 解析 ─────────────────────────────────

def parse_visibility(value: Any) -> str:
    """把任意值规范成合法 Visibility；缺省/非法回退 OPEN。"""
    v = (value or "").strip().upper()
    return v if v in ALL_VISIBILITIES else VISIBILITY_OPEN


def parse_usage_tags(value: Any) -> list[str]:
    """把 usage_tags（JSON 数组或字符串数组）解析为合法的 usage 列表（去重保序）。"""
    if value is None:
        return []
    tags: list[str] = []
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            import json

            try:
                raw = json.loads(text)
            except (ValueError, TypeError):
                raw = [t.strip() for t in text.strip("[]").split(",") if t.strip()]
        else:
            raw = [t.strip() for t in text.split(",") if t.strip()]
    else:
        return []
    for t in raw:
        u = str(t).strip().upper()
        if u in ALL_USAGES and u not in tags:
            tags.append(u)
    return tags


# ── 三层过滤 ─────────────────────────────────────────────

def usage_allowed(mode: str, memory: dict[str, Any]) -> tuple[bool, int]:
    """判断一条记忆在指定模式下是否被 Usage 过滤放行。

    返回 (是否放行, 兼容加分)。放行条件：usage_tags 中至少一个 usage 属于该模式的
    允许列表，且不属于该模式的禁止列表；usage 与 Memory Type 必须兼容（第二张表）。
    """
    mode = normalize_mode(mode)
    tags = parse_usage_tags(memory.get("usage_tags"))
    if not tags:
        # 无 usage 标签的旧数据：按 OPEN 常识处理——只要类型兼容即可
        mem_type = (memory.get("type") or TYPE_FACT).strip().upper()
        for usages in _USAGE_TYPE_MATRIX.values():
            if mem_type in usages:
                return True, 1
        return True, 1
    forbidden = _MODE_FORBIDDEN_USAGE.get(mode, frozenset())
    mode_score_map = _MODE_USAGE_SCORE.get(mode, {})
    best = 0
    allowed_any = False
    mem_type = (memory.get("type") or TYPE_FACT).strip().upper()
    for tag in tags:
        if tag in forbidden:
            continue
        # usage 不属于该模式的允许列表 → 该记忆不适合当前行为模式（如 RECOMMEND 用在 TECH_HELP）
        if tag not in mode_score_map:
            continue
        allowed_any = True
        score = mode_score_map.get(tag, 0)
        # Usage 与 Memory Type 兼容性（第二张表是“主要来源”指引，不是硬排除）：
        # 类型兼容 → 全分；类型不兼容 → 降权一半，仍可能被调用（避免过度过滤）
        compat_types = _USAGE_TYPE_MATRIX.get(tag, frozenset())
        if compat_types and mem_type not in compat_types:
            score = int(score * 0.5)
        best = max(best, score)
    if not allowed_any:
        return False, 0
    return True, best


def visibility_access(mode: str, visibility: str) -> Optional[bool]:
    """查询某模式下某可见性的访问权：True 完全允许 / None 条件允许 / False 禁止。"""
    mode = normalize_mode(mode)
    vis = parse_visibility(visibility)
    return _VISIBILITY_ACCESS.get(mode, {}).get(vis, False)


def visibility_allowed(mode: str, memory: dict[str, Any]) -> bool:
    """Visibility 层过滤：RESTRICTED / INTERNAL 在大多数模式不可进入聊天素材。

    条件允许（None）在该层放行，但会由排序阶段的低分压制；真正需要
    高相关度 + 明确触发才可能被选中。
    """
    access = visibility_access(mode, (memory.get("visibility") or VISIBILITY_OPEN))
    return access is not False


# ── 排序（Memory Score） ────────────────────────────────

def _semantic_similarity(query: str, content: str) -> float:
    """轻量语义相似度：词集合 Jaccard + 关键词命中，作为向量检索的占位。"""
    if not query or not content:
        return 0.0
    q_words = set(_tokenize(query))
    c_words = set(_tokenize(content))
    if not q_words or not c_words:
        return 0.0
    jac = len(q_words & c_words) / len(q_words | c_words)
    hits = sum(1 for w in q_words if w in content)
    return min(1.0, jac + hits * 0.1)


def _tokenize(text: str) -> list[str]:
    """中文/英文词元化：中文按 2~4 字滑窗 + 单词。"""
    tokens: list[str] = []
    segments = re.findall(r"[\u4e00-\u9fff]{2,8}", (text or ""))
    for seg in segments:
        if len(seg) <= 4:
            tokens.append(seg)
        else:
            for size in (2, 3):
                for i in range(len(seg) - size + 1):
                    tokens.append(seg[i : i + size])
    tokens.extend(re.findall(r"[a-zA-Z0-9_]+", text.lower()))
    return tokens


def rank_memories(
    memories: list[dict[str, Any]],
    mode: str,
    query: str = "",
) -> list[dict[str, Any]]:
    """按 Policy 排序：Context Match → Usage Match → Semantic → Confidence → Importance。

    返回已排序、已去掉“禁止/不兼容/主题不匹配”项的记忆列表（不截断，由调用方按模式上限截断）。
    """
    mode = normalize_mode(mode)
    scored: list[tuple[float, dict[str, Any]]] = []
    for mem in memories:
        allowed, usage_score = usage_allowed(mode, mem)
        if not allowed:
            continue
        if not visibility_allowed(mode, mem):
            continue

        # Semantic Similarity
        semantic = _semantic_similarity(query, mem.get("content", ""))

        # CONTEXTUAL 需要主题匹配（Schema 4.4）：主题不匹配时即使分数高也不该被调用
        if parse_visibility(mem.get("visibility")) == VISIBILITY_CONTEXTUAL and semantic < CONTEXTUAL_MIN_SIMILARITY:
            continue

        # Context Match：当前 mode 是否“需要”这类记忆（取 usage 兼容分归一化）
        context_match = usage_score / 5.0
        # Usage Match：usage 与模式匹配度
        usage_match = usage_score / 5.0
        # Confidence / Importance
        confidence = _clamp_float(mem.get("confidence"), 0.0, 1.0, 0.7)
        importance = _clamp_float(mem.get("importance"), 0.0, 1.0, 0.5)

        score = (
            MEMORY_SCORE_W_CONTEXT * context_match
            + MEMORY_SCORE_W_USAGE * usage_match
            + MEMORY_SCORE_W_SEMANTIC * semantic
            + MEMORY_SCORE_W_CONFIDENCE * confidence
            + MEMORY_SCORE_W_IMPORTANCE * importance
        )
        mem = dict(mem)
        mem["_score"] = round(score, 4)
        scored.append((score, mem))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [mem for _, mem in scored]


def _clamp_float(value: Any, lo: float, hi: float, default: float) -> float:
    """安全转 float 并夹在 [lo, hi]；无法解析返回 default。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def mode_limit(mode: str) -> int:
    """返回指定模式的动态记忆条数上限。"""
    return _MODE_LIMITS.get(normalize_mode(mode), MEMORY_LIMIT_CASUAL_REPLY)


# ── 分离：聊天素材 vs 行为约束 ──────────────────────────
# RESTRICTED / INTERNAL / BOUNDARY 相关记忆禁止作为聊天素材，
# 只能进入 Behavior Guard（行为约束），二者绝不混合。

def _is_behavior_only(memory: dict[str, Any]) -> bool:
    """判断一条记忆是否“只进行为约束、不进聊天素材”。"""
    vis = parse_visibility(memory.get("visibility"))
    if vis in (VISIBILITY_RESTRICTED, VISIBILITY_INTERNAL):
        return True
    tags = parse_usage_tags(memory.get("usage_tags"))
    return USAGE_BOUNDARY_PROTECTION in tags or USAGE_CONFLICT_AVOID in tags


def split_behavior_constraints(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从（已按政策过滤后的）记忆中分离出行为约束，供 Behavior Guard 使用。"""
    return [m for m in memories if _is_behavior_only(m)]


# ── Policy Validator（Consolidation Gate 3） ─────────────
# 修正模型对记忆的错误分类：Usage 不合理时自动改为合理值，并同步 Visibility。

# 边界/冲突敏感内容的“行为化”关键词：命中即应归为 BOUNDARY / CONFLICT
_SENSITIVE_KEYWORDS = (
    "不喜欢", "讨厌", "反感", "拒绝", "不能", "不要", "禁止", "害怕",
    "不舒服", "难受", "边界", "冒犯", "反感", "生气", "别碰", "禁区",
    "禁止碰", "未经允许", "不同意",
)
# 被禁止“当成聊天话题”的 usage 组合
_FORBIDDEN_CHAT_USAGE = frozenset(
    {USAGE_TOPIC_START, USAGE_TOPIC_CONTINUE, USAGE_HUMOR}
)


def validate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """审核并修正一条记忆候选的分类（Gate 3）。

    规则：
    - 内容含“不喜欢/讨厌/边界…”等敏感词，但 usage 却是 TOPIC_START/HUMOR 等
      聊天用途 → 强制改为 BOUNDARY_PROTECTION + visibility=RESTRICTED；
    - 涉及边界但未给 behavior_rule → 补一条默认行为规则；
    - 缺失 usage_tags / visibility / confidence 时补齐合理默认值。
    """
    cand = dict(candidate)
    content = (cand.get("content") or "").strip()
    tags = parse_usage_tags(cand.get("usage_tags"))
    vis = parse_visibility(cand.get("visibility"))

    # 敏感内容被误当作“聊天素材”
    if content and any(k in content for k in _SENSITIVE_KEYWORDS):
        if any(t in _FORBIDDEN_CHAT_USAGE for t in tags) or vis in (
            VISIBILITY_OPEN,
            VISIBILITY_CONTEXTUAL,
        ):
            tags = [USAGE_BOUNDARY_PROTECTION]
            vis = VISIBILITY_RESTRICTED
            cand["behavior_rule"] = (
                cand.get("behavior_rule")
                or f"避免主动针对相关用户进行涉及「{_short(content)}」的互动。"
            )

    # 行为约束缺失默认行为规则
    if (
        vis == VISIBILITY_RESTRICTED
        or USAGE_BOUNDARY_PROTECTION in tags
        or USAGE_CONFLICT_AVOID in tags
    ) and not cand.get("behavior_rule"):
        cand["behavior_rule"] = f"避免主动针对相关用户进行涉及「{_short(content)}」的互动。"

    cand["usage_tags"] = tags
    cand["visibility"] = vis

    # 补齐置信度 / 重要度默认值
    if cand.get("confidence") is None:
        cand["confidence"] = 0.7
    if cand.get("importance") is None:
        cand["importance"] = 0.5
    return cand


def _short(content: str, limit: int = 20) -> str:
    """截取内容前若干字作为默认行为规则里的摘要。"""
    text = (content or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit] + "…"


# ── 过滤对话中重复人格描述（Selection Rule 2） ───────────
_PERSONA_WORDS = frozenset(
    {
        "随和", "温柔", "友好", "热心", "开朗", "内向", "幽默", "敏感",
        "细心", "稳重", "活泼", "安静", "乐观", "悲观", "善良", "大方",
        "急躁", "理性", "感性", "爱笑", "慢性子", "急性子",
    }
)


def has_persona_overlap(content: str) -> bool:
    """判断记忆内容是否为“重复的人格描述”（Selection Rule 2）。"""
    return any(w in (content or "") for w in _PERSONA_WORDS)


def stable_profile_facts(traits: str) -> list[str]:
    """从画像特征里筛出「稳定事实」，过滤人格判断/心理状态/价值判断。

    对应 Memory Policy 的 User Profile 治理：user_profiles 只保存稳定画像
    （语言偏好、回答长度偏好、技术水平、可观察行为），人格/心理/价值判断
    应转为低置信 Internal Memory，而不是当作事实。
    """
    if not traits:
        return []
    parts = [s.strip() for s in re.split(r"[,，;；、\n]+", traits) if s.strip()]
    kept: list[str] = []
    for part in parts:
        if any(w in part for w in _PERSONA_WORDS):
            continue
        # 心理状态/价值判断关键词 → 丢弃
        if any(k in part for k in ("心理", "状态", "压力大", "孤独", "抑郁", "焦虑")):
            continue
        # 仅保留“可观察行为/客观特征”型描述（含动词或名词），长度限制
        if len(part) >= 3 and (any(w in part for w in ("聊", "玩", "喜欢", "用", "研究", "学", "做")) or re.search(r"[\u4e00-\u9fff]", part)):
            kept.append(part)
    return kept[:5]
