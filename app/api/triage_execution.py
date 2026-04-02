"""Shared triage run used by REST and the Phase 7 Gradio UI."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.agent.graph import run_triage_with_audit
from app.api.audit import append_triage_jsonl


def run_full_triage(incident: dict[str, Any]) -> dict[str, Any]:
    """
    Run graph, append audit line, return triage dict including ``triage_id``.

    ``incident`` must already match the validated incident schema (e.g. from ``parse_incident_payload``).
    """
    triage_id = str(uuid4())
    result, audit_meta = run_triage_with_audit(incident)
    result_out = {**result, "triage_id": triage_id}
    append_triage_jsonl(
        incident,
        result_out,
        triage_id=triage_id,
        rag_context=audit_meta.get("rag_context"),
        retrieval_hits=audit_meta.get("retrieval_hits"),
    )
    return result_out
