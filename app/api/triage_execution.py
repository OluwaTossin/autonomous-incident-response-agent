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
    usage = audit_meta.get("llm_usage") if isinstance(audit_meta.get("llm_usage"), dict) else {}
    tp = int(usage.get("tokens_prompt") or 0)
    tc = int(usage.get("tokens_completion") or 0)
    tt = int(usage.get("tokens_total") or 0)
    write_triage_metrics_line(
        {
            "log_schema": "aira.triage.v1",
            "event": "triage_metrics",
            "triage_id": triage_id,
            "outcome": "success" if success else "graph_error",
            "duration_ms": duration_ms,
            "success": success,
            "severity": result.get("severity"),
            "escalate": bool(result.get("escalate")),
            "graph_error": bool(err),
            "tokens_prompt": tp,
            "tokens_completion": tc,
            "tokens_total": tt,
        }
    )
    return result_out
