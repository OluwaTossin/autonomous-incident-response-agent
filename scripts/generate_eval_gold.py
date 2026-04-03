#!/usr/bin/env python3
"""Generate data/eval/gold.jsonl (run from repo root: python scripts/generate_eval_gold.py)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "eval" / "gold.jsonl"


def line(
    id_: str,
    incident: dict,
    expect: dict | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> dict:
    row: dict = {"id": id_, "incident": incident, "expect": expect or {}}
    if tags:
        row["tags"] = tags
    if notes:
        row["notes"] = notes
    return row


# Broad retrieval hint so local runs with default index get non-None checks when index exists.
R = {"retrieval_source_contains_any": ["data/"], "min_top_retrieval_score": 0.05}


def strict(
    summary_kw: list[str] | None = None,
    root_kw: list[str] | None = None,
    extra: dict | None = None,
) -> dict:
    e = {**R}
    if summary_kw:
        e["summary_contains_all"] = summary_kw
    if root_kw:
        e["root_cause_contains_any"] = root_kw
    if extra:
        e.update(extra)
    return e


CASES: list[dict] = [
    # --- CPU variants ---
    line(
        "eval-cpu-payment-spike",
        {
            "alert_title": "High CPU on payment-api",
            "service_name": "payment-api",
            "environment": "production",
            "log_excerpt": "2024-01-15T10:00:00Z payment-api pid=4412 cpu=94% threads=80 gc_pause_ms=12",
            "metrics_snapshot": "cpu_percent: 94, request_rate: 1200/s, error_rate: 0.2%",
        },
        {**strict(["payment", "CPU"], ["CPU", "cpu"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["cpu"],
    ),
    line(
        "eval-cpu-checkout-throttle",
        {
            "alert_title": "Checkout workers saturated",
            "service_name": "checkout-service",
            "environment": "production",
            "log_excerpt": "queue_depth=5000 worker_pool=exhausted rejecting=15%",
            "metrics_snapshot": "cpu_percent: 88, latency_p99_ms: 4200",
        },
        # Summary: queue/worker reflect saturation without requiring literal "CPU" (models often say "compute").
        {**strict(["checkout", "queue"], ["worker", "queue"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["cpu", "capacity"],
    ),
    line(
        "eval-cpu-batch-job",
        {
            "alert_title": "Batch processor CPU sustained",
            "service_name": "batch-processor",
            "environment": "production",
            "log_excerpt": "job_id=8821 stage=transform cpu_avg=91% duration_exceeded=true",
            "metrics_snapshot": "cpu_percent: 91, batch_lag_minutes: 40",
        },
        {**strict(["batch", "CPU"], ["batch", "job"]), "severity_any_of": ["medium", "high"], "min_actions": 1},
        tags=["cpu"],
    ),
    line(
        "eval-cpu-node-noisy-neighbor",
        {
            "alert_title": "Node CPU high — possible noisy neighbor",
            "service_name": "shared-node-7",
            "environment": "production",
            "log_excerpt": "cgroup_throttle_events=1200 steal_time_ms=high",
            "metrics_snapshot": "cpu_percent: 92, container_count: 18",
        },
        {**strict(["CPU", "node"], ["CPU", "container"]), "severity_any_of": ["medium", "high"], "min_actions": 1},
        tags=["cpu", "ambiguous", "mixed_signals"],
        notes="CPU high but steal/throttle suggests host contention, not app bug.",
    ),
    line(
        "eval-cpu-gc-vs-hot-path",
        {
            "alert_title": "payment-api CPU spike",
            "service_name": "payment-api",
            "environment": "production",
            "log_excerpt": "gc_pause_ms=450 young_gen_full=true heap_used=98% but also hot_method=PricingEngine.apply",
            "metrics_snapshot": "cpu_percent: 96, gc_time_percent: 62",
        },
        {**strict(["payment", "CPU"], ["GC", "heap", "memory"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["cpu", "ambiguous", "mixed_signals"],
        notes="Logs mix GC pressure and hot code path — model should not pick only one without nuance.",
    ),
    # --- DB ---
    line(
        "eval-db-connection-pool",
        {
            "alert_title": "DB connection pool exhausted",
            "service_name": "orders-api",
            "environment": "production",
            "log_excerpt": "HikariPool - Connection is not available, request timed out after 30000ms",
            "metrics_snapshot": "db_conn_wait_ms: 28000, active_connections: 50/50",
        },
        # "database" is often paraphrased as Postgres/SQL/Hikari; require pool/connection terms from logs.
        {**strict(["connection", "pool"], ["connection", "pool", "database", "timeout"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["database"],
    ),
    line(
        "eval-db-replica-lag",
        {
            "alert_title": "Read replica lag critical",
            "service_name": "reporting-api",
            "environment": "production",
            "log_excerpt": "replica lag_sec=420 replication_slot=behind",
            "metrics_snapshot": "replica_lag_seconds: 420, read_qps: 800",
        },
        {**strict(["replica", "lag"], ["replica", "lag"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["database"],
    ),
    line(
        "eval-db-deadlock-hint",
        {
            "alert_title": "Spike in DB deadlocks",
            "service_name": "inventory-service",
            "environment": "production",
            "log_excerpt": "Deadlock found when trying to get lock; try restarting transaction",
            "metrics_snapshot": "deadlock_count_5m: 34, tx_duration_p99_ms: 8000",
        },
        # "transaction" is often omitted from summaries; "lock" still grounds the deadlock theme.
        {**strict(["deadlock", "lock"], ["deadlock", "lock"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["database"],
    ),
    line(
        "eval-db-migration-lock",
        {
            "alert_title": "Long-running migration holding lock",
            "service_name": "core-db",
            "environment": "production",
            "log_excerpt": "ALTER TABLE ... waiting for lock mode=AccessExclusive",
            "metrics_snapshot": "blocked_sessions: 120, lock_wait_sec_max: 900",
        },
        {**strict(["migration", "lock"], ["migration", "lock"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["database"],
    ),
    # --- Network ---
    line(
        "eval-net-tls-handshake",
        {
            "alert_title": "TLS handshake failures to upstream",
            "service_name": "edge-gateway",
            "environment": "production",
            "log_excerpt": "SSLHandshakeException: certificate_unknown upstream=api.partner.com",
            "metrics_snapshot": "tls_error_rate: 8%, upstream_latency_p99_ms: timeout",
        },
        {**strict(["TLS", "upstream"], ["TLS", "certificate", "upstream"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["network"],
    ),
    line(
        "eval-net-dns-flap",
        {
            "alert_title": "Intermittent DNS resolution failures",
            "service_name": "worker-fleet",
            "environment": "production",
            "log_excerpt": "UnknownHostException: payments.internal.svc.cluster.local",
            "metrics_snapshot": "dns_failures_per_min: 22",
        },
        {**strict(["DNS", "resolution"], ["DNS", "resolution"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["network"],
    ),
    line(
        "eval-net-packet-loss",
        {
            "alert_title": "Elevated packet loss AZ-b",
            "service_name": "multi-az-router",
            "environment": "production",
            "log_excerpt": "interface eth1 dropped=4.2% retransmits=high",
            "metrics_snapshot": "packet_loss_percent: 4.2, cross_az_latency_ms: 180",
        },
        {**strict(["packet", "loss"], ["packet", "loss", "network"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["network"],
    ),
    line(
        "eval-net-cdn-origin",
        {
            "alert_title": "CDN 502 from origin",
            "service_name": "static-cdn",
            "environment": "production",
            "log_excerpt": "origin_fetch_failed status=502 origin=assets.prod.internal",
            "metrics_snapshot": "origin_error_rate: 12%, cache_hit_ratio: 0.71",
        },
        {**strict(["CDN", "origin"], ["CDN", "origin"]), "severity_any_of": ["medium", "high"], "min_actions": 1},
        tags=["network"],
    ),
    # --- Auth ---
    line(
        "eval-auth-401-spike",
        {
            "alert_title": "401 rate spike on public API",
            "service_name": "public-api",
            "environment": "production",
            "log_excerpt": "401 Unauthorized invalid_token count=4500/min",
            "metrics_snapshot": "http_401_rate: 7%, valid_traffic_estimate: stable",
        },
        {**strict(["401", "token"], ["401", "token", "auth"]), "severity_any_of": ["medium", "high"], "min_actions": 1},
        tags=["auth"],
    ),
    line(
        "eval-auth-oauth-issuer",
        {
            "alert_title": "OAuth token validation errors",
            "service_name": "bff-web",
            "environment": "production",
            "log_excerpt": "issuer_mismatch expected=https://idp.corp/real got=https://idp.corp/staging",
            "metrics_snapshot": "oauth_validation_failures: 890/hr",
        },
        {**strict(["OAuth", "issuer"], ["OAuth", "issuer", "token"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["auth"],
    ),
    line(
        "eval-auth-429-vs-ddos",
        {
            "alert_title": "429 rate limit storm",
            "service_name": "api-gateway",
            "environment": "production",
            "log_excerpt": "rate_limit_exceeded client_id=partner_x AND client_id=unknown_bulk",
            "metrics_snapshot": "429_rate: 35%, distinct_clients: 12",
        },
        {**strict(["429", "rate"], ["429", "rate", "limit"]), "severity_any_of": ["medium", "high"], "min_actions": 1},
        tags=["auth", "ambiguous", "mixed_signals"],
        notes="Mix of legitimate partner and possible abuse — severity/escalation judgment matters.",
    ),
    line(
        "eval-auth-clock-skew",
        {
            "alert_title": "JWT not yet valid / skew",
            "service_name": "internal-api",
            "environment": "production",
            "log_excerpt": "nbf claim in future clock_skew_detected_ms=42000",
            "metrics_snapshot": "jwt_validation_errors: 200/min",
        },
        {**strict(["JWT", "clock"], ["JWT", "clock", "skew"]), "severity_any_of": ["medium", "high"], "min_actions": 1},
        tags=["auth"],
    ),
    # --- Disk ---
    line(
        "eval-disk-volume-full",
        {
            "alert_title": "Disk usage critical /var",
            "service_name": "log-aggregator",
            "environment": "production",
            "log_excerpt": "No space left on device path=/var/log",
            "metrics_snapshot": "disk_used_percent: 99, inode_used_percent: 22",
        },
        {**strict(["disk", "space"], ["disk", "space", "volume"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["disk"],
    ),
    line(
        "eval-disk-inode-exhausted",
        {
            "alert_title": "Inode exhaustion on temp volume",
            "service_name": "job-runner",
            "environment": "production",
            "log_excerpt": "cannot create temp file: no space left on device (inode)",
            "metrics_snapshot": "inode_used_percent: 100, disk_used_percent: 62",
        },
        # Models often say "inodes" / "filesystem" without the word "disk".
        {**strict(["inode", "file"], ["inode", "disk", "filesystem", "storage"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["disk", "ambiguous", "mixed_signals"],
        notes="Classic misleading: disk % ok but inodes full.",
    ),
    line(
        "eval-disk-nfs-stale",
        {
            "alert_title": "NFS stale file handle errors",
            "service_name": "media-worker",
            "environment": "production",
            "log_excerpt": "ESTALE Stale NFS file handle mount=/mnt/shared",
            "metrics_snapshot": "nfs_error_rate: 5%",
        },
        {**strict(["NFS", "stale"], ["NFS", "stale", "file"]), "severity_any_of": ["medium", "high"], "min_actions": 1},
        tags=["disk", "network"],
    ),
    # --- Misleading / partial logs ---
    line(
        "eval-mis-cpu-alert-db-root",
        {
            "alert_title": "CPU high on api-tier",
            "service_name": "catalog-api",
            "environment": "production",
            "log_excerpt": "slow query detected duration=38s waiting on row lock catalog.products",
            "metrics_snapshot": "cpu_percent: 90, db_wait_time_percent: 78",
        },
        {**strict(["query", "lock"], ["database", "query", "lock", "sql", "postgres"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["misleading_alert", "database"],
        notes="Alert says CPU; dominant wait is DB — root cause should lean DB, not CPU tuning only.",
    ),
    line(
        "eval-mis-p99-cache-stampede",
        {
            "alert_title": "p99 latency regression",
            "service_name": "home-feed",
            "environment": "production",
            "log_excerpt": "cache_miss_storm key_prefix=user_feed rebuild_in_progress=true",
            "metrics_snapshot": "p99_ms: 8200, cache_hit: 0.12",
        },
        {**strict(["cache", "latency"], ["cache", "miss", "latency"]), "severity_any_of": ["high", "critical"], "min_actions": 1},
        tags=["misleading_alert", "partial_logs"],
        notes="Generic latency alert; logs show cache stampede.",
    ),
    line(
        "eval-partial-thin-logs",
        {
            "alert_title": "Service unhealthy",
            "service_name": "unknown-worker",
            "environment": "staging",
            "log_excerpt": "ERROR",
            "metrics_snapshot": "health_check: failing",
        },
        {**strict(["staging", "health"], ["health", "unknown"]), "severity_any_of": ["low", "medium"], "min_actions": 1, "escalate": False},
        tags=["partial_logs", "thin_signal"],
        notes="Minimal evidence — expect conservative actions and no blind escalation.",
    ),
    # --- Escalation traps ---
    line(
        "eval-trap-staging-low-no-escalate",
        {
            "alert_title": "Staging pod restart loop",
            "service_name": "feature-flags-staging",
            "environment": "staging",
            "log_excerpt": "CrashLoopBackOff staging only",
            "metrics_snapshot": "restart_count: 8",
        },
        # root_cause_contains_any is OR; add K8s synonyms models use instead of "restart".
        {
            **strict(
                ["staging", "CrashLoop"],
                ["staging", "restart", "crashloop", "crash", "pod", "feature"],
            ),
            "severity_any_of": ["low", "medium"],
            "min_actions": 1,
            "escalate": False,
        },
        tags=["under_escalate_trap", "over_escalate_risk"],
        notes="Gold: do NOT escalate staging noise; over-escalation should fail escalate check.",
    ),
    line(
        "eval-trap-prod-revenue-escalate",
        {
            "alert_title": "Checkout payment failures climbing",
            "service_name": "checkout-service",
            "environment": "production",
            "log_excerpt": "payment_provider timeout errors=12% revenue_impact_estimated=true",
            "metrics_snapshot": "payment_error_rate: 12%, abandoned_carts: spike",
        },
        {**strict(["payment", "checkout"], ["payment", "checkout", "revenue"]), "severity_any_of": ["critical"], "min_actions": 2, "escalate": True},
        tags=["under_escalate_trap"],
        notes="Gold: must escalate and be CRITICAL — under-escalation fails.",
    ),
    line(
        "eval-trap-sev-too-low-bad",
        {
            "alert_title": "Primary DB failover in progress",
            "service_name": "core-db",
            "environment": "production",
            "log_excerpt": "automatic_failover initiated new_primary=db-replica-2",
            "metrics_snapshot": "write_errors: spike, rto_timer: active",
        },
        {
            **strict(
                ["failover", "primary"],
                ["failover", "primary", "database", "replica", "writer"],
            ),
            "severity_any_of": ["critical"],
            "min_actions": 2,
            "escalate": True,
        },
        tags=["under_escalate_trap"],
        notes="Treating as low/med severity should fail severity_any_of.",
    ),
    line(
        "eval-trap-over-escalate-wrong",
        {
            "alert_title": "Dev laptop metric agent flapping",
            "service_name": "dev-metric-agent",
            "environment": "development",
            "log_excerpt": "localhost scrape failed intermittently",
            "metrics_snapshot": "cpu_percent: noisy",
        },
        {**strict(["development", "localhost"], ["development", "dev"]), "severity_any_of": ["low"], "min_actions": 1, "escalate": False},
        tags=["over_escalate_risk"],
        notes="Gold: never CRITICAL/on-call; over-escalation fails escalate=True or severity.",
    ),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for c in CASES:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"Wrote {len(CASES)} cases to {OUT}")


if __name__ == "__main__":
    main()
