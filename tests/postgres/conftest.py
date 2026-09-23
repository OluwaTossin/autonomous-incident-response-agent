"""Real PostgreSQL fixtures for migrations, constraints, repositories, and RLS."""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from app.persistence.postgres.engine import (
    create_postgres_engine,
    create_session_factory,
)
from app.persistence.postgres.models import Base


@dataclass(frozen=True)
class PostgresTestDatabase:
    migration_engine: Engine
    runtime_engine: Engine


@pytest.fixture(scope="session")
def postgres_database() -> PostgresTestDatabase:
    migration_url = os.environ.get("AIRA_TEST_MIGRATION_DATABASE_URL", "").strip()
    runtime_url = os.environ.get("AIRA_TEST_DATABASE_URL", "").strip()
    if not migration_url or not runtime_url:
        pytest.skip(
            "Set AIRA_TEST_MIGRATION_DATABASE_URL and AIRA_TEST_DATABASE_URL "
            "to run PostgreSQL integration tests"
        )

    previous_url = os.environ.get("AIRA_DATABASE_MIGRATION_URL")
    os.environ["AIRA_DATABASE_MIGRATION_URL"] = migration_url
    config = Config("alembic.ini")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    migration_engine = create_postgres_engine(
        migration_url, pool_size=1, max_overflow=0
    )
    runtime_engine = create_postgres_engine(runtime_url, pool_size=1, max_overflow=0)
    database = PostgresTestDatabase(migration_engine, runtime_engine)
    yield database

    runtime_engine.dispose()
    migration_engine.dispose()
    if previous_url is None:
        os.environ.pop("AIRA_DATABASE_MIGRATION_URL", None)
    else:
        os.environ["AIRA_DATABASE_MIGRATION_URL"] = previous_url


@pytest.fixture(autouse=True)
def clean_postgres(postgres_database: PostgresTestDatabase) -> None:
    table_names = sorted(
        name for name in Base.metadata.tables if name != "alembic_version"
    )
    quoted = ", ".join(f'"{name}"' for name in table_names)
    with postgres_database.migration_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {quoted} CASCADE"))


@pytest.fixture
def runtime_session_factory(postgres_database: PostgresTestDatabase):
    return create_session_factory(postgres_database.runtime_engine)
