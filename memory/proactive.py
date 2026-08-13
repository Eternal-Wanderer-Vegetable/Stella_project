# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动发言调度：只在群聊有一定活跃度时，低调地插一句话。

主动发言强度由“群消息频率（平均间隔）”决定，走双锚点插值曲线：
- 消息不足两条时无法估算频率，完全不主动发言；
- 间隔处于 [FAST, SLOW] 之间时按 t**GAMMA 幂次插值——锚点参数决定了
  「热闹时插话」还是「热闹时闭嘴」，同一条曲线两种意图；
- 主动发言之间有硬性冷却，且高度相似的重复内容会被去重，避免刷屏。
"""

from __future__ import annotations

import random
import re
import time

from nonebot import logger

from config import (
    PROACTIVE_COOLDOWN,
    PROACTIVE_FREQ_WINDOW,
    PROACTIVE_INTERVAL_FAST,
    PROACTIVE_INTERVAL_SLOW,
    PROACTIVE_PROB_AT_FAST,
    PROACTIVE_PROB_AT_SLOW,
    PROACTIVE_PROB_GAMMA,
)


def _ngrams(text: str, n: int) -> list[str]:
    """把文本切成一连串相邻字符片段（用于相似度去重）。"""
    text = re.sub(r"\s+", "", text)
    return [text[i : i + n] for i in range(max(0, len(text) - n + 1))]


# 相似度去重阈值：新台词与上次发言的 4-gram 重叠率超过该比例即视为重复
SIMILARITY_THRESHOLD = 0.5


class ProactiveController:
    """主动发言控制：基于群消息频率（平均间隔）估算活跃度。

    规则（双锚点插值曲线，见 memory/proactive.py speak_probability）：
    1. 消息不足两条无法估算频率时，不主动发言（概率为 0）；
    2. 平均间隔处于 [FAST, SLOW] 时按 t**GAMMA 幂次插值——「热闹时插话」
       与「热闹时闭嘴」只是锚点参数差异，同一条曲线覆盖；
    3. 主动发言之间有硬性冷却时间，且复用「与最近发言高度相似则去重」防刷屏。

    时间戳按用户分组存储，群级统计由各用户聚合得出。
    """

    def __init__(self):
        # group_id -> user_id -> 最近发言时间戳列表（估算群级与用户级活跃度）
        self._timestamps: dict[int, dict[int, list[float]]] = {}
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
    def record_message(self, group_id: int, user_id: int | None = None):
        """收到群消息时调用，按用户记录时间戳用于估算群级/用户级活跃度。

        user_id 为 None 时归入伪用户 0（兼容旧调用；群级统计不受影响）。
        """
        now = time.monotonic()
        uid = int(user_id) if user_id is not None else 0
        per_user = self._timestamps.setdefault(group_id, {})
        lst = per_user.setdefault(uid, [])
        lst.append(now)
        if len(lst) > PROACTIVE_FREQ_WINDOW:
            del lst[: len(lst) - PROACTIVE_FREQ_WINDOW]

    def average_interval(self, group_id: int) -> float | None:
        """估算全群最近消息的平均间隔（秒）。消息不足两条时返回 None。"""
        merged = sorted(
            ts for lst in self._timestamps.get(group_id, {}).values() for ts in lst
        )
        if len(merged) < 2:
            return None
        window = merged[-PROACTIVE_FREQ_WINDOW:]
        if len(window) < 2:
            return None
        return (window[-1] - window[0]) / (len(window) - 1)

    def user_average_interval(self, group_id: int, user_id: int) -> float | None:
        """该用户自身的发言平均间隔（秒）；不足两条返回 None。"""
        lst = self._timestamps.get(group_id, {}).get(int(user_id), [])
        if len(lst) < 2:
            return None
        return (lst[-1] - lst[0]) / (len(lst) - 1)

    def active_users(self, group_id: int, within_seconds: float) -> list[int]:
        """返回 within_seconds 内发过言的用户，按最近发言时间倒序（D2 的选人依据）。

        排除伪用户 0（旧调用兜底）与 Bot 自身不在此处处理——调用方按需过滤。
        """
        now = time.monotonic()
        recent = [
            (uid, lst[-1])
            for uid, lst in self._timestamps.get(group_id, {}).items()
            if uid and lst and (now - lst[-1]) <= within_seconds
        ]
        recent.sort(key=lambda item: item[1], reverse=True)
        return [uid for uid, _ in recent]

    def user_message_count(self, group_id: int, user_id: int) -> int:
        """该用户在当前统计窗口内的发言条数（窗口受 PROACTIVE_FREQ_WINDOW 限制）。

        注意：这是内存窗口内的计数，不等于 24h 总量。配额奖励用的 24h 计数
        走 memory.proactive_state.count_user_messages_24h（读 DB，重启不丢）。
        """
        return len(self._timestamps.get(group_id, {}).get(int(user_id), []))

    def last_spoke_ts(self, group_id: int, user_id: int) -> float | None:
        """该用户最后一次发言的 monotonic 时间戳；无记录返回 None。

        供主动 @ 的回应检测判断「提问之后有没有说话」。
        """
        lst = self._timestamps.get(group_id, {}).get(int(user_id), [])
        return lst[-1] if lst else None

    # ── 冷却管理 ────────────────────────────────────────
    def mark_spoke(self, group_id: int):
        self._last_speak[group_id] = time.monotonic()

    def last_spoke_at(self, group_id: int) -> float:
        return self._last_speak.get(group_id, 0.0)

    def in_cooldown(self, group_id: int) -> bool:
        return (time.monotonic() - self.last_spoke_at(group_id)) < PROACTIVE_COOLDOWN

    # ── 概率计算 ────────────────────────────────────────
    def speak_probability(self, group_id: int) -> float:
        """按群消息频率换算话题参与概率（双锚点插值 + 幂次整形）。

        interval <= FAST  → PROB_AT_FAST
        interval >= SLOW  → PROB_AT_SLOW
        中间              → t = (SLOW - interval) / (SLOW - FAST)   # t: 0=慢, 1=快
                            prob = SLOW + (FAST - SLOW) * t**GAMMA

        「热闹时插话」与「热闹时闭嘴」只是参数差异，同一条曲线覆盖，
        不需要模式分支。消息不足两条时返回 0——无法估算频率就不主动开口。
        """
        interval = self.average_interval(group_id)
        if interval is None:
            return 0.0

        fast, slow = PROACTIVE_INTERVAL_FAST, PROACTIVE_INTERVAL_SLOW
        p_fast, p_slow = PROACTIVE_PROB_AT_FAST, PROACTIVE_PROB_AT_SLOW

        if interval <= fast:
            return max(0.0, min(1.0, p_fast))
        if interval >= slow:
            return max(0.0, min(1.0, p_slow))
        # 锚点配置异常（slow <= fast）时退化为慢端概率，避免除零
        if slow <= fast:
            return max(0.0, min(1.0, p_slow))

        t = (slow - interval) / (slow - fast)
        gamma = PROACTIVE_PROB_GAMMA if PROACTIVE_PROB_GAMMA > 0 else 1.0
        prob = p_slow + (p_fast - p_slow) * (t**gamma)
        return max(0.0, min(1.0, prob))

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
