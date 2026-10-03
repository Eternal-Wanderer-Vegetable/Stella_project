# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""实验时钟（计划 §6.7.3 时钟合同）：逻辑业务时间与性能计时严格分离。

合同（计划原文）：「逻辑业务时钟注入所有 TTL/冷却/backoff/配额/任务 lease/
回复窗口及 SQL 时间写入；性能时长继续 monotonic 真实计时」。

- :class:`SystemClock`：真实时钟，生产路径使用。
- :class:`VirtualClock`：固定起始时间 + 手动 ``advance`` 的虚拟时钟；评测里
  TTL/冷却/配额/窗口等**业务时间**全部走它，绝不偷看系统墙钟；而
  ``monotonic`` 恒返回真实 ``time.monotonic``——性能计时与虚拟时间彻底独立，
  一次 ``advance(10_000)`` 不会让耗时测量凭空多出 10 秒。

不替换全局 ``time`` 模块：业务代码按依赖注入 :class:`Clock`，SQL 时间写
显式参数（计划 §6.7.3「避免替换全局 time 模块」）。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "SystemClock", "VirtualClock"]


@runtime_checkable
class Clock(Protocol):
    """时钟合同：``now`` 恒为 aware UTC datetime；``monotonic`` 恒为真实单调秒。"""

    def now(self) -> datetime:
        """当前业务时间（aware UTC）。"""
        ...

    def monotonic(self) -> float:
        """性能计时（真实单调时钟，与业务时间无关）。"""
        ...


class SystemClock:
    """真实时钟：生产与集成冒烟使用。"""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


class VirtualClock:
    """虚拟时钟：起始时间 + ``advance`` 手动推进，业务 TTL/冷却/配额/窗口
    的唯一时间源（离线可复现：同一起点 + 同一推进序列 → 同一业务时间）。

    - ``now()`` 返回 aware UTC；naive 起始时间直接拒绝（防主机时区渗入）。
    - ``advance(seconds)`` 只允许前进——业务时间倒退会让 TTL/冷却判断出现
      幻觉，评测里没有合法的倒退场景。
    - ``advance_to(moment)`` 把虚拟时间推进到指定时刻（按消息时间戳回放用），
      只前进不倒退。
    - ``monotonic()`` 与 :class:`SystemClock` 相同：恒为真实
      ``time.monotonic``，与虚拟时间无关。
    """

    def __init__(self, start: datetime | None = None):
        if start is None:
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        if start.tzinfo is None:
            raise ValueError("VirtualClock 起始时间必须是 aware datetime（拒绝 naive 时间）")
        self._now = start.astimezone(timezone.utc)

    @property
    def virtual_epoch(self) -> float:
        """当前虚拟时间的 Unix epoch 秒（供需要浮点 ``now`` 的业务函数使用）。"""
        return self._now.timestamp()

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        """把虚拟时间前进 ``seconds`` 秒（负数拒绝）。"""
        if seconds < 0:
            raise ValueError("虚拟业务时间不能倒退")
        self._now = self._now + timedelta(seconds=seconds)
        return self._now

    def advance_to(self, moment: datetime) -> datetime:
        """把虚拟时间推进到 ``moment``；只前进不倒退（乱序输入按原样截停）。"""
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        moment = moment.astimezone(timezone.utc)
        if moment > self._now:
            self._now = moment
        return self._now

    def monotonic(self) -> float:
        # 性能计时恒走真实单调时钟：advance 十小时，monotonic 依旧只走真实一瞬。
        return time.monotonic()
