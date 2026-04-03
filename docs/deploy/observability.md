# Observability (Phase 13 — CloudWatch)

After **`terraform apply`** in `infra/terraform/envs/dev` or `envs/prod`, the stack exposes:

1. **ECS → CloudWatch Logs** — log group `/ecs/<name_prefix>-api`; container stdout/stderr (including uvicorn access logs).
2. **Dashboard** `<name_prefix>-api-observability` — ALB (request rate/min, latency **avg + p95**, **4xx** and **5xx** split, health), ECS CPU/memory, **triage** outcomes + **token sum**, triage duration **avg + p95**, **severity / escalate** breakdowns (log-derived metrics via SEARCH), and a **Logs Insights** table of recent rows with **`triage_id`** for traceability.
3. **Alarms** (optional **SNS** via `observability_alarm_sns_topic_arns` in `terraform.tfvars`):
   - ALB target **5xx** (sum per period)
   - **UnHealthyHostCount** on the target group
   - ALB **TargetResponseTime p95** high (default **25s**, tunable in `modules/monitoring` variables)
   - ECS service **CPUUtilization** average high (default **85%**)
   - **TriageDurationMs Maximum** over period high (default **120s** wall time for one graph run)

```bash
terraform output cloudwatch_dashboard_name
terraform output cloudwatch_custom_metric_namespace
terraform output cloudwatch_alarm_alb_target_5xx
terraform output cloudwatch_alarm_alb_latency_p95
terraform output cloudwatch_alarm_ecs_cpu_high
terraform output cloudwatch_alarm_triage_duration_max
```

Tune thresholds by passing variables into `module.monitoring` from `monitoring.tf` (or extend `variables.tf` / `terraform.tfvars` when exposing them at the env layer).

## Application metrics & structured logging

Each **triage** emits **one JSON object** to **stdout** and the **`aira.triage`** logger (same string) so CloudWatch metric filters and Logs Insights stay aligned.

Example:

```json
{"log_schema":"aira.triage.v1","event":"triage_metrics","triage_id":"…","stack_environment":"dev","outcome":"success","duration_ms":8421,"success":true,"severity":"HIGH","severity_metric":"HIGH","escalate":false,"escalate_str":"false","graph_error":false,"tokens_prompt":1200,"tokens_completion":400,"tokens_total":1600}
```

| JSON field | Purpose |
|------------|---------|
| `triage_id` | Correlate with audit JSONL, n8n feedback, and the dashboard Logs Insights widget |
| `stack_environment` | Low-cardinality label for CloudWatch metric dimensions (set **`AIRA_ENV`** on the task — Terraform sets it to `var.environment` in dev/prod) |
| `outcome` | `success` \| `graph_error` |
| `duration_ms` | LangGraph wall time (retrieve + LLM + format) |
| `severity` / `escalate` | Raw business fields from triage output |
| `severity_metric` / `escalate_str` | Normalized strings for **log metric filter dimensions** (avoid `null` / non-string dimensions) |
| `tokens_*` | From LangChain `UsageMetadataCallbackHandler` on the structured chat call (`0` when no usage recorded) |

**EMF vs log metric filters:** this stack uses **structured JSON logs + metric filters** (not Embedded Metric Format). That avoids duplicate publishing when EMF is added later; when switching to EMF-only, remove or disable the corresponding filters so the same custom namespace is not counted twice.

Disable stdout + `aira.triage` emission with **`TRIAGE_METRICS_LOG_DISABLE=1`**.

### CloudWatch custom metrics (log metric filters)

All triage metrics below include dimension **`Environment`** = JSON **`stack_environment`** (must match Terraform `triage_metrics_environment` / container **`AIRA_ENV`**).

| Metric | Filter (simplified) |
|--------|---------------------|
| `TriageSuccessCount` | `success = true` |
| `TriageFailureCount` | `success = false` |
| `TriageDurationMs` | value = `duration_ms` on success |
| `TriageTokensTotal` | `tokens_total >= 1` (skips zero-token lines) |
| `TriageBySeverityCount` | count `1` per line; dimensions **Environment**, **Severity** (`severity_metric`) |
| `TriageByEscalateCount` | count `1` per line; dimensions **Environment**, **Escalate** (`escalate_str` = `true` / `false`) |

Do **not** put `triage_id` on custom metrics as a dimension — CloudWatch cardinality limits would make that unusable. Keep **`triage_id` in logs** and the dashboard **Logs Insights** widget (and ad hoc Insights queries).

Namespace: **`terraform output -raw cloudwatch_custom_metric_namespace`** (default `<name_prefix>/API`).

## CloudWatch Logs Insights

Filter logger **`aira.triage`** or search for `"triage_metrics"`:

```sql
fields @timestamp, @message
| filter @message like /"event":"triage_metrics"/
| sort @timestamp desc
| limit 50
```

Parse when the line is pure JSON:

```sql
fields @timestamp,
  triage_id = jsonParse(@message).triage_id,
  outcome = jsonParse(@message).outcome,
  duration_ms = jsonParse(@message).duration_ms,
  tokens_total = jsonParse(@message).tokens_total
| filter jsonParse(@message).event = "triage_metrics"
| stats avg(duration_ms) as avg_ms, sum(tokens_total) as tokens by outcome
```

## Container Insights

Enable **`enable_container_insights = true`** in `terraform.tfvars` for richer ECS metrics (already supported by `modules/ecs_fargate_api`).

## n8n

Workflow success rates live in **n8n** (executions UI or self-hosted metrics), not in this stack. Ensure HTTP nodes that call the API include **`x-api-key`** when `API_KEY` is set (see [`workflows/n8n/README.md`](../../workflows/n8n/README.md)).
