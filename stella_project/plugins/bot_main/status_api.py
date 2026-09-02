# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""本地状态接口。挂在 NoneBot 已有的 ASGI app 上（``HOST:PORT``），**不新增端口**——
反向 WS 端点本就是同一个 HTTP 服务器提供的。

为什么需要它：``link_status()`` 与调度器统计都是 Bot 进程内的状态，外部进程
（``deploy status`` / GUI）读不到。写状态文件会有陈旧问题（Bot 崩了之后文件仍在），
HTTP 端点则天然「连不上就是没运行」。

安全约束：``HOST`` 可能是 ``0.0.0.0``（NapCat 在另一台机器时必须如此），那时本路由
也会暴露到局域网。因此两道防护：① 只接受来自回环地址的请求；② 响应体不含任何
凭据与群聊内容。

消费方：``deploy status --json`` 与桌面 GUI（都是回环调用）。
"""

from __future__ import annotations

import ipaddress
import os
import time
from importlib.metadata import PackageNotFoundError, version

# fastapi 必须在模块级导入：本文件启用了 from __future__ import annotations，
# 所有标注变成字符串，而 FastAPI 靠运行时解析标注来识别依赖注入——它只在
# **模块全局命名空间**里查找类型名。若 Request 只存在于函数局部作用域，
# FastAPI 找不到它，会把 request 当成必需的查询参数，请求返回 422。
from fastapi import Request
from fastapi.responses import JSONResponse

from config import ALLOWED_GROUPS, STELLA_STATUS_API_ENABLED, STELLA_STATUS_API_PATH

# 进程启动时刻：模块 import 即执行（ai_gateway 在插件加载时导入本模块）。
# 放这里比放 setup_status_api() 里早——即便路由因故未注册，uptime 基准也更接近真实启动点。
_STARTED_AT = time.time()

# importlib.metadata 查不到（未安装成包 / 源码直接运行）时的回退版本号。
# 与 pyproject.toml 的 version 保持一致，改版本号时一并更新。
_FALLBACK_VERSION = "2.6.0"


def _project_version() -> str:
    """项目版本号：优先 importlib.metadata，查不到回退到模块常量。

    不要解析 pyproject.toml——Release 包里它在，但依赖文件位置不优雅。
    """
    try:
        return version("stella_project")
    except PackageNotFoundError:
        return _FALLBACK_VERSION


def _is_loopback(host: str | None) -> bool:
    """判断客户端地址是否回环；解析失败按非回环处理（宁关勿开）。

    覆盖 ``127.0.0.1`` / ``::1`` / ``localhost`` / ``127.x.x.x``（Docker 场景
    可能不是 .0.1）。``ipaddress.ip_address`` 对两种地址族都能解析。
    """
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _fallback_states() -> dict:
    """各角色此刻的降级状态（配了降级链的角色才有）。取不到就当空。"""
    try:
        from core.llm import fallback_states

        return fallback_states()
    except Exception:
        return {}


def _capabilities() -> dict | None:
    """能力清单快照。取不到就当没有（同 ``_fallback_states`` 的惯例）。

    ``capability.inventory.snapshot()`` 刻意只产结构化字段（不含 description 与
    examples 原文），正是为了满足本模块「响应体不含凭据与群聊内容」那条约束——
    自由文本是唯一可能夹带 URL 与密钥的字段，不放进来就不必为它加一道守卫。
    """
    try:
        from capability.inventory import snapshot as capability_snapshot

        return capability_snapshot()
    except Exception:
        return None


def build_payload(
    link: dict | None,
    sched: dict,
    *,
    pid: int,
    started_at: float,
    usage: dict | None = None,
    capabilities: dict | None = None,
) -> dict:
    """组装状态响应。

    刻意不包含的字段：ONEBOT_ACCESS_TOKEN、ALLOWED_GROUPS 的具体群号、
    任何消息内容。即使路由被误暴露，泄漏面也仅限「有个机器人在运行」。
    allowed_groups 只给数量——GUI 需要它来提示「未配置任何群」。

    ``usage`` 是 ``core.llm.usage_store.usage_snapshot()``，**只有计数与比率**：
    今日 token 按角色/端点/模型、缓存命中率、预算余量、正在降级的角色。
    绝不含 prompt / 模型输出 / base_url / api_key——这条与上面那串同等重要，
    用量面板是给用户看成本的，不是给它一个泄漏通道。

    ``capabilities`` 是 ``capability.inventory.snapshot()``：能力 id、域、来源层、
    是否可路由、provider 的工具名与退避状态。**同样只有结构化字段**，理由见
    ``_capabilities()``。它回答的是「插件装了为什么从来不被调用」——今天这个问题
    只能靠翻启动日志。
    """
    return {
        "version": _project_version(),
        "pid": pid,
        "uptime_seconds": time.time() - started_at,
        "allowed_group_count": len(ALLOWED_GROUPS),
        "link": link,          # link_status() 原样，或 None（扩展未加载时）
        "scheduler": sched,    # core.llm.snapshot()
        "usage": usage,        # usage_store.usage_snapshot()，或 None（取数失败）
        "capabilities": capabilities,  # inventory.snapshot()，或 None（取数失败）
    }


def setup_status_api() -> None:
    """注册 GET /stella/status。非 ASGI 驱动或开关关闭时静默跳过。

    NoneBot 的 get_app() 只在 ReverseDriver（FastAPI/Quart）下可用。取不到
    app 时不报错——状态接口是加分项，缺了只是 GUI 少一块信息，不该阻断启动。
    """
    if not STELLA_STATUS_API_ENABLED:
        return
    try:
        from nonebot import get_app, logger

        app = get_app()
    except Exception:
        return
    if app is None:
        return

    @app.get(STELLA_STATUS_API_PATH)
    async def _status_endpoint(request: Request):
        # request.client.host 是直连对端地址。若将来置于反向代理之后，
        # 这里会拿到代理的地址（通常也是回环）——那时回环校验会失效，
        # 需要改为校验 X-Forwarded-For 或干脆禁用本接口。
        # 当前部署形态是直连，无此问题。
        host = request.client.host if request.client else None
        if not _is_loopback(host):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        try:
            from extensions.link_monitor import link_status

            link = link_status()
        except Exception:
            link = None
        try:
            from core.llm import snapshot

            sched = snapshot()
        except Exception:
            sched = {}
        try:
            from core.llm.usage_store import usage_snapshot

            usage = usage_snapshot()
            usage["fallback_states"] = _fallback_states()
        except Exception:
            # 取数失败只让面板少一块，绝不让状态接口 500
            usage = None
        return build_payload(
            link,
            sched,
            pid=os.getpid(),
            started_at=_STARTED_AT,
            usage=usage,
            capabilities=_capabilities(),
        )

    try:
        from nonebot import get_driver

        port = getattr(get_driver().config, "port", None)
    except Exception:
        port = None
    # 回环校验决定了只有本机能访问，完整 URL 写 127.0.0.1 即可（与 HOST 无关）
    url = (
        f"http://127.0.0.1:{port}{STELLA_STATUS_API_PATH}"
        if port
        else f"http://127.0.0.1{STELLA_STATUS_API_PATH}"
    )
    logger.success(f"✅ 本地状态接口已就绪: {url}")
