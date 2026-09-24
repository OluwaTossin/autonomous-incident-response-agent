"""Tenant-scoped repositories for memberships and authorization grants."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.governance import GovernanceConflict
from app.authorization.models import (
    MembershipWorkspaceGrant,
    ServiceAccountGrant,
    ServiceAccountWorkspaceGrant,
)
from app.domain.identifiers import (
    MembershipId,
    OrganizationId,
    ServiceAccountGrantId,
    ServiceAccountId,
)
from app.domain.tenancy import MembershipRole, MembershipState, OrganizationMembership
from app.persistence.postgres.mappers import (
    membership_from_record,
    membership_to_record,
    membership_workspace_grant_to_record,
    service_account_grant_from_record,
    service_account_grant_to_record,
    service_account_workspace_grant_to_record,
)
from app.persistence.postgres.models import (
    MembershipWorkspaceGrantRecord,
    OrganizationMembershipRecord,
    OrganizationRecord,
    ServiceAccountAuthorizationGrantRecord,
    ServiceAccountWorkspaceGrantRecord,
)


class PostgresMembershipRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, membership: OrganizationMembership) -> None:
        try:
            self._session.add(membership_to_record(membership))
            self._session.flush()
        except IntegrityError as exc:
            raise GovernanceConflict("Membership already exists") from exc

    def save(self, membership: OrganizationMembership) -> None:
        self._session.merge(membership_to_record(membership))
        self._session.flush()

    def get(self, membership_id: MembershipId) -> OrganizationMembership | None:
        record = self._session.get(
            OrganizationMembershipRecord, UUID(str(membership_id))
        )
        return membership_from_record(record) if record else None

    def get_for_user(
        self, organization_id: OrganizationId, user_id: object
    ) -> OrganizationMembership | None:
        record = self._session.scalar(
            select(OrganizationMembershipRecord).where(
                OrganizationMembershipRecord.organization_id
                == UUID(str(organization_id)),
                OrganizationMembershipRecord.user_id == UUID(str(user_id)),
            )
        )
        return membership_from_record(record) if record else None

    def list(self) -> list[OrganizationMembership]:
        records = self._session.scalars(
            select(OrganizationMembershipRecord).order_by(
                OrganizationMembershipRecord.created_at,
                OrganizationMembershipRecord.id,
            )
        ).all()
        return [membership_from_record(record) for record in records]

    def count_active_owners(self) -> int:
        return int(
            self._session.scalar(
                select(func.count()).select_from(OrganizationMembershipRecord).where(
                    OrganizationMembershipRecord.role == MembershipRole.OWNER.value,
                    OrganizationMembershipRecord.state == MembershipState.ACTIVE.value,
                )
            )
            or 0
        )

    def lock_organization(self, organization_id: OrganizationId) -> None:
        self._session.execute(
            select(OrganizationRecord.id)
            .where(OrganizationRecord.id == UUID(str(organization_id)))
            .with_for_update()
        ).scalar_one()


class PostgresMembershipWorkspaceGrantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace(
        self,
        membership_id: MembershipId,
        grants: list[MembershipWorkspaceGrant],
    ) -> None:
        self._session.execute(
            delete(MembershipWorkspaceGrantRecord).where(
                MembershipWorkspaceGrantRecord.membership_id
                == UUID(str(membership_id))
            )
        )
        self._session.add_all(
            [membership_workspace_grant_to_record(grant) for grant in grants]
        )
        self._session.flush()


class PostgresServiceAccountGrantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, grant: ServiceAccountGrant) -> None:
        try:
            self._session.add(service_account_grant_to_record(grant))
            self._session.flush()
        except IntegrityError as exc:
            raise GovernanceConflict("Active service-account grant already exists") from exc

    def save(self, grant: ServiceAccountGrant) -> None:
        self._session.merge(service_account_grant_to_record(grant))
        self._session.flush()

    def get(self, grant_id: ServiceAccountGrantId) -> ServiceAccountGrant | None:
        record = self._session.get(
            ServiceAccountAuthorizationGrantRecord, UUID(str(grant_id))
        )
        return service_account_grant_from_record(record) if record else None

    def get_active(
        self,
        organization_id: OrganizationId,
        service_account_id: ServiceAccountId,
    ) -> ServiceAccountGrant | None:
        record = self._session.scalar(
            select(ServiceAccountAuthorizationGrantRecord).where(
                ServiceAccountAuthorizationGrantRecord.organization_id
                == UUID(str(organization_id)),
                ServiceAccountAuthorizationGrantRecord.service_account_id
                == UUID(str(service_account_id)),
                ServiceAccountAuthorizationGrantRecord.revoked_at.is_(None),
            )
        )
        return service_account_grant_from_record(record) if record else None


class PostgresServiceAccountWorkspaceGrantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace(
        self,
        grant_id: ServiceAccountGrantId,
        grants: list[ServiceAccountWorkspaceGrant],
    ) -> None:
        self._session.execute(
            delete(ServiceAccountWorkspaceGrantRecord).where(
                ServiceAccountWorkspaceGrantRecord.service_account_grant_id
                == UUID(str(grant_id))
            )
        )
        self._session.add_all(
            [service_account_workspace_grant_to_record(grant) for grant in grants]
        )
        self._session.flush()
