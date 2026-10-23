# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Run the existing Stella business assembly as one managed Nucleus generation."""

from __future__ import annotations

import runpy
import sys
from typing import Any

from nucleus.bootstrap import ManagedBootstrapError, prepare_managed_environment
from nucleus.lifecycle import (
    BusinessRootLock,
    BusinessRootLockError,
    ManagedNucleusASGI,
    NucleusLifecycle,
    set_active_lifecycle,
)


def _make_server(config: Any, lifecycle: NucleusLifecycle) -> Any:
    """Build a Uvicorn server that starts one budget for every shutdown path."""
    import uvicorn

    class ManagedUvicornServer(uvicorn.Server):
        async def shutdown(self, sockets=None) -> None:
            lifecycle.begin_shutdown()
            await super().shutdown(sockets=sockets)

    return ManagedUvicornServer(config)


def main() -> int:
    try:
        bootstrap = prepare_managed_environment()
    except ManagedBootstrapError as exc:
        print(f"[nucleus] bootstrap rejected ({type(exc).__name__})", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[nucleus] bootstrap failed ({type(exc).__name__})", file=sys.stderr)
        return 2

    try:
        lock = BusinessRootLock.acquire(bootstrap.database_path)
    except BusinessRootLockError as exc:
        print(f"[nucleus] business database ownership rejected ({type(exc).__name__})", file=sys.stderr)
        return 73

    lifecycle = NucleusLifecycle(
        instance_id=bootstrap.instance_id,
        controller_boot_id=bootstrap.controller_boot_id,
        generation_id=bootstrap.generation_id,
        revision_id=bootstrap.revision.revision_id,
        launch_token=bootstrap.launch_token,
        internal_host=bootstrap.internal_host,
        internal_port=bootstrap.internal_port,
    )
    set_active_lifecycle(lifecycle)
    result = 1
    try:
        # Import and execute the existing business assembly only after the data
        # root lock is held. The non-main module name bypasses legacy dashboard,
        # replacement and self-registration side effects in bot.py.
        runpy.run_module("bot", run_name="nucleus_bot", alter_sys=False)

        import nonebot
        import uvicorn

        driver = nonebot.get_driver()
        from nucleus.framework import defer_managed_business_runtimes

        deferred = defer_managed_business_runtimes()
        if set(deferred) != {"_start_scheduling", "_start_cometa"}:
            raise RuntimeError("managed scheduler and Cometa ready hooks were not registered")
        app = ManagedNucleusASGI(nonebot.get_asgi(), lifecycle)
        logging_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {"default": {"class": "nonebot.log.LoguruHandler"}},
            "loggers": {
                "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
                "uvicorn.access": {"handlers": ["default"], "level": "INFO"},
            },
        }
        server = _make_server(
            uvicorn.Config(
                app,
                host=bootstrap.internal_host,
                port=bootstrap.internal_port,
                log_config=logging_config,
                timeout_graceful_shutdown=5,
            ),
            lifecycle,
        )
        lifecycle.attach_server(server)
        # Driver remains a local assertion point so an unsupported/non-ASGI path
        # fails before serving or releasing the business-root lock.
        if driver.config.host.compressed != bootstrap.internal_host:
            raise RuntimeError("NoneBot Driver host does not match managed address")
        if driver.config.port != bootstrap.internal_port:
            raise RuntimeError("NoneBot Driver port does not match managed address")
        server.run()
        result = 0
    except KeyboardInterrupt:
        result = 130
    except Exception as exc:
        lifecycle.mark_startup_failed()
        print(f"[nucleus] generation failed ({type(exc).__name__})", file=sys.stderr)
        result = 1
    finally:
        lifecycle.cancel_watchdog()
        set_active_lifecycle(None)
        lock.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
