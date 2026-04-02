"""Triage HTML card helpers for Gradio."""

from app.ui.triage_display import (
    confidence_bar,
    format_triage_card,
    severity_badge,
)


def test_severity_badge_critical() -> None:
    h = severity_badge("CRITICAL")
    assert "CRITICAL" in h
    assert "#7f1d1d" in h or "critical" in h.lower() or "CRITICAL" in h


def test_confidence_bar_bounds() -> None:
    assert "100%" in confidence_bar(1.0)
    assert "0%" in confidence_bar(0.0) or "width:0%" in confidence_bar(0.0)


def test_format_triage_card_sections() -> None:
    out = {
        "triage_id": "00000000-0000-4000-8000-000000000001",
        "incident_summary": "CPU high",
        "service_name": "pay",
        "severity": "HIGH",
        "likely_root_cause": "Saturation",
        "recommended_actions": ["Scale"],
        "escalate": True,
        "confidence": 0.82,
        "evidence": [
            {"type": "log", "source": "a.log", "reason": "cpu line"},
            {"type": "incident", "source": "i.md", "reason": "similar"},
            {"type": "metric", "source": "m", "reason": "cpu 90"},
            {"type": "runbook", "source": "rb.md", "reason": "steps"},
        ],
        "timeline": ["T+0 alert"],
    }
    html = format_triage_card(out)
    assert "CPU high" in html
    assert "Saturation" in html
    assert "Scale" in html
    assert "Logs" in html or "log" in html.lower()
    assert "Incidents" in html or "incident" in html.lower()
    assert "00000000-0000-4000-8000-000000000001" in html
    assert "Timeline" in html
