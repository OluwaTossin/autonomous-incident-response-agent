# Usage and quota operations

This runbook concerns capacity protection, not billing.

## Unexpected rejection spike

1. Check `quota_rejections_total` by bounded `QuotaType`, `Operation`, and `Result`.
2. Correlate the time window with API 429 logs and the affected operation. Use protected IDs
   in logs; never add tenant IDs to metric dimensions.
3. Verify the effective workspace override, organization policy, and deployment default in
   that order, including policy version and UTC reset time.
4. For alert intake, confirm rejected new events are durable policy-ignored acknowledgements
   and are not cycling through the alert DLQ.
5. Do not raise a quota through browser input or an unaudited database edit.

## Counter drift

1. Compare the affected lifetime counter with authoritative PostgreSQL metadata for the same
   tenant and usage definition.
2. Check duplicate source references, failed transactions, and application logs for
   `usage_record_failures_total`.
3. Run the repository reconciliation operation in an authorized tenant transaction. Record
   the mismatch count through aggregate observability.
4. Re-read the summary and sample raw ledger events. Routine reconciliation must not issue a
   broad S3 inventory scan.

## Stuck concurrency

Concurrent triage derives from durable pending/running jobs, and index concurrency derives
from BUILDING index versions; there are no detached reservation rows. Reconcile the owning
Job/TriageRun or knowledge-index lifecycle using its existing runbook. Never decrement a
counter to conceal stuck authoritative state.

## False storage exhaustion

Confirm pending document uploads and retained immutable versions. Pending versions reserve
their expected upload size; finalized versions use verified S3 metadata. Failed-object
cleanup and actual durable deletion may release capacity only through their defined lifecycle.
Historical objects must not be deleted merely to satisfy a quota.

## Override review

Quota override rows are versioned and tenant scoped. V3.24 has no mutation endpoint. Any
future operator override workflow must require Owner/Admin or platform-system authority,
write a durable audit event, retain the previous policy version, and remain bounded. There is
no `unlimited` bypass.

