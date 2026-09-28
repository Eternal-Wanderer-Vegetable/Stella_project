# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""逐段发送 + 回执收集（计划 §6.1「发送改造」的公共实现）。

三个发送入口（普通回复 / 主动 @ / 主动群聊）统一走这里：

- 逐段 ``send_one(line, part_index)`` → 每段一个 :class:`DeliveryReceipt`；
  平台消息 ID 只有真实拿到才记录（引用归因的锚点）；
- 某段明确失败（平台异常）→ 该段 failed，**停止后续片段**（已 ACK 的片段
  不可撤销；继续发只会扩大半成功面），聚合状态由调用方计算（partial/failed）；
- 网络超时等不确定失败按 unknown 处理的判定在平台适配层做不到——适配器
  抛什么异常这里无法区分，统一按 failed 记录并保留错误文本；unknown 只来自
  「发送成功但落库失败」与取消中断；
- 每段回执**立即落库**（短事务、失败静默）：进程在多段发送中途崩溃时，
  已发事实不丢；
- ``FinishedException``（NoneBot matcher 结束控制流）原样上抛，绝不当作
  发送失败。

本模块不 import 网关、不知道 NoneBot matcher 的存在（send_one 由调用方
闭包提供），因此可以脱离机器人运行时单测。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from nonebot import logger
from nonebot.exception import FinishedException

from core.social.contracts import (
    DELIVERY_ACKNOWLEDGED,
    DELIVERY_FAILED,
    DELIVERY_UNKNOWN,
    ConversationScope,
    DeliveryReceipt,
    aggregate_delivery_status,
    utc_now_iso,
)
from memory import social_store

SendOne = Callable[[str, int], Awaitable[str | None]]


def coerce_platform_message_id(result) -> str | None:
    """把平台 send 调用的返回值规约为消息 ID 字符串；拿不到返回 None。

    OneBot v11 的 ``bot.send_group_msg`` 返回 ``{"message_id": int}`` 字典；
    NoneBot ``Matcher.send`` 透传适配器返回值。识别不了的一律 None——
    宁可没有归因锚点，不猜一个假 ID。
    """
    if result is None:
        return None
    if isinstance(result, bool):
        return None
    if isinstance(result, int):
        return str(result)
    if isinstance(result, dict):
        mid = result.get("message_id")
        return str(mid) if mid is not None else None
    text = str(result)
    return text if text.isdigit() else None


async def deliver_lines(
    lines: list[str],
    *,
    scope: ConversationScope | None,
    trace_id: str,
    turn_id: str,
    epoch: int = 0,
    send_one: SendOne,
    interval_seconds: float = 0.0,
    stop_on_failure: bool = True,
    abort_check: Callable[[], bool] | None = None,
) -> list[DeliveryReceipt]:
    """逐段发送并收集回执。scope 为 None 时只发送、不落库（社交总开关关闭）。

    ``abort_check``（计划 §6.9 层 3）：每个片段发送前调用，返回 True 表示
    本轮输出已过期（转题/撤销/静音/新直接请求）——停止后续片段并保留已
    收回执；已 ACK 的片段不可撤销，聚合状态按已尝试片段计算（partial 语义）。
    返回已尝试片段的回执列表（未尝试的片段没有事实，不产生行）。
    """
    receipts: list[DeliveryReceipt] = []
    started_at = time.monotonic()
    for i, line in enumerate(lines):
        if i > 0 and interval_seconds > 0:
            await asyncio.sleep(interval_seconds)
        if abort_check is not None and abort_check():
            logger.info(f"[Delivery] 发送中止（输出已过期）：段 {i}/{len(lines)} 未发送")
            break
        try:
            platform_id = coerce_platform_message_id(await send_one(line, i))
            status = DELIVERY_ACKNOWLEDGED
        except FinishedException:
            raise
        except asyncio.CancelledError:
            # 取消中断：该段结果不明（平台可能已收到），绝不重发
            _append_and_persist(
                receipts, scope, trace_id, turn_id, epoch, i,
                status=DELIVERY_UNKNOWN, text=line, platform_id=None, detail="cancelled",
            )
            raise
        except Exception as e:
            logger.warning(f"[Delivery] 群 {scope.group_id if scope else '?'} "
                           f"第 {i + 1}/{len(lines)} 段发送失败: {e}")
            _append_and_persist(
                receipts, scope, trace_id, turn_id, epoch, i,
                status=DELIVERY_FAILED, text=line, platform_id=None, detail=str(e)[:160],
            )
            if stop_on_failure:
                break
            continue
        _append_and_persist(
            receipts, scope, trace_id, turn_id, epoch, i,
            status=status, text=line, platform_id=platform_id,
        )
    _trace_delivery(trace_id, turn_id, scope, receipts, started_at)
    return receipts


def _trace_delivery(trace_id: str, turn_id: str, scope: ConversationScope | None,
                    receipts: list[DeliveryReceipt], started_at: float | None) -> None:
    """投递事实入追踪（计划 §6.8 delivery 阶段）：metadata 恒记，detailed 按群。"""
    if not receipts:
        return
    try:
        from core.observability import turn_trace

        statuses = [r.status for r in receipts]
        scope_str = f"qq:{scope.group_id}" if scope else ""
        turn_trace.record_event(
            trace_id=trace_id, turn_id=turn_id, stage="delivery",
            status=aggregate_delivery_status(statuses),
            scope=scope_str, started_at=started_at,
            metrics={"segments": len(receipts),
                     "acknowledged": statuses.count("acknowledged"),
                     "failed": statuses.count("failed"),
                     "unknown": statuses.count("unknown")},
            detailed={
                "receipts": [
                    {"part": r.part_index, "status": r.status,
                     "platform_message_id": r.platform_message_id,
                     "text": r.text}
                    for r in receipts
                ],
            }
            if turn_trace.detailed_enabled_for_scope(scope_str) else None,
        )
    except Exception:
        pass


def _append_and_persist(
    receipts: list[DeliveryReceipt],
    scope: ConversationScope | None,
    trace_id: str,
    turn_id: str,
    epoch: int,
    part_index: int,
    *,
    status: str,
    text: str,
    platform_id: str | None,
    detail: str = "",
) -> DeliveryReceipt:
    receipt = DeliveryReceipt(
        trace_id=trace_id,
        turn_id=turn_id,
        part_index=part_index,
        status=status,
        epoch=epoch,
        platform_message_id=platform_id,
        acknowledged_at_utc=utc_now_iso() if status == DELIVERY_ACKNOWLEDGED else "",
        text=text,
        scope=scope,
    )
    receipts.append(receipt)
    if scope is not None and not social_store.record_delivery(receipt):
        # 落库失败 = 发送成功但事实缺档（unknown 降级）：记日志，不阻塞后续片段
        logger.warning(f"[Delivery] 回执落库失败（turn={turn_id} part={part_index}）")
    if detail and status == DELIVERY_UNKNOWN:
        logger.info(f"[Delivery] 段 {part_index} 状态 unknown: {detail}")
    return receipt
