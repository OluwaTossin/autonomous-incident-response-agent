"""Shared triage run used by REST and the Phase 7 Gradio UI."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from app.agent.graph import run_triage_with_audit
from app.api.audit import append_triage_jsonl
from app.api.metrics_log import write_triage_metrics_line


def run_full_triage(incident: dict[str, Any]) -> dict[str, Any]:
    """
    Run graph, append audit line, return triage dict including ``triage_id``.

    ``incident`` must already match the validated incident schema (e.g. from ``parse_incident_payload``).
    """
    triage_id = str(uuid4())
    t0 = time.perf_counter()
    result, audit_meta = run_triage_with_audit(incident)
    duration_ms = int((time.perf_counter() - t0) * 1000)
    result_out = {**result, "triage_id": triage_id}
    append_triage_jsonl(
        incident,
        result_out,
        triage_id=triage_id,
        rag_context=audit_meta.get("rag_context"),
        retrieval_hits=audit_meta.get("retrieval_hits"),
    )
    err = result.get("error")
    success = not err
    write_triage_metrics_line(
        {
            "event": "triage_metrics",
            "triage_id": triage_id,
            "duration_ms": duration_ms,
            "success": success,
            "severity": result.get("severity"),
            "escalate": bool(result.get("escalate")),
            "graph_error": bool(err),
            "tokens_total": None,
        }
    )
    return result_out
