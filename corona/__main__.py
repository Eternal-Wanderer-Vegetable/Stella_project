# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Start the independent Corona control process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys

from corona.app import create_corona_app
from corona.bootstrap import CoronaBootstrapError, prepare_corona_bootstrap
from corona.config_store import ConfigStore
from corona.operations import OperationManager
from corona.ownership import CoronaOwnershipError, CoronaOwnershipLock
from corona.recovery import RecoveryManager
from corona.supervisor import CoreSupervisor
from stella_bootstrap.config import CONFIG_REVISION_FILE_ENV


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
        print(
            f"[corona] controller ownership rejected ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 73

    supervisor = None
    try:
        store = ConfigStore(
            stella_home=bootstrap.stella_home,
            instance_id=bootstrap.instance_id,
            project_root=bootstrap.project_root,
            external_environment=dict(os.environ),
        )
        store.initialize(bootstrap.revision)
        recovery = RecoveryManager(store)
        decision = recovery.prepare_startup(bootstrap.controller_boot_id)
        selected_revision, selected_path = store.get_revision(decision.revision_id)
        selected_environment = dict(os.environ)
        selected_environment[CONFIG_REVISION_FILE_ENV] = str(selected_path)
        selected_environment["STELLA_INSTANCE_ID"] = bootstrap.instance_id
        bootstrap = prepare_corona_bootstrap(
            selected_environment,
            project_root=bootstrap.project_root,
        )
        if bootstrap.revision.revision_id != selected_revision.revision_id:
            raise CoronaBootstrapError(
                "selected recovery revision changed while loading"
            )

        supervisor = CoreSupervisor(bootstrap)
        operation_manager = OperationManager(store, supervisor)
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
        app = create_corona_app(
            bootstrap,
            supervisor,
            config_store=store,
            operation_manager=operation_manager,
            startup_decision=decision,
        )
        import uvicorn

        public_server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=bootstrap.public_host,
                port=bootstrap.public_port,
                log_level="info",
                access_log=False,
                proxy_headers=False,
            )
        )
        local_app = app.state.local_control_app
        local_server = _local_server_class(uvicorn.Server)(
            uvicorn.Config(
                local_app,
                host="127.0.0.1",
                port=bootstrap.local_control_port,
                log_level="warning",
                access_log=False,
                lifespan="off",
            )
        )

        def request_controller_shutdown() -> None:
            public_server.should_exit = True
            local_server.should_exit = True

        app.state.request_controller_shutdown = request_controller_shutdown
        operation_manager.set_controller_shutdown(request_controller_shutdown)
        local_app.state.controller_app = app
        print(
            f"[corona] local deploy control is listening at http://127.0.0.1:{bootstrap.local_control_port}",
            flush=True,
        )
        asyncio.run(_serve_servers(public_server, local_server))
        return 0
    except Exception as exc:
        logging.getLogger("corona").exception(
            "Corona server failed (%s)", type(exc).__name__
        )
        return 1
    finally:
        if supervisor is not None:
            with contextlib.suppress(RuntimeError):
                asyncio.run(supervisor.stop())
        ownership.close()


def _local_server_class(server_class):
    class LocalControlServer(server_class):
        def install_signal_handlers(self) -> None:
            # The public server owns process-level signal handling.
            return

    return LocalControlServer


async def _serve_servers(public_server, local_server) -> None:
    tasks = {
        asyncio.create_task(public_server.serve(), name="corona-public-http"),
        asyncio.create_task(local_server.serve(), name="corona-local-control-http"),
    }
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    public_server.should_exit = True
    local_server.should_exit = True
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(
            result, asyncio.CancelledError
        ):
            raise result


if __name__ == "__main__":
    raise SystemExit(main())
