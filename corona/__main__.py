# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Start the independent Corona control process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from corona.app import create_corona_app
from corona.bootstrap import CoronaBootstrapError, prepare_corona_bootstrap
from corona.ownership import CoronaOwnershipError, CoronaOwnershipLock
from corona.supervisor import CoreSupervisor


def main() -> int:
    try:
        bootstrap = prepare_corona_bootstrap()
    except CoronaBootstrapError as exc:
        print(f"[corona] bootstrap rejected ({type(exc).__name__})", file=sys.stderr)
        return 2

    try:
        ownership = CoronaOwnershipLock.acquire(
            bootstrap.stella_home, bootstrap.instance_id
        )
    except CoronaOwnershipError as exc:
        print(f"[corona] controller ownership rejected ({type(exc).__name__})", file=sys.stderr)
        return 73

    supervisor = CoreSupervisor(bootstrap)
    try:
        if bootstrap.recovery_mode:
            print(
                f"[corona] recovery control is listening at http://{bootstrap.public_host}:{bootstrap.public_port}",
                flush=True,
            )
        elif not bootstrap.webui_enabled:
            print(
                f"[corona] browser management is disabled; local control binds {bootstrap.public_host}:{bootstrap.public_port}",
                flush=True,
            )
        app = create_corona_app(bootstrap, supervisor)
        import uvicorn

        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=bootstrap.public_host,
                port=bootstrap.public_port,
                log_level="info",
                access_log=False,
            )
        )
        server.run()
        return 0
    except Exception as exc:
        logging.getLogger("corona").exception("Corona server failed (%s)", type(exc).__name__)
        return 1
    finally:
        with contextlib.suppress(RuntimeError):
            asyncio.run(supervisor.stop())
        ownership.close()


if __name__ == "__main__":
    raise SystemExit(main())
