"""HTML structure for elite Gradio triage view (severity, confidence bar, evidence groups)."""

from __future__ import annotations

import html
import json
from typing import Any

_SEVERITY_STYLES: dict[str, tuple[str, str]] = {
    "CRITICAL": ("#7f1d1d", "#fecaca"),
    "HIGH": ("#9a3412", "#fed7aa"),
    "MEDIUM": ("#854d0e", "#fef08a"),
    "LOW": ("#14532d", "#bbf7d0"),
}


def _escape(s: Any) -> str:
    return html.escape(str(s), quote=True)


def severity_badge(severity: str) -> str:
    sev = (severity or "LOW").upper()
    fg, bg = _SEVERITY_STYLES.get(sev, ("#374151", "#e5e7eb"))
    return (
        f'<span style="display:inline-block;padding:4px 14px;border-radius:999px;'
        f"font-weight:700;font-size:12px;letter-spacing:0.04em;"
        f"color:{fg};background:{bg};border:1px solid {fg}22;"
        f'">{_escape(sev)}</span>'
    )


def confidence_bar(confidence: float | None) -> str:
    try:
        c = float(confidence if confidence is not None else 0.0)
    except (TypeError, ValueError):
        c = 0.0
    c = max(0.0, min(1.0, c))
    pct = int(round(c * 100))
    if c < 0.45:
        bar = "linear-gradient(90deg,#ef4444,#f97316)"
        label_color = "#b91c1c"
    elif c < 0.75:
        bar = "linear-gradient(90deg,#f59e0b,#eab308)"
        label_color = "#a16207"
    else:
        bar = "linear-gradient(90deg,#22c55e,#16a34a)"
        label_color = "#15803d"
    return f"""
<div style="margin:12px 0 8px 0;font-family:system-ui,sans-serif;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
    <span style="font-weight:600;color:#374151;font-size:13px;">Confidence</span>
    <span style="font-weight:700;color:{label_color};font-size:14px;">{pct}%</span>
  </div>
  <div style="background:#e5e7eb;border-radius:10px;height:14px;overflow:hidden;box-shadow:inset 0 1px 2px #0001;">
    <div style="width:{pct}%;height:100%;background:{bar};border-radius:10px;transition:width 0.35s ease;"></div>
  </div>
</div>
""".strip()


def _group_evidence(items: list[Any]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "logs": [],
        "incidents": [],
        "metrics": [],
        "knowledge": [],
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        t = str(item.get("type") or "other").lower()
        if t == "log":
            groups["logs"].append(item)
        elif t == "incident":
            groups["incidents"].append(item)
        elif t in ("metric", "alert"):
            groups["metrics"].append(item)
        else:
            groups["knowledge"].append(item)
    return groups


def _evidence_li(e: dict[str, Any]) -> str:
    src = _escape(e.get("source", ""))
    reason = _escape(e.get("reason", ""))
    return (
        f'<li style="margin:8px 0;line-height:1.45;">'
        f'<code style="background:#f3f4f6;padding:2px 6px;border-radius:4px;font-size:12px;">{src}</code>'
        f"<br/><span style=\"color:#4b5563;font-size:13px;\">{reason}</span></li>"
    )


def evidence_sections_html(evidence: list[Any]) -> str:
    g = _group_evidence(evidence)
    titles = [
        ("logs", "Logs", "Log lines and log-derived retrieval"),
        ("incidents", "Incidents", "Past incidents and narratives"),
        ("metrics", "Metrics & alerts", "Metrics, SLOs, and alert context"),
        ("knowledge", "Runbooks & knowledge", "Runbooks, docs, and other sources"),
    ]
    parts: list[str] = []
    for key, title, hint in titles:
        items = g.get(key) or []
        if not items:
            continue
        inner = "<ul style=\"margin:0;padding-left:20px;list-style:disc;\">" + "".join(_evidence_li(i) for i in items) + "</ul>"
        parts.append(
            f"<details style=\"margin:10px 0;border:1px solid #e5e7eb;border-radius:10px;padding:0 14px;background:#fafafa;\">"
            f"<summary style=\"cursor:pointer;padding:12px 0;font-weight:600;color:#111827;\">"
            f"{_escape(title)} <span style=\"color:#6b7280;font-weight:500;font-size:12px;\">({len(items)}) · {_escape(hint)}</span>"
            f"</summary><div style=\"padding:0 0 14px 4px;\">{inner}</div></details>"
        )
    if not parts:
        return '<p style="color:#6b7280;font-size:13px;">No structured evidence rows.</p>'
    return f'<div style="font-family:system-ui,sans-serif;">{"".join(parts)}</div>'


def format_triage_card(out: dict[str, Any]) -> str:
    """Rich HTML card: badge, confidence bar, sections, collapsible evidence."""
    summary = _escape(out.get("incident_summary") or "")
    svc = _escape(out.get("service_name") or "—")
    sev = str(out.get("severity") or "LOW")
    root = _escape(out.get("likely_root_cause") or "")
    actions = out.get("recommended_actions") or []
    if not isinstance(actions, list):
        actions = []
    action_lis = "".join(
        f'<li style="margin:10px 0;padding-left:4px;line-height:1.5;color:#1f2937;">{_escape(a)}</li>'
        for a in actions
        if a
    )
    esc = bool(out.get("escalate"))
    conf_html = confidence_bar(out.get("confidence"))
    badge = severity_badge(sev)
    ev = out.get("evidence") if isinstance(out.get("evidence"), list) else []
    ev_html = evidence_sections_html(ev)
    conflict = out.get("conflicting_signals_summary")
    conflict_blk = ""
    if conflict:
        conflict_blk = (
            f'<div style="margin-top:14px;padding:12px;background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;">'
            f'<strong style="color:#92400e;">Conflicting signals</strong>'
            f'<p style="margin:6px 0 0;color:#78350f;font-size:13px;">{_escape(conflict)}</p></div>'
        )
    tid = _escape(out.get("triage_id") or "")

    return f"""
<div style="max-width:820px;font-family:system-ui,-apple-system,sans-serif;color:#111827;">
  <div style="display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-bottom:16px;">
    {badge}
    <span style="color:#6b7280;font-size:13px;">Service · <strong style="color:#111827;">{svc}</strong></span>
    <span style="color:#6b7280;font-size:13px;">Escalate · <strong style="color:{'#b45309' if esc else '#6b7280'};">{'yes' if esc else 'no'}</strong></span>
  </div>
  {conf_html}
  <h2 style="font-size:15px;font-weight:700;margin:22px 0 8px;color:#374151;text-transform:uppercase;letter-spacing:0.06em;">Summary</h2>
  <p style="margin:0;line-height:1.6;font-size:15px;color:#1f2937;">{summary}</p>
  <h2 style="font-size:15px;font-weight:700;margin:22px 0 8px;color:#374151;text-transform:uppercase;letter-spacing:0.06em;">Likely root cause</h2>
  <p style="margin:0;line-height:1.6;font-size:15px;color:#374151;">{root}</p>
  <h2 style="font-size:15px;font-weight:700;margin:22px 0 10px;color:#374151;text-transform:uppercase;letter-spacing:0.06em;">Recommended actions</h2>
  <ol style="margin:0;padding-left:22px;">{action_lis}</ol>
  {_timeline_block(out.get("timeline"))}
  {conflict_blk}
  <h2 style="font-size:15px;font-weight:700;margin:24px 0 10px;color:#374151;text-transform:uppercase;letter-spacing:0.06em;">Evidence</h2>
  {ev_html}
  <p style="margin-top:20px;font-size:12px;color:#9ca3af;">triage_id · <code style="background:#f3f4f6;padding:2px 8px;border-radius:4px;">{tid}</code></p>
</div>
""".strip()


def pretty_json(out: dict[str, Any]) -> str:
    return json.dumps(out, indent=2, ensure_ascii=False)


def _timeline_block(timeline: Any) -> str:
    if not isinstance(timeline, list) or not timeline:
        return ""
    items = "".join(
        f'<li style="margin:8px 0;color:#374151;font-size:14px;">{_escape(t)}</li>'
        for t in timeline
        if t and str(t).strip()
    )
    if not items:
        return ""
    return (
        '<h2 style="font-size:15px;font-weight:700;margin:22px 0 8px;color:#374151;'
        'text-transform:uppercase;letter-spacing:0.06em;">Timeline</h2>'
        f'<ol style="margin:0;padding-left:22px;">{items}</ol>'
    )
