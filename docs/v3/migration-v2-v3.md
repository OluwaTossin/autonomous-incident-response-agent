# V2 to V3 Migration and Compatibility

## Scope and safety boundary

V3.27 provides an operator-controlled path from a retained V2 filesystem workspace to an
existing V3 organization and workspace. It does not perform a production cutover, change DNS,
deploy infrastructure, or migrate customer data automatically. The V2 source is always read
only. The generated migration package is a separate directory and is treated as untrusted input.

The supported import is deliberately narrow:

| V2 artifact | Classification | V3.27 behavior |
|---|---|---|
| Runbooks, incident documents, log documents, knowledge text | Directly migratable | Imported as tenant-scoped V3 documents and immutable versions |
| Safe allowlisted workspace settings | Transformable | Reported for operator review; not applied automatically |
| Triage output, feedback, n8n history JSONL | Historical only | Checksummed into `history/`; not inserted as native V3 audit/triage events |
| Local FAISS index, chunks and metadata | Re-creatable | Never imported; rebuild and verify a V3 immutable bundle |
| V2 API/admin keys and local sessions | Unsupported | Never exported; users reauthenticate through Cognito |
| Provider keys, AWS keys, passwords and tokens | Unsupported | Rejected or omitted; destination secrets are provisioned independently |
| AWS role/config metadata | Requires operator decision | Fresh V3 onboarding and AssumeRole verification are required |
| Queue/process/cache/temp/lock state | Unsupported | Never exported |
| Local JSONL audit | Historical only | Retained in source backup; no claim that it is native V3 audit history |

V2 historical triage lacks enough durable identity, tenant, actor, lifecycle, and provenance data
to satisfy V3 constraints without inventing facts. It therefore remains historical-only in V3.27.
No imported history enqueues triage, creates proposals, requests approvals, or prepares intents.

## Source and destination models

V2 stores a workspace under `workspaces/<workspace>/`:

- `data/{runbooks,incidents,logs,knowledge_base}` contains source material;
- `index/{index.faiss,chunks.jsonl,meta.json}` is a mutable local retrieval index;
- `config/operator_overrides.yaml` contains local settings;
- JSONL files contain triage output, feedback, and n8n workflow history.

V2 does not persist V3 organizations, memberships, workspace grants, browser sessions, durable
incidents/jobs, action approvals/intents, integration verification, usage counters, or immutable
knowledge publication state.

The destination is never inferred from source names or content. Every operation requires an
explicit `organization_id` and `workspace_id`. A verified human Owner/Admin or narrowly granted
service account must hold `migration.import`. Authorization produces an
`AuthorizedTenantContext`; each PostgreSQL unit of work applies transaction-local tenant context.
The runtime role continues to use forced RLS and has neither table ownership nor `BYPASSRLS`.

## Compatibility matrix

| Capability | V2 behavior | V3 hosted behavior | Compatibility and migration | Cutover/fallback impact |
|---|---|---|---|---|
| Triage API | `POST /triage`, synchronous | Incident create plus asynchronous triage/job resources | Not a drop-in endpoint; clients must adapt auth, payloads, polling and errors | Keep V2 endpoint during rehearsal; switch clients explicitly |
| CLI | Local `triage`, RAG and workspace commands | No hosted CLI replacement | V2 CLI remains local and unchanged | May remain available against frozen V2 data |
| Gradio | Optional local UI on self-hosted API | Not part of hosted web | Retained V2-only | May remain read-only during fallback window |
| V2 frontend | Static Next.js export against V2 API | Separate server-capable hosted Next.js service | Separate build and contracts | Users change URL and reauthenticate |
| Documents | Filesystem files | PostgreSQL metadata plus private S3 objects | Supported files import with checksum, size, media type and opaque key | Source backup remains authoritative until commit point |
| RAG/FAISS | Mutable local three-file index | Versioned, checksummed, immutable bundle lifecycle | Rebuild only; V2 binary is not reusable | Activate V3 bundle before traffic switch |
| Incident history | JSONL/input files with incomplete identity | Durable tenant-scoped incidents/runs/evidence | Historical-only in V3.27 | Available from retained V2 archive, not V3 incident UI |
| Audit | Local JSONL/application events | Immutable tenant-scoped audit ledger | Legacy audit is not inserted as native audit | Preserve source archive for historical review |
| Metrics | Process/CloudWatch side effects | Hosted bounded platform telemetry | No metric history migration | Start V3 SLO window at hosted operation |
| Authentication | Optional API/admin keys | Cognito session or service account | Keys/cookies do not migrate | Reauthentication is required |
| AWS integrations | Local/operator configuration | Verified cross-account trust and bounded capabilities | Fresh onboarding; no keys or cached STS credentials | Verify before enabling intake |
| Async jobs | None for synchronous triage | PostgreSQL lifecycle, outbox and SQS | No V2 job state to migrate | New submissions begin only after V3 write enablement |
| Proposals/approvals/intents | Not durable V2 concepts | Tenant-scoped controlled records | V3-only, not a regression | Never synthesized from imported output |
| Usage quotas | None | Durable quota policy, counters and ledger | Imported stored bytes/count count once; historical rates do not | Confirm capacity before import |

## Supported V2 contract

Retained self-hosted V2 remains a supported composition. Its CLI, Gradio UI, FastAPI endpoints,
local FAISS, JSONL audit, filesystem workspaces and static frontend must remain usable without
Cognito, PostgreSQL, SQS, RDS, hosted AWS resources, or hosted environment variables. The
`hosted` dependency extra and hosted startup validation are not required by generic V2 startup.
Migration does not repoint V2 commands to hosted V3.

## Migration package v1

Only directory packages are supported; tar and zip extraction are intentionally absent. The
package contains:

```text
migration-manifest.json
documents/data/<category>/...
history/<recognized-history-file>.jsonl
```

The canonical JSON manifest includes `schema_version`, `source_version`, `source_type`,
`source_identifier`, `created_at`, `source_build_sha`, `migration_tool_version`, typed record
counts, allowlisted configuration, omissions, and records. Each record carries a deterministic
source ID, safe relative package/source paths, SHA-256, byte size, media type, record type, and
document category where applicable. Unsupported schema/source versions and unknown manifest
fields are rejected rather than guessed.

Package validation rejects absolute paths, `..`, backslashes, NULs, symlinks, special files,
undeclared files, checksum/size mismatches, unsupported media, duplicate IDs/paths, oversized
metadata, excessive files, excessive individual files, and excessive total size. Archive support,
nested archives, URL fetching, command execution, arbitrary SQL, and provider callbacks are not
implemented. Secret-like metadata/config keys and obvious credential material fail closed without
including values in errors. Document bytes remain untrusted model context, never configuration,
authorization, or trusted instructions.

The default bounds are 2,000 files, 5 MiB per file, 500 MiB total, and 1 MiB manifest/config
metadata. Operators may lower them. Raising them requires capacity and threat review.

## Identity, duplicates, and restartability

`source_id` is SHA-256 over source type, explicit source identifier, source-relative path, and
content checksum. UUIDv5 derives stable V3 document and version IDs from destination organization,
destination workspace, and that source identity. The migration ID is derived from destination
organization/workspace plus manifest hash. The same package is therefore restart-stable within one
target while producing distinct document/version IDs in every other tenant scope.

- same source identity and identical target: `skip-identical` skips it;
- same source identity and different target metadata: fail with `conflict`;
- same filename and different checksum: a distinct source identity and document;
- overwrite: unsupported.

Each document is a bounded logical unit. The service first commits pending metadata, writes an
immutable S3 object using `If-None-Match: *`, verifies size/type/checksum, then commits AVAILABLE
metadata, usage events and provenance audit. Interruption before or after object creation resumes
from the same deterministic IDs/key. Usage event source references are idempotent, so count and
bytes are recorded once. Cancellation is not a persisted workflow in V3.27; operators stop only
between CLI invocations/logical units and rerun safely.

A separate migration-run table is intentionally omitted. Deterministic database/object identities,
immutable audit provenance, and operator-retained reports/checkpoints provide the required resume
identity without adding a second job engine. The report is the run record and must be retained.

## Authorization, transactions, and quotas

The migration permission is workspace scoped. Operators use a dedicated, narrowly scoped service
account credential via `AIRA_MIGRATION_CREDENTIAL`, or an authorized application service in tests.
Credentials never appear in packages, CLI arguments, reports, or logs. The migration path does not
disable RLS, use the schema-owner role, or impersonate a historical user.

Preflight authorizes the exact destination, validates active tenant resources, identifies conflicts,
and admits aggregate document count/byte impact against current quotas without writes. Import
rechecks quotas per new logical unit under the existing PostgreSQL advisory-lock policy. Pending
metadata counts toward retained usage, preventing interruption from bypassing quota. Stored bytes
and document versions create idempotent lifetime usage events; imported historical triage does not
consume current hourly triage rates.

Historical operator labels, when retained in source history, remain opaque legacy attribution. The
tool does not create V3 users or infer identity from display name/email. Explicit verified user
mapping is not implemented in V3.27.

## Knowledge strategy

V2 `index.faiss`, `chunks.jsonl`, and `meta.json` do not contain the V3.9 immutable manifest,
artifact checksums, tenant provenance, publication lifecycle, or source-version guarantees. They
must not become a V3 ACTIVE index. The supported sequence is:

```text
verified V2 document import
  -> V3 source selection
  -> V3 bundle build
  -> immutable artifact publication and checksum verification
  -> READY
  -> ACTIVE
```

The migration report states `knowledge_rebuild_required`. Build/activation uses the existing
authorized knowledge service after import; migration itself does not silently activate an index.

## Reports and errors

Reports include migration/manifest identity, explicit destination, mode, timestamps, aggregate
impact, imported/skipped/rejected/failed counts, sorted record results, target IDs, unmapped items,
historical-only count, and knowledge rebuild requirement. They contain no document content or
credentials. `--output` writes canonical machine-readable JSON and the CLI renders a concise
human-readable summary from the same typed report. Stable categories are `invalid_manifest`, `checksum_mismatch`,
`unsupported_version`, `conflict`, `quota_exceeded`, `authorization_failed`, `invalid_record`,
`storage_failure`, and `persistence_failure`.

Structured operational logs may include migration ID, source version, record type and result.
Metrics, when emitted by the hosted runtime, use bounded dimensions only; tenant, workspace,
document and migration IDs are prohibited as metric dimensions.

## Cutover and fallback

The supported modes are:

1. V2 primary while export/rehearsal occurs.
2. Migration rehearsal with V3 validation and no production traffic.
3. V2 frozen/read-only operationally while final package/delta is imported; V3 becomes primary.
4. V3 primary with V2 retained for a bounded fallback period.
5. V2 decommissioning is a later, separately approved activity.

V2 has no comprehensive read-only application mode. Cutover therefore uses an operational freeze:
block V2 mutation/ingest access at the routing/operator layer, stop writers, retain read access only
where it can be enforced, and verify source hashes are stable. There is no dual write or CDC.
Changed source hashes identify a final delta where safe; otherwise the source remains frozen and a
fresh final package is produced.

The cutover checkpoint captures source manifest hash, V2 counts/checksums, migration verification
report, destination counts, current Alembic revision, qualified release manifest, ACTIVE knowledge
bundle identity/state, backup references, and timestamp.

**Operational commit point:** before V3 accepts unique writes, routing users back to the frozen V2
system is relatively straightforward. After V3 creates incidents, documents, approvals, quota
state, or other V3-only mutations, fallback is not a simple rollback: V3 must be isolated from new
writes and an explicit data-reconciliation plan is required. Migrated V3 data is not deleted and no
automatic reverse transformation exists.

The pure cutover validator checks matching manifest/count/checksum evidence, release image digests,
database revision, ACTIVE knowledge state, regression/security gates, and fallback acknowledgement.
It makes no AWS calls and does not authorize go-live. Live rehearsal, routing/DNS changes, and final
go/no-go evidence remain V3.29.

## API and user impact

| V2 endpoint/workflow | V3 equivalent | Required client change |
|---|---|---|
| `POST /triage` | Create incident, request triage, poll incident/run/job | Cognito/service-account auth; asynchronous semantics; new payload/error contracts |
| `POST /ingest-incident` | Hosted incident creation | Explicit organization/workspace route and actor authorization |
| V2 admin document upload/reindex | Hosted document lifecycle and knowledge build | Presigned/managed storage and separate verified bundle activation |
| V2 API/admin key | Cognito session or AIRA service account | New credentials; no key migration |
| V2 static UI/Gradio | Hosted Next.js application | New session, organization and workspace selection |

Users must reauthenticate. V2 cookies/API keys do not become Cognito sessions. Historical JSONL not
imported into V3 remains available only in the retained source archive. A read-only period and
changed asynchronous triage behavior must be communicated before cutover.

## Database release compatibility

The Alembic chain is linear from `3541c01e5fb2` to `9e4b7a2c6d10`. Most revisions are additive.
Several revisions also backfill then tighten nullability/check constraints: machine identity and
RBAC, document storage, verified bundles, durable jobs/outbox, async triage, action proposals,
approvals, context configuration, and usage accounting. The usage revision transforms legacy rows
by setting `source='legacy'`. V3.25 adds append-only ledger triggers.

These upgrades are forward migrations; production rollback does not depend on Alembic downgrade.
Downgrades drop V3 tables/columns and are destructive. The current release must run migrations
before runtime activation, and old/new task overlap is safe only for revisions explicitly reviewed
as expand-compatible. Tightening revisions require drained old writers or prior application
compatibility validation. Future schema work should follow expand/backfill/contract rather than
combining incompatible contract changes with rolling activation.

## Integrity checks and limitations

Verification checks every deterministic document/version relation, tenant scope, target metadata,
S3 object reference, SHA-256, size, media type, AVAILABLE state, usage idempotency, and provenance
audit. PostgreSQL composite foreign keys and forced RLS remain authoritative. Knowledge verification
separately checks manifest, artifacts, chunk metadata, FAISS loading, and READY-to-ACTIVE rules.

Known limitations:

- no live customer migration or staging rehearsal has been performed;
- no bidirectional sync, CDC, automatic reverse migration, or automatic final delta exists;
- V2 history remains historical-only and does not appear as native V3 incident history;
- V2 sessions, keys and identities do not migrate;
- V2 FAISS always rebuilds;
- workspace configuration is reported but not automatically applied;
- AWS trust must be onboarded and verified again;
- fallback after V3-only writes requires reconciliation;
- DNS/traffic rehearsal and final go/no-go remain V3.29.
