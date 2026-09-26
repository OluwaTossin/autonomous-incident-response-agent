"""FastAPI correlation, request logs, metrics, and spans."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.observability.context import correlation_id, log_context
from app.observability.logging import log_event
from app.observability.slo import api_request_is_eligible
from app.observability.telemetry import HostedTelemetry
from app.observability.tracing import span

logger = logging.getLogger(__name__)


def install_http_observability(application: FastAPI, telemetry: HostedTelemetry) -> None:
    @application.middleware("http")
    async def observe_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_correlation = correlation_id(
            request.headers.get("x-correlation-id")
        )
        request.state.correlation_id = request_correlation
        started = time.monotonic()
        status_code = 500
        with log_context(
            correlation_id=request_correlation,
            request_id=request_correlation,
        ):
            with span(
                "http.request",
                **{
                    "service.name": telemetry.service,
                    "http.request.method": request.method,
                },
            ) as current_span:
                try:
                    response = await call_next(request)
                    status_code = response.status_code
                except Exception:
                    log_event(
                        logger,
                        logging.ERROR,
                        "http.request_failed",
                        "Hosted API request failed",
                        error_category="internal",
                        exc_info=True,
                    )
                    response = JSONResponse(
                        status_code=500,
                        content={"detail": "Internal server error"},
                    )
                route = request.scope.get("route")
                operation = getattr(route, "name", None) or "unmatched"
                route_template = getattr(route, "path", None) or "unmatched"
                status_class = f"{status_code // 100}xx"
                result = "succeeded" if status_code < 500 else "failed"
                duration_ms = int((time.monotonic() - started) * 1000)
                dimensions = {
                    "Operation": operation,
                    "Result": result,
                    "StatusClass": status_class,
                }
                telemetry.metrics.counter("request_count", **dimensions)
                if api_request_is_eligible(operation, status_code):
                    telemetry.metrics.counter("eligible_request_count", **dimensions)
                telemetry.metrics.histogram(
                    "request_duration_ms", duration_ms, **dimensions
                )
                if status_code >= 500:
                    telemetry.metrics.counter("server_error_count", **dimensions)
                elif status_code == 401:
                    telemetry.metrics.counter("auth_failure_count", **dimensions)
                elif status_code == 403:
                    telemetry.metrics.counter(
                        "authorization_failure_count", **dimensions
                    )
                current_span.set_attribute("http.route", route_template)
                current_span.set_attribute("http.response.status_code", status_code)
                log_event(
                    logger,
                    logging.INFO if status_code < 500 else logging.ERROR,
                    "http.request_completed",
                    "Hosted API request completed",
                    operation=operation,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    error_category=("internal" if status_code >= 500 else None),
                )
                response.headers["x-correlation-id"] = request_correlation
                return response
