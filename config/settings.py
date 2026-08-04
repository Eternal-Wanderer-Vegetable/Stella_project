from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ============================================================
# Stella Project — 集中配置
# 修改此文件即可调整所有运行时参数，无需改动业务代码。
# ============================================================

# ---------- 项目路径（自动校准） ----------
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
    """读取环境变量，优先级高于默认值。"""
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    """安全读取 int 环境变量，解析失败时返回默认值。"""
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
    """安全读取 float 环境变量，解析失败时返回默认值。"""
    raw = os.getenv(key, "")
    if not raw:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        from nonebot import logger
        logger.warning(f"⚠️ 配置项 {key}={raw!r} 不是有效浮点数，使用默认值 {default}")
        return default

# ---------- 项目路径（自动校准） ----------
_CURRENT_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _CURRENT_FILE.parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT:
    if (_PROJECT_ROOT / "core").is_dir():
        break
    _PROJECT_ROOT = _PROJECT_ROOT.parent
PROJECT_ROOT = _PROJECT_ROOT

# ---------- 目录与文件路径 ----------
SYSTEM_PROMPT_PATH = PROJECT_ROOT / "memory" / "SYSTEM.md"
DB_PATH = PROJECT_ROOT / "memory" / "agent_memory.db"
THOUGHT_LOG_PATH = PROJECT_ROOT / "stella_thought_logs.md"
EXTENSIONS_DIR = PROJECT_ROOT / "extensions"

# ---------- QQ 群聊 ----------
ALLOWED_GROUPS = {int(x) for x in _env("ALLOWED_GROUPS", "263402786").split(",") if x.strip()}

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

# ---------- 本地 LLM（LM Studio） ----------
LM_STUDIO_BASE_URL = _env("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234")
LM_STUDIO_MODEL = _env("LM_STUDIO_MODEL", "")

# LLM 调用超时（秒）
LLM_TIMEOUT = _env_float("LLM_TIMEOUT", 90.0)

# ---------- 在线 LLM（FlexiWeb） ----------
FLEXIWEB_BASE_URL = _env("FLEXIWEB_BASE_URL", "http://127.0.0.1:8000")
CONSOLIDATION_SITE = _env("CONSOLIDATION_SITE", "deepseek")

# FlexiWeb 项目路径（用于自动拉起子进程）
FLEXIWEB_PROJECT_DIR = _env("FLEXIWEB_PROJECT_DIR", str(PROJECT_ROOT.parent / "FlexiWeb_Stream_Scraper"))

# FlexiWeb 启动模式：
#   True  = 无头模式（不显示浏览器窗口，生产环境使用）
#   False = 有头模式（显示浏览器窗口，调试用）
# ⚠️ 首次使用：FlexiWeb 无登录数据，无头模式会卡在 DeepSeek 登录页。
#    请设为 False 启动，手动登录一次 DeepSeek（会话保存在 browser_user_data），
#    之后再改回 True 即可无头运行。
FLEXIWEB_HEADLESS = _env("FLEXIWEB_HEADLESS", "false").lower() in ("true", "1", "yes")

# ---------- 记忆整合 ----------
# LLM 优先级链，按顺序尝试，前一个失败自动降级到下一个。
#   "flexiweb"  = 在线 LLM（Playwright 抓取 DeepSeek 网页，总结能力强）
#   "lm_studio" = 本地 SLM（HTTP API，稳定快速，作为兜底）
CONSOLIDATION_LLM_PRIORITY = [s.strip() for s in _env("CONSOLIDATION_LLM_PRIORITY", "flexiweb,lm_studio").split(",") if s.strip()]

# 在线 LLM 失败后的冷却时间（秒），避免频繁重试拖慢整合
CONSOLIDATION_ONLINE_COOLDOWN = _env_int("CONSOLIDATION_ONLINE_COOLDOWN", 300)

# 在线 LLM（FlexiWeb/DeepSeek）的整合批量：
# 批量太小会导致调用过于频繁，容易触发网站风控；批量大才能发挥大模型总结优势。
# 注意：该批量会拼成较大的 prompt，只适合上下文窗口大的在线模型。
CONSOLIDATION_BATCH_SIZE = _env_int("CONSOLIDATION_BATCH_SIZE", 100)
# 每次整合时向前回看多少条用于话题连续
CONSOLIDATION_OVERLAP = _env_int("CONSOLIDATION_OVERLAP", 15)
# 在线 LLM 最大生成 token 数
CONSOLIDATION_MAX_TOKENS = _env_int("CONSOLIDATION_MAX_TOKENS", 2000)

# 本地 SLM（LM Studio）兜底时的整合批量：
# 本地小模型上下文窗口小（如 gemma-4-e4b），批次必须缩小，否则触发 400 Context exceeded
CONSOLIDATION_LOCAL_BATCH_SIZE = _env_int("CONSOLIDATION_LOCAL_BATCH_SIZE", 10)
# 本地 SLM 最大生成 token 数
CONSOLIDATION_LOCAL_MAX_TOKENS = _env_int("CONSOLIDATION_LOCAL_MAX_TOKENS", 800)

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
# 平均消息间隔 >= 此值（秒）视为低频（冷清群），主动发言概率高
PROACTIVE_LOW_FREQ_INTERVAL = _env_float("PROACTIVE_LOW_FREQ_INTERVAL", 180.0)
# 低频时的最大主动发言概率（0~1），高频时的最小概率（不可为 0）
PROACTIVE_MAX_PROB = _env_float("PROACTIVE_MAX_PROB", 0.5)
PROACTIVE_MIN_PROB = _env_float("PROACTIVE_MIN_PROB", 0.05)
# 主动发言前若累计新消息达到该数量，则触发一次短期记忆总结
CONSOLIDATION_TRIGGER_NEW_MESSAGES = _env_int("CONSOLIDATION_TRIGGER_NEW_MESSAGES", 10)

# ---------- 数据库清理（测试期用） ----------
# 程序启动时自动清理混乱的记忆数据（测试阶段频繁重启注入的脏数据）
#   True = 每次启动都清理短期/长期记忆并重置整合 checkpoint（用户画像保留）
#   测试结束后请改回 False，否则每次重启都会丢失记忆
DB_CLEANUP_ON_START = _env("DB_CLEANUP_ON_START", "false").lower() in ("true", "1", "yes")
# 清理时是否连原始群消息记录也一起删除（危险操作，默认关闭）
DB_CLEANUP_CLEAR_MESSAGES = _env("DB_CLEANUP_CLEAR_MESSAGES", "false").lower() in ("true", "1", "yes")

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

# ---------- NapCat 看门狗 ----------
NAPCAT_TOKEN = _env("NAPCAT_TOKEN", "")
NAPCAT_API_URL = _env("NAPCAT_API_URL", "http://127.0.0.1:6099/api/Process/Restart")

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
