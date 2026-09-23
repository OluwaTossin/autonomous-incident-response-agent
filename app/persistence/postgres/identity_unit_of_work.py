"""Short global identity transaction, deliberately without tenant RLS context."""

from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session, sessionmaker

from app.persistence.postgres.identity_repositories import (
    PostgresServiceAccountCredentialRepository,
    PostgresServiceAccountRepository,
    PostgresUserIdentityRepository,
)


class PostgresIdentityUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self.session: Session | None = None

    def __enter__(self) -> PostgresIdentityUnitOfWork:
        self.session = self._session_factory()
        self.session.begin()
        self.users = PostgresUserIdentityRepository(self.session)
        self.service_accounts = PostgresServiceAccountRepository(self.session)
        self.service_account_credentials = (
            PostgresServiceAccountCredentialRepository(self.session)
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.session is None:
            return
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None
