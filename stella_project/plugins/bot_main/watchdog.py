import time
import httpx
from nonebot import logger, on_message
from nonebot_plugin_apscheduler import scheduler

from config import NAPCAT_TOKEN, NAPCAT_API_URL

last_event_time = time.time()

msg_monitor = on_message(priority=1, block=False)

@msg_monitor.handle()
async def _():
    global last_event_time
    last_event_time = time.time()

async def call_napcat_restart_api():
    """通过 NapCat WebUI API 触发重启"""
    if not NAPCAT_TOKEN:
        logger.warning("[Watchdog] NAPCAT_TOKEN 未配置，跳过重启")
        return
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {NAPCAT_TOKEN}"
    }
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(NAPCAT_API_URL, headers=headers, timeout=10.0)
            if response.status_code == 200:
                logger.success("[Watchdog] 已成功通过 API 触发 NapCat 重启指令")
            else:
                logger.error(f"[Watchdog] API 重启失败，状态码: {response.status_code}, 响应: {response.text}")
    except Exception as e:
        logger.error(f"[Watchdog] 调用重启接口时发生错误: {e}")

@scheduler.scheduled_job("interval", minutes=1)
async def watchdog_task():
    global last_event_time
    now = time.time()
    if now - last_event_time > 300:
        logger.warning("[Watchdog] 检测到消息流中断，正在尝试 API 重启...")
        await call_napcat_restart_api()
        last_event_time = time.time() + 120