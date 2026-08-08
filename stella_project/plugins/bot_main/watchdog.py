# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""NapCat 消息流看门狗（bot_main.watchdog）。

作用：监控 QQ 群消息是否仍在正常流入。若长时间（默认 300 秒）没有任何消息到达，
推断 NapCat 与 QQ 的连接可能中断，此时通过 NapCat WebUI API 触发一次重启，
并在重启后把 last_event_time 拨后 120 秒作为缓冲，避免恢复过程中反复触发重启。

机制：
- 每次收到任意群消息都会更新模块级全局 last_event_time；
- 定时任务（每 1 分钟）比较 last_event_time 距今是否超过 300 秒并决定是否重启。
"""

import time
import httpx
from nonebot import logger, on_message
from nonebot_plugin_apscheduler import scheduler

from config import NAPCAT_TOKEN, NAPCAT_API_URL

# 记录最后一次收到群消息的时间（epoch 秒）；模块导入时初始化为“当前”作为冷启动基准
last_event_time = time.time()

# 监听所有消息（不 block 其他处理器）：只要有消息到达就刷新心跳时间
msg_monitor = on_message(priority=1, block=False)


@msg_monitor.handle()
async def _():
    """把最近一条群消息的时间戳记录到 last_event_time（看门狗的心跳）。"""
    global last_event_time
    last_event_time = time.time()


async def call_napcat_restart_api():
    """通过 NapCat WebUI 的 API 触发一次 NapCat 服务重启。

    行为：NAPCAT_TOKEN 未配置时不发请求（超时 10 秒）；成功返回 200 记 success，
    否则记 error；异常捕获后仅记录日志，不向调用方抛错。
    """
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


# 每分钟执行一次：若超过 300 秒没有任何消息进来，则认为链路中断并尝试重启 NapCat
@scheduler.scheduled_job("interval", minutes=1)
async def watchdog_task():
    global last_event_time
    now = time.time()
    if now - last_event_time > 300:
        logger.warning("[Watchdog] 检测到消息流中断，正在尝试 API 重启...")
        await call_napcat_restart_api()
        # 拨后 120 秒：给重启到恢复留出缓冲窗口，避免在修复期间反复触发重启
        last_event_time = time.time() + 120