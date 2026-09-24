"""Transaction-local PostgreSQL tenant context."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.auth.context import ActorContext
from app.authorization.service import AuthorizedTenantContext
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


def apply_actor_context(session: Session, context: ActorContext) -> None:
    """Apply verified identity for narrowly scoped authorization-fact policies."""
    session.execute(
        text("SELECT set_config('app.actor_kind', :actor_kind, true)"),
        {"actor_kind": context.actor.kind.value},
    )
    session.execute(
        text("SELECT set_config('app.actor_id', :actor_id, true)"),
        {"actor_id": str(context.actor.actor_id) if context.actor.actor_id else ""},
    )
    session.execute(
        text("SELECT set_config('app.system_name', :system_name, true)"),
        {"system_name": context.actor.system_name or ""},
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


@contextmanager
def actor_transaction(
    session_factory: sessionmaker[Session],
    context: ActorContext,
) -> Iterator[Session]:
    """Read authorization facts using verified actor identity, before tenant scope."""
    with session_factory.begin() as session:
        apply_actor_context(session, context)
        yield session


@contextmanager
def authorized_tenant_transaction(
    session_factory: sessionmaker[Session],
    context: AuthorizedTenantContext,
) -> Iterator[Session]:
    """Establish RLS scope only from a sealed successful authorization result."""
    with tenant_transaction(
        session_factory,
        TenantContext(context.organization_id, context.workspace_id),
    ) as session:
        yield session
