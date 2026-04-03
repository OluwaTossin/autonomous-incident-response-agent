"""Deterministic guardrails after LLM triage (environment, blast radius)."""

from __future__ import annotations

from typing import Any

_NON_PROD_ENVS = frozenset(
    {
        "development",
        "dev",
        "staging",
        "local",
        "test",
        "sandbox",
        "nonprod",
        "non-prod",
        "nonproduction",
    }
)


def _environment_lower(incident: dict[str, Any]) -> str:
    return str(incident.get("environment") or incident.get("env") or "").strip().lower()


def _incident_text_blob(incident: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in (
        "alert_title",
        "alertTitle",
        "title",
        "service_name",
        "serviceName",
        "service",
        "environment",
        "env",
        "logs",
        "log_excerpt",
        "logExcerpt",
        "metric_summary",
        "metricSummary",
        "metrics_snapshot",
        "metricsSnapshot",
    ):
        v = incident.get(k)
        if v is not None and str(v).strip():
            parts.append(str(v))
    return " ".join(parts).lower()


def _prod_checkout_payment_critical(blob: str) -> bool:
    if not any(k in blob for k in ("payment", "checkout")):
        return False
    impact_markers = (
        "revenue",
        "abandoned_cart",
        "abandoned cart",
        "payment_error",
        "payment provider",
        "payment_provider",
        "settlement",
        "capture",
    )
    return any(m in blob for m in impact_markers)


def _dev_lab_noise(blob: str) -> bool:
    return any(
        n in blob
        for n in (
            "localhost",
            "laptop",
            "dev-metric",
            "metric-agent",
            "scrape failed",
            "scraped",
        )
    )


def apply_operational_policy(incident: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    """
    Adjust severity/escalation for environments and clear business-impact signals.

    Non-production: do not escalate on-call; cap HIGH/CRITICAL to MEDIUM so staging/dev
    noise does not look like outages. Development lab/scrape flaps → LOW when obvious.

    Production: payment/checkout + revenue or error-rate style impact → at least CRITICAL
    with escalate (matches typical SEV-1 / payment ops practice).
    """
    if not draft or not isinstance(draft, dict):
        return draft
    env = _environment_lower(incident)
    blob = _incident_text_blob(incident)
    out = dict(draft)
    sev = str(out.get("severity", "MEDIUM")).upper()

    if env in _NON_PROD_ENVS:
        out["escalate"] = False
        if sev == "CRITICAL":
            out["severity"] = "MEDIUM"
            sev = "MEDIUM"
        elif sev == "HIGH":
            out["severity"] = "MEDIUM"
            sev = "MEDIUM"
        if env in ("development", "dev") and _dev_lab_noise(blob):
            out["severity"] = "LOW"
            out["escalate"] = False
            sev = "LOW"

    if env == "production" and _prod_checkout_payment_critical(blob):
        out["severity"] = "CRITICAL"
        out["escalate"] = True

    return out
