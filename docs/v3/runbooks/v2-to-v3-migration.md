# V2 to V3 Migration Runbook

This runbook is an operator procedure and does not authorize a live migration. Replace example IDs
and paths only with approved values. Never put credentials in shell history, CLI arguments,
packages, reports, or tickets.

## Preconditions

- Approved V2 source version and workspace owner.
- Source filesystem backup/archive and restoration test.
- Current RDS automated backup plus an approved pre-cutover snapshot plan.
- Target V3 release deployed and qualified using its immutable release manifest.
- Alembic is at the release manifest revision.
- Destination organization/workspace exists and is active.
- Dedicated service account is scoped to that workspace with only `migration.import`.
- Destination S3/KMS access, quotas, Cognito access, monitoring, and fallback owners are ready.
- V2, V3, security, migration, and knowledge verification suites are green.

Do not use the schema-owner database credential. Do not disable RLS. Do not copy API keys, AWS
keys, browser cookies, database credentials, private keys, or provider tokens.

## 1. Back up and inventory V2

Record the V2 build SHA/version and workspace path. Stop only long enough to make a consistent
filesystem backup if V2 cannot snapshot atomically. Capture counts and SHA-256 values for:

- supported files under `data/runbooks`, `data/incidents`, `data/logs`, and
  `data/knowledge_base`;
- recognized JSONL history;
- config for operator review;
- local FAISS files for backup evidence only.

The exporter never mutates these files. Keep the backup and original workspace read only after the
final freeze.

## 2. Build a package

Create the package outside the V2 workspace:

```bash
uv run aira-migrate \
  --mode export \
  --source /absolute/path/to/v2-workspace \
  --output /secure/operator/path/migration-package \
  --source-identifier approved-source/default \
  --source-build-sha <40-character-v2-sha>
```

Retain the printed manifest hash. Inspect `migration-manifest.json`; review every `omitted` setting.
Do not edit the package to work around a rejection. Correct the source selection and rebuild into a
new empty destination.

## 3. Provision migration identity

Create or select a dedicated AIRA service account with a workspace-limited grant containing
`migration.import`. Store the credential in the approved secret channel and expose it only to the
operator process:

```bash
export AIRA_MIGRATION_CREDENTIAL='<retrieved securely>'
```

Also provide the approved hosted runtime database URL, document bucket, KMS key ARN, and AWS region.
The runtime database role must remain the non-owner `aira_app` role with no `BYPASSRLS`.

## 4. Preflight

```bash
uv run aira-migrate \
  --mode preflight \
  --source /secure/operator/path/migration-package \
  --organization-id <organization-uuid> \
  --workspace-id <workspace-uuid> \
  --output /secure/operator/path/preflight-report.json
```

Require a clean report. Review document count/byte quota impact, conflicts, skipped records,
historical-only records, unmapped configuration and `knowledge_rebuild_required`. A quota failure
must be resolved through an approved quota policy change; never bypass it in migration code.

## 5. Dry run

Run the same inputs using `--mode dry-run`. Dry-run performs authorization, destination checks,
conflict detection, and quota admission but creates no database rows, usage events, audit events, or
S3 objects.

```bash
uv run aira-migrate \
  --mode dry-run \
  --source /secure/operator/path/migration-package \
  --organization-id <organization-uuid> \
  --workspace-id <workspace-uuid> \
  --output /secure/operator/path/dry-run-report.json
```

Resolve every rejection. The supported conflict policies are `fail` and `skip-identical`; overwrite
does not exist.

## 6. Rehearsal import

Use a non-production target with synthetic or approved sanitized data. Real import requires an
explicit confirmation flag:

```bash
uv run aira-migrate \
  --mode import \
  --source /secure/operator/path/migration-package \
  --organization-id <organization-uuid> \
  --workspace-id <workspace-uuid> \
  --conflict-mode skip-identical \
  --confirm-import \
  --output /secure/operator/path/import-report.json
```

The tool commits one document logical unit at a time. If interrupted, preserve the package and rerun
the exact command. Deterministic IDs and immutable object keys resume pending units and skip
completed identical units. Do not delete pending database rows or S3 objects manually.

## 7. Verify import

```bash
uv run aira-migrate \
  --mode verify \
  --source /secure/operator/path/migration-package \
  --organization-id <organization-uuid> \
  --workspace-id <workspace-uuid> \
  --output /secure/operator/path/verification-report.json
```

Check target count and bytes, document/version relationships, tenant scope, AVAILABLE state, object
key, checksum, size, media type, usage events, and migration audit provenance. Run orphan/composite
FK and forced-RLS tests. A successful process exit is not sufficient evidence.

## 8. Rebuild knowledge

Never upload or activate the V2 `index.faiss`, `chunks.jsonl`, or `meta.json`. Invoke the existing
authorized V3 knowledge build against imported AVAILABLE source versions. Require:

1. BUILDING created with the expected source-version IDs;
2. immutable artifacts and manifest published;
3. all artifact checksums verified;
4. bundle loads and retrieval regression passes;
5. state reaches READY, then ACTIVE through the normal service;
6. the ACTIVE index identity is recorded in the checkpoint.

Corrupt or incomplete bundles must fail and remain inactive.

## 9. Prepare final cutover

V2 has no comprehensive application-level read-only mode. Enforce an operational freeze:

1. announce the write freeze and expected reauthentication;
2. block V2 mutation and ingest routes at the routing/operator boundary;
3. stop n8n/external writers and verify no writer remains;
4. preserve only explicitly enforceable read access;
5. hash the source again and compare it with rehearsal evidence.

There is no dual write. If source hashes changed, produce a fresh deterministic package/final delta
where record identity makes that safe. If any change cannot be classified safely, keep V2 frozen
and rebuild/import a complete final package.

## 10. Capture the checkpoint

Store together:

- V2 backup reference, source counts/checksums and final manifest hash;
- preflight, dry-run, import and verification reports;
- destination counts and integrity query results;
- qualified V3 release manifest and exact image digests;
- current Alembic revision;
- ACTIVE knowledge bundle identity/manifest checksum;
- Cognito, integration, monitoring and smoke-test evidence;
- timestamp, operators/approvers and fallback owner.

The cutover validator must report ready with no reasons. Its result is evidence, not authorization.
V3.29 owns live rehearsal, routing validation, SLO observation and final go/no-go.

## 11. Future traffic sequence

No DNS or traffic change is performed in V3.27. The future approved sequence is:

1. lower DNS TTL in advance if DNS is the routing mechanism;
2. validate V3 HTTPS, sessions, tenant selection, API/worker health, queue age and ACTIVE knowledge;
3. hold V2 frozen and complete final verification;
4. switch the application hostname/traffic to V3;
5. require users to authenticate through Cognito;
6. monitor health, SLO/error-budget indicators and ingestion/triage success;
7. retain the isolated V2 endpoint and backup for the approved fallback window.

External V2 API clients require an explicit client migration. V3 is not a drop-in replacement for
`POST /triage`: authentication, tenant routing, payloads, asynchronous polling and error contracts
differ.

## Failure recovery and fallback

Before V3 accepts unique writes, fallback may route users to the still-frozen V2 deployment while
V3 imported data remains isolated. Stop V3 writers first, preserve all V3 data/evidence, diagnose,
and never delete imported data as a rollback step.

**Point of no simple fallback:** the first V3-only incident, document, approval, quota mutation, or
other unique write accepted after traffic switch. After this point, routing back to V2 can omit V3
data. Fallback requires an incident-specific reconciliation plan, explicit data ownership decision,
and approval. There is no automatic reverse migration.

For an interrupted import:

- storage failure before object creation: rerun the same package;
- unknown object-write result: rerun; immutable stat/checksum decides whether to continue;
- pending metadata with no object: rerun;
- matching AVAILABLE record: skipped;
- source identity bound to different data: stop on `conflict`; do not overwrite;
- quota rejection: stop before new units, approve capacity, rerun;
- checksum/package/security rejection: quarantine the package and rebuild from verified source.

Never disable RLS, use `BYPASSRLS`, run arbitrary SQL, mutate the V2 source, or manually relabel a
failed package as successful.

## Final operator checklist

- [ ] Supported V2 source/build and verified backup.
- [ ] Versioned package and stable manifest hash.
- [ ] Clean preflight and dry-run with quotas approved.
- [ ] Exact destination organization/workspace and migration actor approved.
- [ ] Import and verification reports clean; no unresolved conflicts.
- [ ] Alembic and release manifest match; V2/V3/security gates green.
- [ ] V3 knowledge bundle verified and ACTIVE.
- [ ] Cognito, secrets, AWS integrations and monitoring independently ready.
- [ ] V2 mutation freeze verified; final hashes/checkpoint captured.
- [ ] Users/client owners informed about reauthentication and async API changes.
- [ ] Fallback owner, bounded window and point-of-no-simple-fallback acknowledged.
- [ ] V3.29 live rehearsal and go/no-go approval still pending.
