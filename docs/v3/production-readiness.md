# AIRA V3 production-readiness evidence

## Current classification

This document does not authorize a launch. V3.29 builds and locally validates the readiness and
rehearsal framework; live AWS evidence and operator approval remain separate gates.

| State | Current classification | Meaning |
|---|---|---|
| `CODE_READY` | yes, subject to the exact release CI gates | Code, schema, security, isolation, migration, and non-live readiness checks pass. |
| `REHEARSAL_READY` | yes | Procedures and safe harnesses exist for an approved staging rehearsal. |
| `LIVE_VALIDATED` | no | No staging deployment, AWS restore, load run, DNS, Cognito, STS, or alert pipeline was exercised in V3.29. |
| `GO_LIVE_APPROVED` | no | No operator has approved an exact release evidence package. |

Consequently the current decision is `NO_GO`. Green local tests are not production approval.

## Evidence states and release binding

Every check is one of `PLANNED`, `LOCAL_VALIDATED`, `CI_VALIDATED`, `LIVE_VALIDATED`, or `FAILED`.
The machine-readable schema is `docs/v3/schemas/readiness-evidence.schema.json`; the fail-closed
validator is `scripts/readiness/validate_evidence.py`.

Evidence and approval must bind all of these values:

- 40-character Git SHA;
- immutable API/worker digest and immutable web digest;
- Alembic revision;
- `staging` or `production` environment.

API and worker must use the same once-built Python image. Any SHA, digest, revision, or environment
mismatch rejects the package. Evidence for release A cannot approve release B.

`GO` requires every hard check, all live checks, no unresolved Critical/High finding, and explicit
release-bound approval. `CONDITIONAL` is limited to Low/Medium risks with owner, deadline,
mitigation, monitoring, and rollback trigger. It cannot waive a Critical/High finding.

## Prerequisite inventory

| Area | Code/CI evidence | Required live or operator evidence |
|---|---|---|
| DNS/TLS/ALB | Route53, ACM, HTTPS listener, target groups in Terraform | owned zone, issued cert, aliases and real target health |
| GitHub | pinned actions, OIDC workflows, protected-environment references | branch protection, OIDC roles/variables, production reviewers |
| Terraform | hosted roots, immutable inputs, destructive guard | initialized remote backends, reviewed drift-free plan |
| ECR/ECS | immutable repositories, task definitions, circuit breakers, smoke script | exact digests present, stable services, health/readiness evidence |
| Secrets | required containers and metadata-only AWSCURRENT check | populate DB, web session, cursor, LLM, and worker grant secrets |
| Cognito | pool/client/PKCE callback configuration | test-user PKCE, session, `/v3/me`, logout/revocation and MFA |
| RDS | private Multi-AZ prod design, 30-day backups, deletion protection/final snapshot | instance health, PITR window, isolated restore rehearsal |
| SQS/DLQ | queues, redrive policies, age and DLQ alarms | zero unexpected DLQ depth and controlled redrive rehearsal |
| S3/KMS | encryption, versioning, lifecycle and multipart cleanup | object round trip, denied foreign access, KMS policy evidence |
| EventBridge/STS | central bus, allowlist, ExternalId and bounded role code | synthetic alarm delivery and test-account AssumeRole |
| Observability | dashboards, alarms, EMF constraints, SLO math | action destinations, synthetic monitor and measured windows |
| Quotas | defaults, overrides, concurrency and noisy-neighbor tests | launch-default approval and observed rejection rates |
| Migration | deterministic package/import/verify/cutover tooling | synthetic staging cutover and signed report package |
| Rollback | prior-manifest workflow with no DB downgrade | N to N+1 failure and exact-digest N rollback rehearsal |
| Providers | bounded retries and redaction tests | NAT/DNS/TLS and provider failure evidence without customer data |

## Hard blockers

`NO_GO` applies to missing or failed security/isolation, migration, rollback, backup/restore,
runtime secrets, production OIDC trust, destructive-plan guard, ECS health, API readiness, DLQ,
alert intake, Cognito login, release binding, required alarms, or data-integrity evidence. It also
applies to any unresolved Critical/High security finding, image/revision drift, destructive
replacement of RDS/S3/KMS/Cognito/SQS, or missing production approval.

## Recovery objectives and procedures

Internal provisional objectives, not contractual SLAs:

- RPO target: at most five minutes for PostgreSQL where RDS PITR supports it; actual RPO is
  `LIVE_VALIDATION_PENDING` until backup/PITR evidence is captured.
- RTO target: four hours for isolated database restore and service recovery; actual RTO must be
  measured from restore start/end timestamps and must never be invented.
- Queue recovery target: return oldest-message age below the warning threshold within two hours of
  restored worker capacity; pending staging measurement.

Recovery behavior:

- bad release: stop promotion, restore the prior exact manifest digests, never downgrade the DB;
- DB failure: `/healthz` remains process-level, `/readyz` fails, workers stop durable transitions,
  and operator-approved failover/restore follows the DR runbook;
- queue backlog/DLQ: preserve messages, correlate to PostgreSQL, fix cause, redrive only selected
  safe messages, and verify idempotency;
- S3 failure: fail the document/bundle operation without marking metadata available/active;
- STS/CloudWatch failure: persist bounded partial-context diagnostics and never broaden access;
- LLM/provider outage: bounded job failure/retry, no duplicate completion, redacted errors;
- telemetry failure: metric/trace export is non-authoritative and must not fail business work;
  transactional audit failure remains operation-failing where audit is required.

The restore rehearsal uses an isolated RDS restore, controlled roles, Alembic comparison, table
counts/integrity, forced-RLS inventory, representative tenant reads, recorded start/end/RTO, and
evidence capture before approved teardown.

## Secrets and rotation

Readiness checks secret metadata only: existence, one `AWSCURRENT` version, and expected task
consumption. Values are never printed. Rotate DB credentials with coordinated task recycling and
connection draining; rotate provider/service-account credentials with overlap only where the
provider supports explicit revocation. Web-session key rotation forces reauthentication because old
sessions cannot be decrypted. `AIRA_CURSOR_SIGNING_KEY` rotation invalidates outstanding pagination
cursors but does not alter persisted data.

## Load and capacity

No live load measurement exists. The harness is ready, and results remain pending. Provisional
engineering assumptions for staging are 20 concurrent API/browser requests, 100 incidents and
triage admissions/hour, 1,000 alert events/hour, up to eight context-provider calls/incident,
100 uploads/day, and worker concurrency four/task. These are test inputs, not measured demand.

Capture request rate, p50/p95/p99, error and quota-rejection rates, queue age, worker throughput,
DB connections, and, in staging, ECS CPU/memory. Provisional pass thresholds: API p95 below 1s for
non-LLM reads/admission, error rate below 1%, oldest queued triage below 5m, at least 25% DB
connection headroom, and sustained ECS CPU/memory below 70%. Tune only from live evidence.

The connection calculator evaluates `tasks * (pool_size + max_overflow)` across API, worker,
dispatcher, alert ingestion, and web pools. Current SQLAlchemy defaults are 5 + 10; the release must
use actual task maxima and the selected RDS `max_connections`, not an assumed instance default.

The worker cache is tenant scoped and bounded to eight entries and 2 GiB. Production Fargate uses a
writable ephemeral cache mount under a read-only root; staging must verify the task's available
ephemeral storage and eviction under representative bundles. S3 uses versioning, KMS, lifecycle,
failed-multipart cleanup, and tenant quota accounting.

## Safe load and egress validation

`scripts/readiness/load_harness.py` accepts localhost or an exact operator allowlisted staging host,
rejects unknown and production-like hosts, emits `AIRA_SYNTHETIC_DO_NOT_ESCALATE`, and captures
latency/error results. It does not approve production load testing.

Runtime egress: LLM provider; public Cognito/JWKS where no endpoint applies; STS where not endpoint
routed; optional external OTLP. AWS-native traffic should use configured VPC endpoints where
present. Build-time egress includes package registries, GitHub Actions, and base-image registries.
`scripts/readiness/egress_check.py` performs exact-allowlist DNS resolution and a TCP/TLS certificate
handshake without sending prompts, documents, logs, tokens, or customer data. Run it only against
operator-approved staging/provider origins, never production merely because the script exists.

## Rehearsal sequence

1. Freeze exact SHA, image digests, revision, and environment in the release manifest.
2. Configure protected GitHub environment, OIDC roles, remote backend, DNS/TLS, and secrets.
3. Review Terraform plan and destructive guard; deploy exact candidate to staging.
4. Run migration before runtime activation; verify ECS, ALB, `/healthz`, and `/readyz`.
5. Perform Cognito PKCE login, `/v3/me`, workspace visibility, logout, and revocation.
6. Create unmistakable synthetic org/workspace/document and build/activate knowledge.
7. Create incident, request triage, poll, and verify evidence/provenance.
8. Deliver synthetic CloudWatch ALARM then OK through EventBridge; verify replay behavior.
9. Assume the dedicated test-account role and collect bounded/redacted Logs/Metrics context.
10. Verify proposal, approval, and frozen execution intent; prove no execution route exists.
11. Exercise quotas, noisy-neighbor isolation, dashboards, alarms, and provider failures.
12. Run allowlisted load harness and connection budget using actual staging configuration.
13. Rehearse N to N+1 failure and exact-digest rollback to N without DB downgrade.
14. Restore an approved backup into isolated RDS and collect restore evidence.
15. Rehearse synthetic V2 export/preflight/import/verify/index/cutover and both fallback boundaries.
16. Assemble evidence, run validator, review residual risks, and obtain separate approval.

Before V3-only writes, traffic can return to frozen V2. After any unique V3 write, fallback requires
data reconciliation and explicit ownership decisions; it is not a simple rollback.

## Engineering SLO and alarm status

The six engineering objectives are API availability, ingestion success, triage success, p95
time-to-triage, worker failure rate, and queue age. Definitions and burn-rate math are locally/CI
validated; actual attainment and threshold tuning require staging data and a synthetic monitor.
Required alarm evidence covers web/API target health, API 5xx/burn, queue age, both DLQs, worker and
dispatcher health, RDS CPU/storage/connections, and authentication degradation where available.

## Security and residual risks

V3.25 scan gates and V3.28 adversarial evidence are required inputs. Scanner reports must identify
tool/version/release and retain reviewed findings; no blind auto-fix or global Checkov suppression.

| Risk | Launch impact | Mitigation/detection | Decision owner |
|---|---|---|---|
| WAF absent | Medium; reduced edge filtering | ALB/Cognito/rate limits/log alarms; decide before launch | security/platform |
| VPC flow logs absent | Medium; reduced network forensics | CloudTrail/service logs; decide before launch | security/platform |
| No malware scanner | Medium; uploaded files are parsed as data, never executed | type/size checks, immutable quarantine/deletion procedure | security/product |
| DNS rebinding residual | Medium | deployment-owned endpoint allowlists and egress controls | security |
| No true step-up auth | not a V3 blocker because V3 cannot execute | require decision and stronger control before V4 | security/product |
| Live AWS/load/restore evidence absent | release blocker | complete staging rehearsal | operator |

Every residual risk needs owner, deadline, mitigation, monitoring, and rollback trigger in evidence.

## Incident tabletop and rollback triggers

Tabletop scenarios: cross-tenant suspicion, DB outage, leaked service/LLM credential, failed
migration, queue backlog, bad deployment, and customer AWS integration failure. Preserve evidence,
assign commander/scribe, contain narrowly, and follow existing security/observability runbooks.

Rollback triggers include failed readiness, sustained 5xx, broken authentication, revision mismatch,
stopped queue processing, security/cross-tenant signal, or major synthetic failure. Minor metric
noise alone is not an automatic rollback. Use a provisional two-hour launch observation window,
subject to operator approval, covering web/API/auth, DB, queues, workers, ingestion, triage, burn,
DLQs, and security signals.

## V4 boundary

V3 ends at `ActionProposal -> Approval -> immutable ExecutionIntent`. It has no remediation
execution. V4 may begin only after V3 production stability is evidenced, approval and intent binding
are proven, step-up authentication is decided, mutation credentials are isolated, execution policy
is designed, and provider-specific verification/rollback semantics are approved.
