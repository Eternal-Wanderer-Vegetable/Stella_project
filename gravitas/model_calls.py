# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Bounded model request execution over the shared resource scheduler."""

from __future__ import annotations

import hashlib
import inspect
import sys
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from core.llm.base import AdaptiveAttemptRequiredError
from gravitas.clock import ControlClock, SystemControlClock
from gravitas.config import ResourceGroupConfig
from gravitas.contracts import Deadline, WorkClass

_RESOURCE_GROUP_BY_SLOT: dict[str, str] = {}
_RESOURCE_GROUP_LIMITS: dict[str, int] = {}
_MAX_MODEL_ATTEMPTS = 3
_MAX_COVERAGE_RESOURCES = 256
_UNKNOWN_COVERAGE: OrderedDict[str, None] = OrderedDict()
_COVERAGE_INCOMPLETE = False
_ACTIVE_BUDGET: ContextVar["_AttemptBudgetView | None"] = ContextVar(
    "gravitas_model_attempt_budget", default=None
)
_T = TypeVar("_T")


class ModelAttemptBudgetExceededError(RuntimeError):
    """The business call has used its bounded number of real request tickets."""


@dataclass(slots=True)
class _AttemptBudget:
    maximum: int
    started: int = 0


@dataclass(frozen=True, slots=True)
class _AttemptBudgetView:
    state: _AttemptBudget
    absolute_limit: int

    @property
    def started(self) -> int:
        return self.state.started

    @property
    def remaining(self) -> int:
        return max(0, min(self.state.maximum, self.absolute_limit) - self.state.started)

    def start(self) -> None:
        if self.remaining <= 0:
            raise ModelAttemptBudgetExceededError("model_attempt_budget_exhausted")
        self.state.started += 1


@asynccontextmanager
async def model_call_scope(max_attempts: int = _MAX_MODEL_ATTEMPTS):
    """Share one finite HTTP-attempt budget across nested model adapters."""
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
        raise ValueError("max_attempts must be an integer")
    if not 1 <= max_attempts <= _MAX_MODEL_ATTEMPTS:
        raise ValueError(f"max_attempts must be between 1 and {_MAX_MODEL_ATTEMPTS}")
    current = _ACTIVE_BUDGET.get()
    if current is not None:
        scoped = _AttemptBudgetView(
            current.state,
            min(current.absolute_limit, current.state.started + max_attempts),
        )
        token = _ACTIVE_BUDGET.set(scoped)
        try:
            yield scoped
        finally:
            _ACTIVE_BUDGET.reset(token)
        return
    state = _AttemptBudget(maximum=max_attempts)
    budget = _AttemptBudgetView(state, absolute_limit=max_attempts)
    token = _ACTIVE_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _ACTIVE_BUDGET.reset(token)


def attempt_coverage_snapshot() -> dict[str, Any]:
    """Return bounded resource groups whose backend cannot promise one HTTP call."""
    return {
        "unknown_resources": tuple(_UNKNOWN_COVERAGE),
        "incomplete": _COVERAGE_INCOMPLETE,
    }


def _mark_coverage_unknown(resource_id: str) -> None:
    global _COVERAGE_INCOMPLETE
    if resource_id in _UNKNOWN_COVERAGE:
        _UNKNOWN_COVERAGE.move_to_end(resource_id)
        return
    if len(_UNKNOWN_COVERAGE) >= _MAX_COVERAGE_RESOURCES:
        _UNKNOWN_COVERAGE.popitem(last=False)
        _COVERAGE_INCOMPLETE = True
    _UNKNOWN_COVERAGE[resource_id] = None


def configure_resource_groups(resources: Iterable[ResourceGroupConfig]) -> None:
    """Bind endpoint slots to configured shared resources at host startup.

    The effective group limit is the minimum of the explicit group limit and
    every member endpoint's limit. Unconfigured group identifiers fall back to
    the existing registry resolver.
    """
    from core.llm.registry import concurrency_of
    from core.llm.scheduler import set_concurrency_resolver

    materialized = tuple(resources)
    by_slot: dict[str, str] = {}
    group_limits: dict[str, int] = {}
    for item in materialized:
        member_limits = [concurrency_of(slot) for slot in item.slots]
        group_limits[item.group_id] = min([item.concurrency, *member_limits])
        for slot in item.slots:
            if slot in by_slot:
                raise ValueError(f"slot belongs to multiple resource groups: {slot}")
            by_slot[slot] = item.group_id

    _RESOURCE_GROUP_BY_SLOT.clear()
    _RESOURCE_GROUP_BY_SLOT.update(by_slot)
    _RESOURCE_GROUP_LIMITS.clear()
    _RESOURCE_GROUP_LIMITS.update(group_limits)

    def resolve_limit(resource_id: str) -> int:
        configured = _RESOURCE_GROUP_LIMITS.get(resource_id)
        return configured if configured is not None else concurrency_of(resource_id)

    set_concurrency_resolver(resolve_limit)


def resource_group_for(slot: str) -> str:
    """Resolve a configured endpoint slot to its shared queue resource."""
    return _RESOURCE_GROUP_BY_SLOT.get(slot, slot)


def resource_group_for_url(base_url: str, *, declared_slot: str | None = None) -> str:
    """Resolve an endpoint URL to a configured slot or a private opaque group."""
    if declared_slot:
        return resource_group_for(declared_slot)
    normalized = str(base_url or "").strip().rstrip("/")
    from core.llm.registry import endpoints

    for endpoint in endpoints().values():
        if endpoint.configured and endpoint.base_url.rstrip("/") == normalized:
            return resource_group_for(endpoint.slot)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"endpoint:{digest}"


def opaque_queue_key(value: object) -> str | None:
    """Hash a trusted conversation identity before retaining it in queue state."""
    if not isinstance(value, str) or not value:
        return None
    return "conversation:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class ModelBackend(Protocol):
    async def generate(self, prompt: str, system_prompt: str = "") -> str: ...

    async def generate_detailed(
        self, prompt: str, system_prompt: str = ""
    ) -> tuple[str, str]: ...


class _ObservedAttemptEndpoint:
    """Record successful single-attempt replies without hiding endpoint identity."""

    def __init__(self, backend: Any, observer: Callable[[str, str, str], None]) -> None:
        self._backend = backend
        self._observer = observer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    async def generate_single_attempt(
        self, prompt: str, system_prompt: str = ""
    ) -> tuple[str, str]:
        reply, finish = await self._backend.generate_single_attempt(prompt, system_prompt)
        self._observer(prompt, reply, finish)
        return reply, finish


class _ObservedLegacyEndpoint:
    """Observe a backend that cannot promise one HTTP request per invocation."""

    def __init__(self, backend: Any, observer: Callable[[str, str, str], None]) -> None:
        self._backend = backend
        self._observer = observer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    async def generate_detailed(self, prompt: str, system_prompt: str = "") -> tuple[str, str]:
        reply, finish = await _invoke_detailed_once(self._backend, prompt, system_prompt)
        self._observer(prompt, reply, finish)
        return reply, finish

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        reply, _ = await self.generate_detailed(prompt, system_prompt)
        return reply


class _ObservedRoleBackend:
    """Keep a RoleBackend's attempt handoff visible through an observation wrapper."""

    def __init__(self, backend: Any, observer: Callable[[str, str, str], None]) -> None:
        self._backend = backend
        self.role = backend.role
        self.cooldown = backend.cooldown
        self._endpoints: dict[int, Any] = {}
        self.primary = self._wrap(backend.primary, observer)
        self.fallback = self._wrap(backend.fallback, observer)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def _wrap(self, backend: Any, observer: Callable[[str, str, str], None]) -> Any:
        wrapper_type = (
            _ObservedAttemptEndpoint
            if callable(getattr(backend, "generate_single_attempt", None))
            else _ObservedLegacyEndpoint
        )
        wrapped = wrapper_type(backend, observer)
        self._endpoints[id(wrapped)] = backend
        return wrapped

    @property
    def model(self) -> str:
        return str(getattr(self._backend, "model", "") or "")

    def attempt_plan(self) -> tuple[Any, bool]:
        endpoint, degraded = self._backend.attempt_plan()
        wrapped = self.primary if endpoint is self._backend.primary else self.fallback
        return wrapped, degraded

    def record_attempt_result(self, endpoint: Any, error: BaseException) -> bool:
        original = self._endpoints.get(id(endpoint))
        if original is None:
            raise ValueError("attempt endpoint does not belong to this observer")
        return self._backend.record_attempt_result(original, error)


class _ObservedAttemptBackend:
    def __init__(self, backend: Any, observer: Callable[[str, str, str], None]) -> None:
        self._backend = backend
        self._observer = observer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    async def generate_single_attempt(
        self, prompt: str, system_prompt: str = ""
    ) -> tuple[str, str]:
        reply, finish = await self._backend.generate_single_attempt(prompt, system_prompt)
        self._observer(prompt, reply, finish)
        return reply, finish


class _ObservedLegacyBackend:
    def __init__(self, backend: Any, observer: Callable[[str, str, str], None]) -> None:
        self._backend = backend
        self._observer = observer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    async def generate_detailed(self, prompt: str, system_prompt: str = "") -> tuple[str, str]:
        reply, finish = await _invoke_detailed_once(self._backend, prompt, system_prompt)
        self._observer(prompt, reply, finish)
        return reply, finish

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        reply, _ = await self.generate_detailed(prompt, system_prompt)
        return reply


def observe_model_backend(
    backend: Any, observer: Callable[[str, str, str], None]
) -> Any:
    """Wrap a backend to observe successful replies while preserving ticket routing."""
    if not callable(observer):
        raise TypeError("observer must be callable")
    from core.llm.registry import RoleBackend

    if isinstance(backend, RoleBackend):
        return _ObservedRoleBackend(backend, observer)
    wrapper_type = (
        _ObservedAttemptBackend
        if callable(getattr(backend, "generate_single_attempt", None))
        else _ObservedLegacyBackend
    )
    return wrapper_type(backend, observer)


def _supports_role_attempts(backend: Any) -> bool:
    return (
        callable(getattr(backend, "attempt_plan", None))
        and callable(getattr(backend, "record_attempt_result", None))
        and hasattr(backend, "primary")
        and hasattr(backend, "fallback")
    )


class ModelCallDeferred(RuntimeError):  # noqa: N818 - names a deferred, not failed, attempt
    """No attempt started because the bounded scheduler rejected its ticket."""

    def __init__(self, reason_code: str = "scheduler_queue_full") -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ModelCallContext:
    """Trusted execution metadata; caller declares the actual shared resource."""

    resource_group_id: str
    work_class: WorkClass
    tag: str = "model-attempt"
    conversation_key: str | None = None
    deadline: Deadline | None = None
    clock: ControlClock = field(default_factory=SystemControlClock)
    max_attempts: int = _MAX_MODEL_ATTEMPTS

    def __post_init__(self) -> None:
        if (
            not isinstance(self.resource_group_id, str)
            or not self.resource_group_id
            or self.resource_group_id != self.resource_group_id.strip()
        ):
            raise ValueError("resource_group_id must be explicitly declared")
        if not isinstance(self.work_class, WorkClass):
            raise ValueError("work_class must be a WorkClass")
        if not isinstance(self.tag, str) or not self.tag or self.tag != self.tag.strip():
            raise ValueError("tag must be a non-empty trimmed diagnostic label")
        if self.deadline is not None and not isinstance(self.deadline, Deadline):
            raise ValueError("deadline must be a Deadline or None")
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 1 <= self.max_attempts <= _MAX_MODEL_ATTEMPTS
        ):
            raise ValueError(f"max_attempts must be between 1 and {_MAX_MODEL_ATTEMPTS}")
        if not callable(getattr(self.clock, "now", None)) or not isinstance(
            getattr(self.clock, "clock_id", None), str
        ):
            raise ValueError("clock must implement the ControlClock contract")


def role_call_context(
    role: str,
    *,
    work_class: WorkClass,
    tag: str,
    conversation_key: object = None,
    deadline: Deadline | None = None,
    clock: ControlClock | None = None,
    endpoint_slot: str | None = None,
    max_attempts: int = _MAX_MODEL_ATTEMPTS,
) -> ModelCallContext:
    """Build a context from an explicitly selected role and trusted turn data."""
    from core.llm.registry import gate_of

    slot = endpoint_slot or gate_of(role)
    return ModelCallContext(
        resource_group_id=resource_group_for(slot),
        work_class=work_class,
        tag=tag,
        conversation_key=opaque_queue_key(conversation_key),
        deadline=deadline,
        clock=clock or SystemControlClock(),
        max_attempts=max_attempts,
    )


@asynccontextmanager
async def model_attempt(context: ModelCallContext):
    """Hold the shared scheduler ticket for the full attempt, including streams."""
    if not isinstance(context, ModelCallContext):
        raise TypeError("context must be a ModelCallContext")
    async with model_call_scope(context.max_attempts) as budget:
        if budget.remaining <= 0:
            raise ModelAttemptBudgetExceededError("model_attempt_budget_exhausted")
        if context.deadline is not None:
            remaining = context.deadline.remaining(
                context.clock.now(), clock_id=context.clock.clock_id
            )
            if remaining <= 0:
                raise TimeoutError("model attempt deadline expired before queueing")
            queue_deadline = time.monotonic() + remaining
        else:
            queue_deadline = None

        # Lazy import keeps the DTO package independent from the host's LLM package.
        from core.llm.scheduler import QueueCapacityError, acquire

        ticket = acquire(
            context.resource_group_id,
            tag=context.tag,
            work_class=context.work_class,
            deadline=queue_deadline,
            conversation_key=context.conversation_key,
        )
        try:
            await ticket.__aenter__()
        except QueueCapacityError as exc:
            raise ModelCallDeferred("scheduler_queue_full") from exc
        except TimeoutError as exc:
            raise ModelCallDeferred("deadline_expired_in_queue") from exc

        try:
            if context.deadline is not None and context.deadline.is_expired(
                context.clock.now(), clock_id=context.clock.clock_id
            ):
                raise TimeoutError("model attempt deadline expired before execution")
            budget.start()
            yield
        except BaseException:
            await ticket.__aexit__(*sys.exc_info())
            raise
        else:
            await ticket.__aexit__(None, None, None)


async def execute_model_call(
    backend: ModelBackend,
    prompt: str,
    system_prompt: str = "",
    *,
    context: ModelCallContext,
    detailed: bool = False,
) -> str | tuple[str, str]:
    """Execute a backend using one ticket per request and at most three requests."""
    from core.llm.registry import RoleBackend

    if isinstance(backend, RoleBackend) or _supports_role_attempts(backend):
        return await execute_role_model_call(
            backend, prompt, system_prompt, context=context, detailed=detailed
        )

    single_attempt = getattr(backend, "generate_single_attempt", None)
    if not callable(single_attempt):
        _mark_coverage_unknown(context.resource_group_id)
        async with model_attempt(context):
            if detailed:
                return await _invoke_detailed_once(backend, prompt, system_prompt)
            return await backend.generate(prompt, system_prompt)

    async def invoke() -> str | tuple[str, str]:
        reply, finish = await single_attempt(prompt, system_prompt)
        return (reply, finish) if detailed else reply

    return await execute_model_operation(invoke, context=context)


async def execute_model_operation(
    operation: Callable[[], Awaitable[_T]],
    *,
    context: ModelCallContext,
    fallback_operation: Callable[[], Awaitable[_T]] | None = None,
    fallback_context: ModelCallContext | None = None,
) -> _T:
    """Run an HTTP operation under one actual-resource ticket per request.

    Adaptive payload changes consume another request. A configured fallback gets
    one attempt, after the primary ticket has been released.
    """
    if (fallback_operation is None) != (fallback_context is None):
        raise ValueError("fallback_operation and fallback_context must be supplied together")

    async with model_call_scope(context.max_attempts) as budget:
        primary_attempts = 0
        while budget.remaining:
            primary_attempts += 1
            before = budget.started
            try:
                async with model_attempt(context):
                    return await operation()
            except AdaptiveAttemptRequiredError as exc:
                retry_limit = 2 if fallback_operation is not None else 3
                if budget.remaining and primary_attempts < retry_limit:
                    continue
                if (
                    budget.remaining
                    and fallback_operation is not None
                    and fallback_worthy(exc.original)
                ):
                    return await _run_operation(fallback_operation, fallback_context)
                raise exc.original from exc
            except (ModelCallDeferred, ModelAttemptBudgetExceededError):
                raise
            except Exception as exc:
                if budget.started == before:
                    raise
                if fallback_operation is not None and fallback_worthy(exc):
                    if _retry_worthy(exc) and primary_attempts < 2 and budget.remaining > 1:
                        continue
                    if budget.remaining:
                        return await _run_operation(fallback_operation, fallback_context)
                if _retry_worthy(exc) and budget.remaining:
                    continue
                raise
        raise ModelAttemptBudgetExceededError("model_attempt_budget_exhausted")


async def execute_model_stream(
    operation: Callable[[], AsyncIterator[_T]],
    *,
    context: ModelCallContext,
    fallback_operation: Callable[[], AsyncIterator[_T]] | None = None,
    fallback_context: ModelCallContext | None = None,
) -> AsyncIterator[_T]:
    """Stream under one endpoint ticket; fallback only before output is exposed."""
    if (fallback_operation is None) != (fallback_context is None):
        raise ValueError("fallback_operation and fallback_context must be supplied together")

    async with model_call_scope(context.max_attempts) as budget:
        primary_attempts = 0
        while budget.remaining:
            primary_attempts += 1
            emitted = False
            before = budget.started
            try:
                async with model_attempt(context):
                    async for item in operation():
                        emitted = True
                        yield item
                return
            except AdaptiveAttemptRequiredError as exc:
                if emitted:
                    raise exc.original from exc
                if budget.remaining and primary_attempts < 3:
                    continue
                if (
                    budget.remaining
                    and fallback_operation is not None
                    and fallback_worthy(exc.original)
                ):
                    async for item in _stream_operation(fallback_operation, fallback_context):
                        yield item
                    return
                raise exc.original from exc
            except (ModelCallDeferred, ModelAttemptBudgetExceededError):
                raise
            except Exception as exc:
                if budget.started == before:
                    raise
                if emitted:
                    raise
                if fallback_operation is not None and fallback_worthy(exc) and budget.remaining:
                    async for item in _stream_operation(fallback_operation, fallback_context):
                        yield item
                    return
                if _retry_worthy(exc) and budget.remaining:
                    continue
                raise
        raise ModelAttemptBudgetExceededError("model_attempt_budget_exhausted")


async def execute_role_model_call(
    role_backend: Any,
    prompt: str,
    system_prompt: str = "",
    *,
    context: ModelCallContext | None = None,
    detailed: bool = False,
) -> str | tuple[str, str]:
    """Run the role's actual primary/fallback endpoint with separate tickets."""
    primary_slot = str(getattr(role_backend.primary, "slot", "") or "").strip()
    if context is None:
        from gravitas.contracts import WorkClass

        resource = primary_slot or str(role_backend.role)
        context = ModelCallContext(
            resource_group_for(resource),
            WorkClass.INTERACTIVE,
            tag="llm-role",
        )

    endpoint, degraded = role_backend.attempt_plan()
    fallback_used = degraded
    primary_attempts = 0
    async with model_call_scope(context.max_attempts) as budget:
        while budget.remaining:
            endpoint_slot = str(getattr(endpoint, "slot", "") or "").strip()
            resource = resource_group_for(endpoint_slot) if endpoint_slot else context.resource_group_id
            endpoint_context = _with_resource(context, resource)
            single_attempt = getattr(endpoint, "generate_single_attempt", None)
            if not callable(single_attempt):
                _mark_coverage_unknown(resource)

            current_endpoint = endpoint
            current_attempt = single_attempt

            async def invoke_endpoint(
                endpoint=current_endpoint, attempt=current_attempt
            ) -> str | tuple[str, str]:
                if callable(attempt):
                    reply, finish = await attempt(prompt, system_prompt)
                    return (reply, finish) if detailed else reply
                if detailed:
                    return await _invoke_detailed_once(endpoint, prompt, system_prompt)
                return await endpoint.generate(prompt, system_prompt)

            before = budget.started
            try:
                async with model_attempt(endpoint_context):
                    return await invoke_endpoint()
            except AdaptiveAttemptRequiredError as exc:
                primary_attempts += 1
                if not fallback_used and callable(single_attempt) and budget.remaining and primary_attempts < 3:
                    continue
                if not fallback_used and role_backend.record_attempt_result(endpoint, exc.original):
                    if not budget.remaining:
                        raise exc.original from exc
                    endpoint = role_backend.fallback
                    fallback_used = True
                    continue
                raise exc.original from exc
            except (ModelCallDeferred, ModelAttemptBudgetExceededError):
                raise
            except Exception as exc:
                if budget.started == before:
                    raise
                if fallback_used:
                    raise
                primary_attempts += 1
                if (
                    callable(single_attempt)
                    and _retry_worthy(exc)
                    and primary_attempts < 2
                    and budget.remaining > 1
                ):
                    continue
                if not role_backend.record_attempt_result(endpoint, exc):
                    raise
                if not budget.remaining:
                    raise
                endpoint = role_backend.fallback
                fallback_used = True
        raise ModelAttemptBudgetExceededError("model_attempt_budget_exhausted")


def _with_resource(context: ModelCallContext, resource_id: str) -> ModelCallContext:
    from dataclasses import replace

    return replace(context, resource_group_id=resource_id)


async def _invoke_detailed_once(
    backend: Any, prompt: str, system_prompt: str
) -> tuple[str, str]:
    """Call a detailed backend once while tolerating older one-argument wrappers."""
    fn = getattr(backend, "generate_detailed", None)
    if not callable(fn):
        return await backend.generate(prompt, system_prompt), ""
    try:
        parameters = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        accepts_system_prompt = True
    else:
        positional = [
            item
            for item in parameters
            if item.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        accepts_system_prompt = len(positional) >= 2 or any(
            item.kind is inspect.Parameter.VAR_POSITIONAL for item in parameters
        )
    result = (
        await fn(prompt, system_prompt) if accepts_system_prompt else await fn(prompt)
    )
    if isinstance(result, tuple) and len(result) == 2:
        return result
    return str(result or ""), ""


async def _run_operation(
    operation: Callable[[], Awaitable[_T]], context: ModelCallContext | None
) -> _T:
    if context is None:
        raise ValueError("fallback context is required")
    async with model_attempt(context):
        return await operation()


async def _stream_operation(
    operation: Callable[[], AsyncIterator[_T]], context: ModelCallContext | None
) -> AsyncIterator[_T]:
    if context is None:
        raise ValueError("fallback context is required")
    async with model_attempt(context):
        async for item in operation():
            yield item


def _retry_worthy(exc: BaseException) -> bool:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return status in {408, 425, 429} or status >= 500
    return True


def fallback_worthy(exc: BaseException) -> bool:
    from core.llm.registry import fallback_worthy as registry_fallback_worthy

    return registry_fallback_worthy(exc)
