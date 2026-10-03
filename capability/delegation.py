# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""委派意图选择器（方案 §6.4）：聊天请求 → 委派意图；**不启动子进程**。

输入是可信 Origin、用户文本、现有路由结果与 cometa 能力快照；输出
``local | delegate | clarify | unavailable``（另有四类显式控制命令）。

执行顺序（§6.4）：

1. 无可信 Origin、主动插话 intent、功能关闭 → 原路径；禁止从被动群聊、
   通知文本或 Agent 输出自动生成任务；
2. 明确 cometa 命令或明确指定后端 → 确定性解析；缺必要信息先澄清；
3. 自动模式（COMETA_DELEGATION_MODE=auto，单独灰度）：规则判定编码/调研
   类请求；现有可靠短工具仍走 Comes；
4. 用户点名但后端不可用 → 明确告知原因，不静默换厂商；
5. 委派选中后整个请求由 cometa 负责，本轮不再执行同目标的 Comes/Skills；
   Memory 的门控不改变（钩子层负责）。

所有规则都是**确定性**的：不靠「模型自称不会」触发执行，无法确定时继续
聊天（§6.4.6）。本模块 import cometa 内核但只在钩子路径被调用。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from core.context import ChatContext

_LOGGER = logging.getLogger("cometa.delegation")

# ── 显式命令（§6.14 QQ 命令建议）────────────────────────────
# 委派 <后端?> <目标>   —— backend 可省略（按 profile 默认）
# 任务状态 <id> / 任务结果 <id> / 取消任务 <id> / 任务补充 <id> <内容>
_DELEGATE_RE = re.compile(r"^委派\s+(?P<rest>.+)$")
_STATUS_RE = re.compile(r"^任务状态\s*(?P<ref>\S+)$")
_RESULT_RE = re.compile(r"^任务结果\s*(?P<ref>\S+)$")
_CANCEL_RE = re.compile(r"^取消任务\s*(?P<ref>\S+)$")
_INPUT_RE = re.compile(r"^任务补充\s+(?P<ref>\S+)\s+(?P<content>.+)$")

# 自动委派的保守信号（§7 M3 门槛：联网能力缺口 + 复杂编码）。
# 词表刻意收窄：误委派的代价（外部 Agent 动代码）远高于漏委派。
_CODING_SIGNALS = (
    "实现", "重构", "编写", "写一个", "写个", "修复", "排查", "复现",
    "单元测试", "跑测试", "编译", "脚本", "补丁", "重构一下",
)
_RESEARCH_SIGNALS = ("调研", "搜索", "查一下", "最新进展", "资料", "综述")
_MIN_OBJECTIVE_CHARS = 12

_ACTION_LABELS = {
    "local": "继续聊天",
}


@dataclass(slots=True)
class Decision:
    """委派判定结论（§6.4 输出 + 显式命令解析结果）。"""

    action: str  # local | delegate | status | result | cancel | input | clarify | unavailable
    reason_code: str = ""
    backend_preference: str = ""
    objective: str = ""
    task_ref: str = ""
    content: str = ""
    message: str = ""  # clarify/unavailable 时给用户的解释


def parse_command(text: str) -> Decision | None:
    """确定性解析显式 cometa 命令；不是命令返回 None（继续走自动判定/本地路径）。

    WebChat 管理页与 QQ 共用同一套词。多条待答问题必须用「任务补充 <id>
    <request_id> <内容>」或引用对应消息（§6.14）——首版先支持带 request_id 的
    第三段形态，纯文本补充由服务层解析唯一 pending 请求。
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    input_match = _INPUT_RE.match(stripped)
    if input_match:
        return Decision(
            action="input",
            task_ref=input_match.group("ref"),
            content=input_match.group("content").strip(),
            reason_code="explicit_command",
        )
    for pattern, action in (
        (_STATUS_RE, "status"),
        (_RESULT_RE, "result"),
        (_CANCEL_RE, "cancel"),
    ):
        match = pattern.match(stripped)
        if match:
            return Decision(
                action=action, task_ref=match.group("ref"), reason_code="explicit_command"
            )
    delegate_match = _DELEGATE_RE.match(stripped)
    if delegate_match:
        rest = delegate_match.group("rest").strip()
        parts = rest.split(None, 1)
        if len(parts) == 2:
            # 「委派 <后端> <目标>」：首段是后端点名（可为空目标 → 澄清）
            backend, objective = parts
            if not objective:
                return Decision(
                    action="clarify",
                    reason_code="explicit_command",
                    message=f"请描述要委派给 {backend} 的目标。",
                )
            return Decision(
                action="delegate",
                backend_preference=backend,
                objective=objective.strip(),
                reason_code="explicit_command",
            )
        # 单片段：无法区分「后端名」与「目标」。过短按澄清处理（§6.4.2），
        # 足够长视为无后端点名的目标（按 profile 默认后端）。
        if len(rest) < 8:
            return Decision(
                action="clarify",
                reason_code="explicit_command",
                message="请描述要委派的目标，例如：委派 codex 给 utils.py 的排序函数补测试。",
            )
        return Decision(
            action="delegate",
            objective=rest,
            reason_code="explicit_command",
        )
    return None


def _has_any(text: str, words) -> bool:
    return any(word in text for word in words)


def decide_auto(ctx: ChatContext, route) -> Decision:
    """自动模式判定（保守规则；M3 只对指定用户/群灰度）。"""
    message = ctx.message or ""
    # 主动发言/插话永不委派（§6.4.1）
    if ctx.intent.startswith("proactive") or ctx.trigger != "reply":
        return Decision(action="local", reason_code="proactive_not_allowed")
    if route is not None and getattr(route, "deterministic", False):
        # 确定性路由命中 = 有可靠短工具，走 Comes（§6.4.3）
        return Decision(action="local", reason_code="deterministic_tool_available")
    if _has_any(message, _CODING_SIGNALS) and len(message) >= _MIN_OBJECTIVE_CHARS:
        return Decision(action="delegate", reason_code="auto_coding_signal",
                        objective=message)
    if _has_any(message, _RESEARCH_SIGNALS) and not getattr(route, "tool", False):
        # 本地路由认为没有工具可用：联网/长程调研是能力缺口（§7 M3）
        return Decision(action="delegate", reason_code="auto_research_gap",
                        objective=message)
    return Decision(action="local", reason_code="no_signal")


def decide(ctx: ChatContext, route, *, delegation_mode: str) -> Decision:
    """主选择器：显式命令优先，其次自动模式（§6.4 顺序 2→3）。"""
    command = parse_command(ctx.message or "")
    if command is not None:
        return command
    if delegation_mode != "auto":
        return Decision(action="local", reason_code="explicit_only_mode")
    return decide_auto(ctx, route)


# ============================================================
# 钩子入口：受理与控制命令执行
# ============================================================


def _resolve_task_ref(service, origin, ref: str) -> str | None:
    """短 ID → 完整 task_id；歧义/未命中返回 None（调用方回候选或要求完整 ID）。"""

    tasks = service.store.list_tasks(origin["instance_id"], requester_id=str(origin["requester_id"]))
    exact = [t for t in tasks if t.task_id == ref]
    if exact:
        return exact[0].task_id
    candidates = [t for t in tasks if t.task_id.startswith(ref)]
    if len(candidates) == 1:
        return candidates[0].task_id
    if len(candidates) > 1:
        return None  # 歧义：要求完整 ID（§6.1 短 ID 冲突必须返回候选）
    return None


def _pending_request_for(service, task_id: str, explicit_request_id: str = ""):
    """任务当前唯一的 pending 输入请求；带 explicit_request_id 时精确匹配。"""
    from cometa.models import InputRequestState

    for event in reversed(service.store.events_page(task_id, limit=500)):
        if event.kind.value in ("input_required", "approval_required"):
            request_id = str(event.payload.get("request_id", ""))
            if explicit_request_id and request_id != explicit_request_id:
                continue
            record = service.store.get_input_request(request_id)
            if record is not None and record.state is InputRequestState.PENDING:
                return record
    return None


def _origin_of(ctx: ChatContext) -> dict | None:
    origin = ctx.cometa_origin
    if isinstance(origin, dict) and origin.get("requester_id"):
        return origin
    return None


def _flow_on_submit(ctx: ChatContext, receipt) -> None:
    """受理事实入流程（计划 §6.3 G）：提交决策 + 独立 cometa root + 关联。

    任务执行可能跨进程，root 在受理时即创建（worker 经 by_source_key
    复用同一 root）；关联是显式 relation，不依赖 ContextVar 跨进程。
    """
    try:
        from core.observability import message_flow

        fctx = message_flow.flow_of(ctx)
        if fctx is not None and not fctx.ended:
            message_flow.decision(
                fctx, "delegation.submit", status="succeeded",
                metrics={"task_id": receipt.task_id[:8]})
        task_key = f"cometa:{receipt.task_id}"
        root = message_flow.by_source_key(task_key)
        if root is None:
            root = message_flow.begin_trace(
                root_kind="cometa_task", platform="cometa", scope="",
                source_message_key=task_key)
        if fctx is not None:
            message_flow.link(fctx.trace_id, root.trace_id,
                              kind="spawned", evidence="delegation_submit")
    except Exception:
        pass


async def handle_delegation_turn(ctx: ChatContext, route) -> bool:
    """委派层接管本轮则返回 True（已写 ctx.reply/lines，prepare_turn 直回）。

    **绝不抛异常**（钩子层也兜底）：cometa 出任何问题的后果是「本轮当普通
    聊天处理」，不是「Stella 不说话」。所有服务调用都是短事务，经
    asyncio.to_thread 执行，不等待 Agent 最终结果（§1.3 不变量 3）。
    """
    try:
        return await _handle(ctx, route)
    except Exception as e:
        _LOGGER.warning("cometa 委派分支异常（按本地路径处理）: %r", e)
        return False


async def _handle(ctx: ChatContext, route) -> bool:
    from config import settings

    if not getattr(settings, "COMETA_ENABLED", False):
        return False
    origin = _origin_of(ctx)
    if origin is None:
        return False  # 被动/主动路径：委派只由用户显式请求触发（§6.4.1）
    from cometa import runtime as cometa_runtime

    service = cometa_runtime.current_service()
    if service is None:
        _LOGGER.info("cometa 已启用但 runtime 未装配，本轮按普通聊天处理")
        return False

    decision = decide(ctx, route, delegation_mode=settings.COMETA_DELEGATION_MODE)
    if decision.action == "local":
        return False

    actor_kind = "webchat_admin" if origin.get("platform") == "webchat" else "qq_user"
    from cometa.service import Actor

    actor = Actor(kind=actor_kind, id=str(origin.get("requester_id", "")))
    loop = asyncio.get_running_loop()

    if decision.action == "delegate":
        from cometa.service import InvalidRequestError, SubmissionPendingError

        try:
            receipt = await loop.run_in_executor(
                None,
                lambda: _submit_delegate(service, origin, decision),
            )
        except InvalidRequestError as e:
            # 点名后端不可用 / 越权：明确告知原因，不静默换厂商（§6.4.4）
            ctx.reply = f"未能受理委派：{e}"
            ctx.lines = [ctx.reply]
            return True
        except SubmissionPendingError:
            ctx.reply = (
                "提交状态待确认（数据库繁忙）。请稍后用「任务状态」查询，"
                "不要重复提交同一目标。"
            )
            ctx.lines = [ctx.reply]
            return True
        if receipt is None:
            return False  # 提交未成功：按普通聊天继续（不做假回执）
        _flow_on_submit(ctx, receipt)
        return _set_ack(ctx, service, receipt)

    if decision.action in ("status", "result", "cancel", "input"):
        text = await loop.run_in_executor(
            None,
            lambda: _execute_control(service, origin, actor, decision),
        )
        if not text:
            return False
        ctx.reply = text
        ctx.lines = [text]
        return True

    if decision.action in ("clarify", "unavailable"):
        ctx.reply = decision.message
        ctx.lines = [decision.message]
        return True
    return False


def _submit_delegate(service, origin: dict, decision: Decision):
    """受理委派（短事务）。幂等键 = 来源请求 ID（同轮重放天然幂等）。"""
    from cometa.models import Origin as CometaOrigin
    from cometa.models import TaskSpec
    from cometa.service import Actor

    spec = TaskSpec(
        objective=decision.objective,
        backend_preference=decision.backend_preference,
    )
    cometa_origin = CometaOrigin.from_dict(origin)
    actor = Actor(
        kind="webchat_admin" if origin.get("platform") == "webchat" else "qq_user",
        id=str(origin.get("requester_id", "")),
    )
    return service.submit(
        spec,
        actor=actor,
        origin=cometa_origin,
        idempotency_key=f"turn:{origin.get('source_request_id', '')}",
    )


def _set_ack(ctx: ChatContext, service, receipt) -> bool:
    """写受理确认（§6.5）：ctx 携带 ack 通知 ID，不标记已发送。"""
    from cometa.presentation import render_ack

    task = service.store.get_task(receipt.task_id)
    if task is None:
        return False
    ack_text = render_ack(task)
    ctx.cometa_submission = {
        "task_id": receipt.task_id,
        "accepted_at": receipt.accepted_at.isoformat(),
        "ack_notification_id": receipt.ack_notification_id,
        "ack_text": ack_text,
    }
    ctx.reply = ack_text
    ctx.lines = [ack_text]
    return True


def _execute_control(service, origin: dict, actor, decision: Decision) -> str:
    """任务状态/结果/取消/补充的确定性执行，返回有界文本（空 = 静默放弃）。"""
    from cometa.models import Outcome, TaskState
    from cometa.service import InvalidRequestError, NotAuthorizedError

    task_id = _resolve_task_ref(service, origin, decision.task_ref)
    if task_id is None:
        return f"没有找到任务 {decision.task_ref}；请提供完整任务 ID（可用任务状态查询）。"
    try:
        if decision.action == "status":
            snapshot = service.get(task_id, actor=actor)
            from cometa.presentation import state_label

            return f"任务 {task_id[:8]}：{state_label(snapshot.state)}。"
        if decision.action == "result":
            result = service.result(task_id, actor=actor)
            outcome = {
                Outcome.SUCCEEDED: "已完成",
                Outcome.PARTIAL: "部分完成",
                Outcome.FAILED: "失败",
                Outcome.CANCELLED: "已取消",
            }.get(result.outcome, result.outcome.value)
            text = f"任务 {task_id[:8]} {outcome}。\n{result.summary}".strip()
            if result.artifacts:
                names = "、".join(a.display_name for a in result.artifacts[:3])
                text += f"\n产物：{names}"
            return text[:2000]
        if decision.action == "cancel":
            _status, state = service.cancel(
                task_id, actor=actor, idempotency_key=f"turn-cancel:{origin.get('source_request_id', '')}"
            )
            if state is TaskState.CANCELLED:
                return f"任务 {task_id[:8]} 已取消。"
            if state in (TaskState.QUEUED, TaskState.CANCELLING):
                return f"已请求取消任务 {task_id[:8]}，确认停止后我会回报。"  # 不提前声称已取消（§6.1）
            return f"任务 {task_id[:8]} 当前状态不允许取消（{state.value}）。"
        if decision.action == "input":
            request = _pending_request_for(service, task_id)
            if request is None:
                return f"任务 {task_id[:8]} 当前没有待回答的问题。"
            service.respond(
                task_id,
                request.request_id,
                decision.content,
                actor=actor,
                expected_revision=request.revision,
            )
            return f"已把补充信息转给任务 {task_id[:8]}。"
    except NotAuthorizedError:
        return "这不是你的任务，无法操作。"
    except InvalidRequestError as e:
        return f"操作未完成：{e}"
    return ""


__all__ = [
    "Decision",
    "decide",
    "decide_auto",
    "handle_delegation_turn",
    "parse_command",
]
