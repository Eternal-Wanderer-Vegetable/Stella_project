# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""attempt 生命周期执行器（方案 §6.8 启动协议、§6.12 结果校验）。

时序（每次认领）::

    认领(claimed) → preparing → connecting(保存 session) → dispatching
      → start_turn → running(保存 turn handle)
      → 消费归一事件流（进度/输入/审批/取消检查）
      → 收集结果与产物 → 校验 → finish_task 同事务落终态

失败语义（方案 §1.3 不变量 5/7）：

- 启动结果不明（dispatching 窗口崩溃）→ recovery_required，**不盲目重发**；
- 流中断且无终态事件 → 核对（inspect）或 recovery_required，不重跑；
- Agent 自述完成 ≠ 成功：completed 只是「待结果校验」，executor 按预先保存
  的 acceptance_criteria 校验后才落业务终态；无法验证保留 limitations；
- 取消先确认停止再落终态；超时无法确认 → recovery_required。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from datetime import timedelta

from .artifacts import ArtifactCollector, ArtifactError, CollectedArtifact
from .backends.base import (
    AgentBackend,
    PolicyContext,
    TurnRequest,
    WorkspaceContext,
)
from .backends.registry import BackendRegistry
from .config import CometaConfig
from .models import (
    EventKind,
    EvidenceSource,
    InputRequestState,
    LaunchPhase,
    NotificationKind,
    Outcome,
    TaskState,
    VerificationStatus,
    utc_now,
)
from .store import (
    AttemptRecord,
    CometaStore,
    NotificationSpec,
    StaleLeaseError,
    TaskNotFoundError,
    TaskRecord,
)
from .workspace import WorkspaceError, WorkspaceManager, WorkspacePreparation

_LOGGER = logging.getLogger("cometa.executor")

# 输入等待轮询间隔（秒）：答复到达的感知延迟，与 DB 压力折中。
_INPUT_POLL_SECONDS = 1.0
# 消息增量的合并阈值：超过该字符数把缓冲刷成一条 progress 事件。
_DELTA_FLUSH_CHARS = 600
# 取消确认的等待上限（秒）；超时转 recovery_required（方案 §6.8）。
_CANCEL_CONFIRM_TIMEOUT_SECONDS = 30.0
# 静默流期间的取消轮询间隔（秒）：后端长时间不发事件也能被取消。
_CANCEL_POLL_SECONDS = 2.0

_STREAM_END = object()  # 流结束哨兵（泵任务放入队列）


@dataclass(slots=True)
class _StreamOutcome:
    """流消费的结局（executor 内部）。"""

    kind: str = ""  # completed | failed | interrupted | "" (流未给终态)
    text: str = ""
    error: str = ""
    usage: dict | None = None
    artifact_hint: str = ""  # completed 事件携带的产物线索（工作区内相对路径）


class AttemptExecutor:
    """驱动一个 attempt 从认领到终态。worker 为每个认领任务起一个它。"""

    def __init__(
        self,
        *,
        store: CometaStore,
        registry: BackendRegistry,
        workspaces: WorkspaceManager,
        artifacts: ArtifactCollector,
        config: CometaConfig,
        worker_id: str,
    ):
        self.store = store
        self.registry = registry
        self.workspaces = workspaces
        self.artifacts = artifacts
        self.config = config
        self.worker_id = worker_id
        # 测试可注入缩短：取消确认等待上限（§6.8 超时 → recovery_required）
        self.cancel_confirm_timeout = _CANCEL_CONFIRM_TIMEOUT_SECONDS

    # ============================================================
    # 主流程
    # ============================================================

    async def run_attempt(self, task: TaskRecord, attempt: AttemptRecord) -> None:
        """完整生命周期。**任何异常路径都必须让任务落到明确状态**。"""
        owner = attempt.lease_owner
        epoch = attempt.lease_epoch
        backend = self._resolve_backend(task)
        if backend is None:
            self._fail_fast(task, attempt, "backend_unresolved", "没有可用的后端")
            return

        probe = await backend.probe()
        if probe.state is not None and probe.state.value not in ("ready", "degraded"):
            self._fail_fast(
                task,
                attempt,
                "backend_probe_failed",
                f"后端探测未通过（{probe.state.value}）：{probe.reason}",
            )
            return

        request = TurnRequest(
            objective=task.spec.objective,
            context_excerpt=task.spec.context_excerpt,
            required_capabilities=list(task.spec.required_capabilities),
            acceptance_criteria=list(task.spec.acceptance_criteria),
            deadline_at=task.deadline_at,
            launch_token=f"{task.task_id}:{attempt.attempt_no}",
        )

        # ── 工作区（§6.9）──
        preparation: WorkspacePreparation | None = None
        if task.workspace_id:
            self.store.update_launch_phase(
                attempt.attempt_id, owner, epoch, LaunchPhase.PREPARING.value
            )
            try:
                ws_cfg = self.config.workspace_of(task.workspace_id)
                if ws_cfg is None:
                    raise WorkspaceError(
                        f"工作区 {task.workspace_id!r} 未在配置中声明"
                    )
                preparation = self.workspaces.prepare(ws_cfg, task.task_id)
            except WorkspaceError as e:
                self._fail_fast(task, attempt, "workspace_failed", str(e))
                return
            ws_ctx = WorkspaceContext(
                workspace_id=preparation.workspace_id,
                path=str(preparation.path),
                mode=preparation.mode,
                base_commit=preparation.base_commit,
                allow_write=self._allow_write(task),
            )
        else:
            ws_ctx = None

        profile_cfg = self.config.profile_of(task.profile)
        policy = PolicyContext(
            profile=task.profile,
            allow_network=bool(profile_cfg.allow_network) if profile_cfg else False,
            allow_workspace_write=self._allow_write(task),
        )

        try:
            # ── 连接后端，session 立即落库（§6.8 启动协议 2）──
            session = None
            self.store.update_launch_phase(
                attempt.attempt_id, owner, epoch, LaunchPhase.CONNECTING.value
            )
            session = await backend.open_session(request, ws_ctx, policy)
            self.store.update_launch_phase(
                attempt.attempt_id,
                owner,
                epoch,
                LaunchPhase.CONNECTING.value,
                session_id=session.session_id,
            )

            # ── dispatching：请求发出到 handle 落库之间是启动结果不明窗口 ──
            self.store.update_launch_phase(
                attempt.attempt_id, owner, epoch, LaunchPhase.DISPATCHING.value
            )
            turn = await backend.start_turn(session, request, request.launch_token)
            self.store.update_launch_phase(
                attempt.attempt_id,
                owner,
                epoch,
                LaunchPhase.RUNNING.value,
                turn_id=turn.turn_id,
            )
            self.store.transition_task(
                task.task_id,
                attempt_id=attempt.attempt_id,
                owner=owner,
                epoch=epoch,
                from_states=(TaskState.STARTING, TaskState.RECOVERING),
                to_state=TaskState.RUNNING,
                phase=LaunchPhase.RUNNING.value,
            )
        except Exception as e:
            # session 已建立但 start_turn 失败：结果明确（启动失败），落 failed
            self._fail_fast(task, attempt, "backend_start_failed", f"{type(e).__name__}: {e}")
            if session is not None:
                await self._safe_close(backend, session)
            return

        # ── 消费事件流 ──
        try:
            outcome = await self._consume_stream(task, attempt, backend, turn)
        except Exception as e:  # executor 自身或 store 异常：明确失败
            _LOGGER.exception("executor 流消费异常 task=%s", task.task_id[:8])
            self._fail_fast(
                task, attempt, "executor_error", f"{type(e).__name__}: {e}"
            )
            await self._safe_close(backend, session)
            return

        if outcome.kind == "" and outcome.error == "__cancelled__":
            # 取消路径已在 _consume_stream 内完成终态
            await self._safe_close(backend, session)
            return
        if outcome.kind == "":
            # 流中断且无终态事件：核对或 recovery_required（§6.8 恢复矩阵）
            await self._handle_dropped_stream(task, attempt, backend, turn)
            await self._safe_close(backend, session)
            return
        if outcome.kind == "interrupted":
            self._fail_fast(
                task,
                attempt,
                "backend_interrupted",
                outcome.error or "后端轮次被中断，未产生可用结果",
            )
            await self._safe_close(backend, session)
            return

        # ── 收集结果与产物（§6.12）──
        await self._finish_from_outcome(
            task, attempt, backend, turn, outcome, preparation
        )
        await self._safe_close(backend, session)

    # ============================================================
    # 事件流消费
    # ============================================================

    async def _consume_stream(
        self,
        task: TaskRecord,
        attempt: AttemptRecord,
        backend: AgentBackend,
        turn,
    ) -> _StreamOutcome:
        owner = attempt.lease_owner
        epoch = attempt.lease_epoch
        outcome = _StreamOutcome()
        delta_buffer: list[str] = []
        last_progress_notification = 0.0
        progress_interval = max(10.0, float(self.config.progress_interval_seconds))

        def maybe_notify_progress() -> "NotificationSpec | None":
            """长任务状态节流：最短合并间隔内的 progress 不再触发通知
            （§6.11——事件照常落库，只有通知被合并）。"""
            nonlocal last_progress_notification
            now_mono = time.monotonic()
            if now_mono - last_progress_notification < progress_interval:
                return None
            last_progress_notification = now_mono
            return NotificationSpec(
                kind=NotificationKind.PROGRESS,
                dedupe_key=f"progress:{task.task_id}",
                payload={},
                merge=True,
            )

        def flush_delta(force: bool = False) -> None:
            if not delta_buffer:
                return
            text = "".join(delta_buffer)
            if not force and len(text) < _DELTA_FLUSH_CHARS:
                return
            delta_buffer.clear()
            self.store.append_event(
                task.task_id,
                attempt_id=attempt.attempt_id,
                owner=owner,
                epoch=epoch,
                kind=EventKind.PROGRESS,
                payload={"kind": "message", "text": text[: self.config.result_max_chars]},
                backend_event_id="",
                notification=maybe_notify_progress(),
            )

        queue: asyncio.Queue = asyncio.Queue()

        async def _pump() -> None:
            """把后端事件搬进队列；异常与结束都以哨兵入队。"""
            try:
                async for ev in backend.stream(turn):
                    await queue.put(ev)
            except Exception as e:
                await queue.put(e)
            finally:
                await queue.put(_STREAM_END)

        pump_task = asyncio.create_task(_pump())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=_CANCEL_POLL_SECONDS
                    )
                except asyncio.TimeoutError:
                    # 必须写 asyncio.TimeoutError：3.10 下与内置 TimeoutError 不同类
                    if await self._check_cancel(task, attempt, backend, turn):
                        flush_delta(force=True)
                        outcome.kind = ""
                        outcome.error = "__cancelled__"
                        return outcome
                    continue
                if event is _STREAM_END:
                    break
                if isinstance(event, BaseException):
                    raise event
                # 每个事件先做取消/到期检查（§6.8：取消与完成竞争由终态 CAS 裁决）
                if await self._check_cancel(task, attempt, backend, turn):
                    flush_delta(force=True)
                    outcome.kind = ""
                    outcome.error = "__cancelled__"
                    return outcome
                kind = event.kind
                if kind == "message_delta":
                    delta_buffer.append(str(event.payload.get("delta", "")))
                    flush_delta()
                elif kind == "message_final":
                    delta_buffer.clear()
                    outcome.text = str(event.payload.get("text", ""))
                elif kind in ("phase", "command_record"):
                    flush_delta(force=True)
                    self.store.append_event(
                        task.task_id,
                        attempt_id=attempt.attempt_id,
                        owner=owner,
                        epoch=epoch,
                        kind=EventKind.PROGRESS,
                        payload={
                            "kind": kind,
                            "detail": _bounded_payload(event.payload),
                            "source": EvidenceSource.OBSERVED_TOOL_EVENT.value,
                        },
                        backend_event_id=event.backend_event_id or "",
                        notification=maybe_notify_progress(),
                    )
                elif kind == "usage":
                    outcome.usage = _merge_usage(outcome.usage, event.payload)
                elif kind in ("input_request", "approval_request"):
                    flush_delta(force=True)
                    answered = await self._handle_input_request(
                        task, attempt, backend, turn, event
                    )
                    if answered == "__cancelled__":
                        outcome.kind = ""
                        outcome.error = "__cancelled__"
                        return outcome
                    # 未答复（过期中断）→ 立即走取消收束（任务已被 expire 置 cancelling）
                    if answered == "__expired__":
                        await self._check_cancel(task, attempt, backend, turn)
                        outcome.kind = ""
                        outcome.error = "__cancelled__"
                        return outcome
                elif kind == "completed":
                    flush_delta(force=True)
                    outcome.kind = "completed"
                    outcome.text = outcome.text or str(event.payload.get("text", ""))
                    hint = event.payload.get("artifact") or event.payload.get("file")
                    if hint:
                        outcome.artifact_hint = str(hint)
                    break
                elif kind == "failed":
                    flush_delta(force=True)
                    outcome.kind = "failed"
                    outcome.error = str(event.payload.get("error", "unknown"))
                    break
                elif kind == "interrupted":
                    flush_delta(force=True)
                    outcome.kind = "interrupted"
                    outcome.error = str(event.payload.get("error", ""))
                    break
                else:
                    # 未知 kind：保留事实，不臆造语义
                    self.store.append_event(
                        task.task_id,
                        attempt_id=attempt.attempt_id,
                        owner=owner,
                        epoch=epoch,
                        kind=EventKind.PROGRESS,
                        payload={"kind": "unknown", "detail": _bounded_payload(event.payload)},
                        backend_event_id=event.backend_event_id or "",
                    )
        finally:
            if not pump_task.done():
                pump_task.cancel()
        flush_delta(force=True)
        return outcome

    # ============================================================
    # 输入/审批（§6.10）
    # ============================================================

    async def _handle_input_request(
        self,
        task: TaskRecord,
        attempt: AttemptRecord,
        backend: AgentBackend,
        turn,
        event,
    ) -> str:
        """登记输入请求并等待答复。返回 answered / __cancelled__ / __expired__。"""
        owner = attempt.lease_owner
        epoch = attempt.lease_epoch
        payload = event.payload
        kind = "approval" if event.kind == "approval_request" else "input"
        wait_seconds = float(self.config.limits.input_wait_seconds)
        expires_at = utc_now() + timedelta(seconds=wait_seconds)
        request_id = self.store.register_input_request(
            task.task_id,
            attempt_id=attempt.attempt_id,
            owner=owner,
            epoch=epoch,
            backend_request_id=str(payload.get("backend_request_id", "")),
            kind=kind,
            question=str(payload.get("question", ""))[:500],
            schema={"type": "string"},
            options=list(payload.get("options", [])),
            expires_at=expires_at,
        )
        if request_id is None:
            return "__expired__"
        while True:
            await asyncio.sleep(_INPUT_POLL_SECONDS)
            if await self._check_cancel(task, attempt, backend, turn):
                return "__cancelled__"
            request = self.store.get_input_request(request_id)
            if request is None or request.state is not InputRequestState.PENDING:
                # 已答复（service 落了 respond 控制命令）或已过期
                request = self.store.get_input_request(request_id)
                if request is not None and request.state is InputRequestState.ANSWERED:
                    result = await backend.respond(
                        turn,
                        str(payload.get("backend_request_id", "")),
                        request.answer,
                    )
                    if result.ok:
                        self.store.transition_task(
                            task.task_id,
                            attempt_id=attempt.attempt_id,
                            owner=owner,
                            epoch=epoch,
                            from_states=(TaskState.WAITING_INPUT, TaskState.WAITING_APPROVAL),
                            to_state=TaskState.RUNNING,
                            clear_waiting=True,
                        )
                        return "answered"
                    # 后端拒收答复：请求重开（不重放旧审批给新请求，§6.10）
                    self.store.append_event(
                        task.task_id,
                        attempt_id=attempt.attempt_id,
                        owner=owner,
                        epoch=epoch,
                        kind=EventKind.PROGRESS,
                        payload={"kind": "respond_rejected", "detail": result.detail},
                    )
                    continue
            if utc_now() >= expires_at:
                self.store.expire_stale_inputs()
                return "__expired__"

    # ============================================================
    # 取消（§6.8）
    # ============================================================

    async def _check_cancel(
        self, task: TaskRecord, attempt: AttemptRecord, backend: AgentBackend, turn
    ) -> bool:
        """任务被标 cancelling 时请求后端中断并收束。返回 True 表示已处理取消。"""
        current = self.store.get_task(task.task_id)
        if current is None or current.state is not TaskState.CANCELLING:
            return False
        owner = attempt.lease_owner
        epoch = attempt.lease_epoch
        started = time.monotonic()
        confirmed = False
        while time.monotonic() - started < self.cancel_confirm_timeout:
            result = await backend.cancel(turn)
            if result.ok and result.confirmed:
                confirmed = True
                break
            await asyncio.sleep(0.5)
        if not confirmed:
            self.store.mark_recovery_required(
                task.task_id,
                reason="cancel_unconfirmed",
            )
            return True
        partial_text = self.artifacts.read_final_text(task.task_id)
        summary = "任务已被用户取消。"
        if partial_text:
            summary = "任务已被用户取消；中断前产出的内容已保留。"
        # 完成先到时终态 CAS 裁决已定（§6.8）：吞掉租约冲突
        with contextlib.suppress(StaleLeaseError):
            self.store.finish_task(
                task.task_id,
                attempt_id=attempt.attempt_id,
                owner=owner,
                epoch=epoch,
                outcome=Outcome.CANCELLED,
                state=TaskState.CANCELLED,
                summary=summary,
                final_text_ref=(
                    self.artifacts.save_final_text(task.task_id, partial_text)
                    if partial_text
                    else ""
                ),
                limitations=["cancelled_by_user"],
                error="",
            )
        return True

    # ============================================================
    # 结果收集与校验（§6.12）
    # ============================================================

    async def _finish_from_outcome(
        self,
        task: TaskRecord,
        attempt: AttemptRecord,
        backend: AgentBackend,
        turn,
        outcome: _StreamOutcome,
        preparation: WorkspacePreparation | None,
    ) -> None:
        owner = attempt.lease_owner
        epoch = attempt.lease_epoch
        collected: list[CollectedArtifact] = []
        limitations: list[str] = []
        evidence: list[dict] = [
            {"source": EvidenceSource.AGENT_REPORTED.value, "fact": "backend_turn_terminal",
             "kind": outcome.kind}
        ]

        # 产物收集：只接受工作区内的允许文件（§6.12 第 4 步）
        if outcome.artifact_hint and preparation is not None:
            try:
                collected.append(
                    self.artifacts.collect(
                        task.task_id,
                        outcome.artifact_hint,
                        workspace_path=preparation.path,
                    )
                )
            except ArtifactError as e:
                limitations.append(f"artifact_rejected: {e}")

        # 验收判定：Agent 自述完成不能覆盖验收记录（§1.3 不变量 7）
        criteria = list(task.spec.acceptance_criteria)
        if outcome.kind == "completed":
            if not criteria:
                verification = VerificationStatus.NOT_REQUIRED
                state = TaskState.SUCCEEDED
                outcome_v = Outcome.SUCCEEDED
            else:
                # 首版宿主不自动执行验收命令（§6.12：不能为「验证」运行模型
                # 提供的新命令）；有未验证标准即如实标记
                verification = VerificationStatus.UNVERIFIED
                state = TaskState.PARTIAL
                outcome_v = Outcome.PARTIAL
                limitations.append("acceptance_criteria_unverified")
        else:
            verification = VerificationStatus.FAILED
            state = TaskState.FAILED
            outcome_v = Outcome.FAILED

        summary = self._build_summary(task, outcome, collected, limitations, verification)
        final_ref = ""
        if outcome.text:
            try:
                final_ref = self.artifacts.save_final_text(task.task_id, outcome.text)
            except ArtifactError as e:
                limitations.append(f"final_text_save_failed: {e}")
        manifest_ref = ""
        if collected:
            try:
                manifest_ref = self.artifacts.collect_manifest(task.task_id, collected)
            except (ArtifactError, OSError) as e:
                limitations.append(f"manifest_failed: {e}")

        try:
            self.store.finish_task(
                task.task_id,
                attempt_id=attempt.attempt_id,
                owner=owner,
                epoch=epoch,
                outcome=outcome_v,
                state=state,
                summary=summary,
                final_text_ref=final_ref,
                evidence=evidence,
                verification_status=verification,
                limitations=limitations,
                error=outcome.error if outcome.kind == "failed" else "",
                usage=outcome.usage or {},
                manifest_ref=manifest_ref,
                artifacts=[
                    {
                        "artifact_id": c.artifact_id,
                        "relative_storage_key": c.relative_storage_key,
                        "sha256": c.sha256,
                        "size": c.size,
                        "mime": c.mime,
                        "display_name": c.display_name,
                    }
                    for c in collected
                ],
            )
        except StaleLeaseError:
            # 取消竞争获胜：终态已由取消路径落库（§6.8）
            _LOGGER.info("task %s 终态已被其他路径裁决（取消竞争）", task.task_id[:8])

    def _build_summary(
        self,
        task: TaskRecord,
        outcome: _StreamOutcome,
        collected: list[CollectedArtifact],
        limitations: list[str],
        verification: VerificationStatus,
    ) -> str:
        """有界、确定性的结果摘要（模板组合，§6.12 第 3 步）。"""
        lines: list[str] = []
        if outcome.kind == "completed":
            if verification is VerificationStatus.NOT_REQUIRED:
                lines.append("任务完成。")
            else:
                lines.append("任务产出已完成，但验收标准未经宿主确认。")
        else:
            lines.append(f"任务失败：{outcome.error or '未知原因'}")
        if outcome.text:
            excerpt = outcome.text.strip().splitlines()[0][: self.config.result_max_chars // 2]
            if excerpt:
                lines.append(f"结果摘要：{excerpt}")
        if collected:
            names = "、".join(c.display_name for c in collected[:3])
            lines.append(f"产物：{names}")
        if limitations:
            lines.append(f"限制：{'；'.join(limitations[:3])}")
        return "\n".join(lines)[: self.config.result_max_chars]

    # ============================================================
    # 流中断与快速失败
    # ============================================================

    async def _handle_dropped_stream(
        self,
        task: TaskRecord,
        attempt: AttemptRecord,
        backend: AgentBackend,
        turn,
    ) -> None:
        """流断了且没有终态事件（§6.7：转 recovering，不是直接重发）。"""
        descriptor = await backend.describe()
        snapshot = None
        if descriptor.lifecycle.supports_inspect:
            try:
                snapshot = await backend.inspect(turn)
            except Exception:
                snapshot = None
        if snapshot is not None and snapshot.turn_completed:
            # 后端已完成而 cometa 未写结果 → 收集一次（恢复矩阵第 5 行）
            self._fail_fast(
                task,
                attempt,
                "completed_without_result",
                "后端已完成但事件流丢失，结果不可收集",
            )
            return
        if snapshot is not None and snapshot.turn_failed:
            self._fail_fast(task, attempt, "backend_failed", "后端报告轮次失败")
            return
        self.store.mark_recovery_required(
            task.task_id,
            reason="stream_dropped_unknown_state",
        )

    def _fail_fast(self, task: TaskRecord, attempt: AttemptRecord, code: str, detail: str) -> None:
        """把任务落为明确失败。租约已丢时放弃（有人接管了）。"""
        try:
            self.store.finish_task(
                task.task_id,
                attempt_id=attempt.attempt_id,
                owner=attempt.lease_owner,
                epoch=attempt.lease_epoch,
                outcome=Outcome.FAILED,
                state=TaskState.FAILED,
                summary=f"任务失败：{detail}"[: self.config.result_max_chars],
                error=code,
                evidence=[{"source": EvidenceSource.HOST_CHECKED.value, "fact": code}],
            )
        except (StaleLeaseError, TaskNotFoundError) as e:
            _LOGGER.info("task %s 快速失败未落库（%s）", task.task_id[:8], e)

    # ============================================================
    # 恢复（worker 启动时调用；方案 §6.8 恢复矩阵）
    # ============================================================

    def recover_task(self, task: TaskRecord, attempt: AttemptRecord) -> str:
        """按 launch_phase + 任务状态决定崩溃窗口的处理。返回处理结果说明。

        首版无跨进程 inspect（worker 进程已死、后端句柄不可达），因此：
        - 任务仍是 starting 且启动协议保证未发出请求（claimed/preparing/
          connecting-无 session）→ 回队重备（恢复矩阵第 2 行）；
        - 其余一切（running/waiting/dispatching/starting-但已过 connecting）：
          turn 是否创建/是否仍在执行不明 → recovery_required
          （第 3、8 行：不启动第二份执行）。
        """
        if not self.store.begin_recovery(task.task_id):
            return "already_handled"
        phase = attempt.launch_phase
        dispatched = task.state in (
            TaskState.RUNNING,
            TaskState.WAITING_INPUT,
            TaskState.WAITING_APPROVAL,
            TaskState.CANCELLING,
        )
        safe_to_requeue = (
            task.state is TaskState.STARTING
            and not dispatched
            and (
                phase in (LaunchPhase.CLAIMED.value, LaunchPhase.PREPARING.value)
                or (phase == LaunchPhase.CONNECTING.value and not attempt.session_id)
            )
        )
        if safe_to_requeue and self.store.requeue_task(
            task.task_id, reason=f"crash_before_dispatch:{phase}"
        ):
            return "requeued"
        self.store.mark_recovery_required(
            task.task_id,
            reason=f"crash_after_dispatch:{phase}",
        )
        return "recovery_required"

    # ============================================================
    # 内部
    # ============================================================

    def _resolve_backend(self, task: TaskRecord) -> AgentBackend | None:
        backend_cfg = self.config.backend_of(task.backend_id)
        if backend_cfg is None or not backend_cfg.enabled:
            return None
        try:
            return self.registry.create(backend_cfg)
        except KeyError:
            return None

    def _allow_write(self, task: TaskRecord) -> bool:
        profile = self.config.profile_of(task.profile)
        if profile is None:
            return False
        return bool(profile.allow_workspace_write)

    async def _safe_close(self, backend: AgentBackend, session) -> None:
        if session is None:
            return
        try:
            await backend.close(session)
        except Exception:
            _LOGGER.debug("backend close 失败（忽略）", exc_info=True)


def _bounded_payload(payload: dict, limit: int = 400) -> str:
    import json

    try:
        text = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(payload)
    return text[:limit]


def _merge_usage(current: dict | None, payload: dict) -> dict:
    merged = dict(current or {})
    for key, value in payload.items():
        if isinstance(value, (int, float)) and isinstance(merged.get(key), (int, float)):
            merged[key] = merged[key] + value
        else:
            merged[key] = value
    return merged


__all__ = ["AttemptExecutor"]
