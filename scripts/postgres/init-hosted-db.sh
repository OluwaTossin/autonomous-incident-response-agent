#!/bin/sh
set -eu

: "${AIRA_DB_RUNTIME_PASSWORD:?AIRA_DB_RUNTIME_PASSWORD is required}"

psql --set=ON_ERROR_STOP=1 \
  --set=runtime_password="$AIRA_DB_RUNTIME_PASSWORD" \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" <<'SQL'
SELECT format(
  'CREATE ROLE aira_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'runtime_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aira_app')
\gexec

ALTER ROLE aira_app WITH
  LOGIN
  PASSWORD :'runtime_password'
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT
  NOBYPASSRLS;
SQL
