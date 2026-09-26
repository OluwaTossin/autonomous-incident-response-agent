"""Tenant-authorized AWS integration onboarding and verification."""

from __future__ import annotations

import json
import re
import secrets
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.auth.context import ActorContext
from app.authorization.permissions import Permission
from app.authorization.service import AuthorizationService, AuthorizedTenantContext
from app.domain.aws_integrations import (
    REQUIRED_AWS_CAPABILITIES,
    AwsCapabilityCheck,
    AwsIntegration,
    AwsIntegrationState,
    AwsVerificationError,
    AwsVerificationResult,
)
from app.domain.common import CorrelationContext, OrganizationScope, WorkspaceScope
from app.domain.events import AuditEvent
from app.domain.identifiers import (
    AuditEventId,
    CorrelationId,
    IntegrationId,
    OrganizationId,
    WorkspaceId,
)
from app.domain.usage import QuotaType, UsageType
from app.integrations.aws import AwsIntegrationCallError, AwsRoleAssumer
from app.persistence.postgres.aws_integrations import AwsIntegrationVersionConflict

_PRINCIPAL_RE = re.compile(r"^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}$")


class AwsIntegrationNotFound(LookupError):
    pass


class AwsIntegrationConflict(RuntimeError):
    pass


class AwsIntegrationConfigurationError(RuntimeError):
    pass


class AwsIntegrationRepository(Protocol):
    def add(self, integration: AwsIntegration) -> None: ...
    def get(self, integration_id: IntegrationId) -> AwsIntegration | None: ...
    def list(self, *, limit: int) -> Sequence[AwsIntegration]: ...
    def save(self, integration: AwsIntegration, *, expected_version: int) -> None: ...
    def count_active(self) -> int: ...


class AuditRepository(Protocol):
    def add(self, event: AuditEvent) -> None: ...


class AwsIntegrationUnitOfWork(Protocol):
    aws_integrations: AwsIntegrationRepository
    audit_events: AuditRepository
    usage: object
    def __enter__(self): ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...


class AwsIntegrationObserver(Protocol):
    def record(self, event: str, duration_ms: int, outcome: str) -> None: ...


class NoopAwsIntegrationObserver:
    def record(self, event: str, duration_ms: int, outcome: str) -> None:
        return None


@dataclass(frozen=True, slots=True)
class AwsTrustInstructions:
    trusted_principal_arn: str
    external_id: str
    trust_policy: dict
    permission_policy: dict


class HostedAwsIntegrationService:
    def __init__(
        self,
        authorization: AuthorizationService,
        uow_factory: Callable[[AuthorizedTenantContext], AwsIntegrationUnitOfWork],
        role_assumer: AwsRoleAssumer,
        *,
        trusted_principal_arn: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        external_id_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
        monotonic: Callable[[], float] = time.monotonic,
        observer: AwsIntegrationObserver = NoopAwsIntegrationObserver(),
        enforce_quotas: bool = False,
    ) -> None:
        principal = trusted_principal_arn.strip()
        if not _PRINCIPAL_RE.fullmatch(principal):
            raise AwsIntegrationConfigurationError(
                "AIRA trusted principal must be a configured standard-partition IAM role ARN"
            )
        self._authorization = authorization
        self._uow_factory = uow_factory
        self._role_assumer = role_assumer
        self._trusted_principal = principal
        self._clock = clock
        self._external_id_factory = external_id_factory
        self._monotonic = monotonic
        self._observer = observer
        self._enforce_quotas = enforce_quotas

    def create(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        display_name: str,
        aws_account_id: str,
        enabled_regions: tuple[str, ...],
        log_group_names: tuple[str, ...] = (),
    ) -> AwsIntegration:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INTEGRATION_MANAGE
        )
        now = self._clock()
        integration = AwsIntegration(
            id=IntegrationId.new(),
            scope=WorkspaceScope(organization_id, workspace_id),
            display_name=display_name,
            aws_account_id=aws_account_id,
            external_id=self._external_id_factory(),
            enabled_regions=enabled_regions,
            log_group_names=log_group_names,
            state=AwsIntegrationState.DRAFT,
            created_by=context.actor,
            created_at=now,
            updated_at=now,
        )
        started = self._monotonic()
        with self._uow_factory(context) as uow:
            if self._enforce_quotas:
                uow.usage.lock(QuotaType.ACTIVE_AWS_INTEGRATIONS)
                uow.usage.admit_current(
                    QuotaType.ACTIVE_AWS_INTEGRATIONS,
                    uow.aws_integrations.count_active(),
                    1,
                    at=now,
                )
            uow.aws_integrations.add(integration)
            uow.audit_events.add(
                _audit(context, integration, "aws_integration.created", now)
            )
            if self._enforce_quotas:
                uow.usage.record(
                    UsageType.AWS_INTEGRATION_COUNT,
                    1,
                    source="aws_integration",
                    source_reference=str(integration.id),
                    correlation=CorrelationContext(CorrelationId.new()),
                    actor=context.actor,
                    at=now,
                    resource_type="aws_integration",
                    resource_id=str(integration.id),
                )
        self._observe("aws_integration_created", started, "succeeded")
        return integration

    def list(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        *,
        limit: int = 50,
    ) -> tuple[AwsIntegration, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("AWS integration list limit must be between 1 and 100")
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INTEGRATION_READ
        )
        with self._uow_factory(context) as uow:
            return tuple(uow.aws_integrations.list(limit=limit))

    def get(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        integration_id: IntegrationId,
    ) -> AwsIntegration:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INTEGRATION_READ
        )
        with self._uow_factory(context) as uow:
            return self._required(uow, integration_id)

    def update(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        integration_id: IntegrationId,
        *,
        expected_version: int,
        display_name: str | None = None,
        aws_account_id: str | None = None,
        role_arn: str | None = None,
        enabled_regions: tuple[str, ...] | None = None,
        log_group_names: tuple[str, ...] | None = None,
    ) -> AwsIntegration:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INTEGRATION_MANAGE
        )
        now = self._clock()
        with self._uow_factory(context) as uow:
            current = self._required(uow, integration_id)
            self._expected(current.version, expected_version)
            updated = current.configure(
                display_name=display_name,
                aws_account_id=aws_account_id,
                role_arn=role_arn,
                enabled_regions=enabled_regions,
                log_group_names=log_group_names,
                at=now,
            )
            self._save(uow, updated, expected_version)
            uow.audit_events.add(
                _audit(
                    context,
                    updated,
                    "aws_integration.configuration_updated",
                    now,
                )
            )
            return updated

    def disable(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        integration_id: IntegrationId,
        *,
        expected_version: int,
    ) -> AwsIntegration:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INTEGRATION_MANAGE
        )
        now = self._clock()
        with self._uow_factory(context) as uow:
            current = self._required(uow, integration_id)
            self._expected(current.version, expected_version)
            disabled = current.disable(at=now)
            self._save(uow, disabled, expected_version)
            uow.audit_events.add(
                _audit(context, disabled, "aws_integration.disabled", now)
            )
            return disabled

    def trust_instructions(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        integration_id: IntegrationId,
    ) -> AwsTrustInstructions:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INTEGRATION_MANAGE
        )
        with self._uow_factory(context) as uow:
            integration = self._required(uow, integration_id)
        return AwsTrustInstructions(
            trusted_principal_arn=self._trusted_principal,
            external_id=integration.external_id,
            trust_policy=_trust_policy(
                self._trusted_principal, integration.external_id
            ),
            permission_policy=_permission_policy(),
        )

    def verify(
        self,
        actor: ActorContext,
        organization_id: OrganizationId,
        workspace_id: WorkspaceId,
        integration_id: IntegrationId,
        *,
        expected_version: int,
    ) -> AwsIntegration:
        context = self._authorize(
            actor, organization_id, workspace_id, Permission.INTEGRATION_MANAGE
        )
        with self._uow_factory(context) as uow:
            snapshot = self._required(uow, integration_id)
            self._expected(snapshot.version, expected_version)
            if snapshot.role_arn is None:
                raise AwsIntegrationConflict("Configure the customer role before verification")

        started = self._monotonic()
        result = self._run_verification(snapshot)
        now = self._clock()
        with self._uow_factory(context) as uow:
            current = self._required(uow, integration_id)
            self._expected(current.version, expected_version)
            verified = current.record_verification(result, at=now)
            self._save(uow, verified, expected_version)
            uow.audit_events.add(
                _audit(
                    context,
                    verified,
                    (
                        "aws_integration.verification_succeeded"
                        if result.succeeded
                        else "aws_integration.verification_failed"
                    ),
                    now,
                )
            )
        self._observe(
            "aws_integration_verification",
            started,
            "succeeded" if result.succeeded else "failed",
        )
        return verified

    def _run_verification(self, integration: AwsIntegration) -> AwsVerificationResult:
        now = self._clock()
        try:
            session = self._role_assumer.assume_role(
                role_arn=integration.role_arn or "",
                external_id=integration.external_id,
                session_name=f"aira-verify-{str(integration.id)[:12]}",
                duration_seconds=900,
            )
        except AwsIntegrationCallError as exc:
            return AwsVerificationResult(
                False, False, (), now, error_code=exc.code, summary=exc.summary
            )
        try:
            identity = session.caller_identity()
        except AwsIntegrationCallError as exc:
            return AwsVerificationResult(
                True, False, (), now, error_code=exc.code, summary=exc.summary
            )
        if identity.account_id != integration.aws_account_id or not _identity_matches_role(
            identity.arn, integration.aws_account_id, integration.role_arn or ""
        ):
            return AwsVerificationResult(
                True,
                False,
                (),
                now,
                error_code=AwsVerificationError.ACCOUNT_MISMATCH,
                summary="Assumed role identity does not match the configured AWS account and role",
            )

        checks: list[AwsCapabilityCheck] = []
        for region in integration.enabled_regions:
            for capability in REQUIRED_AWS_CAPABILITIES:
                try:
                    session.probe(capability, region)
                    checks.append(AwsCapabilityCheck(capability, region, True))
                except AwsIntegrationCallError as exc:
                    checks.append(
                        AwsCapabilityCheck(
                            capability,
                            region,
                            False,
                            error_code=exc.code,
                            summary=exc.summary,
                        )
                    )
        first_failure = next((check for check in checks if not check.passed), None)
        return AwsVerificationResult(
            True,
            True,
            tuple(checks),
            now,
            error_code=first_failure.error_code if first_failure else None,
            summary=first_failure.summary if first_failure else None,
        )

    def _authorize(self, actor, organization_id, workspace_id, permission):
        return self._authorization.authorize(
            actor, organization_id, permission, workspace_id=workspace_id
        )

    @staticmethod
    def _required(uow, integration_id):
        integration = uow.aws_integrations.get(integration_id)
        if integration is None:
            raise AwsIntegrationNotFound("AWS integration not found")
        return integration

    @staticmethod
    def _expected(actual: int, expected: int) -> None:
        if actual != expected:
            raise AwsIntegrationConflict("AWS integration version is stale")

    @staticmethod
    def _save(uow, integration, expected_version):
        try:
            uow.aws_integrations.save(integration, expected_version=expected_version)
        except AwsIntegrationVersionConflict as exc:
            raise AwsIntegrationConflict("AWS integration version is stale") from exc

    def _observe(self, event: str, started: float, outcome: str) -> None:
        self._observer.record(event, int((self._monotonic() - started) * 1000), outcome)


def _identity_matches_role(identity_arn: str, account_id: str, role_arn: str) -> bool:
    role_name = role_arn.rsplit("/", 1)[-1]
    prefix = f"arn:aws:sts::{account_id}:assumed-role/{role_name}/"
    return identity_arn.startswith(prefix)


def _trust_policy(principal: str, external_id: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": principal},
                "Action": "sts:AssumeRole",
                "Condition": {"StringEquals": {"sts:ExternalId": external_id}},
            }
        ],
    }


def _permission_policy() -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AiraCloudWatchRead",
                "Effect": "Allow",
                "Action": [
                    "cloudwatch:DescribeAlarms",
                    "cloudwatch:GetMetricData",
                    "cloudwatch:GetMetricStatistics",
                    "cloudwatch:ListMetrics",
                ],
                "Resource": "*",
            },
            {
                "Sid": "AiraCloudWatchLogsRead",
                "Effect": "Allow",
                "Action": [
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                    "logs:FilterLogEvents",
                    "logs:GetLogEvents",
                    "logs:GetQueryResults",
                    "logs:StartQuery",
                    "logs:StopQuery",
                ],
                "Resource": "*",
            },
        ],
    }


def _audit(
    context: AuthorizedTenantContext,
    integration: AwsIntegration,
    event_type: str,
    at: datetime,
) -> AuditEvent:
    verification = integration.verification
    details = {
        "provider": "aws",
        "aws_account_id": integration.aws_account_id,
        "regions": ",".join(integration.enabled_regions),
        "state": integration.state.value,
        "version": str(integration.version),
    }
    if verification is not None:
        details["verification_result"] = (
            "succeeded" if verification.succeeded else "failed"
        )
        if verification.error_code:
            details["error_code"] = verification.error_code.value
    return AuditEvent(
        id=AuditEventId.new(),
        organization_scope=OrganizationScope(context.organization_id),
        workspace_scope=WorkspaceScope(context.organization_id, context.workspace_id),
        event_type=event_type,
        target_type="aws_integration",
        target_id=str(integration.id),
        actor=context.actor,
        occurred_at=at,
        correlation=CorrelationContext(CorrelationId.new()),
        details=tuple(sorted(details.items())),
    )


def policy_json(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True)
