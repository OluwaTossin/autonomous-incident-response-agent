# Hosted Engineering SLOs

These are internal engineering objectives, not public or contractual SLAs. The initial
window is a rolling 30 days. Targets and latency thresholds remain subject to production
measurement in V3.29.

For a percentage target `T` over a window of `W` seconds, the error budget is
`(1 - T) * W`. A 99.9% target over exactly 30 days therefore permits 2,592 seconds, or 43
minutes 12 seconds, of equivalent bad events. Event-ratio SLOs use the equivalent count
budget rather than translating it into downtime.

## Objectives

### Hosted API Availability

- **Target:** 99.9%.
- **SLI:** eligible requests without an unexpected 5xx or unavailable-backend response / all eligible requests.
- **Numerator:** eligible ALB/API requests returning below 500.
- **Denominator:** all API requests excluding health probes, deliberate client validation
  4xx, correct 401/403 responses, policy-correct `quota_exceeded` 429 responses, and approved
  maintenance. Internal quota evaluation failures remain eligible server failures.
- **Source:** ALB target metrics plus `AIRA/Hosted` API request/server-error metrics.
- **Budget:** 0.1%, equivalent to 2,592 seconds over 30 days.
- **Alerting:** provisional fast burn at 14.4x (1.44% error ratio) and slow burn at 6x (0.6%); require sustained datapoints rather than alerting on one 5xx.
- **Limitation:** metric math is an initial aggregate proxy; low-traffic synthetic checks and exclusion validation remain V3.29 work.

### Hosted Web Availability

- **Target:** 99.9%.
- **SLI:** successful eligible server/BFF requests with a healthy ALB target / all eligible web requests.
- **Numerator:** eligible requests below 500 while the target group has a healthy target.
- **Denominator:** all eligible protected/server-rendered requests, excluding client errors, static asset misses, bots rejected by policy, and approved maintenance.
- **Source:** web ALB target-group metrics, `/healthz`, and server structured logs.
- **Budget:** 0.1%, equivalent to 2,592 seconds over 30 days.
- **Alerting:** unhealthy-target and sustained target-5xx alarms; burn-rate metric math follows after representative traffic exists.
- **Limitation:** process health alone is insufficient; a synthetic protected-flow measurement is deferred to V3.29.

### Triage Request Durability

- **Target:** 99.9%.
- **SLI:** valid triage requests that atomically persist `TriageRun`, `Job`, and outbox row / valid authorized non-duplicate requests.
- **Numerator:** requests crossing that PostgreSQL transaction boundary, including idempotent replays already bound to the same request.
- **Denominator:** valid authorized requests; rejected validation, authorization, conflicts,
  deliberate quota admission rejections, and client cancellation before acceptance are
  excluded.
- **Source:** triage request lifecycle metrics and PostgreSQL audit/state consistency sampling.
- **Budget:** 0.1% of eligible requests per rolling 30 days.
- **Alerting:** request failures, dispatcher failures, queue age, and job DLQ.
- **Limitation:** this measures durable acceptance, not LLM success.

### Triage Processing Latency

- **Targets:** provisional p95 queue-to-start <= 2 minutes; p95 accepted-to-terminal <= 10 minutes; execution duration is reported separately.
- **SLI:** percentile of persisted timestamps for eligible terminal triage runs.
- **Numerator/denominator:** not a success ratio; include accepted runs that reach a terminal state, segmented by phase rather than combined silently.
- **Source:** `TriageRun`/`Job` timestamps, SQS oldest age, and triage/worker durations.
- **Exclusions:** operator cancellation and approved provider maintenance; failed/retried work remains visible in reliability indicators.
- **Budget:** latency objectives use the allowed 5% above threshold, not downtime minutes.
- **Limitation:** thresholds are hypotheses until V3.29 load and production measurements.

### Alert-Ingestion Durability

- **Target:** 99.9%.
- **SLI:** valid authenticated alarm events durably recorded as accepted, duplicate, or correctly policy-ignored / valid authenticated events received.
- **Numerator:** durable accepted events, same-payload duplicates, and explicitly ignored `INSUFFICIENT_DATA` events.
- **Denominator:** authenticated, route-matched, schema-valid EventBridge alarm events; malformed, unauthorized, and unconfigured routes are excluded and monitored separately.
- **Source:** alert lifecycle metrics, receipt rows, audits, SQS age, and alert DLQ.
- **Budget:** 0.1% of eligible events per rolling 30 days.
- **Alerting:** alert queue age, alert receiver task count, ingestion failures, and any DLQ message.
- **Limitation:** EventBridge delivery before AIRA SQS is measured by AWS delivery telemetry and onboarding validation.

### Async Worker Health

- **Target:** 99.9% of five-minute intervals healthy.
- **SLI:** intervals with running tasks at desired count, job queue oldest age <= 5 minutes, no sustained lease-recovery spike, and no new job-DLQ message / eligible intervals.
- **Numerator:** intervals satisfying all health conditions.
- **Denominator:** all intervals excluding approved maintenance with worker desired count zero.
- **Source:** ECS Container Insights, SQS, worker lifecycle metrics, and PostgreSQL reconciliation sampling.
- **Budget:** 0.1%, equivalent to 2,592 seconds over 30 days.
- **Alerting:** worker task-count, queue-age, DLQ, and worker failure/retry signals.
- **Limitation:** runnable-job and oldest-outbox age are not yet direct gauges; PostgreSQL-derived exporters are deferred pending operational evidence.

## Review Policy

SLO reviews must state the window, eligible population, exclusions, missing data, consumed
budget, and top error categories. Changes require documented evidence; missing telemetry
must not be interpreted as success. V3.29 validates thresholds, traffic assumptions,
synthetic coverage, and multi-window burn policy before a production-readiness decision.
