# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""有界、确定性的状态与结果表达（方案 §3.2 presentation）。

铁律（§6.11/§1.3 不变量 8）：

- 完整日志与文件**不进**聊天上下文；只输出有界摘要与产物引用；
- 只转述工作阶段、公开进展和工具执行事实，不转发推理全文、凭据或原始命令输出；
- 等待输入/失败必须如实呈现，不能显示成「仍在思考」（§1.3 不变量 6 的反面）；
- 没有可衡量总量时不生成百分比或预计完成时间。
"""

from __future__ import annotations

from .models import NotificationKind, Outcome, TaskState, VerificationStatus
from .store import NotificationRecord, TaskRecord

_STATE_LABELS = {
    TaskState.QUEUED: "已受理，排队中",
    TaskState.STARTING: "正在启动",
    TaskState.RUNNING: "正在执行",
    TaskState.WAITING_INPUT: "等待你补充信息",
    TaskState.WAITING_APPROVAL: "等待审批",
    TaskState.CANCELLING: "正在取消",
    TaskState.RECOVERING: "正在核对执行状态",
    TaskState.RECOVERY_REQUIRED: "需要管理员处理（执行状态无法确认）",
    TaskState.CANCELLED: "已取消",
    TaskState.SUCCEEDED: "已完成",
    TaskState.PARTIAL: "部分完成",
    TaskState.FAILED: "失败",
    TaskState.TIMED_OUT: "超时终止",
}

_OUTCOME_LABELS = {
    Outcome.SUCCEEDED: "已完成",
    Outcome.PARTIAL: "部分完成",
    Outcome.FAILED: "失败",
    Outcome.CANCELLED: "已取消",
}


def state_label(state: TaskState) -> str:
    return _STATE_LABELS.get(state, state.value)


def _clean(text: str, limit: int) -> str:
    """单行化 + 截断（不引入换行注入）。"""
    joined = " ".join(line.strip() for line in (text or "").splitlines() if line.strip())
    return joined[:limit]


def render_ack(task: TaskRecord, *, max_chars: int = 500) -> str:
    """受理确认（§6.5）：不等待 Agent 运行即可发送的确定性文案。"""
    return _clean(
        f"已受理外部任务（{short_id_of(task.task_id)}）：{task.spec.objective}。"
        f"完成后我会回报结果；发送「任务状态 {short_id_of(task.task_id)}」可随时查询。",
        max_chars,
    )


def render_progress(task: TaskRecord, payload: dict, *, max_chars: int = 500) -> str:
    head = f"任务 {short_id_of(task.task_id)}：{state_label(task.state)}"
    detail = _clean(str(payload.get("text") or payload.get("detail") or ""), 160)
    if detail:
        return _clean(f"{head}｜最近活动：{detail}", max_chars)
    # 无新活动也要说实话（§6.11：明确「仍在运行，最近一次活动是……」）
    if task.last_activity_at is not None:
        return _clean(f"{head}（最近活动 {_clean(task.last_activity_at.isoformat(), 19)}）", max_chars)
    return _clean(head, max_chars)


def render_input_request(task: TaskRecord, payload: dict, *, max_chars: int = 500) -> str:
    question = _clean(str(payload.get("question") or ""), 200)
    return _clean(
        f"任务 {short_id_of(task.task_id)} 需要你补充信息：{question or '（见任务详情）'}",
        max_chars,
    )


def render_final(task: TaskRecord, payload: dict, *, max_chars: int = 2000) -> str:
    """最终结果（§6.12 第 3 步：模板组合状态、产物与验证事实）。"""
    state = payload.get("state") or task.state.value
    outcome = payload.get("outcome") or ""
    head = f"任务 {short_id_of(task.task_id)} "
    if outcome and outcome in _OUTCOME_LABELS:
        head += f"{_OUTCOME_LABELS[outcome]}。"
    else:
        head += f"{_STATE_LABELS.get(task.state, state)}。"
    lines = [_clean(head, 200)]
    summary = _clean(str(payload.get("summary") or ""), max_chars - 300)
    if summary:
        lines.append(summary)
    if task.state in (TaskState.SUCCEEDED, TaskState.PARTIAL):
        verification = payload.get("verification") or ""
        if verification == VerificationStatus.UNVERIFIED.value:
            lines.append("注意：验收标准未经宿主确认，请自行核对。")
    return "\n".join(lines)


def render_notification(
    task: TaskRecord, notification: NotificationRecord, *, max_chars: int = 2000
) -> str:
    """泵发送前的统一渲染入口。"""
    if notification.kind is NotificationKind.ACK:
        return render_ack(task, max_chars=max_chars)
    if notification.kind is NotificationKind.PROGRESS:
        return render_progress(task, notification.payload, max_chars=max_chars)
    if notification.kind is NotificationKind.INPUT_REQUIRED:
        return render_input_request(task, notification.payload, max_chars=max_chars)
    return render_final(task, notification.payload, max_chars=max_chars)


def short_id_of(task_id: str) -> str:
    from .models import short_id

    return short_id(task_id)


__all__ = [
    "render_ack",
    "render_final",
    "render_input_request",
    "render_notification",
    "render_progress",
    "short_id_of",
    "state_label",
]
