# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""通知投递泵（方案 §6.5/§6.11/§6.3 事务边界 5）。

时序（与 scheduling/delivery.py 同款纪律）::

    pending --(CAS claim)--> sending --(平台调用)--> sent
                                   │
                                   ├─ 发送前不可用 → pending（退避重试，有上限）
                                   └─ 调用异常/超时 → delivery_unknown（终态）

- **入口 ack 与后台泵用同一 CAS 竞争**：谁先 claim 谁发送，另一方放弃
  （§6.5：避免「当前聊天发送一次 ack，后台又发送一次」）；
- ``delivery_unknown`` 不自动重发；任务终态与投递状态分开（§6.2）；
- 平台调用**绝不**放在 SQLite 事务内；
- 脱敏：发送文本经 presentation 渲染，原始事件与日志不出库。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol

from .config import CometaConfig
from .models import NotificationState, utc_now
from .presentation import render_notification
from .store import CometaStore, NotificationRecord, StoreBusyError

_LOGGER = logging.getLogger("cometa.delivery")

DEFAULT_SEND_TIMEOUT_SECONDS = 30.0
DEFAULT_RETRY_BACKOFF_SECONDS = 60.0
DEFAULT_MAX_ATTEMPTS = 3


class SenderUnavailable(Exception):  # noqa: N818 - 可用性信号，不是错误
    """发送器未就绪（bot 不在线/账号不可用）——**平台调用从未发生**，
    可以退避重试。调用已发生但结果不明时必须抛普通异常（→ delivery_unknown）。"""


class NotificationSender(Protocol):
    """把渲染后的文本发到 target 描述的会话；返回平台回执或 None。

    target 是通知行里的 target dict（platform/bot_id/conversation_id/
    requester_id/reply_to_message_id/group_id/task_id）。payload 是通知行
    的原始 payload（final 通知携带 full_text_ref/full_text_chars，供
    长结果投递——QQ 文件/合并转发）。实现方负责按配置校验群允许状态与
    目标有效性（§6.11）。"""

    async def send(self, target: dict, text: str, payload: dict | None = None) -> str | None: ...


class _FunctionSender:
    """裸 async 函数 → NotificationSender 协议适配。"""

    def __init__(self, fn: Callable[[dict, str], Awaitable[str | None]]):
        self._fn = fn

    async def send(self, target: dict, text: str, payload: dict | None = None) -> str | None:
        return await self._fn(target, text, payload)


class NotificationPump:
    """pending → sending → sent/delivery_unknown 的执行者（一库一实例）。"""

    def __init__(
        self,
        store: CometaStore,
        sender: NotificationSender,
        *,
        config: CometaConfig | None = None,
        render: Callable[[NotificationRecord], str] | None = None,
        send_timeout_seconds: float = DEFAULT_SEND_TIMEOUT_SECONDS,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        poll_interval_seconds: float = 2.0,
    ):
        self.store = store
        # 协议适配：Sender 协议是带 .send 方法的对象，但接线层（QQ 桥接）传入的
        # 是裸 async 函数——统一包装，否则 pump 调 .send 时 AttributeError、
        # 所有通知被打成 delivery_unknown（2026-09-30 人工清单实测）。
        if callable(sender) and not hasattr(sender, "send"):
            self._sender = _FunctionSender(sender)
        else:
            self._sender = sender
        self._config = config
        self._send_timeout = max(float(send_timeout_seconds), 1.0)
        self._backoff = max(float(retry_backoff_seconds), 1.0)
        self._max_attempts = max(int(max_attempts), 1)
        self._poll = max(float(poll_interval_seconds), 0.5)
        self._render = render or self._default_render

    def _default_render(self, notification: NotificationRecord) -> str:
        task = self.store.get_task(notification.task_id)
        if task is None:
            return f"任务 {notification.task_id[:8]} 状态更新。"
        max_chars = self._config.result_max_chars if self._config else 2000
        return render_notification(task, notification, max_chars=max_chars)

    # ── 主循环 ───────────────────────────────────────────
    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            with contextlib.suppress(StoreBusyError):
                await self.pump_once()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._poll)

    async def pump_once(self, *, limit: int = 16) -> int:
        """投递一轮到期通知。返回成功发出的条数（不含 unknown/退避）。"""
        due = self.store.due_notifications(limit=limit)
        delivered = 0
        for notification in due:
            if await self.deliver_one(notification):
                delivered += 1
        return delivered

    async def deliver_one(self, notification: NotificationRecord) -> bool:
        claimed = self.store.claim_notification(notification.notification_id)
        if claimed is None:
            return False  # 入口已抢先（ack 竞争）或已被别人取走
        try:
            text = self._render(claimed)
        except Exception:
            _LOGGER.exception(
                "notification %s 渲染失败，跳过本次发送", claimed.notification_id[:8]
            )
            self.store.mark_notification(
                claimed.notification_id,
                state=NotificationState.PENDING,
                error="render_failed",
                next_attempt_at=utc_now() + timedelta(seconds=self._backoff),
            )
            return False
        try:
            receipt = await asyncio.wait_for(
                self._sender.send(claimed.target, text, claimed.payload),
                timeout=self._send_timeout,
            )
        except asyncio.TimeoutError:
            return self._unknown(claimed, f"send_timeout_after_{self._send_timeout:.0f}s")
        except SenderUnavailable as e:
            return self._retry_later(claimed, str(e))
        except Exception as e:
            return self._unknown(claimed, f"send_error: {type(e).__name__}")
        self.store.mark_notification(
            claimed.notification_id,
            state=NotificationState.SENT,
            receipt=str(receipt or ""),
        )
        _LOGGER.info(
            "notification %s（%s）已投递 task=%s",
            claimed.notification_id[:8],
            claimed.kind.value,
            claimed.task_id[:8],
        )
        return True

    # ── 内部 ─────────────────────────────────────────────
    def _unknown(self, claimed: NotificationRecord, error: str) -> bool:
        self.store.mark_notification(
            claimed.notification_id,
            state=NotificationState.DELIVERY_UNKNOWN,
            error=error[:200],
        )
        _LOGGER.warning(
            "notification %s 投递结果未知（%s）；不自动重发（方案 §6.5）",
            claimed.notification_id[:8],
            error,
        )
        return False

    def _retry_later(self, claimed: NotificationRecord, reason: str) -> bool:
        """发送**前**失败（调用从未发生）：退避重试，有上限（§6.11）。"""
        if claimed.send_attempts >= self._max_attempts:
            return self._unknown(claimed, f"exhausted_after_{claimed.send_attempts}: {reason}")
        self.store.mark_notification(
            claimed.notification_id,
            state=NotificationState.PENDING,
            error=reason[:200],
            next_attempt_at=utc_now() + timedelta(seconds=self._backoff),
        )
        return False


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETRY_BACKOFF_SECONDS",
    "DEFAULT_SEND_TIMEOUT_SECONDS",
    "NotificationPump",
    "NotificationSender",
    "SenderUnavailable",
]
