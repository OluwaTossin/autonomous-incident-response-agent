# First-response checklist (first 15 minutes)

Generic SRE sequence for **alert → bounded triage**. Pair with specific **`RB-*`** runbooks from `data/runbooks/`.

1. **Acknowledge** the page; open war room / ticket; note **UTC** time.  
2. **Classify blast radius:** one service vs many, one region vs global.  
3. **Correlate changes:** deploy, flag, cert, rotation, traffic spike (last 1–4 hours).  
4. **Check golden signals** for affected scope: errors, latency, saturation, traffic.  
5. **Grab evidence:** deployment ID, graph links, **redacted** log lines, trace IDs.  
6. **Stabilise** only with approved levers: rollback, scale, circuit open, rate limit.  
7. **Escalate** if SEV-1 criteria met or timebox exceeded per escalation matrix.  
8. **Update** stakeholders on customer impact **yes/no** and next checkpoint time.

## If symptoms match…

| Symptom sketch | Start here |
|----------------|------------|
| CPU + latency after deploy | `RB-GEN-HIGH-CPU-001` / `RB-PAYMENT-API-HIGH-CPU-001` |
| OOM / exit 137 | `RB-MEM-OOM-002` |
| 5xx / ALB | `RB-HTTP-5XX-003`, `RB-LB-HEALTH-010` |
| DB connections / FATAL | `RB-DB-CONN-004` |
| Pod crash loop | `RB-K8S-CRASH-005` |
| Disk full / pressure | `RB-DISK-SAT-006` |
| TLS / cert | `RB-TLS-CERT-007` |
| Vendor slow / 429 | `RB-EXT-API-008` |
| Queue lag | `RB-QUEUE-LAG-009` |

## Synthetic practice data

- Incidents: `data/incidents/`  
- Logs: `data/logs/`  
