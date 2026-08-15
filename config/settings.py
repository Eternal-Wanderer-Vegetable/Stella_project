# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""集中配置模块。

本模块是 Stella 机器人的“配置中枢”：通过读取项目根目录下的 .env（及按
ENVIRONMENT 区分的 .env.dev / .env.prod）环境变量，将全部运行时参数集中
导出为模块级常量，供 memory/、core/ 等业务模块 import 使用。业务代码不改动
此文件即可调整参数。环境变量解析统一走 _env / _env_int / _env_float 三个
私有助手，保证类型安全并带默认值兜底。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ============================================================
# Stella Project — 集中配置
# 修改此文件即可调整所有运行时参数，无需改动业务代码。
# ============================================================

# ---------- 项目路径（自动校准） ----------
# 从本文件所在目录向上逐级寻找包含 core/ 子目录的目录，即为项目根目录。
# 这样无论包被安装在何处（源码目录/打包后/相对导入），都能准确定位根路径。
_CURRENT_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _CURRENT_FILE.parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT:
    if (_PROJECT_ROOT / "core").is_dir():
        break
    _PROJECT_ROOT = _PROJECT_ROOT.parent
PROJECT_ROOT = _PROJECT_ROOT

# 加载 .env 文件（项目根目录，不覆盖已有环境变量）
load_dotenv(PROJECT_ROOT / ".env", override=False)

# 根据 ENVIRONMENT 加载环境覆盖文件（覆盖 .env 中的值）
_ENVIRONMENT = os.getenv("ENVIRONMENT", "").strip().lower()
if _ENVIRONMENT in ("dev", "development"):
    load_dotenv(PROJECT_ROOT / ".env.dev", override=True)
elif _ENVIRONMENT in ("prod", "production"):
    load_dotenv(PROJECT_ROOT / ".env.prod", override=True)


def _env(key: str, default: str = "") -> str:
    """读取字符串环境变量并按优先级返回。

    参数:
        key: 环境变量名。
        default: 变量为空或未设置时返回的默认值。
    返回:
        key 对应的环境变量值；未设置时返回 default。
    """
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    """安全读取 int 环境变量，解析失败时返回默认值（避免直接 int() 抛异常）。

    参数:
        key: 环境变量名；
        default: 空值或解析失败时使用的整数默认值。
    返回:
        解析成功返回整数；否则返回 default 并告警日志。
    """
    raw = os.getenv(key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        from nonebot import logger
        logger.warning(f"⚠️ 配置项 {key}={raw!r} 不是有效整数，使用默认值 {default}")
        return default


def _env_float(key: str, default: float = 0.0) -> float:
    """安全读取 float 环境变量，解析失败时返回默认值。

    参数:
        key: 环境变量名；
        default: 空值或解析失败时使用的浮点默认值。
    返回:
        浮点环境变量值；解析失败时返回 default 并告警日志。
    """
    raw = os.getenv(key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        from nonebot import logger
        logger.warning(f"⚠️ 配置项 {key}={raw!r} 不是有效浮点数，使用默认值 {default}")
        return default


def _env_path(key: str, default: Path) -> Path:
    """读取路径类环境变量，解析为 Path；未设置时返回 default。

    路径统一解析为绝对路径，避免不同工作目录下相对路径漂移。
    """
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    return Path(raw).expanduser().resolve()

# ---------- 项目路径（自动校准） ----------
# 与上文同样地向上定位项目根目录（以存在 core/ 目录为判据），
# 确保后续 SYSTEM.md、数据库等相对路径都建立在根目录之上。
_CURRENT_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _CURRENT_FILE.parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT:
    if (_PROJECT_ROOT / "core").is_dir():
        break
    _PROJECT_ROOT = _PROJECT_ROOT.parent
PROJECT_ROOT = _PROJECT_ROOT

# ---------- 目录与文件路径（可通过 .env 覆盖） ----------
# 各路径均锚定 PROJECT_ROOT，保证在不同工作目录下启动都能正确定位文件；
# 如需自定义，在 .env 里设置同名环境变量（绝对路径）。
SYSTEM_PROMPT_PATH = _env_path("SYSTEM_PROMPT_PATH", PROJECT_ROOT / "memory" / "SYSTEM.md")
DB_PATH = _env_path("DB_PATH", PROJECT_ROOT / "memory" / "agent_memory.db")
THOUGHT_LOG_PATH = _env_path("THOUGHT_LOG_PATH", PROJECT_ROOT / "stella_thought_logs.md")
EXTENSIONS_DIR = _env_path("EXTENSIONS_DIR", PROJECT_ROOT / "extensions")

# ---------- QQ 群聊 ----------
# 逗号分隔的群号字符串转为 int 集合；过滤空片段避免尾逗号导致 int('') 报错。
# 群号从 .env 的 ALLOWED_GROUPS 读取（用英文逗号分隔多个群号）。
ALLOWED_GROUPS = {int(x) for x in _env("ALLOWED_GROUPS", "").split(",") if x.strip()}

# ---------- 上下文 ----------
# ⚠️ 废弃（DEPRECATED）：RECENT_MESSAGE_LIMIT 已被 RECENT_TAIL_LIMIT 取代——
# build_context 现在总是附加最近原始消息尾巴，recent_exchanges 仅在无尾巴时兜底，
# RECENT_MESSAGE_LIMIT 不再被读取。保留定义仅供既有 .env 兼容（无效但不报错）。
RECENT_MESSAGE_LIMIT = _env_int("RECENT_MESSAGE_LIMIT", 3)

# 每次回复时附加的最近原始消息条数（含 Bot 自己的发言）。
# 短期摘要由整合器产出，按设计滞后（需累积 CONSOLIDATION_TRIGGER_NEW_MESSAGES 条
# 才更新），因此最近几轮对话必须以原始消息补足——否则 Bot 看不到自己刚说过什么，
# 用户的「手机」「对」这类简短回应会被接到上一个话题上去。
# 太小：活跃群里刷屏会把 Bot 自己的提问挤出窗口，简短回应（「手机」「对」）
#       重新被接到上一个话题（2026-08-13 bug 的成因）；
# 太大：无关历史会干扰模型，且每次回复的 prompt 变长。
# 12 是起点，需按真实群的刷屏速度调整。
RECENT_TAIL_LIMIT = _env_int("RECENT_TAIL_LIMIT", 12)

# ---------- 长期记忆引用策略 ----------
# 主动发言时引用的长期记忆条数（按 last_accessed_at 倒序取最近 N 条）
PROACTIVE_LONG_TERM_LIMIT = _env_int("PROACTIVE_LONG_TERM_LIMIT", 10)
# @-回复时引用的该用户近期长期记忆条数
REPLY_LONG_TERM_LIMIT = _env_int("REPLY_LONG_TERM_LIMIT", 3)
# @-回复时是否启用旧记忆话题匹配（对非该用户的旧记忆做关键词相关度筛选）
LONG_TERM_RELEVANCE_ENABLED = _env("LONG_TERM_RELEVANCE_ENABLED", "true").lower() in ("true", "1", "yes")
# 从用户消息中提取的关键词数量（用于匹配旧记忆摘要）
LONG_TERM_RELEVANCE_KEYWORDS = _env_int("LONG_TERM_RELEVANCE_KEYWORDS", 5)
# 相关记忆检索的候选数量上限
LONG_TERM_RELEVANCE_CANDIDATE_LIMIT = _env_int("LONG_TERM_RELEVANCE_CANDIDATE_LIMIT", 20)
# 相关记忆评分权重：关键词重叠、最近访问、重要性、置信度、用户相关性
LONG_TERM_RELEVANCE_WEIGHT_KEYWORDS = _env_float("LONG_TERM_RELEVANCE_WEIGHT_KEYWORDS", 2.0)
LONG_TERM_RELEVANCE_WEIGHT_RECENCY = _env_float("LONG_TERM_RELEVANCE_WEIGHT_RECENCY", 1.0)
LONG_TERM_RELEVANCE_WEIGHT_IMPORTANCE = _env_float("LONG_TERM_RELEVANCE_WEIGHT_IMPORTANCE", 1.2)
LONG_TERM_RELEVANCE_WEIGHT_CONFIDENCE = _env_float("LONG_TERM_RELEVANCE_WEIGHT_CONFIDENCE", 0.8)
LONG_TERM_RELEVANCE_WEIGHT_USER_RELEVANCE = _env_float("LONG_TERM_RELEVANCE_WEIGHT_USER_RELEVANCE", 0.6)

# ---------- RAG（检索增强生成）配置 ----------
# 是否启用基于 SQLite 的 RAG 检索
RAG_ENABLED = _env("RAG_ENABLED", "true").lower() in ("true", "1", "yes")
# 每次检索时返回的相关记忆上限
RAG_TOP_K = _env_int("RAG_TOP_K", 5)
# 是否启用 SQLite FTS5 作为记忆检索索引
RAG_SQLITE_FTS_ENABLED = _env("RAG_SQLITE_FTS_ENABLED", "true").lower() in ("true", "1", "yes")

# ---------- 记忆候选处理策略 ----------
# ⚠️ 废弃（DEPRECATED）：MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE / _MIN_IMPORTANCE
# 已被 Gate 1 三档判定取代（见下：MEMORY_CONFIRM_HIGH_CONFIDENCE /
# MEMORY_OBSERVE_LOW_CONFIDENCE / MEMORY_PROMOTE_*）。这两个键**保留定义仅供 .env
# 兼容**——已有 .env 里配过它们的人不该静默失去配置项，但代码不再读取、不产生任何效果。
MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE = _env_float("MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE", 0.5)
MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE = _env_float("MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE", 0.5)

# ---------- 候选强化（交叉验证） ----------
# 同一事实被再次独立观察到时的置信度增益。这是「暂存 → 交叉验证 → 逐步强化」
# 的核心：单次陈述不足以晋升，复现才是证据。取 0.12 使 0.5 起步的候选
# 约 2 次复现后跨过 MEMORY_OBSERVE_LOW_CONFIDENCE(0.6)。
MEMORY_CANDIDATE_REOCCURRENCE_BONUS = _env_float("MEMORY_CANDIDATE_REOCCURRENCE_BONUS", 0.12)
# 候选在 OBSERVING 停留的最长天数，超期未获新证据即标 REJECTED（不删除，保留供审计）
MEMORY_CANDIDATE_MAX_OBSERVING_DAYS = _env_int("MEMORY_CANDIDATE_MAX_OBSERVING_DAYS", 30)
# evidence 字段累积上限（字符）。多次复现会不断追加证据，需防止无界增长
MEMORY_CANDIDATE_EVIDENCE_MAX_CHARS = _env_int("MEMORY_CANDIDATE_EVIDENCE_MAX_CHARS", 800)

# ---------- 晋升门槛（Gate 1 三档分级） ----------
# 晋升所需的最低独立观察次数（纯 PASSIVE 来源）。被动摄入的群聊信息密度低，
# 单次陈述不足以构成长期记忆依据；复现才是证据。
MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE = _env_int("MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE", 2)
# AT_MENTION（用户直接对 Bot 说）是高密度、高意图证据，单次即可晋升。
# 关闭后 AT_MENTION 与 PASSIVE 同等对待（仍需复现）。
MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT = _env("MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT", "true").lower() in ("true", "1", "yes")
# 晋升所需的最低重要度：importance 由 LLM 自评、可靠性最低，
# 因此只作为「淘汰过于琐碎的信息」的下限，不单独构成晋升依据。
MEMORY_PROMOTE_MIN_IMPORTANCE = _env_float("MEMORY_PROMOTE_MIN_IMPORTANCE", 0.3)

# ---------- 每用户记忆配额（宁缺毋滥的硬约束） ----------
# 是否真正执行淘汰。**默认关闭**：先以 dry-run 观察它想淘汰什么，
# 确认合理后再打开。打开后会把超额记忆置 archived（不删除，但退出检索）。
MEMORY_QUOTA_ENFORCE = _env("MEMORY_QUOTA_ENFORCE", "false").lower() in ("true", "1", "yes")
# 单用户在单群的 active 记忆上限。到顶后新记忆必须挤掉现存最弱的一条。
# 依据：一个用户真正有价值的稳定事实数量有限；上限封顶使呈现层总量可控，
# 天然对抗捕获层放宽带来的膨胀。
MEMORY_USER_QUOTA = _env_int("MEMORY_USER_QUOTA", 25)
# 配额淘汰的排序权重（得分最低者先被挤掉）。三项含义：
# importance=这条信息本身多重要；confirmation=被反复确认过几次（最硬的证据）；
# recency=最近是否还被用到（久未触达的记忆价值衰减）。
MEMORY_QUOTA_W_IMPORTANCE = _env_float("MEMORY_QUOTA_W_IMPORTANCE", 0.4)
MEMORY_QUOTA_W_CONFIRMATION = _env_float("MEMORY_QUOTA_W_CONFIRMATION", 0.3)
MEMORY_QUOTA_W_RECENCY = _env_float("MEMORY_QUOTA_W_RECENCY", 0.3)
# confirmation_count 的归一化上限：达到该次数即视为「充分确认」（满分）
MEMORY_QUOTA_CONFIRMATION_CAP = _env_int("MEMORY_QUOTA_CONFIRMATION_CAP", 3)

# ---------- 记忆系统 v2（Memory Policy / Retrieval v2） ----------
# 总开关：False 时回退旧系统（旧 Consolidator 输出、旧 Retriever、旧 Prompt Builder）
MEMORY_V2_ENABLED = _env("MEMORY_V2_ENABLED", "true").lower() in ("true", "1", "yes")

# Mode 检测的最低调用分数：detect_mode 打分制下，得分低于该值的信号不足以把
# 模式从 CASUAL_REPLY 改判为其他模式。可调、可 benchmark（越高越保守）。
MODE_DETECT_MIN_SCORE = _env_float("MODE_DETECT_MIN_SCORE", 0.5)

# 候选审核门槛（Gate 1：Confidence 三档）—— 由 MemoryManager.process_new_candidates 使用
# confidence >= MEMORY_CONFIRM_HIGH_CONFIDENCE → 直接晋升（用户明确直接陈述）
# confidence >= MEMORY_OBSERVE_LOW_CONFIDENCE  → 看证据充分度（来源等级 / 复现次数）
# confidence <  MEMORY_OBSERVE_LOW_CONFIDENCE  → OBSERVING，等待更多证据
MEMORY_CONFIRM_HIGH_CONFIDENCE = _env_float("MEMORY_CONFIRM_HIGH_CONFIDENCE", 0.85)
MEMORY_OBSERVE_LOW_CONFIDENCE = _env_float("MEMORY_OBSERVE_LOW_CONFIDENCE", 0.6)

# 检索排序权重（Memory Score =
#   w1*Context Match + w2*Usage Match + w3*Semantic Similarity + w4*Recency + w5*Confidence + w6*Importance）
# 原则：Policy / Context 优先于 Similarity，避免“找错”而非“找不到”。
# 六维独立：Context=类型/触发对当前模式的契合，Usage=usage 与该模式匹配，Semantic=词面，
# Recency=时效（见 MEMORY_SCORE_W_RECENCY），Conf/Imp=记忆自带质量。
# 权重依据（benchmark 实测）：ctx/sem 决定「当前该不该用这条」，而 conf/imp 只描述
# 「记忆本身可靠/重要」，与当前决策关系弱，适合当 tie-breaker——因此 conf/imp 各从
# 0.10 压到 0.05，把省下的权重补给 ctx（0.20→0.25）与 sem（0.30→0.35）。否则
# C04/T05 这类 conf≈0.98/imp≈0.9 的高质量诱饵会在「该不该用」上作弊。
MEMORY_SCORE_W_CONTEXT = _env_float("MEMORY_SCORE_W_CONTEXT", 0.25)
MEMORY_SCORE_W_USAGE = _env_float("MEMORY_SCORE_W_USAGE", 0.20)
MEMORY_SCORE_W_SEMANTIC = _env_float("MEMORY_SCORE_W_SEMANTIC", 0.35)
# Recency：新记忆天然压过旧记忆（时效型 EVENT/PLAN 尤其），旧记忆除非语义强相关否则靠后
MEMORY_SCORE_W_RECENCY = _env_float("MEMORY_SCORE_W_RECENCY", 0.10)
MEMORY_SCORE_W_CONFIDENCE = _env_float("MEMORY_SCORE_W_CONFIDENCE", 0.05)
MEMORY_SCORE_W_IMPORTANCE = _env_float("MEMORY_SCORE_W_IMPORTANCE", 0.05)

# usage 与 memory_type 不兼容时的降权系数。第二张表是「主要来源指引」而非硬排除
# （见 Memory Policy Matrix），因此只做轻微降权：0.5 对 usg（0.20 权重里的主导项）
# 已是实质淘汰，会让矩阵漏写直接决定排序结果；0.75 保留兼容项仍能参与排序。
USAGE_TYPE_MISMATCH_PENALTY = _env_float("USAGE_TYPE_MISMATCH_PENALTY", 0.75)

# Recency 兜底半衰期（天）：记忆类型没有 MEMORY_DECAY_DAYS 条目时用此值
MEMORY_RECENCY_HALF_LIFE_DAYS = _env_float("MEMORY_RECENCY_HALF_LIFE_DAYS", 120.0)

# ---------- 消息来源分级（source_kind） ----------
# @ 对话是唯一稳定的用户信息源（依据 check_point#1：群聊主体为角色扮演，
# 被动摄入的可提取信息极少）。开关关闭时退回「所有消息等权」的旧行为：
# prompt 不标注来源、候选不加置信度奖励；schema 字段仍然写入（无害，便于审计）。
MEMORY_SOURCE_KIND_ENABLED = _env("MEMORY_SOURCE_KIND_ENABLED", "true").lower() in ("true", "1", "yes")
# AT_MENTION 来源候选的置信度奖励。仅作微调，不足以让低置信候选越过
# consolidation_prompt 的 0.7 门槛或 MEMORY_OBSERVE_LOW_CONFIDENCE。
MEMORY_AT_MENTION_CONFIDENCE_BONUS = _env_float("MEMORY_AT_MENTION_CONFIDENCE_BONUS", 0.05)

# ---------- 记忆语义检索（可选，Embedding） ----------
# 默认关闭：语义分用 memory.policy 的规则版（词面 Jaccard，离线、确定）。
# 打开后走本地 LM Studio /v1/embeddings 计算查询与记忆的余弦相似度，语义分真正可区分；
# 模型/服务不可用时自动回退规则版，保证链路不中断。
MEMORY_EMBEDDING_ENABLED = _env("MEMORY_EMBEDDING_ENABLED", "false").lower() in ("true", "1", "yes")
MEMORY_EMBEDDING_BASE_URL = _env("MEMORY_EMBEDDING_BASE_URL", "http://127.0.0.1:1234")
MEMORY_EMBEDDING_MODEL = _env("MEMORY_EMBEDDING_MODEL", "")
# 每次语义检索的超时（秒）
MEMORY_EMBEDDING_TIMEOUT = _env_float("MEMORY_EMBEDDING_TIMEOUT", 10.0)
# embedding 路径下 CONTEXTUAL 记忆的“主题匹配”阈值（余弦相似度）。
# 依据实测：正样本余弦 min ≈0.222，取 0.25 留余量；宁松勿严，后面还有 usage 层
# 与分数门槛（MEMORY_SCORE_MIN）兜底。仅作用于 embedding 路径，
# rule-only 路径仍用 policy.CONTEXTUAL_MIN_SIMILARITY（0.05），两条路径阈值不共用。
MEMORY_EMBEDDING_CONTEXTUAL_MIN = _env_float("MEMORY_EMBEDDING_CONTEXTUAL_MIN", 0.25)

# 记忆进入 Prompt 的最低分数门槛（宁缺毋滥）：
# rank_memories 给出的 _score 低于此值时不进聊天素材。避免“合法候选足够多就
# 一定填满 mode_limit”的超召回噪音（Retrieval Spec 第 7 节：不要固定 Top-K）。
# 0.40 的经验依据（embedding 路径）：仅靠领域(1.0)+usage(5)+recency、语义≈0 的
# “及格候选”≈0.60；而类型不兼容降权或低重要度噪音通常落回 0.40 以下，应被挡在门外。
# rule-only 路径对剩余权重归一化（见 rank_memories），分数整体抬高但排序相对不变。
MEMORY_SCORE_MIN = _env_float("MEMORY_SCORE_MIN", 0.40)

# 各模式最大记忆条数（动态上限，而不是固定 Top-K）
MEMORY_LIMIT_CASUAL_REPLY = _env_int("MEMORY_LIMIT_CASUAL_REPLY", 3)
MEMORY_LIMIT_ACTIVE_JOIN = _env_int("MEMORY_LIMIT_ACTIVE_JOIN", 3)
MEMORY_LIMIT_HUMOR = _env_int("MEMORY_LIMIT_HUMOR", 3)
MEMORY_LIMIT_TECH_HELP = _env_int("MEMORY_LIMIT_TECH_HELP", 5)
MEMORY_LIMIT_RECOMMEND = _env_int("MEMORY_LIMIT_RECOMMEND", 5)
MEMORY_LIMIT_EMOTIONAL = _env_int("MEMORY_LIMIT_EMOTIONAL", 3)
MEMORY_LIMIT_CONFLICT_AVOID = _env_int("MEMORY_LIMIT_CONFLICT_AVOID", 10)
MEMORY_LIMIT_GROUP_EVENT = _env_int("MEMORY_LIMIT_GROUP_EVENT", 5)

# Prompt 长度控制（Gemma 27B 虽支持较长上下文，但记忆不是越多越好）
#   Conversation Memory 上限（普通聊天）
MEMORY_CONVERSATION_MAX_TOKENS = _env_int("MEMORY_CONVERSATION_MAX_TOKENS", 500)
#   Behavior Constraint 上限
MEMORY_BEHAVIOR_MAX_TOKENS = _env_int("MEMORY_BEHAVIOR_MAX_TOKENS", 150)
#   技术场景 Conversation 上限
MEMORY_CONVERSATION_TECH_MAX_TOKENS = _env_int("MEMORY_CONVERSATION_TECH_MAX_TOKENS", 1000)

# 记忆类型生命周期（衰减用，天）；FACT 极慢 → GROUP_CONTEXT 很快
MEMORY_DECAY_DAYS: dict[str, float] = {
    "FACT": 730.0,
    "STYLE": 365.0,
    "PREFERENCE": 180.0,
    "RELATION": 180.0,
    "EVENT": 60.0,
    "PLAN": 60.0,
    "GROUP_CONTEXT": 30.0,
}

# 决策追踪（Evaluation & Debug：记录为什么调用/拒绝记忆）
MEMORY_TRACE_ENABLED = _env("MEMORY_TRACE_ENABLED", "true").lower() in ("true", "1", "yes")
# 决策追踪表名
MEMORY_TRACE_TABLE = _env("MEMORY_TRACE_TABLE", "memory_traces")

# Benchmark 数据集目录（Evaluation & Debug）
MEMORY_BENCHMARK_DIR = _env_path(
    "MEMORY_BENCHMARK_DIR", PROJECT_ROOT / "memory" / "benchmark"
)

# ---------- 本地 LLM（LM Studio） ----------
LM_STUDIO_BASE_URL = _env("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234")
LM_STUDIO_MODEL = _env("LM_STUDIO_MODEL", "")
# 远程 OpenAI 兼容 API 的 Bearer Token；本地 LM Studio 留空
LM_STUDIO_API_KEY = _env("LM_STUDIO_API_KEY", "")

# LLM 调用超时（秒）
LLM_TIMEOUT = _env_float("LLM_TIMEOUT", 90.0)

# ---------- 记忆整合 ----------
# 整合统一使用本地 LM Studio（在线整合流程已废弃，见 _deprecated/core_llm_flexiweb.py），
# 数据整理任务与主聊天模型分离，避免显存/推理竞争；可指向同一实例的多模型或独立端口。
CONSOLIDATION_LM_STUDIO_BASE_URL = _env("CONSOLIDATION_LM_STUDIO_BASE_URL", LM_STUDIO_BASE_URL)
# 记忆整合用的 API key（默认与主聊天共用；远程 API 时填写）
CONSOLIDATION_LM_STUDIO_API_KEY = _env("CONSOLIDATION_LM_STUDIO_API_KEY", LM_STUDIO_API_KEY)
# 注意：LM Studio 路由需要完整模型 ID（含 google/ 前缀），如 google/gemma-4-e4b
CONSOLIDATION_LM_STUDIO_MODEL = _env("CONSOLIDATION_LM_STUDIO_MODEL", "google/gemma-4-e4b")
# 整理任务偏低温度，保证 JSON 输出稳定
CONSOLIDATION_LM_STUDIO_TEMPERATURE = _env_float("CONSOLIDATION_LM_STUDIO_TEMPERATURE", 0.3)

# 整合批次大小（整合模型上下文窗口足够，可从旧值 10 放宽）
CONSOLIDATION_LOCAL_BATCH_SIZE = _env_int("CONSOLIDATION_LOCAL_BATCH_SIZE", 30)
# force 路径（@触发/主动发言前）的小批次，尽快出结果
CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE = _env_int("CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE", 10)
# 每次整合时向前回看多少条用于话题连续（与上一批量重叠，保证话题不被切断）
CONSOLIDATION_OVERLAP = _env_int("CONSOLIDATION_OVERLAP", 15)
# 整合最大生成 token 数
CONSOLIDATION_LOCAL_MAX_TOKENS = _env_int("CONSOLIDATION_LOCAL_MAX_TOKENS", 1200)
# 整合日志文件路径（可视化记录每次整合运行详情，可通过 .env 覆盖）
CONSOLIDATION_LOG_PATH = _env_path("CONSOLIDATION_LOG_PATH", PROJECT_ROOT / "memory_consolidation_log.md")

# ---------- 主动发言 ----------
# 是否启用主动发言
PROACTIVE_ENABLED = _env("PROACTIVE_ENABLED", "true").lower() in ("true", "1", "yes")
# 群级硬冷却（秒）：两次主动发言之间的最小间隔。
# 120s 配合 CHECK_INTERVAL=30s / PROB_AT_FAST=0.35 时实测约每 3~4 分钟发言一次，过于频繁。
PROACTIVE_COOLDOWN = _env_int("PROACTIVE_COOLDOWN", 600)
# 距上次自己发言，群里至少要有多少条新消息才允许再开口。
# 比纯时间冷却更贴合语义：冷清群里「自己说完等 10 分钟又自己说」是时间冷却
# 无法拦住的，而消息数门槛能保证「话题真的往前走了」才插话。0 表示不限制。
PROACTIVE_MIN_MESSAGES_SINCE_SPOKE = _env_int("PROACTIVE_MIN_MESSAGES_SINCE_SPOKE", 15)
# 主动发言的定时检查间隔（秒）
PROACTIVE_CHECK_INTERVAL = _env_int("PROACTIVE_CHECK_INTERVAL", 60)
# 消息频率估算窗口（取最近 N 条消息计算平均间隔）
PROACTIVE_FREQ_WINDOW = _env_int("PROACTIVE_FREQ_WINDOW", 10)
# 已由 PROACTIVE_PROB_AT_* 双锚点曲线取代，保留定义以兼容既有 .env
PROACTIVE_HIGH_FREQ_INTERVAL = _env_float("PROACTIVE_HIGH_FREQ_INTERVAL", 20.0)
# 已由 PROACTIVE_PROB_AT_* 双锚点曲线取代，保留定义以兼容既有 .env
PROACTIVE_LOW_FREQ_INTERVAL = _env_float("PROACTIVE_LOW_FREQ_INTERVAL", 180.0)
# 已由 PROACTIVE_PROB_AT_* 双锚点曲线取代，保留定义以兼容既有 .env
PROACTIVE_MAX_PROB = _env_float("PROACTIVE_MAX_PROB", 0.5)
# 已由 PROACTIVE_PROB_AT_* 双锚点曲线取代，保留定义以兼容既有 .env
PROACTIVE_MIN_PROB = _env_float("PROACTIVE_MIN_PROB", 0.05)
# 主动发言时每次最多发出的行数（主动插话宜简短，避免刷屏）
PROACTIVE_MAX_LINES = _env_int("PROACTIVE_MAX_LINES", 1)
# 主动发言前若累计新消息达到该数量，则触发一次短期记忆总结
CONSOLIDATION_TRIGGER_NEW_MESSAGES = _env_int("CONSOLIDATION_TRIGGER_NEW_MESSAGES", 10)

# ---------- 主动发言：睡眠时段 ----------
# 模拟人类作息：睡眠期间关闭一切主动发言（话题插话 + 主动 @），
# 但**被 @ 时照常回复**——用户主动叫它却不回应看起来像掉线，
# 且 AT_MENTION 是当前唯一的记忆来源，睡眠期不回复等于每天损失数小时采集。
# 被动信息收集（消息落库、整合）在睡眠期照常进行。
PROACTIVE_SLEEP_ENABLED = _env("PROACTIVE_SLEEP_ENABLED", "true").lower() in ("true", "1", "yes")
# 睡眠起止（HH:MM，**本地时间**——它描述人类作息，与 DB 时间戳的 UTC 无关）。
# 支持跨午夜：START > END 时视为跨天区间。
PROACTIVE_SLEEP_START = _env("PROACTIVE_SLEEP_START", "23:30")
PROACTIVE_SLEEP_END = _env("PROACTIVE_SLEEP_END", "07:30")
# 醒来缓冲（秒）：苏醒后不立刻恢复主动发言。
# 积压一夜的活跃度统计会让它一睁眼就连发几句。
PROACTIVE_WAKEUP_GRACE_SECONDS = _env_float("PROACTIVE_WAKEUP_GRACE_SECONDS", 900.0)
# 是否在入睡/苏醒时向群里播报一句
PROACTIVE_SLEEP_ANNOUNCE = _env("PROACTIVE_SLEEP_ANNOUNCE", "true").lower() in ("true", "1", "yes")
# 播报台词（逗号分隔多条，随机选一条；留空则不播报对应时段）
PROACTIVE_SLEEP_MESSAGES = [
    t.strip()
    for t in _env(
        "PROACTIVE_SLEEP_MESSAGES",
        "我先去睡了，晚安~,有点困了，明天聊,睡觉去了，你们别聊太晚",
    ).split(",")
    if t.strip()
]
PROACTIVE_WAKEUP_MESSAGES = [
    t.strip()
    for t in _env(
        "PROACTIVE_WAKEUP_MESSAGES",
        "早，我回来了,睡醒了，早上好,起床了~",
    ).split(",")
    if t.strip()
]

# ---------- 主动发言：运行时开关 ----------
# 管理员可在群内临时关闭主动发言（配置级开关之外的另一道闸门），
# 便于部署者在群成员反馈后即时调整，避免未知问题打扰正常聊天。
# 运行时开关持久化在 group_runtime_state 表，重启后仍生效——
# 管理员关掉它通常是因为出了问题，重启不该把它悄悄打开。
PROACTIVE_RUNTIME_TOGGLE_ENABLED = _env("PROACTIVE_RUNTIME_TOGGLE_ENABLED", "true").lower() in ("true", "1", "yes")
# 允许操作运行时开关的用户（QQ 号，逗号分隔）。留空则仅群主/管理员可操作。
PROACTIVE_TOGGLE_ADMINS = {int(x) for x in _env("PROACTIVE_TOGGLE_ADMINS", "").split(",") if x.strip()}

# ---------- 主动发言 v2：话题参与概率曲线（双锚点插值） ----------
# 同一条曲线通过参数即可表达两种意图，无需模式开关：
#   「热闹时插话」（新默认）：PROB_AT_FAST=0.35, PROB_AT_SLOW=0.0
#   「热闹时闭嘴」（旧行为）：PROB_AT_FAST=0.05, PROB_AT_SLOW=0.5
#   完全关闭：两个锚点都设 0
# 群性质差异大（闲聊群 vs 技术群），因此这条曲线必须现场可调。
PROACTIVE_INTERVAL_FAST = _env_float("PROACTIVE_INTERVAL_FAST", 20.0)
PROACTIVE_INTERVAL_SLOW = _env_float("PROACTIVE_INTERVAL_SLOW", 180.0)
PROACTIVE_PROB_AT_FAST = _env_float("PROACTIVE_PROB_AT_FAST", 0.15)
PROACTIVE_PROB_AT_SLOW = _env_float("PROACTIVE_PROB_AT_SLOW", 0.0)
# 曲线整形指数：1.0 线性；>1 把高概率压缩到最活跃一端（更保守）；<1 更平坦
PROACTIVE_PROB_GAMMA = _env_float("PROACTIVE_PROB_GAMMA", 1.0)
# 话题预热：话题刚开始时模型总结不出主题，贸然插话会答非所问
PROACTIVE_TOPIC_WARMUP_SECONDS = _env_float("PROACTIVE_TOPIC_WARMUP_SECONDS", 45.0)

# ---------- 主动发言 v2：每用户 @ 配额 ----------
# 主动 @ 是侵入性最强的行为，必须有硬上限。基础 2 次/天，高频发言者小幅上浮：
# 依据是双向的——高频用户信息产出多、值得多问，且对群内消息容忍度更高。
# 但奖励幅度必须小，上限封顶在 BASE + BONUS_MAX，杜绝「越活跃越被骚扰」。
PROACTIVE_AT_ENABLED = _env("PROACTIVE_AT_ENABLED", "true").lower() in ("true", "1", "yes")
PROACTIVE_AT_QUOTA_BASE = _env_int("PROACTIVE_AT_QUOTA_BASE", 2)
PROACTIVE_AT_QUOTA_BONUS_MAX = _env_int("PROACTIVE_AT_QUOTA_BONUS_MAX", 2)
PROACTIVE_AT_BONUS_MSGS_LOW = _env_int("PROACTIVE_AT_BONUS_MSGS_LOW", 20)
PROACTIVE_AT_BONUS_MSGS_HIGH = _env_int("PROACTIVE_AT_BONUS_MSGS_HIGH", 100)
# 同一用户两次主动 @ 的最小间隔（秒），默认 2 小时
PROACTIVE_AT_USER_COOLDOWN = _env_float("PROACTIVE_AT_USER_COOLDOWN", 7200.0)
# 判定「正在活跃」的时间窗（秒）：只对刚说过话的人主动搭话
PROACTIVE_AT_ACTIVE_WITHIN = _env_float("PROACTIVE_AT_ACTIVE_WITHIN", 300.0)
# 连续无回应上限：超过则暂停对该用户的主动 @（自动退避，避免对不想聊的人反复搭话）
PROACTIVE_MAX_NO_REPLY = _env_int("PROACTIVE_MAX_NO_REPLY", 2)
# 回应检测窗口（秒）：发出提问后该用户在此窗口内有任何发言即视为有回应
PROACTIVE_REPLY_WINDOW_SECONDS = _env_float("PROACTIVE_REPLY_WINDOW_SECONDS", 300.0)
# 冷启动话题清单（无候选可验证时用，逗号分隔）
PROACTIVE_COLDSTART_TOPICS = [
    t.strip()
    for t in _env(
        "PROACTIVE_COLDSTART_TOPICS",
        "最近在玩什么游戏,平时喜欢吃什么,今天天气怎么样,最近在忙什么,平时用什么设备",
    ).split(",")
    if t.strip()
]

# ---------- 数据库清理（测试期用） ----------
# 程序启动时自动清理混乱的记忆数据（测试阶段频繁重启注入的脏数据）
#   True = 每次启动都清理短期/长期记忆并重置整合 checkpoint（用户画像保留）
#   测试结束后请改回 False，否则每次重启都会丢失记忆
DB_CLEANUP_ON_START = _env("DB_CLEANUP_ON_START", "false").lower() in ("true", "1", "yes")
# 清理时是否连原始群消息记录也一起删除（危险操作，默认关闭）
DB_CLEANUP_CLEAR_MESSAGES = _env("DB_CLEANUP_CLEAR_MESSAGES", "false").lower() in ("true", "1", "yes")

# ---------- 记忆压缩（Compressor）配置 ----------
# 轻量化压缩触发阈值（活动记忆条数，超过则考虑轻量触发）
MEMORY_COMPRESS_LIGHT_THRESHOLD = _env_int("MEMORY_COMPRESS_LIGHT_THRESHOLD", 500)
# 轻量化压缩冷却时间（秒），两次轻量化之间最小间隔
MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS = _env_int("MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS", 3600)
# 低价值记忆归档阈值，低于该 importance 的记忆会被归档
MEMORY_ARCHIVE_IMPORTANCE_THRESHOLD = _env_float("MEMORY_ARCHIVE_IMPORTANCE_THRESHOLD", 0.3)
# 低价值记忆归档条件：距离上次访问超过多少天
MEMORY_ARCHIVE_INACTIVE_DAYS = _env_int("MEMORY_ARCHIVE_INACTIVE_DAYS", 180)
# 压缩器运行日志文件名（保存在项目根目录）
MEMORY_COMPRESS_LOG_FILENAME = _env("MEMORY_COMPRESS_LOG_FILENAME", "memory_compressor_log.md")

# ---------- 消息表定期清理 ----------
# 是否启用 group_messages 定期清理（每天定时清理，保留最近 N 条）
MESSAGE_CLEANUP_ENABLED = _env("MESSAGE_CLEANUP_ENABLED", "true").lower() in ("true", "1", "yes")
# 每个群保留的最近消息条数（超出部分删除）
MESSAGE_CLEANUP_KEEP_COUNT = _env_int("MESSAGE_CLEANUP_KEEP_COUNT", 1000)
# 定时清理的执行时间（小时，24小时制），默认凌晨 4 点
MESSAGE_CLEANUP_HOUR = _env_int("MESSAGE_CLEANUP_HOUR", 4)

# ---------- 输出 ----------
MAX_REPLY_LINES = _env_int("MAX_REPLY_LINES", 5)
SEND_INTERVAL = _env_float("SEND_INTERVAL", 0.8)

# ---------- NapCat 前端（NapCat.Shell）进程管理 ----------
# NapCat.Shell 安装目录（需含 launcher-user.bat / NapCatWinBootMain.exe / napcat.mjs）
# 默认取项目根目录上一级下的 NapCat.Shell，可用绝对路径覆盖
NAPCAT_SHELL_PATH = _env_path("NAPCAT_SHELL_PATH", PROJECT_ROOT.parent / "NapCat.Shell")
# 机器人启动时若 NapCat 未运行，是否自动经 launcher-user.bat 拉起
NAPCAT_AUTO_START = _env("NAPCAT_AUTO_START", "true").lower() in ("true", "1", "yes")
# 开机自动登录：写入子进程环境变量 NAPCAT_QUICK_ACCOUNT / NAPCAT_QUICK_PASSWORD。
# NapCat 优先快速登录（历史会话），失效时用密码回退登录；MD5 优先于明文密码。
NAPCAT_QQ_ACCOUNT = _env("NAPCAT_QQ_ACCOUNT", "")
NAPCAT_QQ_PASSWORD = _env("NAPCAT_QQ_PASSWORD", "")
NAPCAT_QQ_PASSWORD_MD5 = _env("NAPCAT_QQ_PASSWORD_MD5", "")

# ---------- NapCat 链路看门狗（外部重启，不再走 WebUI API） ----------
# 距上次收到**任何** OneBot 事件（含 NapCat 周期性发送的心跳元事件）超过该秒数，
# **且主动探活（get_status）失败**，才判定链路中断并外部重启 NapCat
NAPCAT_WATCHDOG_TIMEOUT = _env_int("NAPCAT_WATCHDOG_TIMEOUT", 300)
# 看门狗定时检查间隔（秒）
NAPCAT_WATCHDOG_CHECK_INTERVAL = _env_int("NAPCAT_WATCHDOG_CHECK_INTERVAL", 60)
# 重启后把最近心跳时间拨后此秒数，给恢复留缓冲，避免反复触发
NAPCAT_WATCHDOG_RESTART_COOLDOWN = _env_int("NAPCAT_WATCHDOG_RESTART_COOLDOWN", 120)
# 连续外部重启的最大次数（连接恢复后清零）。达到上限即停止自动重启：
# 重启换不回连接时（如自动登录退化为扫码），继续重启只会持续把 bot 踢下线，
# 且高频登录尝试可能触发 QQ 风控。
NAPCAT_WATCHDOG_MAX_RESTARTS = _env_int("NAPCAT_WATCHDOG_MAX_RESTARTS", 3)
# NapCat 启动输出的日志文件（原先丢进 DEVNULL，导致重启后完全无法诊断）
NAPCAT_LAUNCH_LOG_PATH = _env_path("NAPCAT_LAUNCH_LOG_PATH", PROJECT_ROOT / "napcat_launch.log")
# 是否显示 NapCat 控制台窗口（调试期建议 true，便于直接看到登录界面/扫码提示）
NAPCAT_SHOW_WINDOW = _env("NAPCAT_SHOW_WINDOW", "false").lower() in ("true", "1", "yes")

# ---------- 破防检测 ----------
BAD_PHRASES = [
    "作为一个AI",
    "作为一个AI模型",
    "作为一个语言模型",
    "我是一个AI",
    "我是AI",
    "我是AI模型",
    "作为AI",
    "我是语言模型",
    "我是一个语言模型",
    "我是人工智能",
    "我是一个人工智能",
]

# ---------- 兜底回复 ----------
FALLBACK_REPLY = "......？"
