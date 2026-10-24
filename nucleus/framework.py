# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""The version-gated NoneBot 2.5.0 managed Driver bridge."""

from __future__ import annotations

import functools
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from types import MethodType
from typing import Any

MANAGED_NONEBOT_VERSION = "2.5.0"


class ManagedFrameworkError(RuntimeError):
    """The installed framework cannot satisfy the managed-driver contract."""


def install_managed_driver() -> Any:
    """Build the real FastAPI Driver without any dotenv reads.

    NoneBot 2.5.0's private resolver and global registry are intentionally used
    only here. This bridge is gated to the version exercised by CN00.
    """
    from nucleus.lifecycle import active_lifecycle

    lifecycle = active_lifecycle()
    try:
        installed = version("nonebot2")
    except PackageNotFoundError as exc:
        raise ManagedFrameworkError("NoneBot is not installed") from exc
    if installed != MANAGED_NONEBOT_VERSION:
        raise ManagedFrameworkError(
            f"managed Nucleus requires NoneBot {MANAGED_NONEBOT_VERSION}"
        )

    import nonebot
    from nonebot.config import Config, Env
    from nonebot.drivers.fastapi import Driver as FastAPIDriver

    resolver = getattr(nonebot, "_resolve_combine_expr", None)
    if not callable(resolver):
        raise ManagedFrameworkError("locked NoneBot Driver resolver is unavailable")
    env = Env(_env_file=None)
    config = Config(
        _env_file=None,
        host=lifecycle.internal_host,
        port=lifecycle.internal_port,
    )
    driver_type = resolver(config.driver)
    driver = driver_type(env, config)
    if not isinstance(driver, FastAPIDriver):
        raise ManagedFrameworkError("managed Nucleus requires the FastAPI Driver")
    nonebot._driver = driver

    lifespan = getattr(driver, "_lifespan", None)
    register_ready = getattr(lifespan, "on_ready", None)
    if not callable(register_ready):
        raise ManagedFrameworkError("locked NoneBot ready callback registry is unavailable")
    # NoneBot's Driver public API has no on_ready method; this private hook is
    # confined here and runs after all startup callbacks, before business runtimes.
    register_ready(lifecycle.mark_ready)

    original_on_shutdown = driver.on_shutdown

    def register_bounded_shutdown(_self: Any, callback: Callable[[], Any]) -> Callable[[], Any]:
        @functools.wraps(callback)
        async def bounded_callback() -> None:
            await lifecycle.run_shutdown_callback(callback)

        original_on_shutdown(bounded_callback)
        return callback

    driver.on_shutdown = MethodType(register_bounded_shutdown, driver)
    return driver


def defer_managed_business_runtimes() -> tuple[str, ...]:
    """Move scheduler/Cometa startup callbacks behind the ready gate.

    The business module keeps its legacy ``driver.on_startup`` registration.
    Only the managed bridge moves these two background work loops to NoneBot's
    post-startup ready queue, after the lifecycle ready gate callback.
    """
    from nucleus.lifecycle import active_lifecycle

    if active_lifecycle().phase != "starting":
        raise ManagedFrameworkError("business runtimes must be deferred during startup")
    import nonebot

    driver = nonebot.get_driver()
    lifespan = getattr(driver, "_lifespan", None)
    startup_funcs = getattr(lifespan, "_startup_funcs", None)
    ready_funcs = getattr(lifespan, "_ready_funcs", None)
    if not isinstance(startup_funcs, list) or not isinstance(ready_funcs, list):
        raise ManagedFrameworkError("locked NoneBot startup callback registry is unavailable")

    wanted = {"_start_scheduling", "_start_cometa"}
    deferred = [
        callback
        for callback in startup_funcs
        if getattr(callback, "__name__", "") in wanted
        and str(getattr(callback, "__module__", "")).endswith("bot_main.ai_gateway")
    ]
    for callback in deferred:
        startup_funcs.remove(callback)
    ready_funcs.extend(deferred)
    return tuple(getattr(callback, "__name__", "") for callback in deferred)
