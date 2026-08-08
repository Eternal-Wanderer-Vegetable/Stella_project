# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动发言调度：在群聊沉默一段时间后，优雅地把话题带回来。

按配置的时间窗口（PROACTIVE_START/END + 随机上限）在合适时机以一定概率
把近期要点总结成一句自然的话发出来。含节流：距上次主动发言不足一定秒数
时会跳过，避免烦扰。
"""

from __future__ import annotations

import random
import time
from typing import Optional

from nonebot import logger

from config import (
    PROACTIVE_COOLDOWN, PROACTIVE_FREQ_WINDOW,
    PROACTIVE_HIGH_FREQ_INTERVAL, PROACTIVE_LOW_FREQ_INTERVAL,
    PROACTIVE_MAX_PROB, PROACTIVE_MIN_PROB,
)


class ProactiveController:
    """主动发言控制：基于群消息频率（平均间隔）估算活跃度，
    高频群低概率主动发言（但非零），低频群高概率主动发言；
    主动发言之间有硬性冷却时间。"""

    def __init__(self):
        # group_id -> 最近消息时间戳列表（用于估算平均间隔）
        self._timestamps: dict[int, list[float]] = {}
        # group_id -> 上次主动发言时间戳
        self._last_speak: dict[int, float] = {}
        self._last_check: dict[int, float] = {}

    # ── 频率统计 ────────────────────────────────────────
    def record_message(self, group_id: int):
        """收到群消息时调用，记录时间戳用于估算频率"""
        now = time.monotonic()
        lst = self._timestamps.setdefault(group_id, [])
        lst.append(now)
        # 只保留窗口内最近的消息
        if len(lst) > PROACTIVE_FREQ_WINDOW:
            del lst[: len(lst) - PROACTIVE_FREQ_WINDOW]

    def average_interval(self, group_id: int) -> Optional[float]:
        """估算最近消息的平均间隔（秒）。消息不足两条时返回 None（按低频处理）。"""
        lst = self._timestamps.get(group_id, [])
        if len(lst) < 2:
            return None
        return (lst[-1] - lst[0]) / (len(lst) - 1)

    # ── 冷却管理 ────────────────────────────────────────
    def mark_spoke(self, group_id: int):
        self._last_speak[group_id] = time.monotonic()

    def last_spoke_at(self, group_id: int) -> float:
        return self._last_speak.get(group_id, 0.0)

    def in_cooldown(self, group_id: int) -> bool:
        return (time.monotonic() - self.last_spoke_at(group_id)) < PROACTIVE_COOLDOWN

    # ── 概率计算 ────────────────────────────────────────
    def speak_probability(self, group_id: int) -> float:
        """根据消息频率换算主动发言概率。
        高频（间隔小）-> 概率低但非零；低频（间隔大）-> 概率高。"""
        interval = self.average_interval(group_id)
        if interval is None:
            # 消息太少，按低频（冷清）处理，概率较高
            return PROACTIVE_MAX_PROB
        if interval <= PROACTIVE_HIGH_FREQ_INTERVAL:
            return PROACTIVE_MIN_PROB
        if interval >= PROACTIVE_LOW_FREQ_INTERVAL:
            return PROACTIVE_MAX_PROB
        # 线性插值：间隔越大概率越高
        ratio = (interval - PROACTIVE_HIGH_FREQ_INTERVAL) / (
            PROACTIVE_LOW_FREQ_INTERVAL - PROACTIVE_HIGH_FREQ_INTERVAL
        )
        return PROACTIVE_MIN_PROB + ratio * (PROACTIVE_MAX_PROB - PROACTIVE_MIN_PROB)

    def should_speak(self, group_id: int) -> bool:
        """是否应该主动发言：未冷却 + 概率命中"""
        if self.in_cooldown(group_id):
            return False
        prob = self.speak_probability(group_id)
        roll = random.random()
        interval = self.average_interval(group_id)
        interval_str = f"{interval:.1f}" if interval is not None else "不足两条"
        logger.debug(f"[Proactive] 群 {group_id} 平均间隔={interval_str}s "
                     f"概率={prob:.2f} 掷骰={roll:.2f}")
        return roll < prob

    # ── 总结时机辅助 ────────────────────────────────────
    def check_interval_elapsed(self, group_id: int, seconds: float) -> bool:
        """距上次 check 是否已超过 seconds 秒（用于限制总结频率）"""
        now = time.monotonic()
        last = self._last_check.get(group_id, 0.0)
        if now - last >= seconds:
            self._last_check[group_id] = now
            return True
        return False


# 全局单例，供 ai_gateway 与 consolidator 共用
_proactive_instance: Optional[ProactiveController] = None


def get_proactive() -> ProactiveController:
    global _proactive_instance
    if _proactive_instance is None:
        _proactive_instance = ProactiveController()
    return _proactive_instance
