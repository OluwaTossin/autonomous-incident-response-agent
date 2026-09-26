# Hosted disaster-recovery runbook

These are internal procedures and provisional recovery objectives, not a public SLA. AWS mutation,
failover, restore, redrive, DNS changes, or teardown require separate approval.

## Database restore rehearsal

1. Select an approved automated backup/PITR point and record identifier, source release/revision,
   restore start, expected RPO, and operator approval.
2. Restore to an isolated private RDS instance with separate security groups and no customer traffic.
3. Use controlled migration/runtime roles; never disable RLS or grant `BYPASSRLS`.
4. Verify Alembic revision, tenant-table counts, constraints, checksums/integrity, forced-RLS
   inventory, runtime non-ownership, and representative tenant-isolated reads.
5. Deploy the exact compatible service digests, run readiness and synthetic checks, and record end
   time plus observed RTO. Do not fabricate a measurement.
6. Capture sanitized evidence before separately approved teardown.

Provisional targets are RPO <= 5 minutes and RTO <= 4 hours; both remain live-validation pending.

## Service and dependency recovery

- API/web deployment: use ECS circuit breaker and prior immutable manifest; verify target health.
- Worker/dispatcher/ingestion crash loop: stop rollout, preserve logs/job state, restore prior task
  definition, then verify queue age and duplicate-safe resume.
- Queue/DLQ: never purge. Inspect metadata, correlate authoritative DB state, classify cause, fix it,
  redrive only selected safe messages, and verify no duplicate side effect.
- S3/KMS: preserve versioned objects, restore policy/key access, verify checksums/manifests, rebuild
  FAISS from authoritative documents when necessary; never trust an unverified cache copy.
- Secret loss/compromise: rotate through approved provider/Secrets Manager procedure and recycle only
  consumers. Session-key rotation forces login; cursor-key rotation invalidates cursors only.
- STS/customer trust: disable the affected integration, verify Principal/ExternalId/path/account and
  read-only policy, then reverify before enablement.
- LLM outage: allow bounded retries/terminal failure; durable incidents/jobs remain authoritative.
- DNS: prefer restoring known-good ALB routing. Do not point traffic at an unverified restore.

## Evidence and closure

Capture exact release identity, backup/restore identifier, timestamps, observed RPO/RTO, integrity
and RLS results, task definitions, queue/DLQ state, object checksums, alarm history, synthetic report,
owners, approvals, and residual risks. Keep the incident open until service, data, tenant isolation,
audit continuity, and monitoring are verified.
