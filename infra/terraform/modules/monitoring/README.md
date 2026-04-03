# monitoring — Phase 13 (CloudWatch)

Terraform resources:

| Resource | Purpose |
|----------|---------|
| `aws_cloudwatch_dashboard` | ALB request **rate/min**, latency **avg + p95**, **4xx** vs **5xx** panels, target health, ECS CPU/memory, triage success/fail + **token sum**, triage duration **avg + p95** |
| `aws_cloudwatch_metric_alarm` | Target **5xx**; **UnHealthyHostCount**; **TargetResponseTime p95**; **ECS CPUUtilization**; **TriageDurationMs** Maximum |
| `aws_cloudwatch_log_metric_filter` | JSON `triage_metrics` → **TriageSuccessCount**, **TriageFailureCount**, **TriageDurationMs**, **TriageTokensTotal** |

## Application logs

The API writes **one JSON object per line** to **stdout** and the **`aira.triage`** logger after each triage (`app/api/metrics_log.py`, `app/api/triage_execution.py`). Fields include `triage_id`, `outcome`, `duration_ms`, `severity`, `tokens_prompt`, `tokens_completion`, `tokens_total` (from LangChain usage metadata on the LLM step).

Disable with `TRIAGE_METRICS_LOG_DISABLE=1`.

## Alarm tuning (module variables)

| Variable | Default | Meaning |
|----------|---------|---------|
| `alb_latency_p95_threshold_seconds` | 25 | ALB target p95 latency |
| `ecs_cpu_alarm_threshold_percent` | 85 | ECS service CPU avg |
| `triage_duration_alarm_max_ms` | 120000 | Max single triage duration in period |
| `create_alb_latency_p95_alarm` | true | Set `false` to skip |
| `create_ecs_cpu_alarm` | true | Set `false` to skip |
| `create_triage_duration_alarm` | true | Set `false` to skip |

Pass these into `module.monitoring` from `envs/*/monitoring.tf` when you want per-env overrides without editing the module.

## n8n workflow success

Not emitted from this API module. Use n8n’s own execution history, or extend `POST /n8n/workflow-log` later.

## After apply

```bash
terraform output cloudwatch_dashboard_name
# AWS Console → CloudWatch → Dashboards → <name>
```

See [`docs/deploy/observability.md`](../../../../docs/deploy/observability.md).
