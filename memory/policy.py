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

import json
import math
import re
import time
from datetime import datetime
from typing import Any

from config import (
    MEMORY_EMBEDDING_CONTEXTUAL_MIN,
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
    MEMORY_SCORE_W_RECENCY,
    MEMORY_SCORE_W_SEMANTIC,
    MEMORY_SCORE_W_USAGE,
    MODE_DETECT_MIN_SCORE,
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
    USAGE_TOPIC_CONTINUE: frozenset({TYPE_EVENT, TYPE_GROUP_CONTEXT, TYPE_PLAN, TYPE_PREFERENCE}),
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
_VISIBILITY_ACCESS: dict[str, dict[str, bool | None]] = {
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
# 词表里的词分两种：强势的“主词”（技术/推荐/冲突词，日常误命中率低）与
# 弱势的“噪音词”（哈哈/笑死/累/烦 等日常高频，误命中率高）。detect_mode
# 用“命中数 × 权重 × 长词加成”打分而非短路链，避免“谁先写谁赢”。
# 注：单个字的日常词（如“累”）权重被刻意压低，仍可能误判，这是预期取舍。
_TECH_KEYWORDS = (
    "cuda", "gpu", "显卡", "显存", "rtx", "显卡驱动", "报错", "error", "代码",
    "python", "pip", "conda", "模型", "部署", "训练", "服务器", "linux", "windows",
    "安装", "配置", "为什么不能", "运行不了", "编译",
)
_RECOMMEND_KEYWORDS = (
    "推荐", "哪个好", "买什么", "选什么", "求推荐", "给我推荐",
    "选哪个", "怎么选", "值得买", "入手",
)
# 情绪关键词分三档：强信号（明确痛苦/求助）> 中信号（情绪状态）> 弱信号（日常高频，
# “累/烦/哭”单独出现十有八九只是随口说说）。detect_mode 按档位给权重，
# 避免“今天好累啊”这类日常吐槽被误判成 EMOTIONAL 而丢用户画像记忆。
_EMOTIONAL_KEYWORDS_STRONG = (
    "焦虑", "抑郁", "撑不住", "失眠", "崩溃", "绝望", "想哭", "大哭", "哭不出来",
    "委屈", "自残", "想死", "没意思",
)
_EMOTIONAL_KEYWORDS_NORMAL = (
    "压力", "心情", "难过", "不开心", "难受", "孤独", "好难", "情绪",
)
_EMOTIONAL_KEYWORDS_WEAK = ("累", "烦", "哭", "心累", "好累")
# 冲突/边界检测：只保留强信号。“不喜欢/讨厌”这类日常吐槽（“这个配色我不喜欢”）
# 会误开 CONFLICT_AVOID 的 RESTRICTED 闸门，已移出；它们仍然属于
# consolidator._SENSITIVE_KEYWORDS，用于判断**记忆内容**而不是当前 mode。
# 补上“碰我/摸我”这类身体边界短句，保住“别开这种玩笑…别碰我”这类真冲突。
_CONFLICT_KEYWORDS = (
    "冒犯", "生气", "别这样", "停下", "讨厌", "边界", "别碰", "碰我",
    "摸我", "过分", "忍不了", "别开玩笑", "自重",
)
_GROUP_EVENT_KEYWORDS = (
    "活动", "组织", "比赛", "聚会", "开黑", "组队", "拼车", "团建", "报名",
    "下周", "约一下",
)
# “哈哈/笑死”从模式信号里删除：它们是群聊最高频的字符串，命中即把 mode 推入
# HUMOR，而 HUMOR 的 usage 表不含 PERSONALIZE，会让全部用户画像记忆失效。
_HUMOR_KEYWORDS = (
    "梗", "玩笑", "演", "戏精", "玩梗", "段子", "沙雕",
    "偶像剧",
)

# 各模式的信号关键词与权重（detect_mode 打分用）：
#   冲突规避权重最高（安全优先）；技术/推荐词特异性强，误判率低；
#   玩梗词噪音最大。
# EMOTIONAL 特殊：关键词分三档（强/中/弱），强档最重、弱档最轻。混档消息
# （“又累又烦，压力好大”）以档位分权重再加成，不会因多命中几个弱词而虚高。
_MODE_SIGNALS: dict[str, tuple[tuple[str, ...], float]] = {
    MODE_CONFLICT_AVOID: (_CONFLICT_KEYWORDS, 1.5),
    MODE_TECH_HELP: (_TECH_KEYWORDS, 1.2),
    MODE_RECOMMEND: (_RECOMMEND_KEYWORDS, 1.2),
    MODE_GROUP_EVENT: (_GROUP_EVENT_KEYWORDS, 1.0),
    MODE_EMOTIONAL: (_EMOTIONAL_KEYWORDS_STRONG, 1.2),
    MODE_HUMOR: (_HUMOR_KEYWORDS, 0.5),
}

# EMOTIONAL 中/弱档词各自加成的权重（强档已并入 _MODE_SIGNALS 的 1.2）
_EMOTIONAL_TIER_WEIGHTS: tuple[tuple[tuple[str, ...], float], ...] = (
    (_EMOTIONAL_KEYWORDS_NORMAL, 0.8),
    (_EMOTIONAL_KEYWORDS_WEAK, 0.4),
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

    采用“打分制”而非短路 if：每个模式的关键词带权重，命中后按
    ``命中数 × 权重 × (1 + 最长命中词长 / 10)`` 计分，得分超过
    ``MODE_DETECT_MIN_SCORE`` 且最高者胜出；都不够则回退 CASUAL_REPLY。
    相比短路链，长词/强信号词能自然压过高频弱信号（如“哈哈/累”），
    阈值进 config 可调、可 benchmark。

    ACTIVE_JOIN（主动插话）优先：主动发言的目的是“找一个自然切入口”，
    而不是回答问题，因此单独走最特殊的路径。
    """
    if trigger == "proactive":
        # 主动插话：若话题本身带玩梗意味，进入 HUMOR；否则 ACTIVE_JOIN
        if any(k in (recent_topic or "") for k in _HUMOR_KEYWORDS):
            return MODE_HUMOR
        return MODE_ACTIVE_JOIN

    text = (message or "").lower()
    best_mode, best_score = MODE_CASUAL_REPLY, MODE_DETECT_MIN_SCORE
    for mode, (keywords, weight) in _MODE_SIGNALS.items():
        hits = [k for k in keywords if k in text]
        if not hits:
            continue
        # 长关键词更特异（“编译”比“累”可靠得多），命中越多信号越强
        score = len(hits) * weight * (1 + max(len(k) for k in hits) / 10)
        if mode == MODE_EMOTIONAL:
            # 情绪词的中/弱档按档位加权：累命中次数再多也不如一个“撑不住”可靠
            for tier, tier_weight in _EMOTIONAL_TIER_WEIGHTS:
                tier_hits = [k for k in tier if k in text]
                if tier_hits:
                    score += len(tier_hits) * tier_weight * (1 + max(len(k) for k in tier_hits) / 10)
        if score > best_score:
            best_mode, best_score = mode, score
    return best_mode


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


def visibility_access(mode: str, visibility: str) -> bool | None:
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


def _context_match(mem: dict[str, Any], usage_score: int, query: str = "") -> float:
    """Context Match：当前查询/场景是否需要这条记忆。

    优先读 ``trigger_data.topics/keywords``：命中 query 视为「触发即该用」→ 满分 1.0。
    Trigger 是比 Memory Type 更直接的当前意图信号（M03「不喜欢恐怖题材」标注
    topics=["game"] 后，在「有什么游戏推荐吗」下即为满分，替代词面 Jaccard 的局限）。
    无触发命中时按 usage 契合度折算（usage_score/5），使 ctx 分量能随记忆与当前
    场景的契合度拉开差距，而不是靠 Memory Type 得出一批近似常数。
    """
    if query and _trigger_topic_match(query, mem):
        return 1.0
    return min(1.0, usage_score / 5.0)


def _parse_ts(value: Any) -> float | None:
    """把 last_accessed_at / created_at 解析为 epoch 秒；空值或解析失败返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    formats = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).timestamp()
        except (ValueError, TypeError):
            continue
    try:
        return datetime.fromisoformat(text).timestamp()
    except (ValueError, TypeError):
        return None


def _mem_timestamp(mem: dict[str, Any]) -> float:
    """取一条记忆的时间戳（last_accessed_at 优先，其次 created_at / updated_at）。
    都没有则按“刚刚”处理（旧数据不因缺时间戳而被当成远古记忆）。"""
    for key in ("last_accessed_at", "created_at", "updated_at"):
        epoch = _parse_ts(mem.get(key))
        if epoch is not None:
            return epoch
    return time.time()


def _reference_timestamp(memories: list[dict[str, Any]]) -> float:
    """排序参考时间：候选池最新一条记忆的访问时间（poll-anchored recency）。
    以此代替“系统当前时间”作为年龄参照，避免 benchmark/快照数据的绝对时间
    漂移：最新记忆 age=0、天然 decay=1.0，旧的按相对年龄衰减。"""
    newest = max((_mem_timestamp(m) for m in memories), default=time.time())
    # 参照不超前于真实当前时间：将来数据（时钟漂移）按 0 年龄处理
    return min(newest, time.time())


def _recency_factor(
    reference: float,
    age_days: float,
    mem_type: str = "",
) -> float:
    """Recency Decay：``exp(-Δdays / τ)``，τ 取 30 天。

    新记忆 recency≈1（贡献满格），一个月后≈0.37，三个月后≈0.05，近乎归零。
    相比半衰期式衰减，指数衰减对新旧差异更敏感，能显著拉开“新压旧”，
    且不区分类型、参数单一（τ=30）。衰减贡献用 ``MEMORY_SCORE_W_RECENCY`` 加权。
    """
    _ = mem_type  # 保留入参以兼容旧调用；衰减不区分类型
    tau_days = 30.0
    return max(0.0, min(1.0, math.exp(-max(0.0, age_days) / tau_days)))


def _rank_score(
    mem: dict[str, Any],
    usage_score: int,
    semantic: float,
    recency: float,
    context_match: float,
    w_ctx: float,
    w_usg: float,
    w_sem: float,
    w_rec: float,
    w_conf: float,
    w_imp: float,
) -> tuple[float, dict[str, float]]:
    """计算单条记忆的排序分（Context Match → Usage → Semantic → Recency → Conf/Imp）。

    六维相互独立（Context 按触发/usage、Usage 按 usage、Semantic 按词面、Recency 按时效），
    避免同一信号被两个权重重复计算。权重由调用方注入：rule-only 时丢弃不可靠的词面
    语义维并把剩余权重重归一化（见 ``rank_memories``）。返回 ``(总分, 各维度加权贡献)``，
    后者供 ``_score_parts`` 诊断用——否则每次调权重都是盲调。
    """
    # Usage Match：usage 与该模式的匹配度（归一化到 0~1）
    usage_match = usage_score / 5.0
    # Confidence / Importance
    confidence = _clamp_float(mem.get("confidence"), 0.0, 1.0, 0.7)
    importance = _clamp_float(mem.get("importance"), 0.0, 1.0, 0.5)

    parts = {
        "ctx": w_ctx * context_match,
        "usg": w_usg * usage_match,
        "sem": w_sem * semantic,
        "rec": w_rec * recency,
        "conf": w_conf * confidence,
        "imp": w_imp * importance,
    }
    return sum(parts.values()), parts


def _trigger_topic_match(query: str, memory: dict[str, Any]) -> bool:
    """trigger_data 主题匹配（Schema 4.5, 4.6）：记忆声明了触发条件且与查询命中。

    两种命中方式：
    1. ``keywords`` 直接出现在查询词面里（“摸头”出现在消息中）；
    2. ``topics`` 是语义主题（game / boundary / tech…），经同义词表映射到查询词面
       （M03「不喜欢恐怖题材」标 topics=["game"]，查询“有什么游戏推荐吗”→“游戏”）。
    用于给 CONTEXTUAL 记忆开“主题匹配豁免”的口子，替代词面 Jaccard 的局限。
    """
    if not query:
        return False
    raw = memory.get("trigger_data")
    if raw is None or raw == "":
        return False
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return False
    elif isinstance(raw, dict):
        data = raw
    else:
        return False
    q = (query or "").lower()
    for kw in (data.get("keywords") or []):
        if kw and str(kw).lower() in q:
            return True
    for topic in (data.get("topics") or []):
        for synonym in _TOPIC_SYNONYMS.get(str(topic).lower(), ()):
            if synonym in q:
                return True
    return False


# trigger_data.topics → 查询命中词（Schema 4.5 的主题是语义标签，词面比对不上，
# 这里给常见主题一张映射表。可在配置扩展；缺省 topics 无表则退化为字面匹配失败）
_TOPIC_SYNONYMS: dict[str, tuple[str, ...]] = {
    "game": ("游戏", "game", "玩", "开黑", "联机", "steam"),
    "tech": ("代码", "报错", "显存", "显卡", "cuda", "gpu", "部署", "模型",
             "python", "pip", "linux", "服务器", "训练", "编译", "运行"),
    "emotion": ("累", "压力", "难过", "心情", "焦虑", "撑不住", "抑郁", "哭", "烦"),
    "boundary": ("碰", "摸", "别碰", "边界", "冒犯", "玩笑", "要求"),
    "event": ("活动", "聚会", "比赛", "报名", "开黑", "团建", "下周", "组织"),
    "food": ("吃", "榴莲", "辣", "菜", "饭", "奶茶", "咖啡"),
    "group": ("群", "群友", "大家", "群里"),
}


def rank_memories(
    memories: list[dict[str, Any]],
    mode: str,
    query: str = "",
    semantic_scores: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """按 Policy 排序：Context Match → Usage Match → Semantic → Confidence → Importance。

    返回已排序、已去掉“禁止/不兼容/主题不匹配”项的记忆列表（不截断，由调用方按模式上限截断）。

    ``semantic_scores`` 可注入外部语义分（如 embedding 余弦相似度，按记忆 id 索引）；
    不传或该 id 缺失时退化为规则版 ``_semantic_similarity``。policy 本身保持纯逻辑。

    rule-only（``semantic_scores is None``）时词面语义不可靠：丢弃 sem 维并把剩余
    权重按比例归一化到总和 1.0，避免 ``W_SEMANTIC`` 变大后降级路径的排序质量断崖。
    """
    mode = normalize_mode(mode)
    if semantic_scores is None:
        # rule-only：跳过词面语义维，剩余权重归一化（scale>1 是预期的，保证降级
        # 路径的排序与 embedding 路径可比，而不是 1/3 分数作废）
        base = (
            MEMORY_SCORE_W_CONTEXT
            + MEMORY_SCORE_W_USAGE
            + MEMORY_SCORE_W_RECENCY
            + MEMORY_SCORE_W_CONFIDENCE
            + MEMORY_SCORE_W_IMPORTANCE
        )
        scale = 1.0 / base
        w_ctx, w_usg, w_sem, w_rec, w_conf, w_imp = (
            MEMORY_SCORE_W_CONTEXT * scale,
            MEMORY_SCORE_W_USAGE * scale,
            0.0,
            MEMORY_SCORE_W_RECENCY * scale,
            MEMORY_SCORE_W_CONFIDENCE * scale,
            MEMORY_SCORE_W_IMPORTANCE * scale,
        )
    else:
        w_ctx, w_usg, w_sem, w_rec, w_conf, w_imp = (
            MEMORY_SCORE_W_CONTEXT,
            MEMORY_SCORE_W_USAGE,
            MEMORY_SCORE_W_SEMANTIC,
            MEMORY_SCORE_W_RECENCY,
            MEMORY_SCORE_W_CONFIDENCE,
            MEMORY_SCORE_W_IMPORTANCE,
        )

    scored: list[tuple[float, dict[str, Any]]] = []
    reference = _reference_timestamp(memories)
    for mem in memories:
        allowed, usage_score = usage_allowed(mode, mem)
        if not allowed:
            continue
        if not visibility_allowed(mode, mem):
            continue

        # Semantic Similarity（外部注入优先，如 embedding 余弦分；否则规则版占位）
        mem_id = mem.get("id")
        embedding_path = semantic_scores is not None
        if embedding_path and mem_id in semantic_scores:
            semantic = max(0.0, min(1.0, float(semantic_scores[mem_id])))
        else:
            semantic = _semantic_similarity(query, mem.get("content", ""))

        # RECENCY：记忆存活度（指数衰减，τ=30 天），新记忆天然占优
        age_days = max(0.0, reference - _mem_timestamp(mem)) / 86400.0
        recency = _recency_factor(reference, age_days, (mem.get("type") or TYPE_FACT).strip().upper())

        # CONTEXTUAL 需要主题匹配（Schema 4.4）：主题不匹配时即使分数高也不该被调用。
        # 两个豁免：usage 强命中（score==5，说明这条记忆就是为当前场景准备的）或
        # trigger_data 主题命中时，不再用词面相似度二次否决（比如「不喜欢恐怖题材」
        # 在“有什么游戏推荐吗”下使用其对应 RECOMMEND usage，语义却≈0）。
        # 阈值分路：embedding 路径用余弦阈值 MEMORY_EMBEDDING_CONTEXTUAL_MIN（0.25），
        # rule-only 路径用词面阈值 CONTEXTUAL_MIN_SIMILARITY（0.05），不共用。
        contextual_min = MEMORY_EMBEDDING_CONTEXTUAL_MIN if embedding_path else CONTEXTUAL_MIN_SIMILARITY
        if (
            parse_visibility(mem.get("visibility")) == VISIBILITY_CONTEXTUAL
            and usage_score < 5
            and not _trigger_topic_match(query, mem)
            and semantic < contextual_min
        ):
            continue

        score, parts = _rank_score(
            mem, usage_score, semantic, recency,
            _context_match(mem, usage_score, query),
            w_ctx, w_usg, w_sem, w_rec, w_conf, w_imp,
        )
        mem = dict(mem)
        mem["_score"] = round(score, 4)
        mem["_score_parts"] = {k: round(v, 3) for k, v in parts.items()}
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
    if (
        content
        and any(k in content for k in _SENSITIVE_KEYWORDS)
        and (
            any(t in _FORBIDDEN_CHAT_USAGE for t in tags)
            or vis in (VISIBILITY_OPEN, VISIBILITY_CONTEXTUAL)
        )
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
