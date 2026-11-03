# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆采集就绪门（AI-gated memory capture，计划 v2 §6.1）。

所有入站消息的记忆采集在 ``CONSOLIDATION`` 角色被**证实可用**之前一律
fail-closed：门开着才允许把收到的消息与自动派生内容落库；门关着时收到的
消息**不排队、不回放、不补录**——就绪恢复后从下一条新消息开始采集。

状态机（全程进程内，不持久化、无 schema 迁移）：

- ``starting``：刚安装、还没探过（关门）；
- ``probing``：探针在途（关门）；
- ``ready``：最近一次探针成功且租约未过期（开门）；
- ``unavailable``：探针失败 / 真实整合调用失败 / 已停止（关门）。

关键约束（计划 §6.1，实现逐条对应）：

1. ``capture_allowed()`` 同步、无副作用、默认 False；除状态外还比较单调
   时钟与租约到期点——事件循环被调度延迟拖住时不会把过期 READY 一直开着；
2. 探针走 ``backend_for(ROLE_CONSOLIDATION)`` 的**同一条生成路径**（含降级
   链），只发一条有界最小补全请求；不要求 ``/v1/models``（在线服务商可以
   不开放），不发会话数据，不落探针正文；
3. epoch 单调递增围栏：真实生成失败立即关门并 bump epoch，迟到的旧探针
   成功结果直接弃用——晚到的成功永远翻不了比它新的失败；
4. 单飞：同一时刻至多一个探针在途；不可用时指数退避（interval 起、封顶
   ``_BACKOFF_MAX_SECONDS``）；
5. 快照只含脱敏事实（状态/槽名/计数/错误类别），绝不含 URL、API key、
   探针请求或响应正文。

没有旁路开关：操作员绕过验证直接开门等于重新引入无界积压（计划 §12 开放
问题 5 的定案），v1 不提供。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from nonebot import logger

from gravitas.contracts import ScopeKind
from gravitas.dependency_recovery import (
    DependencyRecovery,
    DependencyScope,
    FailureKind,
    classify_dependency_failure,
    dependency_recovery,
)

# ── 采集结果码（record_message 的 capture 契约，计划 §6.2） ──
CAPTURE_RESULT_OK = "captured"
CAPTURE_RESULT_DENIED = "not_captured_unavailable"

# ── 状态与原因码：都是有界枚举值，可直接进状态接口 ──
STATE_STARTING = "starting"
STATE_READY = "ready"
STATE_UNAVAILABLE = "unavailable"
STATE_PROBING = "probing"

REASON_NOT_STARTED = "not_started"
REASON_LEASE_EXPIRED = "lease_expired"
REASON_SHUTDOWN = "shutdown"

# 探针请求正文：固定两个字，不携带任何会话内容（与 deploy.probe 的 "ping" 同口径）
_PROBE_PROMPT = "ping"
_PROBE_SYSTEM = ""

# 租约与退避上限刻意不进 .env：计划 §6.4 只暴露 interval/timeout 两个键，
# 这两个内部节奏常数改动需要走代码评审。
_READY_LEASE_SECONDS = 60.0
_BACKOFF_MAX_SECONDS = 300.0


@dataclass(frozen=True)
class CaptureDecision:
    """一次采集决策快照：生产入口在持久化前取一次并显式传递。

    ``reason_code`` 只在 ``allowed=False`` 时非空，取值属于有界集合
    （REASON_* 常数或探针错误类别）。
    """

    allowed: bool
    state: str = STATE_STARTING
    reason_code: str = REASON_NOT_STARTED
    epoch: int = 0

    @property
    def result_code(self) -> str:
        """写库方回填到 ``ctx.capture_result`` 的结果码。"""
        return CAPTURE_RESULT_OK if self.allowed else CAPTURE_RESULT_DENIED


class CaptureGate:
    """进程内采集门：状态机 + 单探针 worker。

    ``probe`` 与 ``clock`` 可注入——测试用它换确定性假探针/假时钟，生产用
    默认值（真实 ``CONSOLIDATION`` 角色探针 + 单调钟）。
    """

    def __init__(
        self,
        *,
        probe: Callable[[], Awaitable[tuple[bool, str]]] | None = None,
        clock=time.monotonic,
        wall=time.time,
        probe_interval: float = 30.0,
        probe_timeout: float = 5.0,
        recovery: DependencyRecovery | None = None,
    ) -> None:
        self._probe_fn = probe or self._default_probe
        self._clock = clock
        self._wall = wall
        self._probe_interval = max(1.0, float(probe_interval))
        self._probe_timeout = max(0.5, float(probe_timeout))
        self._recovery = recovery or (
            DependencyRecovery(
                clock=clock,
                seed=0,
                base_backoff_seconds=0.5,
                max_backoff_seconds=_BACKOFF_MAX_SECONDS,
            )
            if probe is not None
            else dependency_recovery
        )
        self._state = STATE_STARTING
        self._epoch = 0
        self._started = False
        self._stopped = False
        self._probing = False
        self._task: asyncio.Task | None = None
        self._ready_until = 0.0
        self._next_retry_at = 0.0
        self._consecutive_failures = 0
        self._error_category = ""
        self._role_slot = ""
        self._last_probe_at = 0.0
        self._last_success_at = 0.0
        self._recovery_scope = DependencyScope(
            ScopeKind.PROVIDER,
            f"capture-gate:{id(self):x}",
        )

    # ── 查询侧（热路径，必须同步无副作用） ──

    def capture_allowed(self) -> bool:
        """现在是否允许采集：READY 且租约未过期。未安装/未就绪一律 False。"""
        return self._state == STATE_READY and self._clock() < self._ready_until

    def decision(self) -> CaptureDecision:
        """当前采集决策（含关门原因码）。"""
        if not self._started:
            return CaptureDecision(False, STATE_STARTING, REASON_NOT_STARTED, self._epoch)
        if self._state == STATE_READY:
            if self._clock() < self._ready_until:
                return CaptureDecision(True, STATE_READY, "", self._epoch)
            # 租约到期但续约探针未回来：按关门处理，绝不让过期 READY 开洞
            return CaptureDecision(False, STATE_READY, REASON_LEASE_EXPIRED, self._epoch)
        reason = self._error_category or self._state
        return CaptureDecision(False, self._state, reason, self._epoch)

    def status_snapshot(self) -> dict:
        """脱敏状态快照（status_api 用）。只有计数/时间/类别，无 URL/key/正文。"""
        return {
            "state": self._state,
            "role": "consolidation",
            "endpoint_slot": self._role_slot,
            "allowed": self.capture_allowed(),
            "epoch": self._epoch,
            "consecutive_failures": self._consecutive_failures,
            "last_probe_at": _iso_or_empty(self._last_probe_at),
            "last_success_at": _iso_or_empty(self._last_success_at),
            "next_retry_in_seconds": round(
                max(0.0, self._next_retry_at - self._clock()), 1
            ),
            "error_category": self._error_category,
        }

    # ── 控制侧 ──

    async def start(self) -> None:
        """装门并拉起探针 worker；启动即先探一次。重复调用幂等。"""
        if self._task is not None:
            return
        self._started = True
        self._stopped = False
        self._next_retry_at = self._clock()
        self._task = asyncio.create_task(self._run(), name="capture-gate-probe")

    async def stop(self) -> None:
        """优雅关闭：取消 worker 并立即关门（epoch 围栏，迟到探针无效）。"""
        self._stopped = True
        task, self._task = self._task, None
        self._state = STATE_UNAVAILABLE
        self._error_category = REASON_SHUTDOWN
        self._epoch += 1
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        """探针 worker：到点即探； READY 时按租约续约，不可用时按退避重试。"""
        while not self._stopped:
            delay = self._next_retry_at - self._clock()
            if delay > 0:
                await asyncio.sleep(delay)
                if self._stopped:
                    return
                continue
            await self.probe_once()

    async def probe_once(self) -> bool:
        """执行一次探针并按围栏规则落地结果。已有探针在途时直接返回现况。"""
        self._started = True  # 直呼 probe_once（无 worker）同样视为已启用
        if self._probing:
            return self.capture_allowed()
        probe_lease = self._recovery.claim_probe(
            self._recovery_scope,
            now=self._clock(),
            min_interval_seconds=0.0,
            lease_seconds=max(1.0, self._probe_timeout + 1.0),
        )
        if probe_lease is None:
            self._next_retry_at = self._clock() + self._probe_interval
            return self.capture_allowed()
        self._probing = True
        start_epoch = self._epoch
        previous_state = self._state
        renewing = self._state == STATE_READY
        if not renewing:
            self._state = STATE_PROBING
        self._last_probe_at = self._wall()
        from gravitas.model_calls import ModelCallDeferred

        try:
            ok, category = await self._probe_fn()
        except ModelCallDeferred:
            # Queue pressure is not an endpoint health signal. Restore the
            # previous state and retry after a normal interval without advancing
            # the failure count or epoch.
            self._state = previous_state
            self._next_retry_at = self._clock() + self._probe_interval
            self._recovery.abandon_probe(
                probe_lease,
                now=self._clock(),
                retry_after=self._probe_interval,
            )
            return self.capture_allowed()
        except Exception:
            # 假探针/默认探针的意外异常同样按「探测失败」处理，绝不外溢
            ok, category = False, "request_failed"
        finally:
            self._probing = False
        accepted = self._recovery.finish_probe(
            probe_lease,
            success=ok,
            failure_kind=_probe_failure_kind(category) if not ok else None,
            now=self._clock(),
        )
        if not accepted:
            self._next_retry_at = self._clock() + self._probe_interval
            return self.capture_allowed()
        self._apply(ok, category, start_epoch)
        if not ok:
            fact = self._recovery.fact(self._recovery_scope, now=self._clock())
            if fact.next_probe_at is not None:
                self._next_retry_at = max(self._next_retry_at, fact.next_probe_at)
        return ok

    def note_generation_failure(self) -> None:
        """真实整合调用失败的立即关门钩子（consolidator._generate 调）。

        与探针失败走同一关门语义；READY→关门的跃迁 bump epoch，使在途的
        旧探针成功结果作废。
        """
        if self._state != STATE_READY:
            return  # 已经关着：不重复计失败，等探针退避自然重试
        self._state = STATE_UNAVAILABLE
        self._epoch += 1
        self._consecutive_failures += 1
        self._error_category = "generation_failed"
        self._next_retry_at = self._clock() + self._backoff_delay()
        fence = self._recovery.begin_attempt(self._recovery_scope, now=self._clock())
        self._recovery.record_attempt_result(
            fence,
            success=False,
            failure_kind=FailureKind.TRANSIENT,
            now=self._clock(),
        )
        logger.warning(
            "🔒 [CaptureGate] 整合角色真实调用失败，记忆采集立即关门"
            "（恢复后从下一条新消息开始采集，期间消息不排队不回放）"
        )

    # ── 内部 ──

    def _apply(self, ok: bool, category: str, start_epoch: int) -> None:
        if start_epoch != self._epoch:
            # 围栏：探针在途期间发生过关门事件（真实失败/停止），
            # 这个迟到的结果无论成败都弃用
            logger.debug("[CaptureGate] 丢弃过期探针结果（epoch 已推进）")
            return
        now = self._clock()
        if ok:
            self._state = STATE_READY
            self._ready_until = now + _READY_LEASE_SECONDS
            self._next_retry_at = self._ready_until  # 租约到期时续约
            self._consecutive_failures = 0
            self._error_category = ""
            self._last_success_at = self._wall()
            logger.info("🔓 [CaptureGate] 整合角色就绪，记忆采集开启")
        else:
            self._state = STATE_UNAVAILABLE
            self._epoch += 1
            self._consecutive_failures += 1
            self._error_category = category
            delay = self._backoff_delay()
            self._next_retry_at = now + delay
            logger.info(
                f"🔒 [CaptureGate] 整合角色未就绪（{category}），记忆采集保持关门，"
                f"{delay:.0f}s 后重试"
            )

    def _backoff_delay(self) -> float:
        exponent = max(0, self._consecutive_failures - 1)
        return min(self._probe_interval * (2**exponent), _BACKOFF_MAX_SECONDS)

    async def _default_probe(self) -> tuple[bool, str]:
        """默认探针：走 CONSOLIDATION 角色的真实生成路径发一条最小请求。

        - 经 ``backend_for`` 拿到的就是整合真正会用的后端（含主/降级链语义），
          但**不修改** ``backend_for`` 本身（CRITICAL 共享解析器，计划 §4）；
        - 不要求 ``/v1/models``（在线服务商可不开放该端点）；
        - 不发会话数据；正文固定 "ping"；响应只判断非空，不落盘。
        """
        from core.llm.registry import ROLE_CONSOLIDATION, backend_for
        from gravitas.clock import SystemControlClock
        from gravitas.contracts import Deadline, WorkClass
        from gravitas.model_calls import (
            ModelCallDeferred,
            execute_model_call,
            role_call_context,
        )

        backend = backend_for(ROLE_CONSOLIDATION)
        if backend is None:
            self._role_slot = ""
            return False, "no_backend"
        primary = getattr(backend, "primary", backend)
        self._role_slot = str(getattr(primary, "slot", "") or "")
        clock = SystemControlClock()
        context = role_call_context(
            ROLE_CONSOLIDATION,
            work_class=WorkClass.MAINTENANCE,
            tag="capture-gate-probe",
            deadline=Deadline(clock.now() + self._probe_timeout, clock.clock_id),
            clock=clock,
        )
        try:
            text = await asyncio.wait_for(
                execute_model_call(
                    backend,
                    _PROBE_PROMPT,
                    _PROBE_SYSTEM,
                    context=context,
                ),
                timeout=self._probe_timeout,
            )
        except ModelCallDeferred:
            raise
        except (asyncio.TimeoutError, TimeoutError):
            return False, "timeout"
        except Exception as exc:
            # 错误细节只进 debug 日志（可能含端点信息），对外只给类别
            logger.debug(f"[CaptureGate] 探针请求失败: {type(exc).__name__}")
            failure = classify_dependency_failure(exc)
            if failure is FailureKind.AUTHORIZATION:
                return False, "authentication_failed"
            if failure is FailureKind.CONFIGURATION:
                return False, "invalid_configuration"
            return False, "request_failed"
        if not str(text or "").strip():
            return False, "empty_output"
        return True, ""


def _probe_failure_kind(category: str) -> FailureKind:
    normalized = str(category or "").casefold()
    if normalized in {"unauthorized", "authentication_failed", "permission_denied"}:
        return FailureKind.AUTHORIZATION
    if normalized in {"no_backend", "invalid_configuration", "invalid_model"}:
        return FailureKind.CONFIGURATION
    return FailureKind.TRANSIENT


def _iso_or_empty(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ── 模块级单例：Bot 进程装一份；测试直接构造 CaptureGate 注入假探针 ──

_gate: CaptureGate | None = None


def get_gate() -> CaptureGate | None:
    return _gate


def capture_allowed() -> bool:
    """热路径查询：门未安装/未就绪一律 False（fail-closed 缺省）。"""
    return _gate is not None and _gate.capture_allowed()


def current_decision() -> CaptureDecision:
    if _gate is None:
        return CaptureDecision(False, STATE_STARTING, REASON_NOT_STARTED, 0)
    return _gate.decision()


def ingress_decision() -> CaptureDecision | None:
    """生产入站的采集决策；门未安装返回 None（遗留语义）。

    生产 Bot 进程在 on_startup 装门、之后绝不卸载（stop 只关门不置空），
    因此 None 只出现在单元测试/显式调用方——那时保持既有直接落库行为，
    存量测试无须感知门的存在。装门失败也会安装一个永不开门的实例，
    进程生命周期内不存在「以为装了门其实没有」的窗口。
    """
    if _gate is None:
        return None
    return _gate.decision()


def note_generation_failure() -> None:
    """真实整合失败的全局钩子；门未安装时无事可做（本来就关着）。"""
    if _gate is not None:
        _gate.note_generation_failure()


def status_snapshot() -> dict:
    """状态接口的脱敏快照；门未安装时给明确的未启动事实。"""
    if _gate is None:
        return {
            "state": STATE_STARTING,
            "role": "consolidation",
            "endpoint_slot": "",
            "allowed": False,
            "epoch": 0,
            "consecutive_failures": 0,
            "last_probe_at": "",
            "last_success_at": "",
            "next_retry_in_seconds": 0.0,
            "error_category": REASON_NOT_STARTED,
        }
    return _gate.status_snapshot()


async def start_gate() -> CaptureGate:
    """按 .env 配置装门并启动（Bot on_startup 调）。重复调用返回现门。

    装门异常时不留空窗：仍把门挂到单例上（worker 缺席 = 永远关门，
    保持 fail-closed），只让启动日志报错。
    """
    global _gate
    if _gate is not None:
        return _gate
    from config import MEMORY_CAPTURE_PROBE_INTERVAL, MEMORY_CAPTURE_PROBE_TIMEOUT

    gate = CaptureGate(
        probe_interval=float(MEMORY_CAPTURE_PROBE_INTERVAL),
        probe_timeout=float(MEMORY_CAPTURE_PROBE_TIMEOUT),
    )
    try:
        await gate.start()
    except Exception as e:
        logger.error(f"❌ [CaptureGate] 探针 worker 启动失败，记忆采集保持关门: {e}")
    _gate = gate
    logger.info(
        "🚪 [CaptureGate] 记忆采集就绪门已启动（fail-closed；"
        f"探针间隔 {gate._probe_interval:.0f}s / 超时 {gate._probe_timeout:.1f}s）"
    )
    return gate


async def stop_gate() -> None:
    """优雅关闭：关门并取消 worker。**保留单例**（停止态 = 明确的关门
    事实），避免关闭窗口期入站拿到「门未安装」的遗留语义而照常落库。"""
    if _gate is None:
        return
    await _gate.stop()
