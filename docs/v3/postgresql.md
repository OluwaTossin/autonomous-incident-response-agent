# Version 3 PostgreSQL Foundation

This document covers the local hosted-development database introduced in V3.3. It does
not describe an AWS database deployment. Version 2 self-hosted commands and the default
`docker-compose.yml` remain independent of PostgreSQL.

## Architecture

The hosted persistence stack uses synchronous SQLAlchemy 2.x with psycopg 3. The current
FastAPI, CLI, and shared triage entrypoints are synchronous, and database transactions
must finish before retrieval, LLM calls, or external API work. An async database stack
would add a second execution model without a demonstrated V3.3 requirement.

The package boundaries are:

- `app/domain/`: framework-independent domain records and invariants; no SQLAlchemy.
- `app/application/repositories.py`: narrow repository protocols at the application boundary.
- `app/persistence/postgres/models.py`: SQLAlchemy table mappings.
- `app/persistence/postgres/mappers.py`: explicit domain-to-record and record-to-domain conversion.
- `app/persistence/postgres/repositories.py`: PostgreSQL repository adapters.
- `app/persistence/postgres/unit_of_work.py`: one short transaction and one tenant context.
- `app/persistence/postgres/tenant.py`: transaction-local RLS context.
- `migrations/`: deterministic Alembic schema, privilege, and RLS changes.

V3.3 intentionally does not wire existing FastAPI routes to these repositories. A hosted
composition will do that in a later phase. The Version 2 filesystem workspace, FAISS,
JSONL audit, feedback, and reindex state remain unchanged.

## Database Roles

Use separate credentials for migrations and application traffic:

- `aira_migrator` owns the local development database objects and runs Alembic. A
  production migration identity should have only the DDL and ownership privileges needed
  for managed migrations.
- `aira_app` is the runtime login. It is not a superuser, cannot create roles or databases,
  has no `BYPASSRLS`, cannot create objects in `public`, and owns no application tables.
  Migrations grant it DML only on named application tables, not Alembic migration history.

Never use the migration URL in an application process. There is no implicit privileged
background-worker role: any future internal operation that needs broader access requires
an explicit, reviewed design.

## Local Development

Choose local-only development passwords, then start the opt-in database:

```bash
export AIRA_DB_MIGRATION_PASSWORD=local-migration-password
export AIRA_DB_RUNTIME_PASSWORD=local-runtime-password
docker compose -f docker-compose.hosted-db.yml up -d --wait
```

The first container initialization creates `aira_app`. Existing volumes are not
reinitialized when password environment variables change.

Set the two URLs without committing their credentials:

```bash
export AIRA_DATABASE_MIGRATION_URL='postgresql+psycopg://aira_migrator:local-migration-password@127.0.0.1:55432/aira_hosted'
export AIRA_DATABASE_URL='postgresql+psycopg://aira_app:local-runtime-password@127.0.0.1:55432/aira_hosted'
```

Apply or inspect migrations:

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic history
uv run alembic check
```

For a safe local reset, stop the stack, explicitly remove only its named development
volume, and start it again. This permanently deletes local hosted-development data:

```bash
docker compose -f docker-compose.hosted-db.yml down
docker volume rm aira-hosted-db_aira_hosted_postgres
docker compose -f docker-compose.hosted-db.yml up -d --wait
uv run alembic upgrade head
```

## Transactions And RLS

Every tenant-scoped runtime transaction must receive trusted `TenantContext` from the
composition boundary. V3.4 will derive it from verified identity; request payload values
must never establish it.

`apply_tenant_context()` calls PostgreSQL `set_config(..., true)`, equivalent to transaction-
local `SET LOCAL`, for `app.organization_id` and `app.workspace_id`. RLS policies read those
settings with `current_setting(..., true)`. Organization-owned rows require a matching
organization. Workspace-owned rows require both matching organization and workspace.
Missing or blank settings produce no visible tenant rows and reject tenant writes.

Tenant settings are valid only inside the current transaction. Code must use
`tenant_transaction()` or `PostgresUnitOfWork`, keep the transaction short, and close it
before retrieval, LLM calls, external APIs, or other potentially long work. Tests reuse
the same one-connection pool to prove that one tenant's settings do not survive commit.

Application authorization remains required in later phases. RLS is an independent
defense-in-depth boundary, not an RBAC implementation.

## Migrations And Recovery

Alembic migrations are reviewed source artifacts and run only with the migration role.
Fresh-schema upgrade is mandatory in CI. A downgrade is acceptable for this initial,
non-destructive foundation migration, but future destructive migrations must not assume
that downgrade is safe. Use expand-and-contract changes, forward fixes, and a tested data
restore when reversal could lose or reinterpret data.

Before a production launch, the hosted infrastructure phase must define retention, RPO,
RTO, encrypted automated backups, point-in-time recovery, and access to backup operations.
A restore rehearsal into an isolated environment is required before claiming recoverability;
a successful backup job alone is insufficient. Migration releases must identify their
restore point and compatibility window. These are architecture expectations, not an AWS
RDS implementation in V3.3.

## PostgreSQL Tests

The integration suite requires the real local PostgreSQL roles because SQLite cannot
exercise PostgreSQL RLS, role ownership, or transaction-local settings:

```bash
export AIRA_TEST_MIGRATION_DATABASE_URL="$AIRA_DATABASE_MIGRATION_URL"
export AIRA_TEST_DATABASE_URL="$AIRA_DATABASE_URL"
uv run pytest tests/postgres -q
```

The fixture migrates a clean schema and truncates application tables between tests. Use
only an expendable local test database with these variables.
