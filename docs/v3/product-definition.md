# AIRA Version 3 product definition

**Product:** AIRA - Autonomous DevOps Incident Response Agent  
**Version:** 3 - hosted incident intelligence platform  
**Status:** Planning source of truth; implementation has not started

## Product scope

AIRA Version 3 evolves the Version 2 self-hosted, single-operator bring-your-own-data product into a hosted, multi-user platform for operational incident intake, context collection, evidence-grounded triage, review, and controlled follow-up.

The product shift is:

```text
Version 2
manual upload -> manual triage

Version 3
alert -> automatic context collection -> retrieval -> triage -> evidence
      -> operator review -> optional workflow action
```

Version 3 preserves the proven Version 2 triage core: incident normalization, workspace-scoped knowledge retrieval, LangGraph reasoning, deterministic policy, structured evidence, recommendations, and correlation identifiers. It adds the hosted control plane and durable operational workflow needed to serve multiple organizations safely.

Version 3 is not the fully autonomous Version 4 system. It may automate ingestion, enrichment, notifications, and ticket creation, but it does not autonomously authorize consequential infrastructure changes.

## Problem

Operational teams receive alerts through monitoring systems while the context needed to understand them is fragmented across logs, metrics, runbooks, incident history, service ownership records, and human knowledge. Version 2 demonstrates that AIRA can retrieve relevant material and produce structured triage, but it assumes one trusted operator, one process-selected workspace, local files, a local FAISS index, shared API keys, synchronous execution, and JSONL state.

Those assumptions prevent AIRA from operating as a safe hosted service. Version 3 must:

- receive alerts without requiring an operator to paste each payload;
- collect relevant context through explicitly authorized integrations;
- isolate each organization's users, workspaces, documents, indexes, incidents, and credentials;
- persist incident and triage lifecycle state durably;
- let teams review evidence and outcomes together;
- execute only policy-appropriate follow-up actions;
- retain Version 2 as a supported self-hosted composition.

## Target users

### DevOps engineers

Need faster first-response context, consistent triage, and links from alerts to relevant runbooks, logs, metrics, and prior incidents.

### Site reliability engineers

Need evidence-grounded severity and escalation decisions, durable incident history, auditable actions, and reliable integration behavior under failure.

### Platform engineers

Need organization-wide workspaces, secure monitoring integrations, service-account access, policy controls, usage visibility, and predictable deployment boundaries.

### Engineering teams

Need a shared incident view that explains what happened, why AIRA reached a conclusion, what evidence supports it, and what should happen next.

## Version 2 versus Version 3

| Concern | Version 2 | Version 3 |
|---------|-----------|-----------|
| Operating model | Self-hosted, one trusted operator team | Hosted, multi-user and multi-organization |
| Identity | Shared triage/admin API keys | Cognito human identity, server-mediated browser sessions, AIRA service accounts, workload identity |
| Tenant selection | Process-wide `WORKSPACE_ID` | Request- and job-scoped organization/workspace context |
| State | Local files, JSONL, process memory | PostgreSQL system of record |
| Documents | Workspace bind mounts and admin upload | Tenant-authorized S3 objects with PostgreSQL metadata |
| Retrieval | Local workspace FAISS path | Versioned workspace FAISS bundles behind an abstraction |
| Triage execution | Synchronous HTTP request | Durable SQS job processed by workers |
| Alert intake | Manual JSON submission | Automatic CloudWatch/EventBridge intake plus manual submission |
| Context | Payload plus pre-indexed corpus | Payload, corpus, and authorized automatic logs/metrics collection |
| Frontend | Static exported operator console | Independently deployable containerized Next.js ECS service; V2 static UI retained |
| Actions | Optional n8n notification/mock ticket flows | Durable action records; automatic informational actions; approval for consequential actions |
| Audit | JSONL and CloudWatch logs | Authoritative PostgreSQL audit records plus logs/traces |

## Value proposition

AIRA Version 3 gives operational teams a hosted incident intelligence layer that connects alert delivery to relevant operational knowledge and live context, produces structured and cited triage, and keeps humans in control of consequential response.

The primary value is reduced time to a credible first diagnosis without sacrificing tenant isolation, evidence, accountability, or operator judgment.

## Primary user journeys

### 1. Organization onboarding

1. A user signs in through the managed identity provider.
2. The user creates or joins an organization.
3. An Owner or Admin creates a workspace and assigns access.
4. The team configures retention, usage limits, and allowed integrations.

### 2. Knowledge onboarding

1. An authorized user uploads runbooks, incident reports, logs, or knowledge documents.
2. AIRA stores immutable source objects in S3 and metadata in PostgreSQL.
3. An index job builds a tenant-scoped FAISS bundle.
4. A validated bundle version is published to S3 and activated for the workspace.

### 3. Manual incident triage

1. An Operator submits an incident payload in an authorized workspace.
2. AIRA persists an incident and queues a triage run.
3. A worker loads the active workspace index, executes the existing triage core, and persists structured output and evidence.
4. The user follows progress and reviews the result in the hosted application.

### 4. Automatic CloudWatch incident flow

1. A CloudWatch Alarm routes through EventBridge to an authenticated cross-account AIRA EventBridge ingestion boundary.
2. AIRA verifies the integration, normalizes and deduplicates the event, and creates an incident.
3. AIRA assumes a least-privilege customer role to collect configured logs and metrics context.
4. A triage job runs with the alert, collected context, and workspace knowledge.
5. Operators review the evidence and recommended response.

### 5. Follow-up action

1. A policy classifies a proposed action by risk.
2. A configured notification or ticket action may execute automatically.
3. A consequential infrastructure-changing action remains blocked pending explicit human approval.
4. AIRA records proposal, approval, execution attempt, actor, and outcome.

### 6. Investigation and learning

1. A user searches workspace incident and triage history.
2. The user reviews evidence, timing, decisions, usage, and feedback.
3. Feedback is linked to the durable triage run and can inform later evaluation without silently changing production behavior.

## Functional capabilities

Version 3 includes:

- managed human authentication using Amazon Cognito Authorization Code Flow with PKCE;
- secure server-mediated hosted browser sessions using Secure, HttpOnly cookies;
- AIRA service accounts for external machine clients and IAM/workload identity for internal services;
- users, organizations, memberships, workspaces, and role-based authorization;
- PostgreSQL-backed incident, triage, job, action, usage, and audit lifecycles using SQLAlchemy 2.x and Alembic;
- tenant-isolated S3 document storage and presigned transfers;
- tenant-aware, versioned FAISS index publication and retrieval;
- asynchronous triage through SQS with retries and a dead-letter queue;
- manual and automatic incident ingestion;
- CloudWatch/EventBridge alert delivery and least-privilege context collection;
- structured triage with evidence, severity, confidence, recommendations, and correlation IDs;
- an independently deployable, containerized, server-capable hosted Next.js ECS service for organizations, workspaces, incidents, triage, knowledge, and approvals;
- automatic informational actions when configured;
- human approval gates for consequential actions;
- tenant-aware logs, traces, durable audit, usage records, and quota enforcement;
- hosted AWS deployment with public HTTPS ingress and private application/data services;
- continued Version 2 self-hosted operation using shared core behavior.

## Non-goals

Version 3 does not include:

- autonomous infrastructure remediation;
- LLM-authorized consequential actions;
- unrestricted discovery or "sniffing" of customer infrastructure;
- a custom password or identity system;
- pgvector as a day-one dependency;
- general-purpose workflow automation replacing n8n or dedicated integration platforms;
- arbitrary customer code execution;
- full billing, invoicing, taxation, or subscription commerce;
- support for every monitoring provider in the first release;
- silent training on customer operational data;
- elimination of the Version 2 self-hosted product.
- Vercel or Amplify as required Version 3 hosting dependencies.

Version 4 is reserved for a separately designed autonomous-action layer with stronger policy, simulation, verification, rollback, and safety requirements.

## Trust model

AIRA assumes:

- the identity provider authenticates human users and issues verifiable tokens;
- hosted human sign-in uses Authorization Code Flow with PKCE and the hosted Next.js server maintains the browser session with Secure, HttpOnly cookies;
- refresh tokens are never stored in `localStorage`, and browser bundles contain no shared AIRA API or admin secret;
- AIRA authorizes every hosted request and job against organization/workspace membership;
- `ActorContext` distinguishes human, `service_account`, and `system` actors;
- external machine clients use AIRA service accounts, while internal API/worker calls use IAM or workload identity where applicable;
- tenant identifiers are derived from authorized context, not trusted from arbitrary payload fields;
- PostgreSQL application authorization is reinforced by Row Level Security;
- the PostgreSQL migration/schema-owner role is separate from the runtime application role; the runtime role neither owns tenant tables nor has `BYPASSRLS`;
- tenant identity is set transaction-locally and consumed by RLS policies, with mandatory pooled-connection isolation tests;
- S3 object keys are opaque and access is mediated by AIRA-authorized presigned operations;
- integration roles and service accounts are least privilege, revocable, and attributable;
- external alert deliveries are authenticated, deduplicated, and replay-safe;
- CloudWatch alert delivery and context collection are separate: EventBridge delivers alarms, while STS `AssumeRole` grants bounded read access to configured customer Logs and Metrics resources;
- SQS delivery is at least once and side effects are idempotent;
- LLM output is untrusted advisory data until validated by schemas and deterministic policy;
- customer documents, alerts, logs, and metrics may contain sensitive operational data and require encryption, retention, redaction, and deletion controls;
- CloudWatch logs support operations but are not the authoritative audit store.
- private hosted services use controlled NAT internet egress for external LLM calls, with selective VPC endpoints for AWS-native services where justified.

No single control is considered sufficient for tenant isolation. Identity verification, application authorization, repository scoping, database constraints, RLS, storage policy, encryption, testing, and observability must reinforce each other.

## Human-in-the-loop boundaries

Version 3 may automatically:

- receive and normalize configured alerts;
- collect explicitly authorized logs and metrics;
- retrieve workspace knowledge;
- generate and persist triage;
- notify configured channels;
- create or update configured tickets;
- request human review.

Version 3 must require human approval before any action that changes infrastructure, production configuration, deployment state, access policy, secrets, data retention, or another consequential operational control.

An LLM may recommend an action, but it cannot classify itself as authorized, grant approval, or execute a consequential action. A deterministic action-risk policy and an authenticated approver are required.

## Version 2 compatibility

Version 2 remains a supported self-hosted product mode. Its CLI, local FastAPI flow, workspace filesystem contract, local FAISS behavior, Docker Compose workflow, static frontend, and documented operator experience remain valid unless an explicit migration phase changes them.

Version 3 will share incident schemas, triage output, LangGraph reasoning, deterministic policy, evidence behavior, and retrieval contracts. Hosted and self-hosted deployments will use separate composition roots instead of scattered `hosted_mode` branches.

## Success criteria

Version 3 is successful when:

- two or more organizations can use one hosted deployment without cross-tenant data access;
- organization and workspace authorization is enforced in API, worker, database, document, retrieval, and action paths;
- a CloudWatch alert can create a deduplicated incident, collect authorized context, enqueue triage, and produce an evidence-grounded result;
- triage jobs survive API restarts, retry safely, and surface terminal failure through a DLQ/replay process;
- every incident, triage run, evidence item, approval, action, and usage record is durably attributable;
- informational actions can run automatically when policy allows, while consequential actions cannot execute without approval;
- uploaded documents and active FAISS bundle versions remain isolated by workspace;
- hosted traffic uses HTTPS and private application/data services;
- the production design targets 99.9% API availability as an internal engineering SLO rather than a public commercial SLA;
- queue age, triage success rate, p95 time-to-triage, ingestion success, and worker failure rate are measured and governed by internal operational targets;
- high-cardinality correlation IDs remain searchable without becoming CloudWatch metric dimensions;
- Version 2 self-hosted tests and documented workflows continue to pass;
- security, isolation, failure, load, recovery, and production-readiness validation are completed before general availability.
