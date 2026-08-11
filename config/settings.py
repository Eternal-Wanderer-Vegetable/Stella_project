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
RECENT_MESSAGE_LIMIT = _env_int("RECENT_MESSAGE_LIMIT", 3)

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
# 记忆候选晋升为长期记忆的最小重要性
MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE = _env_float("MEMORY_CANDIDATE_CONFIRM_MIN_IMPORTANCE", 0.5)
# 记忆候选晋升为长期记忆的最小置信度
MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE = _env_float("MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE", 0.5)

# ---------- 记忆系统 v2（Memory Policy / Retrieval v2） ----------
# 总开关：False 时回退旧系统（旧 Consolidator 输出、旧 Retriever、旧 Prompt Builder）
MEMORY_V2_ENABLED = _env("MEMORY_V2_ENABLED", "true").lower() in ("true", "1", "yes")

# Mode 检测的最低调用分数：detect_mode 打分制下，得分低于该值的信号不足以把
# 模式从 CASUAL_REPLY 改判为其他模式。可调、可 benchmark（越高越保守）。
MODE_DETECT_MIN_SCORE = _env_float("MODE_DETECT_MIN_SCORE", 0.5)

# 候选审核门槛（Gate 1：Confidence）
#   confidence >= MEMORY_CONFIRM_HIGH_CONFIDENCE   → 直接进入长期记忆
#   MEMORY_OBSERVE_LOW_CONFIDENCE <= confidence    → 进入观察区（OBSERVING）
#   confidence < MEMORY_OBSERVE_LOW_CONFIDENCE     → 丢弃
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

# Recency 兜底半衰期（天）：记忆类型没有 MEMORY_DECAY_DAYS 条目时用此值
MEMORY_RECENCY_HALF_LIFE_DAYS = _env_float("MEMORY_RECENCY_HALF_LIFE_DAYS", 120.0)

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

# LLM 调用超时（秒）
LLM_TIMEOUT = _env_float("LLM_TIMEOUT", 90.0)

# ---------- 记忆整合 ----------
# 整合统一使用本地 LM Studio（在线整合流程已废弃，见 _deprecated/core_llm_flexiweb.py），
# 数据整理任务与主聊天模型分离，避免显存/推理竞争；可指向同一实例的多模型或独立端口。
CONSOLIDATION_LM_STUDIO_BASE_URL = _env("CONSOLIDATION_LM_STUDIO_BASE_URL", LM_STUDIO_BASE_URL)
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
# 主动发言的最小冷却间隔（秒）：冷却期内绝不再主动发言
PROACTIVE_COOLDOWN = _env_int("PROACTIVE_COOLDOWN", 120)
# 主动发言的定时检查间隔（秒）
PROACTIVE_CHECK_INTERVAL = _env_int("PROACTIVE_CHECK_INTERVAL", 30)
# 消息频率估算窗口（取最近 N 条消息计算平均间隔）
PROACTIVE_FREQ_WINDOW = _env_int("PROACTIVE_FREQ_WINDOW", 10)
# 平均消息间隔 <= 此值（秒）视为高频（活跃群），主动发言概率低
PROACTIVE_HIGH_FREQ_INTERVAL = _env_float("PROACTIVE_HIGH_FREQ_INTERVAL", 20.0)
# 平均消息间隔 >= 此值（秒）视为消息频率过低（冷清群）→ 完全不再主动发言，
# 只有频率高于它（平均间隔更小）时才按概率插话
PROACTIVE_LOW_FREQ_INTERVAL = _env_float("PROACTIVE_LOW_FREQ_INTERVAL", 180.0)
# 主动发言的最大概率（0~1，高频区间的最小概率不可为 0）
PROACTIVE_MAX_PROB = _env_float("PROACTIVE_MAX_PROB", 0.5)
PROACTIVE_MIN_PROB = _env_float("PROACTIVE_MIN_PROB", 0.05)
# 主动发言时每次最多发出的行数（主动插话宜简短，避免刷屏）
PROACTIVE_MAX_LINES = _env_int("PROACTIVE_MAX_LINES", 1)
# 主动发言前若累计新消息达到该数量，则触发一次短期记忆总结
CONSOLIDATION_TRIGGER_NEW_MESSAGES = _env_int("CONSOLIDATION_TRIGGER_NEW_MESSAGES", 10)

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

# ---------- NapCat 消息流看门狗（外部重启，不再走 WebUI API） ----------
# 超过该秒数无任何群消息进入，判定链路中断并外部重启 NapCat
NAPCAT_WATCHDOG_TIMEOUT = _env_int("NAPCAT_WATCHDOG_TIMEOUT", 300)
# 看门狗定时检查间隔（秒）
NAPCAT_WATCHDOG_CHECK_INTERVAL = _env_int("NAPCAT_WATCHDOG_CHECK_INTERVAL", 60)
# 重启后把最近消息时间拨后此秒数，给恢复留缓冲，避免反复触发
NAPCAT_WATCHDOG_RESTART_COOLDOWN = _env_int("NAPCAT_WATCHDOG_RESTART_COOLDOWN", 120)

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
