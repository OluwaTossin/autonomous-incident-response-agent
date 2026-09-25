"""Hosted TRIAGE job execution and atomic result lifecycle."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Protocol
from uuid import uuid4

from app.agent.graph import run_triage_with_audit
from app.application.incidents import (
    HostedIncidentUnitOfWorkFactory,
    IncidentLifecycleObserver,
    NoopIncidentLifecycleObserver,
    _audit,
)
from app.application.jobs import (
    ClassifiedJobExecutionError,
    JobNotClaimable,
    TransientJobExecutionError,
)
from app.application.triage import TriageExecution, execute_triage
from app.application.incident_context import (
    AwsIncidentContextBinding,
    ContextEnrichmentFailure,
    IncidentContextEnricher,
    project_context,
)
from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.domain.identifiers import (
    EvidenceId,
    IncidentId,
    OrganizationId,
    TriageRunId,
    WorkspaceId,
)
from app.domain.incident_context import (
    ContextCollectionStatus,
    ContextItemType,
    IncidentContextSnapshot,
)
from app.domain.incidents import Evidence, Incident, TriageRun, TriageRunState
from app.domain.operations import (
    Job,
    JobErrorCategory,
    JobFailure,
    JobKind,
    JobResultReference,
    JobState,
)
from app.knowledge.contracts import (
    PublishedKnowledgeIndexReference,
    RetrievalContext,
    Retriever,
)
from app.models.triage import TriageOutput
from app.worker.orchestration import JobHandlerOutcome

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HostedTriageInputs:
    run: TriageRun
    incident_payload: dict[str, object]
    incident: Incident | None = None
    aws_binding: AwsIncidentContextBinding | None = None
    context_snapshot: IncidentContextSnapshot | None = None


@dataclass(frozen=True, slots=True)
class TriageCompletion:
    result: TriageOutput
    evidence: tuple[Evidence, ...]
    duration_ms: int


class ActiveKnowledgeResolver(Protocol):
    def resolve_active(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
    ) -> PublishedKnowledgeIndexReference: ...


class ActionProposalGenerator(Protocol):
    def generate_for_completed_run(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        run_id: TriageRunId,
    ) -> tuple[object, ...]: ...


class HostedTriageLifecycle:
    """Coordinates Job and TriageRun state in the same PostgreSQL transaction."""

    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: HostedIncidentUnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        retry_base: timedelta = timedelta(seconds=30),
        retry_max: timedelta = timedelta(minutes=15),
        observer: IncidentLifecycleObserver = NoopIncidentLifecycleObserver(),
        proposal_generator: ActionProposalGenerator | None = None,
    ) -> None:
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._clock = clock
        self._retry_base = retry_base
        self._retry_max = retry_max
        self._observer = observer
        self._proposal_generator = proposal_generator

    def load_inputs(self, actor: ActorContext, job: Job) -> HostedTriageInputs:
        context = self._context(actor, job)
        incident_id, run_id = _payload_ids(job)
        with self._uow_factory(context) as uow:
            run = uow.triage_runs.get(run_id)
            incident = uow.incidents.get(incident_id)
            if run is None or incident is None or run.incident.id != incident.id:
                raise ClassifiedJobExecutionError(
                    JobFailure(
                        "triage_input_missing",
                        JobErrorCategory.VALIDATION,
                        False,
                        "Triage input is unavailable",
                    )
                )
            snapshot = uow.context_snapshots.get_for_run(run.id)
            binding = None
            if incident.source.provider == "aws.cloudwatch":
                receipt = uow.alert_receipts.get_for_triage_run(run.id)
                integration = (
                    uow.aws_integrations.get(receipt.integration_id)
                    if receipt is not None
                    else None
                )
                if receipt is None or integration is None:
                    raise ClassifiedJobExecutionError(
                        JobFailure(
                            "aws_context_binding_missing",
                            JobErrorCategory.CONFIGURATION,
                            False,
                            "AWS incident context binding is unavailable",
                        )
                    )
                binding = AwsIncidentContextBinding(incident, run, receipt, integration)
            return HostedTriageInputs(
                run,
                incident.to_legacy_payload(),
                incident,
                binding,
                snapshot,
            )

    def mark_enrichment_started(self, actor: ActorContext, claimed: Job) -> None:
        context = self._context(actor, claimed)
        _, run_id = _payload_ids(claimed)
        now = self._clock()
        with self._uow_factory(context) as uow:
            current_job = uow.jobs.get(claimed.id, for_update=True)
            run = uow.triage_runs.get(run_id)
            _require_current_claim(current_job, claimed, now)
            if run is None or run.state is not TriageRunState.RUNNING:
                raise JobNotClaimable("Triage enrichment state is unavailable")
            uow.audit_events.add(
                _audit(
                    context, run, "context_enrichment.started", now, job_id=claimed.id
                )
            )

    def persist_context(
        self,
        actor: ActorContext,
        claimed: Job,
        snapshot: IncidentContextSnapshot,
    ) -> IncidentContextSnapshot:
        context = self._context(actor, claimed)
        incident_id, run_id = _payload_ids(claimed)
        now = self._clock()
        with self._uow_factory(context) as uow:
            current_job = uow.jobs.get(claimed.id, for_update=True)
            run = uow.triage_runs.get(run_id)
            _require_current_claim(current_job, claimed, now)
            if run is None or run.state is not TriageRunState.RUNNING:
                raise JobNotClaimable("Triage context claim is stale")
            existing = uow.context_snapshots.get_for_run(run_id)
            if existing is not None:
                return existing
            if (
                snapshot.scope != run.scope
                or snapshot.triage_run_id != run_id
                or snapshot.incident_id != incident_id
            ):
                raise JobNotClaimable("Triage context scope is invalid")
            uow.context_snapshots.add(snapshot)
            event = (
                "context_enrichment.partial"
                if snapshot.status is ContextCollectionStatus.PARTIAL
                else "context_enrichment.completed"
            )
            uow.audit_events.add(_audit(context, run, event, now, job_id=claimed.id))
        self._observer.record(
            "context_enrichment_persisted",
            0,
            snapshot.status.value,
        )
        return snapshot

    def record_enrichment_failed(self, actor: ActorContext, claimed: Job) -> None:
        context = self._context(actor, claimed)
        _, run_id = _payload_ids(claimed)
        now = self._clock()
        with self._uow_factory(context) as uow:
            current_job = uow.jobs.get(claimed.id, for_update=True)
            run = uow.triage_runs.get(run_id)
            _require_current_claim(current_job, claimed, now)
            if run is None or run.state is not TriageRunState.RUNNING:
                raise JobNotClaimable("Triage enrichment state is unavailable")
            uow.audit_events.add(
                _audit(
                    context, run, "context_enrichment.failed", now, job_id=claimed.id
                )
            )
        self._observer.record("context_enrichment_failed", 0, "failed")

    def claim(
        self,
        actor: ActorContext,
        job: Job,
        *,
        worker_id: str,
        lease_duration: timedelta,
    ) -> Job:
        context = self._context(actor, job)
        _, run_id = _payload_ids(job)
        now = self._clock()
        with self._uow_factory(context) as uow:
            current_job = uow.jobs.get(job.id, for_update=True)
            run = uow.triage_runs.get(run_id, for_update=True)
            if current_job is None or run is None:
                raise JobNotClaimable("Triage job is unavailable")
            try:
                claimed = current_job.claim(
                    worker_id=worker_id,
                    claim_token=uuid4(),
                    lease_expires_at=now + lease_duration,
                    at=now,
                )
                if run.state is TriageRunState.QUEUED:
                    updated_run = run.start(at=now)
                    uow.triage_runs.save(
                        updated_run, expected_version=run.state_version
                    )
                    uow.audit_events.add(
                        _audit(
                            context,
                            updated_run,
                            "triage.started",
                            now,
                            job_id=claimed.id,
                        )
                    )
                elif run.state is not TriageRunState.RUNNING:
                    raise ValueError("Triage run is not executable")
                uow.jobs.save(claimed, expected_version=current_job.state_version)
            except Exception as exc:
                raise JobNotClaimable("Triage job is not claimable") from exc
        self._observer.record("triage_started", 0, "succeeded")
        return claimed

    def complete(
        self, actor: ActorContext, claimed: Job, outcome: JobHandlerOutcome
    ) -> Job:
        if not isinstance(outcome.completion_payload, TriageCompletion):
            raise ValueError("TRIAGE completion payload is invalid")
        context = self._context(actor, claimed)
        _, run_id = _payload_ids(claimed)
        now = self._clock()
        with self._uow_factory(context) as uow:
            current_job = uow.jobs.get(claimed.id, for_update=True)
            run = uow.triage_runs.get(run_id, for_update=True)
            if current_job is None or run is None or claimed.claim_token is None:
                raise JobNotClaimable("Triage completion state is unavailable")
            try:
                completed_job = current_job.succeed(
                    claimed.claim_token, outcome.result, at=now
                )
                if run.state is not TriageRunState.RUNNING:
                    raise ValueError("Triage run is not running")
                completed_run = run.succeed(outcome.completion_payload.result, at=now)
                uow.evidence.replace_for_run(
                    run.id, outcome.completion_payload.evidence
                )
                uow.triage_runs.save(completed_run, expected_version=run.state_version)
                uow.jobs.save(completed_job, expected_version=current_job.state_version)
            except Exception as exc:
                raise JobNotClaimable("Triage completion claim is stale") from exc
            uow.audit_events.add(
                _audit(
                    context,
                    completed_run,
                    "triage.succeeded",
                    now,
                    job_id=completed_job.id,
                )
            )
        self._observer.record(
            "triage_succeeded",
            outcome.completion_payload.duration_ms,
            "succeeded",
        )
        if self._proposal_generator is not None:
            try:
                self._proposal_generator.generate_for_completed_run(
                    actor,
                    completed_run.scope.organization_id,
                    completed_run.scope.workspace_id,
                    completed_run.id,
                )
            except Exception:
                logger.exception(
                    "Action proposal generation failed after triage completion"
                )
                self._observer.record("action_proposal_generation", 0, "failed")
            else:
                self._observer.record("action_proposal_generation", 0, "succeeded")
        return completed_job

    def fail(self, actor: ActorContext, claimed: Job, failure: JobFailure) -> Job:
        context = self._context(actor, claimed)
        _, run_id = _payload_ids(claimed)
        now = self._clock()
        with self._uow_factory(context) as uow:
            current_job = uow.jobs.get(claimed.id, for_update=True)
            run = uow.triage_runs.get(run_id, for_update=True)
            if current_job is None or run is None or claimed.claim_token is None:
                raise JobNotClaimable("Triage failure state is unavailable")
            try:
                if current_job.cancellation_requested_at is not None:
                    updated_job = current_job.acknowledge_cancellation(
                        claimed.claim_token, at=now
                    )
                else:
                    updated_job = current_job.fail_attempt(
                        claimed.claim_token,
                        failure,
                        next_available_at=now
                        + self._backoff(current_job.attempt_count),
                        at=now,
                    )
                if updated_job.state is JobState.PENDING:
                    updated_run = run.retry(at=now)
                    uow.dispatches.add(updated_job, at=now)
                    event_type = "triage.retry_scheduled"
                elif updated_job.state is JobState.CANCELLED:
                    updated_run = run.cancel(at=now)
                    event_type = "triage.cancelled"
                else:
                    updated_run = run.fail(
                        failure.summary,
                        code=failure.code,
                        category=failure.category.value,
                        retryable=False,
                        at=now,
                    )
                    event_type = "triage.failed"
                uow.triage_runs.save(updated_run, expected_version=run.state_version)
                uow.jobs.save(updated_job, expected_version=current_job.state_version)
            except Exception as exc:
                raise JobNotClaimable("Triage failure claim is stale") from exc
            uow.audit_events.add(
                _audit(context, updated_run, event_type, now, job_id=updated_job.id)
            )
        metric = {
            JobState.PENDING: "triage_retried",
            JobState.CANCELLED: "triage_cancelled",
            JobState.FAILED: "triage_failed",
        }[updated_job.state]
        self._observer.record(metric, 0, "succeeded")
        return updated_job

    def reconcile_scope(
        self,
        actor: ActorContext,
        organization_id,
        workspace_id,
        *,
        limit: int = 100,
    ) -> int:
        """Repair recoverable Job/TriageRun drift after lease recovery or a crash."""
        if not 1 <= limit <= 500:
            raise ValueError("Reconciliation limit must be between 1 and 500")
        context = self._authorization.authorize(
            actor,
            organization_id,
            Permission.JOB_EXECUTE,
            workspace_id=workspace_id,
        )
        now = self._clock()
        reconciled = 0
        with self._uow_factory(context) as uow:
            for run, job in uow.triage_runs.list_inconsistent_jobs(limit=limit):
                if job.state is JobState.PENDING:
                    updated = run.retry(at=now)
                    event = "triage.retry_reconciled"
                elif job.state is JobState.CANCELLED:
                    updated = run.cancel(at=now)
                    event = "triage.cancelled"
                elif job.state is JobState.FAILED and job.last_error is not None:
                    updated = run.fail(
                        job.last_error.summary,
                        code=job.last_error.code,
                        category=job.last_error.category.value,
                        retryable=False,
                        at=now,
                    )
                    event = "triage.failed"
                else:
                    continue
                uow.triage_runs.save(updated, expected_version=run.state_version)
                uow.audit_events.add(
                    _audit(context, updated, event, now, job_id=job.id)
                )
                reconciled += 1
        return reconciled

    def acknowledge_cancellation(self, actor: ActorContext, claimed: Job) -> Job:
        context = self._context(actor, claimed)
        _, run_id = _payload_ids(claimed)
        now = self._clock()
        with self._uow_factory(context) as uow:
            current_job = uow.jobs.get(claimed.id, for_update=True)
            run = uow.triage_runs.get(run_id, for_update=True)
            if current_job is None or run is None or claimed.claim_token is None:
                raise JobNotClaimable("Triage cancellation state is unavailable")
            try:
                updated_job = current_job.acknowledge_cancellation(
                    claimed.claim_token, at=now
                )
                updated_run = run.cancel(at=now)
                uow.triage_runs.save(updated_run, expected_version=run.state_version)
                uow.jobs.save(updated_job, expected_version=current_job.state_version)
            except Exception as exc:
                raise JobNotClaimable("Triage cancellation claim is stale") from exc
            uow.audit_events.add(
                _audit(
                    context,
                    updated_run,
                    "triage.cancelled",
                    now,
                    job_id=updated_job.id,
                )
            )
        self._observer.record("triage_cancelled", 0, "succeeded")
        return updated_job

    def _context(self, actor: ActorContext, job: Job) -> AuthorizedTenantContext:
        if job.kind is not JobKind.TRIAGE:
            raise ValueError("TRIAGE lifecycle received another job kind")
        return self._authorization.authorize(
            actor,
            job.scope.organization_id,
            Permission.JOB_EXECUTE,
            workspace_id=job.scope.workspace_id,
        )

    def _backoff(self, attempt_count: int) -> timedelta:
        return min(
            self._retry_base * (2 ** max(0, attempt_count - 1)),
            self._retry_max,
        )


class HostedTriageJobHandler:
    def __init__(
        self,
        lifecycle: HostedTriageLifecycle,
        knowledge: ActiveKnowledgeResolver,
        retriever: Retriever,
        top_k: Callable[[ActorContext, OrganizationId, WorkspaceId], int],
        *,
        pipeline: Callable = run_triage_with_audit,
        context_enricher: IncidentContextEnricher | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._knowledge = knowledge
        self._retriever = retriever
        self._top_k = top_k
        self._pipeline = pipeline
        self._context_enricher = context_enricher

    def handle(
        self,
        actor: ActorContext,
        job: Job,
        *,
        cancellation_requested: Callable[[], bool],
    ) -> JobHandlerOutcome:
        if job.kind is not JobKind.TRIAGE:
            raise ValueError("TRIAGE handler received another job kind")
        if cancellation_requested():
            from app.application.jobs import JobCancellationRequested

            raise JobCancellationRequested("Job cancellation was requested")
        inputs = self._lifecycle.load_inputs(actor, job)
        snapshot = inputs.context_snapshot
        if inputs.aws_binding is not None:
            if self._context_enricher is None:
                raise ClassifiedJobExecutionError(
                    JobFailure(
                        "context_enricher_unavailable",
                        JobErrorCategory.CONFIGURATION,
                        False,
                        "AWS incident context enrichment is unavailable",
                    )
                )
            if snapshot is None:
                self._lifecycle.mark_enrichment_started(actor, job)
                try:
                    collected = self._context_enricher.collect(
                        inputs.aws_binding,
                        cancellation_requested=cancellation_requested,
                    )
                except ContextEnrichmentFailure as exc:
                    self._lifecycle.record_enrichment_failed(actor, job)
                    if exc.retryable:
                        raise TransientJobExecutionError(exc.summary) from exc
                    raise ClassifiedJobExecutionError(
                        JobFailure(exc.code, exc.category, False, exc.summary)
                    ) from exc
                if cancellation_requested():
                    from app.application.jobs import JobCancellationRequested

                    raise JobCancellationRequested("Job cancellation was requested")
                snapshot = self._lifecycle.persist_context(actor, job, collected)
        incident_payload = (
            project_context(inputs.incident_payload, snapshot)
            if snapshot is not None
            else inputs.incident_payload
        )
        try:
            index = self._knowledge.resolve_active(
                actor, job.scope.organization_id, job.scope.workspace_id
            )
        except LookupError as exc:
            raise ClassifiedJobExecutionError(
                JobFailure(
                    "active_knowledge_unavailable",
                    JobErrorCategory.CONFIGURATION,
                    False,
                    "No active knowledge index is available",
                )
            ) from exc
        top_k = self._top_k(actor, job.scope.organization_id, job.scope.workspace_id)
        retrieval = RetrievalContext(index, self._retriever, top_k)
        execution = execute_triage(
            incident_payload,
            pipeline=partial(self._pipeline, retrieval_context=retrieval),
            id_factory=lambda: str(inputs.run.id),
        )
        _raise_execution_failure(execution)
        completion = _validated_completion(inputs.run, execution, snapshot=snapshot)
        if cancellation_requested():
            from app.application.jobs import JobCancellationRequested

            raise JobCancellationRequested("Job cancellation was requested")
        return JobHandlerOutcome(
            JobResultReference(
                "triage_run",
                str(inputs.run.id),
                (("duration_ms", str(execution.duration_ms)),),
            ),
            completion,
        )


def _payload_ids(job: Job) -> tuple[IncidentId, TriageRunId]:
    if job.kind is not JobKind.TRIAGE or job.payload_version != 1:
        raise ValueError("Unsupported TRIAGE job payload")
    payload = dict(job.payload)
    incident_id = IncidentId(payload["incident_id"])
    run_id = TriageRunId(payload["triage_run_id"])
    if job.subject_type != "triage_run" or job.subject_id != str(run_id):
        raise ValueError("TRIAGE job subject does not match its payload")
    return incident_id, run_id


def _validated_completion(
    run: TriageRun,
    execution: TriageExecution,
    *,
    snapshot: IncidentContextSnapshot | None = None,
) -> TriageCompletion:
    if execution.triage_id != str(run.id):
        raise ValueError("Triage identifier does not match the durable run")
    raw = dict(execution.result)
    raw.pop("triage_id", None)
    result = TriageOutput.model_validate(raw)
    evidence: list[Evidence] = []
    for sequence, item in enumerate(result.evidence):
        if len(item.source) > 1000 or len(item.reason) > 2000:
            raise ValueError("Hosted evidence exceeds persistence limits")
        evidence.append(
            Evidence(
                id=EvidenceId.new(),
                scope=run.scope,
                triage_run=run.reference,
                type=item.type,
                source=item.source,
                reason=item.reason,
                created_at=datetime.now(UTC),
                sequence=sequence,
                origin=item.origin,
                document_id=item.document_id,
                document_version_id=item.document_version_id,
                knowledge_index_version_id=item.knowledge_index_version_id,
                chunk_index=item.chunk_index,
                score=item.score,
            )
        )
    if snapshot is not None:
        for item in snapshot.items:
            evidence.append(
                Evidence(
                    id=EvidenceId.new(),
                    scope=run.scope,
                    triage_run=run.reference,
                    type={
                        ContextItemType.ALARM: "alert",
                        ContextItemType.METRIC: "metric",
                        ContextItemType.LOG: "log",
                    }[item.type],
                    source=item.source,
                    reason=_context_evidence_reason(item),
                    created_at=datetime.now(UTC),
                    sequence=len(evidence),
                    origin="operational",
                )
            )
    return TriageCompletion(result, tuple(evidence), execution.duration_ms)


def _require_current_claim(current: Job | None, claimed: Job, now: datetime) -> None:
    if (
        current is None
        or current.state is not JobState.RUNNING
        or current.claim_token is None
        or current.claim_token != claimed.claim_token
        or current.lease_expires_at is None
        or current.lease_expires_at <= now
    ):
        raise JobNotClaimable("Triage context claim is stale")


def _context_evidence_reason(item) -> str:
    if item.type is ContextItemType.LOG:
        message = str(item.content.get("message", ""))[:1800]
        return f"Redacted CloudWatch log event collected for this triage run: {message}"
    if item.type is ContextItemType.METRIC:
        name = str(item.content.get("metric_name") or "alarm metric")
        return (
            f"Bounded CloudWatch metric context collected for this triage run: {name}"
        )
    return "Persisted CloudWatch alarm identity and state for this triage run"


def _raise_execution_failure(execution: TriageExecution) -> None:
    if not execution.result.get("error"):
        return
    category_value = str(execution.metadata.get("failure_category") or "internal")
    code = str(execution.metadata.get("failure_code") or "triage_execution_failed")
    if category_value == JobErrorCategory.TRANSIENT.value:
        raise TransientJobExecutionError("Triage dependency is temporarily unavailable")
    try:
        category = JobErrorCategory(category_value)
    except ValueError:
        category = JobErrorCategory.INTERNAL
    summary = {
        JobErrorCategory.CONFIGURATION: "Triage provider configuration is unavailable",
        JobErrorCategory.VALIDATION: "Triage result validation failed",
        JobErrorCategory.AUTHORIZATION: "Triage dependency authorization failed",
        JobErrorCategory.INTERNAL: "Triage execution failed",
    }.get(category, "Triage execution failed")
    raise ClassifiedJobExecutionError(JobFailure(code[:120], category, False, summary))
