"""Version 2 self-hosted triage composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.agent.graph import run_triage_with_audit
from app.application.triage import TriageExecution, TriagePipeline, execute_triage
from app.config import get_settings


class TriageAuditSink(Protocol):
    def record(
        self,
        incident: dict[str, Any],
        execution: TriageExecution,
    ) -> None: ...


class TriageMetricsSink(Protocol):
    def record(self, execution: TriageExecution) -> None: ...


@dataclass(frozen=True)
class JsonlTriageAuditSink:
    """Persist the current self-hosted append-only triage audit record."""

    def record(
        self,
        incident: dict[str, Any],
        execution: TriageExecution,
    ) -> None:
        from app.api.audit import append_triage_jsonl

        append_triage_jsonl(
            incident,
            execution.result,
            triage_id=execution.triage_id,
            rag_context=execution.metadata.get("rag_context"),
            retrieval_hits=execution.metadata.get("retrieval_hits"),
        )


@dataclass(frozen=True)
class StructuredTriageMetricsSink:
    """Emit the existing self-hosted structured triage metric line."""

    stack_environment: str

    def record(self, execution: TriageExecution) -> None:
        from app.api.metrics_log import write_triage_metrics_line

        result = execution.result
        error = result.get("error")
        success = not error
        raw_usage = execution.metadata.get("llm_usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        tokens_prompt = int(usage.get("tokens_prompt") or 0)
        tokens_completion = int(usage.get("tokens_completion") or 0)
        tokens_total = int(usage.get("tokens_total") or 0)
        raw_severity = result.get("severity")
        severity_metric = (
            str(raw_severity).strip().upper()
            if raw_severity is not None and str(raw_severity).strip()
            else "UNKNOWN"
        )
        escalate = bool(result.get("escalate"))
        write_triage_metrics_line(
            {
                "log_schema": "aira.triage.v1",
                "event": "triage_metrics",
                "triage_id": execution.triage_id,
                "stack_environment": self.stack_environment,
                "outcome": "success" if success else "graph_error",
                "duration_ms": execution.duration_ms,
                "success": success,
                "severity": result.get("severity"),
                "severity_metric": severity_metric,
                "escalate": escalate,
                "escalate_str": "true" if escalate else "false",
                "graph_error": bool(error),
                "tokens_prompt": tokens_prompt,
                "tokens_completion": tokens_completion,
                "tokens_total": tokens_total,
            }
        )


@dataclass(frozen=True)
class SelfHostedTriage:
    """Compose current LangGraph, JSONL audit, and structured metrics adapters."""

    pipeline: TriagePipeline
    audit_sink: TriageAuditSink
    metrics_sink: TriageMetricsSink

    def run(self, incident: dict[str, Any]) -> dict[str, Any]:
        execution = execute_triage(incident, pipeline=self.pipeline)
        self.audit_sink.record(incident, execution)
        self.metrics_sink.record(execution)
        return execution.result


def build_self_hosted_triage(
    *,
    pipeline: TriagePipeline = run_triage_with_audit,
) -> SelfHostedTriage:
    """Build the filesystem/configuration-backed Version 2 composition."""
    stack_environment = get_settings().aira_env.strip() or "local"
    return SelfHostedTriage(
        pipeline=pipeline,
        audit_sink=JsonlTriageAuditSink(),
        metrics_sink=StructuredTriageMetricsSink(stack_environment),
    )
