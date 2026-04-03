# monitoring — Phase 13 (CloudWatch)

Terraform resources:

| Resource | Purpose |
|----------|---------|
| `aws_cloudwatch_dashboard` | ALB (requests, latency, 4xx/5xx, healthy hosts), ECS service CPU/memory, custom triage metrics from logs |
| `aws_cloudwatch_metric_alarm` | Target **5xx** spike; **UnHealthyHostCount** on the target group |
| `aws_cloudwatch_log_metric_filter` | Parses JSON lines `{"event":"triage_metrics",...}` from the ECS log group → **TriageSuccessCount**, **TriageFailureCount**, **TriageDurationMs** |

## Application logs

The API writes **one JSON object per line** to **stdout** after each triage (see `app/api/metrics_log.py`). Fields include `duration_ms`, `success`, `severity`, `escalate`, `graph_error`; `tokens_total` is reserved for future LangChain usage metadata.

Disable locally with `TRIAGE_METRICS_LOG_DISABLE=1`.

## Variables

- `observability_alarm_sns_topic_arns` (env root) — optional SNS ARNs for alarm notifications.
- `observability_alb_target_5xx_threshold` — default `10` per 5-minute period.
- `observability_create_dashboard` — set `false` to skip the dashboard only (alarms and metric filters remain).

## n8n workflow success

Not emitted from this API module. Use n8n’s own execution history, or extend `POST /n8n/workflow-log` with a metric line later.

## After apply

```bash
terraform output cloudwatch_dashboard_name
# AWS Console → CloudWatch → Dashboards → <name>
```

See also: [`docs/deploy/observability.md`](../../../../docs/deploy/observability.md).
