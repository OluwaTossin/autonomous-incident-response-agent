from __future__ import annotations

import json

import pytest

from app.config.settings import Settings
from app.runtime.config import alert_routes, validate_hosted_settings, worker_scopes


def _settings(**changes) -> Settings:
    values = {
        "AIRA_ENV": "production",
        "AIRA_DATABASE_URL": "postgresql+psycopg://aira_app:x@db/aira?sslmode=verify-full",
        "AIRA_SQS_QUEUE_URL": "https://sqs.eu-west-2.amazonaws.com/1/jobs",
        "AIRA_DOCUMENT_BUCKET": "documents",
        "AIRA_KNOWLEDGE_BUCKET": "knowledge",
        "AIRA_KMS_KEY_ARN": "arn:aws:kms:eu-west-2:1:key/example",
        "AIRA_OIDC_ISSUER": "https://cognito-idp.eu-west-2.amazonaws.com/pool",
        "AIRA_OIDC_CLIENT_ID": "client",
        "AIRA_AWS_TRUSTED_PRINCIPAL_ARN": "arn:aws:iam::1:role/aira/customer-read",
        "AIRA_AWS_SOURCE_ROLE_ARN": "arn:aws:iam::1:role/aira/customer-read",
        "AIRA_PUBLIC_ORIGIN": "https://app.example.com",
        "AIRA_CURSOR_SIGNING_KEY": "test-cursor-signing-key-at-least-32-bytes",
        "AIRA_WORKLOAD_SUBJECT": "arn:aws:iam::1:role/aira-worker",
    }
    values.update(changes)
    return Settings.model_validate(values)


def test_production_validation_requires_tls_and_no_endpoint_overrides() -> None:
    validate_hosted_settings(_settings())
    with pytest.raises(RuntimeError, match="TLS"):
        validate_hosted_settings(
            _settings(AIRA_DATABASE_URL="postgresql+psycopg://aira_app:x@db/aira")
        )
    with pytest.raises(RuntimeError, match="override"):
        validate_hosted_settings(
            _settings(AIRA_SQS_ENDPOINT_URL="http://localhost:4566")
        )


def test_worker_scopes_and_alert_routes_are_explicit_and_unique() -> None:
    route = {
        "organization_id": "00000000-0000-4000-8000-000000000001",
        "workspace_id": "00000000-0000-4000-8000-000000000002",
        "integration_id": "00000000-0000-4000-8000-000000000003",
        "aws_account_id": "123456789012",
        "regions": ["eu-west-2"],
    }
    settings = _settings(AIRA_WORKER_SCOPE_GRANTS=json.dumps([route]))
    assert len(worker_scopes(settings)) == 1
    assert alert_routes(settings)[0].aws_account_id == "123456789012"
    with pytest.raises(RuntimeError, match="unique"):
        alert_routes(
            _settings(AIRA_WORKER_SCOPE_GRANTS=json.dumps([route, route]))
        )


def test_hosted_runtime_rejects_missing_configuration() -> None:
    with pytest.raises(RuntimeError, match="AIRA_DATABASE_URL"):
        validate_hosted_settings(_settings(AIRA_DATABASE_URL=""))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AIRA_OIDC_JWKS_URL", "https://169.254.169.254/keys"),
        ("AIRA_OTEL_EXPORTER_OTLP_ENDPOINT", "https://127.0.0.1/traces"),
        ("OPENAI_API_BASE", "https://10.0.0.1/v1"),
    ],
)
def test_hosted_runtime_rejects_unsafe_outbound_destinations(
    name: str, value: str
) -> None:
    with pytest.raises(RuntimeError):
        validate_hosted_settings(_settings(**{name: value}))
