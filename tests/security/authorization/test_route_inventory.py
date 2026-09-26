"""Machine-maintained hosted API and BFF security inventories."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIRoute

from app.api.hosted_alert_ingestion import build_hosted_alert_ingestion_router
from app.api.hosted_aws_integrations import build_hosted_aws_integration_router
from app.api.hosted_bootstrap import build_hosted_bootstrap_router
from app.api.hosted_incidents import build_hosted_incident_router
from app.api.hosted_usage import build_hosted_usage_router
from app.api.hosted_workspaces import build_hosted_workspace_router
from app.security.cursors import CursorCodec

ROOT = Path(__file__).resolve().parents[3]
MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CURSORS = CursorCodec("test-cursor-signing-key-at-least-32-bytes")


def _human_actor():
    raise AssertionError("route inventory must not execute dependencies")


def _machine_actor():
    raise AssertionError("route inventory must not execute dependencies")


def _routes() -> tuple[APIRoute, ...]:
    placeholder = object()
    routers = (
        build_hosted_bootstrap_router(placeholder, _human_actor),
        build_hosted_workspace_router(
            placeholder, _human_actor, cursor_codec=CURSORS
        ),
        build_hosted_incident_router(
            placeholder,
            _human_actor,
            cursor_codec=CURSORS,
            action_proposals=placeholder,
            approvals=placeholder,
            execution_intents=placeholder,
        ),
        build_hosted_aws_integration_router(placeholder, _human_actor),
        build_hosted_usage_router(placeholder, _human_actor),
        build_hosted_alert_ingestion_router(placeholder, _machine_actor),
    )
    return tuple(
        route
        for router in routers
        for route in router.routes
        if isinstance(route, APIRoute)
    )


def test_every_hosted_route_has_the_expected_authentication_dependency() -> None:
    routes = _routes()
    assert len(routes) >= 30
    for route in routes:
        expected = _machine_actor if route.path.startswith("/internal/") else _human_actor
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        assert expected in dependency_calls, f"{sorted(route.methods)} {route.path} lacks auth"


def test_hosted_route_inventory_has_no_execution_or_get_mutation_route() -> None:
    routes = _routes()
    inventory = {(method, route.path) for route in routes for method in route.methods}
    assert ("POST", "/internal/v1/organizations/{organization_id}/workspaces/{workspace_id}/integrations/aws/{integration_id}/cloudwatch-alarms") in inventory
    assert not any(
        forbidden in path
        for _method, path in inventory
        for forbidden in ("/execute", "/apply", "/remediate")
    )
    assert all(
        not ({"GET"} & route.methods and MUTATION_METHODS & route.methods)
        for route in routes
    )


def test_every_bff_api_route_uses_session_and_mutations_request_csrf() -> None:
    route_files = sorted((ROOT / "web/src/app/api").rglob("route.ts"))
    assert route_files
    exported = re.compile(r"export async function (GET|POST|PUT|PATCH|DELETE)\b")
    for route_file in route_files:
        source = route_file.read_text(encoding="utf-8")
        methods = set(exported.findall(source))
        assert methods, route_file
        assert "withBffSession" in source, f"{route_file} is an unprotected BFF route"
        if methods & MUTATION_METHODS:
            assert re.search(r"withBffSession\([^,]+,\s*true\s*,", source, re.DOTALL), (
                f"{route_file} mutation does not require CSRF"
            )
        assert "cache-control" not in source.lower() or "no-store" in source.lower()
