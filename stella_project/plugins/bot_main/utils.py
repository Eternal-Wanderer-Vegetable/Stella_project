import asyncio
import random
import re
from datetime import datetime

async def human_delay(message: str = "0123456789ABCDEF"):
    """模拟人类打字与思考的延迟策略"""
    length = len(message)
    now_hour = datetime.now().hour

    # 1. 极短回复
    if length < 5:
        await asyncio.sleep(random.uniform(0.4, 0.8))
        return

    # 2. 长文本
    if length > 120:
        await asyncio.sleep(random.uniform(0.5, 1.2))
        return

    # 3. 打字速度计算
    typing_speed = random.uniform(0.05, 0.12)
    typing_time = length * typing_speed

    # 4. 思考/组织语言时间
    think_delay = random.uniform(0.6, 1.5)
    if "(" in message or "（" in message:
        think_delay += random.uniform(0.5, 1.0)

    # 5. 深夜/凌晨响应变慢
    if 0 <= now_hour <= 6:
        think_delay *= 1.5
        typing_time *= 1.2

    delay = think_delay + typing_time

    # 6. 随机走神波动
    if random.random() < 0.05:
        delay += random.uniform(2.0, 4.0)

    final_delay = min(delay, 6.0)
    await asyncio.sleep(final_delay)

def md_to_qq(md_text: str) -> str:
    """Markdown 格式转换为适用于 QQ 纯文本展示的格式"""
    text = md_text
    text = re.sub(r"^# (.*)", r"🎮 \1", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.*)", r"【\1】", text, flags=re.MULTILINE)
    text = re.sub(r"^### (.*)", r"▪ \1", text, flags=re.MULTILINE)
    text = re.sub(r"^- (.*)", r"• \1", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"【\1】", text)
    text = re.sub(r"^-{3,}", "──────────", text)
    return text