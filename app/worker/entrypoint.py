"""Process entrypoint used by the future ECS bootstrap composition."""

from __future__ import annotations

import threading

from app.worker.runtime import (
    HostedDispatcherRuntime,
    HostedWorkerRuntime,
    PollingWorker,
    install_shutdown_handlers,
)


def run_worker(runtime: HostedWorkerRuntime) -> None:
    """Run until SIGINT/SIGTERM, then stop polling and finish the bounded batch."""
    stop = threading.Event()
    install_shutdown_handlers(stop)
    runtime.run(stop)


def run_polling_worker(worker: PollingWorker) -> None:
    stop = threading.Event()
    install_shutdown_handlers(stop)
    worker.run(stop)


def run_dispatcher(dispatcher: HostedDispatcherRuntime) -> None:
    stop = threading.Event()
    install_shutdown_handlers(stop)
    dispatcher.run(stop)
