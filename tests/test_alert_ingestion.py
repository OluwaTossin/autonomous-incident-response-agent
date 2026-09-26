"""CloudWatch alarm ingestion domain, application, and API tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.api.hosted_alert_ingestion import build_hosted_alert_ingestion_router
from app.application.alert_ingestion import (
    AlertIngestionConflict,
    AlertIngestionDenied,
    AlertIngestionNotFound,
    AlertIngestionOutcome,
    HostedAlertIngestionService,
)
from app.auth.context import ActorContext, AuthenticationMethod, trusted_system_actor
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, SystemAuthorizationGrant
from app.domain.alert_ingestion import CloudWatchAlarmEvent, CloudWatchAlarmValue
from app.domain.aws_integrations import (
    REQUIRED_AWS_CAPABILITIES,
    AwsCapabilityCheck,
    AwsIntegration,
    AwsIntegrationState,
    AwsVerificationResult,
)
from app.domain.common import ActorKind, ActorReference, WorkspaceScope
from app.domain.identifiers import (
    IntegrationId,
    OrganizationId,
    UserId,
    WorkspaceId,
)
from app.domain.incidents import IncidentState

NOW = datetime(2026, 9, 25, 17, 0, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000701")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000702")
INTEGRATION = IntegrationId("00000000-0000-4000-8000-000000000703")


def _machine() -> ActorContext:
    return trusted_system_actor(
        system_name="alert-ingress",
        workload_issuer="https://sts.example",
        workload_subject="role/alert-ingress",
    )


def _human() -> ActorContext:
    return ActorContext(
        ActorReference(
            ActorKind.HUMAN,
            actor_id=UserId("00000000-0000-4000-8000-000000000704"),
        ),
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="operator",
    )


class Facts:
    def human_facts(self, actor, organization_id, workspace_id):
        return None

    def service_account_facts(self, actor, organization_id, workspace_id):
        return None

    def invited_membership_id(self, actor, organization_id):
        return None

    def visible_organization_ids(self, actor):
        return ()


class Resources:
    def is_active(self, organization_id, workspace_id):
        return organization_id == ORG and workspace_id == WORKSPACE


class Store:
    def __init__(self, integration):
        self.integrations = {integration.id: integration}
        self.receipts = {}
        self.states = {}
        self.incidents = {}
        self.runs = {}
        self.jobs = {}
        self.dispatches = []
        self.audits = []


class Integrations:
    def __init__(self, store): self.store = store
    def get(self, integration_id): return self.store.integrations.get(integration_id)


class Receipts:
    def __init__(self, store): self.store = store
    def create_or_get(self, receipt):
        key = (receipt.integration_id, receipt.event_id)
        if key in self.store.receipts:
            return self.store.receipts[key], False
        self.store.receipts[key] = receipt
        return receipt, True
    def save(self, receipt):
        self.store.receipts[(receipt.integration_id, receipt.event_id)] = receipt


class States:
    def __init__(self, store): self.store = store
    def lock_identity(self, integration_id, identity_hash): return None
    def get(self, integration_id, identity_hash):
        return self.store.states.get((integration_id, identity_hash))
    def add(self, state):
        self.store.states[(state.integration_id, state.alarm_identity_hash)] = state
    def save(self, state): self.add(state)


class Incidents:
    def __init__(self, store): self.store = store
    def create_or_get(self, incident):
        for current in self.store.incidents.values():
            if (
                current.source.provider == incident.source.provider
                and current.source.external_id == incident.source.external_id
            ):
                return current, False
        self.store.incidents[incident.id] = incident
        return incident, True
    def get(self, incident_id, *, for_update=False):
        return self.store.incidents.get(incident_id)
    def save(self, incident): self.store.incidents[incident.id] = incident


class Runs:
    def __init__(self, store): self.store = store
    def add(self, run): self.store.runs[run.id] = run


class Jobs:
    def __init__(self, store): self.store = store
    def create_or_get(self, job):
        for current in self.store.jobs.values():
            if current.kind == job.kind and current.idempotency_key == job.idempotency_key:
                return current, False
        self.store.jobs[job.id] = job
        return job, True


class Dispatches:
    def __init__(self, store): self.store = store
    def add(self, job, *, at):
        self.store.dispatches.append((job.id, job.dispatch_generation))


class Audits:
    def __init__(self, store): self.store = store
    def add(self, event): self.store.audits.append(event)


class Uow:
    def __init__(self, store):
        self.aws_integrations = Integrations(store)
        self.alert_receipts = Receipts(store)
        self.alarm_states = States(store)
        self.incidents = Incidents(store)
        self.triage_runs = Runs(store)
        self.jobs = Jobs(store)
        self.dispatches = Dispatches(store)
        self.audit_events = Audits(store)
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_value, traceback): return None


def _integration(state=AwsIntegrationState.READY) -> AwsIntegration:
    checks = tuple(
        AwsCapabilityCheck(capability, "eu-west-2", True)
        for capability in REQUIRED_AWS_CAPABILITIES
    )
    verification = AwsVerificationResult(True, True, checks, NOW)
    return AwsIntegration(
        id=INTEGRATION,
        scope=WorkspaceScope(ORG, WORKSPACE),
        display_name="Production AWS",
        aws_account_id="123456789012",
        role_arn="arn:aws:iam::123456789012:role/aira-read",
        external_id="x" * 43,
        enabled_regions=("eu-west-2",),
        state=state,
        verification=verification if state is AwsIntegrationState.READY else None,
        created_by=_machine().actor,
        created_at=NOW,
        updated_at=NOW,
    )


def _service(integration=None):
    store = Store(integration or _integration())
    authorization = AuthorizationService(
        Facts(),
        Resources(),
        system_grants=(
            SystemAuthorizationGrant(
                "alert-ingress",
                "https://sts.example",
                "role/alert-ingress",
                ORG,
                frozenset(
                    {
                        Permission.INTEGRATION_READ,
                        Permission.INCIDENT_CREATE,
                        Permission.TRIAGE_RUN,
                        Permission.JOB_CREATE,
                    }
                ),
                frozenset({WORKSPACE}),
            ),
        ),
    )
    return (
        HostedAlertIngestionService(
            authorization,
            lambda context: Uow(store),
            clock=lambda: NOW,
            monotonic=lambda: 1.0,
        ),
        store,
    )


def _event(**changes) -> CloudWatchAlarmEvent:
    values = {
        "schema_version": 1,
        "event_id": "11111111-1111-4111-8111-111111111111",
        "account_id": "123456789012",
        "region": "eu-west-2",
        "observed_at": NOW - timedelta(minutes=1),
        "alarm_name": "payments-latency",
        "alarm_arn": "arn:aws:cloudwatch:eu-west-2:123456789012:alarm:payments-latency",
        "state": CloudWatchAlarmValue.ALARM,
        "previous_state": CloudWatchAlarmValue.OK,
        "reason": "Threshold crossed",
        "resources": (
            "arn:aws:cloudwatch:eu-west-2:123456789012:alarm:payments-latency",
        ),
    }
    values.update(changes)
    return CloudWatchAlarmEvent(**values)


def _envelope(**changes):
    payload = {
        "version": "0",
        "id": "11111111-1111-4111-8111-111111111111",
        "detail-type": "CloudWatch Alarm State Change",
        "source": "aws.cloudwatch",
        "account": "123456789012",
        "time": (NOW - timedelta(minutes=1)).isoformat(),
        "region": "eu-west-2",
        "resources": [
            "arn:aws:cloudwatch:eu-west-2:123456789012:alarm:payments-latency"
        ],
        "detail": {
            "alarmName": "payments-latency",
            "state": {"value": "ALARM", "reason": "Threshold crossed"},
            "previousState": {"value": "OK"},
        },
    }
    payload.update(changes)
    return payload


def test_alarm_creates_incident_triage_job_outbox_and_audit() -> None:
    service, store = _service()
    result = service.ingest(_machine(), ORG, WORKSPACE, INTEGRATION, _event())

    assert result.outcome is AlertIngestionOutcome.ACCEPTED
    assert len(store.incidents) == len(store.runs) == len(store.jobs) == 1
    assert len(store.dispatches) == 1
    incident = next(iter(store.incidents.values()))
    assert incident.source.provider == "aws.cloudwatch"
    assert incident.payload.severity_hint == "HIGH"
    assert incident.payload.time_of_occurrence == (
        NOW - timedelta(minutes=1)
    ).isoformat()
    assert {event.event_type for event in store.audits} >= {
        "alarm_event.accepted",
        "incident.created",
        "triage.requested",
    }


def test_duplicate_is_idempotent_and_conflicting_payload_fails_closed() -> None:
    service, store = _service()
    first = service.ingest(_machine(), ORG, WORKSPACE, INTEGRATION, _event())
    duplicate = service.ingest(_machine(), ORG, WORKSPACE, INTEGRATION, _event())

    assert duplicate.outcome is AlertIngestionOutcome.DUPLICATE
    assert duplicate.incident_id == first.incident_id
    assert len(store.incidents) == len(store.runs) == len(store.jobs) == 1
    with pytest.raises(AlertIngestionConflict, match="different content"):
        service.ingest(
            _machine(), ORG, WORKSPACE, INTEGRATION, _event(reason="Changed content")
        )


def test_state_policy_recovery_and_stale_ordering() -> None:
    service, store = _service()
    alarm = _event()
    first = service.ingest(_machine(), ORG, WORKSPACE, INTEGRATION, alarm)
    insufficient = _event(
        event_id="22222222-2222-4222-8222-222222222222",
        observed_at=alarm.observed_at + timedelta(seconds=10),
        state=CloudWatchAlarmValue.INSUFFICIENT_DATA,
        previous_state=CloudWatchAlarmValue.ALARM,
    )
    assert service.ingest(
        _machine(), ORG, WORKSPACE, INTEGRATION, insufficient
    ).outcome is AlertIngestionOutcome.IGNORED
    repeated_alarm = _event(
        event_id="33333333-3333-4333-8333-333333333333",
        observed_at=alarm.observed_at + timedelta(seconds=20),
        previous_state=CloudWatchAlarmValue.INSUFFICIENT_DATA,
    )
    assert service.ingest(
        _machine(), ORG, WORKSPACE, INTEGRATION, repeated_alarm
    ).outcome is AlertIngestionOutcome.IGNORED
    stale = _event(
        event_id="44444444-4444-4444-8444-444444444444",
        observed_at=alarm.observed_at + timedelta(seconds=5),
        state=CloudWatchAlarmValue.OK,
        previous_state=CloudWatchAlarmValue.ALARM,
    )
    assert service.ingest(
        _machine(), ORG, WORKSPACE, INTEGRATION, stale
    ).outcome is AlertIngestionOutcome.IGNORED
    recovery = replace(
        stale,
        event_id="55555555-5555-4555-8555-555555555555",
        observed_at=alarm.observed_at + timedelta(seconds=30),
    )
    recovered = service.ingest(_machine(), ORG, WORKSPACE, INTEGRATION, recovery)
    assert recovered.incident_id == first.incident_id
    assert store.incidents[first.incident_id].state is IncidentState.RESOLVED

    new_alarm = replace(
        alarm,
        event_id="66666666-6666-4666-8666-666666666666",
        observed_at=alarm.observed_at + timedelta(seconds=40),
    )
    second = service.ingest(_machine(), ORG, WORKSPACE, INTEGRATION, new_alarm)
    assert second.incident_id != first.incident_id
    assert len(store.incidents) == len(store.runs) == len(store.jobs) == 2


def test_machine_scope_and_ready_account_region_checks_fail_closed() -> None:
    service, _ = _service()
    with pytest.raises(AlertIngestionDenied):
        service.ingest(_human(), ORG, WORKSPACE, INTEGRATION, _event())
    with pytest.raises(AlertIngestionConflict, match="account"):
        service.ingest(
            _machine(),
            ORG,
            WORKSPACE,
            INTEGRATION,
            _event(
                account_id="999999999999",
                alarm_arn="arn:aws:cloudwatch:eu-west-2:999999999999:alarm:payments-latency",
                resources=(
                    "arn:aws:cloudwatch:eu-west-2:999999999999:alarm:payments-latency",
                ),
            ),
        )
    with pytest.raises(AlertIngestionConflict, match="region"):
        service.ingest(
            _machine(),
            ORG,
            WORKSPACE,
            INTEGRATION,
            _event(
                region="us-east-1",
                alarm_arn="arn:aws:cloudwatch:us-east-1:123456789012:alarm:payments-latency",
                resources=(
                    "arn:aws:cloudwatch:us-east-1:123456789012:alarm:payments-latency",
                ),
            ),
        )
    with pytest.raises(AlertIngestionConflict, match="future"):
        service.ingest(
            _machine(),
            ORG,
            WORKSPACE,
            INTEGRATION,
            _event(observed_at=NOW + timedelta(minutes=6)),
        )
    with pytest.raises(AlertIngestionNotFound):
        service.ingest(
            _machine(),
            ORG,
            WORKSPACE,
            IntegrationId("00000000-0000-4000-8000-000000000799"),
            _event(),
        )
    not_ready, _ = _service(_integration(AwsIntegrationState.PENDING_VERIFICATION))
    with pytest.raises(AlertIngestionConflict, match="not ready"):
        not_ready.ingest(_machine(), ORG, WORKSPACE, INTEGRATION, _event())


def test_payload_tenant_hints_cannot_select_scope_or_create_foreign_side_effects() -> None:
    service, store = _service()
    app = FastAPI()
    app.include_router(build_hosted_alert_ingestion_router(service, lambda: _machine()))
    client = TestClient(app)
    path = f"/internal/v1/organizations/{ORG}/workspaces/{WORKSPACE}/integrations/aws/{INTEGRATION}/cloudwatch-alarms"
    payload = _envelope(
        organization_id="00000000-0000-4000-8000-000000000799",
        workspace_id="00000000-0000-4000-8000-000000000798",
        integration_id="00000000-0000-4000-8000-000000000797",
    )

    accepted = client.post(path, json=payload)
    assert accepted.status_code == 202
    incident = next(iter(store.incidents.values()))
    assert incident.scope == WorkspaceScope(ORG, WORKSPACE)

    counts = {
        "receipts": len(store.receipts),
        "incidents": len(store.incidents),
        "runs": len(store.runs),
        "jobs": len(store.jobs),
        "dispatches": len(store.dispatches),
        "audits": len(store.audits),
    }
    foreign_path = (
        "/internal/v1/organizations/00000000-0000-4000-8000-000000000799/"
        f"workspaces/{WORKSPACE}/integrations/aws/{INTEGRATION}/cloudwatch-alarms"
    )
    denied = client.post(
        foreign_path,
        json=_envelope(id="22222222-2222-4222-8222-222222222222"),
    )
    assert denied.status_code == 403
    assert counts == {
        "receipts": len(store.receipts),
        "incidents": len(store.incidents),
        "runs": len(store.runs),
        "jobs": len(store.jobs),
        "dispatches": len(store.dispatches),
        "audits": len(store.audits),
    }


def test_machine_api_authentication_validation_and_acknowledgement() -> None:
    service, _ = _service()

    def authenticate(request: Request):
        if request.headers.get("authorization") != "AiraServiceAccount test":
            raise HTTPException(status_code=401, detail="Unauthorized")
        return _machine()

    app = FastAPI()
    app.include_router(build_hosted_alert_ingestion_router(service, authenticate))
    client = TestClient(app)
    path = f"/internal/v1/organizations/{ORG}/workspaces/{WORKSPACE}/integrations/aws/{INTEGRATION}/cloudwatch-alarms"

    assert client.post(path, json=_envelope()).status_code == 401
    accepted = client.post(
        path,
        json=_envelope(),
        headers={"authorization": "AiraServiceAccount test"},
    )
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "accepted"
    invalid = client.post(
        path,
        json=_envelope(source="aws.ec2"),
        headers={"authorization": "AiraServiceAccount test"},
    )
    assert invalid.status_code == 422
    oversized = client.post(
        path,
        content=b"x" * 65_537,
        headers={
            "authorization": "AiraServiceAccount test",
            "content-type": "application/json",
        },
    )
    assert oversized.status_code == 413


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "aws.ec2"},
        {"detail-type": "EC2 Instance State-change Notification"},
        {"account": "missing"},
        {"region": "not-a-region"},
        {"time": "not-a-time"},
        {
            "detail": {
                "alarmName": "payments-latency",
                "state": {"value": "UNKNOWN", "reason": "bad"},
                "previousState": {"value": "OK"},
            }
        },
        {
            "detail": {
                "alarmName": "x" * 256,
                "state": {"value": "ALARM", "reason": "bad"},
                "previousState": {"value": "OK"},
            }
        },
        {"resources": ["arn:aws:cloudwatch:eu-west-2:123456789012:alarm:x"] * 21},
    ],
)
def test_eventbridge_schema_rejects_unsupported_or_oversized_values(changes) -> None:
    service, _ = _service()
    app = FastAPI()
    app.include_router(
        build_hosted_alert_ingestion_router(service, lambda: _machine())
    )
    path = f"/internal/v1/organizations/{ORG}/workspaces/{WORKSPACE}/integrations/aws/{INTEGRATION}/cloudwatch-alarms"
    response = TestClient(app).post(path, json=_envelope(**changes))
    assert response.status_code == 422


def test_equal_timestamp_uses_event_id_as_deterministic_ordering_tiebreaker() -> None:
    service, store = _service()
    later_id = _event(event_id="99999999-9999-4999-8999-999999999999")
    lower_id = replace(
        later_id,
        event_id="11111111-1111-4111-8111-111111111111",
        state=CloudWatchAlarmValue.OK,
        previous_state=CloudWatchAlarmValue.ALARM,
    )
    service.ingest(_machine(), ORG, WORKSPACE, INTEGRATION, later_id)
    ignored = service.ingest(_machine(), ORG, WORKSPACE, INTEGRATION, lower_id)
    assert ignored.outcome is AlertIngestionOutcome.IGNORED
    current = next(iter(store.states.values()))
    assert current.latest_event_id == later_id.event_id
    assert current.latest_state is CloudWatchAlarmValue.ALARM
