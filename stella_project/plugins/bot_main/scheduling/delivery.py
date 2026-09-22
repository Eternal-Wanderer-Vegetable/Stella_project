# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""投递状态机与观测（计划 §6.7）。

核心时序（计划 §5 PDG 结论：**不沿用**旧主动发言的 mark-before-send 次序）::

    running --(有内容)--> ready --(CAS)--> sending --(平台回执)--> sent
                                              │
                                              ├─ 调用异常/超时 → delivery_unknown
    running --(on_content 且空)---------> silent
    任何一步 CAS 失败 -----------------> 放弃（租约已丢/状态被他人接管）

- ``sending`` 在平台调用**之前**持久化：进程在调用后、回执前死掉时，
  ``recover_expired_leases`` 把它判成 ``delivery_unknown``——这正是
  「不承诺 exactly-once」的落点；
- ``delivery_unknown`` 是终态：**绝不自动重投**，只接受人工 run-now（新运行）；
- 指纹（``result_fingerprint``）是内容级的确定性标记，供人工核对「这次重试
  是不是同一份内容」，不参与自动去重；
- 日志与 ``run_summary`` 只出 id/状态/计数/时延，**不出** prompt、目标全文
  与工具返回（脱敏是硬要求）。

QQ 适配器经 ``sender`` 注入（接线层包 ``bot.send_group_msg``，返回平台回执
字符串或 None），本模块对 NoneBot 零依赖，可独立测试。
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from nonebot import logger

from .models import NotificationMode, Run, RunState, Task, iso_utc
from .store import TaskStore

# 必须写 asyncio.TimeoutError：Python 3.10 下与内置 TimeoutError 是两个类
# （3.11 起才合并），写内置的会在 3.10 上漏接。

DEFAULT_SEND_TIMEOUT_SECONDS = 30.0


@dataclass(slots=True)
class DeliveryResult:
    """一次投递的结局（state 取 sent/silent/failed/delivery_unknown/cancelled）。"""

    state: RunState
    receipt: str = ""
    error: str = ""


# sender：把文本发进群；返回平台回执（如 message_id 字符串），拿不到回执返回
# None（此时**不**声称 exactly-once，只记 sent 且 receipt 为空）。
Sender = Callable[[int, str], Awaitable[str | None]]


def result_fingerprint(*, task_id: str, revision: int, run_key: str, text: str) -> str:
    """投递内容的确定性指纹（sha256 前 16 位）。

    ``run_key``：Cron 触发用 ``scheduled_for`` 的 ISO 串，人工运行用 request_id。
    同一任务、同一触发时刻、同一文案 → 同一指纹；人工比对重试是否重复全靠它。
    """
    normalized = "\n".join(line.rstrip() for line in text.strip().splitlines())
    payload = f"{task_id}:{revision}:{run_key}:{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def render_reminder(task: Task) -> str:
    """reminder 任务投递的就是 objective 本身（v1 不加模板修饰，所见即所配）。"""
    return task.objective.strip()


class DeliveryService:
    """ready → sending → sent/delivery_unknown 的执行者（一库一实例）。"""

    def __init__(
        self,
        store: TaskStore,
        *,
        sender: Sender,
        send_timeout_seconds: float = DEFAULT_SEND_TIMEOUT_SECONDS,
    ) -> None:
        self.store = store
        self._sender = sender
        self._send_timeout = max(float(send_timeout_seconds), 1.0)

    async def deliver(self, *, run: Run, task: Task, text: str) -> DeliveryResult:
        """把运行产物投进群。CAS 失败一律静默放弃（守不住租约就别发）。"""
        text = (text or "").strip()

        # 1. silent：策略允许的空产出
        if not text:
            if task.notification_mode is NotificationMode.ON_CONTENT:
                if self.store.transition_run(
                    run.run_id, run.lease_owner,
                    from_states=(RunState.RUNNING,), to_state=RunState.SILENT,
                ):
                    return DeliveryResult(state=RunState.SILENT)
                return DeliveryResult(state=RunState.CANCELLED, error="lease_lost")
            return self._fail(run, "empty_output")

        # 2. running → ready：先落结果与指纹，再进发送段
        run_key = run.scheduled_for_utc.isoformat() if run.scheduled_for_utc else run.request_id
        fingerprint = result_fingerprint(
            task_id=task.task_id, revision=run.task_revision, run_key=run_key, text=text
        )
        if not self.store.transition_run(
            run.run_id, run.lease_owner,
            from_states=(RunState.RUNNING,), to_state=RunState.READY,
            result_text=text, fingerprint=fingerprint,
        ):
            return DeliveryResult(state=RunState.CANCELLED, error="lease_lost")

        # 3. ready → sending：平台调用之前持久化（崩溃窗口语义的关键一步）
        if not self.store.transition_run(
            run.run_id, run.lease_owner,
            from_states=(RunState.READY,), to_state=RunState.SENDING,
        ):
            return DeliveryResult(state=RunState.CANCELLED, error="lease_lost")

        # 4. 发送（超时/异常都按 delivery_unknown：平台调用可能已实际发生）
        send_started = time.monotonic()
        try:
            receipt = await asyncio.wait_for(
                self._sender(task.group_id, text), timeout=self._send_timeout
            )
        except asyncio.TimeoutError:
            return self._unknown(run, f"send_timeout_after_{self._send_timeout:.0f}s")
        except Exception as e:
            return self._unknown(run, f"send_error: {type(e).__name__}")
        latency = time.monotonic() - send_started

        if not self.store.transition_run(
            run.run_id, run.lease_owner,
            from_states=(RunState.SENDING,), to_state=RunState.SENT,
            delivery_receipt=str(receipt or ""),
        ):
            return DeliveryResult(state=RunState.CANCELLED, error="lease_lost")
        self.store.record_delivered_message(task.group_id)
        logger.info(
            f"📤 [Scheduling] 任务 {task.task_id[:8]} 运行 {run.run_id[:8]} 已投递到群 "
            f"{task.group_id}（{latency:.1f}s，回执 {'有' if receipt else '无'}）"
        )
        return DeliveryResult(state=RunState.SENT, receipt=str(receipt or ""))

    # ── 内部 ─────────────────────────────────────────────
    def _fail(self, run: Run, reason: str) -> DeliveryResult:
        if self.store.transition_run(
            run.run_id, run.lease_owner,
            from_states=(RunState.RUNNING,), to_state=RunState.FAILED,
            error=reason,
        ):
            return DeliveryResult(state=RunState.FAILED, error=reason)
        return DeliveryResult(state=RunState.CANCELLED, error="lease_lost")

    def _unknown(self, run: Run, error: str) -> DeliveryResult:
        """发送调用超时/异常：delivery_unknown 终态，等人工 run-now。"""
        if self.store.transition_run(
            run.run_id, run.lease_owner,
            from_states=(RunState.SENDING,), to_state=RunState.DELIVERY_UNKNOWN,
            delivery_error=error[:200],
        ):
            logger.warning(
                f"⚠️ [Scheduling] 运行 {run.run_id[:8]} 投递结果未知（{error}）；"
                "不自动重投，需人工 定时立即 重试"
            )
            return DeliveryResult(state=RunState.DELIVERY_UNKNOWN, error=error)
        return DeliveryResult(state=RunState.CANCELLED, error="lease_lost")


def run_summary(run: Run, *, task: Task | None = None, now=None) -> dict:
    """运行的脱敏摘要（日志 / 状态接口用）：id、状态、计数、时延——无内容。"""
    from .models import utc_now

    now = now or utc_now()
    latency = None
    if run.claimed_at_utc is not None:
        end = run.finished_at_utc or now
        latency = round(max((end - run.claimed_at_utc).total_seconds(), 0.0), 2)
    summary: dict = {
        "run_id": run.run_id[:8],
        "task_id": run.task_id[:8],
        "revision": run.task_revision,
        "group_id": run.group_id,
        "state": run.state.value,
        "manual": run.is_manual,
        "scheduled_for": iso_utc(run.scheduled_for_utc) if run.scheduled_for_utc else None,
        "due_delay_seconds": (
            round(max((run.claimed_at_utc - run.scheduled_for_utc).total_seconds(), 0.0), 1)
            if run.claimed_at_utc and run.scheduled_for_utc
            else None
        ),
        "lease_owner": run.lease_owner or None,
        "model_rounds": run.model_rounds,
        "tool_calls": run.tool_calls,
        "result_chars": len(run.result_text),
        "fingerprint": run.fingerprint or None,
        "error": run.error or None,
        "delivery_error": run.delivery_error or None,
        "latency_seconds": latency,
    }
    if task is not None:
        summary["mode"] = task.mode.value
        summary["owner_id"] = task.owner_id
    return summary


__all__ = [
    "DEFAULT_SEND_TIMEOUT_SECONDS",
    "DeliveryResult",
    "DeliveryService",
    "Sender",
    "render_reminder",
    "result_fingerprint",
    "run_summary",
]
