"""Compatibility entry point used by REST and the Version 2 Gradio UI."""

from __future__ import annotations

from typing import Any

from app.agent.graph import run_triage_with_audit
from app.composition.self_hosted import build_self_hosted_triage


def run_full_triage(incident: dict[str, Any]) -> dict[str, Any]:
    """Run the explicit self-hosted composition and preserve the V2 result contract."""
    return build_self_hosted_triage(pipeline=run_triage_with_audit).run(incident)
