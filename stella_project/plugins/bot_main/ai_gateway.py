import asyncio
import os
import sys
import re
from pathlib import Path
from datetime import datetime
from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.exception import FinishedException
from nonebot.rule import Rule

# --- 1. 路径自动校准 ---
CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parent
while PROJECT_ROOT.parent != PROJECT_ROOT:
    if (PROJECT_ROOT / "pi_agent_core").is_dir():
        break
    PROJECT_ROOT = PROJECT_ROOT.parent

PI_AGENT_DIR = str(PROJECT_ROOT / "pi_agent_core")
SYSTEM_PROMPT_PATH = str(PROJECT_ROOT / "pi_agent_core" / "SYSTEM.md")

# 💡 指定 Markdown 思考日志文件的保存路径
THOUGHT_LOG_PATH = PROJECT_ROOT / "stella_thought_logs.md"

# --- 2. 建立全局并发锁（并发控制）---
model_lock = asyncio.Lock()


async def append_thought_to_markdown(user_id: int, user_msg: str, thought: str, action: str, reply_lines: list):
    """异步将 AI 的思考过程追加写入指定 md 文件"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reply_str = " <br> ".join(reply_lines)
    
    # 构造 Markdown 日志记录条目
    log_entry = f"""### 🕒 [{now_str}] 用户: `{user_id}`
- **📥 用户输入**: {user_msg}
- **🧠 内部思考**: 
  > {thought.replace('/n', '/n  > ')}
- **⚙️ 判定动作**: `{action}`
- **💬 最终台词**: {reply_str}

---
"""
    try:
        # 如果文件不存在，先创建文件并写入标题
        if not THOUGHT_LOG_PATH.exists():
            THOUGHT_LOG_PATH.write_text("# 🤖 Stella 思考过程与决策日志\n\n", encoding="utf-8")

        # 追加写入
        with open(THOUGHT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(log_entry)
            
    except Exception as e:
        logger.error(f"❌ [Log System] 追加 Markdown 日志失败: {e}")


def parse_model_output(raw_text: str):
    """
    极强容错的 XML 提取器：
    即便模型被 Token 截断未闭合标签，也能正常提取。
    返回 (thought, action, reply)
    """
    thought = "（无思考过程）"
    action = "NONE"
    reply = ""

    # 1. 提取 <thought>（支持未闭合情况）
    thought_match = re.search(r'<thought>(.*?)(?:</thought>|<action>|<reply>|$)', raw_text, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    # 2. 提取 <action>（支持未闭合情况）
    action_match = re.search(r'<action>(.*?)(?:</action>|<reply>|$)', raw_text, re.DOTALL)
    if action_match:
        action = action_match.group(1).strip()

    # 3. 提取 <reply>（容错核心：匹配到 </reply> 或文本末尾）
    reply_match = re.search(r'<reply>(.*?)(?:</reply>|$)', raw_text, re.DOTALL)
    if reply_match:
        reply = reply_match.group(1).strip()

    # 4. 极致兜底：如果模型完全没写 <reply> 标签，将剔除标签后的文本直接作为 reply
    if not reply:
        clean_text = re.sub(r'<[^>]+>.*?(?:</[^>]+>|$)', '', raw_text, flags=re.DOTALL).strip()
        if clean_text:
            reply = clean_text

    return thought, action, reply


async def call_pi_agent(prompt: str) -> str:
    """拉起 PI Agent CLI 子进程"""
    if not os.path.isdir(PI_AGENT_DIR):
        raise FileNotFoundError(f"PI Agent 目录无效: {PI_AGENT_DIR}")

    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"

    cmd = [
        npx_cmd, "pi",
        "-p", prompt,
        "--provider", "lm-studio",
        "--model", "stella-local",
        "--system-prompt", SYSTEM_PROMPT_PATH,
        "--tools", "",  # 👈 1. 禁用 pi 内置的 bash/read/write/edit 默认工具包
        # "--extension", str(PROJECT_ROOT / "pi_agent_core" / "extensions" / "online_llm.ts")  # 👈 2. 以后有自定义扩展时加这一行即可
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=PI_AGENT_DIR
    )

    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"❌ [PI Agent Error]: {stderr.decode('utf-8', errors='ignore')}")
        raise RuntimeError("PI Agent 引擎运行异常")

    reply = stdout.decode("utf-8", errors="ignore").strip()

    # 破防/出戏/硬编码身份拦截
    bad_words = ["作为", "AI", "模型", "助手", "语言模型", "Gemma", "QQ用户", "qq用户"]
    if any(w in reply for w in bad_words):
        reply = "<thought>破防兜底</thought><action>NONE</action><reply>……？你在说什么奇怪的话呢。</reply>"

    return reply


async def is_chat_trigger(event: GroupMessageEvent) -> bool:
    if not event.is_tome():
        return False
    user_msg = event.get_plaintext().strip()
    return len(user_msg) > 0


chat_handler = on_message(rule=Rule(is_chat_trigger), priority=1, block=True)


@chat_handler.handle()
async def handle_chat(bot: Bot, event: GroupMessageEvent):
    user_msg = event.get_plaintext().strip()
    user_id = event.user_id
    msg_id = event.message_id
    
    logger.info(f"🤖 [AI Gateway] 收到来自用户 {user_id} 的对话请求: {user_msg}")

    raw_output = ""
    try:
        async with model_lock:
            raw_output = await asyncio.wait_for(call_pi_agent(user_msg), timeout=45.0)

    except FinishedException:
        raise
    except asyncio.TimeoutError:
        logger.error("❌ [AI Gateway] PI Agent 执行超时")
        raw_output = "<thought>执行超时了，给个卡顿回应</thought><action>NONE</action><reply>……（稍等下，刚刚有点卡了）</reply>"
    except Exception as e:
        logger.error(f"❌ [AI Gateway] 处理消息时发生错误: {e}")
        raw_output = "<thought>系统发生异常</thought><action>NONE</action><reply>……</reply>"

    # 1. 解析统一格式 (此时返回 3 个值)
    thought, action, reply = parse_model_output(raw_output)

    # 2. 🧠 控制台日志记录
    logger.info("--------------------------------------------------")
    logger.info(f"🧠 [Stella 内部思考过程]:\n{thought}")
    logger.info(f"⚙️ [Stella 判定动作]: {action}")
    logger.info("--------------------------------------------------")

    # 3. 极速拆分短句
    if not reply:
        reply = "......？"

    reply = re.sub(r'[\（\(][^\）\)]*[\）\)]', '', reply).strip()
    lines = [line.strip() for line in reply.split("\n") if line.strip()][:3]
    if not lines:
        lines = ["......？"]

    # 4. 📝 写入指定 Markdown 日志文件
    await append_thought_to_markdown(user_id, user_msg, thought, action, lines)

    # 5. 发送消息回 QQ
    reply_segment = MessageSegment.reply(msg_id)
    logger.success(f"✨ [即将发送给 QQ 的台词]: {' | '.join(lines)}")

    for i, line in enumerate(lines):
        if i > 0:
            await asyncio.sleep(0.8)
        
        if i == 0:
            msg_to_send = Message([reply_segment, MessageSegment.text(line)])
        else:
            msg_to_send = Message(line)

        if i == len(lines) - 1:
            await chat_handler.finish(msg_to_send)
        else:
            await chat_handler.send(msg_to_send)