"""Deterministic evidence, contradiction detection, and timeline extraction."""

from __future__ import annotations

import os
import re
from typing import Any

# doc_type from index → EvidenceItem.type
_DOC_TYPE_MAP: dict[str, str] = {
    "runbook": "runbook",
    "incident": "incident",
    "log": "log",
    "knowledge": "knowledge",
    "decision": "decision",
}


def _map_evidence_type(doc_type: str) -> str:
    dt = (doc_type or "").strip().lower()
    return _DOC_TYPE_MAP.get(dt, "other")


def _norm_source_key(source: str) -> str:
    s = (source or "").strip().replace("\\", "/")
    return os.path.basename(s).lower() if s else ""


def evidence_from_retrieval_dicts(hit_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One evidence row per unique (evidence_type, source), merging multi-chunk hits."""
    buckets: dict[tuple[str, str], float] = {}
    counts: dict[tuple[str, str], int] = {}
    for h in hit_dicts:
        source = str(h.get("source") or "").strip()
        if not source:
            continue
        et = _map_evidence_type(str(h.get("doc_type") or ""))
        try:
            score = float(h.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        key = (et, source)
        buckets[key] = max(buckets.get(key, 0.0), score)
        counts[key] = counts.get(key, 0) + 1

    items: list[dict[str, Any]] = []
    for (etype, source), score in sorted(buckets.items(), key=lambda x: -x[1]):
        n = counts[(etype, source)]
        reason = f"Retrieved from knowledge index (similarity={score:.3f})"
        if n > 1:
            reason += f"; {n} chunks matched this source"
        items.append({"type": etype, "source": source, "reason": reason})
    return items


def merge_evidence_lists(
    programmatic: list[dict[str, Any]],
    from_llm: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Programmatic rows first; append LLM rows that are not duplicates by (type, basename source)."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []

    for row in programmatic:
        t = str(row.get("type") or "other").lower()
        sk = _norm_source_key(str(row.get("source") or ""))
        key = (t, sk)
        if sk and key in seen:
            continue
        if sk:
            seen.add(key)
        out.append(row)

    for row in from_llm:
        if not isinstance(row, dict):
            continue
        src = str(row.get("source") or "").strip()
        reason = str(row.get("reason") or "").strip()
        if not src or not reason:
            continue
        t_raw = str(row.get("type") or "other").strip().lower()
        et = t_raw if t_raw in _ALLOWED_EVIDENCE_TYPES else "other"
        key = (et, _norm_source_key(src))
        if key in seen:
            continue
        seen.add(key)
        out.append({"type": et, "source": src, "reason": reason})
    return out


# --- Contradiction heuristics (multi-cause / competing narratives) ---

_SIGNAL_DEFS: list[tuple[str, re.Pattern[str]]] = [
    ("cpu", re.compile(r"high\s*cpu|cpu\s+spike|cpu\s+saturation|\bcpu\b.*\d{2,}\s*%|throttl", re.I)),
    ("db_conn", re.compile(r"connection\s+exhaust|pool\s+exhaust|too\s+many\s+connections|db\s+conn|rds\s+conn", re.I)),
    ("memory", re.compile(r"\boom\b|out\s+of\s+memory|memory\s+leak|heap\s+pressure|oomkill", re.I)),
    ("disk", re.compile(r"disk\s+full|enospc|no\s+space|inode\s+exhaust|storage\s+full", re.I)),
    ("network", re.compile(r"\b504\b|gateway\s+timeout|latency\s+spike|timeout\s+cascade|network\s+error", re.I)),
    ("tls", re.compile(r"cert(ificate)?\s+expir|tls\s+handshake|ssl\s+error|mtls", re.I)),
]


def _incident_text_blob(incident: dict[str, Any]) -> str:
    parts = [
        str(incident.get("alert_title") or ""),
        str(incident.get("metric_summary") or ""),
        str(incident.get("logs") or ""),
    ]
    return " ".join(parts)


def active_signal_tags(incident: dict[str, Any]) -> frozenset[str]:
    blob = _incident_text_blob(incident)
    found: set[str] = set()
    for name, rx in _SIGNAL_DEFS:
        if rx.search(blob):
            found.add(name)
    return frozenset(found)


def detect_conflicting_signals(incident: dict[str, Any]) -> str | None:
    """
    Return a fixed message when multiple competing failure families are present.
    Pairs are chosen to match common multi-cause scenarios (e.g. CPU + DB pool).
    """
    active = active_signal_tags(incident)
    if len(active) < 2:
        return None

    pairs: list[tuple[frozenset[str], str]] = [
        (
            frozenset({"cpu", "db_conn"}),
            "Conflicting signals detected: CPU or compute pressure appears alongside database "
            "connection stress; consider amplification or a multi-cause incident.",
        ),
        (
            frozenset({"cpu", "memory"}),
            "Conflicting signals detected: CPU and memory pressure both present; "
            "verify whether load, leaks, or cgroup limits explain both.",
        ),
        (
            frozenset({"db_conn", "disk"}),
            "Conflicting signals detected: database pressure co-occurs with disk or storage signals; "
            "check logs, replication, and disk I/O together.",
        ),
        (
            frozenset({"network", "tls"}),
            "Conflicting signals detected: network or latency symptoms overlap with TLS/certificate "
            "issues; validate chain expiry and upstream connectivity.",
        ),
    ]
    for need, msg in pairs:
        if need.issubset(active):
            return msg

    return (
        "Conflicting signals detected. Multiple distinct failure families appear in the payload "
        "(metrics, logs, or title); treat as a possible multi-cause incident until narrowed."
    )


# --- Timeline ---

_ISO_FULL = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)\b"
)
_ISO_MIN = re.compile(r"\b(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2})\b")
_REL_MARKERS = re.compile(r"T[+-]\d+[msh]?", re.I)

_ALLOWED_EVIDENCE_TYPES = frozenset(
    {"log", "incident", "runbook", "knowledge", "decision", "metric", "alert", "other"}
)


def _extract_iso_timestamps(text: str) -> list[str]:
    found: set[str] = set()
    for rx in (_ISO_FULL, _ISO_MIN):
        for m in rx.finditer(text):
            found.add(m.group(1).replace(" ", "T"))
    return sorted(found)


def build_programmatic_timeline(incident: dict[str, Any]) -> list[str]:
    """Anchor from payload time field; add ISO-like and relative markers from logs/metrics."""
    lines: list[str] = []
    t0 = (
        str(incident.get("time_of_occurrence") or "")
        or str(incident.get("timestamp") or "")
        or str(incident.get("detected_at") or "")
    ).strip()
    if t0:
        lines.append(f"Condition / alert reference time: {t0}")

    blob = f"{incident.get('logs') or ''} {incident.get('metric_summary') or ''}"
    for ts in _extract_iso_timestamps(blob):
        lines.append(f"Timestamp observed in logs or metrics: {ts}")

    for m in _REL_MARKERS.finditer(str(incident.get("logs") or "")):
        lines.append(f"Relative sequence marker: {m.group(0)}")

    return lines


def merge_timelines(programmatic: list[str], from_llm: list[str]) -> list[str]:
    """Programmatic first; append LLM strings not already represented (normalized)."""
    norm_seen: set[str] = set()
    out: list[str] = []

    for line in programmatic:
        s = str(line).strip()
        if not s:
            continue
        k = s.lower()
        if k in norm_seen:
            continue
        norm_seen.add(k)
        out.append(s)

    for line in from_llm:
        s = str(line).strip()
        if not s:
            continue
        k = s.lower()
        if k in norm_seen:
            continue
        norm_seen.add(k)
        out.append(s)

    return out
