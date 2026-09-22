# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""运行态只读取数：OneBot 链路（平台页）与模型调度器/降级状态（提供商页）。

M1 只读边界：这里只有「此刻发生了什么」的进程内快照；端点/角色的**配置**
（.env 平面）读写属 M2。``link_status()`` 的键在未连接时是显式 ``None``
（link_monitor 契约），本层原样透传，由前端按可空渲染。
"""

from __future__ import annotations


def platform_link() -> dict:
    """OneBot 链路实时状态（心跳/探活/健康度）。取不到时给可识别的降级形状。"""
    try:
        from extensions.link_monitor import link_status

        return link_status()
    except Exception:
        return {"enabled": False, "connected": False, "unavailable": True}


def providers_runtime() -> dict:
    """调度器闸门快照 + 降级状态（只读运行态，配置态属 M2）。"""
    scheduler: dict = {}
    try:
        from core.llm import snapshot

        scheduler = snapshot()
    except Exception:
        scheduler = {}
    fallback: dict = {}
    try:
        from core.llm import fallback_states

        fallback = fallback_states()
    except Exception:
        fallback = {}
    return {"scheduler": scheduler, "fallback_states": fallback}
