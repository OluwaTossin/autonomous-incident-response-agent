"""Approved V3.5 permission vocabulary and role matrix."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from app.domain.tenancy import MembershipRole


class Permission(StrEnum):
    ORGANIZATION_CREATE = "organization.create"
    ORGANIZATION_READ = "organization.read"
    ORGANIZATION_UPDATE = "organization.update"
    ORGANIZATION_TRANSFER_OWNERSHIP = "organization.transfer_ownership"
    MEMBERSHIP_READ = "membership.read"
    MEMBERSHIP_INVITE = "membership.invite"
    MEMBERSHIP_UPDATE = "membership.update"
    MEMBERSHIP_REMOVE = "membership.remove"
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_CREATE = "workspace.create"
    WORKSPACE_UPDATE = "workspace.update"
    WORKSPACE_ARCHIVE = "workspace.archive"
    INCIDENT_READ = "incident.read"
    INCIDENT_CREATE = "incident.create"
    TRIAGE_RUN = "triage.run"
    JOB_READ = "job.read"
    JOB_CREATE = "job.create"
    JOB_CANCEL = "job.cancel"
    JOB_RETRY = "job.retry"
    JOB_EXECUTE = "job.execute"
    KNOWLEDGE_READ = "knowledge.read"
    KNOWLEDGE_MANAGE = "knowledge.manage"
    INTEGRATION_READ = "integration.read"
    INTEGRATION_MANAGE = "integration.manage"
    ACTION_READ = "action.read"
    ACTION_PROPOSE = "action.propose"
    APPROVAL_READ = "approval.read"
    APPROVAL_REQUEST = "approval.request"
    APPROVAL_DECIDE = "approval.decide"
    EXECUTION_INTENT_READ = "execution_intent.read"
    EXECUTION_INTENT_PREPARE = "execution_intent.prepare"
    EXECUTION_INTENT_CANCEL = "execution_intent.cancel"
    USAGE_READ = "usage.read"
    AUDIT_READ = "audit.read"
    SERVICE_ACCOUNT_READ = "service_account.read"
    SERVICE_ACCOUNT_MANAGE = "service_account.manage"


_VIEWER = frozenset(
    {
        Permission.ORGANIZATION_READ,
        Permission.WORKSPACE_READ,
        Permission.INCIDENT_READ,
        Permission.JOB_READ,
        Permission.KNOWLEDGE_READ,
        Permission.INTEGRATION_READ,
        Permission.ACTION_READ,
        Permission.APPROVAL_READ,
        Permission.EXECUTION_INTENT_READ,
    }
)
_OPERATOR = _VIEWER | {
    Permission.INCIDENT_CREATE,
    Permission.TRIAGE_RUN,
    Permission.JOB_CREATE,
    Permission.JOB_CANCEL,
    Permission.JOB_RETRY,
    Permission.KNOWLEDGE_MANAGE,
    Permission.ACTION_PROPOSE,
    Permission.APPROVAL_REQUEST,
    Permission.AUDIT_READ,
}
_ADMIN = frozenset(Permission) - {
    Permission.ORGANIZATION_CREATE,
    Permission.ORGANIZATION_TRANSFER_OWNERSHIP,
    Permission.JOB_EXECUTE,
}
_OWNER = frozenset(Permission) - {
    Permission.ORGANIZATION_CREATE,
    Permission.JOB_EXECUTE,
}

ROLE_PERMISSIONS = MappingProxyType(
    {
        MembershipRole.OWNER: _OWNER,
        MembershipRole.ADMIN: _ADMIN,
        MembershipRole.OPERATOR: frozenset(_OPERATOR),
        MembershipRole.VIEWER: _VIEWER,
    }
)

WORKSPACE_SCOPED_PERMISSIONS = frozenset(
    {
        Permission.WORKSPACE_READ,
        Permission.WORKSPACE_UPDATE,
        Permission.WORKSPACE_ARCHIVE,
        Permission.INCIDENT_READ,
        Permission.INCIDENT_CREATE,
        Permission.TRIAGE_RUN,
        Permission.JOB_READ,
        Permission.JOB_CREATE,
        Permission.JOB_CANCEL,
        Permission.JOB_RETRY,
        Permission.JOB_EXECUTE,
        Permission.KNOWLEDGE_READ,
        Permission.KNOWLEDGE_MANAGE,
        Permission.INTEGRATION_READ,
        Permission.INTEGRATION_MANAGE,
        Permission.ACTION_READ,
        Permission.ACTION_PROPOSE,
        Permission.APPROVAL_READ,
        Permission.APPROVAL_REQUEST,
        Permission.APPROVAL_DECIDE,
        Permission.EXECUTION_INTENT_READ,
        Permission.EXECUTION_INTENT_PREPARE,
        Permission.EXECUTION_INTENT_CANCEL,
    }
)

SERVICE_ACCOUNT_GRANTABLE_PERMISSIONS = frozenset(
    {
        Permission.ORGANIZATION_READ,
        Permission.WORKSPACE_READ,
        Permission.INCIDENT_READ,
        Permission.INCIDENT_CREATE,
        Permission.TRIAGE_RUN,
        Permission.JOB_READ,
        Permission.JOB_CREATE,
        Permission.JOB_CANCEL,
        Permission.JOB_RETRY,
        Permission.KNOWLEDGE_READ,
        Permission.INTEGRATION_READ,
        Permission.ACTION_READ,
        Permission.ACTION_PROPOSE,
    }
)


def role_allows(role: MembershipRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
