"""Operational policy guardrails (non-prod dampening, prod payment critical)."""

from __future__ import annotations

from app.agent.operational_policy import apply_operational_policy


def test_staging_high_becomes_medium_no_escalate() -> None:
    incident = {
        "environment": "staging",
        "alert_title": "CrashLoopBackOff",
        "service_name": "feature-flags-staging",
        "logs": "staging only",
    }
    draft = {"severity": "HIGH", "escalate": True}
    out = apply_operational_policy(incident, draft)
    assert out["severity"] == "MEDIUM"
    assert out["escalate"] is False


def test_development_metric_agent_low() -> None:
    incident = {
        "environment": "development",
        "service_name": "dev-metric-agent",
        "logs": "localhost scrape failed",
    }
    draft = {"severity": "MEDIUM", "escalate": True}
    out = apply_operational_policy(incident, draft)
    assert out["severity"] == "LOW"
    assert out["escalate"] is False


def test_production_checkout_revenue_critical() -> None:
    incident = {
        "environment": "production",
        "service_name": "checkout-service",
        "metric_summary": "payment_error_rate: 12%, abandoned_carts: spike",
        "logs": "payment_provider timeout revenue_impact_estimated=true",
    }
    draft = {"severity": "HIGH", "escalate": True}
    out = apply_operational_policy(incident, draft)
    assert out["severity"] == "CRITICAL"
    assert out["escalate"] is True


def test_production_unrelated_unchanged_by_payment_rule() -> None:
    incident = {
        "environment": "production",
        "service_name": "static-cdn",
        "logs": "origin 502",
    }
    draft = {"severity": "MEDIUM", "escalate": False}
    out = apply_operational_policy(incident, draft)
    assert out["severity"] == "MEDIUM"
    assert out["escalate"] is False
