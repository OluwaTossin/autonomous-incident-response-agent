"""AWS integration onboarding domain, application, and API tests."""

from __future__ import annotations

from datetime import UTC, datetime
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.hosted_aws_integrations import build_hosted_aws_integration_router
from app.application.aws_integrations import (
    AwsIntegrationConflict,
    HostedAwsIntegrationService,
)
from app.auth.context import ActorContext, AuthenticationMethod
from app.authorization.service import (
    AuthorizationService,
    HumanAuthorizationFacts,
)
from app.domain.aws_integrations import (
    AwsCapability,
    AwsIntegrationState,
    AwsVerificationError,
)
from app.domain.common import ActorKind, ActorReference, DomainInvariantError
from app.domain.identifiers import (
    MembershipId,
    OrganizationId,
    UserId,
    WorkspaceId,
)
from app.domain.tenancy import MembershipRole, WorkspaceAccessMode
from app.integrations.aws import (
    AwsCallerIdentity,
    AwsIntegrationCallError,
)
from app.persistence.postgres.aws_integrations import AwsIntegrationVersionConflict

NOW = datetime(2026, 9, 25, 16, 0, tzinfo=UTC)
ORG = OrganizationId("00000000-0000-4000-8000-000000000501")
WORKSPACE = WorkspaceId("00000000-0000-4000-8000-000000000502")
PRINCIPAL = "arn:aws:iam::111122223333:role/aira-hosted-api"
ROLE = "arn:aws:iam::123456789012:role/aira-read"


def _actor() -> ActorContext:
    return ActorContext(
        ActorReference(
            ActorKind.HUMAN,
            actor_id=UserId("00000000-0000-4000-8000-000000000503"),
        ),
        AuthenticationMethod.OIDC,
        issuer="https://issuer.example",
        external_subject="admin",
    )


class Facts:
    def __init__(self, role=MembershipRole.ADMIN):
        self.role = role

    def human_facts(self, actor, organization_id, workspace_id):
        if organization_id != ORG or workspace_id != WORKSPACE:
            return None
        return HumanAuthorizationFacts(
            MembershipId("00000000-0000-4000-8000-000000000504"),
            self.role,
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
    def is_active(self, organization_id, workspace_id):
        return organization_id == ORG and workspace_id == WORKSPACE


class Store:
    def __init__(self):
        self.integrations = {}
        self.audits = []


class Integrations:
    def __init__(self, store):
        self.store = store

    def add(self, integration):
        self.store.integrations[integration.id] = integration

    def get(self, integration_id):
        return self.store.integrations.get(integration_id)

    def list(self, *, limit):
        return sorted(
            self.store.integrations.values(),
            key=lambda item: (item.created_at, str(item.id)),
            reverse=True,
        )[:limit]

    def save(self, integration, *, expected_version):
        if self.store.integrations[integration.id].version != expected_version:
            raise AwsIntegrationVersionConflict("stale")
        self.store.integrations[integration.id] = integration


class Audits:
    def __init__(self, store):
        self.store = store

    def add(self, event):
        self.store.audits.append(event)


class Uow:
    def __init__(self, store):
        self.aws_integrations = Integrations(store)
        self.audit_events = Audits(store)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return None


class Session:
    def __init__(self, *, account="123456789012", failures=None):
        self.account = account
        self.failures = failures or {}
        self.probes = []

    def caller_identity(self):
        return AwsCallerIdentity(
            self.account,
            f"arn:aws:sts::{self.account}:assumed-role/aira-read/aira-verify",
        )

    def probe(self, capability, region):
        self.probes.append((capability, region))
        if capability in self.failures:
            raise self.failures[capability]


class Assumer:
    def __init__(self, session=None, error=None, callback=None):
        self.session = session or Session()
        self.error = error
        self.callback = callback
        self.calls = []

    def assume_role(self, **values):
        self.calls.append(values)
        if self.callback:
            self.callback()
        if self.error:
            raise self.error
        return self.session


def _service(*, role=MembershipRole.ADMIN, assumer=None):
    store = Store()
    service = HostedAwsIntegrationService(
        AuthorizationService(Facts(role), Resources()),
        lambda context: Uow(store),
        assumer or Assumer(),
        trusted_principal_arn=PRINCIPAL,
        clock=lambda: NOW,
        external_id_factory=lambda: "x" * 43,
        monotonic=lambda: 1.0,
    )
    return service, store


def _create(service):
    return service.create(
        _actor(),
        ORG,
        WORKSPACE,
        display_name="Production AWS",
        aws_account_id="123456789012",
        enabled_regions=("eu-west-2", "us-east-1", "eu-west-2"),
    )


def _configured(service):
    created = _create(service)
    return service.update(
        _actor(), ORG, WORKSPACE, created.id, expected_version=1, role_arn=ROLE
    )


def test_create_generates_external_id_and_normalizes_regions() -> None:
    service, store = _service()
    integration = _create(service)

    assert integration.state is AwsIntegrationState.DRAFT
    assert integration.external_id == "x" * 43
    assert integration.enabled_regions == ("eu-west-2", "us-east-1")
    assert store.audits[0].event_type == "aws_integration.created"


@pytest.mark.parametrize(
    "account,role",
    [
        ("123", None),
        ("123456789012", "arn:aws:iam::999999999999:role/aira-read"),
        ("123456789012", "arn:aws:iam::123456789012:user/not-a-role"),
        ("123456789012", "arn:aws-us-gov:iam::123456789012:role/aira"),
    ],
)
def test_account_and_role_validation_fail_closed(account, role) -> None:
    service, _ = _service()
    if role is None:
        with pytest.raises(DomainInvariantError):
            service.create(
                _actor(), ORG, WORKSPACE, display_name="AWS", aws_account_id=account,
                enabled_regions=("eu-west-2",),
            )
    else:
        created = _create(service)
        with pytest.raises(DomainInvariantError):
            service.update(
                _actor(), ORG, WORKSPACE, created.id,
                expected_version=created.version, role_arn=role,
            )


def test_successful_verification_requires_identity_and_all_capabilities() -> None:
    session = Session()
    assumer = Assumer(session)
    service, store = _service(assumer=assumer)
    configured = _configured(service)

    ready = service.verify(
        _actor(), ORG, WORKSPACE, configured.id, expected_version=configured.version
    )

    assert ready.state is AwsIntegrationState.READY
    assert ready.verification and ready.verification.succeeded
    assert len(session.probes) == 6
    assert assumer.calls[0]["external_id"] == "x" * 43
    assert assumer.calls[0]["duration_seconds"] == 900
    assert store.audits[-1].event_type == "aws_integration.verification_succeeded"


def test_capability_failure_is_safe_and_prevents_ready() -> None:
    error = AwsIntegrationCallError(
        AwsVerificationError.LOGS_PERMISSION_MISSING,
        "logs:DescribeLogGroups is not permitted",
    )
    service, _ = _service(
        assumer=Assumer(Session(failures={AwsCapability.CLOUDWATCH_LOGS_READ: error}))
    )
    configured = _configured(service)

    failed = service.verify(
        _actor(), ORG, WORKSPACE, configured.id, expected_version=configured.version
    )

    assert failed.state is AwsIntegrationState.ERROR
    assert failed.verification
    assert failed.verification.error_code is AwsVerificationError.LOGS_PERMISSION_MISSING
    assert "credentials" not in failed.verification.summary.lower()


def test_configuration_change_invalidates_ready_and_stale_verifier_loses() -> None:
    service, store = _service()
    configured = _configured(service)
    ready = service.verify(
        _actor(), ORG, WORKSPACE, configured.id, expected_version=configured.version
    )
    changed = service.update(
        _actor(), ORG, WORKSPACE, ready.id, expected_version=ready.version,
        enabled_regions=("eu-central-1",),
    )
    assert changed.state is AwsIntegrationState.PENDING_VERIFICATION
    assert changed.verification is None

    def mutate_during_call():
        current = store.integrations[changed.id]
        store.integrations[changed.id] = current.configure(
            enabled_regions=("ap-southeast-2",), at=NOW
        )

    stale_service = HostedAwsIntegrationService(
        service._authorization,
        lambda context: Uow(store),
        Assumer(callback=mutate_during_call),
        trusted_principal_arn=PRINCIPAL,
        clock=lambda: NOW,
        external_id_factory=lambda: "x" * 43,
        monotonic=lambda: 1.0,
    )
    with pytest.raises(AwsIntegrationConflict, match="stale"):
        stale_service.verify(
            _actor(), ORG, WORKSPACE, changed.id, expected_version=changed.version
        )
    assert store.integrations[changed.id].state is AwsIntegrationState.PENDING_VERIFICATION


def test_account_mismatch_and_assume_role_failure_are_persisted_safely() -> None:
    service, _ = _service(assumer=Assumer(Session(account="999999999999")))
    configured = _configured(service)
    mismatch = service.verify(
        _actor(), ORG, WORKSPACE, configured.id, expected_version=configured.version
    )
    assert mismatch.verification
    assert mismatch.verification.error_code is AwsVerificationError.ACCOUNT_MISMATCH

    denied_service, _ = _service(
        assumer=Assumer(
            error=AwsIntegrationCallError(
                AwsVerificationError.ROLE_NOT_ASSUMABLE,
                "AIRA could not assume the configured role",
            )
        )
    )
    configured = _configured(denied_service)
    denied = denied_service.verify(
        _actor(), ORG, WORKSPACE, configured.id, expected_version=configured.version
    )
    assert denied.state is AwsIntegrationState.ERROR
    assert denied.verification and not denied.verification.assume_role_passed


def test_trust_documents_are_deterministic_and_contain_no_credentials() -> None:
    service, _ = _service()
    integration = _create(service)
    instructions = service.trust_instructions(
        _actor(), ORG, WORKSPACE, integration.id
    )
    serialized = str(instructions)
    assert instructions.trusted_principal_arn == PRINCIPAL
    assert instructions.trust_policy["Statement"][0]["Condition"]["StringEquals"]["sts:ExternalId"] == "x" * 43
    assert "cloudwatch:*" not in serialized
    assert "SecretAccessKey" not in serialized


def test_disable_is_durable_and_viewers_cannot_manage() -> None:
    service, _ = _service()
    integration = _create(service)
    disabled = service.disable(
        _actor(), ORG, WORKSPACE, integration.id, expected_version=integration.version
    )
    assert disabled.state is AwsIntegrationState.DISABLED
    viewer_service, _ = _service(role=MembershipRole.VIEWER)
    with pytest.raises(Exception, match="Access denied"):
        _create(viewer_service)
    with pytest.raises(Exception, match="Access denied"):
        viewer_service.trust_instructions(
            _actor(), ORG, WORKSPACE, integration.id
        )


def test_hosted_api_lifecycle_and_safe_contract() -> None:
    service, _ = _service()
    application = FastAPI()
    application.include_router(
        build_hosted_aws_integration_router(service, lambda: _actor())
    )
    client = TestClient(application)
    prefix = f"/v3/organizations/{ORG}/workspaces/{WORKSPACE}/integrations/aws"
    created = client.post(
        prefix,
        json={
            "display_name": "Production AWS",
            "aws_account_id": "123456789012",
            "enabled_regions": ["eu-west-2"],
        },
    )
    assert created.status_code == 201
    body = created.json()
    integration_id = body["integration_id"]
    assert body["state"] == "draft"
    assert "external_id" not in body
    assert "access_key" not in created.text.lower()

    trust = client.get(f"{prefix}/{integration_id}/trust-instructions")
    assert trust.status_code == 200
    assert trust.json()["trusted_principal_arn"] == PRINCIPAL
    configured = client.patch(
        f"{prefix}/{integration_id}",
        json={"expected_version": 1, "role_arn": ROLE},
    )
    assert configured.status_code == 200
    verified = client.post(
        f"{prefix}/{integration_id}/verify", json={"expected_version": 2}
    )
    assert verified.status_code == 200
    assert verified.json()["state"] == "ready"
    assert len(client.get(prefix).json()["items"]) == 1
    assert client.post(
        f"{prefix}/{integration_id}/disable", json={"expected_version": 2}
    ).status_code == 409
    assert client.post(
        prefix,
        json={"display_name": "Bad", "aws_account_id": "123", "enabled_regions": ["eu-west-2"]},
    ).status_code == 422
