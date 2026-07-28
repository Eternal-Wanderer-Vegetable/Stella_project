import asyncio
import os
import sys
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional
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
DB_PATH = PROJECT_ROOT / "pi_agent_core" / "agent_memory.db"

# 💡 指定 Markdown 思考日志文件的保存路径
THOUGHT_LOG_PATH = PROJECT_ROOT / "stella_thought_logs.md"

# 💡 配置支持 AI 服务的群号白名单
ALLOWED_GROUPS = {263402786}

# --- 2. 建立全局并发锁（并发控制）---
model_lock = asyncio.Lock()


async def append_thought_to_markdown(user_id: int, user_msg: str, thought: str, action: str, reply_lines: list):
    """异步将 AI 的思考过程追加写入指定 md 文件"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reply_str = " <br> ".join(reply_lines)
    
    thought_formatted = thought.replace('\n', '\n  > ')
    
    log_entry = f"""### 🕒 [{now_str}] 用户: `{user_id}`
- **📥 用户输入**: {user_msg}
- **🧠 内部思考**: 
  > {thought_formatted}
- **⚙️ 判定动作**: `{action}`
- **💬 最终台词**: {reply_str}

---
"""
    try:
        if not THOUGHT_LOG_PATH.exists():
            THOUGHT_LOG_PATH.write_text("# 🤖 思考过程与决策日志\n\n", encoding="utf-8")

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

    thought_match = re.search(r'<thought>(.*?)(?:</thought>|<action>|<reply>|$)', raw_text, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    action_match = re.search(r'<action>(.*?)(?:</action>|<reply>|$)', raw_text, re.DOTALL)
    if action_match:
        action = action_match.group(1).strip()

    reply_match = re.search(r'<reply>(.*?)(?:</reply>|$)', raw_text, re.DOTALL)
    if reply_match:
        reply = reply_match.group(1).strip()

    if not reply:
        clean_text = re.sub(r'<[^>]+>.*?(?:</[^>]+>|$)', '', raw_text, flags=re.DOTALL).strip()
        if clean_text:
            reply = clean_text

    return thought, action, reply


def get_recent_group_chat_context(group_id: int, limit: int = 15) -> str:
    """从数据库读取该群最新的聊天记录作为上下文"""
    if not DB_PATH.exists():
        return ""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, content FROM group_messages WHERE group_id = ? ORDER BY id DESC LIMIT ?",
            (str(group_id), limit)
        )
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return ""
        
        # 翻转为正序：旧 -> 新
        rows.reverse()
        chat_logs = [f"用户({r[0]}): {r[1]}" for r in rows]
        return "\n".join(chat_logs)
    except Exception as e:
        logger.error(f"❌ [DB Read Exception]: {e}")
        return ""


async def call_pi_agent(user_msg: str, user_id: int, group_id: Optional[int] = None) -> str:
    """拉起 PI Agent CLI 子进程"""
    if not os.path.isdir(PI_AGENT_DIR):
        raise FileNotFoundError(f"PI Agent 目录无效: {PI_AGENT_DIR}")

    npx_cmd = "npx.cmd" if sys.platform == "win32" else "npx"

    # 1. 动态获取群聊历史上下文
    recent_context = ""
    if group_id:
        recent_context = get_recent_group_chat_context(group_id, limit=12)

    # 2. 构建 Prompt
    prompt_sections = []
    if recent_context:
        prompt_sections.append(f"--- 【近期群聊记录（你可以参考这些内容回答）】 ---\n{recent_context}\n----------------------------------")
    
    prompt_sections.append(f"当前说话的用户: {user_id}\n用户提问: {user_msg}")
    
    full_prompt = "\n\n".join(prompt_sections)

    # 3. 严格校验绝对路径
    system_prompt_path = (PROJECT_ROOT / "pi_agent_core" / "SYSTEM.md").resolve().as_posix()
    extension_path = (PROJECT_ROOT / "pi_agent_core" / "extensions" / "memory_system" / "index.ts").resolve().as_posix()

    # 💡 核心修复：把 -p 放在参数列表的最末尾，防止换行符打断后续标志的解析！
    cmd = [
        npx_cmd, "pi",
        "--provider", "lm-studio",
        "--model", "stella-local",
        "--system-prompt", system_prompt_path,
        "--extension", extension_path,
        "-p", full_prompt  # 👈 关键！必须将 -p 移到参数数组的最后一位！
    ]

    logger.info(f"🔍 [CMD DEBUG] 正在启动 PI Agent...")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=PI_AGENT_DIR
    )

    stdout, stderr = await proc.communicate()

    err_msg = stderr.decode('utf-8', errors='ignore').strip()
    out_msg = stdout.decode('utf-8', errors='ignore').strip()

    if err_msg:
        logger.warning(f"⚠️ [PI Agent Stderr]:\n{err_msg}")
    logger.info(f"💡 [PI Agent Stdout Raw]:\n{out_msg}")

    if proc.returncode != 0:
        logger.error(f"❌ [PI Agent Error ReturnCode {proc.returncode}]")
        raise RuntimeError("PI Agent 引擎运行异常")

    reply = out_msg

    # 破防/出戏/硬编码身份拦截
    bad_words = ["作为", "AI", "模型", "助手", "语言模型", "Gemma", "QQ用户", "qq用户"]
    if any(w in reply for w in bad_words):
        reply = "<thought>破防兜底</thought><action>NONE</action><reply>……？你在说什么奇怪的话呢。</reply>"

    return reply

def save_raw_message_to_db(user_id: int, group_id: int, text: str):
    """同步写入 SQLite 数据库的短期记录表（在 executor 中异步运行）"""
    if not DB_PATH.exists():
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT,
                user_id TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute(
            "INSERT INTO group_messages (group_id, user_id, content) VALUES (?, ?, ?)",
            (str(group_id), str(user_id), text)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ [DB Writer Exception]: {e}")


# --- 静默群聊监听器（带过滤器）---
group_silent_listener = on_message(priority=99, block=False)

@group_silent_listener.handle()
async def record_group_chat(event: GroupMessageEvent):
    group_id = event.group_id
    
    # 🛡️ 过滤器 1：如果不是允许的群，直接拦截忽略
    if group_id not in ALLOWED_GROUPS:
        return

    user_msg = event.get_plaintext().strip()
    
    # 🛡️ 过滤器 2：忽略空文本或系统指令
    if not user_msg or user_msg.startswith("/"):
        return

    user_id = event.user_id

    # 异步抛给后台线程执行 SQLite 写入
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, save_raw_message_to_db, user_id, group_id, user_msg)


async def is_chat_trigger(event: GroupMessageEvent) -> bool:
    # 🛡️ 群过滤：不在白名单内的群，即便 @Bot 也不触发回复
    if event.group_id not in ALLOWED_GROUPS:
        return False

    if not event.is_tome():
        return False

    user_msg = event.get_plaintext().strip()
    return len(user_msg) > 0


chat_handler = on_message(rule=Rule(is_chat_trigger), priority=1, block=True)

@chat_handler.handle()
async def handle_chat(bot: Bot, event: GroupMessageEvent):
    user_msg = event.get_plaintext().strip()
    user_id = event.user_id
    group_id = event.group_id
    msg_id = event.message_id
    
    logger.info(f"🤖 [AI Gateway] 收到来自用户 {user_id} (群 {group_id}) 的对话请求: {user_msg}")

    raw_output = ""
    try:
        async with model_lock:
            raw_output = await asyncio.wait_for(
                call_pi_agent(user_msg=user_msg, user_id=user_id, group_id=group_id), 
                timeout=45.0
            )

    except FinishedException:
        raise
    except asyncio.TimeoutError:
        logger.error("❌ [AI Gateway] PI Agent 执行超时")
        raw_output = "<thought>执行超时了，给个卡顿回应</thought><action>NONE</action><reply>......？</reply>"
    except Exception as e:
        logger.error(f"❌ [AI Gateway] 处理消息时发生错误: {e}")
        raw_output = "<thought>系统发生异常</thought><action>NONE</action><reply>......？</reply>"

    # 1. 解析统一格式
    thought, action, reply = parse_model_output(raw_output)

    # 2. 🧠 控制台日志记录
    logger.info("--------------------------------------------------")
    logger.info(f"🧠 [内部思考过程]:\n{thought}")
    logger.info(f"⚙️ [判定动作]: {action}")
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