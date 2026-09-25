"""Hosted AWS integration onboarding routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.application.aws_integrations import (
    AwsIntegrationConfigurationError,
    AwsIntegrationConflict,
    AwsIntegrationNotFound,
    AwsTrustInstructions,
    HostedAwsIntegrationService,
)
from app.auth.context import ActorContext
from app.authorization.service import AuthorizationDenied
from app.domain.aws_integrations import AwsIntegration
from app.domain.common import DomainInvariantError
from app.domain.identifiers import IntegrationId, OrganizationId, WorkspaceId
from app.persistence.postgres.aws_integrations import AwsIntegrationVersionConflict


class AwsIntegrationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=200)
    aws_account_id: str = Field(pattern=r"^[0-9]{12}$")
    enabled_regions: list[str] = Field(min_length=1, max_length=20)
    log_group_names: list[str] = Field(default_factory=list, max_length=20)


class AwsIntegrationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    aws_account_id: str | None = Field(default=None, pattern=r"^[0-9]{12}$")
    role_arn: str | None = Field(default=None, min_length=1, max_length=600)
    enabled_regions: list[str] | None = Field(default=None, min_length=1, max_length=20)
    log_group_names: list[str] | None = Field(default=None, max_length=20)


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class CapabilityCheckResponse(BaseModel):
    capability: str
    region: str
    passed: bool
    error_code: str | None
    summary: str | None


class VerificationResponse(BaseModel):
    assume_role_passed: bool
    account_identity_passed: bool
    succeeded: bool
    verified_at: datetime
    error_code: str | None
    summary: str | None
    checks: list[CapabilityCheckResponse]


class AwsIntegrationResponse(BaseModel):
    integration_id: str
    provider: str = "aws"
    display_name: str
    aws_account_id: str
    role_arn: str | None
    enabled_regions: list[str]
    log_group_names: list[str]
    state: str
    version: int
    verification: VerificationResponse | None
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None


class AwsIntegrationPageResponse(BaseModel):
    items: list[AwsIntegrationResponse]


class TrustInstructionsResponse(BaseModel):
    trusted_principal_arn: str
    external_id: str
    required_sts_action: str = "sts:AssumeRole"
    expected_role_arn_format: str
    trust_policy: dict
    permission_policy: dict


def build_hosted_aws_integration_router(
    service: HostedAwsIntegrationService,
    actor_dependency,
) -> APIRouter:
    router = APIRouter(
        prefix="/v3/organizations/{organization_id}/workspaces/{workspace_id}/integrations/aws",
        tags=["hosted-aws-integrations"],
    )

    @router.get("", response_model=AwsIntegrationPageResponse)
    def list_integrations(
        organization_id: str,
        workspace_id: str,
        actor: ActorContext = Depends(actor_dependency),
        limit: int = Query(50, ge=1, le=100),
    ) -> AwsIntegrationPageResponse:
        try:
            items = service.list(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                limit=limit,
            )
            return AwsIntegrationPageResponse(items=[_response(item) for item in items])
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post(
        "", response_model=AwsIntegrationResponse, status_code=status.HTTP_201_CREATED
    )
    def create_integration(
        organization_id: str,
        workspace_id: str,
        body: AwsIntegrationCreateRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> AwsIntegrationResponse:
        try:
            integration = service.create(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                display_name=body.display_name,
                aws_account_id=body.aws_account_id,
                enabled_regions=tuple(body.enabled_regions),
                log_group_names=tuple(body.log_group_names),
            )
            return _response(integration)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/{integration_id}", response_model=AwsIntegrationResponse)
    def get_integration(
        organization_id: str,
        workspace_id: str,
        integration_id: str,
        actor: ActorContext = Depends(actor_dependency),
    ) -> AwsIntegrationResponse:
        try:
            return _response(
                service.get(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    IntegrationId(integration_id),
                )
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.patch("/{integration_id}", response_model=AwsIntegrationResponse)
    def update_integration(
        organization_id: str,
        workspace_id: str,
        integration_id: str,
        body: AwsIntegrationUpdateRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> AwsIntegrationResponse:
        try:
            values = body.model_dump(exclude_unset=True)
            values.pop("expected_version")
            if "enabled_regions" in values:
                values["enabled_regions"] = tuple(values["enabled_regions"])
            if "log_group_names" in values:
                values["log_group_names"] = tuple(values["log_group_names"])
            return _response(
                service.update(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    IntegrationId(integration_id),
                    expected_version=body.expected_version,
                    **values,
                )
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get(
        "/{integration_id}/trust-instructions", response_model=TrustInstructionsResponse
    )
    def trust_instructions(
        organization_id: str,
        workspace_id: str,
        integration_id: str,
        actor: ActorContext = Depends(actor_dependency),
    ) -> TrustInstructionsResponse:
        try:
            instructions = service.trust_instructions(
                actor,
                OrganizationId(organization_id),
                WorkspaceId(workspace_id),
                IntegrationId(integration_id),
            )
            return _trust_response(instructions)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/{integration_id}/verify", response_model=AwsIntegrationResponse)
    def verify_integration(
        organization_id: str,
        workspace_id: str,
        integration_id: str,
        body: VersionRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> AwsIntegrationResponse:
        try:
            return _response(
                service.verify(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    IntegrationId(integration_id),
                    expected_version=body.expected_version,
                )
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/{integration_id}/disable", response_model=AwsIntegrationResponse)
    def disable_integration(
        organization_id: str,
        workspace_id: str,
        integration_id: str,
        body: VersionRequest,
        actor: ActorContext = Depends(actor_dependency),
    ) -> AwsIntegrationResponse:
        try:
            return _response(
                service.disable(
                    actor,
                    OrganizationId(organization_id),
                    WorkspaceId(workspace_id),
                    IntegrationId(integration_id),
                    expected_version=body.expected_version,
                )
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    return router


def _response(integration: AwsIntegration) -> AwsIntegrationResponse:
    verification = integration.verification
    return AwsIntegrationResponse(
        integration_id=str(integration.id),
        display_name=integration.display_name,
        aws_account_id=integration.aws_account_id,
        role_arn=integration.role_arn,
        enabled_regions=list(integration.enabled_regions),
        log_group_names=list(integration.log_group_names),
        state=integration.state.value,
        version=integration.version,
        verification=(
            VerificationResponse(
                assume_role_passed=verification.assume_role_passed,
                account_identity_passed=verification.account_identity_passed,
                succeeded=verification.succeeded,
                verified_at=verification.verified_at,
                error_code=(
                    verification.error_code.value if verification.error_code else None
                ),
                summary=verification.summary,
                checks=[
                    CapabilityCheckResponse(
                        capability=check.capability.value,
                        region=check.region,
                        passed=check.passed,
                        error_code=check.error_code.value if check.error_code else None,
                        summary=check.summary,
                    )
                    for check in verification.checks
                ],
            )
            if verification
            else None
        ),
        created_at=integration.created_at,
        updated_at=integration.updated_at,
        disabled_at=integration.disabled_at,
    )


def _trust_response(value: AwsTrustInstructions) -> TrustInstructionsResponse:
    return TrustInstructionsResponse(
        trusted_principal_arn=value.trusted_principal_arn,
        external_id=value.external_id,
        expected_role_arn_format="arn:aws:iam::<12-digit-account-id>:role/<role-path>",
        trust_policy=value.trust_policy,
        permission_policy=value.permission_policy,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AuthorizationDenied):
        return HTTPException(
            403, detail={"code": "forbidden", "message": "Access denied"}
        )
    if isinstance(exc, AwsIntegrationNotFound):
        return HTTPException(404, detail={"code": "not_found", "message": str(exc)})
    if isinstance(exc, (AwsIntegrationConflict, AwsIntegrationVersionConflict)):
        return HTTPException(409, detail={"code": "conflict", "message": str(exc)})
    if isinstance(exc, (ValueError, TypeError, DomainInvariantError)):
        return HTTPException(
            422, detail={"code": "invalid_request", "message": str(exc)}
        )
    if isinstance(exc, AwsIntegrationConfigurationError):
        return HTTPException(
            503,
            detail={
                "code": "unavailable",
                "message": "AWS onboarding is not configured",
            },
        )
    return HTTPException(
        500,
        detail={"code": "internal_error", "message": "Request could not be completed"},
    )
