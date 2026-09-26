# AIRA Version 3 execution plan

**Project:** Autonomous DevOps Incident Response Agent  
**Version:** 3 - hosted multi-user incident intelligence platform  
**Status:** Planned; no Version 3 application implementation has started

This document is the dependency-ordered source of truth for Version 3 delivery. It follows the checkbox-driven discipline of `docs/build-journey/execution-v1.md`, while making dependencies, validation, risks, and compatibility explicit for a multi-tenant hosted system.

## Version 3 objective

Evolve AIRA from the Version 2 self-hosted, single-operator BYOD product into a hosted platform that can securely receive alerts, collect authorized operational context, retrieve tenant-scoped knowledge, run evidence-grounded triage asynchronously, support operator review, and prepare immutable policy-approved execution intents.

```text
Version 2: manual upload -> manual triage

Version 3: alert -> automatic context collection -> retrieval -> triage
          -> evidence -> operator review -> approved execution intent
```

Version 3 preserves human authority and stops at deterministic connector preparation.
Version 4 owns actual controlled or autonomous remediation execution and is explicitly out
of scope.

## Scope

### In scope

- Cognito Authorization Code Flow with PKCE for humans, AIRA service accounts for external machines, and IAM/workload identity for internal services.
- Users, organizations, memberships, roles, workspaces, and tenant isolation.
- PostgreSQL system-of-record persistence using SQLAlchemy 2.x, Alembic, separated database roles, transaction-local tenant context, and RLS.
- S3 document storage and tenant-scoped versioned FAISS bundles.
- SQS/DLQ asynchronous incident triage.
- Authenticated, server-capable hosted Next.js ECS/Fargate service, independently deployable from the API.
- CloudWatch/EventBridge alert intake and least-privilege logs/metrics enrichment.
- Durable action proposals, approval gates, immutable execution intents, and deterministic
  connector preparation without provider mutation.
- Private hosted AWS application/data topology behind HTTPS with controlled NAT egress and selective VPC endpoints.
- Tenant-aware audit, observability, usage, quotas, security, CI/CD, and validation.
- Continued V2 self-hosted behavior through a separate composition root.

### Out of scope

- Autonomous consequential remediation or LLM-authorized infrastructure changes.
- pgvector in the initial Version 3 implementation.
- Custom password storage or authentication.
- Broad multi-cloud or every-vendor integration support.
- General-purpose workflow automation.
- Full billing, invoicing, subscriptions, or taxation.
- Silent use of customer data for model training.
- Replacing Version 2 self-hosted mode.

## Delivery principles

- [ ] Preserve V2 behavior until an explicit migration step changes a contract.
- [ ] Keep V1 and V2 reference worktrees read-only.
- [ ] Make tenant context explicit at API, service, repository, job, storage, retrieval, action, and telemetry boundaries.
- [ ] Add abstractions only where hosted and self-hosted implementations genuinely differ.
- [ ] Keep FAISS for the first hosted retrieval implementation.
- [ ] Treat SQS delivery as at least once and all side effects as idempotent.
- [ ] Design RLS with the first hosted schema; do not defer tenant isolation.
- [ ] Require deterministic policy and human approval for consequential actions.
- [ ] Explain every AWS resource through a runtime, security, durability, or operational requirement.
- [ ] Complete each phase with tests and documentation before depending on it.

## Milestone summary

| Phase | Milestone | Depends on | Primary evidence |
|------:|-----------|------------|------------------|
| V3.0 | Product boundary and decisions | Assessment | `docs/v3/` |
| V3.1 | Shared core boundaries | V3.0 | Characterization tests, composition design |
| V3.2-V3.5 | Hosted tenancy and identity foundation | V3.1 | Domain model, PostgreSQL, Cognito, RBAC |
| V3.6-V3.9 | Workspace knowledge plane | V3.3-V3.5 | Durable workspaces, S3 documents, versioned FAISS |
| V3.10-V3.12 | Async triage plane | V3.3, V3.8 | Job state, SQS worker, async APIs |
| V3.13-V3.15 | Hosted operator application | V3.4-V3.12 | Authenticated Next.js workflows and history |
| V3.16-V3.18 | CloudWatch automation | V3.6, V3.10-V3.12 | Onboarding, alert intake, context collection |
| V3.19-V3.21 | Controlled action plane | V3.5, V3.12 | Risk policy, approvals, connectors |
| V3.22-V3.25 | Hosted operations and security | Prior runtime phases | AWS, telemetry, quotas, hardening |
| V3.26-V3.29 | Delivery and release validation | All implementation phases | CI/CD, compatibility, isolation, readiness |

---

## V3.0 - Product boundary and architecture decisions

**Goal:** Establish the agreed product, trust, safety, and architecture constraints before implementation.

**Dependencies:** Repository assessment and Version 1/2 references.

**Checklist:**

- [x] Record the accepted hosted frontend runtime: separate containerized Next.js ECS/Fargate service, independently deployable and optionally sharing ALB routing with the API; retain V2 static S3 deployment and exclude Vercel/Amplify dependencies.
- [x] Record Cognito Authorization Code Flow with PKCE and Secure, HttpOnly server-mediated sessions; prohibit refresh tokens in `localStorage` and shared browser-bundle secrets.
- [x] Record human, `service_account`, and `system` actor types, with IAM/workload identity for internal services where applicable.
- [x] Record SQLAlchemy 2.x, Alembic, separated schema-owner/runtime roles, non-owner/non-`BYPASSRLS` application access, and `SET LOCAL`-style tenant context.
- [x] Record CloudWatch Alarm -> EventBridge -> authenticated cross-account AIRA EventBridge intake, with separate STS AssumeRole context collection and no long-lived customer keys.
- [x] Record initial NAT egress for external LLM access plus selective VPC endpoints; defer only environment-specific NAT redundancy to V3.22.
- [x] Record internal engineering SLOs, beginning with a 99.9% production API availability target plus async operational indicators.
- [ ] Review and approve `product-definition.md` and `architecture-decisions.md` as the implementation baseline.
- [ ] Track deferred implementation decisions in their owning phases: Cognito configuration details (V3.4), permission matrix (V3.5), CloudWatch multi-region mechanics (V3.16), NAT redundancy (V3.22), and measured SLO thresholds (V3.23/V3.29).
- [ ] Record explicit Version 3 non-goals and Version 4 boundary.
- [ ] Establish ADR change and approval process.

**Files/modules:** `docs/v3/*`; later ADRs may live under `docs/v3/decisions/`.

**Validation:** Architecture review against current FastAPI, LangGraph, FAISS, frontend, Terraform, and V2 workflows.

**Deliverable / definition of done:** Approved product and architecture baseline with the listed decisions closed; measurement- or implementation-dependent details are explicitly owned by later phases and are not architecture blockers.

**Risks:** Treating a deferred implementation detail as permission to reopen accepted boundaries, or implementing RBAC before V3.5 approves its permission matrix.

## V3.1 - Shared core boundaries

**Goal:** Isolate reusable triage behavior without changing V2 behavior.

**Dependencies:** V3.0.

**Status:** Complete in `ac20505` (`refactor: establish shared triage core for AIRA v3`).

**Checklist:**

- [x] Add characterization tests for incident normalization, graph output, evidence, policy, retrieval hits, audit metadata, CLI, REST, and Gradio paths.
- [x] Define only the runtime seams required by V3.1 (`TriagePipeline`, audit, and metrics); defer repository, document, index, job, and action contracts to their owning phases.
- [x] Separate pure triage execution from HTTP/JSONL/metrics orchestration in `run_full_triage`.
- [x] Define the explicit self-hosted composition root and an injected boundary for the later hosted root; prohibit scattered `hosted_mode` checks.
- [x] Preserve current command names and V2 response contracts.

**Files/modules:** Existing `app/agent/`, `app/api/triage_execution.py`, `app/rag/`; expected `app/core/`, `app/application/`, `app/composition/`; characterization tests.

**Validation:** Existing 89+ tests, CLI smoke, API contract tests, retrieval fixture comparison, V2 Compose smoke where available.

**Deliverable / definition of done:** Shared triage core can run through current V2 adapters with no intentional behavior change and accepts explicit dependencies needed by hosted code.

**Risks:** Premature generic abstractions or accidental changes to evidence and severity behavior.

## V3.2 - Hosted domain model

**Goal:** Define durable domain entities and lifecycle invariants independently of HTTP and database implementation.

**Dependencies:** V3.1.

**Status:** Complete in `08841f8` (`feat: add hosted domain model for AIRA v3`).

**Checklist:**

- [x] Define IDs and models for user, organization, membership, workspace, incident, triage run, evidence, document, index version, integration, job, action, approval, usage, and audit event.
- [x] Define incident and triage state transitions and immutable versus mutable fields.
- [x] Define correlation between legacy `triage_id` and hosted `triage_run_id`.
- [x] Define data classification, retention markers, timestamps, and actor attribution.
- [x] Add invariant and state-transition unit tests.

**Files/modules:** Expected `app/domain/`, `app/application/contracts/`, domain tests; existing `app/models/incident.py` and `triage.py` adapted or reused.

**Validation:** Model tests, transition-table tests, serialization/versioning tests, architecture review.

**Deliverable / definition of done:** Framework-independent domain contract supports later persistence, jobs, UI, integrations, and actions without tenant ambiguity.

**Risks:** Encoding provider/database details in domain models or allowing duplicate sources of lifecycle truth.

## V3.3 - PostgreSQL, migrations, and RLS

**Goal:** Establish PostgreSQL as the hosted system of record with tenant isolation designed from the first schema.

**Dependencies:** V3.2.

**Status:** Complete in `83cd522` (`feat: add PostgreSQL persistence and tenant RLS`).

**Checklist:**

- [x] Configure SQLAlchemy 2.x and Alembic; document transaction and session conventions.
- [x] Create initial schemas, constraints, indexes, timestamps, and migration history.
- [x] Add `organization_id`/`workspace_id` to tenant-owned rows with organization/workspace consistency constraints.
- [x] Create separate migration/schema-owner and application runtime roles; ensure the application role owns no tenant table and lacks `BYPASSRLS`.
- [x] Implement `SET LOCAL`-style transaction-local organization/workspace context consumed by RLS policies.
- [x] Add repositories and explicit unit-of-work boundaries.
- [x] Add local hosted-development PostgreSQL without changing default V2 Compose behavior.
- [x] Define backup, restore, retention, and migration rollback expectations.

**Files/modules:** Expected `app/db/`, `app/repositories/postgres/`, `migrations/`, hosted Compose overlay, database tests.

**Validation:** Fresh Alembic migration, upgrade/downgrade policy test, role/ownership inspection, constraint tests, mandatory pooled-connection tenant-context reset tests, cross-tenant RLS denial tests, backup/restore rehearsal design.

**Deliverable / definition of done:** A clean database can be migrated and all tenant tables deny unauthorized cross-tenant access through both repositories and RLS.

**Risks:** RLS bypass by migration/owner roles, pooled tenant context leakage, long transactions around LLM calls.

## V3.4 - Identity and ActorContext

**Goal:** Authenticate human and machine principals and provide verified request-scoped actor identity.

**Dependencies:** V3.3.

**Status:** Complete in `1d52c67` (`feat: add hosted identity and actor context`).

**Checklist:**

- [x] Configure the hosted API's Cognito-compatible issuer, audience/client ID, token use, algorithms, clock handling, and JWKS cache; document PKCE, callback, MFA, and token/session expectations for V3.13.
- [x] Define the V3.13 hosted Next.js server-mediated session contract using Secure, HttpOnly cookies; defer its browser callback, refresh, logout, CSRF, and route-protection implementation to V3.13.
- [x] Implement JWT verification with fail-closed key rotation and clock handling.
- [x] Map provider subjects to durable users without trusting role claims as the authorization source.
- [x] Define `ActorContext` variants for human, `service_account`, and `system` principals.
- [x] Implement service-account identity, credential rotation, revocation, and audit attribution without assigning RBAC scopes before V3.5.
- [x] Define trusted system actors and the future IAM/workload-identity boundary without adding AWS infrastructure.
- [x] Retain shared-key security only in the self-hosted composition.

**Files/modules:** Expected `app/auth/`, hosted FastAPI dependencies/middleware, identity repositories, Cognito configuration, auth tests; adapt `app/api/security.py`.

**Validation:** Local valid/invalid/expired/not-yet-valid/wrong-audience token tests, JWKS rotation and failure tests, durable identity mapping, disabled user, service-account lifecycle, trusted system actor construction, authentication-versus-RLS separation, and V2 shared-key regression tests. PKCE callback/state/nonce, cookie, CSRF, refresh, logout, and browser-bundle tests belong to V3.13.

**Deliverable / definition of done:** Every protected hosted request has a verified `ActorContext`; no hosted route treats shared deployment keys as user identity.

**Risks:** Token leakage, stale membership, insecure browser storage, confusing human and service-account authorization.

## V3.5 - Organizations, memberships, and RBAC

**Goal:** Enforce Owner/Admin/Operator/Viewer permissions across organization and workspace operations.

**Dependencies:** V3.3, V3.4.

**Checklist:**

- [ ] Produce and approve the explicit Owner/Admin/Operator/Viewer permission matrix before implementing RBAC policies; do not infer fine-grained permissions from role names.
- [ ] Implement RBAC only after the matrix is approved.
- [ ] Implement organization creation, membership invitation/acceptance, role change, suspension, and removal.
- [ ] Protect last-owner and ownership-transfer invariants.
- [ ] Implement workspace restrictions/grants without weakening organization membership checks.
- [ ] Centralize authorization policies in application services/dependencies.
- [ ] Emit durable audit events for membership and role changes.

**Files/modules:** Expected `app/application/organizations/`, `app/authorization/`, hosted routes/schemas, repository methods, RBAC tests.

**Validation:** Permission matrix tests for every role, last-owner tests, suspended actor tests, workspace restriction tests, cross-organization denial tests.

**Deliverable / definition of done:** The permission matrix is approved first; all subsequent organization/workspace operations are authorized by centralized policy and attributable to an actor.

**Risks:** Role-name checks scattered through handlers and accidental organization-wide access from workspace grants.

## V3.6 - Workspace persistence

**Goal:** Replace hosted filesystem-selected workspaces with durable authorized workspace records and settings.

**Dependencies:** V3.3, V3.5.

**Status:** Complete in `86b38ab` (`feat: add hosted workspace persistence`).

**Checklist:**

- [x] Implement workspace create/read/update/archive lifecycle.
- [x] Persist allowlisted workspace configuration with schema/version and actor audit.
- [x] Pass workspace context explicitly to services; remove hosted dependence on cached `WORKSPACE_ID`.
- [x] Preserve `app/workspace/paths.py` for self-hosted composition.
- [x] Define archive/deletion and dependent-resource behavior.

**Files/modules:** Expected workspace services/repositories/routes; adapt `app/api/operator_routes.py`, `app/config/settings.py`, and operator configuration UI contract.

**Validation:** Workspace lifecycle, authorization, optimistic concurrency, settings validation, archive behavior, and V2 path regression tests.

**Deliverable / definition of done:** Hosted workspace state is database-backed and request-scoped; V2 still resolves filesystem workspaces as before.

**Risks:** Mixing deployment settings with tenant settings and global cache invalidation affecting other workspaces.

## V3.7 - S3 document layer

**Goal:** Store hosted workspace source documents durably and securely in S3.

**Dependencies:** V3.5, V3.6.

**Checklist:**

- [ ] Define document lifecycle and immutable opaque object-key format.
- [ ] Implement storage port, S3 adapter, and V2 filesystem adapter.
- [ ] Add authorized short-lived presigned upload/download flows.
- [ ] Finalize uploads only after checksum, size, type, and object verification.
- [ ] Persist metadata, versions, categories, actor, and processing state in PostgreSQL.
- [ ] Add SSE-KMS, bucket policy, access logging, lifecycle, and orphan-cleanup requirements.
- [ ] Provide malware/DLP hook points without claiming those controls are implemented until they are.

**Files/modules:** Expected `app/documents/`, storage adapters, document routes/schemas, repository migrations, tests; replace hosted path in `app/api/admin_routes.py`.

**Validation:** Presigned authorization, cross-tenant denial, checksum mismatch, oversize/type rejection, expired URL, orphan cleanup, encryption-policy tests.

**Deliverable / definition of done:** Authorized users can upload/list/download/delete workspace documents without API-local persistence or predictable authorization shortcuts.

**Risks:** Bearer URL leakage, incomplete uploads, orphaned objects, content threats, and database/S3 consistency.

## V3.8 - Tenant-aware knowledge/index abstraction

**Goal:** Make corpus loading, index building, and retrieval explicit to a workspace without changing FAISS behavior.

**Dependencies:** V3.1, V3.6, V3.7.

**Status:** Complete in `80194ea` (`feat: add tenant-aware knowledge retrieval`).

**Checklist:**

- [x] Define narrow `KnowledgeSource`, `KnowledgeIndex`, and `Retriever` contracts using current retrieval-hit semantics.
- [x] Remove hosted reliance on global `rag_index_dir()` and `corpus_data_root()`.
- [x] Stage authorized document versions for indexing.
- [x] Preserve decision-document behavior only through an explicit system corpus policy, not unconditional tenant mixing.
- [x] Keep local filesystem FAISS adapter for V2.

**Files/modules:** Adapt `app/rag/config.py`, `loader.py`, `index_store.py`, `retrieve.py`, `cli.py`; expected hosted knowledge services/adapters.

**Validation:** Golden retrieval comparisons, explicit workspace tests, no cross-tenant source leakage, empty/demo/user V2 regressions.

**Deliverable / definition of done:** The same triage core retrieves through an explicit workspace index handle in hosted mode and existing paths in V2 mode.

**Risks:** Over-generalizing retrieval or silently changing rankings, source paths, and evidence citations.

## V3.9 - Versioned FAISS publication and caching

**Goal:** Build, publish, activate, load, and roll back immutable tenant-scoped FAISS bundles.

**Dependencies:** V3.7, V3.8.

**Checklist:**

- [ ] Define bundle and manifest versions, embedding/chunking metadata, document revision, checksums, and compatibility rules.
- [ ] Build into a unique staging location and upload immutable artifacts to S3.
- [ ] Verify manifest/checksums before atomically activating an index version in PostgreSQL.
- [ ] Add checksum-keyed bounded worker cache with per-bundle download locking and eviction.
- [ ] Support rollback and safe garbage collection of inactive bundles.
- [ ] Record build status, failure, source revision, and usage.

**Files/modules:** Expected index-version models/repositories/services, FAISS bundle builder/loader/cache, index job tests, S3/KMS policies later in Terraform.

**Validation:** Concurrent build/load, corrupt bundle rejection, activation race, rollback, cache eviction, cold/warm retrieval, and tenant-isolation tests.

**Deliverable / definition of done:** Every hosted retrieval resolves one verified active workspace bundle; replicas can cache it without shared mutable state.

**Risks:** Cold-start latency, disk exhaustion, concurrent cache corruption, and deleting an in-use bundle.

## V3.10 - Async job model

**Goal:** Define durable, idempotent triage and supporting job lifecycles before adding SQS.

**Dependencies:** V3.2, V3.3.

**Status:** Complete in `bd72e0d` (`feat: add durable asynchronous job model`).

**Checklist:**

- [x] Implement `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, and `CANCELLED` transitions.
- [x] Define job type/version, attempts, idempotency key, lease, timestamps, error classification, and result references.
- [x] Define cancellation and terminal-state invariants.
- [x] Add transactional job creation with incident/triage records.
- [x] Choose and implement an outbox or equivalent reliable publish boundary.

**Files/modules:** Expected job domain/application/repository modules, outbox tables/services, migrations, state-machine tests.

**Validation:** Transition tests, duplicate request tests, concurrent claim tests, publish-failure recovery, cancellation race tests.

**Deliverable / definition of done:** PostgreSQL represents one authoritative async lifecycle and can recover unpublished work without duplicate domain effects.

**Risks:** Database/SQS dual-write loss, ambiguous retries, and cancellation that only changes display state.

## V3.11 - SQS worker architecture

**Goal:** Execute durable triage jobs in a separately deployable worker using SQS and DLQ.

**Dependencies:** V3.8-V3.10.

**Status:** Complete in `d7a481f` (`feat: add SQS worker transport`).

**Checklist:**

- [x] Implement queue publisher and versioned tenant-qualified message envelope.
- [x] Implement worker entrypoint, claim/lease, heartbeat/visibility extension, graceful shutdown, and concurrency limits.
- [x] Load actor/workspace/incident/index context from authoritative IDs, not message payload assertions.
- [x] Make result writes, events, usage, and later actions idempotent.
- [x] Classify retryable versus terminal failures and configure DLQ redrive behavior.
- [x] Add replay tooling with authorization and audit.

**Files/modules:** Expected `app/jobs/sqs/`, `app/worker/`, worker container command, local queue emulator/test harness if justified, worker tests.

**Validation:** Duplicate delivery, worker crash, visibility expiry, poison job, DLQ, replay, shutdown, and concurrent worker tests.

**Deliverable / definition of done:** Jobs survive API/worker restarts, retry predictably, and produce at most one logical terminal result.

**Risks:** Hidden non-idempotent effects, excessive LLM retries, stale index versions, and runaway concurrency/cost.

## V3.12 - Async incident and triage APIs

**Goal:** Expose durable incident submission, triage creation, status, cancellation, result, evidence, and feedback APIs.

**Dependencies:** V3.5, V3.10, V3.11.

**Status:** Complete in `41e217e` (`feat: add hosted incident and async triage APIs`).

**Checklist:**

- [x] Add authorized incident create/list/detail endpoints.
- [x] Add idempotent triage-run creation returning `202` and stable IDs.
- [x] Add status/result/evidence endpoints and safe polling semantics.
- [x] Add cancellation and feedback linked to durable runs.
- [x] Define error schema, pagination, filtering, API versioning, and OpenAPI examples.
- [x] Preserve V2 synchronous `/triage` in the self-hosted composition.

**Files/modules:** Hosted FastAPI routers/schemas/services, API contract tests; adapt `app/api/main.py` and `triage_execution.py` through composition.

**Validation:** Auth/RBAC, idempotency, pagination, lifecycle, cancellation, cross-tenant denial, OpenAPI snapshot, V2 endpoint regression.

**Deliverable / definition of done:** Hosted clients can manage the full async triage lifecycle without filesystem or process-memory state.

**Risks:** Polling load, exposing internal errors or sensitive evidence, and accidental synchronous compatibility breakage.

## V3.13 - Hosted Next.js application

**Goal:** Establish a server-capable authenticated hosted frontend while retaining the V2 static frontend.

**Dependencies:** V3.4, V3.5, V3.12.

**Status:** Complete in `942ce57` (`feat: add hosted web app and browser authentication`).

**Checklist:**

- [x] Define separate hosted and self-hosted build/composition paths.
- [x] Containerize the server-capable hosted Next.js runtime as a distinct ECS/Fargate service; retain V2 static Next.js/S3 output.
- [x] Implement Cognito Authorization Code Flow with PKCE, Secure/HttpOnly cookie session, refresh, logout, and route protection.
- [x] Add CSRF, security headers, server-side API client, and no-store handling for tenant data.
- [x] Remove hosted dependence on `NEXT_PUBLIC_TRIAGE_API_KEY` and browser admin secrets.
- [x] Define health checks and ALB routing that may share the API ALB while preserving independent deployment and scaling.
- [x] Keep Vercel and Amplify out of the hosted dependency set.
- [x] Reuse presentational components without coupling hosted state to V2 static APIs.

**Files/modules:** `frontend/` hosted app/session/API modules or clearly separated hosted frontend package; hosted frontend Dockerfile/runtime; current static build retained; frontend tests and CI; Terraform wiring in V3.22.

**Validation:** Session fixation/expiry/logout, CSRF, protected routes, no secrets in bundles, tenant cache isolation, both frontend builds.

**Deliverable / definition of done:** The authenticated hosted shell runs as its own containerized server runtime without public shared secrets, and the V2 static export remains buildable and usable.

**Risks:** Token leakage, cached cross-tenant pages, unclear two-mode build boundaries, and duplicated UI code.

## V3.14 - Organization and workspace UX

**Goal:** Let authorized users select and administer organizations, memberships, and workspaces.

**Dependencies:** V3.5, V3.6, V3.13.

**Status:** Complete in `fca0d34` (`feat: add organization and workspace experience`).

**Checklist:**

- [x] Add organization/workspace switcher with stable tenant-aware routes.
- [x] Show authoritative membership role and effective permissions; keep organization provisioning, invitations, and member administration deferred until a secure product workflow is designed.
- [x] Add permission-aware workspace creation, details, allowlisted settings, optimistic concurrency, and archive UX; keep integration setup in V3.16 and later.
- [x] Handle revoked access and stale sessions without leaking prior tenant data.
- [x] Display authorization errors distinctly from missing resources.

**Files/modules:** Hosted Next.js organization/workspace routes, components, server actions/API clients; corresponding API endpoints/tests.

**Validation:** Role-based UI tests, switcher isolation, revoked membership, deep links, empty/loading/error states, accessibility.

**Deliverable / definition of done:** Users can navigate only organizations/workspaces authorized by backend policy; UI hiding is never the sole control.

**Risks:** Client cache retaining previous workspace data and inconsistent role messaging.

## V3.15 - Incident and triage history

**Goal:** Provide durable incident investigation and triage-run history.

**Dependencies:** V3.12-V3.14.

**Status:** Complete in `aeff537` (`feat: add incident history and triage investigation`).

**Checklist:**

- [x] Add incident list/detail, triage progress/result, evidence, timeline, feedback, and retry views.
- [x] Preserve severity, confidence, actions, evidence grouping, and correlation presentation from V2.
- [x] Add pagination/filtering without unbounded queries.
- [x] Show terminal failures and operator-safe diagnostics.
- [x] Keep exports/downloads unavailable until an authorized and audited flow is implemented.

**Files/modules:** Hosted incident/triage frontend routes; query APIs/repositories; reuse V2 display components where suitable.

**Validation:** Async UI tests, cross-tenant denial, pagination, retries, evidence rendering, sensitive error redaction, accessibility.

**Deliverable / definition of done:** Operators can follow an incident from submission through durable triage and feedback without reading JSONL or worker logs.

**Risks:** Large evidence payloads, expensive history queries, and accidental sensitive-data exposure.

## V3.16 - AWS integration onboarding and verification

**Goal:** Securely connect a workspace to one or more customer AWS accounts/regions.

**Dependencies:** V3.5-V3.7, V3.13-V3.14.

**Status:** Complete in `2796437` (`feat: add AWS integration onboarding`).

**Checklist:**

- [x] Define workspace-scoped AWS integration records, AIRA-generated external IDs, role ARNs, explicit regions, lifecycle state, and optimistic configuration versions.
- [x] Implement short-lived STS AssumeRole trust using a customer-managed least-privilege AIRA read role and no long-lived customer keys.
- [x] Verify caller identity and bounded CloudWatch alarm, metric, and log-read capabilities in each configured region before marking an integration ready.
- [x] Add safe permission diagnostics, retry, verification invalidation, disable, durable audit history, authorization, and forced-RLS isolation.
- [x] Add hosted APIs, BFF routes, and onboarding UI with copyable trust/read-policy artifacts and explicit customer actions.
- [x] Keep EventBridge and CloudWatch alarm delivery in V3.17 and operational Logs/Metrics enrichment in V3.18.

**Files/modules:** AWS integration domain/application model, `app/integrations/aws.py`, integration routes/services/repositories, migration, hosted UI/BFF, documentation, and tests.

**Validation:** Generated external ID, denied permission, wrong account/role/region, identity mismatch, capability failures, disabled integration, stale verification, authorization/RLS, API/BFF/UI, and V2 regression coverage using injected AWS clients only.

**Deliverable / definition of done:** An Owner/Admin can configure and verify a constrained AssumeRole integration for supported AWS accounts/regions using documented permissions; no alert delivery or incident enrichment is claimed.

**Risks:** Confused-deputy vulnerabilities, overly broad IAM, regional complexity, and onboarding support burden.

## V3.17 - EventBridge / CloudWatch alarm delivery

**Status:** Complete in `168de1d` (`feat: add CloudWatch alert ingestion`).

**Goal:** Convert authenticated cross-account EventBridge deliveries originating from CloudWatch Alarms into deduplicated workspace incidents and triage jobs.

**Dependencies:** V3.10-V3.12, V3.16.

**Checklist:**

- [x] Authenticate inbound delivery and resolve integration/workspace without trusting body tenant IDs.
- [x] Define canonical alert envelope and provider payload retention/redaction.
- [x] Implement normalization, deduplication/idempotency, replay handling, and incident creation.
- [x] Queue triage and expose delivery health; CloudWatch Logs/Metrics enrichment remains V3.18.
- [x] Preserve manual incident submission as a separate source adapter.

**Files/modules:** CloudWatch/EventBridge ingress adapter, canonical alert models, ingestion service/routes, deduplication persistence, tests.

**Validation:** Valid/forged/replayed events, duplicate state changes, malformed payloads, disabled integration, tenant mapping, burst/load tests.

**Deliverable / definition of done:** A supported CloudWatch alert creates exactly one logical incident and queued triage in the authorized workspace.

**Risks:** Duplicate alerts, forged delivery, alert storms, and retaining excessive raw provider data.

## V3.18 - CloudWatch Logs / Metrics enrichment

**Status:** Complete in `0ad424e` (`feat: add CloudWatch context enrichment`).

**Goal:** Collect bounded, relevant CloudWatch context before triage using the authorized integration role.

**Dependencies:** V3.9, V3.11, V3.16, V3.17.

**Checklist:**

- [x] Define enrichment plan from alert metadata and workspace connector configuration.
- [x] Query only allowlisted log groups, metric namespaces, time windows, and limits.
- [x] Persist provenance, safe query metadata, truncation, collection status, and bounded collection diagnostics.
- [x] Redact configured sensitive patterns before persistence, LLM use, and logs.
- [x] Handle partial collection failure without losing the incident.
- [x] Feed collected context through the existing incident/triage evidence contract.

**Files/modules:** CloudWatch Logs/Metrics collectors, enrichment jobs/services, evidence persistence, redaction and quota modules, tests.

**Validation:** Least-privilege denial, pagination, timeout, throttling, truncation, redaction, partial failure, cost-bound tests.

**Deliverable / definition of done:** Automatic triage includes attributable bounded context and clearly reports unavailable sources.

**Risks:** CloudWatch query cost, sensitive logs, slow context collection, prompt size, and misleading incomplete context.

## V3.19 - Action model

**Status:** Complete in `adca5be` (`feat: add controlled action proposals`).

**Goal:** Represent recommended and future-executable follow-up actions independently of LLM output without approving or executing them.

**Dependencies:** V3.2, V3.3, V3.12.

**Checklist:**

- [x] Define allowlisted action types, bounded targets and parameters, source recommendation provenance, risk, lifecycle, idempotency, and actor fields.
- [x] Define deterministic risk, reversibility, and review-eligibility policy without approval or execution semantics.
- [x] Validate type-specific parameters and trusted target authority before proposal creation.
- [x] Persist policy decisions and immutable action history.
- [x] Ensure LLM content cannot set authorization, risk, approval, or bypass policy.

**Files/modules:** Expected action domain/policy/services/repositories, migrations, schemas, tests.

**Validation:** Risk-policy table tests, hostile LLM output tests, invalid target tests, duplicate proposal tests, audit tests.

**Deliverable / definition of done:** Every executable action is a validated durable proposal with deterministic risk and authorization requirements.

**Risks:** Incomplete action taxonomy, policy bypass through connector parameters, and stale incident context.

## V3.20 - Human approval workflow

**Status:** Complete in `d014a64` (`feat: add human approval workflow`).

**Goal:** Require accountable approval before consequential action execution.

**Dependencies:** V3.5, V3.19.

**Checklist:**

- [x] Implement approval request, approve, reject, expire, cancel, and revalidation transitions.
- [x] Define which roles may approve and prevent self-approval where policy requires.
- [x] Bind approval to an immutable action version and current target context.
- [x] Add approval APIs, proposal detail/history UI, and durable audit.
- [x] Keep immutable intent preparation and deterministic connector validation in V3.21;
  defer actual execution to Version 4.

**Files/modules:** Approval domain/services/routes/repositories, hosted approval UI, audit/observer hooks, tests.

**Validation:** Unauthorized/self/stale/expired/double approvals, action mutation, revocation, concurrent decisions, audit completeness.

**Deliverable / definition of done:** No consequential action can reach execution without a valid policy-compliant approval tied to that exact action.

**Risks:** Approval fatigue, race conditions, stale approvals, and role changes during pending approval.

## V3.21 - Immutable execution intents and connector preparation

**Status:** Complete in `9b5a03e` (`feat: add immutable execution intents`).

**Goal:** Freeze one exact approved action into an immutable execution intent and prepare
its allowlisted connector operation deterministically without executing it.

**Dependencies:** V3.3, V3.5, V3.19, V3.20.

**Checklist:**

- [x] Bind each intent to the exact proposal, human approval, tenant, target, typed
  parameters, policy version, and canonical intent hash.
- [x] Enforce one race-safe durable intent per approval and immutable execution-defining
  fields with forced RLS and composite tenant foreign keys.
- [x] Add a static allowlisted connector/operation registry with deterministic local
  validation and no LLM, dynamic import, generic HTTP, shell, or arbitrary provider input.
- [x] Preserve fail-closed AWS target authority and support only the justified internal
  acknowledge-incident prepared operation.
- [x] Add bounded preparation/intent lifetimes, invalidation, cancellation, audit,
  observability hooks, API/BFF inspection, and explicit not-executed operator UX.

**Files/modules:** Execution-intent domain/application service, deterministic connector
registry, PostgreSQL migration/repository, hosted API/BFF/UI, audit/observer hooks, tests,
and `docs/v3/execution-intents.md`.

**Validation:** Exact approval/proposal binding, canonical hashing, concurrent idempotency,
immutability, terminal-state protection, target-authority rejection, authorization/RLS,
API/BFF/CSRF, no-execution routes, UI wording, V2 regressions, and production builds.

**Deliverable / definition of done:** An authorized operator can create and inspect one
immutable, bounded-lifetime, connector-validated intent for an exact approved action, while
no provider mutation or execution endpoint exists.

**Risks:** Stale authorization, target drift, accidental intent mutation, overbroad future
connector mappings, and confusing preparation with execution.

## V3.22 - Hosted AWS infrastructure and runtime wiring

**Goal:** Provision and wire the minimum secure AWS platform required by implemented Version
3 runtime components without activating remediation execution.

**Dependencies:** Runtime requirements from V3.3-V3.21 and approved infrastructure ADRs.

**Status:** Complete in `0152734` (`feat: add hosted AWS infrastructure and runtime wiring`).
V3.22 infrastructure/runtime code complete. Terraform fmt/validate passed. Plan was not
generated because the configured S3 backends require initialization. No Terraform apply or
live AWS mutation was performed. Live deployment validation remains deferred.

**Checklist:**

- [x] Add public ALB subnets and private application/data subnets with deliberate routing.
- [x] Add ACM HTTPS listener and HTTP redirect; define DNS ownership.
- [x] Place separate hosted frontend, API, and worker ECS services in private subnets without public IPs, with exposure only through required HTTPS ALB routes.
- [x] Add RDS PostgreSQL, subnet group, encryption, backups, deletion protection, monitoring, and pooling/proxy decision.
- [x] Add encrypted SQS/DLQ, S3 document/index buckets, KMS keys, Secrets Manager, and least-privilege IAM.
- [x] Add controlled NAT internet egress for external LLM access.
- [x] Add VPC endpoints selectively for AWS-native services where measured cost, security, or availability justifies them.
- [x] Decide dev/prod NAT gateway redundancy using the accepted availability target and measured cost; record the result as an implementation decision.
- [x] Add autoscaling, deployment health, alarms, outputs, and environment separation.
- [x] Keep Terraform plan/apply approval and remote-state controls.

**Files/modules:** Extend/version `infra/terraform/modules/` and `envs/dev|prod`; deployment docs/scripts/workflows.

**Validation:** `terraform fmt`, init/validate, reviewed plans, policy/security scans, HTTPS frontend/API routing, private-task reachability, NAT LLM egress, endpoint routing, secret access, migration task, backup/restore and failure drills. No apply until separately approved.

**Deliverable / definition of done:** Reviewed Terraform can create a private, encrypted, HTTPS-hosted platform containing only resources required by implemented services.

**Risks:** NAT cost, IAM/KMS mistakes, destructive migrations, RDS recovery gaps, and dev/prod drift.

## V3.23 - Tenant-aware observability

**Goal:** Correlate hosted activity across API, queues, workers, retrieval, integrations, and actions without high-cardinality metrics.

**Dependencies:** V3.11, V3.12, V3.17-V3.22.

**Status:** Complete in `89b2fde` (`feat: add hosted observability and SLOs`).
Structured logging, correlation, bounded metrics, tracing, dashboards, alarms, runbooks,
and internal engineering SLO definitions are complete. Terraform fmt/validate passed. A
Terraform plan was not generated because the configured S3 backends require
initialization. No Terraform apply or live AWS mutation was performed.

**Checklist:**

- [x] Define structured log and trace schemas carrying organization, workspace, actor, incident, and triage-run IDs.
- [x] Propagate correlation through HTTP and SQS envelopes.
- [x] Add distributed tracing and redact payloads/secrets.
- [x] Keep authoritative audit in PostgreSQL.
- [x] Use only bounded metric dimensions: environment, operation, status, severity, plan, connector type.
- [x] Define internal engineering SLOs rather than a public commercial SLA, beginning with 99.9% production API availability.
- [x] Add queue age, triage success rate, p95 time-to-triage, ingestion success, and worker failure rate indicators.
- [x] Add dashboards, alarms, queue/DLQ, worker, database, integration, and action signals supporting those SLOs.

**Files/modules:** Telemetry middleware/context, worker/integration instrumentation, audit repository, Terraform monitoring, dashboards/runbooks, tests.

**Validation:** End-to-end trace, correlation search, redaction tests, metric-cardinality review, alarm tests, audit/log consistency sampling.

**Deliverable / definition of done:** One incident can be investigated end to end by correlation IDs; metrics remain bounded; the 99.9% API target and async indicators have measurable definitions and initial thresholds.

**Risks:** Sensitive data in telemetry, missing async context, metric cost, and confusing audit with logs.

## V3.24 - Usage and quotas

**Goal:** Measure and constrain platform consumption without implementing billing.

**Dependencies:** V3.3, V3.9, V3.11, V3.18, V3.21, V3.23.

**Status:** Complete in `fb40a13` (`feat: add usage accounting and tenant quotas`).
Operational usage accounting, tenant quota admission, summary API/UI, bounded quota
telemetry, and deployment-owned defaults are complete. Billing remains explicitly out of
scope. Provider token usage is recorded only when authoritative metadata is available;
knowledge-bundle byte accounting remains deferred until publication exposes authoritative
size metadata. No Terraform apply or live AWS mutation was performed.

**Checklist:**

- [x] Define typed usage events for triage runs, authoritative LLM tokens, document bytes, index builds, enrichment context, and connector deliveries.
- [x] Persist idempotent usage ledger entries and bounded aggregates.
- [x] Define deployment defaults plus versioned organization/workspace quota policies without subscription-plan semantics.
- [x] Enforce limits before expensive work and expose clear retry/upgrade-independent errors.
- [x] Add authorized usage summary API/UI, bounded quota telemetry, and an operator runbook.
- [x] Explicitly exclude invoicing and payment processing.

**Files/modules:** Usage domain/repositories/services, quota policy, worker hooks, APIs/UI, telemetry, migrations, tests.

**Validation:** Duplicate-event idempotency, concurrent quota checks, rollover, delayed events, over-limit behavior, tenant isolation.

**Deliverable / definition of done:** Operators can view attributable usage and the platform can prevent configured resource abuse predictably.

**Risks:** Race conditions, inaccurate token/provider reporting, quota bypass, and accidental billing semantics.

## V3.25 - Security hardening

**Goal:** Validate and strengthen security controls accumulated throughout Version 3.

**Dependencies:** V3.3-V3.24.

**Status:** Complete in `5a407be` (`feat: harden hosted platform security`).
The hosted threat model, trust boundaries, security controls, forced-RLS inventory,
SSRF protections, process-specific IAM, runtime/container hardening, reviewed dependency
remediation, local security scans, release gates, and incident runbook are complete. No
unresolved critical/high release-blocking finding remains. External penetration testing,
live deployment validation, destructive tenant-erasure verification, WAF, and other
documented production controls remain later release-readiness gates. No Terraform apply or
live AWS mutation was performed.

**Checklist:**

- [x] Update the threat model and data-flow diagram for identity, tenancy, S3, SQS, RDS, integrations, and actions.
- [x] Review authorization, RLS, IAM, KMS, presigned URLs, SSRF, CSRF, CORS, headers, input limits, and secret handling.
- [x] Add dependency, container, secret, SAST, and IaC scanning commands plus a reviewed patch policy; defer CI enforcement to V3.26.
- [x] Define data classification, retention, deletion, redaction, and exceptional support-access boundaries; keep tenant-wide export and organization erasure fail-closed pending release-readiness design and destructive verification.
- [x] Review abuse controls and preserve bounded inputs, context collection, and tenant quotas; document WAF and a dedicated distributed login limiter as production residuals.
- [x] Conduct the local/static security review and close release-blocking findings; explicitly defer external penetration testing and live-environment validation to release readiness.

**Files/modules:** Security docs/tests/middleware/policies, CI scans, Terraform controls, incident-response runbooks.

**Validation:** Threat-based test suite, tenant attacks, authorization fuzzing, SSRF/CSRF tests, secret scans, container/IaC scans, deletion verification.

**Deliverable / definition of done:** Documented threat model and no unresolved critical/high release-blocking security finding.

**Risks:** Treating this phase as the first time security is considered; earlier phases must include their own security tests.

## V3.26 - CI/CD

**Goal:** Build, test, migrate, scan, and deploy hosted and self-hosted compositions reproducibly.

**Dependencies:** V3.22-V3.25.

**Status:** Complete in `ea1dbc9` (`feat: add hosted CI/CD and deployment automation`).
Credential-free pull-request CI and hosted release qualification, immutable build-once image
promotion, GitHub OIDC-based development and production deployment workflows, protected production
environment approval, Terraform destructive-change guards, migration-before-runtime-activation
ordering, ECS stability and health checks, release manifests, rollback, and the V3.25 security gates
are implemented. No Terraform apply, ECR push, ECS task execution, live AWS mutation, or production
deployment was performed. GitHub Environments, OIDC roles, remote backends, and initial ECR
repositories remain external prerequisites.

**Checklist:**

- [x] Extend CI for database migrations, PostgreSQL/RLS integration tests, auth/RBAC, SQS workers, hosted frontend, and dual-composition builds.
- [x] Add security, dependency, container, and Terraform checks.
- [x] Build immutable API, worker, hosted frontend, and retained self-hosted artifacts.
- [x] Implement OIDC deployments with environment approvals, migration job, health checks, rollback, and provenance.
- [x] Prevent production deploy from unreviewed branches and protect secrets/environments.

**Files/modules:** `.github/workflows/`, Dockerfiles/build config, deployment scripts/docs, artifact/version metadata.

**Validation:** Pull-request CI, failed-migration rehearsal, staged deploy, rollback, artifact verification, branch/environment protection review.

**Deliverable / definition of done:** A reviewed commit can produce traceable artifacts and a controlled staged deployment without workstation credentials.

**Risks:** Migration/deploy ordering, mutable tags, excessive CI duration, and production rollback gaps.

## V3.27 - Migration and V2 regression

**Goal:** Formalize hosted adoption paths while proving Version 2 remains supported.

**Dependencies:** V3.1 and all hosted behavior intended for release.

**Status:** Complete in `1a738a3` (`feat: add V2 to V3 migration and cutover compatibility`).
The V2 compatibility matrix and regression coverage, tenant-scoped and restart-safe migration
package workflow, verified source-document import, V3 knowledge rebuild requirements, cutover
validation, and operator runbook are complete. Migration uses ordinary authorization and forced
RLS boundaries without schema-owner bypass. Operational fallback to V2 remains straightforward
only before V3-only writes; later fallback requires explicit data reconciliation.

**Checklist:**

- [x] Define V2 compatibility matrix for CLI, synchronous API, Gradio, static Next.js, filesystem workspace, FAISS, Compose, and n8n.
- [x] Add automated self-hosted regression suite and representative E2E smoke.
- [x] Define optional import of V2 workspace documents/config/index metadata into one hosted workspace.
- [x] Rebuild hosted indexes from imported source documents rather than trusting old bundles blindly.
- [x] Document unsupported migration data and rollback/export.
- [x] Update V2 and V3 operator documentation without conflating modes.

**Files/modules:** Migration/import tooling, compatibility tests, Compose/build configs, V2/V3 docs, release notes.

**Validation:** Clean V2 install, existing workspace run, hosted import rehearsal, count/checksum comparison, triage comparison, rollback/export.

**Deliverable / definition of done:** V2 documented workflows still pass and a supported migration path preserves attributable source data.

**Risks:** Hidden V2 environment assumptions, incompatible configuration, and claiming lossless migration for JSONL or runtime state that is not imported.

## V3.28 - Multi-tenant isolation testing

**Goal:** Prove tenant isolation across every data and execution plane under adversarial conditions.

**Dependencies:** V3.3-V3.27.

**Status:** Complete in `872eecd` (`test: add adversarial tenant isolation coverage`).
Adversarial multi-tenant isolation and authorization suites cover cross-organization/workspace,
stale membership/grant, service-account, async transport, migration, quota, BFF, runtime-role RLS
bypass, pooled-connection reuse, composite-FK, and denied-mutation side-effect attacks. Two Medium
isolation defects were found and fixed: pagination cursors are now HMAC-signed and tenant/resource
scoped, and FAISS cache keys and locks are tenant scoped. No unresolved Critical/High isolation
finding remains; the suites are release-blocking in CI. No live target was attacked and no AWS
mutation occurred.

**Checklist:**

- [x] Build a multi-organization fixture with overlapping identifiers and content.
- [x] Test API object references, list/search, RLS, jobs, S3 presigned flows, FAISS cache, integrations, actions, usage, logs, and exports.
- [x] Test pooled connections, worker retries, stale sessions, revoked memberships, and support tooling.
- [x] Add deterministic generated matrices and adversarial identifier-substitution tests without adding a property-testing dependency.
- [x] Run targeted concurrency and failure-path tests for cache, queue, database, quota, and storage boundaries.
- [x] Make isolation suite release-blocking.

**Files/modules:** Dedicated isolation test suite, fixtures, test infrastructure, CI job, security evidence report.

**Validation:** No cross-tenant read/write/execute/log leakage across supported paths; findings reproduced and closed.

**Deliverable / definition of done:** Release-blocking automated evidence demonstrates tenant isolation in application and RLS layers.

**Risks:** False confidence from endpoint-only tests that omit workers, caches, presigned URLs, telemetry, and operational tools.

## V3.29 - Production-readiness validation

**Goal:** Demonstrate that Version 3 meets functional, reliability, security, operability, recovery, and compatibility criteria.

**Dependencies:** V3.0-V3.28.

**Status:** Complete at the code/readiness-evidence level in `5992bd1` (`feat: add production readiness and rehearsal evidence`).
Release-bound production-readiness evidence and fail-closed go/no-go validation are implemented,
with production prerequisite, recovery, capacity, egress, staging, migration/cutover, and disaster
recovery procedures documented. Local/CI readiness, adversarial, migration, frontend, PostgreSQL,
and Terraform validation passed. `CODE_READY=yes` and `REHEARSAL_READY=yes`, while
`LIVE_VALIDATED=no`, `LIVE_VALIDATION_PENDING=yes`, and `GO_LIVE_APPROVED=no`. The current decision
remains `NO_GO` until the exact committed release is built, deployed, and exercised in an approved
staging/live environment. No AWS call, Terraform plan/apply, deployment, DNS change, restore, live
load test, or customer migration occurred during V3.29.

**Checklist:**

- [x] Add release-bound evidence gates and staging procedures for end-to-end CloudWatch alert -> context -> retrieval -> triage -> review -> permitted-action scenarios; live execution remains pending.
- [x] Add bounded load/capacity tooling and procedures for soak, burst, queue backlog, retry/DLQ, provider outage, database failure, worker loss, and dependency timeout validation; live measurements remain pending.
- [x] Document backup restore, index rollback, incident response, key/secret rotation, connector disable, deployment rollback, and disaster-recovery rehearsal procedures; live rehearsal remains pending.
- [x] Define verification evidence for SLOs, dashboards, alarms, runbooks, support access, retention/deletion, quotas, and cost budgets.
- [x] Preserve internal engineering SLOs and record that final queue age, triage success, p95 time-to-triage, ingestion success, and worker failure thresholds require live measurements before adjustment.
- [x] Complete local/CI accessibility, browser, API compatibility, V2 regression, security, PostgreSQL, Terraform, migration, and isolation validation.
- [x] Record known limitations, release-bound acceptance criteria, and the explicit `NO_GO` decision pending live validation and operator approval.

**Files/modules:** Validation plans/reports, load/failure tooling, operational runbooks, release checklist, final documentation.

**Validation:** Staging rehearsal with synthetic data only; reviewed evidence for each acceptance criterion; no unapproved AWS production changes.

**Deliverable / definition of done:** Signed production-readiness report and explicit go/no-go decision with no unresolved release-blocking risk.

**Risks:** Treating a successful happy path as readiness, skipping recovery drills, or using real customer data during validation.

---

## Architecture acceptance criteria

- [ ] Every hosted request and job has verified actor, organization, and workspace context where applicable.
- [ ] Application authorization and PostgreSQL RLS independently prevent cross-tenant row access.
- [ ] S3 access is authorized through application/database state; opaque keys and KMS encryption are enforced.
- [ ] Every hosted retrieval uses the authorized workspace's verified active FAISS version.
- [ ] API and worker are independently deployable; SQS retries cannot create duplicate logical effects.
- [ ] PostgreSQL is authoritative for lifecycle and audit state; logs are not used as the database.
- [ ] CloudWatch integration uses explicit least-privilege cross-account trust and bounded collection.
- [ ] Consequential actions cannot execute without deterministic policy and valid human approval.
- [ ] Hosted application traffic uses HTTPS; API, worker, and PostgreSQL are private.
- [ ] High-cardinality IDs are available in logs/traces/audit but absent from CloudWatch metric dimensions.
- [ ] Hosted and self-hosted compositions share core triage behavior without global mode conditionals.

## Version 2 self-hosted compatibility requirements

- [ ] `uv run triage`, `rag-build`, `rag-query`, `serve-api`, product workspace commands, and eval remain supported.
- [ ] Existing incident and triage output fields, evidence behavior, and `triage_id` compatibility remain intact.
- [ ] Filesystem workspaces, demo/user corpus modes, local FAISS, JSONL adapters, and operator configuration remain available in self-hosted composition.
- [ ] Current FastAPI synchronous routes, Gradio UI, static Next.js export, Docker Compose, and optional n8n path remain testable.
- [ ] V2 does not require Cognito, PostgreSQL, S3, SQS, or hosted AWS resources.
- [ ] Hosted-only changes do not silently alter V2 security or deployment assumptions.

## Final Version 3 definition of done

Version 3 is complete when:

- [ ] Multiple organizations use one deployment with demonstrated tenant isolation.
- [ ] Cognito users and service accounts are authenticated, attributable, and governed by tested RBAC.
- [ ] PostgreSQL migrations, RLS, backup, restore, retention, and durable audit are operational.
- [ ] Workspace documents and versioned FAISS bundles are isolated, encrypted, verifiable, and recoverable.
- [ ] Manual and CloudWatch alerts create durable incidents and asynchronous triage runs.
- [ ] Automatic context collection is least privilege, bounded, attributable, and resilient to partial failure.
- [ ] Operators can review incident history, evidence, triage, feedback, usage, and pending approvals in the hosted application.
- [ ] Approved actions produce immutable, policy-controlled execution intents; actual
  controlled or autonomous remediation execution remains Version 4 work.
- [ ] The AWS platform uses HTTPS public ingress with private API, worker, and PostgreSQL services.
- [ ] Observability, quotas, security controls, CI/CD, failure recovery, and runbooks meet approved readiness criteria.
- [ ] Multi-tenant isolation and V2 regression suites are release-blocking and passing.
- [ ] Production-readiness review records no unresolved critical or high release blocker.

Version 4 remains the separate future execution layer for actual controlled or autonomous
remediation. Version 3 stops at immutable approved intent and deterministic connector
preparation; it does not execute remediation.
