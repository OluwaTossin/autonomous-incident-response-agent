"""Transaction-local PostgreSQL tenant context."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.domain.identifiers import OrganizationId, WorkspaceId


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Trusted tenant scope established by a composition/authentication boundary."""

    organization_id: OrganizationId
    workspace_id: WorkspaceId | None = None


def apply_tenant_context(session: Session, context: TenantContext) -> None:
    """Apply tenant IDs to the current transaction only; never use session-level ``SET``."""
    session.execute(
        text("SELECT set_config('app.organization_id', :organization_id, true)"),
        {"organization_id": str(context.organization_id)},
    )
    session.execute(
        text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
        {"workspace_id": str(context.workspace_id) if context.workspace_id else ""},
    )


@contextmanager
def tenant_transaction(
    session_factory: sessionmaker[Session],
    context: TenantContext,
) -> Iterator[Session]:
    """Open one short transaction, apply RLS context, and commit or roll back."""
    with session_factory.begin() as session:
        apply_tenant_context(session, context)
        yield session
