"""Hosted TRIAGE handler tests using the shared triage executor."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.application.jobs import (
    ClassifiedJobExecutionError,
    JobNotClaimable,
    TransientJobExecutionError,
)
from app.application.triage_jobs import (
    HostedTriageInputs,
    HostedTriageJobHandler,
    _require_current_claim,
)
from app.auth.context import trusted_system_actor
from app.domain.common import (
    ActorKind,
    ActorReference,
    CorrelationContext,
    WorkspaceScope,
)
from app.domain.identifiers import (
    CorrelationId,
    IncidentContextItemId,
    IncidentContextSnapshotId,
    IncidentId,
    IntegrationId,
    JobId,
    OrganizationId,
    TriageRunId,
    WorkspaceId,
)
from app.domain.incident_context import (
    CollectorDiagnostic,
    CollectorStatus,
    ContextCollectionStatus,
    ContextItemType,
    IncidentContextItem,
    IncidentContextSnapshot,
)
from app.domain.incidents import IncidentReference, TriageRun, TriageRunState
from app.domain.operations import Job, JobKind, JobState

NOW = datetime(2026, 9, 25, 13, 0, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000001")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000002")
INCIDENT = IncidentId("00000000-0000-4000-8000-000000000003")
RUN = TriageRunId("00000000-0000-4000-8000-000000000004")
JOB = JobId("00000000-0000-4000-8000-000000000005")


def _actor():
    return trusted_system_actor(
        system_name="aira-worker",
        workload_issuer="https://workload.example",
        workload_subject="worker-role",
    )


def _run() -> TriageRun:
    scope = WorkspaceScope(ORG, WORKSPACE)
    return TriageRun(
        id=RUN,
        scope=scope,
        incident=IncidentReference(INCIDENT, scope),
        state=TriageRunState.RUNNING,
        created_by=ActorReference(ActorKind.SYSTEM, system_name="aira-worker"),
        created_at=NOW,
        updated_at=NOW,
        started_at=NOW,
        correlation=CorrelationContext(
            CorrelationId.new(), incident_id=INCIDENT, triage_run_id=RUN, job_id=JOB
        ),
        state_version=2,
    )


def _job() -> Job:
    return Job(
        id=JOB,
        scope=WorkspaceScope(ORG, WORKSPACE),
        kind=JobKind.TRIAGE,
        subject_type="triage_run",
        subject_id=str(RUN),
        state=JobState.PENDING,
        created_by=ActorReference(ActorKind.SYSTEM, system_name="scheduler"),
        created_at=NOW,
        updated_at=NOW,
        correlation=CorrelationContext(
            CorrelationId.new(), incident_id=INCIDENT, triage_run_id=RUN, job_id=JOB
        ),
        idempotency_key="triage-request",
        payload_version=1,
        payload=(("incident_id", str(INCIDENT)), ("triage_run_id", str(RUN))),
        payload_hash="a" * 64,
        available_at=NOW,
    )


class Lifecycle:
    def load_inputs(self, actor, job):
        return HostedTriageInputs(
            _run(),
            {
                "alert_title": "Payments latency",
                "service_name": "payments-api",
                "environment": "production",
                "logs": "timeouts",
                "metric_summary": "p99 900ms",
                "time_of_occurrence": NOW.isoformat(),
            },
        )


class Knowledge:
    def __init__(self, *, missing=False):
        self.missing = missing

    def resolve_active(self, actor, organization_id, workspace_id):
        if self.missing:
            raise LookupError("missing")
        return type("Index", (), {"format_version": "aira-faiss-v1"})()


class Retriever:
    def retrieve(self, index, query, *, top_k):
        return []


def _pipeline(incident, *, retrieval_context):
    assert retrieval_context.top_k == 8
    return (
        {
            "incident_summary": "Payments are slow",
            "service_name": "payments-api",
            "severity": "HIGH",
            "likely_root_cause": "Dependency timeout",
            "recommended_actions": ["Inspect dependency health"],
            "escalate": True,
            "confidence": 0.8,
            "evidence": [
                {
                    "type": "runbook",
                    "source": "payments-runbook.md",
                    "reason": "Documents timeout recovery",
                    "origin": "tenant",
                    "document_id": "doc-1",
                    "document_version_id": "doc-version-1",
                    "knowledge_index_version_id": "index-1",
                    "chunk_index": 2,
                    "score": 0.91,
                }
            ],
            "conflicting_signals_summary": None,
            "timeline": ["T+0 alert fired"],
        },
        {"retrieval_hits": [], "llm_usage": {}},
    )


def test_triage_handler_uses_shared_executor_and_preserves_provenance() -> None:
    handler = HostedTriageJobHandler(
        Lifecycle(),
        Knowledge(),
        Retriever(),
        lambda actor, organization_id, workspace_id: 8,
        pipeline=_pipeline,
    )

    outcome = handler.handle(_actor(), _job(), cancellation_requested=lambda: False)

    assert outcome.result.result_type == "triage_run"
    assert outcome.result.result_id == str(RUN)
    completion = outcome.completion_payload
    assert completion.result.severity == "HIGH"
    assert completion.evidence[0].sequence == 0
    assert completion.evidence[0].origin == "tenant"
    assert completion.evidence[0].document_version_id == "doc-version-1"


def test_aws_context_is_persisted_before_shared_triage_and_becomes_evidence() -> None:
    snapshot_id = IncidentContextSnapshotId.new()
    item = IncidentContextItem(
        IncidentContextItemId.new(),
        snapshot_id,
        WorkspaceScope(ORG, WORKSPACE),
        ContextItemType.LOG,
        "/aws/lambda/payments:stream",
        NOW,
        {"timestamp": NOW.isoformat(), "message": "redacted timeout"},
        0,
    )
    snapshot = IncidentContextSnapshot(
        snapshot_id,
        WorkspaceScope(ORG, WORKSPACE),
        INCIDENT,
        RUN,
        IntegrationId.new(),
        "aws.cloudwatch",
        "eu-west-2",
        NOW,
        NOW,
        NOW,
        ContextCollectionStatus.COMPLETE,
        "cloudwatch-context-v1",
        (CollectorDiagnostic("logs", CollectorStatus.SUCCEEDED),),
        (item,),
    )

    class AwsLifecycle(Lifecycle):
        started = False
        persisted = False

        def load_inputs(self, actor, job):
            inputs = super().load_inputs(actor, job)
            return HostedTriageInputs(
                inputs.run,
                inputs.incident_payload,
                aws_binding=object(),  # the injected fake enricher owns this test boundary
            )

        def mark_enrichment_started(self, actor, job):
            self.started = True

        def persist_context(self, actor, job, value):
            assert value is snapshot
            self.persisted = True
            return value

    class Enricher:
        def collect(self, binding, *, cancellation_requested):
            assert not cancellation_requested()
            return snapshot

    def pipeline(incident, *, retrieval_context):
        assert "redacted timeout" in incident["logs"]
        assert incident["operational_context"]["snapshot_id"] == str(snapshot.id)
        return _pipeline(incident, retrieval_context=retrieval_context)

    lifecycle = AwsLifecycle()
    outcome = HostedTriageJobHandler(
        lifecycle,
        Knowledge(),
        Retriever(),
        lambda actor, organization_id, workspace_id: 8,
        pipeline=pipeline,
        context_enricher=Enricher(),
    ).handle(_actor(), _job(), cancellation_requested=lambda: False)

    assert lifecycle.started is True
    assert lifecycle.persisted is True
    context_evidence = outcome.completion_payload.evidence[-1]
    assert context_evidence.origin == "operational"
    assert context_evidence.type == "log"
    assert "redacted timeout" in context_evidence.reason


def test_expired_worker_claim_cannot_persist_context() -> None:
    claimed = _job().claim(
        worker_id="worker-a",
        claim_token=uuid4(),
        lease_expires_at=NOW + timedelta(minutes=1),
        at=NOW,
    )

    with pytest.raises(JobNotClaimable, match="stale"):
        _require_current_claim(claimed, claimed, NOW + timedelta(minutes=2))


def test_missing_active_index_is_permanent_configuration_failure() -> None:
    handler = HostedTriageJobHandler(
        Lifecycle(),
        Knowledge(missing=True),
        Retriever(),
        lambda actor, organization_id, workspace_id: 8,
        pipeline=_pipeline,
    )

    with pytest.raises(ClassifiedJobExecutionError) as raised:
        handler.handle(_actor(), _job(), cancellation_requested=lambda: False)

    assert raised.value.failure.category.value == "configuration"
    assert raised.value.failure.retryable is False


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("transient", TransientJobExecutionError),
        ("validation", ClassifiedJobExecutionError),
    ],
)
def test_error_shaped_pipeline_results_receive_deterministic_failure_classification(
    category, expected
) -> None:
    def failed_pipeline(incident, *, retrieval_context):
        return (
            {"error": "provider detail must not be persisted"},
            {
                "failure_code": "llm_provider_failed",
                "failure_category": category,
            },
        )

    handler = HostedTriageJobHandler(
        Lifecycle(),
        Knowledge(),
        Retriever(),
        lambda actor, organization_id, workspace_id: 8,
        pipeline=failed_pipeline,
    )

    with pytest.raises(expected):
        handler.handle(_actor(), _job(), cancellation_requested=lambda: False)
