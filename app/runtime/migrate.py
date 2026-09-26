"""One-off ECS migration entrypoint with separate schema-owner credentials."""

from __future__ import annotations

import json
import os
from urllib.parse import quote

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url


def main() -> None:
    master = json.loads(_required("AIRA_DB_MASTER_SECRET"))
    runtime_url = make_url(_required("AIRA_DATABASE_URL"))
    if runtime_url.username != "aira_app" or not runtime_url.password:
        raise RuntimeError("Runtime database secret must use the aira_app login")
    required_master = ("host", "port", "username", "password")
    if any(not master.get(key) for key in required_master):
        raise RuntimeError("RDS master secret is incomplete")
    database = master.get("dbname") or runtime_url.database
    with psycopg.connect(
        host=master["host"],
        port=int(master["port"]),
        user=master["username"],
        password=master["password"],
        dbname=database,
        sslmode="require",
        autocommit=True,
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = 'aira_app'"
        ).fetchone()
        if exists is None:
            connection.execute(
                sql.SQL("CREATE ROLE aira_app LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS").format(
                    sql.Literal(runtime_url.password)
                )
            )
        else:
            connection.execute(
                sql.SQL("ALTER ROLE aira_app WITH PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS").format(
                    sql.Literal(runtime_url.password)
                )
            )
    migration_url = (
        "postgresql+psycopg://"
        f"{quote(str(master['username']), safe='')}:{quote(str(master['password']), safe='')}"
        f"@{master['host']}:{master['port']}/{database}?sslmode=require"
    )
    os.environ["AIRA_DATABASE_MIGRATION_URL"] = migration_url
    command.upgrade(Config("alembic.ini"), "head")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


if __name__ == "__main__":
    main()
