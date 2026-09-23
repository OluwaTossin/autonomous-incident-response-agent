"""Synchronous SQLAlchemy engine and session construction for hosted mode."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_postgres_engine(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_pre_ping: bool = True,
) -> Engine:
    """Create a PostgreSQL engine only when a hosted composition requests one."""
    if not database_url.strip():
        raise ValueError("A hosted PostgreSQL database URL is required")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("Hosted persistence requires a PostgreSQL URL")
    return create_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
