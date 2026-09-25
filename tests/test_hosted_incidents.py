"""Hosted incident and asynchronous triage application tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.hosted_incidents import build_hosted_incident_router
from app.application.incidents import HostedIncidentInput, HostedIncidentService
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.service import (
    AuthorizationDenied,
    AuthorizationService,
    HumanAuthorizationFacts,
)
from app.domain.common import ActorKind, ActorReference
from app.domain.identifiers import MembershipId, OrganizationId, UserId, WorkspaceId
from app.domain.operations import JobState
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000001")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000002")


def _actor() -> ActorContext:
    return ActorContext(
        ActorReference(
            ActorKind.HUMAN,
            actor_id=UserId("00000000-0000-4000-8000-000000000003"),
        ),
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="operator",
    )


class Facts:
    def human_facts(self, actor, organization_id, workspace_id):
        if organization_id != ORG or workspace_id != WORKSPACE:
            return None
        return HumanAuthorizationFacts(
            MembershipId("00000000-0000-4000-8000-000000000004"),
            MembershipRole.OPERATOR,
            WorkspaceAccessMode.ALL,
            True,
        )

    def service_account_facts(self, actor, organization_id, workspace_id):
        return None

    def invited_membership_id(self, actor, organization_id):
        return None

    def visible_organization_ids(self, actor):
        return (ORG,)


class Resources:
    def __init__(self, active=True):
        self.active = active

    def is_active(self, organization_id, workspace_id):
        return self.active and organization_id == ORG and workspace_id == WORKSPACE


class Store:
    def __init__(self):
        self.incidents = {}
        self.runs = {}
        self.jobs = {}
        self.dispatches = []
        self.audits = []
        self.evidence = {}
        self.feedback = []


class Incidents:
    def __init__(self, store):
        self.store = store

    def create_or_get(self, incident):
        for current in self.store.incidents.values():
            if (
                incident.source.external_id
                and current.source.provider == incident.source.provider
                and current.source.external_id == incident.source.external_id
            ):
                return current, False
        self.store.incidents[incident.id] = incident
        return incident, True

    def get(self, incident_id, *, for_update=False):
        return self.store.incidents.get(incident_id)

    def list(self, *, limit, before, state=None):
        values = list(self.store.incidents.values())
        if state is not None:
            values = [item for item in values if item.state is state]
        values.sort(key=lambda item: (item.created_at, str(item.id)), reverse=True)
        if before is not None:
            values = [
                item
                for item in values
                if (item.created_at, str(item.id))
                < (before.created_at, str(before.incident_id))
            ]
        return values[:limit]


class Runs:
    def __init__(self, store):
        self.store = store

    def add(self, run):
        self.store.runs[run.id] = run

    def get(self, run_id, *, for_update=False):
        return self.store.runs.get(run_id)

    def list(self, *, limit, before, incident_id=None, state=None):
        values = list(self.store.runs.values())
        if incident_id is not None:
            values = [item for item in values if item.incident.id == incident_id]
        if state is not None:
            values = [item for item in values if item.state is state]
        values.sort(key=lambda item: (item.created_at, str(item.id)), reverse=True)
        return values[:limit]

    def save(self, run, *, expected_version):
        assert self.store.runs[run.id].state_version == expected_version
        self.store.runs[run.id] = run


class Jobs:
    def __init__(self, store):
        self.store = store

    def create_or_get(self, job):
        for current in self.store.jobs.values():
            if current.kind == job.kind and current.idempotency_key == job.idempotency_key:
                return current, False
        self.store.jobs[job.id] = job
        return job, True

    def get(self, job_id, *, for_update=False):
        return self.store.jobs.get(job_id)

    def get_by_subject(self, subject_type, subject_id, *, for_update=False):
        return next(
            (
                job
                for job in self.store.jobs.values()
                if job.subject_type == subject_type and job.subject_id == subject_id
            ),
            None,
        )

    def save(self, job, *, expected_version):
        assert self.store.jobs[job.id].state_version == expected_version
        self.store.jobs[job.id] = job


class Dispatches:
    def __init__(self, store):
        self.store = store

    def add(self, job, *, at):
        self.store.dispatches.append((job.id, job.dispatch_generation))


class EvidenceRepo:
    def __init__(self, store):
        self.store = store

    def list_for_run(self, run_id):
        return self.store.evidence.get(run_id, ())

    def replace_for_run(self, run_id, evidence):
        self.store.evidence[run_id] = tuple(evidence)


class FeedbackRepo:
    def __init__(self, store):
        self.store = store

    def add(self, feedback):
        self.store.feedback.append(feedback)


class Audits:
    def __init__(self, store):
        self.store = store

    def add(self, event):
        self.store.audits.append(event)


class Uow:
    def __init__(self, store):
        self.incidents = Incidents(store)
        self.triage_runs = Runs(store)
        self.jobs = Jobs(store)
        self.dispatches = Dispatches(store)
        self.evidence = EvidenceRepo(store)
        self.feedback = FeedbackRepo(store)
        self.audit_events = Audits(store)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


def _service(*, active=True):
    store = Store()
    service = HostedIncidentService(
        AuthorizationService(Facts(), Resources(active)),
        lambda context: Uow(store),
        clock=lambda: NOW,
        monotonic=lambda: 1.0,
    )
    return service, store


def _input(**changes):
    values = {
        "title": "Payments latency",
        "description": "Requests exceed the latency objective",
        "service_name": "payments-api",
        "environment": "production",
        "source_provider": "manual",
        "source_type": "operator",
        "observed_at": NOW,
        "external_event_id": "event-42",
        "severity_hint": "HIGH",
    }
    values.update(changes)
    return HostedIncidentInput(**values)


def test_incident_create_read_list_and_external_id_idempotency() -> None:
    service, store = _service()
    created = service.create_incident(_actor(), ORG, WORKSPACE, _input())
    reused = service.create_incident(_actor(), ORG, WORKSPACE, _input())

    assert reused.id == created.id
    assert service.get_incident(_actor(), ORG, WORKSPACE, created.id) == created
    assert service.list_incidents(_actor(), ORG, WORKSPACE) == (created,)
    assert [event.event_type for event in store.audits] == ["incident.created"]


def test_archived_workspace_and_input_limits_are_rejected() -> None:
    service, _ = _service(active=False)
    with pytest.raises(AuthorizationDenied):
        service.create_incident(_actor(), ORG, WORKSPACE, _input())
    with pytest.raises(ValueError, match="title exceeds"):
        _input(title="x" * 201)


def test_triage_request_is_atomic_shape_and_idempotent() -> None:
    service, store = _service()
    incident = service.create_incident(_actor(), ORG, WORKSPACE, _input())

    first = service.request_triage(
        _actor(), ORG, WORKSPACE, incident.id, idempotency_key="request-1"
    )
    second = service.request_triage(
        _actor(), ORG, WORKSPACE, incident.id, idempotency_key="request-1"
    )

    assert first.created is True
    assert second.created is False
    assert second.run.id == first.run.id
    assert second.job.id == first.job.id
    assert first.job.state is JobState.PENDING
    assert dict(first.job.payload) == {
        "incident_id": str(incident.id),
        "triage_run_id": str(first.run.id),
    }
    assert len(store.dispatches) == 1
    assert [event.event_type for event in store.audits] == [
        "incident.created",
        "triage.requested",
    ]


def test_pending_triage_cancellation_updates_job_and_run_together() -> None:
    service, _ = _service()
    incident = service.create_incident(_actor(), ORG, WORKSPACE, _input())
    requested = service.request_triage(
        _actor(), ORG, WORKSPACE, incident.id, idempotency_key="request-2"
    )

    cancelled = service.cancel_triage(
        _actor(), ORG, WORKSPACE, requested.run.id
    )

    assert cancelled.run.state.value == "cancelled"
    assert cancelled.job.state is JobState.CANCELLED


def test_running_triage_cancellation_is_requested_until_worker_acknowledges() -> None:
    service, store = _service()
    incident = service.create_incident(_actor(), ORG, WORKSPACE, _input())
    requested = service.request_triage(
        _actor(), ORG, WORKSPACE, incident.id, idempotency_key="request-3"
    )
    running_job = requested.job.claim(
        worker_id="worker-a",
        claim_token=uuid4(),
        lease_expires_at=NOW + timedelta(minutes=5),
        at=NOW,
    )
    running_run = requested.run.start(at=NOW)
    store.jobs[running_job.id] = running_job
    store.runs[running_run.id] = running_run

    cancelled = service.cancel_triage(
        _actor(), ORG, WORKSPACE, requested.run.id
    )

    assert cancelled.run.state.value == "running"
    assert cancelled.job.state is JobState.RUNNING
    assert cancelled.job.cancellation_requested_at == NOW


def test_hosted_api_returns_202_and_stable_polling_contract() -> None:
    service, _ = _service()
    application = FastAPI()
    application.include_router(
        build_hosted_incident_router(service, lambda: _actor())
    )
    client = TestClient(application)
    prefix = f"/v3/organizations/{ORG}/workspaces/{WORKSPACE}"
    created = client.post(
        f"{prefix}/incidents",
        json={
            "title": "Payments latency",
            "description": "Requests exceed the latency objective",
            "service_name": "payments-api",
            "environment": "production",
            "source_provider": "manual",
            "source_type": "operator",
            "observed_at": NOW.isoformat(),
            "external_event_id": "api-event-1",
        },
    )
    assert created.status_code == 201
    incident_id = created.json()["incident_id"]

    queued = client.post(
        f"{prefix}/incidents/{incident_id}/triage",
        headers={"Idempotency-Key": "api-request-1"},
    )
    assert queued.status_code == 202
    body = queued.json()
    assert body["triage_id"] == body["triage_run_id"]
    assert body["state"] == "queued"
    assert body["job_state"] == "pending"

    polled = client.get(f"{prefix}/triage-runs/{body['triage_run_id']}")
    assert polled.status_code == 200
    assert polled.json()["result"] is None
    assert "claim_token" not in polled.text

    page = client.get(f"{prefix}/incidents", params={"limit": 1})
    assert page.status_code == 200
    assert len(page.json()["items"]) == 1

    schema = application.openapi()
    triage_path = (
        "/v3/organizations/{organization_id}/workspaces/{workspace_id}"
        "/incidents/{incident_id}/triage"
    )
    assert schema["paths"][triage_path]["post"]["responses"].get("202")

    forbidden = client.get(
        f"/v3/organizations/00000000-0000-4000-8000-000000000099/"
        f"workspaces/{WORKSPACE}/incidents"
    )
    assert forbidden.status_code == 403


def test_hosted_api_authentication_failure_stays_at_dependency_boundary() -> None:
    service, _ = _service()

    def deny():
        raise HTTPException(status_code=401, detail="Unauthorized")

    application = FastAPI()
    application.include_router(build_hosted_incident_router(service, deny))
    response = TestClient(application).get(
        f"/v3/organizations/{ORG}/workspaces/{WORKSPACE}/incidents"
    )
    assert response.status_code == 401
