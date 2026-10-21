# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Single-attempt model execution adapter over the shared resource scheduler."""

from __future__ import annotations

import hashlib
import sys
import time
from collections.abc import Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Protocol

from gravitas.clock import ControlClock, SystemControlClock
from gravitas.config import ResourceGroupConfig
from gravitas.contracts import Deadline, WorkClass

_RESOURCE_GROUP_BY_SLOT: dict[str, str] = {}
_RESOURCE_GROUP_LIMITS: dict[str, int] = {}


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
) -> ModelCallContext:
    """Build a context from an explicitly selected role and trusted turn data."""
    from core.llm.registry import gate_of

    slot = gate_of(role)
    return ModelCallContext(
        resource_group_id=resource_group_for(slot),
        work_class=work_class,
        tag=tag,
        conversation_key=opaque_queue_key(conversation_key),
        deadline=deadline,
        clock=clock or SystemControlClock(),
    )


@asynccontextmanager
async def model_attempt(context: ModelCallContext):
    """Hold the shared scheduler ticket for the full attempt, including streams."""
    if not isinstance(context, ModelCallContext):
        raise TypeError("context must be a ModelCallContext")
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
    """Run exactly one backend attempt while holding its declared resource ticket.

    This adapter deliberately does not infer a resource from backend class names,
    perform retries, or choose fallback endpoints. Those choices belong to the
    role/endpoint orchestration layer.
    """
    async with model_attempt(context):
        if detailed:
            return await backend.generate_detailed(prompt, system_prompt)
        return await backend.generate(prompt, system_prompt)
