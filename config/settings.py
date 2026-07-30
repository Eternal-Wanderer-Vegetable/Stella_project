from pathlib import Path

# ============================================================
# Stella Project — 集中配置
# 修改此文件即可调整所有运行时参数，无需改动业务代码。
# ============================================================

# ---------- 项目路径（自动校准） ----------
_CURRENT_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _CURRENT_FILE.parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT:
    if (_PROJECT_ROOT / "core").is_dir() or (_PROJECT_ROOT / "pi_agent_core").is_dir():
        break
    _PROJECT_ROOT = _PROJECT_ROOT.parent
PROJECT_ROOT = _PROJECT_ROOT

# ---------- 目录与文件路径 ----------
SYSTEM_PROMPT_PATH = PROJECT_ROOT / "pi_agent_core" / "SYSTEM.md"
DB_PATH = PROJECT_ROOT / "pi_agent_core" / "agent_memory.db"
THOUGHT_LOG_PATH = PROJECT_ROOT / "stella_thought_logs.md"
EXTENSIONS_DIR = PROJECT_ROOT / "extensions"

# ---------- QQ 群聊 ----------
ALLOWED_GROUPS = {263402786}

# ---------- 上下文 ----------
RECENT_MESSAGE_LIMIT = 3

# ---------- 本地 LLM（LM Studio） ----------
LM_STUDIO_BASE_URL = "http://127.0.0.1:1234"
LM_STUDIO_MODEL = ""

# LLM 调用超时（秒）
LLM_TIMEOUT = 90.0

# ---------- 在线 LLM（FlexiWeb） ----------
FLEXIWEB_BASE_URL = "http://127.0.0.1:8000"
CONSOLIDATION_SITE = "deepseek"

# ---------- 记忆整合 ----------
# 处理多少条新消息触发一次整合
CONSOLIDATION_BATCH_SIZE = 100
# 每次整合时向前回看多少条用于话题连续
CONSOLIDATION_OVERLAP = 15

# ---------- 输出 ----------
MAX_REPLY_LINES = 5
SEND_INTERVAL = 0.8

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
