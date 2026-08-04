import time
import httpx
from nonebot import logger, on_message
from nonebot_plugin_apscheduler import scheduler

last_event_time = time.time()

msg_monitor = on_message(priority=1, block=False)

@msg_monitor.handle()
async def _():
    global last_event_time
    last_event_time = time.time()

async def call_napcat_restart_api():
    """通过 NapCat WebUI API 触发重启"""
    url = "http://127.0.0.1:6099/api/Process/Restart"
    token = "ac889a86153e" 
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(url, headers=headers, timeout=10.0)
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