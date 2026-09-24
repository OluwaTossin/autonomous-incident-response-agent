"""Process entrypoint used by the future ECS bootstrap composition."""

from __future__ import annotations

import threading

from app.worker.runtime import HostedWorkerRuntime, install_shutdown_handlers


def run_worker(runtime: HostedWorkerRuntime) -> None:
    """Run until SIGINT/SIGTERM, then stop polling and finish the bounded batch."""
    stop = threading.Event()
    install_shutdown_handlers(stop)
    runtime.run(stop)
