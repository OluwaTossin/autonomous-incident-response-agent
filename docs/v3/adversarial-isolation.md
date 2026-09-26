# V3.28 adversarial tenant-isolation evidence

## Scope and limits

V3.28 exercises AIRA locally as a hostile but authenticated tenant, service account, machine
caller, or worker. It is automated adversarial evidence, not a penetration test, external audit,
compliance certification, or proof about a deployed environment. No live AWS or customer system
is a test target. V3.29 owns deployed production-readiness validation.

The deterministic fixture model contains Organizations A and B; Workspaces A1, A2, B1, and B2;
Owner, Admin, Operator, and Viewer users in both organizations; workspace-scoped service accounts
A1, A2, and B1; and trusted machine/worker actors.

## Threat and test matrix

| Boundary | Adversarial inputs | Enforced by | Evidence |
|---|---|---|---|
| Human authorization | cross-org/workspace IDs, stale membership/grant, role escalation | authoritative membership/grant lookup and permission matrix | exhaustive actor/role/permission matrix tests |
| Actor type | service/system actor presented for human-only operation | verified `ActorContext` kind and grantable permissions | actor-confusion and service-account denial tests |
| HTTP/BFF | nested foreign IDs, valid CSRF with foreign path, missing auth | backend authorization; session and CSRF are independent controls | route inventory and BFF adversarial tests |
| Pagination | malformed/modified cursor, cross-org/workspace replay | HMAC signature plus route tenant-scope binding | cursor codec and hosted API tests |
| PostgreSQL | missing/wrong tenant context, raw cross-tenant CRUD, ownership rewrite | transaction-local context, forced RLS, composite FKs | real PostgreSQL adversarial suite |
| Connection pool | commit/rollback followed by same backend reused for another tenant | `SET LOCAL` transaction scope | same-backend reuse tests |
| Async transport | forged job, dispatch, correlation, generation, and tenant IDs | authoritative PostgreSQL job/dispatch reload and workload grant | async transport adversarial tests |
| Denied mutations | viewer/foreign create and update attempts | authorization before UoW/storage/queue | no DB, audit, usage, S3, or queue side-effect assertions |
| Alert ingestion | payload tenant hints and wrong path scope | authenticated route plus configured integration identity | EventBridge forgery and no-side-effect tests |
| Documents/knowledge | foreign IDs/keys and colliding index UUIDs | authorized scope, immutable object metadata, verified manifests | document regressions and tenant-scoped cache tests |
| Action governance | foreign proposal/approval/intent links and non-human decisions | scope references, two-person rule, immutable hashes, composite FKs | action, approval, intent, and PostgreSQL tests |
| Usage/quota | cross-scope reads/writes and concurrent final slots | authorized UoW, RLS, tenant-scoped locks/counters | usage and concurrent quota tests |
| Migration | unauthorized destination and same source across tenants | ordinary authorization/RLS and tenant-scoped deterministic IDs | V3.27 unit and PostgreSQL regressions |
| Audit/observability | audit mutation and foreign content in telemetry | append-only DB controls, redaction, bounded metric dimensions | PostgreSQL and observability security tests |

The hosted route inventory asserts the expected human or machine authentication dependency for
every registered hosted route. The BFF inventory asserts server-mediated session use for every API
route and CSRF validation for mutations. It also fails if execution/remediation endpoints appear.

## Database evidence

The metadata-driven inventory fails when a tenant table lacks row-security enablement, forced RLS,
a policy, or required `USING`/`WITH CHECK` expressions. It also verifies that the runtime role does
not own tenant tables and has `NOBYPASSRLS`.

Real PostgreSQL attacks cover missing context, A-to-B reads, inserts, updates, deletes, tenant-ID
rewrites, composite foreign-key mismatches, and `SET row_security = off`. Pool tests force the same
backend connection through tenant A commit or rollback and tenant B reuse, verify transaction-local
settings are cleared, and verify tenant B cannot observe tenant A. Audit and usage append-only
controls remain in the full PostgreSQL suite.

## Findings and corrections

### Medium: unsigned, scope-free pagination cursors

- Attack path: modify a cursor timestamp/ID or replay a valid cursor under another organization or
  workspace.
- Affected boundary: hosted workspace, incident, and triage-run list pagination.
- Preconditions: authenticated access to a list endpoint and possession of any cursor.
- Impact: foreign rows remained protected by authorization/RLS, but a caller could influence scan
  position and a restricted workspace candidate ID could be exposed in a continuation token.
- Fix: HMAC-SHA256 cursor signatures, explicit cursor kind and tenant-scope binding, a dedicated
  hosted signing secret, and authorized-only workspace page construction.
- Regression: modified timestamp/ID, wrong kind, cross-organization, cross-workspace, malformed,
  and hidden-workspace pagination tests.

### Medium: FAISS runtime cache omitted tenant scope

- Attack path: two tenants publish independently verified bundles with the same index UUID.
- Affected boundary: hosted local FAISS bundle cache.
- Preconditions: colliding bundle UUIDs across workspaces on one worker host.
- Impact: manifest verification prevented serving an unverified foreign bundle, but cache entries
  collided and could evict or thrash one another.
- Fix: cache directories and locks now include organization, workspace, and index-version IDs.
- Regression: identical index UUIDs in two tenant scopes produce distinct verified cache entries.

No critical or high tenant-isolation defect was found in this phase. Both medium findings were
fixed and have deterministic regression coverage.

## Side effects and transport authority

Denied viewer and cross-tenant mutations assert more than an HTTP status: no unit of work enters,
no row or audit event is added, no usage counter changes, and no S3 or queue method is called.
Alert-ingestion rejection similarly leaves receipts, alarm state, incidents, runs, jobs,
dispatches, and audit events unchanged.

Forged queue envelopes cannot establish tenant authority. Tests vary job ID, dispatch ID,
correlation ID, tenant hints, and dispatch generation and assert that claim, handler, and completion
paths are not invoked. Durable PostgreSQL state and the configured workload grant remain the source
of truth.

## Release gate and residual risk

CI has explicit release-blocking adversarial backend, PostgreSQL/RLS, migration, and BFF steps in
addition to the full backend, PostgreSQL, hosted-web, V2, security, and Terraform jobs.

Residual validation belongs to V3.29: deployed secret population/rotation, ALB and Cognito behavior,
ECS connection-pool behavior under production load, live S3/KMS policy validation, multi-region AWS
delivery, and customer-role onboarding. These require controlled environment evidence and are not
substituted by local tests.
