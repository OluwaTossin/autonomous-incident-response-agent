# Observability (Phase 13 — CloudWatch)

After **`terraform apply`** in `infra/terraform/envs/dev` or `envs/prod`, you get:

1. **ECS → CloudWatch Logs** (existing) — log group `/ecs/<name_prefix>-api`; container stdout/stderr (including uvicorn access logs).
2. **Dashboard** `<name_prefix>-api-observability` — ALB metrics, ECS CPU/memory, and **log-derived triage** metrics.
3. **Alarms** — ALB target **5xx** count; **unhealthy** registered targets (optional **SNS** via `observability_alarm_sns_topic_arns` in `terraform.tfvars`).

```bash
terraform output cloudwatch_dashboard_name
terraform output cloudwatch_custom_metric_namespace
terraform output cloudwatch_alarm_alb_target_5xx
```

## Triage JSON metrics (application)

Each successful or failed **graph** run appends a **single-line JSON** object to stdout, for example:

```json
{"event":"triage_metrics","triage_id":"…","duration_ms":8421,"success":true,"severity":"HIGH","escalate":false,"graph_error":false,"tokens_total":null}
```

CloudWatch **metric filters** on the ECS log group turn these into:

| Metric | Meaning |
|--------|---------|
| `TriageSuccessCount` | `success: true` |
| `TriageFailureCount` | `success: false` (graph error / invalid LLM path) |
| `TriageDurationMs` | Wall time for the LangGraph run (milliseconds) |

Namespace: **`terraform output -raw cloudwatch_custom_metric_namespace`** (default `<name_prefix>/API`).

**Token usage** is not populated yet (`tokens_total: null`); add LangChain / OpenAI usage callbacks later if you need billable token metrics in CloudWatch.

## CloudWatch Logs Insights

Example query on the API log group (replace group name from `terraform output -raw cloudwatch_log_group`):

```sql
fields @timestamp, @message
| filter @message like /"event":"triage_metrics"/
| sort @timestamp desc
| limit 50
```

For parsed fields (when the **entire** log line is JSON):

```sql
fields @timestamp, triage_id = jsonParse(@message).triage_id, duration_ms = jsonParse(@message).duration_ms, success = jsonParse(@message).success
| filter jsonParse(@message).event = "triage_metrics"
| stats avg(duration_ms) as avg_ms, count(*) as n by success
```

If uvicorn prefixes lines, filter on `@message like /triage_metrics/` and use `parse @message /.../` as needed.

## Container Insights

Enable **`enable_container_insights = true`** in `terraform.tfvars` for richer ECS metrics (already supported by `modules/ecs_fargate_api`). The dashboard still includes standard **AWS/ECS** CPU and memory for the service.

## n8n

Workflow success rates live in **n8n** (executions UI or self-hosted metrics), not in this stack. Ensure HTTP nodes that call the API include **`x-api-key`** when `API_KEY` is set (see [`workflows/n8n/README.md`](../../workflows/n8n/README.md)).
