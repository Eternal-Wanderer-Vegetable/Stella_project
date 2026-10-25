# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Compatibility coordinator for the existing QQ and WebChat entry points.

Platform handlers still own trusted event parsing, scene registration, reply
relations, and platform-specific bookkeeping. This coordinator shares the
policy, capture, persistence, and runtime-facade boundaries without changing
their ordering. ``STELLA_SHARED_INGRESS_ENABLED=false`` selects the direct
legacy callbacks as a rollback path; a handler never runs both branches.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from core.context import ChatContext
from core.transport.normalizers import AdmissionPolicy, NormalizedEvent


class LegacyIngressBridge:
    """Share common ingress boundaries while preserving legacy adapter hooks."""

    def __init__(self, admission_policy: AdmissionPolicy | None = None) -> None:
        self.policy = admission_policy or AdmissionPolicy()

    @staticmethod
    def _enabled() -> bool:
        try:
            from config import settings

            return bool(settings.STELLA_SHARED_INGRESS_ENABLED)
        except Exception:
            # Minimal and test-only configurations keep the established path.
            return False

    def decide(
        self,
        event: NormalizedEvent,
        *,
        legacy_policy: AdmissionPolicy | None = None,
        **kwargs: Any,
    ):
        """Use the common policy instance, or the caller's legacy instance."""
        policy = self.policy if self._enabled() else (legacy_policy or self.policy)
        return policy.decide(event, **kwargs)

    def capture_decision(self, gate: Any) -> Any:
        """Take the one capture-gate snapshot shared by each legacy ingress."""
        if self._enabled():
            return self._capture_decision(gate)
        return gate.ingress_decision()

    @staticmethod
    def _capture_decision(gate: Any) -> Any:
        return gate.ingress_decision()

    @staticmethod
    def capture_allowed(decision: Any) -> bool:
        """A missing gate preserves standalone/dev-server behavior."""
        if decision is None:
            return True
        if type(decision) is bool:
            return decision
        return getattr(decision, "allowed", None) is True

    async def record_message(
        self,
        writer: Callable[..., Any],
        context: ChatContext,
        *,
        capture: Any,
    ) -> Any:
        """Write one context through the existing transactional recorder."""
        if self._enabled():
            return await self._record_message(writer, context, capture=capture)
        return await _maybe_await(writer(context, capture=capture))

    @staticmethod
    async def _record_message(
        writer: Callable[..., Any], context: ChatContext, *, capture: Any
    ) -> Any:
        return await _maybe_await(writer(context, capture=capture))

    async def submit_turn(
        self,
        session_key: str,
        pipeline: object,
        context: ChatContext,
        *,
        deadline: float | None = None,
        turn_deadline: Any = None,
        facade: Any = None,
        legacy_submit: Callable[[], Awaitable[ChatContext]] | None = None,
    ) -> ChatContext:
        """Submit through the shared process-local facade, with a direct rollback."""
        if not self._enabled() and legacy_submit is not None:
            return await legacy_submit()
        if facade is None:
            from core.runtime.facade import ensure_shared_facade_started

            facade = await ensure_shared_facade_started()
        kwargs: dict[str, Any] = {}
        if deadline is not None:
            kwargs["deadline"] = deadline
        if turn_deadline is not None:
            kwargs["turn_deadline"] = turn_deadline
        return await facade.submit_turn(session_key, pipeline, context, **kwargs)


async def _maybe_await(value: object) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


shared_legacy_ingress = LegacyIngressBridge()

__all__ = ["LegacyIngressBridge", "shared_legacy_ingress"]
