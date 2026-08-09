# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动发言调度：只在群聊有一定活跃度时，低调地插一句话。

主动发言强度由“群消息频率（平均间隔）”决定：
- 消息频率过低（平均间隔过大 / 消息不足两条）时，完全不主动发言，
  避免在冷清的群里自言自语、制造噪音；
- 消息频率达到一定水平后，再按其高低复用既定概率（高频略低、中频较高），
  且主动发言之间有硬性冷却，避免刷屏。
"""

from __future__ import annotations

import random
import re
import time

from nonebot import logger

from config import (
    PROACTIVE_COOLDOWN,
    PROACTIVE_FREQ_WINDOW,
    PROACTIVE_HIGH_FREQ_INTERVAL,
    PROACTIVE_LOW_FREQ_INTERVAL,
    PROACTIVE_MAX_PROB,
    PROACTIVE_MIN_PROB,
)


def _ngrams(text: str, n: int) -> list[str]:
    """把文本切成一连串相邻字符片段（用于相似度去重）。"""
    text = re.sub(r"\s+", "", text)
    return [text[i : i + n] for i in range(max(0, len(text) - n + 1))]


# 相似度去重阈值：新台词与上次发言的 4-gram 重叠率超过该比例即视为重复
SIMILARITY_THRESHOLD = 0.5


class ProactiveController:
    """主动发言控制：基于群消息频率（平均间隔）估算活跃度。

    规则：
    1. 消息频率低于阈值（平均间隔 >= PROACTIVE_LOW_FREQ_INTERVAL）或消息不足
       两条时，不主动发言（概率为 0），避免在冷清群自言自语；
    2. 消息频率高于阈值（间隔更小）时，复用上一次的概率换算：高频群低概率、
       相对低频但仍有活跃的群高一点，且主动发言之间有硬性冷却时间。
    """

    def __init__(self):
        # group_id -> 最近消息时间戳列表（用于估算平均间隔）
        self._timestamps: dict[int, list[float]] = {}
        # group_id -> 上次主动发言时间戳
        self._last_speak: dict[int, float] = {}
        self._last_check: dict[int, float] = {}
        # group_id -> 最近说过的话（用于反重复刷屏）
        self._spoken: dict[int, list[str]] = {}

    # ── 反重复刷屏 ──────────────────────────────────────
    def record_spoken(self, group_id: int, lines: list[str]):
        """记录本群刚说过的话，用于判断要不要拦截几乎一样的重复内容"""
        joined = "\n".join(lines)
        self._spoken[group_id] = [joined]

    def recently_spoken(self, group_id: int, lines: list[str]) -> bool:
        """新台词与最近一次主动/回复台词高度相似时返回 True（用于防刷屏）。"""
        prev = self._spoken.get(group_id)
        if not prev or not lines:
            return False
        joined = "\n".join(lines).strip()
        before = prev[0].strip()
        if not joined or not before:
            return False
        # 分词成相邻子串，只要有较长片段重叠就视为重复
        segments = [
            _seg
            for ln in lines
            if ln.strip()
            for _seg in _ngrams(ln.strip(), 4)
        ]
        if not segments:
            return False
        overlap = sum(1 for s in segments if s in before)
        return overlap / len(segments) >= SIMILARITY_THRESHOLD

    # ── 频率统计 ────────────────────────────────────────
    def record_message(self, group_id: int):
        """收到群消息时调用，记录时间戳用于估算频率"""
        now = time.monotonic()
        lst = self._timestamps.setdefault(group_id, [])
        lst.append(now)
        # 只保留窗口内最近的消息
        if len(lst) > PROACTIVE_FREQ_WINDOW:
            del lst[: len(lst) - PROACTIVE_FREQ_WINDOW]

    def average_interval(self, group_id: int) -> float | None:
        """估算最近消息的平均间隔（秒）。消息不足两条时返回 None（视为频率过低）。"""
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

        消息频率过低（平均间隔 >= PROACTIVE_LOW_FREQ_INTERVAL，或消息不足
        两条使 interval 为 None）时返回 0，即不主动发言；否则复用上一次
        逻辑：高频（间隔小）概率低，随间隔增大概率线性攀升。
        """
        interval = self.average_interval(group_id)
        if interval is None:
            # 消息太少（不足两条）即频率过低 → 不主动发言
            return 0.0
        if interval >= PROACTIVE_LOW_FREQ_INTERVAL:
            # 平均间隔过大 → 消息频率过低 → 不主动发言
            return 0.0
        if interval <= PROACTIVE_HIGH_FREQ_INTERVAL:
            return PROACTIVE_MIN_PROB
        # 线性插值：间隔越大概率越高（复用过上一版逻辑）
        ratio = (interval - PROACTIVE_HIGH_FREQ_INTERVAL) / (
            PROACTIVE_LOW_FREQ_INTERVAL - PROACTIVE_HIGH_FREQ_INTERVAL
        )
        return PROACTIVE_MIN_PROB + ratio * (PROACTIVE_MAX_PROB - PROACTIVE_MIN_PROB)

    def should_speak(self, group_id: int) -> bool:
        """是否应该主动发言：未冷却 + 概率命中。

        概率为 0（消息频率过低）时，掷骰永远不会命中，保证冷清群不主动开口。
        """
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
_proactive_instance: ProactiveController | None = None


def get_proactive() -> ProactiveController:
    global _proactive_instance
    if _proactive_instance is None:
        _proactive_instance = ProactiveController()
    return _proactive_instance
