# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Message Buffer：每群短期消息缓冲区（上游工程方案 §4）。

只保存最近发生的事情，不负责理解意义、不承担长期记忆。字段按上游方案定义：
timestamp / sender_id / text / reply_to / mentioned_users / has_image /
has_emoji / message_type / embedding（懒计算）。
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class BufferedMessage:
    """缓冲区内的单条消息。embedding 懒计算：仅在话题判定需要时才填。"""

    timestamp: float                      # time.time()（墙上时钟，便于持久化）
    sender_id: int
    text: str
    msg_id: int = 0
    reply_to: int | None = None           # 回复的消息 id（None = 非回复）
    mentioned_users: tuple[int, ...] = () # 被 @ 的用户
    has_image: bool = False
    has_emoji: bool = False
    message_type: str = "text"            # text / image / emoji / mixed
    embedding: list[float] | None = field(default=None, repr=False)

    @property
    def is_low_value(self) -> bool:
        """图片/表情等非文本消息默认只观察（上游 §22.3/§22.4）。"""
        return self.message_type != "text"


class MessageBuffer:
    """固定容量的环形缓冲。append O(1)，查询只扫尾部。"""

    def __init__(self, maxlen: int):
        self._msgs: deque[BufferedMessage] = deque(maxlen=maxlen)

    def append(self, msg: BufferedMessage) -> None:
        self._msgs.append(msg)

    def tail(self, n: int) -> list[BufferedMessage]:
        """最近 n 条（按时间升序）。"""
        if n <= 0:
            return []
        return list(self._msgs)[-n:]

    def texts(self, n: int, *, skip_low_value: bool = True) -> list[str]:
        """最近 n 条消息的文本（低信息量/非文本默认跳过）。"""
        out: list[str] = []
        for m in self.tail(n):
            if skip_low_value and m.is_low_value:
                continue
            if m.text.strip():
                out.append(m.text.strip())
        return out

    def count_in_window(self, window_seconds: float, now: float | None = None) -> int:
        """滑动时间窗内的消息数（消息速度的原始值，上游 §23）。"""
        now = now if now is not None else time.time()
        return sum(1 for m in self._msgs if now - m.timestamp <= window_seconds)

    def __len__(self) -> int:
        return len(self._msgs)
