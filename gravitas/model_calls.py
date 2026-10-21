# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Single-attempt model execution adapter over the shared resource scheduler."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from gravitas.clock import ControlClock, SystemControlClock
from gravitas.contracts import Deadline, WorkClass


class ModelBackend(Protocol):
    async def generate(self, prompt: str, system_prompt: str = "") -> str: ...

    async def generate_detailed(
        self, prompt: str, system_prompt: str = ""
    ) -> tuple[str, str]: ...


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
    from core.llm.scheduler import acquire

    async with acquire(
        context.resource_group_id,
        tag=context.tag,
        work_class=context.work_class,
        deadline=queue_deadline,
        conversation_key=context.conversation_key,
    ):
        if context.deadline is not None and context.deadline.is_expired(
            context.clock.now(), clock_id=context.clock.clock_id
        ):
            raise TimeoutError("model attempt deadline expired before execution")
        if detailed:
            return await backend.generate_detailed(prompt, system_prompt)
        return await backend.generate(prompt, system_prompt)
