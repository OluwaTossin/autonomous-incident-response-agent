# AIRA Version 3 architecture decisions

**Status:** Accepted for Version 3 planning  
**Scope:** Hosted platform architecture while preserving Version 2 self-hosted behavior

This record translates the Version 3 product boundary into implementation constraints. Each decision is grounded in the current repository: a synchronous FastAPI/LangGraph pipeline, process-global workspace configuration, filesystem documents and JSONL state, local FAISS, a static Next.js frontend, optional n8n workflows, and an ECS/ALB deployment built for one trusted operator team.

## A. Tenant model

**Decision:** Model tenancy as `User <-> OrganizationMembership -> Organization -> Workspace`. Roles are Owner, Admin, Operator, and Viewer, primarily scoped to organization membership with optional workspace restrictions.

**Context:** Version 2 calls a filesystem directory a workspace, but selects it with one cached process-wide `WORKSPACE_ID`. It has no user, organization, membership, or durable authorization model.

**Chosen approach:** Persist users, organizations, memberships, workspaces, and optional workspace grants. Resolve an authorized organization/workspace context for every hosted request and job. V3.5 will produce and approve the explicit Owner/Admin/Operator/Viewer permission matrix before RBAC implementation rather than inventing fine-grained permissions during architecture planning.

**Why:** Membership supports users in multiple organizations, invitations, revocation, and attributable actions. Organization-level roles keep initial administration understandable; workspace restrictions support least privilege without making every permission workspace-specific.

**Alternatives considered:** One organization per user was rejected as too restrictive. Workspace-only roles were rejected as administratively noisy. Free-form ACLs were rejected as premature complexity.

**Risks / trade-offs:** Organization roles can accidentally grant broad workspace access. Owner transfer and last-owner protections require explicit invariants. Role semantics can drift if permissions are duplicated across handlers.

**Consequences for the current repository:** `app/workspace/paths.py` can no longer define hosted tenancy. FastAPI dependencies, service methods, repositories, jobs, retrieval, audit, frontend routes, and tests must accept tenant context. The V2 filesystem workspace remains in the self-hosted composition.

**Follow-up work:** V3.5 must define and approve the permission matrix, invitation lifecycle, workspace restriction semantics, ownership transfer, suspension, and tenant-negative tests before RBAC implementation.

## B. Identity

**Decision:** Use Amazon Cognito as the initial managed human identity provider with Authorization Code Flow and PKCE. Hosted Next.js maintains a server-mediated session using Secure, HttpOnly cookies. AIRA service accounts authenticate external machine clients and integrations; internal API/worker identities use IAM or workload identity where applicable. `ActorContext` distinguishes human, `service_account`, and `system` actors. AIRA will not implement passwords.

**Context:** Version 2 protects routes with deployment-wide `API_KEY` and `ADMIN_API_KEY`. Those keys cannot represent users, membership, role, revocation, or per-actor audit.

**Chosen approach:** Complete Cognito Authorization Code Flow with PKCE through the hosted Next.js server, keep browser session material in Secure, HttpOnly cookies, and never store refresh tokens in `localStorage`. Verify issuer, audience, signature, expiry, and token type against Cognito JWKS. Map the stable provider subject to an AIRA user and build `ActorContext` from verified identity plus current membership. Represent external service accounts as attributable, revocable principals with scoped credentials; use AWS workload identity for internal services where possible.

**Why:** Managed identity reduces password, recovery, MFA, and account-security scope while giving AIRA standards-based tokens.

**Alternatives considered:** Custom passwords were rejected. Continuing shared API keys was rejected for hosted users. Cognito-hosted authorization alone was rejected because AIRA still must enforce domain permissions.

**Risks / trade-offs:** Cognito creates provider coupling and session complexity. Cookie sessions require CSRF defenses, secure callback handling, and careful refresh/revocation. JWT claims can become stale relative to membership changes. Machine credentials need rotation and compromise response.

**Consequences for the current repository:** `app/api/security.py` becomes a self-hosted adapter plus hosted authentication/authorization dependencies. Hosted request handlers stop reading shared keys as identity. The hosted frontend gains server-only Cognito/session code. Browser bundles contain no shared AIRA API/admin secrets. Audit records gain `actor_id` and actor type.

**Follow-up work:** V3.4 validates Cognito user-pool configuration, callback domains, MFA policy, token lifetimes, logout/revocation behavior, invitation flow, service-account credential format, IAM workload identities, CSRF controls, and local test-token strategy. These are deferred implementation details, not architecture blockers.

## C. Frontend

**Decision:** Keep the V2 self-hosted static Next.js/S3 frontend. Build Version 3 as a server-capable, containerized Next.js ECS/Fargate service that is independently deployable from the API. It may share the ALB routing layer with the API. Vercel and Amplify are not Version 3 dependencies.

**Context:** The current frontend uses `output: 'export'`, calls FastAPI directly, optionally compiles `NEXT_PUBLIC_TRIAGE_API_KEY`, and stores the admin key in `sessionStorage`.

**Chosen approach:** Preserve the static export and S3 deployment as the self-hosted UI. Run the hosted Next.js server in its own container and ECS service, complete Cognito Authorization Code Flow with PKCE server-side, maintain Secure, HttpOnly cookie sessions, and call hosted APIs without public static secrets. Route frontend and API traffic through explicit HTTPS ALB rules while retaining independent deployment and scaling.

**Why:** Hosted authentication, session refresh, organization routing, and protected server behavior do not fit the current static-only assumptions. V2 users should not lose their simple static deployment.

**Alternatives considered:** Keeping one static frontend was rejected due to token and session exposure. Replacing V2 outright was rejected because it would break self-hosted deployment. Embedding shared secrets was rejected. Vercel and Amplify were rejected as required dependencies so the hosted runtime remains aligned with the AWS/ECS platform.

**Risks / trade-offs:** Two deployment compositions increase build and test scope. Shared UI components can diverge. Server rendering introduces CSRF, cookie, caching, and runtime concerns. A separate ECS service adds image, health-check, scaling, routing, and deployment coordination work.

**Consequences for the current repository:** Reuse presentational components and API types where practical, but separate hosted session/API clients from V2 `frontend/src/lib/config.ts`, `api.ts`, and `admin-api.ts`. CI builds both modes. Terraform and deployment workflows add a distinct frontend image, ECS service, target group, health check, and ALB route.

**Follow-up work:** V3.13 validates the concrete Next.js Cognito library/integration, route protection, CSRF strategy, organization-aware URL model, cache behavior, and shared-component boundaries. Runtime selection is closed.

## D. PostgreSQL system of record

**Decision:** PostgreSQL is the authoritative hosted system of record, accessed with SQLAlchemy 2.x and migrated with Alembic. Lifecycle state lives in PostgreSQL, not JSONL. CloudWatch logs are observability, not authoritative audit storage. The migration/schema-owner role is separate from the runtime application role; the application role does not own tenant tables and does not have `BYPASSRLS`.

**Context:** Triage audit, feedback, and n8n events currently append local JSONL; reindex status is process memory; incidents and triage runs are not durable domain records.

**Chosen approach:** Persist identity mappings, tenancy, incidents, triage runs, jobs, evidence metadata, documents, index versions, integrations, actions, approvals, usage, and audit events in PostgreSQL. Use SQLAlchemy 2.x repositories/unit-of-work and Alembic migrations executed by the schema-owner role. Run the application with a non-owner, non-`BYPASSRLS` role. Keep structured logs as derived operational telemetry.

**Why:** Hosted workflows require transactions, queries, concurrency control, replica-safe state, retention, and durable correlation.

**Alternatives considered:** Continuing JSONL was rejected. DynamoDB was considered but rejected for the first hosted relational domain because memberships, lifecycle joins, migrations, and RLS fit PostgreSQL better.

**Risks / trade-offs:** PostgreSQL adds migration discipline, pooling, backup, recovery, and availability requirements. Poor transaction boundaries can couple long-running LLM work to database connections.

**Consequences for the current repository:** Introduce SQLAlchemy 2.x database configuration/models/sessions, Alembic, separate migration and runtime credentials, repository interfaces, and local PostgreSQL for hosted development. Refactor `app/api/audit.py`, feedback, reindex state, and triage execution into repositories/services while retaining V2 file adapters.

**Follow-up work:** V3.3 defines transaction conventions, SQLAlchemy session scope, Alembic execution, retention, backup/restore objectives, pool configuration, and operational credential rotation. Toolkit and role ownership choices are closed.

## E. Tenant isolation

**Decision:** Tenant-owned records carry `organization_id` and, where workspace-scoped, `workspace_id`. Enforce application authorization and design PostgreSQL Row Level Security in the initial hosted schema. RLS is defense in depth, not the only authorization mechanism.

**Context:** Current code derives one filesystem workspace from cached settings. It does not carry tenant identity through function signatures, storage, logs, or jobs.

**Chosen approach:** Derive tenant context from the authenticated actor or trusted job envelope. Scope every repository query explicitly. Apply organization/workspace identity transaction-locally using `SET LOCAL`-style PostgreSQL session settings; RLS policies consume those settings. Add foreign keys and composite constraints preventing organization/workspace mismatches.

**Why:** Multi-tenant safety requires multiple reinforcing controls and testable invariants.

**Alternatives considered:** Application checks alone were rejected as too fragile. RLS alone was rejected because authorization includes role and operation semantics outside row visibility. Separate databases per tenant were rejected for initial operational cost.

**Risks / trade-offs:** Incorrect transaction or pool handling can omit or leak tenant context. Background jobs can bypass request dependencies. Redundant tenant columns can drift without constraints. Mandatory pooled-connection isolation tests must prove settings do not survive transaction boundaries.

**Consequences for the current repository:** Global `get_settings().workspace_id` cannot select hosted data. Hosted services, workers, index caches, object keys, audits, and tests must be tenant-explicit. Raw unscoped queries are prohibited.

**Follow-up work:** V3.3 specifies RLS policy expressions and transaction helpers; V3.28 validates pooled reuse, worker context, migration-owner separation, support access, and adversarial isolation. Exact policy SQL is a deferred implementation decision, not an architecture blocker.

## F. Document storage

**Decision:** Store uploaded hosted source documents in S3 using immutable opaque object keys, PostgreSQL metadata, presigned transfer flows, and SSE-KMS. Enforce authorization in the application/database, not through predictable prefixes alone.

**Context:** `/admin/upload` currently writes validated files into `workspaces/<id>/data/...` on local disk. ECS replicas cannot safely share that model.

**Chosen approach:** Create document records before upload, issue short-lived presigned operations after authorization, finalize metadata after object verification, and retain checksum, size, media type, source category, state, and version. Never overwrite an existing object key.

**Why:** S3 provides durable, scalable objects while PostgreSQL controls lifecycle and access.

**Alternatives considered:** EFS was rejected as the primary hosted document model because it preserves filesystem coupling. Database blobs were rejected for size and operational concerns. Public or prefix-only S3 access was rejected.

**Risks / trade-offs:** Orphaned uploads, incomplete finalization, malicious content, KMS policy errors, and deletion races need handling. Presigned URLs are bearer capabilities until expiry.

**Consequences for the current repository:** Introduce a document-storage port and S3 adapter. Keep the filesystem adapter for V2. Loaders/index builders consume document streams or staged files rather than repository-relative paths.

**Follow-up work:** Define upload state machine, checksum verification, supported content, malware/DLP hook points, retention/deletion, object-lock needs, KMS key policy, and orphan cleanup.

## G. Retrieval

**Decision:** Preserve FAISS for initial hosted retrieval behind `KnowledgeIndex` and `Retriever` abstractions. Publish immutable, versioned, tenant-scoped FAISS bundles to S3 with manifests and checksums. ECS workers may cache verified bundles locally. PostgreSQL stores the active index version. pgvector is a later option, not a V3 dependency.

**Context:** Current retrieval directly opens `index.faiss`, `chunks.jsonl`, and `meta.json` from the process-selected workspace path. Index rebuild overwrites local output.

**Chosen approach:** Build a bundle for one workspace and corpus revision, upload immutable artifacts, validate the manifest, then atomically activate the version in PostgreSQL. Retrieval resolves the authorized workspace's active version and uses a bounded checksum-keyed cache.

**Why:** This retains proven FAISS behavior while making replicas and tenant boundaries explicit. The abstraction creates a migration seam only where a real storage difference exists.

**Alternatives considered:** pgvector day one was rejected as unnecessary migration risk. Mutable shared EFS indexes were rejected due to publication races. Baking all indexes into images was rejected as non-scalable and cross-tenant unsafe.

**Risks / trade-offs:** Large bundles increase cold-start latency and local disk use. Cache eviction and concurrent download locking must be correct. Corpus/index activation can race with deletion.

**Consequences for the current repository:** Refactor `app/rag/config.py`, `index_store.py`, `retrieve.py`, and index CLI around explicit workspace/index handles. Preserve existing hit/evidence contracts and a local filesystem implementation for V2.

**Follow-up work:** Define bundle format/version, manifest, checksums, cache limits, locking, activation transaction, rollback, garbage collection, compatibility checks, and pgvector evaluation criteria.

## H. Asynchronous triage

**Decision:** Use SQS with a dead-letter queue. Separate API and worker services while keeping the triage engine reusable. Assume at-least-once delivery and require idempotency. Triage-run states are `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, and `CANCELLED`.

**Context:** `/triage` currently generates an ID, runs retrieval and the LLM inline, appends JSONL, emits metrics, and returns the result in one request.

**Chosen approach:** The API transaction creates incident/triage/job state and publishes a tenant-qualified job. A worker claims the run, executes the shared triage service, writes terminal state and evidence, and emits an outbox-backed completion event. Retries reuse the same run or explicit attempt records.

**Why:** LLM and context work can exceed HTTP timeouts and must survive API restarts. SQS supplies durable buffering and redelivery.

**Alternatives considered:** Background tasks in FastAPI were rejected as non-durable. A general workflow engine was deferred. SQS FIFO is not required unless later ordering requirements justify it.

**Risks / trade-offs:** Duplicate delivery, visibility timeout expiry, poison jobs, cancellation races, and API/database/SQS dual writes require explicit handling.

**Consequences for the current repository:** Split pure triage from `run_full_triage` orchestration. Add job repositories, producer, worker entrypoint, status/result APIs, idempotency, and DLQ operations. Retain synchronous V2 adapters.

**Follow-up work:** Choose outbox/publish reliability pattern, visibility extension, retry taxonomy, maximum attempts, cancellation semantics, DLQ replay, job payload versioning, and worker concurrency.

## I. CloudWatch first integration

**Decision:** CloudWatch is the first automated source integration. The preferred first intake is `CloudWatch Alarm -> EventBridge -> authenticated cross-account AIRA EventBridge ingestion boundary`. Alert delivery remains separate from context collection. Context collection uses STS `AssumeRole` into a customer-managed, least-privilege AIRA read role. Long-lived customer AWS access keys are prohibited.

**Context:** Current CloudWatch code observes AIRA's own ECS/ALB behavior. It does not onboard customer accounts, ingest alarms, or collect customer telemetry.

**Chosen approach:** Authenticate the cross-account EventBridge delivery, map it to an integration/workspace, normalize and deduplicate the alarm, then enqueue context collection and triage. Store customer role ARN, external ID, allowed regions, log groups, and metric scope as integration metadata. Use STS `AssumeRole` only for bounded context reads; do not perform unrestricted account discovery.

**Why:** CloudWatch matches the existing AWS focus and supports a clear, least-privilege first integration without claiming universal infrastructure access.

**Alternatives considered:** Polling entire accounts was rejected. SNS/webhook variants are not the preferred first path. Long-lived access keys were rejected. Adding multiple monitoring vendors simultaneously was deferred.

**Risks / trade-offs:** Cross-account EventBridge onboarding is operationally complex. Region/account routing, quotas, Logs Insights cost, permission drift, and sensitive log data need controls.

**Consequences for the current repository:** Add integration domain records, onboarding APIs/UI, provider adapters, inbound verification, normalized alert schema, collectors, and integration health. Existing Terraform monitoring remains AIRA platform observability, not customer integration infrastructure.

**Follow-up work:** V3.16 validates exact multi-region EventBridge mechanics and publishes customer-side EventBridge/IAM templates, minimum AssumeRole permissions, external-ID rotation, supported alarm types, context query limits, redaction, and integration diagnostics. Multi-region mechanics are a deferred implementation decision, not an architecture blocker.

## J. Human approval

**Decision:** Informational actions such as configured notifications and tickets may execute automatically. Consequential infrastructure-changing actions require authenticated human approval in Version 3. LLM output alone never authorizes them. A deterministic action-risk policy is required.

**Context:** The current agent recommends actions, while n8n can send Slack messages and create mock tickets. There is no durable action or approval model.

**Chosen approach:** Persist action proposals, risk classification, policy decision, approval requests, approver, expiry, execution attempts, and outcomes. Separate recommendation generation from authorization and execution.

**Why:** This enables useful automation while preserving accountable control over production changes.

**Alternatives considered:** Fully manual notifications were too limiting. Fully autonomous remediation was rejected for Version 3. Letting the LLM self-classify authorization was rejected.

**Risks / trade-offs:** Misclassification can bypass or over-trigger approval. Stale approvals can authorize changed conditions. Connectors can duplicate side effects.

**Consequences for the current repository:** Existing n8n flows become optional connector implementations or compatibility paths. New hosted services enforce action policy and idempotency before dispatch.

**Follow-up work:** Define risk taxonomy, allowed automatic actions, approval roles, quorum if any, expiry, revalidation, connector idempotency, and emergency disable controls.

## K. AWS topology

**Decision:** Use public HTTPS entry through ALB and private networking for the containerized Next.js frontend, ECS API/worker tasks, and PostgreSQL according to their exposure requirements. Add SQS/DLQ, S3, KMS, Secrets Manager, ACM, CloudWatch, and required IAM. NAT provides controlled internet egress for external LLM access in the initial hosted design; use VPC endpoints selectively for AWS-native services where they improve cost, security, or availability.

**Context:** Current Terraform creates only public subnets, an HTTP ALB listener, and ECS tasks with public IPs. It has ECR, SSM secret injection, CloudWatch, and optional S3/CloudFront UI hosting.

**Chosen approach:** Keep ALB in public subnets; place frontend, API, and worker ECS tasks plus RDS in appropriate private subnet tiers with restrictive security groups. Terminate TLS using ACM and route frontend/API requests to independent target groups. Provide NAT egress for external LLM calls and add justified VPC endpoints for AWS-native traffic. Grant each service a distinct least-privilege role. Encrypt queues, buckets, database, and secrets.

**Why:** Hosted tenant data and credentials require stronger network and data boundaries than the V2 demonstration topology.

**Alternatives considered:** Public ECS/RDS was rejected. Endpoint-only egress was rejected because the initial design requires external LLM internet access. Kubernetes was rejected as unnecessary operational scope. Vercel/Amplify frontend hosting and serverless replacement of the existing container application were rejected as Version 3 dependencies.

**Risks / trade-offs:** NAT gateways can be expensive; endpoint-only networking cannot provide OpenAI internet egress. Private networking, migrations, failover, and restore operations add complexity.

**Consequences for the current repository:** Extend or version Terraform modules for private subnets, routing, endpoints/NAT, ACM/HTTPS, RDS, SQS, S3, KMS, Secrets Manager, worker ECS, autoscaling, backups, and alarms. No resource is added without a documented runtime requirement.

**Follow-up work:** V3.22 establishes domain/DNS ownership, environment/account strategy, RTO/RPO, database sizing, pooling, deployment migration jobs, selective endpoints, and cost budgets before apply. Exact dev/prod NAT gateway redundancy is a deferred implementation decision to be validated against availability and cost.

## L. Version 2 compatibility

**Decision:** Keep Version 2 self-hosted mode, preserve shared core behavior, and use separate hosted and self-hosted composition roots. Avoid scattered `hosted_mode` conditionals.

**Context:** V2 has a working local CLI, FastAPI API, Gradio UI, static Next.js console, workspace files, FAISS, Compose, n8n, tests, and documentation.

**Chosen approach:** Extract domain/application ports only where hosted adapters differ: identity, repositories, documents, index resolution, jobs, audit, and actions. Compose those ports separately for self-hosted and hosted entrypoints.

**Why:** The triage engine is proven and should evolve, not be rewritten. Explicit compositions make compatibility testable.

**Alternatives considered:** Replacing V2 was rejected. Forking the whole codebase was rejected due to drift. Global mode checks were rejected because they obscure boundaries.

**Risks / trade-offs:** Supporting two compositions increases CI and documentation load. Over-abstraction could slow delivery; under-separation could contaminate V2 with hosted assumptions.

**Consequences for the current repository:** Preserve current commands and contracts until an explicit migration phase. Add characterization tests before refactoring. New hosted modules should depend on shared interfaces, not filesystem globals.

**Follow-up work:** Define compatibility matrix, deprecation policy, dual-composition test suite, packaging, environment variables, and release artifacts.

## M. Observability

**Decision:** Propagate `organization_id`, `workspace_id`, `actor_id`, `incident_id`, and `triage_run_id` through logs, traces, and durable audit. Do not use those high-cardinality IDs as CloudWatch metric dimensions. Metric dimensions are bounded to values such as environment, operation, status, severity, plan, and connector type. Version 3 uses internal engineering SLOs rather than a public commercial SLA, beginning with a 99.9% hosted production API availability target.

**Context:** Current metrics emit `triage_id` in structured logs and use bounded environment/severity/escalation dimensions. There is no tracing or durable tenant-aware audit.

**Chosen approach:** Carry a structured correlation context across HTTP, SQS, workers, retrieval, integrations, and actions. Store authoritative audit events in PostgreSQL. Use logs/traces for individual correlation and bounded metrics for aggregate health and usage signals. Measure API availability, queue age, triage success rate, p95 time-to-triage, ingestion success, and worker failure rate.

**Why:** Full identifiers are essential for investigation but would make CloudWatch metrics expensive and unusable if used as dimensions.

**Alternatives considered:** Metrics-only correlation was rejected. Omitting tenant IDs from logs was rejected because it prevents support and incident investigation. Treating CloudWatch logs as the audit database was rejected.

**Risks / trade-offs:** Logs can leak sensitive identifiers or payloads. Missing propagation breaks traces. Organization-level metric dimensions can still become too numerous and are excluded by default.

**Consequences for the current repository:** Extend `app/api/metrics_log.py` into a shared context-aware telemetry layer, preserve `triage_id` compatibility as `triage_run_id` evolves, add tracing, redaction, and audit repositories, and update CloudWatch filters/dashboards.

**Follow-up work:** V3.23 defines log schema, trace propagation, redaction, retention, support access, sampling, bounded dimension values, usage aggregation, dashboards, and initial operational thresholds. V3.29 validates and may adjust final SLO thresholds based on measured behavior; those threshold refinements are deferred implementation decisions, not architecture blockers.
