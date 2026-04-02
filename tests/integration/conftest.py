"""Integration tests: do not append to data/logs/triage_outputs.jsonl by default."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def disable_triage_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_AUDIT_DISABLE", "1")


@pytest.fixture(autouse=True)
def disable_n8n_workflow_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("N8N_WORKFLOW_LOG_DISABLE", "1")
