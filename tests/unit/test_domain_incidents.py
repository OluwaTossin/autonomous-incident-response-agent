"""Incident, triage, evidence, feedback, and compatibility invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.common import (
    ActorKind,
    ActorReference,
    CorrelationContext,
    DomainInvariantError,
    InvalidStateTransition,
    WorkspaceScope,
)
from app.domain.identifiers import (
    CorrelationId,
    EvidenceId,
    FeedbackId,
    IncidentId,
    OrganizationId,
    TriageRunId,
    UserId,
    WorkspaceId,
)
from app.domain.incidents import (
    Evidence,
    Feedback,
    Incident,
    IncidentSource,
    IncidentState,
    TriageRun,
    TriageRunState,
)
from app.models.incident import IncidentPayload
from app.models.triage import TriageOutput

NOW = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=1)
DONE = NOW + timedelta(minutes=2)


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


def _scope(organization: int = 1, workspace: int = 2) -> WorkspaceScope:
    return WorkspaceScope(_id(OrganizationId, organization), _id(WorkspaceId, workspace))


def _actor() -> ActorReference:
    return ActorReference(ActorKind.HUMAN, actor_id=_id(UserId, 3))


def _incident(scope: WorkspaceScope | None = None) -> Incident:
    actual_scope = scope or _scope()
    incident_id = _id(IncidentId, 4)
    return Incident(
        id=incident_id,
        scope=actual_scope,
        payload=IncidentPayload.model_validate(
            {
                "alertTitle": "Checkout latency",
                "alert_title": "Checkout latency",
                "service_name": "checkout-api",
                "provider_event_id": "evt-1",
            }
        ),
        source=IncidentSource("manual", "api", NOW, external_id="evt-1"),
        state=IncidentState.OPEN,
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
        correlation=CorrelationContext(_id(CorrelationId, 5), incident_id=incident_id),
    )


def _queued_triage(incident: Incident | None = None) -> TriageRun:
    actual_incident = incident or _incident()
    run_id = _id(TriageRunId, 6)
    return TriageRun(
        id=run_id,
        scope=actual_incident.scope,
        incident=actual_incident.reference,
        state=TriageRunState.QUEUED,
        created_by=_actor(),
        created_at=NOW,
        updated_at=NOW,
        correlation=CorrelationContext(
            _id(CorrelationId, 7),
            incident_id=actual_incident.id,
            triage_run_id=run_id,
        ),
    )


def _result() -> TriageOutput:
    return TriageOutput(
        incident_summary="Checkout is slow",
        service_name="checkout-api",
        severity="HIGH",
        likely_root_cause="Worker saturation",
        recommended_actions=["Scale workers"],
        escalate=True,
        confidence=0.85,
        evidence=[
            {
                "type": "runbook",
                "source": "runbooks/checkout.md",
                "reason": "Relevant scaling procedure",
            }
        ],
        timeline=["T+0 alert"],
    )


def test_incident_preserves_legacy_payload_and_forward_only_lifecycle() -> None:
    incident = _incident()

    investigating = incident.transition(IncidentState.INVESTIGATING, at=LATER)
    resolved = investigating.transition(IncidentState.RESOLVED, at=DONE)
    closed = resolved.transition(IncidentState.CLOSED, at=DONE)

    assert incident.to_legacy_payload()["provider_event_id"] == "evt-1"
    assert closed.state is IncidentState.CLOSED
    with pytest.raises(InvalidStateTransition):
        closed.transition(IncidentState.INVESTIGATING, at=DONE)


def test_triage_run_lifecycle_and_legacy_result_contract() -> None:
    queued = _queued_triage()
    running = queued.start(at=LATER)
    succeeded = running.succeed(_result(), at=DONE)

    assert succeeded.state is TriageRunState.SUCCEEDED
    assert succeeded.legacy_triage_id == str(succeeded.id)
    legacy = succeeded.to_legacy_result()
    assert legacy["triage_id"] == str(succeeded.id)
    assert legacy["severity"] == "HIGH"
    assert legacy["evidence"][0]["source"] == "runbooks/checkout.md"
    with pytest.raises(InvalidStateTransition):
        succeeded.cancel(at=DONE)


def test_triage_failure_and_cancellation_are_terminal() -> None:
    failed = _queued_triage().start(at=LATER).fail("provider timeout", at=DONE)
    cancelled = _queued_triage().cancel(at=LATER)

    assert failed.error_message == "provider timeout"
    assert cancelled.started_at is None
    with pytest.raises(InvalidStateTransition):
        failed.start(at=DONE)
    with pytest.raises(InvalidStateTransition):
        cancelled.start(at=DONE)


def test_triage_rejects_cross_workspace_incident_reference() -> None:
    incident = _incident(_scope(1, 20))
    run_id = _id(TriageRunId, 6)

    with pytest.raises(DomainInvariantError, match="same workspace scope"):
        TriageRun(
            id=run_id,
            scope=_scope(1, 21),
            incident=incident.reference,
            state=TriageRunState.QUEUED,
            created_by=_actor(),
            created_at=NOW,
            updated_at=NOW,
            correlation=CorrelationContext(_id(CorrelationId, 7)),
        )


def test_evidence_and_feedback_require_triage_scope_and_actor_attribution() -> None:
    triage = _queued_triage()
    evidence = Evidence(
        id=_id(EvidenceId, 8),
        scope=triage.scope,
        triage_run=triage.reference,
        type="runbook",
        source="runbooks/checkout.md",
        reason="Relevant scaling procedure",
        created_at=NOW,
    )
    feedback = Feedback(
        id=_id(FeedbackId, 9),
        scope=triage.scope,
        triage_run=triage.reference,
        submitted_by=_actor(),
        created_at=NOW,
        diagnosis_correct=True,
        actions_useful=False,
        notes=" Needs another action. ",
    )

    assert evidence.to_triage_item().source == "runbooks/checkout.md"
    assert feedback.notes == "Needs another action."

    with pytest.raises(DomainInvariantError, match="same workspace scope"):
        Evidence(
            id=_id(EvidenceId, 10),
            scope=_scope(9, 9),
            triage_run=triage.reference,
            type="log",
            source="logs/a.log",
            reason="Error line",
            created_at=NOW,
        )
