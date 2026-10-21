# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Explicit host wiring for the dormant Gravitas shadow controller."""

from __future__ import annotations

import asyncio
import copy
import logging
import os
from pathlib import Path

from gravitas.config import (
    ConfigError,
    GravitasMode,
    default_config,
    load_config,
)
from gravitas.controller import (
    GravitasController,
    active_controller,
    set_active_controller,
)

_LOG = logging.getLogger("stella.gravitas")
_ACTIVE_GRAVITAS_RUNTIME: "GravitasRuntime | None" = None


class GravitasRuntime:
    """Own one controller task and expose its cached read-only status."""

    def __init__(
        self,
        controller: GravitasController,
        *,
        bootstrap_reason: str = "ready",
    ) -> None:
        self.controller = controller
        self.bootstrap_reason = bootstrap_reason
        self._task: asyncio.Task | None = None
        self._cometa_policy_ack: dict[str, object] | None = None

    def record_cometa_policy_ack(self, status: dict[str, object]) -> None:
        """Cache only the low-cardinality ACK for the current Cometa revision."""
        allowed_keys = {
            "state",
            "reason_code",
            "policy_revision",
            "applied",
            "claim_allowed",
            "claim_limit",
        }
        if not isinstance(status, dict):
            return
        safe = {key: status[key] for key in allowed_keys if key in status}
        if (
            not isinstance(safe.get("state"), str)
            or not isinstance(safe.get("reason_code"), str)
            or isinstance(safe.get("policy_revision"), bool)
            or not isinstance(safe.get("policy_revision"), int)
            or not isinstance(safe.get("applied"), bool)
            or not isinstance(safe.get("claim_allowed"), bool)
            or isinstance(safe.get("claim_limit"), bool)
            or not isinstance(safe.get("claim_limit"), int)
        ):
            return
        self._cometa_policy_ack = safe

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        try:
            from gravitas.model_calls import configure_resource_groups

            configure_resource_groups(self.controller.config.resources)
        except Exception:
            self.bootstrap_reason = "resource_group_config_error"
            _LOG.error("Gravitas resource groups could not be installed; endpoint gates remain active")
        self._task = asyncio.create_task(
            self._run_guarded(), name="stella-gravitas-controller"
        )

    async def _run_guarded(self) -> None:
        try:
            await self.controller.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.bootstrap_reason = "controller_failed"
            _LOG.error("Gravitas controller stopped unexpectedly")

    async def stop(self) -> None:
        global _ACTIVE_GRAVITAS_RUNTIME
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if active_controller() is self.controller:
            set_active_controller(None)
            from memory.pre_processors import set_capture_pressure_provider

            set_capture_pressure_provider(None)
        if _ACTIVE_GRAVITAS_RUNTIME is self:
            _ACTIVE_GRAVITAS_RUNTIME = None

    def status_snapshot(self) -> dict[str, object]:
        payload = self.controller.status_snapshot()
        if self._cometa_policy_ack is not None:
            ack = copy.deepcopy(self._cometa_policy_ack)
            payload["cometa_policy_ack"] = ack
            assessment = payload.get("assessment")
            if isinstance(assessment, dict):
                current = assessment.get("applied_ack")
                items = list(current.get("items", [])) if isinstance(current, dict) else []
                items.append({"adapter": "cometa.worker", **ack})
                assessment["applied_ack"] = {
                    "state": (
                        "partial"
                        if ack["state"] in ("applied", "rejected")
                        else "not_received"
                    ),
                    "reason_code": ack["reason_code"],
                    "items": items,
                }
        if self.bootstrap_reason != "ready":
            payload["reason_code"] = self.bootstrap_reason
            payload["bootstrap_state"] = "degraded"
        else:
            payload["bootstrap_state"] = "ready"
        return payload


def setup_gravitas(driver, *, stella_home: str | Path, status_api) -> GravitasRuntime:
    """Register startup/shutdown hooks after providers and before WebUI mount."""
    home = Path(stella_home)
    config_path = home / "config" / "gravitas.toml"
    bootstrap_reason = "ready"
    if config_path.is_file():
        try:
            config = load_config(config_path)
        except ConfigError:
            config = default_config()
            bootstrap_reason = "config_error"
    else:
        config = default_config()

    raw_mode = os.environ.get("GRAVITAS_MODE", GravitasMode.SHADOW.value)
    try:
        mode = GravitasMode(raw_mode.strip().lower())
    except (AttributeError, ValueError):
        mode = GravitasMode.SHADOW
        bootstrap_reason = "invalid_mode"

    def scheduler_source() -> object:
        from core.llm import snapshot

        return snapshot()

    def capture_source() -> object:
        from memory.capture_gate import status_snapshot

        return status_snapshot()

    controller = GravitasController(
        config,
        scheduler_source=scheduler_source,
        capture_source=capture_source,
        mode=mode,
    )
    set_active_controller(controller)
    from memory.pre_processors import set_capture_pressure_provider

    if controller.effective_mode is GravitasMode.ENFORCE:
        set_capture_pressure_provider(
            lambda snapshot, wall_time: controller.admit_memory_capture(
                snapshot, wall_time=wall_time
            )
        )
    else:
        set_capture_pressure_provider(None)
    runtime = GravitasRuntime(controller, bootstrap_reason=bootstrap_reason)
    global _ACTIVE_GRAVITAS_RUNTIME
    _ACTIVE_GRAVITAS_RUNTIME = runtime
    status_api.set_gravitas_status_provider(runtime.status_snapshot)
    driver.on_startup(runtime.start)
    driver.on_shutdown(runtime.stop)
    if bootstrap_reason != "ready":
        _LOG.error("Gravitas bootstrap degraded: %s", bootstrap_reason)
    elif controller.enforcement_refused:
        _LOG.warning("GRAVITAS_MODE=enforce was refused; controller remains shadow-only")
    return runtime


def active_gravitas_runtime() -> GravitasRuntime | None:
    """Return the explicitly assembled host runtime, if setup completed."""
    return _ACTIVE_GRAVITAS_RUNTIME
