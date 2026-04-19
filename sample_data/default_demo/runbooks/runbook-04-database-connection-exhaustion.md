# Runbook: Database connection pool exhaustion / “too many connections”

**Runbook ID:** RB-DB-CONN-004  
**Service:** Applications using RDBMS (Postgres, MySQL, etc.) via pools (Hikari, pgx, SQLAlchemy, etc.)  
**Environment:** Production  
**Primary owner:** Application team + **DBA / data platform**  
**Supporting:** SRE  
**Severity when triggered:** HIGH–CRITICAL (often drives **5xx** and full outage when pool and server max collide)  
**Last updated:** 2026-04-02 — Oluwatosin Jegede

---

## Summary

**Connection exhaustion** occurs when apps cannot obtain DB connections: pool **saturated**, **leaks** (connections not returned), or DB **`max_connections`** reached across many clients. Goal: restore queries, identify leak vs scale vs misconfig, and prevent retry amplification.

---

## Scope and applicability

**In scope:** `too many connections`, `connection refused`, pool **wait time** alerts, RDS/Aurora **DatabaseConnections** maxed.

**Out of scope:** **Query slowness only** with healthy pool — performance tuning runbook. **Storage full** — disk runbook.

---

## Symptoms and typical alerts

- App logs: `Timeout waiting for connection`, `FATAL: too many connections`, `remaining connection slots are reserved`.
- Metrics: pool **active** == **max**, wait queue depth, DB connection count near limit.
- **5xx** spike correlated with DB errors — see **`runbook-03-http-5xx-spike.md`**.

---

## Preconditions

- [ ] **DB instance** identifier, **max_connections**, **reserved** slots (superuser/replication).  
- [ ] Count of **app replicas** × **pool max per instance** (rough upper bound of app demand).  
- [ ] Read/write split: writers vs readers connection paths.

---

## Immediate checks (first 5 minutes)

1. **DB side** — Current connections by **user** and **application** (if tagged); idle in transaction?  
2. **Spike timing** — Deploy increasing **replica count** or **pool size**?  
3. **Leak signal** — Connections growing monotonically per pod until restart?  
4. **Retry storm** — Clients hammering DB on failure (exponential backoff missing)?  
5. **Failover** — Recent RDS failover doubling connections briefly?

---

## Deeper diagnosis (15–30 minutes)

| Area | Actions |
|------|---------|
| **Pool config** | `maximumPoolSize`, `minimumIdle`, connection **lifetime**, **validation** query. |
| **ORM / code** | Unclosed sessions, long transactions, N+1 in batch jobs holding connections. |
| **Migrations** | Long-running migration holding pool or advisory locks. |
| **PgBouncer / RDS Proxy** | If used — session vs transaction mode, pool sizing. |
| **Read replicas** | Read traffic wrongly pinned to writer. |

---

## Likely root causes

1. **Replica × pool size** exceeded DB `max_connections`.  
2. **Connection leak** in new code or library bump.  
3. **Idle in transaction** from slow clients or debugging sessions.  
4. **Background jobs** spawning unbounded workers each with a pool.  
5. **Chaos after failover** — apps reconnect storm.

---

## Recommended remediation (ordered)

1. **Short term (with DBA):** terminate **safe** idle connections; scale **read** capacity; **restrict** new deploys that add replicas.  
2. **App:** scale **in** temporarily if leak suspected on new version + **rollback** if deploy-correlated.  
3. **Fix config:** reduce per-pod pool max, add **RDS Proxy** / PgBouncer, raise `max_connections` only after capacity planning (CPU/memory per conn).  
4. **Code:** fix leaks, shorten transactions, add **connection timeout** and **backoff** on errors.

---

## Escalation criteria

- **Writer** saturated — risk to all services.  
- **Cannot reduce** connections without killing critical workloads — page DBA + leadership.  
- **Data risk** from mass kill of sessions — get DBA approval on who to terminate.

---

## Communication and status updates

DB incidents are **multi-team**; designate **DBA + app** pairing in ticket; avoid unilateral `max_connections` changes without review.

---

## Recovery verification

- [ ] App pool wait **near zero** under normal load.  
- [ ] DB connections **below** threshold with headroom (e.g. 70–80% of max).  
- [ ] 5xx and latency recovered.

---

## Post-incident

- [ ] **Formula** in service catalog: max_replicas × pool_max ≤ budget.  
- [ ] CI check or doc for pool changes on replica scale events.  
- [ ] Consider **RDS Proxy** for serverless or high churn workloads.

---

## Evidence to capture

DB connection graph by app, pool metrics per deployment, `pg_stat_activity` / MySQL `SHOW PROCESSLIST` snapshot (redacted), deploy timeline.

---

## Metadata for RAG / automation

```yaml
runbook_id: RB-DB-CONN-004
service: rdbms_clients
symptoms: [too_many_connections, pool_exhausted, db_timeout, 5xx_with_db_errors]
environments: [production]
tags: [database, postgres, mysql, rds, connection_pool, aurora]
related_runbooks: [runbook-03-http-5xx-spike, runbook-09-queue-backlog-worker-lag]
```
