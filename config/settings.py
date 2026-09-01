# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""集中配置模块。

本模块是 Stella 机器人的“配置中枢”：通过读取用户数据目录下的 .env（及按
ENVIRONMENT 区分的 .env.dev / .env.prod）环境变量，将全部运行时参数集中
导出为模块级常量，供 memory/、core/ 等业务模块 import 使用。业务代码不改动
此文件即可调整参数。环境变量解析统一走 _env / _env_int / _env_float 三个
私有助手，保证类型安全并带默认值兜底。

两个根目录必须分清（2026-08-27 起）：

- ``PROJECT_ROOT``：**程序目录**（bot.py 所在处）。升级时整体被新版本替换，
  代码、``.env.example``、发布包自带的默认人格与能力配置都在这里。
- ``STELLA_HOME``：**用户数据目录**（``config/home.py`` 定位）。升级时不动，
  ``.env``、记忆库、空间配置、自定义人格、第三方插件、日志都在这里。

新增配置项时按这条准则选基准：**用户会改的、丢了心疼的 → STELLA_HOME；
随发布包一起替换的 → PROJECT_ROOT**。选错的后果是升级时数据被覆盖或读不到。
旧布局（STELLA_HOME == PROJECT_ROOT）下两者等价，所以本地跑不出差别——
只有真正升级时才暴露，这也是为什么这条准则要写在这里。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from . import home

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

# ---------- 用户数据根目录（STELLA_HOME） ----------
# PROJECT_ROOT 是**程序目录**（升级时整体替换），STELLA_HOME 是**用户数据目录**
# （升级时不动）。定位顺序见 config/home.py：环境变量 → 机器级指针文件 →
# 旧布局（数据就在安装目录内）→ 安装目录同级的 StellaData。
#
# 旧布局下 STELLA_HOME == PROJECT_ROOT，所有路径与 2026-08-27 之前完全一致，
# 存量安装原地继续工作。刻意在这里不创建目录：import config 不该有副作用，
# 真正落盘由 deploy init / deploy migrate 显式触发。
_HOME = home.resolve(PROJECT_ROOT)
STELLA_HOME = _HOME.path
STELLA_HOME_SOURCE = _HOME.source

# 加载 .env（在用户数据目录里；不覆盖已有环境变量）
load_dotenv(STELLA_HOME / ".env", override=False)

# 根据 ENVIRONMENT 加载环境覆盖文件（覆盖 .env 中的值）
_ENVIRONMENT = os.getenv("ENVIRONMENT", "").strip().lower()
if _ENVIRONMENT in ("dev", "development"):
    load_dotenv(STELLA_HOME / ".env.dev", override=True)
elif _ENVIRONMENT in ("prod", "production"):
    load_dotenv(STELLA_HOME / ".env.prod", override=True)


def _env(key: str, default: str = "") -> str:
    """读取字符串环境变量并按优先级返回。

    参数:
        key: 环境变量名。
        default: 变量**未设置**时返回的默认值。
    返回:
        key 对应的环境变量值；未设置时返回 default。

    注意「未设置」与「设为空」是两回事：``KEY=`` 会返回空字符串而不是 default。
    这是有意的——``LM_STUDIO_API_KEY=`` 的空值本身就有意义（表示「不带 key」），
    一刀切回落会让用户无法表达它。**默认值需要继承另一个配置项时，用
    ``_env_inherit``**，那里空值才等同未设置。
    """
    return os.getenv(key, default)


def _env_inherit(key: str, inherited: str) -> str:
    """读取「默认继承另一个配置项」的字符串环境变量；**空值等同未设置**。

    参数:
        key: 环境变量名；
        inherited: 未设置或设为空时继承的父项值（传入父项常量本身，
            变量名必须与父项的环境变量名一致——``deploy/env_schema.py``
            靠这个名字告诉 GUI「这一项继承自谁」）。
    返回:
        去除首尾空白后的环境变量值；为空则返回 inherited。

    **为什么不能直接用 ``_env``**：GUI 的高级配置页会把 schema 里每个键都写成
    ``KEY=值`` 一行，而继承型默认值在 AST 里不是字面量、schema 只能给出空串，
    于是 ``.env`` 里落下 ``KEY=``。``_env`` 把它读成 ``""``，继承链就被静默切断了
    ——2026-08-28 之前 ``MEMORY_EXTRACT_LM_STUDIO_BASE_URL`` 正是这样变成空串，
    使阶段2 候选提取每次调用都拼出 ``/v1/chat/completions`` 这种无协议 URL 而失败，
    再静默回退阶段1 候选。修复是三处协同的，缺一不可：
    本函数（空值回落）、``env_schema`` 输出 ``inherits`` 标记、GUI 对这类字段留空时
    **不写入** ``.env``。
    """
    return os.getenv(key, "").strip() or inherited


def _env_int_inherit(key: str, inherited: int) -> int:
    """读取「默认继承另一个配置项」的整数环境变量；**空值等同未设置**。

    参数:
        key: 环境变量名；
        inherited: 未设置或设为空时继承的父项值（传入父项常量本身，变量名
            必须与父项的环境变量名一致，理由同 :func:`_env_inherit`）。
    返回:
        解析成功返回整数；空值或解析失败返回 inherited。

    行为与 :func:`_env_int` 完全一致——独立命名只为让 ``deploy/env_schema.py``
    输出 ``inherits`` 标记：继承型默认值在 AST 里不是字面量，schema 拿不到数值，
    GUI 必须知道「留空即继承谁」才能渲染提示、并在留空时**不写入** ``.env``。
    """
    return _env_int(key, inherited)


def _env_float_inherit(key: str, inherited: float) -> float:
    """读取「默认继承另一个配置项」的浮点环境变量；**空值等同未设置**。

    与 :func:`_env_int_inherit` 同理，见那里的说明。
    """
    return _env_float(key, inherited)


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


def _user_path(relative: str) -> Path:
    """用户数据路径：``STELLA_HOME/relative``。"""
    return STELLA_HOME / relative


def _shipped_or_user(relative: str) -> Path:
    """既随发布包出厂、又允许用户改的文件（默认人格、能力配置）。

    优先用 ``STELLA_HOME`` 里的那份（用户改过的）；那里没有就用程序目录里出厂的那份。
    这样新版本的默认值能随升级到达，而用户的修改不会被覆盖。
    """
    candidate = STELLA_HOME / relative
    if candidate.exists():
        return candidate
    return PROJECT_ROOT / relative


# ---------- 目录与文件路径（可通过 .env 覆盖） ----------
# 用户数据锚定 STELLA_HOME（升级不动），程序资源锚定 PROJECT_ROOT（随版本替换）；
# 如需自定义，在 .env 里设置同名环境变量（绝对路径）。
SYSTEM_PROMPT_PATH = _env_path(
    "SYSTEM_PROMPT_PATH", _shipped_or_user("system_prompts/default.md")
)
DB_PATH = _env_path("DB_PATH", _user_path("memory/agent_memory.db"))
# 扩展是程序代码而不是用户数据：随发布包一起替换
EXTENSIONS_DIR = _env_path("EXTENSIONS_DIR", PROJECT_ROOT / "extensions")

# ---------- 日志目录 ----------
# **所有运行期日志的唯一落点。** 改这一个就能把全部日志搬走（含结构化 JSON 日志、
# 思考日志、整合日志、压缩日志、启动诊断），单个文件仍可用各自的 *_PATH 单独覆盖。
#
# 2026-08-25 之前这些文件散在项目根目录（stella_thought_logs.md /
# memory_consolidation_log.md / memory_compressor_log.md / boot_debug.log），
# 排查时要在根目录一堆源码里翻，而且每加一个日志就多一条 .gitignore。
#
# 写日志的代码**必须自己 mkdir**：LOG_DIR 可能被指到不存在的路径，而且日志写入
# 失败不该影响主链路，所以不能依赖「启动时有人建过这个目录」。
LOG_DIR = _env_path("LOG_DIR", _user_path("logs"))
# 人读的思考/决策日志（每轮的完整 prompt、原始输出、路由判定、工具结果）
THOUGHT_LOG_PATH = _env_path("THOUGHT_LOG_PATH", LOG_DIR / "stella_thought_logs.md")
# 启动期诊断（插件发现/加载结果、能力装配、原型预热）。每次启动清空重写——
# 它回答的是「这一次启动为什么没加载上插件」，保留历史反而要翻。
BOOT_DIAG_LOG_PATH = _env_path("BOOT_DIAG_LOG_PATH", LOG_DIR / "boot_debug.log")

# ---------- QQ 群聊 ----------
# 逗号分隔的群号字符串转为 int 集合；过滤空片段避免尾逗号导致 int('') 报错。
# 群号从 .env 的 ALLOWED_GROUPS 读取（用英文逗号分隔多个群号）。
ALLOWED_GROUPS = {int(x) for x in _env("ALLOWED_GROUPS", "").split(",") if x.strip()}

# ---------- 上下文 ----------
# 每次回复时附加的最近原始消息条数（含 Bot 自己的发言）。
# 短期摘要由整合器产出，按设计滞后（需累积 CONSOLIDATION_TRIGGER_NEW_MESSAGES 条
# 才更新），因此最近几轮对话必须以原始消息补足——否则 Bot 看不到自己刚说过什么，
# 用户的「手机」「对」这类简短回应会被接到上一个话题上去。
# 太小：活跃群里刷屏会把 Bot 自己的提问挤出窗口，简短回应（「手机」「对」）
#       重新被接到上一个话题（2026-08-13 bug 的成因）；
# 太大：无关历史会干扰模型，且每次回复的 prompt 变长。
# 12 是起点，需按真实群的刷屏速度调整。
RECENT_TAIL_LIMIT = _env_int("RECENT_TAIL_LIMIT", 12)

# 原始尾巴的时间窗（分钟）：超出该时长的消息不再算作「最近的对话」。
# 停机数小时后重启时，仅按 id 取最近 N 条会把几小时前的对话当成刚刚发生的事
# （2026-08-15 缺陷）。0 表示不做时间过滤。
RECENT_TAIL_MAX_AGE_MINUTES = _env_float("RECENT_TAIL_MAX_AGE_MINUTES", 45.0)
# 相邻两条消息间隔超过该分钟数时，在尾巴里插入一行断层标记。
# 比直接丢弃更好：让模型知道「之前聊过但已经过去很久」，而不是完全失忆。
RECENT_TAIL_GAP_MARK_MINUTES = _env_float("RECENT_TAIL_GAP_MARK_MINUTES", 15.0)
# 话题摘要超过该分钟数未更新时，标题改为「之前的话题」并注明时长。
# 摘要由整合器产出、按设计滞后，不标注新鲜度会让模型以为那是当前话题。
SHORT_TERM_SUMMARY_STALE_MINUTES = _env_float("SHORT_TERM_SUMMARY_STALE_MINUTES", 60.0)

# ---------- 会话上下文压缩 ----------
# 短时连续对话中，早期消息会滚出尾巴窗口而彻底消失。本机制把滚出的部分
# 压缩成一段摘要，使 Bot 在长对话里保持连贯（类似 coding agent 的 compact）。
#
# 与另两层上下文的边界（按消息 id 划分，绝不重叠）：
#   会话摘要：summarized_up_to_id → 尾巴起点（较早部分，已压缩）
#   原始尾巴：最近 RECENT_TAIL_LIMIT 条（原文）
#   话题摘要：整合器产出的跨会话背景
# 重叠会导致同一段对话出现两个版本，模型以摘要为准从而接错话题
# （2026-08-13 缺陷的成因）。
SESSION_CONTEXT_ENABLED = _env("SESSION_CONTEXT_ENABLED", "true").lower() in ("true", "1", "yes")
# 待压缩文本超过该 token 估算值才触发压缩。
# 不是每轮都压缩：27B 在 GPU 上约 2 秒，但每轮多一次调用会让 COMPACT 角色所在
# 那道闸门（纯本地默认是 LOCAL 槽，与聊天同一道）的串行等待明显放大。
# COMPACT 改绑到在线槽后这项的成本含义就变了：不再是等待，而是账单。
SESSION_COMPACT_THRESHOLD_TOKENS = _env_int("SESSION_COMPACT_THRESHOLD_TOKENS", 600)
# 摘要自身的 token 预算：超过则连同新内容重新压缩一次（摘要的摘要）
SESSION_SUMMARY_MAX_TOKENS = _env_int("SESSION_SUMMARY_MAX_TOKENS", 300)
# 单次压缩最多喂入多少条消息，防止长时间未压缩后一次性过大
SESSION_COMPACT_MAX_MESSAGES = _env_int("SESSION_COMPACT_MAX_MESSAGES", 60)
# 空闲多久视为会话结束（秒）：结束时清空摘要并触发一次完整整合
SESSION_IDLE_TIMEOUT_SECONDS = _env_float("SESSION_IDLE_TIMEOUT_SECONDS", 900.0)
# 空闲会话的检查间隔（秒）。不需要很频繁——它只负责收尾。
SESSION_IDLE_CHECK_INTERVAL = _env_int("SESSION_IDLE_CHECK_INTERVAL", 300)

# ---------- 长期记忆引用策略 ----------
# 主动发言时引用的长期记忆条数（按证据新鲜度倒序取最近 N 条）
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

# ---------- 候选强化（交叉验证） ----------
# 同一事实被再次独立观察到时的置信度增益。这是「暂存 → 交叉验证 → 逐步强化」
# 的核心：单次陈述不足以晋升，复现才是证据。取 0.12 使 0.5 起步的候选
# 约 2 次复现后跨过 MEMORY_OBSERVE_LOW_CONFIDENCE(0.6)。
MEMORY_CANDIDATE_REOCCURRENCE_BONUS = _env_float("MEMORY_CANDIDATE_REOCCURRENCE_BONUS", 0.12)
# 候选在 OBSERVING 停留的最长天数，超期未获新证据即标 REJECTED（不删除，保留供审计）
MEMORY_CANDIDATE_MAX_OBSERVING_DAYS = _env_int("MEMORY_CANDIDATE_MAX_OBSERVING_DAYS", 30)
# 按类型覆盖上面的 TTL（天）；未列出的类型沿用全局值。与 MEMORY_DECAY_DAYS 同为
# 代码级常量而非 .env 键——它是「这类信息多久之后不再值得等第二次证据」的语义
# 判断，不是部署参数。
#
# 为什么必须分类型：TTL 的含义是「愿意为这条信息等多久复现」。一条 EVENT
# （「听到地震预警」）如果三天内没被再提一次，它既没重要到会被反复说起，也已经
# 不是「当下」；统一 30 天只会让它一直占着候选池并被反复挑中去验证
# （见 design_docs/bug_report/bug_report_2026_8_31#1.md 现象 2）。
#   EVENT 3 天：够覆盖「周末说的事、周一还有人提」，再长就没有语义价值；
#   PLAN 14 天：计划有执行窗口，两周内无人再提，多半已作废或已完成；
#   GROUP_CONTEXT 7 天：群层面的上下文变化最快（它的衰减期本就是最短的 30 天）。
MEMORY_CANDIDATE_MAX_OBSERVING_DAYS_BY_TYPE: dict[str, float] = {
    "EVENT": 3.0,
    "PLAN": 14.0,
    "GROUP_CONTEXT": 7.0,
}
# evidence 字段累积上限（字符）。多次复现会不断追加证据，需防止无界增长
MEMORY_CANDIDATE_EVIDENCE_MAX_CHARS = _env_int("MEMORY_CANDIDATE_EVIDENCE_MAX_CHARS", 800)
# 模型没给 importance 时的兜底值。**不能是 0**：0 会被 MEMORY_PROMOTE_MIN_IMPORTANCE
# 一票否决，候选从此永远卡在 OBSERVING、被主动验证反复追问却永远晋升不了
# （见 design_docs/bug_report/bug_report_2026_8_31#1.md）。取中位值让
# confidence 与复现次数继续决定去留——「importance 不单独构成晋升依据」这条
# 设计意图，本来就该同时意味着它不能单独让候选失败。
MEMORY_CANDIDATE_DEFAULT_IMPORTANCE = _env_float("MEMORY_CANDIDATE_DEFAULT_IMPORTANCE", 0.5)

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
# embedding 走哪个端点槽的闸门：auto | <端点槽名> | none。取代旧的布尔键
# LLM_SCHEDULER_GATE_EMBEDDING（true→auto、false→none，旧键仍被兼容读取）。
# auto 的判定是确定性的、doctor 会打印结果：**若存在 KIND=local 且 BASE_URL 与
# MEMORY_EMBEDDING_BASE_URL 相同的端点槽 → 共用该槽闸门；否则独立不排队。**
# 为什么不能沿用旧的布尔默认值：旧默认把 embedding 挂在「主聊天」闸门上，理由是
# 「embedding 默认与主聊天同实例」。一旦对话切到在线端点，这个前提就不成立了，
# 本地 embedding 会去排在线调用的队、白白串行。
MEMORY_EMBEDDING_GATE = _env("MEMORY_EMBEDDING_GATE", "auto")
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
# 本段是**旧键**，保留为「LLM 端点 / LLM 角色」两节的默认继承来源：未迁移的 .env
# 只填这三个键也能照旧跑（LOCAL 槽与 CHAT/ROUTER/COMPACT 角色都默认继承它们）。
# 新配置请直接写 LLM_ENDPOINT_* / LLM_ROLE_*，见本文件末尾那两节。
LM_STUDIO_BASE_URL = _env("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234")
LM_STUDIO_MODEL = _env("LM_STUDIO_MODEL", "")
# 远程 OpenAI 兼容 API 的 Bearer Token；本地 LM Studio 留空
LM_STUDIO_API_KEY = _env("LM_STUDIO_API_KEY", "")

# LLM 调用超时（秒）
LLM_TIMEOUT = _env_float("LLM_TIMEOUT", 90.0)

# ---------- LLM 调度器（应用层闸门） ----------
# LM Studio 本身不限并发，应用层必须手动串行访问共享模型，否则并发推理会
# 互相拖慢且难以定位。调度器为两种资源（chat=27B / consolidation=E4B）各自
# 维护 FIFO 队列，两种资源彼此并行；调用方绝不能同时持有两把锁（否则跨模型
# 队头阻塞——这正是 consolidate_group 用独立群级锁的原因）。
# 等待/持有超阈值打 warning，配合 snapshot() 做可观测性；优先级暂未实现。
# 排队等待超过该秒数才告警。实测阶段2 提取占 27B 约 20 秒（1617 prompt tokens
# + 280 生成 @19 tok/s），30 秒意味着前面已排了一个以上后台任务。
LLM_SCHEDULER_WAIT_WARN_SECONDS = _env_float("LLM_SCHEDULER_WAIT_WARN_SECONDS", 30.0)
# 持有超过该秒数才告警。后端内含 3 次重试（每次 timeout 120s），单次持有上界
# 远大于一次正常请求；90 秒足以覆盖正常生成又能抓卡死。
LLM_SCHEDULER_HOLD_WARN_SECONDS = _env_float("LLM_SCHEDULER_HOLD_WARN_SECONDS", 90.0)
# 排队数（不含持有者）达到该深度时打 warning
LLM_SCHEDULER_QUEUE_WARN_DEPTH = _env_int("LLM_SCHEDULER_QUEUE_WARN_DEPTH", 3)
# 优先级排队**尚未实现**，保留开关：先以 FIFO + snapshot() 积累真实排队数据，
# 多群上线后据数据再决定是否偏离 FIFO。
LLM_SCHEDULER_PRIORITY_ENABLED = _env("LLM_SCHEDULER_PRIORITY_ENABLED", "false").lower() in ("true", "1", "yes")
# **已被 MEMORY_EMBEDDING_GATE 取代**，保留仅为兼容未迁移的 .env：
# 未显式设置 MEMORY_EMBEDDING_GATE 时，本键 false 等价于 GATE=none、true 等价于 auto。
# 旧语义：embedding 默认与主聊天同实例（一次检索可编码 20+ 条），需走 chat 闸门；
# 独立实例部署（与聊天模型隔离）时可关闭。
LLM_SCHEDULER_GATE_EMBEDDING = _env("LLM_SCHEDULER_GATE_EMBEDDING", "true").lower() in ("true", "1", "yes")

# ---------- 记忆整合 ----------
# 数据整理任务与主聊天模型分离，避免显存/推理竞争；可指向同一实例的多模型或独立端口。
# 留空则继承主聊天配置。
# 历史注记：_deprecated/core_llm_flexiweb.py 那套「用 Playwright 抓网页充当在线模型」的
# 整合流程已弃用，**与本项无关**——本项一直在用。（这句话里的「弃用」曾让
# deploy/env_schema.py 的注释子串匹配把本项误判为废弃键、从 GUI 里整个丢掉；
# 现判据已改走 deploy/env_keys.py 的显式登记表，不再猜注释。）
CONSOLIDATION_LM_STUDIO_BASE_URL = _env_inherit("CONSOLIDATION_LM_STUDIO_BASE_URL", LM_STUDIO_BASE_URL)
# 记忆整合用的 API key（默认与主聊天共用；远程 API 时填写）
CONSOLIDATION_LM_STUDIO_API_KEY = _env_inherit("CONSOLIDATION_LM_STUDIO_API_KEY", LM_STUDIO_API_KEY)
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
# 整合日志文件路径（可视化记录每次整合运行详情，可通过 .env 覆盖）。默认落在 LOG_DIR。
CONSOLIDATION_LOG_PATH = _env_path("CONSOLIDATION_LOG_PATH", LOG_DIR / "memory_consolidation_log.md")

# ---------- 整合成本控制（在线端点专用批量 + 预筛兜底） ----------
# 上面那组 CONSOLIDATION_LOCAL_* 是**本地**端点的取值：本地推理不计费，代价只是
# 时间，所以批量小、重叠多、force 路径尽快出结果都是对的。切到在线端点后这些
# 取值全部变成「每批都在重复付固定成本」，因此另给一组在线取值，
# 只在 CONSOLIDATION 角色实际落在在线端点上时生效（core.llm.registry.role_is_online）。
#
# ⚠️ 省钱只能靠**加大批量**，绝不能靠拉长 CONSOLIDATION_SCHEDULE_INTERVAL：
# 厂商前缀缓存是分钟级 TTL，间隔一旦超过 TTL，固定部分就从缓存价回到全价，
# 反而更贵。间隔请保持 ≤ 4 分钟。

# 在线端点下的常规整合批次。默认 60（本地 30 的两倍）：固定 prompt 成本按批摊薄，
# 批量翻倍就等于把每条消息摊到的固定成本砍半。
CONSOLIDATION_ONLINE_BATCH_SIZE = _env_int("CONSOLIDATION_ONLINE_BATCH_SIZE", 60)
# 在线端点下 force 路径（@触发/主动发言前）的批次。本地是 10，即用 1/3 的批量付
# 同一份固定成本——全链路单位成本最高的一条路径。默认 30 与本地常规批量对齐。
# 代价只是摘要新鲜度稍滞后：force 整合走 asyncio.create_task 的 fire-and-forget，
# 不在 @ 回复的关键路径上，加大批量不会让 @ 变慢。
CONSOLIDATION_ONLINE_FORCE_BATCH_SIZE = _env_int("CONSOLIDATION_ONLINE_FORCE_BATCH_SIZE", 30)
# 在线端点下向前回看的重叠条数。默认 0 = 不重叠：重叠消息每批都要重复计费，
# 而话题连续性已经由每批都在传的 current_summary（阶段1 输出的 active_summary）承担。
# 填成与 CONSOLIDATION_OVERLAP 相同的值即可恢复重叠。
CONSOLIDATION_ONLINE_OVERLAP = _env_int("CONSOLIDATION_ONLINE_OVERLAP", 0)
# 连续跳过上限（memory/cost_gates.py 的预筛兜底）。预筛跳过时**不推进 checkpoint**，
# 消息留着攒到下一轮；但如果某个群持续只有图片刷屏，它就会无限滞留。
# 连续跳过达到这个次数就强制整合一次并清零，保证「最坏情况下也只是延迟，不是丢失」。
# 设为 0 = 不兜底（不建议）。
CONSOLIDATION_MAX_SKIP_STREAK = _env_int("CONSOLIDATION_MAX_SKIP_STREAK", 3)

# ---------- 记忆候选提取（两阶段整合的第二阶段） ----------
# 整合拆两步：阶段1（E4B）出短期摘要+用户画像+自我披露判断；阶段2（本段配置的
# 模型）只做一件高精度的事——从消息里精确提取「用户亲口说的、关于自己的稳定信息」。
# 依据（log_2026_8_16_1717）：E4B 能总结主题，却系统性地把候选提取判空
# （7 批全空，且明确「读到了信息但主动弃掉」）。候选提取是高精度抽取任务，
# 交给主聊天用的 27B。默认全部继承主聊天配置（即 27B），保留独立键便于将来替换。
MEMORY_EXTRACT_LM_STUDIO_BASE_URL = _env_inherit("MEMORY_EXTRACT_LM_STUDIO_BASE_URL", LM_STUDIO_BASE_URL)
MEMORY_EXTRACT_LM_STUDIO_API_KEY = _env_inherit("MEMORY_EXTRACT_LM_STUDIO_API_KEY", LM_STUDIO_API_KEY)
MEMORY_EXTRACT_LM_STUDIO_MODEL = _env_inherit("MEMORY_EXTRACT_LM_STUDIO_MODEL", LM_STUDIO_MODEL)
# 提取偏低温度保证 JSON 稳定；比整合的 0.3 再低一点，抽取任务不需要发散
MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE = _env_float("MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE", 0.2)
# 提取只输出 memory_candidates 数组，不需要很大；但要容纳多条候选
MEMORY_EXTRACT_MAX_TOKENS = _env_int("MEMORY_EXTRACT_MAX_TOKENS", 1000)
# 阶段2 总开关。关闭时退回单阶段（E4B 一次性出全部，即 af60473 之前的行为），
# 用于对照与回退。
MEMORY_EXTRACT_ENABLED = _env("MEMORY_EXTRACT_ENABLED", "true").lower() in ("true", "1", "yes")

# ---------- 整合调度 ----------
# 定时整合的检查间隔（秒）。整合此前只在 @ 触发与主动发言前进行，
# 被动摄入速度超过整合速度时会无界积压（2026-08-16 实测积压 1004 条，
# 且超过 MESSAGE_CLEANUP_KEEP_COUNT 后未整合消息会被清理直接丢弃）。
CONSOLIDATION_SCHEDULE_INTERVAL = _env_int("CONSOLIDATION_SCHEDULE_INTERVAL", 120)
# 单次定时任务最多连续整合几批。CPU 小模型单批 20~60 秒：
# 批次太多会长时间占用整合模型，太少则追不上积压。
CONSOLIDATION_MAX_ROUNDS_PER_RUN = _env_int("CONSOLIDATION_MAX_ROUNDS_PER_RUN", 3)
# 积压超过该条数时日志提升为 warning（可观测性，不改变行为）
CONSOLIDATION_BACKLOG_WARN = _env_int("CONSOLIDATION_BACKLOG_WARN", 300)

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
# 主动 @ 的排除名单（QQ 号，逗号分隔）：这些账号不会被选为主动搭话对象。
# 主要用途是群内其他 AI ——互相 @ 会触发无终止的循环对话。
# 注意：被排除的账号仍会被动收集信息（消息照常落库与整合），
# 只是不主动向它们提问。
PROACTIVE_AT_EXCLUDE_USERS = {int(x) for x in _env("PROACTIVE_AT_EXCLUDE_USERS", "").split(",") if x.strip()}
# 不参与「主动验证」的候选类型（逗号分隔；留空表示所有类型都可验证）。
# 主动 @ 的配额极其稀缺（默认每人每天 2 次），而验证的目的是把候选推过晋升线、
# 变成**长期**记忆。对时效型信息这笔配额本身就花错了：等确认下来，信息已经过期。
# 语义上也说不通——「你住在 X 吗」隔一周仍然成立，「你听到地震预警了吗」隔一周
# 就是荒谬的（见 design_docs/bug_report/bug_report_2026_8_31#1.md 现象 2）。
# GROUP_CONTEXT 另有一层理由：它归属于群而不是人，向某个人验证群层面的事本身错位。
# 注意：排除的只是**主动追问**这一条路径。这些候选照常落库、照常可以凭 AT_MENTION
# 单次晋升或靠被动复现晋升，只是不会为它们去打扰用户。
PROACTIVE_VERIFY_EXCLUDE_TYPES = {
    t.strip().upper()
    for t in _env("PROACTIVE_VERIFY_EXCLUDE_TYPES", "EVENT,PLAN,GROUP_CONTEXT").split(",")
    if t.strip()
}

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
# 压缩器运行日志路径。默认落在 LOG_DIR。
# 2026-08-25 之前这一项叫 MEMORY_COMPRESS_LOG_FILENAME，是个**文件名**而不是路径
# （由 memory/compressor.py 拼到 PROJECT_ROOT 上），因此无法指到别处、也不像其他
# 日志项那样支持绝对路径。统一成 _env_path 后写法与 THOUGHT_LOG_PATH 一致；
# 旧键名已登记在 deploy/env_keys.py 的 DEPRECATED 表里，`deploy doctor` 会提示改名。
MEMORY_COMPRESS_LOG_PATH = _env_path("MEMORY_COMPRESS_LOG_PATH", LOG_DIR / "memory_compressor_log.md")

# ---------- 消息表定期清理 ----------
# 是否启用 group_messages 定期清理（每天定时清理，保留最近 N 条）
MESSAGE_CLEANUP_ENABLED = _env("MESSAGE_CLEANUP_ENABLED", "true").lower() in ("true", "1", "yes")
# 每个群保留的最近消息条数（超出部分删除）
MESSAGE_CLEANUP_KEEP_COUNT = _env_int("MESSAGE_CLEANUP_KEEP_COUNT", 1000)
# 定时清理的执行时间（小时，24小时制），默认凌晨 4 点
MESSAGE_CLEANUP_HOUR = _env_int("MESSAGE_CLEANUP_HOUR", 4)
# 清理时是否保护未整合的消息（checkpoint 之后的消息不删除）。
# 关闭会导致积压超过 MESSAGE_CLEANUP_KEEP_COUNT 时未整合消息被永久丢弃，
# 那些内容永远不会进入记忆系统，且 checkpoint 对齐会让丢失变得不可见。
MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED = _env(
    "MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED", "true"
).lower() in ("true", "1", "yes")

# ---------- 输出 ----------
MAX_REPLY_LINES = _env_int("MAX_REPLY_LINES", 5)
SEND_INTERVAL = _env_float("SEND_INTERVAL", 0.8)

# ---------- OneBot 链路监测 ----------
# 只监测、不重启。Bot 不再管理 NapCat 进程——QQ 的登录风控会把自动登录退化为
# 扫码（见 design_docs/deprecated_napcat_manager.md），登录必须有人在场，
# 进程管理因此没有收益。用户用 NapCatQQ Desktop 装好并登录 NapCat，
# Bot 只连接现成的 OneBot WS 端点（连接方式配置在 .env 顶部：HOST/PORT 或 ONEBOT_WS_URLS）。
LINK_MONITOR_ENABLED = _env("LINK_MONITOR_ENABLED", "true").lower() in ("true", "1", "yes")
# 距上次收到**任何** OneBot 事件（含 NapCat 周期性心跳元事件，默认 15s 一次）
# 超过该秒数，才做一次主动探活。静默 ≠ 断线：群里没人说话时心跳仍在，
# 只挂 on_message 会把安静的群误判为链路中断（2026-08-14 重启循环的成因）。
LINK_MONITOR_TIMEOUT = _env_int("LINK_MONITOR_TIMEOUT", 300)
# 定时检查间隔（秒）
LINK_MONITOR_CHECK_INTERVAL = _env_int("LINK_MONITOR_CHECK_INTERVAL", 60)
# 告警节流（秒）：断线期间不重复刷同样的 error
LINK_MONITOR_ALERT_INTERVAL = _env_int("LINK_MONITOR_ALERT_INTERVAL", 300)

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

# ---------- 结构化日志（供 GUI / 前端消费） ----------
# 与人类可读日志并存：这份是给程序读的，GUI 靠它做级别过滤与错误复制。
STELLA_JSON_LOG_ENABLED = _env("STELLA_JSON_LOG_ENABLED", "true").lower() in ("true", "1", "yes")
STELLA_JSON_LOG_PATH = _env_path("STELLA_JSON_LOG_PATH", LOG_DIR / "stella.jsonl")
# 单条消息的截断长度：prompt 全文动辄数千字符，进结构化日志只会让文件暴涨
STELLA_JSON_LOG_MAX_MESSAGE = _env_int("STELLA_JSON_LOG_MAX_MESSAGE", 500)

# ---------- 本地状态接口 ----------
# 挂在 NoneBot 已有的 ASGI app 上（HOST:PORT/stella/status），**不新增端口**——
# 反向 WS 端点本就是同一个 HTTP 服务器提供的。供 deploy status 与 GUI 读取
# 进程内状态（链路健康度、调度器排队），那些数据外部进程拿不到。
# 只接受回环地址的请求，且响应体不含凭据与群聊内容——HOST 可能是 0.0.0.0，
# 那时本路由也会暴露到局域网。
STELLA_STATUS_API_ENABLED = _env("STELLA_STATUS_API_ENABLED", "true").lower() in ("true", "1", "yes")
STELLA_STATUS_API_PATH = _env("STELLA_STATUS_API_PATH", "/stella/status")

# ---------- 优雅停止 ----------
# 停止时等待在途后台任务（整合/压缩）收尾的上限（秒）。
# LLM 单次调用最长 120s×3 次重试，无限等待会让「停止」看起来卡死。
SHUTDOWN_GRACE_SECONDS = _env_float("SHUTDOWN_GRACE_SECONDS", 30.0)
# 停止请求哨兵：deploy stop 写入该文件，进程内的 watcher 观察到后自行触发退出。
# 不能依赖控制台信号：GUI 用 CREATE_NO_WINDOW(0x08000000) 启动 Bot，子进程根本
# 没有控制台，GenerateConsoleCtrlEvent 发的 CTRL_BREAK 永远送不到（实测）。
# 文件哨兵是跨平台、不依赖控制台、不开新端口的唯一选项。
# 路径可覆盖：项目目录只读时指到可写位置。
# 不用 POST /shutdown：status_api 只读，加写接口就多一个无鉴权的写接口，
# HOST=0.0.0.0 时就是局域网可触发的远程关机。哨兵靠文件系统权限天然只限本机用户。
STELLA_STOP_SENTINEL = _env_path("STELLA_STOP_SENTINEL", _user_path(".stella-stop-request"))
# watcher 轮询间隔（秒）：轮询过于频繁只是空转，0.5s 足够让停止按钮几乎即时响应
STOP_WATCH_INTERVAL_SECONDS = _env_float("STOP_WATCH_INTERVAL_SECONDS", 0.5)

# ---------- AstrBot 插件兼容层 ----------
# 将 AstrBot 生态的第三方插件直接放入 data/plugins/<插件目录>/ 即可。
# 仅支持不依赖大模型能力的功能类插件；依赖模型的插件需官方移植。
ASTRBOT_COMPAT_ENABLED = _env("ASTRBOT_COMPAT_ENABLED", "true").lower() in ("true", "1", "yes")
# 对外声称兼容的 AstrBot 版本（注入日志与插件自检用，仅声明，不代表完全兼容）
ASTRBOT_COMPAT_VERSION = _env("ASTRBOT_COMPAT_VERSION", "4.27.0")
# 第三方插件源码目录（每个子目录为一个插件，需含 metadata.yaml）
ASTRBOT_PLUGINS_DIR = _env_path("ASTRBOT_PLUGINS_DIR", _user_path("data/plugins"))
# 插件配置持久化目录（AstrBot 侧为 data/config）
ASTRBOT_PLUGIN_CONFIG_DIR = _env_path("ASTRBOT_PLUGIN_CONFIG_DIR", _user_path("data/config"))
# 插件运行时数据目录（StarTools.get_data_dir 返回的根目录）
ASTRBOT_PLUGIN_DATA_DIR = _env_path("ASTRBOT_PLUGIN_DATA_DIR", _user_path("data/plugin_data"))
# 是否自动安装插件声明的依赖（requirements.txt）；默认关闭，避免任意代码执行
ASTRBOT_AUTO_INSTALL_REQUIREMENTS = _env("ASTRBOT_AUTO_INSTALL_REQUIREMENTS", "false").lower() in (
    "true",
    "1",
    "yes",
)
# 是否载入插件自带的 <插件目录>/capability.toml（声明三层里优先级最低的那层）。
# 默认开：零配置装完插件就能被聊天触发，是插件接入规范的意义所在。
# 留开关是因为它让**插件作者**决定自己的工具能否被自动调用——而这件事以前需要
# 用户手写 config/capabilities/*.toml 才成立，那是一次显式的逐工具授权。关掉它
# 就退回旧行为：插件工具照常注册、可被显式执行，但不参与语义路由。
# 用户层与出厂层的声明不受本开关影响。详见 docs/plugin-spec.md。
ASTRBOT_PLUGIN_CAPABILITIES_ENABLED = _env(
    "ASTRBOT_PLUGIN_CAPABILITIES_ENABLED",
    "true",
).lower() in ("true", "1", "yes")
# 指令唤醒前缀（逗号分隔）。AstrBot 上游默认为 "/"，插件的 @filter.command 依赖它：
# 群里直接打 "/help" 就能触发，不必先 @ 机器人。留空表示只认 @ / 引用 / 私聊。
ASTRBOT_WAKE_PREFIXES = [
    p for p in (s.strip() for s in _env("ASTRBOT_WAKE_PREFIXES", "/").split(",")) if p
]
# 是否允许私聊触发插件。上游私聊默认无需唤醒前缀即可命中指令。
ASTRBOT_COMPAT_ALLOW_PRIVATE = _env("ASTRBOT_COMPAT_ALLOW_PRIVATE", "true").lower() in (
    "true",
    "1",
    "yes",
)

# ---------- HTML → 图片渲染（插件卡片） ----------
# 大量 AstrBot 插件把结果卡片做成 Jinja2 模板 + CSS，靠 Star.html_render 出图。
# 后端是**本地 Chromium**（playwright）：模板里填的是群友昵称、动态正文、头像 URL，
# 属于聊天内容；上游默认把 HTML 发到远程 t2i 服务，Stella 不走那条路——其他环节
# （对话模型、embedding、整合）全在本地，渲染没理由成为唯一出网的一环。
# 实现见 astrbot_compat/render.py。
RENDER_ENABLED = _env("RENDER_ENABLED", "true").lower() in ("true", "1", "yes")
# 浏览器缺失时是否自动后台下载浏览器内核（headless shell，约 270MB，几分钟）。
# 下载期间照常降级（插件回纯文本），装好后自动生效、不需要重启。
# 关掉它就得手工跑：<python> -m playwright install chromium-headless-shell
RENDER_AUTO_INSTALL = _env("RENDER_AUTO_INSTALL", "true").lower() in ("true", "1", "yes")
# 自动安装失败后多久才再试（秒）。必须有冷却——否则每条带链接的消息都会重新拉一次几百 MB。
RENDER_INSTALL_RETRY_SECONDS = _env_float("RENDER_INSTALL_RETRY_SECONDS", 3600.0)
# 渲染产物目录。**不放 LOG_DIR**：这是要发出去的图片，不是日志。
RENDER_CACHE_DIR = _env_path("RENDER_CACHE_DIR", _user_path("data/render_cache"))
# 保留最近多少张渲染产物。每张几百 KB，不清理会无声涨到几个 G。
RENDER_CACHE_KEEP = _env_int("RENDER_CACHE_KEEP", 50)
# 同时最多渲染几张。每个页面都是一份 Chromium 渲染进程的内存开销，
# 而卡片渲染挂在聊天主链路上，并发高了不会更快，只会一起变慢。
RENDER_MAX_CONCURRENCY = _env_int("RENDER_MAX_CONCURRENCY", 2)
# 页面 load 完之后再等多少毫秒截图。给 Web 字体与 CSS 动画留出稳定时间——
# 少了它偶发会截到字体回退（方框字）或渐变未完成的中间态。
RENDER_SETTLE_MS = _env_int("RENDER_SETTLE_MS", 300)
# text_to_image / t2i 的图片宽度（像素）
RENDER_TEXT_WIDTH = _env_int("RENDER_TEXT_WIDTH", 800)

# ---------- AstrBot 插件的 LLM 服务 ----------
# 插件通过 context.get_using_provider_async() / event.request_llm() 调模型时走这里。
# 与 Stella 主聊天链路（core/llm/lm_studio.py）**共用同一个本地模型**，
# 但走独立的 OpenAI 兼容客户端（core/llm/openai_client.py），因为插件需要
# messages 数组 / function calling / 图片，而主链路的 generate() 表达不了这些。
# 插件调用经 core.llm.scheduler 上 PLUGIN 角色所属端点槽的那道闸门排队；
# 纯本地默认（PLUGIN 在 LOCAL 槽）下与主对话 FIFO 串行，改绑到在线槽后这道串行消失。
ASTRBOT_LLM_ENABLED = _env("ASTRBOT_LLM_ENABLED", "true").lower() in ("true", "1", "yes")
ASTRBOT_LLM_BASE_URL = _env_inherit("ASTRBOT_LLM_BASE_URL", LM_STUDIO_BASE_URL)
ASTRBOT_LLM_MODEL = _env_inherit("ASTRBOT_LLM_MODEL", LM_STUDIO_MODEL)
ASTRBOT_LLM_API_KEY = _env_inherit("ASTRBOT_LLM_API_KEY", LM_STUDIO_API_KEY)
ASTRBOT_LLM_TEMPERATURE = _env_float("ASTRBOT_LLM_TEMPERATURE", 0.7)
# 插件专属人格：插件没给 system_prompt 时注入这一句。
# 刻意不用 Stella 的人格——插件的回复不该带 Stella 的语气，否则用户分不清是谁在说话；
# 但完全不给 system 消息又会让本地模型的输出风格漂移，所以给一句最小的锚。
# 设为空串则彻底不发 system 消息。
ASTRBOT_LLM_SYSTEM_PROMPT = _env(
    "ASTRBOT_LLM_SYSTEM_PROMPT",
    "你是一个简单的机器人助手，请直接、简短地回答，不要扮演角色。",
)
# 单次回复的生成预算
ASTRBOT_LLM_MAX_TOKENS = _env_int("ASTRBOT_LLM_MAX_TOKENS", 1024)
# 送出前的上下文预算（估算值）。超出时从最早的非 system 消息开始丢弃。
# 本地 8192 窗口的模型请保持默认；换更大窗口的模型时调大这里。
ASTRBOT_LLM_MAX_CONTEXT_TOKENS = _env_int("ASTRBOT_LLM_MAX_CONTEXT_TOKENS", 8192)
# 单次请求最多携带多少个函数工具。每个工具的 JSON schema 约 60~120 token，
# 装满插件时这一项很容易吃掉上下文，超出即截断并告警。
ASTRBOT_LLM_MAX_TOOLS = _env_int("ASTRBOT_LLM_MAX_TOOLS", 32)
# 单个工具调用的超时（秒）
ASTRBOT_LLM_TOOL_TIMEOUT = _env_float("ASTRBOT_LLM_TOOL_TIMEOUT", 120.0)
# 工具调用循环的最大轮数，防止模型反复调用工具打转
ASTRBOT_LLM_MAX_TOOL_STEPS = _env_int("ASTRBOT_LLM_MAX_TOOL_STEPS", 10)

# ---------- LLM 端点（Endpoint） ----------
# 端点 = 一组连接参数：地址 + API key + 类型 + 并发度 + 超时。
# 它同时是**两样东西的归属单位**：
#   ① API key —— 不同 key 就是不同的前缀缓存域。对话域与记忆域各用一个 key，
#      两者的固定前缀才不会互相挤出缓存（这是「双 key」要求的落点）。
#   ② 闸门资源 —— core/llm/scheduler.py 按端点槽名建闸门，并发度即该端点的上限。
# 槽位数量**固定为 4**：deploy/env_schema.py 用 AST 扫本文件里字面量
# _env*("KEY", ...) 调用来生成 GUI，动态命名的端点在界面上根本不会出现。
# 需要第 5 个端点时在这里照抄 5 行——这是静态声明约束下的显式取舍。
#
# 「哪个角色用哪个端点、用什么模型」见下一节「LLM 角色」。
# embedding **不在**本体系内：它恒定本地，闸门归属见 MEMORY_EMBEDDING_GATE。

# 槽 LOCAL：本地 LM Studio。三个连接键默认继承旧的 LM_STUDIO_*，
# 因此未迁移的 .env 行为与改造前一致。
LLM_ENDPOINT_LOCAL_BASE_URL = _env_inherit("LLM_ENDPOINT_LOCAL_BASE_URL", LM_STUDIO_BASE_URL)
# 本地服务通常不校验 key；少数本地网关要求填 dummy key，那时填这里。
LLM_ENDPOINT_LOCAL_API_KEY = _env_inherit("LLM_ENDPOINT_LOCAL_API_KEY", LM_STUDIO_API_KEY)
# 端点级模型 ID：绑到本槽的角色自己没写 MODEL 时用它（解析顺序见 core/llm/registry
# 的 _resolve_role_model）。**本机槽留空即可**——留空时每个角色回落到自己的旧键
# （LM_STUDIO_MODEL / ASTRBOT_LLM_MODEL / MEMORY_EXTRACT_LM_STUDIO_MODEL 等），
# 那正是改造前的行为；填了这里就等于「本机槽统一用这一个模型」，会盖掉那些旧键。
LLM_ENDPOINT_LOCAL_MODEL = _env("LLM_ENDPOINT_LOCAL_MODEL", "")
# local | online。**显式声明，不再靠「有没有 api_key」猜**——那个启发式在两个
# 方向上都会错：本地网关要求 dummy key 时漏发 reasoning_effort=none（本地推理
# 模型会把 token 全耗在思维链上、content 为空），在线服务不要 key 时误发
# （有厂商直接 400）。厂商中立的代价就是不许猜。
LLM_ENDPOINT_LOCAL_KIND = _env("LLM_ENDPOINT_LOCAL_KIND", "local")
# 闸门并发度。本地=1：共享同一份模型权重，并发推理只会一起变慢。
LLM_ENDPOINT_LOCAL_CONCURRENCY = _env_int("LLM_ENDPOINT_LOCAL_CONCURRENCY", 1)
# 单次 HTTP 请求超时（秒）。这一项接管了 core/llm/lm_studio.py 里原先硬编码的
# 120 秒，**与 LLM_TIMEOUT 不是一回事**：后者是 core/pipeline.py 的整轮回复预算。
LLM_ENDPOINT_LOCAL_TIMEOUT = _env_float("LLM_ENDPOINT_LOCAL_TIMEOUT", 120.0)

# 槽 ONLINE_CHAT：在线·对话域。持有「对话生成」那把 key。
LLM_ENDPOINT_ONLINE_CHAT_BASE_URL = _env("LLM_ENDPOINT_ONLINE_CHAT_BASE_URL", "")
# 在线端点必须有 key（registry 启动校验会拦），且**不要与记忆域填同一个 key**：
# 同 key 会让两个域共享一个缓存空间、互相驱逐彼此的固定前缀。
LLM_ENDPOINT_ONLINE_CHAT_API_KEY = _env("LLM_ENDPOINT_ONLINE_CHAT_API_KEY", "")
# 在线槽的模型 ID **写在这里**，不必在每个角色上重复一遍：切到在线时，绑到本槽的
# 角色默认全用它。个别角色要用别的模型（例如兜底判定挑一个更便宜的），再单独写
# 那个角色的 LLM_ROLE_<角色>_MODEL 覆盖。
LLM_ENDPOINT_ONLINE_CHAT_MODEL = _env("LLM_ENDPOINT_ONLINE_CHAT_MODEL", "")
LLM_ENDPOINT_ONLINE_CHAT_KIND = _env("LLM_ENDPOINT_ONLINE_CHAT_KIND", "online")
# 在线端点并发度按厂商限流填。默认 4 是个保守值，不是厂商上限。
LLM_ENDPOINT_ONLINE_CHAT_CONCURRENCY = _env_int("LLM_ENDPOINT_ONLINE_CHAT_CONCURRENCY", 4)
LLM_ENDPOINT_ONLINE_CHAT_TIMEOUT = _env_float("LLM_ENDPOINT_ONLINE_CHAT_TIMEOUT", 120.0)

# 槽 ONLINE_MEMORY：在线·记忆域。持有「记忆整合」那把 key（整合 / 压缩 / 提取共用）。
LLM_ENDPOINT_ONLINE_MEMORY_BASE_URL = _env("LLM_ENDPOINT_ONLINE_MEMORY_BASE_URL", "")
LLM_ENDPOINT_ONLINE_MEMORY_API_KEY = _env("LLM_ENDPOINT_ONLINE_MEMORY_API_KEY", "")
LLM_ENDPOINT_ONLINE_MEMORY_MODEL = _env("LLM_ENDPOINT_ONLINE_MEMORY_MODEL", "")
LLM_ENDPOINT_ONLINE_MEMORY_KIND = _env("LLM_ENDPOINT_ONLINE_MEMORY_KIND", "online")
# 记忆域是后台任务，并发度比对话域低：它不该抢对话的限流额度。
LLM_ENDPOINT_ONLINE_MEMORY_CONCURRENCY = _env_int("LLM_ENDPOINT_ONLINE_MEMORY_CONCURRENCY", 2)
LLM_ENDPOINT_ONLINE_MEMORY_TIMEOUT = _env_float("LLM_ENDPOINT_ONLINE_MEMORY_TIMEOUT", 120.0)

# 槽 EXTRA：备用槽。**默认充当「本地记忆域」**——地址与 LOCAL 相同（继承旧的
# CONSOLIDATION_LM_STUDIO_*），但闸门独立，于是整合与聊天能真正并行。
# 这正是改造前 chat / consolidation 两把锁分离的原因（27B 跑 GPU、E4B 跑 CPU），
# 所以 LLM_ROLE_CONSOLIDATION_ENDPOINT 默认指向本槽而不是 LOCAL。
# 混合部署或调试时也可把它指向第三个服务。
LLM_ENDPOINT_EXTRA_BASE_URL = _env_inherit("LLM_ENDPOINT_EXTRA_BASE_URL", CONSOLIDATION_LM_STUDIO_BASE_URL)
LLM_ENDPOINT_EXTRA_API_KEY = _env_inherit("LLM_ENDPOINT_EXTRA_API_KEY", CONSOLIDATION_LM_STUDIO_API_KEY)
# 留空即可：CONSOLIDATION 角色回落到 CONSOLIDATION_LM_STUDIO_MODEL（GUI 里的
# 「记忆整合模型 ID」），与改造前一致。指向第三个服务时才需要填这里。
LLM_ENDPOINT_EXTRA_MODEL = _env("LLM_ENDPOINT_EXTRA_MODEL", "")
LLM_ENDPOINT_EXTRA_KIND = _env("LLM_ENDPOINT_EXTRA_KIND", "local")
LLM_ENDPOINT_EXTRA_CONCURRENCY = _env_int("LLM_ENDPOINT_EXTRA_CONCURRENCY", 1)
LLM_ENDPOINT_EXTRA_TIMEOUT = _env_float("LLM_ENDPOINT_EXTRA_TIMEOUT", 120.0)

# ---------- LLM 角色（Role） ----------
# 角色 = 一个调用场景。每个角色引用一个端点槽，并带自己的模型 / 温度 / max_tokens。
# ENDPOINT 取 LOCAL | ONLINE_CHAT | ONLINE_MEMORY | EXTRA | none；
# none = 停用该角色，所有调用点必须优雅退化而不是抛异常（沿用
# capability/router/fallback.py 里「构造失败返回 None 即降级」的惯例）。
#
# 六个角色的默认值都对齐改造前的实际行为，所以**未迁移的 .env 逐项等价今天**：
# CHAT/ROUTER/PLUGIN/COMPACT/EXTRACT 在 LOCAL 槽（= 改造前的 chat 闸门），
# CONSOLIDATION 在 EXTRA 槽（= 改造前的 consolidation 闸门）。
# 模型 / 温度 / max_tokens 则继承各自原来的旧键；没有旧键的（CHAT/ROUTER/COMPACT）
# 写死成改造前 LMStudioBackend 的构造默认值。
#
# **MODEL 通常不用填**：模型 ID 的正常出处是端点槽的 LLM_ENDPOINT_<槽>_MODEL
# （GUI 的端点卡片就是它），这里只是**角色级覆盖**，给「同一个端点上，某个角色要用
# 另一个模型」的场景（例如兜底判定挑一个更便宜的）。完整解析顺序见
# core/llm/registry.py 的 _resolve_role_model：
#   角色显式 MODEL → 该角色所绑端点的 MODEL → 角色自己的旧键（下面每行标出的那个）。
# 「显式」的判据是「值与它继承的旧键不同」——只写了旧键的存量 .env 因此仍走第三档，
# 与改造前逐字等价；而把角色切到在线槽时，本机模型名不会被误带到在线服务商去。
#
# FALLBACK_ENDPOINT 留空 = 不降级。降级只在鉴权失败 / 限流 / 5xx 重试耗尽 /
# 连接超时时触发；400（请求体错误）**不降级**——那是配置问题，降级只会掩盖它。

# 主对话生成。改造前：ai_gateway.py 用 LM_STUDIO_* 构造，温度/长度取构造默认值。
LLM_ROLE_CHAT_ENDPOINT = _env("LLM_ROLE_CHAT_ENDPOINT", "LOCAL")
LLM_ROLE_CHAT_MODEL = _env_inherit("LLM_ROLE_CHAT_MODEL", LM_STUDIO_MODEL)
LLM_ROLE_CHAT_TEMPERATURE = _env_float("LLM_ROLE_CHAT_TEMPERATURE", 0.7)
LLM_ROLE_CHAT_MAX_TOKENS = _env_int("LLM_ROLE_CHAT_MAX_TOKENS", 2000)
LLM_ROLE_CHAT_FALLBACK_ENDPOINT = _env("LLM_ROLE_CHAT_FALLBACK_ENDPOINT", "")

# Router Level 2 兜底判定。任务是「要不要工具」的二分类，在线时可用廉价模型。
LLM_ROLE_ROUTER_ENDPOINT = _env("LLM_ROLE_ROUTER_ENDPOINT", "LOCAL")
LLM_ROLE_ROUTER_MODEL = _env_inherit("LLM_ROLE_ROUTER_MODEL", LM_STUDIO_MODEL)
LLM_ROLE_ROUTER_TEMPERATURE = _env_float("LLM_ROLE_ROUTER_TEMPERATURE", 0.7)
LLM_ROLE_ROUTER_MAX_TOKENS = _env_int("LLM_ROLE_ROUTER_MAX_TOKENS", 2000)
LLM_ROLE_ROUTER_FALLBACK_ENDPOINT = _env("LLM_ROLE_ROUTER_FALLBACK_ENDPOINT", "")

# AstrBot 插件的 LLM 调用（messages 数组 / function calling / 图片）。
# 走 core/llm/openai_client.py，不是 LMStudioBackend。
LLM_ROLE_PLUGIN_ENDPOINT = _env("LLM_ROLE_PLUGIN_ENDPOINT", "LOCAL")
LLM_ROLE_PLUGIN_MODEL = _env_inherit("LLM_ROLE_PLUGIN_MODEL", ASTRBOT_LLM_MODEL)
LLM_ROLE_PLUGIN_TEMPERATURE = _env_float_inherit("LLM_ROLE_PLUGIN_TEMPERATURE", ASTRBOT_LLM_TEMPERATURE)
LLM_ROLE_PLUGIN_MAX_TOKENS = _env_int_inherit("LLM_ROLE_PLUGIN_MAX_TOKENS", ASTRBOT_LLM_MAX_TOKENS)
LLM_ROLE_PLUGIN_FALLBACK_ENDPOINT = _env("LLM_ROLE_PLUGIN_FALLBACK_ENDPOINT", "")

# 会话压缩：把较早的对话压成回顾。**在线时归记忆域**（与整合共用同一把 key），
# 让记忆域的流量与对话域的缓存互不干扰。
LLM_ROLE_COMPACT_ENDPOINT = _env("LLM_ROLE_COMPACT_ENDPOINT", "LOCAL")
LLM_ROLE_COMPACT_MODEL = _env_inherit("LLM_ROLE_COMPACT_MODEL", LM_STUDIO_MODEL)
LLM_ROLE_COMPACT_TEMPERATURE = _env_float("LLM_ROLE_COMPACT_TEMPERATURE", 0.3)
# **0 = 按 SESSION_SUMMARY_MAX_TOKENS × 3 推导**（改造前 session_compact.py 的算法）。
# 不写死数值，是为了让调大摘要长度的用户不必同时改这里。
LLM_ROLE_COMPACT_MAX_TOKENS = _env_int("LLM_ROLE_COMPACT_MAX_TOKENS", 0)
LLM_ROLE_COMPACT_FALLBACK_ENDPOINT = _env("LLM_ROLE_COMPACT_FALLBACK_ENDPOINT", "")

# 记忆整合 阶段1：出短期摘要 + 用户画像 + 自我披露判断。是「总结 + 二分类」任务，
# 在线时用廉价模型即可。默认端点是 EXTRA 而非 LOCAL，理由见 EXTRA 槽的说明。
LLM_ROLE_CONSOLIDATION_ENDPOINT = _env("LLM_ROLE_CONSOLIDATION_ENDPOINT", "EXTRA")
LLM_ROLE_CONSOLIDATION_MODEL = _env_inherit("LLM_ROLE_CONSOLIDATION_MODEL", CONSOLIDATION_LM_STUDIO_MODEL)
LLM_ROLE_CONSOLIDATION_TEMPERATURE = _env_float_inherit("LLM_ROLE_CONSOLIDATION_TEMPERATURE", CONSOLIDATION_LM_STUDIO_TEMPERATURE)
LLM_ROLE_CONSOLIDATION_MAX_TOKENS = _env_int_inherit("LLM_ROLE_CONSOLIDATION_MAX_TOKENS", CONSOLIDATION_LOCAL_MAX_TOKENS)
LLM_ROLE_CONSOLIDATION_FALLBACK_ENDPOINT = _env("LLM_ROLE_CONSOLIDATION_FALLBACK_ENDPOINT", "")

# 记忆整合 阶段2：从消息里精确提取「用户亲口说的、关于自己的稳定信息」。
# 高精度抽取任务，但只在阶段1 判定 has_self_disclosure=true 时才唤醒，频次低。
LLM_ROLE_EXTRACT_ENDPOINT = _env("LLM_ROLE_EXTRACT_ENDPOINT", "LOCAL")
LLM_ROLE_EXTRACT_MODEL = _env_inherit("LLM_ROLE_EXTRACT_MODEL", MEMORY_EXTRACT_LM_STUDIO_MODEL)
LLM_ROLE_EXTRACT_TEMPERATURE = _env_float_inherit("LLM_ROLE_EXTRACT_TEMPERATURE", MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE)
LLM_ROLE_EXTRACT_MAX_TOKENS = _env_int_inherit("LLM_ROLE_EXTRACT_MAX_TOKENS", MEMORY_EXTRACT_MAX_TOKENS)
LLM_ROLE_EXTRACT_FALLBACK_ENDPOINT = _env("LLM_ROLE_EXTRACT_FALLBACK_ENDPOINT", "")

# 降级总开关。关掉后主端点失败就是失败（各调用点自行退化），不会切到备用端点。
LLM_FALLBACK_ENABLED = _env("LLM_FALLBACK_ENABLED", "true").lower() in ("true", "1", "yes")
# 降级后多少秒再试探性回归主端点。太短会在厂商限流期间反复撞墙，
# 太长则厂商恢复了还在用备用端点。
LLM_FALLBACK_COOLDOWN = _env_int("LLM_FALLBACK_COOLDOWN", 300)


# ---------- LLM 成本控制（用量记账与预算） ----------
# 在线端点按 token 计费，而记忆域（整合 / 压缩 / 提取）是高频后台任务：不记账就不知道
# 钱花在哪，没有预算就没有上限。用量按「日期 × 角色 × 端点槽 × 模型」累加进
# llm_usage_daily 表，日期键取**本地时区**——用日期而不是计时器，进程重启当天的累计
# 不清零（否则「每日预算」会变成「每次启动后 24 小时」）。日账保留 90 天后自动清理，
# 这个天数写死不给配置项：一天最多几十行，没有需要用户调的理由。
#
# 用量与缓存命中率在 GUI 的「运行状态」页可见。**缓存命中率是验证前缀缓存是否真的
# 生效的唯一手段**，分母是输入 token 而不是调用次数。

# 是否把 LLM 用量落库。关掉则完全不挂记账钩子、一次也不碰数据库——
# 代价是**预算随之失效**（没有用量数据，预算无从判断），GUI 用量面板同时留白。
LLM_USAGE_ACCOUNTING = _env("LLM_USAGE_ACCOUNTING", "true").lower() in ("true", "1", "yes")
# 每日 token 预算（输入 + 输出之和）。**0 = 不限**。
# 撞破之后做什么由 LLM_BUDGET_EXHAUSTED_ACTION 决定，默认只停记忆域、对话照常。
LLM_DAILY_TOKEN_BUDGET = _env_int("LLM_DAILY_TOKEN_BUDGET", 0)
# 预算算哪些端点的用量：online = 只算在线端点（默认，本地模型不花钱）；all = 全算。
# 纯本地部署设成 all 才有意义——那时它是「算力预算」而不是账单预算。
LLM_BUDGET_SCOPE = _env("LLM_BUDGET_SCOPE", "online").strip().lower()
# 撞破预算之后做什么：
#   pause_memory（默认）= 只停记忆域三个角色（整合 / 压缩 / 提取），对话照常可用；
#   pause_all           = 连对话一起停，被拦下的消息**静默不回**（只写 warn 日志，
#                         不发提示句、也不回落到本地端点——回落会让「全停」名不副实，
#                         而纯在线部署本来就没有本地端点可落）；
#   warn_only           = 只在日志里告警一次，从不拦任何调用。
# 认不出的值按最保守的 pause_memory 处理。
LLM_BUDGET_EXHAUSTED_ACTION = _env("LLM_BUDGET_EXHAUSTED_ACTION", "pause_memory").strip().lower()


# ---------- Capability Router（能力路由） ----------
# 判断一次请求需要哪些能力（聊天 / 记忆 / 工具），避免把所有插件工具的 schema
# 都塞进 Stella 的聊天上下文——8192 的工作窗口装不下几十个工具描述，且工具描述
# 会干扰正常聊天。设计见 design_docs/Capability Router 与 Comes 落地方案 v1.0.md。
CAPABILITY_ROUTER_ENABLED = _env("CAPABILITY_ROUTER_ENABLED", "true").lower() in ("true", "1", "yes")
# 自动派生的能力（``tool.<工具名>``，即没有被任何 config/capabilities/*.toml 认领的
# 插件工具）是否参与 Router 的能力竞争。**默认关闭：声明优先。**
#
# 依据是 2026-08-24 的首轮实测（design_docs/logs/log_2026_8_25_1303.md）。自动派生的
# 原型语料只有插件的工具描述，而工具描述是写给「看着全部工具做选择」的决策器的指令句
# （"当用户询问 X 时调用"），与用户的问句不同构；同一语域的几个工具因此几乎没有区分度。
# 实测（5 个 bilibili/bgm 工具，12 条用例，真实 embedding）：
#   自动派生：工具假阳 1、首位选错 2/5、无关工具被执行 13 次，
#             负样本阈值余量 -0.024（「这个游戏怎么样」拿到 0.474 > 0.45 直接触发工具）
#   显式声明：见 docs/capability-system.md 的对照表
# 工具假阳在 docs 的错误代价表里是**高**严重度（凭空调工具、可能改变外部状态、
# 且结果会被贴上「真实数据，回答时以此为准」送进 prompt）。
#
# 关闭后未声明的工具仍然照常注册（启动日志会点名），只是不参与语义路由；
# 要让它可被聊天触发，就给它写一份声明——那是几行 TOML 的一次性成本。
# 设为 true 可恢复「装上插件就能路由」的旧行为（零配置，代价是上面这些数）。
ROUTER_ROUTE_AUTO_CAPABILITIES = _env("ROUTER_ROUTE_AUTO_CAPABILITIES", "false").lower() in ("true", "1", "yes")
# Level 0：关键词规则快速判断。零延迟、不调模型，处理高置信度请求。
ROUTER_RULE_ENABLED = _env("ROUTER_RULE_ENABLED", "true").lower() in ("true", "1", "yes")
# Level 1：Embedding 语义路由。用消息与各能力原型向量的余弦相似度判定。
# 复用 MEMORY_EMBEDDING_* 的服务地址与模型（同一个本地 embedding 实例）。
ROUTER_SEMANTIC_ENABLED = _env("ROUTER_SEMANTIC_ENABLED", "true").lower() in ("true", "1", "yes")
# Level 2：更强模型兜底。默认**关闭**——方案第 8 节明确要求避免浪费 27B 推理资源，
# 先靠 L0/L1 跑一段时间、用 router benchmark 量出准确率再决定是否打开。
ROUTER_FALLBACK_ENABLED = _env("ROUTER_FALLBACK_ENABLED", "false").lower() in ("true", "1", "yes")
# ---- 下面四个阈值是一组，2026-08-25 用真实 embedding（qwen3-embedding-0.6b）在 12 条
# ---- 用例上标定，前提是**能力带中文 examples**（即 ROUTER_ROUTE_AUTO_CAPABILITIES=false）。
# ---- 复现：python -m capability.router.benchmark --cases capability/router/benchmark/acg.json
# ----
# ---- ⚠️ 与 ROUTER_ROUTE_AUTO_CAPABILITIES 强耦合。自动派生能力（原型语料是英文/指令句式
# ---- 的工具描述）的打分整体比带 examples 的能力低约 0.2，实测正样本只到 0.61~0.71。
# ---- 若把它设成 true 又不同时下调这里的阈值，工具会**静默地永远不触发**。
#
# 语义路由命中某能力的最低余弦相似度（能力进入候选列表的绝对地板）。
# 实测：带 examples 时负样本最高 0.559、正样本最低 0.851，真正起作用的是下面的
# ROUTER_CAPABILITY_MARGIN，本项只用来压掉日志里的长尾噪声。
ROUTER_SEMANTIC_THRESHOLD = _env_float("ROUTER_SEMANTIC_THRESHOLD", 0.50)
# 判定 tool=true 所需的最高分置信线。低于它但高于 ROUTER_UNCERTAIN_FLOOR 的落入
# 「不确定带」，只有此时才考虑 Level 2。
# 0.70 取自实测两个分布的中点（负样本上界 0.559 / 正样本下界 0.851），两侧余量
# +0.141 / +0.151，基本对称。样本里只有 1 条是线上真实用户消息，其余是构造的，
# 所以没有按「工具假阳代价更高」进一步上调——上调会先牺牲真实用户的召回。
ROUTER_TOOL_THRESHOLD = _env_float("ROUTER_TOOL_THRESHOLD", 0.70)
# 命中能力允许比最高分低多少（相对间距裁剪）。0 表示不裁剪。
#
# 这一项治的是首轮实测里最实在的问题：一旦 tool=true，所有过了绝对地板的能力都会
# **各自执行一次**，于是「帮我推荐一些新番」同时调了每日放送和 B 站热门视频，
# 无关结果被贴上「真实数据，回答时以此为准」送进 prompt。
# 绝对地板解决不了它：实测正确能力的分数是 0.851~0.911，而搭车能力是 0.616~0.743，
# 后者高于任何一个能用的地板值（地板要低于 0.851 才不误杀正样本）。
# 只有相对间距能把两者分开——正确能力与第二名的实测落差是 0.155~0.336。
# 0.12 落在 0.08~0.15 这个平台的中间（该区间内搭车数恒为 0，0.20 起开始漏进搭车）。
ROUTER_CAPABILITY_MARGIN = _env_float("ROUTER_CAPABILITY_MARGIN", 0.12)
# 不确定带下界：最高分低于它就是「确定不需要工具」，不进 Level 2。
# 0.55 紧贴实测负样本上界（0.559），于是不确定带 = 0.55~0.70，只覆盖真正含混的那一小段
# （首轮实测里「主管，这是？」的 0.559 正好落在这儿）。Level 2 默认关闭，本项暂无实际效果，
# 但必须跟着上面一起标定，否则将来打开 L2 会发现它对几乎所有消息都开火。
ROUTER_UNCERTAIN_FLOOR = _env_float("ROUTER_UNCERTAIN_FLOOR", 0.55)
# 单次请求最多路由几个能力。每个能力在 Comes 里是一次独立的受限 agent 调用，
# 都排 PLUGIN 角色那道闸门（纯本地默认与聊天同一道），不设上限会让一条消息卡住整个群的回复。
ROUTER_MAX_CAPABILITIES = _env_int("ROUTER_MAX_CAPABILITIES", 3)
# 是否真的按 route.memory 门控长期记忆检索。
# **默认关闭**：Router 误判 memory=false 会让 Stella 当轮悄悄丢失长期记忆——不抛异常、
# 不影响回复，只是「它突然不记得你了」，与 2026-08-17 那次 AT_MENTION 全为 0 的缺陷
# 同一类型（静默、难察觉、后果严重）。先用 router benchmark 量出准确率再打开。
ROUTER_GATE_MEMORY = _env("ROUTER_GATE_MEMORY", "false").lower() in ("true", "1", "yes")
# 单次路由判定的超时（秒）。超时按降级处理（chat+memory，不调工具），不阻塞回复。
ROUTER_TIMEOUT = _env_float("ROUTER_TIMEOUT", 8.0)

# ---------- Comes（工具执行层） ----------
# Comes 只负责「能力 → 找 Provider → 调 Tool → 返回 Result」，不理解用户、不管人格。
# 它用一个**受限 agent**驱动工具：请求里只有 COMES_SYSTEM_PROMPT + 任务目标 +
# 本次命中能力的 1~3 个工具 schema，既没有 Stella 的人格也没有聊天上下文。
COMES_ENABLED = _env("COMES_ENABLED", "true").lower() in ("true", "1", "yes")
# Comes 的执行器人格。刻意不用 Stella 的人格（与 ASTRBOT_LLM_SYSTEM_PROMPT 同一考量）：
# 它的输出只是给 Stella 看的中间结果，不该带语气。
COMES_SYSTEM_PROMPT = _env(
    "COMES_SYSTEM_PROMPT",
    "你是一个工具执行器。根据给定的任务目标，选择合适的工具并填好参数。"
    "只调用工具，不要闲聊，不要扮演角色。拿到工具结果后用一句中文陈述事实即可。",
)
# 单个任务的工具调用最大轮数。比 ASTRBOT_LLM_MAX_TOOL_STEPS(10) 小：
# Comes 的任务是单一能力的定向执行，需要 5 轮以上通常意味着模型在打转。
COMES_MAX_TOOL_STEPS = _env_int("COMES_MAX_TOOL_STEPS", 5)
# 单个工具调用的超时（秒）。比 ASTRBOT_LLM_TOOL_TIMEOUT(120) 短得多——
# Comes 挂在聊天主链路上，用户在等回复，不能为一个工具等两分钟。
COMES_TOOL_TIMEOUT = _env_float("COMES_TOOL_TIMEOUT", 60.0)
# 单个任务的总超时（秒），含模型往返与工具执行。超时按 failed 处理并照常回复。
COMES_TASK_TIMEOUT = _env_float("COMES_TASK_TIMEOUT", 90.0)
# 进 Stella prompt 的结果摘要长度上限（字符）。Result.data 全程不进 prompt，
# 只有 summary 进——工具结果同样不该污染聊天上下文。
COMES_SUMMARY_MAX_CHARS = _env_int("COMES_SUMMARY_MAX_CHARS", 300)
# 命中能力只有一个 provider、且其工具没有必填参数时，跳过 LLM 直接调工具。
# 省一次 27B 往返，且不可能填错参数。
COMES_DIRECT_CALL_NO_ARGS = _env("COMES_DIRECT_CALL_NO_ARGS", "true").lower() in ("true", "1", "yes")
# 连续失败多少次后临时禁用一个 provider（健康度退避）。0 表示不退避。
COMES_PROVIDER_FAILURE_THRESHOLD = _env_int("COMES_PROVIDER_FAILURE_THRESHOLD", 3)
# 被退避的 provider 多久后恢复（秒）。
COMES_PROVIDER_RECOVER_SECONDS = _env_float("COMES_PROVIDER_RECOVER_SECONDS", 600.0)
