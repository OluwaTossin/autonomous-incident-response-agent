"""Fail-closed production configuration validation for hosted processes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config.settings import Settings
from app.domain.common import WorkspaceScope
from app.domain.identifiers import OrganizationId, WorkspaceId


@dataclass(frozen=True, slots=True)
class AlertRoute:
    scope: WorkspaceScope
    integration_id: str
    aws_account_id: str
    regions: frozenset[str]


def validate_hosted_settings(settings: Settings, *, worker: bool = False) -> None:
    if settings.aira_env != "production":
        raise RuntimeError("Hosted runtime requires AIRA_ENV=production")
    required = {
        "AIRA_DATABASE_URL": settings.aira_database_url,
        "AIRA_SQS_QUEUE_URL": settings.aira_sqs_queue_url,
        "AIRA_DOCUMENT_BUCKET": settings.aira_document_bucket,
        "AIRA_KNOWLEDGE_BUCKET": settings.aira_knowledge_bucket,
        "AIRA_KMS_KEY_ARN": settings.aira_kms_key_arn,
        "AIRA_OIDC_ISSUER": settings.aira_oidc_issuer,
        "AIRA_OIDC_CLIENT_ID": settings.aira_oidc_client_id,
        "AIRA_AWS_TRUSTED_PRINCIPAL_ARN": settings.aira_aws_trusted_principal_arn,
        "AIRA_AWS_SOURCE_ROLE_ARN": settings.aira_aws_source_role_arn,
        "AIRA_PUBLIC_ORIGIN": settings.aira_public_origin,
    }
    if worker:
        required["AIRA_WORKER_SCOPE_GRANTS"] = settings.aira_worker_scope_grants
        required["AIRA_WORKLOAD_SUBJECT"] = settings.aira_workload_subject
    missing = sorted(name for name, value in required.items() if not value.strip())
    if missing:
        raise RuntimeError("Missing hosted configuration: " + ", ".join(missing))
    if not settings.aira_database_url.startswith(
        ("postgresql://", "postgresql+psycopg://")
    ):
        raise RuntimeError("AIRA_DATABASE_URL must be PostgreSQL")
    if "sslmode=" not in settings.aira_database_url:
        raise RuntimeError("AIRA_DATABASE_URL must explicitly require PostgreSQL TLS")
    for name, value in {
        "AIRA_PUBLIC_ORIGIN": settings.aira_public_origin,
        "AIRA_OIDC_ISSUER": settings.aira_oidc_issuer,
    }.items():
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.hostname == "localhost":
            raise RuntimeError(f"{name} must be a non-local HTTPS URL")
    if settings.aira_sqs_endpoint_url or settings.aira_sts_endpoint_url:
        raise RuntimeError("Hosted production cannot override AWS service endpoints")


def worker_scopes(settings: Settings) -> tuple[WorkspaceScope, ...]:
    validate_hosted_settings(settings, worker=True)
    try:
        values = json.loads(settings.aira_worker_scope_grants)
        parsed = tuple(
            WorkspaceScope(
                OrganizationId(item["organization_id"]),
                WorkspaceId(item["workspace_id"]),
            )
            for item in values
        )
        scopes = tuple(dict.fromkeys(parsed))
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("AIRA_WORKER_SCOPE_GRANTS must be a JSON scope list") from exc
    if not scopes:
        raise RuntimeError("Worker scope grants must be non-empty")
    return scopes


def alert_routes(settings: Settings) -> tuple[AlertRoute, ...]:
    validate_hosted_settings(settings, worker=True)
    try:
        values = json.loads(settings.aira_worker_scope_grants)
        routes = tuple(
            AlertRoute(
                WorkspaceScope(
                    OrganizationId(item["organization_id"]),
                    WorkspaceId(item["workspace_id"]),
                ),
                str(item["integration_id"]),
                str(item["aws_account_id"]),
                frozenset(str(region) for region in item["regions"]),
            )
            for item in values
        )
    except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Alert routes require integration_id, aws_account_id, and regions"
        ) from exc
    identities = {(route.aws_account_id, region) for route in routes for region in route.regions}
    if not routes or len(identities) != sum(len(route.regions) for route in routes):
        raise RuntimeError("Alert account/region routes must be non-empty and unique")
    return routes
