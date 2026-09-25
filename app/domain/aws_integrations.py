"""AWS integration onboarding domain without SDK or persistence dependencies."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from app.domain.common import (
    ActorReference,
    DomainInvariantError,
    WorkspaceScope,
    require_aware,
    validate_timestamps,
)
from app.domain.identifiers import IntegrationId

_ACCOUNT_RE = re.compile(r"^[0-9]{12}$")
_ROLE_ARN_RE = re.compile(
    r"^arn:aws:iam::(?P<account>[0-9]{12}):role/(?P<role>[A-Za-z0-9+=,.@_/-]{1,512})$"
)
_REGION_RE = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z0-9-]+-[0-9]+$")
_EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{32,200}$")


class AwsIntegrationState(StrEnum):
    DRAFT = "draft"
    PENDING_VERIFICATION = "pending_verification"
    READY = "ready"
    ERROR = "error"
    DISABLED = "disabled"


class AwsCapability(StrEnum):
    CLOUDWATCH_ALARMS_READ = "aws_cloudwatch_alarms_read"
    CLOUDWATCH_METRICS_READ = "aws_cloudwatch_metrics_read"
    CLOUDWATCH_LOGS_READ = "aws_cloudwatch_logs_read"


REQUIRED_AWS_CAPABILITIES = tuple(AwsCapability)


class AwsVerificationError(StrEnum):
    ROLE_NOT_ASSUMABLE = "role_not_assumable"
    EXTERNAL_ID_MISMATCH = "external_id_mismatch"
    ACCOUNT_MISMATCH = "account_mismatch"
    ACCESS_DENIED = "access_denied"
    REGION_UNAVAILABLE = "region_unavailable"
    CLOUDWATCH_PERMISSION_MISSING = "cloudwatch_permission_missing"
    METRICS_PERMISSION_MISSING = "metrics_permission_missing"
    LOGS_PERMISSION_MISSING = "logs_permission_missing"
    NETWORK_ERROR = "network_error"
    THROTTLED = "throttled"
    INVALID_CONFIGURATION = "invalid_configuration"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class AwsCapabilityCheck:
    capability: AwsCapability
    region: str
    passed: bool
    error_code: AwsVerificationError | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        _validate_region(self.region)
        if self.passed and (self.error_code is not None or self.summary is not None):
            raise DomainInvariantError("Passed capability checks cannot carry errors")
        if not self.passed and (self.error_code is None or not self.summary):
            raise DomainInvariantError("Failed capability checks require safe error details")
        if self.summary is not None and len(self.summary) > 500:
            raise DomainInvariantError("Capability summary exceeds 500 characters")


@dataclass(frozen=True, slots=True)
class AwsVerificationResult:
    assume_role_passed: bool
    account_identity_passed: bool
    checks: tuple[AwsCapabilityCheck, ...]
    verified_at: datetime
    error_code: AwsVerificationError | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.verified_at, "verified_at")
        if self.succeeded and (self.error_code is not None or self.summary is not None):
            raise DomainInvariantError("Successful verification cannot carry a top-level error")
        if not self.succeeded and (self.error_code is None or not self.summary):
            raise DomainInvariantError("Failed verification requires a safe error")
        if self.summary is not None and len(self.summary) > 500:
            raise DomainInvariantError("Verification summary exceeds 500 characters")

    @property
    def succeeded(self) -> bool:
        return (
            self.assume_role_passed
            and self.account_identity_passed
            and bool(self.checks)
            and all(check.passed for check in self.checks)
        )


@dataclass(frozen=True, slots=True)
class AwsIntegration:
    id: IntegrationId
    scope: WorkspaceScope
    display_name: str
    aws_account_id: str
    external_id: str
    enabled_regions: tuple[str, ...]
    state: AwsIntegrationState
    created_by: ActorReference
    created_at: datetime
    updated_at: datetime
    version: int = 1
    role_arn: str | None = None
    verification: AwsVerificationResult | None = None
    disabled_at: datetime | None = None

    def __post_init__(self) -> None:
        name = self.display_name.strip()
        if not name or len(name) > 200:
            raise DomainInvariantError("AWS integration display name is invalid")
        object.__setattr__(self, "display_name", name)
        _validate_account(self.aws_account_id)
        if not _EXTERNAL_ID_RE.fullmatch(self.external_id):
            raise DomainInvariantError("AWS integration ExternalId is invalid")
        regions = normalize_regions(self.enabled_regions)
        object.__setattr__(self, "enabled_regions", regions)
        if self.role_arn is not None:
            _validate_role_arn(self.role_arn, self.aws_account_id)
        if self.version < 1:
            raise DomainInvariantError("AWS integration version must be positive")
        validate_timestamps(self.created_at, self.updated_at)
        if self.disabled_at is not None:
            require_aware(self.disabled_at, "disabled_at")
        if self.state is AwsIntegrationState.DRAFT and self.role_arn is not None:
            raise DomainInvariantError("Draft AWS integrations cannot have a role ARN")
        if self.state not in {
            AwsIntegrationState.DRAFT,
            AwsIntegrationState.DISABLED,
        } and self.role_arn is None:
            raise DomainInvariantError("Configured AWS integrations require a role ARN")
        if self.state is AwsIntegrationState.READY:
            if self.verification is None or not self.verification.succeeded:
                raise DomainInvariantError("Ready AWS integrations require successful verification")
        if self.state is AwsIntegrationState.ERROR:
            if self.verification is None or self.verification.succeeded:
                raise DomainInvariantError("Errored AWS integrations require failed verification")
        if self.state is AwsIntegrationState.DISABLED and self.disabled_at is None:
            raise DomainInvariantError("Disabled AWS integrations require disabled_at")
        if self.state is not AwsIntegrationState.DISABLED and self.disabled_at is not None:
            raise DomainInvariantError("Only disabled AWS integrations carry disabled_at")

    def configure(
        self,
        *,
        display_name: str | None = None,
        aws_account_id: str | None = None,
        role_arn: str | None = None,
        enabled_regions: tuple[str, ...] | None = None,
        at: datetime,
    ) -> AwsIntegration:
        if self.state is AwsIntegrationState.DISABLED:
            raise DomainInvariantError("Disabled AWS integrations cannot be changed")
        account = aws_account_id or self.aws_account_id
        role = self.role_arn if role_arn is None else role_arn.strip()
        regions = (
            normalize_regions(enabled_regions)
            if enabled_regions is not None
            else self.enabled_regions
        )
        trust_changed = (
            account != self.aws_account_id
            or (role or None) != self.role_arn
            or regions != self.enabled_regions
        )
        return replace(
            self,
            display_name=display_name if display_name is not None else self.display_name,
            aws_account_id=account,
            role_arn=role or None,
            enabled_regions=regions,
            state=(
                (
                    AwsIntegrationState.PENDING_VERIFICATION
                    if role
                    else AwsIntegrationState.DRAFT
                )
                if trust_changed
                else self.state
            ),
            verification=None if trust_changed else self.verification,
            updated_at=at,
            version=self.version + 1,
        )

    def record_verification(
        self, result: AwsVerificationResult, *, at: datetime
    ) -> AwsIntegration:
        if self.state is AwsIntegrationState.DISABLED or self.role_arn is None:
            raise DomainInvariantError("AWS integration cannot be verified")
        return replace(
            self,
            state=(AwsIntegrationState.READY if result.succeeded else AwsIntegrationState.ERROR),
            verification=result,
            updated_at=at,
            version=self.version + 1,
        )

    def disable(self, *, at: datetime) -> AwsIntegration:
        if self.state is AwsIntegrationState.DISABLED:
            raise DomainInvariantError("AWS integration is already disabled")
        return replace(
            self,
            state=AwsIntegrationState.DISABLED,
            disabled_at=at,
            updated_at=at,
            version=self.version + 1,
        )


def normalize_regions(values: tuple[str, ...]) -> tuple[str, ...]:
    regions = tuple(sorted({value.strip().lower() for value in values if value.strip()}))
    if not regions or len(regions) > 20:
        raise DomainInvariantError("AWS integrations require 1 to 20 regions")
    for region in regions:
        _validate_region(region)
    return regions


def validate_role_arn(value: str, account_id: str) -> str:
    role_arn = value.strip()
    _validate_role_arn(role_arn, account_id)
    return role_arn


def _validate_account(value: str) -> None:
    if not _ACCOUNT_RE.fullmatch(value):
        raise DomainInvariantError("AWS account ID must contain exactly 12 digits")


def _validate_role_arn(value: str, account_id: str) -> None:
    match = _ROLE_ARN_RE.fullmatch(value)
    if match is None:
        raise DomainInvariantError("Role ARN must be a standard-partition IAM role ARN")
    if match.group("account") != account_id:
        raise DomainInvariantError("Role ARN account does not match AWS account ID")
    if "//" in match.group("role") or match.group("role").endswith("/"):
        raise DomainInvariantError("Role ARN path is invalid")


def _validate_region(value: str) -> None:
    if not _REGION_RE.fullmatch(value):
        raise DomainInvariantError("AWS region name is invalid")
